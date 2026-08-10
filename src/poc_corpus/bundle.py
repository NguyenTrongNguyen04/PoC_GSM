from __future__ import annotations

import csv
import json
from pathlib import Path

import yaml

from poc_corpus.checksum import sha256_text
from poc_corpus.models import ManifestRow, SnapshotDocument
from poc_corpus.paths import snapshot_path_for, validate_source_id


class BundleValidationError(ValueError):
    pass


EXPECTED_CORPUS_COUNT = 18
CONTRACT_PATH = Path("data/corpus/corpus_contract.yaml")


def _read_manifest(path: Path) -> list[ManifestRow]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [ManifestRow.from_csv_row(row) for row in csv.DictReader(f)]


def load_expected_source_ids(project_root: Path) -> list[str]:
    """Authoritative ordered source_id list from immutable corpus_contract.yaml."""
    path = project_root / CONTRACT_PATH
    if not path.exists():
        raise BundleValidationError(f"missing immutable corpus contract: {path}")
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    ids = list(doc.get("source_ids") or [])
    if len(ids) != EXPECTED_CORPUS_COUNT:
        raise BundleValidationError(
            f"corpus contract must have {EXPECTED_CORPUS_COUNT} source_ids, got {len(ids)}"
        )
    if len(set(ids)) != EXPECTED_CORPUS_COUNT:
        raise BundleValidationError("corpus contract source_id values must be unique")
    for sid in ids:
        validate_source_id(sid)
    return ids


def assert_contract_ids_immutable(project_root: Path, candidate_ids: list[str]) -> None:
    expected = load_expected_source_ids(project_root)
    if candidate_ids != expected:
        raise BundleValidationError(
            "source_id list diverges from immutable corpus contract: "
            f"only_in_candidate={sorted(set(candidate_ids) - set(expected))} "
            f"only_in_contract={sorted(set(expected) - set(candidate_ids))}"
        )


def _align_metadata(row: ManifestRow, doc: SnapshotDocument) -> list[str]:
    errors: list[str] = []
    checks = [
        ("title", row.title, doc.title),
        ("canonical_url", row.canonical_url, doc.canonical_url),
        ("content_selector", row.content_selector, doc.content_selector),
        ("language", row.language or "vi", doc.language),
        ("publisher", row.publisher or "Green SM", doc.publisher),
    ]
    for field, left, right in checks:
        if left != right:
            errors.append(
                f"{doc.source_id}: metadata mismatch on {field}: manifest={left!r} snapshot={right!r}"
            )
    if doc.char_count != len(doc.normalized_text):
        errors.append(
            f"{doc.source_id}: char_count={doc.char_count} != len(normalized_text)={len(doc.normalized_text)}"
        )
    return errors


def assert_materialization_lineage(doc: SnapshotDocument) -> None:
    required = [
        doc.materializer_version,
        doc.materialization_mode,
        doc.materialization_payload_sha256,
        doc.parser_version,
    ]
    if any(not v for v in required):
        raise BundleValidationError(
            f"{doc.source_id}: snapshot missing materialization lineage "
            "(materializer_version/mode/payload_sha256/parser_version)"
        )
    if doc.content_kind == "image_only":
        if doc.ocr_status != "not_run":
            raise BundleValidationError(f"{doc.source_id}: image-only requires ocr_status=not_run")
        if doc.text_retrieval_eligible:
            raise BundleValidationError(
                f"{doc.source_id}: image-only must set text_retrieval_eligible=false"
            )
        if not doc.asset_urls:
            raise BundleValidationError(f"{doc.source_id}: image-only missing asset_urls")


def validate_snapshot_manifest_bundle(
    *,
    snapshots_dir: Path,
    manifest_path: Path,
    expected_ids: list[str],
    require_snapshotted: bool = True,
) -> tuple[list[ManifestRow], list[SnapshotDocument]]:
    """
    Shared validator for staging preflight and production strict bundles.
    Enforces exact ID set from immutable contract, filename/source_id, checksums,
    char_count, metadata alignment, and materialization lineage.
    """
    if not manifest_path.exists():
        raise BundleValidationError(f"manifest missing: {manifest_path}")
    if not snapshots_dir.exists():
        raise BundleValidationError(f"snapshots directory missing: {snapshots_dir}")

    expected_set = set(expected_ids)
    if len(expected_ids) != EXPECTED_CORPUS_COUNT or len(expected_set) != EXPECTED_CORPUS_COUNT:
        raise BundleValidationError(
            f"expected_ids must be exactly {EXPECTED_CORPUS_COUNT} unique source_ids"
        )

    rows = _read_manifest(manifest_path)
    row_ids = [r.source_id for r in rows]
    if len(row_ids) != EXPECTED_CORPUS_COUNT or set(row_ids) != expected_set:
        raise BundleValidationError(
            "manifest IDs must exactly match expected 18 corpus source_ids: "
            f"only_in_manifest={sorted(set(row_ids) - expected_set)} "
            f"only_in_expected={sorted(expected_set - set(row_ids))} "
            f"count={len(row_ids)}"
        )

    files = sorted(snapshots_dir.glob("*.json"))
    extras = [p for p in snapshots_dir.iterdir() if p.is_file() and p.suffix.lower() != ".json"]
    # provenance json is allowed beside by_source, not inside by_source
    if extras:
        raise BundleValidationError(f"snapshots dir has non-json extras: {[p.name for p in extras]}")
    file_ids = {p.stem for p in files}
    if len(files) != EXPECTED_CORPUS_COUNT or file_ids != expected_set:
        raise BundleValidationError(
            "snapshot IDs must exactly match expected 18 corpus source_ids: "
            f"only_in_files={sorted(file_ids - expected_set)} "
            f"only_in_expected={sorted(expected_set - file_ids)} "
            f"count={len(files)}"
        )

    docs: list[SnapshotDocument] = []
    by_row = {r.source_id: r for r in rows}
    for sid in expected_ids:
        path = snapshot_path_for(snapshots_dir, sid)
        if not path.exists():
            raise BundleValidationError(f"missing snapshot file for {sid}")
        try:
            doc = SnapshotDocument.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:
            raise BundleValidationError(f"invalid snapshot JSON {path.name}: {exc}") from exc
        if path.name != f"{doc.source_id}.json" or doc.source_id != sid:
            raise BundleValidationError(
                f"filename/source_id mismatch: file={path.name} doc={doc.source_id} expected={sid}"
            )
        try:
            assert_materialization_lineage(doc)
        except BundleValidationError:
            raise
        if sha256_text(doc.normalized_text) != doc.content_sha256:
            raise BundleValidationError(f"content_sha256 mismatch for {sid}")
        if not doc.normalized_text.strip():
            raise BundleValidationError(f"empty normalized_text for {sid}")

        row = by_row[sid]
        if require_snapshotted and row.snapshot_status != "snapshotted":
            raise BundleValidationError(f"manifest row {sid} must be snapshotted")
        if require_snapshotted and row.sha256 != doc.content_sha256:
            raise BundleValidationError(f"manifest sha256 mismatch for {sid}")
        if require_snapshotted and not row.fetched_at:
            raise BundleValidationError(f"manifest fetched_at missing for {sid}")

        meta_errors = _align_metadata(row, doc)
        if meta_errors:
            raise BundleValidationError("; ".join(meta_errors))
        docs.append(doc)
    return rows, docs
