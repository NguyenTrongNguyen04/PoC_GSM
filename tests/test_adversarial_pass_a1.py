from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from poc_corpus.checksum import sha256_text
from poc_corpus.fetch import (
    FetchError,
    FetchResult,
    assert_html_content_type,
    clamp_retry_after,
    load_raw_cache,
    validate_fetch_payload,
)
from poc_corpus.fact_catalog import (
    detect_production_phase,
    production_evidence_verified,
    validate_catalog_structure,
)
from poc_corpus.models import (
    EvidenceKind,
    EvidenceSpan,
    EvidenceStatus,
    FactEntry,
    ManifestRow,
    SnapshotDocument,
    StructuredEvidenceRef,
)
from poc_corpus.normalize import normalize_fragment_html
from poc_corpus.paths import PathSafetyError, resolve_artifacts_staging_dir, safe_rmtree
from poc_corpus.persist import PublishError, preflight_staged_bundle, publish_staged_transaction, write_manifest, write_snapshot_json
from poc_corpus.pipeline import PipelineError, publish_staged, stage_snapshots
from poc_corpus.selectors import SelectorError, extract_normalized, extract_section


def _minimal_doc(source_id: str, text: str = "hello") -> SnapshotDocument:
    digest = sha256_text(text)
    return SnapshotDocument(
        source_id=source_id,
        title="t",
        canonical_url="https://www.greensm.com/vn-vi/helps",
        requested_url="https://www.greensm.com/vn-vi/helps",
        final_url="https://www.greensm.com/vn-vi/helps",
        content_selector="page",
        fetched_at="2026-08-09T20:00:00+07:00",
        http_status=200,
        content_type="text/html",
        raw_sha256="a" * 64,
        content_sha256=digest,
        extraction_strategy="dom_semantic",
        parser_version="0.2.0",
        normalizer_version="0.1.0",
        materializer_version="0.2.0",
        materialization_mode="identity",
        materialization_payload_sha256="b" * 64,
        content_kind="text",
        text_retrieval_eligible=True,
        normalized_text=text,
        char_count=len(text),
        language="vi",
        publisher="Green SM",
    )


class AdversarialPathTests(unittest.TestCase):
    def test_custom_staging_outside_project_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "outside_staging"
            outside.mkdir()
            with self.assertRaises(PipelineError):
                stage_snapshots(PROJECT_ROOT, mode="offline", staging_root=outside)

    def test_resolve_staging_rejects_artifacts_root(self):
        with self.assertRaises(PathSafetyError):
            resolve_artifacts_staging_dir(PROJECT_ROOT, PROJECT_ROOT / "artifacts")

    def test_safe_rmtree_refuses_outside_and_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Use a fake project layout
            root = Path(tmp)
            (root / "artifacts").mkdir()
            outside = root / "outside"
            outside.mkdir()
            with self.assertRaises(PathSafetyError):
                safe_rmtree(outside, project_root=root)
            with self.assertRaises(PathSafetyError):
                safe_rmtree(root / "artifacts", project_root=root)


class AdversarialFetchTests(unittest.TestCase):
    def test_mime_rejects_html_malicious_prefix(self):
        with self.assertRaises(FetchError):
            assert_html_content_type("text/html-malicious")

    def test_retry_after_capped(self):
        self.assertEqual(clamp_retry_after("999999", 1.0), 60.0)

    def test_cache_must_pass_same_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            from poc_corpus.checksum import sha256_bytes

            url = "https://www.greensm.com/vn-vi/helps"
            key = sha256_bytes(url.encode("utf-8"))
            (cache / f"{key}.html").write_bytes(b"<html></html>")
            (cache / f"{key}.meta").write_text(
                "\n".join(
                    [
                        "final_url=https://evil.example/phish",
                        "content_type=text/html",
                        "status=200",
                        "last_modified=",
                        "redirect_hop=https://evil.example/phish",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(FetchError):
                load_raw_cache(
                    cache,
                    url,
                    allowed_hosts=["www.greensm.com"],
                    require_https=True,
                    max_response_bytes=1_000_000,
                )


class AdversarialSelectorTests(unittest.TestCase):
    def test_section_jump_2_to_4_rejected(self):
        html = """
        <html><body>
        <section data-section="2">
          <h2>2. Section Two</h2>
          <p>body</p>
          <h2>4. Section Four leaked</h2>
        </section>
        </body></html>
        """
        with self.assertRaises(SelectorError):
            extract_section(html, "section:2")

    def test_heading_data_faq_keeps_body(self):
        html = """
        <html><body><main>
          <h3 data-faq="3.4">3.4. Invoice heading</h3>
          <p>Body guidance for VAT invoice export.</p>
          <h3 data-faq="3.5">3.5. Next</h3>
          <p>Other</p>
        </main></body></html>
        """
        text, _ = extract_normalized(html, "faq:3.4")
        self.assertIn("Body guidance for VAT invoice export", text)
        self.assertNotIn("Other", text)

    def test_incomplete_faq_range_rejected(self):
        html = """
        <html><body><main>
        <article data-faq="4.1"><h3>4.1. A</h3><p>one</p></article>
        <article data-faq="4.2"><h3>4.2. B</h3><p>two</p></article>
        <article data-faq="4.4"><h3>4.4. D</h3><p>four</p></article>
        </main></body></html>
        """
        with self.assertRaises(SelectorError):
            extract_section(html, "faq:4.1-4.4")


class AdversarialNormalizeTests(unittest.TestCase):
    def test_lowercase_chrome_removed(self):
        html = "<html><body><main><p>Guide</p><p>hotline: 1555</p></main></body></html>"
        text = normalize_fragment_html(html)
        self.assertNotIn("hotline: 1555", text.lower())


def _seed_ids_contract(root: Path, ids: list[str]) -> None:
    import yaml

    (root / "data" / "corpus").mkdir(parents=True, exist_ok=True)
    (root / "data" / "corpus" / "corpus_contract.yaml").write_text(
        yaml.safe_dump(
            {"contract_version": "0.2.0", "retrieval_unit_count": 18, "source_ids": list(ids)},
            sort_keys=False,
        ),
        encoding="utf-8",
    )


class AdversarialPublishTests(unittest.TestCase):
    def test_publish_requires_allow_flag(self):
        with self.assertRaises(PipelineError):
            publish_staged(PROJECT_ROOT, PROJECT_ROOT / "artifacts/offline_staging", allow_publish=False)

    def test_preflight_rejects_invalid_json_bodies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = [f"GSM-TEST-{i:02d}" for i in range(18)]
            _seed_ids_contract(root, ids)
            write_manifest(
                root / "data" / "corpus" / "corpus_manifest.csv",
                [
                    ManifestRow(
                        source_id=sid,
                        title="t",
                        canonical_url="https://www.greensm.com/vn-vi/helps",
                        content_selector="page",
                        snapshot_status="pending",
                    )
                    for sid in ids
                ],
            )
            staging = root / "artifacts" / "offline_staging"
            snaps = staging / "by_source"
            snaps.mkdir(parents=True)
            rows = []
            for sid in ids:
                (snaps / f"{sid}.json").write_text("{not-json", encoding="utf-8")
                rows.append(
                    ManifestRow(
                        source_id=sid,
                        title="t",
                        canonical_url="https://www.greensm.com/vn-vi/helps",
                        content_selector="page",
                        snapshot_status="snapshotted",
                        sha256="x",
                        fetched_at="2026-08-09T20:00:00+07:00",
                    )
                )
            write_manifest(staging / "corpus_manifest.csv", rows)
            with self.assertRaises(PublishError):
                preflight_staged_bundle(
                    project_root=root,
                    staging_snapshots=snaps,
                    staging_manifest=staging / "corpus_manifest.csv",
                )

    def test_publish_always_updates_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = [f"GSM-TEST-{i:02d}" for i in range(18)]
            _seed_ids_contract(root, ids)
            write_manifest(
                root / "data" / "corpus" / "corpus_manifest.csv",
                [
                    ManifestRow(
                        source_id=sid,
                        title="t",
                        canonical_url="https://www.greensm.com/vn-vi/helps",
                        content_selector="page",
                        snapshot_status="pending",
                        language="vi",
                        publisher="Green SM",
                    )
                    for sid in ids
                ],
            )
            staging = root / "artifacts" / "offline_staging"
            snaps = staging / "by_source"
            snaps.mkdir(parents=True)
            target = root / "data" / "corpus" / "snapshots" / "by_source"
            target.parent.mkdir(parents=True)
            prod_manifest = root / "data" / "corpus" / "corpus_manifest.csv"
            rows = []
            for i, sid in enumerate(ids):
                doc = _minimal_doc(sid, f"text-{i}")
                write_snapshot_json(snaps / f"{sid}.json", doc)
                rows.append(
                    ManifestRow(
                        source_id=sid,
                        title="t",
                        canonical_url="https://www.greensm.com/vn-vi/helps",
                        content_selector="page",
                        snapshot_status="snapshotted",
                        sha256=doc.content_sha256,
                        fetched_at=doc.fetched_at,
                        language="vi",
                        publisher="Green SM",
                    )
                )
            write_manifest(staging / "corpus_manifest.csv", rows)
            pending_rows = [
                r.model_copy(update={"snapshot_status": "pending", "sha256": "", "fetched_at": ""})
                for r in rows
            ]
            write_manifest(prod_manifest, pending_rows)
            backup = root / "artifacts" / "publish_backup"
            publish_staged_transaction(
                project_root=root,
                staging_snapshots=snaps,
                target_snapshots=target,
                staging_manifest=staging / "corpus_manifest.csv",
                production_manifest=prod_manifest,
                backup_root=backup,
            )
            from poc_corpus.persist import read_manifest

            out = read_manifest(prod_manifest)
            self.assertEqual(len(out), 18)
            self.assertTrue(all(r.snapshot_status == "snapshotted" for r in out))
            self.assertEqual(len(list(target.glob("*.json"))), 18)


class AdversarialReadinessTests(unittest.TestCase):
    def test_rejected_noncorpus_not_verified(self):
        facts = [
            FactEntry(
                fact_id="INVOICE_GUIDANCE",
                evidence_kind=EvidenceKind.CORPUS,
                evidence_status=EvidenceStatus.APPROVED,
                source_id="GSM-HELP-INVOICE-304",
                evidence_spans=[EvidenceSpan(quote="x", start_codepoint=0, end_codepoint=1)],
            ),
            FactEntry(
                fact_id="FORBID_X",
                evidence_kind=EvidenceKind.NEGATIVE_CONSTRAINT,
                evidence_status=EvidenceStatus.REJECTED,
                source_id=None,
                structured_evidence_refs=[
                    StructuredEvidenceRef(ref_type="negative_rule", ref_id="x", path="config/policy.yaml")
                ],
            ),
        ]
        # Pad remaining required? production_evidence_verified only checks given list
        self.assertFalse(production_evidence_verified(facts))

    def test_skeleton_and_verified_phases(self):
        skeleton = [
            FactEntry(
                fact_id="INVOICE_GUIDANCE",
                evidence_kind=EvidenceKind.CORPUS,
                evidence_status=EvidenceStatus.PENDING_LIVE_REVIEW,
                source_id="GSM-HELP-INVOICE-304",
                evidence_spans=[],
            )
        ]
        self.assertEqual(detect_production_phase(skeleton), "production-skeleton")
        verified = [
            FactEntry(
                fact_id="INVOICE_GUIDANCE",
                evidence_kind=EvidenceKind.CORPUS,
                evidence_status=EvidenceStatus.APPROVED,
                source_id="GSM-HELP-INVOICE-304",
                evidence_spans=[EvidenceSpan(quote="abc", start_codepoint=0, end_codepoint=3)],
                source_content_sha256="c" * 64,
            )
        ]
        self.assertEqual(detect_production_phase(verified), "production-verified")
        from poc_corpus.models import CatalogReview, ReviewStatus

        review = CatalogReview(
            reviewed_by="Research Lead",
            reviewed_at="2026-08-10T00:00:00+07:00",
            review_status=ReviewStatus.APPROVED,
            reviewed_snapshot_sha256="d" * 64,
        )
        errs = validate_catalog_structure(
            verified,
            {"INVOICE_GUIDANCE"},
            catalog_scope="production-verified",
            project_root=PROJECT_ROOT,
            review=review,
        )
        self.assertEqual(errs, [])


if __name__ == "__main__":
    unittest.main()
