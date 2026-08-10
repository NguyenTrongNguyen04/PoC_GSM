from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from poc_corpus.bundle import (
    BundleValidationError,
    load_expected_source_ids,
    validate_snapshot_manifest_bundle,
)
from poc_corpus.fact_catalog import (
    FactCatalogError,
    collect_dev_expected_doc_ids,
    collect_dev_fact_ids,
    detect_production_phase,
    load_fact_catalog,
    production_evidence_verified,
    validate_catalog_structure,
    validate_corpus_evidence_against_texts,
)
from poc_corpus.pipeline import load_snapshot_config, stage_snapshots
from poc_corpus.persist import read_manifest


class KnowledgeValidationError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protect_eval_dataset(project_root: Path) -> tuple[str, str]:
    path = project_root / "data/scenarios/scenarios_eval.yaml"
    pre = sha256_file(path)
    post = sha256_file(path)
    if pre != post:
        raise KnowledgeValidationError("scenarios_eval.yaml changed during validation")
    return pre, post


def validate_knowledge(
    project_root: Path,
    *,
    scope: str = "offline-fixture",
    strict: bool = False,
    fixture_dir: Path | None = None,
) -> dict:
    if scope not in {"offline-fixture", "production"}:
        raise KnowledgeValidationError(f"unsupported scope: {scope}")

    errors: list[str] = []
    eval_pre, eval_post = protect_eval_dataset(project_root)
    cfg = load_snapshot_config(project_root)
    manifest_path = project_root / cfg["paths"]["manifest"]
    manifest_hash_pre = sha256_file(manifest_path)

    if scope == "offline-fixture":
        catalog_path = project_root / cfg["paths"]["fact_catalog_fixture"]
        structure_scope = "offline-fixture"
    else:
        catalog_path = project_root / cfg["paths"]["fact_catalog"]
        structure_scope = "production"

    try:
        _meta, facts, review = load_fact_catalog(catalog_path)
    except FactCatalogError as exc:
        raise KnowledgeValidationError(str(exc)) from exc

    required_ids = collect_dev_fact_ids(project_root)
    phase = detect_production_phase(facts) if scope == "production" else "offline-fixture"
    errors.extend(
        validate_catalog_structure(
            facts,
            required_ids,
            catalog_scope=structure_scope if scope == "offline-fixture" else phase,
            project_root=project_root,
            review=review if scope == "production" else None,
        )
    )

    expected_docs = collect_dev_expected_doc_ids(project_root)
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as f:
        manifest_rows = list(csv.DictReader(f))
    try:
        contract_ids = load_expected_source_ids(project_root)
    except BundleValidationError as exc:
        errors.append(str(exc))
        contract_ids = []
    manifest_ids = {row["source_id"] for row in manifest_rows}
    missing_docs = sorted(expected_docs - manifest_ids)
    if missing_docs:
        errors.append(f"development expected_doc_ids missing from manifest: {missing_docs}")
    if contract_ids and set(contract_ids) != manifest_ids:
        errors.append(
            "production manifest IDs diverge from immutable corpus contract "
            f"(manifest_extra={sorted(manifest_ids - set(contract_ids))} "
            f"contract_extra={sorted(set(contract_ids) - manifest_ids)})"
        )

    strict_details: dict = {}
    readiness = "NOT_READY"

    if scope == "offline-fixture":
        print("PRODUCTION KNOWLEDGE READINESS: NOT_READY")
        if strict:
            staging_root, docs, _rows = stage_snapshots(
                project_root,
                mode="offline",
                fixture_dir=fixture_dir or project_root / "tests/fixtures/corpus",
            )
            texts = {d.source_id: d.normalized_text for d in docs}
            errors.extend(validate_corpus_evidence_against_texts(facts, texts))
            missing_extract = sorted(expected_docs - set(texts))
            if missing_extract:
                errors.append(f"offline staging missing expected docs: {missing_extract}")
            _, docs2, _ = stage_snapshots(
                project_root,
                mode="offline",
                fixture_dir=fixture_dir or project_root / "tests/fixtures/corpus",
            )
            if {d.source_id: d.content_sha256 for d in docs} != {
                d.source_id: d.content_sha256 for d in docs2
            }:
                errors.append("offline staging not idempotent on content_sha256")
            manifest_hash_post = sha256_file(manifest_path)
            unchanged = manifest_hash_pre == manifest_hash_post
            if not unchanged:
                errors.append("production manifest hash changed during offline-fixture validation")
            strict_details = {
                "staged_units": len(docs),
                "artifact_dir": str(staging_root),
                "production_manifest_unchanged": unchanged,
                "production_manifest_sha256_pre": manifest_hash_pre,
                "production_manifest_sha256_post": manifest_hash_post,
                "pass": cfg.get("pass"),
            }
        readiness = "NOT_READY"
    else:
        rows = read_manifest(manifest_path)
        pending = [r.source_id for r in rows if r.snapshot_status != "snapshotted"]
        snap_dir = project_root / cfg["paths"]["snapshots_dir"]
        missing_files: list[str] = []
        texts: dict[str, str] = {}
        sha_by_source: dict[str, str] = {}
        verified = production_evidence_verified(facts, review)
        bundle_ok = False
        expected_ids: list[str] = contract_ids

        if expected_ids:
            try:
                _rows, docs = validate_snapshot_manifest_bundle(
                    snapshots_dir=snap_dir,
                    manifest_path=manifest_path,
                    expected_ids=expected_ids,
                    require_snapshotted=True,
                )
                texts = {d.source_id: d.normalized_text for d in docs}
                sha_by_source = {d.source_id: d.content_sha256 for d in docs}
                bundle_ok = True
            except BundleValidationError as exc:
                if strict:
                    errors.append(f"production strict bundle: {exc}")
                if snap_dir.exists():
                    present = {p.stem for p in snap_dir.glob("*.json")}
                    missing_files = sorted(set(expected_ids) - present)
                else:
                    missing_files = list(expected_ids)
        else:
            missing_files = [r.source_id for r in rows]

        if strict:
            if phase == "production-skeleton":
                errors.append("production strict: catalog still in production-skeleton phase")
            if phase == "production-candidate":
                errors.append(
                    "production strict: evidence still candidate_live (NOT_READY until Research approval)"
                )
            if pending:
                errors.append(f"production strict: manifest still pending for {pending}")
            if not verified:
                errors.append("production strict: evidence not fully approved/verified by Research")
            if phase == "production-verified" and bundle_ok:
                errors.extend(
                    validate_corpus_evidence_against_texts(
                        facts, texts, content_sha_by_source=sha_by_source
                    )
                )
            elif phase == "production-verified" and not bundle_ok:
                errors.append("production strict: cannot verify spans without valid production bundle")

        readiness = (
            "READY"
            if (
                phase == "production-verified"
                and not pending
                and bundle_ok
                and verified
                and not errors
            )
            else "NOT_READY"
        )
        print(f"PRODUCTION KNOWLEDGE READINESS: {readiness}")
        strict_details = {
            "production_phase": phase,
            "pending_manifest_rows": pending,
            "missing_snapshot_files": missing_files,
            "evidence_verified": verified,
            "bundle_exact_18": bundle_ok,
            "expected_source_ids": expected_ids,
            "review_status": review.review_status.value,
        }

    eval_final = sha256_file(project_root / "data/scenarios/scenarios_eval.yaml")
    if eval_final != eval_pre:
        errors.append("scenarios_eval.yaml mutated during validate_knowledge")

    summary = {
        "scope": scope,
        "production_knowledge_readiness": readiness,
        "production_phase": phase if scope == "production" else None,
        "fact_count": len(facts),
        "required_fact_count": len(required_ids),
        "catalog_path": str(catalog_path),
        "development_expected_doc_ids": sorted(expected_docs),
        "scenarios_eval_sha256_pre": eval_pre,
        "scenarios_eval_sha256_post": eval_post,
        "scenarios_eval_sha256_final": eval_final,
        "strict": strict,
        "strict_details": strict_details,
        "errors": errors,
    }
    if errors:
        raise KnowledgeValidationError("\n".join(errors))
    return summary
