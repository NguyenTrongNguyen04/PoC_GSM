from __future__ import annotations

from pathlib import Path

import yaml

from poc_corpus.checksum import codepoint_span, nfc, slice_codepoints
from poc_corpus.models import (
    CatalogReview,
    EvidenceKind,
    EvidenceSpan,
    EvidenceStatus,
    FactEntry,
    ReviewStatus,
)
from poc_corpus.paths import validate_source_id


class FactCatalogError(ValueError):
    pass


def load_fact_catalog(path: Path) -> tuple[dict, list[FactEntry], CatalogReview]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    facts = [FactEntry.model_validate(item) for item in doc.get("facts", [])]
    ids = [f.fact_id for f in facts]
    if len(ids) != len(set(ids)):
        raise FactCatalogError("duplicate fact_id in catalog")
    review_raw = doc.get("review") or {}
    review = CatalogReview.model_validate(review_raw) if review_raw else CatalogReview()
    return doc, facts, review


def collect_dev_fact_ids(project_root: Path) -> set[str]:
    path = project_root / "data/scenarios/scenarios_dev.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    ids: set[str] = set()
    for scenario in doc["scenarios"]:
        for turn in scenario["turns"]:
            gt = turn["ground_truth"]
            for item in gt.get("expected_facts") or []:
                ids.add(item["fact_id"])
            for item in gt.get("forbidden_facts") or []:
                ids.add(item["fact_id"])
    return ids


def collect_dev_expected_doc_ids(project_root: Path) -> set[str]:
    path = project_root / "data/scenarios/scenarios_dev.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    ids: set[str] = set()
    for scenario in doc["scenarios"]:
        for turn in scenario["turns"]:
            for source_id in turn["ground_truth"].get("expected_doc_ids") or []:
                ids.add(source_id)
    return ids


def make_span(text: str, quote: str) -> EvidenceSpan:
    start, end = codepoint_span(text, quote)
    if slice_codepoints(text, start, end) != nfc(quote):
        raise FactCatalogError("codepoint span mismatch")
    return EvidenceSpan(quote=nfc(quote), start_codepoint=start, end_codepoint=end)


def detect_production_phase(facts: list[FactEntry]) -> str:
    """
    Return production-skeleton | production-candidate | production-verified | production-invalid.
    """
    corpus = [f for f in facts if f.evidence_kind == EvidenceKind.CORPUS]
    if not corpus:
        return "production-invalid"
    if all(
        f.evidence_status == EvidenceStatus.PENDING_LIVE_REVIEW and not f.evidence_spans
        for f in corpus
    ):
        return "production-skeleton"
    if all(
        f.evidence_status == EvidenceStatus.CANDIDATE_LIVE
        and bool(f.evidence_spans)
        and bool(f.source_content_sha256)
        for f in corpus
    ):
        return "production-candidate"
    if all(
        f.evidence_status == EvidenceStatus.APPROVED
        and bool(f.evidence_spans)
        and bool(f.source_content_sha256)
        for f in corpus
    ):
        return "production-verified"
    return "production-invalid"


def _validate_structured_ref_paths(
    fact: FactEntry,
    project_root: Path,
) -> list[str]:
    from poc_corpus.paths import PathSafetyError, ensure_within

    errors: list[str] = []
    root = project_root.resolve()
    for ref in fact.structured_evidence_refs:
        path = ref.path
        if not path:
            errors.append(f"{fact.fact_id}: structured ref {ref.ref_id} missing path")
            continue
        file_part = path.split("#", 1)[0]
        if not (
            file_part.startswith("config/")
            or file_part.startswith("data/")
            or file_part.startswith("docs/")
            or file_part.startswith("schemas/")
        ):
            errors.append(
                f"{fact.fact_id}: structured ref path must be project-relative "
                f"under config|data|docs|schemas: {path}"
            )
            continue
        full = (root / file_part).resolve()
        try:
            ensure_within(root, full)
        except PathSafetyError:
            errors.append(
                f"{fact.fact_id}: structured ref path escapes project root after resolve: {file_part}"
            )
            continue
        if not full.exists():
            errors.append(f"{fact.fact_id}: structured ref path does not exist: {file_part}")
    return errors


def validate_catalog_structure(
    facts: list[FactEntry],
    required_ids: set[str],
    *,
    catalog_scope: str,
    project_root: Path | None = None,
    review: CatalogReview | None = None,
) -> list[str]:
    """catalog_scope: offline-fixture | production-skeleton | production-candidate | production-verified"""
    errors: list[str] = []
    present = {f.fact_id for f in facts}
    missing = sorted(required_ids - present)
    if missing:
        errors.append(f"catalog missing fact_ids: {missing}")

    if catalog_scope == "production":
        catalog_scope = detect_production_phase(facts)
        if catalog_scope == "production-invalid":
            errors.append(
                "production catalog phase invalid: CORPUS must be all pending_live_review "
                "(skeleton), all candidate_live with spans (candidate), "
                "or all approved with spans (verified)"
            )

    for fact in facts:
        if fact.fact_id not in required_ids:
            errors.append(f"unexpected fact_id not in development set: {fact.fact_id}")
        if fact.source_id:
            try:
                validate_source_id(fact.source_id)
            except Exception as exc:
                errors.append(f"{fact.fact_id}: {exc}")

        if fact.evidence_kind == EvidenceKind.CORPUS:
            if not fact.source_id:
                errors.append(f"{fact.fact_id}: CORPUS requires source_id")
            if catalog_scope == "offline-fixture":
                if not fact.evidence_spans:
                    errors.append(f"{fact.fact_id}: fixture CORPUS requires evidence_spans")
                if fact.evidence_status not in {EvidenceStatus.CANDIDATE, EvidenceStatus.APPROVED}:
                    errors.append(f"{fact.fact_id}: fixture CORPUS status must be candidate/approved")
            elif catalog_scope == "production-skeleton":
                if fact.evidence_spans:
                    errors.append(f"{fact.fact_id}: production-skeleton CORPUS must not have evidence_spans")
                if fact.evidence_status != EvidenceStatus.PENDING_LIVE_REVIEW:
                    errors.append(f"{fact.fact_id}: production-skeleton CORPUS must be pending_live_review")
            elif catalog_scope == "production-candidate":
                if not fact.evidence_spans:
                    errors.append(f"{fact.fact_id}: production-candidate CORPUS requires evidence_spans")
                if fact.evidence_status != EvidenceStatus.CANDIDATE_LIVE:
                    errors.append(f"{fact.fact_id}: production-candidate CORPUS must be candidate_live")
                if not fact.source_content_sha256:
                    errors.append(f"{fact.fact_id}: CORPUS requires source_content_sha256")
            elif catalog_scope == "production-verified":
                if not fact.evidence_spans:
                    errors.append(f"{fact.fact_id}: production-verified CORPUS requires evidence_spans")
                if fact.evidence_status != EvidenceStatus.APPROVED:
                    errors.append(f"{fact.fact_id}: production-verified CORPUS must be approved")
                if not fact.source_content_sha256:
                    errors.append(f"{fact.fact_id}: CORPUS requires source_content_sha256")
        elif fact.evidence_kind in {
            EvidenceKind.NEGATIVE_CONSTRAINT,
            EvidenceKind.TICKET_FIXTURE,
            EvidenceKind.MEMORY_FIXTURE,
            EvidenceKind.POLICY_RULE,
        }:
            if fact.source_id is not None:
                errors.append(f"{fact.fact_id}: {fact.evidence_kind} must have source_id null")
            if not fact.structured_evidence_refs:
                errors.append(f"{fact.fact_id}: requires structured_evidence_refs")
            if fact.evidence_spans:
                errors.append(f"{fact.fact_id}: must not use corpus evidence_spans")
            if catalog_scope == "production-verified":
                if fact.evidence_status != EvidenceStatus.APPROVED:
                    errors.append(f"{fact.fact_id}: production-verified requires approved status")
            elif catalog_scope == "production-candidate":
                if fact.evidence_status != EvidenceStatus.CANDIDATE_LIVE:
                    errors.append(
                        f"{fact.fact_id}: production-candidate non-corpus must be candidate_live"
                    )
            elif catalog_scope == "production-skeleton":
                if fact.evidence_status not in {
                    EvidenceStatus.PENDING_LIVE_REVIEW,
                    EvidenceStatus.CANDIDATE,
                }:
                    errors.append(
                        f"{fact.fact_id}: production-skeleton non-corpus status must be "
                        "pending_live_review or candidate"
                    )
            if project_root is not None:
                errors.extend(_validate_structured_ref_paths(fact, project_root))
        else:
            errors.append(f"{fact.fact_id}: unknown evidence_kind")

    if catalog_scope == "production-verified" and review is not None:
        if review.review_status != ReviewStatus.APPROVED:
            errors.append("production-verified requires catalog review_status=approved")
        if not review.reviewed_by or not review.reviewed_at or not review.reviewed_snapshot_sha256:
            errors.append(
                "production-verified requires reviewed_by, reviewed_at, reviewed_snapshot_sha256"
            )
    return errors


def validate_corpus_evidence_against_texts(
    facts: list[FactEntry],
    texts_by_source: dict[str, str],
    content_sha_by_source: dict[str, str] | None = None,
) -> list[str]:
    errors: list[str] = []
    for fact in facts:
        if fact.evidence_kind != EvidenceKind.CORPUS:
            continue
        if not fact.evidence_spans:
            continue
        text = texts_by_source.get(fact.source_id or "")
        if text is None:
            errors.append(f"{fact.fact_id}: missing snapshot text for {fact.source_id}")
            continue
        if content_sha_by_source and fact.source_content_sha256:
            expected = content_sha_by_source.get(fact.source_id or "")
            if expected and fact.source_content_sha256 != expected:
                errors.append(
                    f"{fact.fact_id}: source_content_sha256 mismatch for {fact.source_id}"
                )
        for span in fact.evidence_spans:
            try:
                start, end = codepoint_span(text, span.quote)
            except ValueError:
                errors.append(f"{fact.fact_id}: quote not found in {fact.source_id}")
                continue
            if span.start_codepoint != start or span.end_codepoint != end:
                errors.append(
                    f"{fact.fact_id}: offset mismatch expected ({start},{end}) "
                    f"got ({span.start_codepoint},{span.end_codepoint})"
                )
    return errors


def production_evidence_verified(facts: list[FactEntry], review: CatalogReview | None = None) -> bool:
    """READY requires every fact APPROVED + Research catalog review approved."""
    if detect_production_phase(facts) != "production-verified":
        return False
    for fact in facts:
        if fact.evidence_status != EvidenceStatus.APPROVED:
            return False
        if fact.evidence_kind == EvidenceKind.CORPUS and not fact.evidence_spans:
            return False
        if fact.evidence_kind == EvidenceKind.CORPUS and not fact.source_content_sha256:
            return False
    if review is None or review.review_status != ReviewStatus.APPROVED:
        return False
    if not review.reviewed_by or not review.reviewed_snapshot_sha256:
        return False
    return True
