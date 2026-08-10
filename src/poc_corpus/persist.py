from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from poc_corpus.bundle import (
    BundleValidationError,
    EXPECTED_CORPUS_COUNT,
    load_expected_source_ids,
    validate_snapshot_manifest_bundle,
)
from poc_corpus.models import ManifestRow, SnapshotDocument
from poc_corpus.paths import (
    PathSafetyError,
    ensure_within,
    resolve_artifacts_staging_dir,
    safe_rmtree,
    snapshot_path_for,
)


MANIFEST_FIELDS = [
    "source_id",
    "title",
    "canonical_url",
    "content_selector",
    "topic_tags",
    "priority",
    "language",
    "publisher",
    "selection_status",
    "snapshot_status",
    "fetched_at",
    "sha256",
    "notes",
]


class PublishError(RuntimeError):
    pass


def read_manifest(path: Path) -> list[ManifestRow]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [ManifestRow.from_csv_row(row) for row in csv.DictReader(f)]


def write_manifest(path: Path, rows: list[ManifestRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.model_dump())
    tmp.replace(path)


def write_snapshot_json(path: Path, doc: SnapshotDocument) -> None:
    path = snapshot_path_for(path.parent, doc.source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = doc.model_dump(mode="json")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def clear_dir(path: Path, *, project_root: Path) -> None:
    if path.exists():
        safe_rmtree(path, project_root=project_root)
    path.mkdir(parents=True, exist_ok=True)


def assert_publish_paths_confined(
    *,
    project_root: Path,
    target_snapshots: Path,
    production_manifest: Path,
    backup_root: Path,
) -> None:
    """Confine target snapshots, production manifest, and backup root under the project."""
    root = project_root.resolve()
    snapshots_root = (root / "data" / "corpus" / "snapshots").resolve()
    corpus_root = (root / "data" / "corpus").resolve()
    backup_allowed = (root / "artifacts" / "publish_backup").resolve()

    try:
        ensure_within(snapshots_root, target_snapshots.resolve())
    except PathSafetyError as exc:
        raise PublishError(f"target_snapshots escapes data/corpus/snapshots: {exc}") from exc

    try:
        manifest_resolved = production_manifest.resolve()
        ensure_within(corpus_root, manifest_resolved)
    except PathSafetyError as exc:
        raise PublishError(f"production_manifest escapes data/corpus: {exc}") from exc
    if production_manifest.resolve().name != "corpus_manifest.csv":
        raise PublishError("production_manifest must be named corpus_manifest.csv")

    backup_resolved = backup_root.resolve()
    if backup_resolved != backup_allowed:
        try:
            ensure_within(backup_allowed, backup_resolved)
        except PathSafetyError as exc:
            raise PublishError(
                f"backup_root must be artifacts/publish_backup or under it: {exc}"
            ) from exc


def preflight_staged_bundle(
    *,
    project_root: Path,
    staging_snapshots: Path,
    staging_manifest: Path,
    expected_count: int = EXPECTED_CORPUS_COUNT,
) -> tuple[list[ManifestRow], list[SnapshotDocument]]:
    """Validate staged snapshots + manifest before any production mutation."""
    try:
        expected_ids = load_expected_source_ids(project_root)
    except BundleValidationError as exc:
        raise PublishError(str(exc)) from exc
    if expected_count != EXPECTED_CORPUS_COUNT:
        raise PublishError(f"expected_count must be {EXPECTED_CORPUS_COUNT}")
    try:
        return validate_snapshot_manifest_bundle(
            snapshots_dir=staging_snapshots,
            manifest_path=staging_manifest,
            expected_ids=expected_ids,
            require_snapshotted=True,
        )
    except BundleValidationError as exc:
        raise PublishError(str(exc)) from exc


@dataclass
class PublishTransactionResult:
    published: bool
    rolled_back: bool
    backup_dir: Path | None


def publish_staged_transaction(
    *,
    project_root: Path,
    staging_snapshots: Path,
    target_snapshots: Path,
    staging_manifest: Path,
    production_manifest: Path,
    backup_root: Path,
    expected_count: int = EXPECTED_CORPUS_COUNT,
    post_validate: bool = True,
) -> PublishTransactionResult:
    """
    Production publish always updates snapshots AND manifest in one transaction.
    Manifest is rolled back on any exception after mutation phase starts.
    """
    assert_publish_paths_confined(
        project_root=project_root,
        target_snapshots=target_snapshots,
        production_manifest=production_manifest,
        backup_root=backup_root,
    )
    # Preflight before any mutation
    preflight_staged_bundle(
        project_root=project_root,
        staging_snapshots=staging_snapshots,
        staging_manifest=staging_manifest,
        expected_count=expected_count,
    )

    backup_root.mkdir(parents=True, exist_ok=True)
    snap_backup = backup_root / "by_source.bak"
    manifest_backup = backup_root / "corpus_manifest.csv.bak"
    snapshots_replaced = False
    mutation_started = False

    try:
        mutation_started = True
        if snap_backup.exists():
            safe_rmtree(snap_backup, project_root=project_root)
        if target_snapshots.exists():
            shutil.copytree(target_snapshots, snap_backup)
        else:
            snap_backup.mkdir(parents=True, exist_ok=True)

        if production_manifest.exists():
            shutil.copy2(production_manifest, manifest_backup)

        target_snapshots.parent.mkdir(parents=True, exist_ok=True)
        tmp_target = target_snapshots.with_name(target_snapshots.name + ".new")
        if tmp_target.exists():
            safe_rmtree(tmp_target, project_root=project_root)
        shutil.copytree(staging_snapshots, tmp_target)

        old_target = target_snapshots.with_name(target_snapshots.name + ".old")
        if old_target.exists():
            safe_rmtree(old_target, project_root=project_root)
        if target_snapshots.exists():
            target_snapshots.rename(old_target)
        tmp_target.rename(target_snapshots)
        snapshots_replaced = True
        if old_target.exists():
            safe_rmtree(old_target, project_root=project_root)

        write_manifest(production_manifest, read_manifest(staging_manifest))

        if post_validate:
            expected_ids = load_expected_source_ids(project_root)
            validate_snapshot_manifest_bundle(
                snapshots_dir=target_snapshots,
                manifest_path=production_manifest,
                expected_ids=expected_ids,
                require_snapshotted=True,
            )

        return PublishTransactionResult(published=True, rolled_back=False, backup_dir=backup_root)
    except Exception as exc:
        try:
            if mutation_started:
                if snapshots_replaced or target_snapshots.exists():
                    if target_snapshots.exists():
                        safe_rmtree(target_snapshots, project_root=project_root)
                    if snap_backup.exists() and any(snap_backup.iterdir()):
                        shutil.copytree(snap_backup, target_snapshots)
                # Always restore manifest if backup exists once mutation started
                if manifest_backup.exists():
                    shutil.copy2(manifest_backup, production_manifest)
        except Exception as rollback_exc:
            raise PublishError(
                f"publish failed ({exc}); rollback also failed ({rollback_exc})"
            ) from rollback_exc
        raise PublishError(f"publish failed and rolled back: {exc}") from exc
