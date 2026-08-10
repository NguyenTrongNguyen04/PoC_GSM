"""Staging bundle provenance + immutable bundle digest (Pass B.1.1)."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from poc_corpus.bundle import EXPECTED_CORPUS_COUNT, load_expected_source_ids
from poc_corpus.checksum import sha256_bytes, sha256_text


PROVENANCE_FILENAME = "bundle_provenance.json"
BUNDLE_DIGEST_SCHEMA = "0.2.0"
_HEX64 = re.compile(r"^[a-f0-9]{64}$")

PromotionStatus = Literal[
    "not_promotable",
    "staged_pending_research_approval",
    "research_approved",
]


class BundleProvenance(BaseModel):
    schema_version: str = "0.2.0"
    data_origin: Literal["offline", "live"]
    run_id: str
    materializer_version: str
    config_sha256: str
    raw_sha256_by_url: dict[str, str] = Field(default_factory=dict)
    created_at: str
    promotion_status: PromotionStatus
    research_reviewed_by: str | None = None
    research_reviewed_at: str | None = None
    research_review_notes: str = ""
    staged_bundle_sha256: str | None = None
    approved_bundle_sha256: str | None = None
    bundle_file_sha256_by_path: dict[str, str] = Field(default_factory=dict)
    auxiliary_script_urls: dict[str, str] = Field(default_factory=dict)
    # url -> sha256 of auxiliary JS (e.g. regulations page script)

    @field_validator("staged_bundle_sha256", "approved_bundle_sha256")
    @classmethod
    def _hex_or_none(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not _HEX64.match(value):
            raise ValueError("digest must be 64 lowercase hex chars")
        return value


class ProvenanceError(ValueError):
    pass


def new_run_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat(timespec="seconds")


def config_sha256(project_root: Path) -> str:
    path = project_root / "config/corpus_snapshot.yaml"
    return sha256_bytes(path.read_bytes())


def provenance_path(staging_root: Path) -> Path:
    return staging_root / PROVENANCE_FILENAME


def write_provenance(staging_root: Path, provenance: BundleProvenance) -> Path:
    path = provenance_path(staging_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(provenance.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return path


def read_provenance(staging_root: Path) -> BundleProvenance:
    path = provenance_path(staging_root)
    if not path.exists():
        raise ProvenanceError(f"missing provenance manifest: {path}")
    try:
        return BundleProvenance.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        raise ProvenanceError(f"invalid provenance manifest: {exc}") from exc


def collect_bundle_file_hashes(staging_root: Path, *, project_root: Path | None = None) -> dict[str, str]:
    """
    Hash staging corpus_manifest.csv + by_source/{id}.json (raw bytes).
    Keys are POSIX paths relative to staging_root. Provenance JSON is excluded.
    """
    staging_root = staging_root.resolve()
    manifest = staging_root / "corpus_manifest.csv"
    snaps = staging_root / "by_source"
    if not manifest.is_file():
        raise ProvenanceError(f"missing staged manifest: {manifest}")
    if not snaps.is_dir():
        raise ProvenanceError(f"missing staged snapshots dir: {snaps}")

    expected_ids: list[str] | None = None
    if project_root is not None:
        from poc_corpus.bundle import BundleValidationError

        try:
            expected_ids = load_expected_source_ids(project_root)
        except BundleValidationError as exc:
            raise ProvenanceError(str(exc)) from exc

    files: dict[str, str] = {"corpus_manifest.csv": sha256_bytes(manifest.read_bytes())}
    json_files = sorted(snaps.glob("*.json"))
    if expected_ids is not None:
        if len(json_files) != EXPECTED_CORPUS_COUNT:
            raise ProvenanceError(
                f"staged bundle must contain exactly {EXPECTED_CORPUS_COUNT} snapshots, "
                f"got {len(json_files)}"
            )
        present = {p.stem for p in json_files}
        if present != set(expected_ids):
            raise ProvenanceError(
                "staged snapshot IDs must match corpus contract: "
                f"only_in_files={sorted(present - set(expected_ids))} "
                f"only_in_contract={sorted(set(expected_ids) - present)}"
            )
        for sid in expected_ids:
            path = snaps / f"{sid}.json"
            if not path.is_file():
                raise ProvenanceError(f"missing staged snapshot: {path.name}")
            files[f"by_source/{sid}.json"] = sha256_bytes(path.read_bytes())
    else:
        for path in json_files:
            files[f"by_source/{path.name}"] = sha256_bytes(path.read_bytes())
    return files


def compute_bundle_sha256(file_hashes: dict[str, str]) -> str:
    """Canonical immutable bundle digest (excludes provenance)."""
    if "corpus_manifest.csv" not in file_hashes:
        raise ProvenanceError("bundle digest requires corpus_manifest.csv")
    snap_keys = [k for k in file_hashes if k.startswith("by_source/") and k.endswith(".json")]
    if len(snap_keys) != EXPECTED_CORPUS_COUNT:
        raise ProvenanceError(
            f"bundle digest requires exactly {EXPECTED_CORPUS_COUNT} snapshot files, got {len(snap_keys)}"
        )
    payload = {
        "schema_version": BUNDLE_DIGEST_SCHEMA,
        "files": {k: file_hashes[k] for k in sorted(file_hashes)},
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return sha256_bytes(canonical)


def compute_staging_bundle_digest(
    staging_root: Path, *, project_root: Path | None = None
) -> tuple[str, dict[str, str]]:
    mapping = collect_bundle_file_hashes(staging_root, project_root=project_root)
    digest = compute_bundle_sha256(mapping)
    return digest, mapping


def assert_publishable_live_provenance(
    provenance: BundleProvenance,
    *,
    staging_root: Path,
    project_root: Path,
) -> str:
    """Validate live + research_approved + immutable digest; return recomputed digest."""
    if provenance.data_origin != "live":
        raise ProvenanceError(
            f"publish refuses non-live bundle (data_origin={provenance.data_origin})"
        )
    if provenance.promotion_status != "research_approved":
        raise ProvenanceError(
            "publish refuses bundle not approved by Research Lead "
            f"(promotion_status={provenance.promotion_status})"
        )
    if not provenance.research_reviewed_by:
        raise ProvenanceError("publish refuses bundle missing research_reviewed_by")
    if not provenance.staged_bundle_sha256 or not provenance.approved_bundle_sha256:
        raise ProvenanceError("publish refuses bundle missing staged/approved bundle digest")
    if provenance.staged_bundle_sha256 != provenance.approved_bundle_sha256:
        raise ProvenanceError(
            "publish refused: staged_bundle_sha256 != approved_bundle_sha256 "
            "(post-approval inconsistency)"
        )
    recomputed, _mapping = compute_staging_bundle_digest(staging_root, project_root=project_root)
    if recomputed != provenance.staged_bundle_sha256 or recomputed != provenance.approved_bundle_sha256:
        raise ProvenanceError(
            "publish REFUSED: post-approval mutation detected "
            f"(recomputed={recomputed} "
            f"staged={provenance.staged_bundle_sha256} "
            f"approved={provenance.approved_bundle_sha256})"
        )
    return recomputed


def mark_research_approved(
    staging_root: Path,
    *,
    project_root: Path,
    reviewed_by: str,
    notes: str = "",
) -> BundleProvenance:
    prov = read_provenance(staging_root)
    if prov.data_origin != "live":
        raise ProvenanceError("only live staging bundles can be research-approved")
    if prov.promotion_status == "not_promotable":
        raise ProvenanceError("bundle is not_promotable")
    if not reviewed_by.strip():
        raise ProvenanceError("reviewed_by required")

    recomputed, mapping = compute_staging_bundle_digest(staging_root, project_root=project_root)
    if not prov.staged_bundle_sha256:
        raise ProvenanceError("staging provenance missing staged_bundle_sha256")
    if recomputed != prov.staged_bundle_sha256:
        raise ProvenanceError(
            "REFUSED: staging bundle changed since stage "
            f"(recomputed={recomputed} staged={prov.staged_bundle_sha256})"
        )

    updated = prov.model_copy(
        update={
            "promotion_status": "research_approved",
            "research_reviewed_by": reviewed_by,
            "research_reviewed_at": now_iso(),
            "research_review_notes": notes,
            "approved_bundle_sha256": recomputed,
            "bundle_file_sha256_by_path": mapping,
            "staged_bundle_sha256": recomputed,
        }
    )
    write_provenance(staging_root, updated)
    return updated


def sha256_mapping(mapping: dict[str, str]) -> str:
    payload = json.dumps(mapping, sort_keys=True, ensure_ascii=False)
    return sha256_text(payload)
