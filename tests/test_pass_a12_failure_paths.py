from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from poc_corpus.bundle import BundleValidationError, validate_snapshot_manifest_bundle
from poc_corpus.checksum import sha256_text
from poc_corpus.fact_catalog import validate_catalog_structure
from poc_corpus.models import (
    EvidenceKind,
    EvidenceStatus,
    FactEntry,
    ManifestRow,
    SnapshotDocument,
    StructuredEvidenceRef,
)
from poc_corpus.paths import PathSafetyError
from poc_corpus.persist import (
    PublishError,
    assert_publish_paths_confined,
    preflight_staged_bundle,
    publish_staged_transaction,
    write_manifest,
    write_snapshot_json,
)
from poc_corpus.pipeline import PipelineError, stage_snapshots
from poc_corpus.selectors import SelectorError, extract_section
from poc_corpus.validate_knowledge import KnowledgeValidationError, validate_knowledge


def _doc(source_id: str, text: str = "hello", **over) -> SnapshotDocument:
    digest = sha256_text(text)
    payload = dict(
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
    payload.update(over)
    return SnapshotDocument(**payload)


def _row(source_id: str, sha: str, **over) -> ManifestRow:
    payload = dict(
        source_id=source_id,
        title="t",
        canonical_url="https://www.greensm.com/vn-vi/helps",
        content_selector="page",
        snapshot_status="snapshotted",
        sha256=sha,
        fetched_at="2026-08-09T20:00:00+07:00",
        language="vi",
        publisher="Green SM",
    )
    payload.update(over)
    return ManifestRow(**payload)


def _seed_contract_manifest(root: Path, ids: list[str]) -> None:
    import yaml

    path = root / "data" / "corpus" / "corpus_manifest.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ManifestRow(
            source_id=sid,
            title="t",
            canonical_url="https://www.greensm.com/vn-vi/helps",
            content_selector="page",
            snapshot_status="pending",
        )
        for sid in ids
    ]
    write_manifest(path, rows)
    contract = {
        "contract_version": "0.2.0",
        "retrieval_unit_count": 18,
        "source_ids": list(ids),
    }
    (root / "data" / "corpus" / "corpus_contract.yaml").write_text(
        yaml.safe_dump(contract, sort_keys=False),
        encoding="utf-8",
    )


class PassA12FailurePathTests(unittest.TestCase):
    """Seven required A.1.2 regression failure paths."""

    def test_01_production_strict_requires_exact_18_ids(self):
        # Bundle validator rejects wrong cardinality (17 != 18).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = [f"GSM-TEST-{i:02d}" for i in range(17)]
            snaps = root / "by_source"
            snaps.mkdir(parents=True)
            rows = []
            for i, sid in enumerate(ids):
                doc = _doc(sid, f"text-{i}")
                write_snapshot_json(snaps / f"{sid}.json", doc)
                rows.append(_row(sid, doc.content_sha256))
            man = root / "manifest.csv"
            write_manifest(man, rows)
            with self.assertRaises(BundleValidationError) as ctx:
                validate_snapshot_manifest_bundle(
                    snapshots_dir=snaps,
                    manifest_path=man,
                    expected_ids=[f"GSM-TEST-{i:02d}" for i in range(18)],
                    require_snapshotted=True,
                )
            self.assertIn("18", str(ctx.exception))
        # Pass B.1: candidate / missing lineage => production strict NOT_READY / FAILED.
        with self.assertRaises(KnowledgeValidationError):
            validate_knowledge(PROJECT_ROOT, scope="production", strict=True)

    def test_02_shared_bundle_rejects_metadata_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = [f"GSM-TEST-{i:02d}" for i in range(18)]
            _seed_contract_manifest(root, ids)
            snaps = root / "data" / "corpus" / "snapshots" / "by_source"
            snaps.mkdir(parents=True)
            rows = []
            for i, sid in enumerate(ids):
                doc = _doc(sid, f"text-{i}", title="snapshot-title")
                write_snapshot_json(snaps / f"{sid}.json", doc)
                rows.append(_row(sid, doc.content_sha256, title="manifest-title"))
            man = root / "data" / "corpus" / "bundle_manifest.csv"
            write_manifest(man, rows)
            with self.assertRaises(BundleValidationError) as ctx:
                validate_snapshot_manifest_bundle(
                    snapshots_dir=snaps,
                    manifest_path=man,
                    expected_ids=ids,
                    require_snapshotted=True,
                )
            self.assertIn("metadata mismatch", str(ctx.exception))

    def test_03_publish_path_confinement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "corpus" / "snapshots").mkdir(parents=True)
            (root / "artifacts" / "publish_backup").mkdir(parents=True)
            with self.assertRaises(PublishError):
                assert_publish_paths_confined(
                    project_root=root,
                    target_snapshots=root / "outside" / "by_source",
                    production_manifest=root / "data" / "corpus" / "corpus_manifest.csv",
                    backup_root=root / "artifacts" / "publish_backup",
                )
            with self.assertRaises(PublishError):
                assert_publish_paths_confined(
                    project_root=root,
                    target_snapshots=root / "data" / "corpus" / "snapshots" / "by_source",
                    production_manifest=root / "elsewhere" / "corpus_manifest.csv",
                    backup_root=root / "artifacts" / "publish_backup",
                )
            with self.assertRaises(PublishError):
                assert_publish_paths_confined(
                    project_root=root,
                    target_snapshots=root / "data" / "corpus" / "snapshots" / "by_source",
                    production_manifest=root / "data" / "corpus" / "corpus_manifest.csv",
                    backup_root=root / "artifacts" / "other_backup",
                )

    def test_04_manifest_rollback_after_mutation_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = [f"GSM-TEST-{i:02d}" for i in range(18)]
            _seed_contract_manifest(root, ids)
            staging = root / "artifacts" / "offline_staging"
            snaps = staging / "by_source"
            snaps.mkdir(parents=True)
            target = root / "data" / "corpus" / "snapshots" / "by_source"
            target.mkdir(parents=True)
            (target / "OLD.json").write_text("{}", encoding="utf-8")
            prod_manifest = root / "data" / "corpus" / "corpus_manifest.csv"
            original = prod_manifest.read_bytes()
            rows = []
            for i, sid in enumerate(ids):
                doc = _doc(sid, f"text-{i}")
                write_snapshot_json(snaps / f"{sid}.json", doc)
                rows.append(_row(sid, doc.content_sha256))
            write_manifest(staging / "corpus_manifest.csv", rows)
            backup = root / "artifacts" / "publish_backup"

            real_write = write_manifest

            def boom_write(path, rows_arg):
                if path == prod_manifest:
                    raise OSError("simulated manifest write failure")
                return real_write(path, rows_arg)

            with mock.patch("poc_corpus.persist.write_manifest", side_effect=boom_write):
                with self.assertRaises(PublishError):
                    publish_staged_transaction(
                        project_root=root,
                        staging_snapshots=snaps,
                        target_snapshots=target,
                        staging_manifest=staging / "corpus_manifest.csv",
                        production_manifest=prod_manifest,
                        backup_root=backup,
                        post_validate=True,
                    )
            self.assertEqual(prod_manifest.read_bytes(), original)

    def test_05_preflight_rejects_manifest_snapshot_metadata_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = [f"GSM-TEST-{i:02d}" for i in range(18)]
            _seed_contract_manifest(root, ids)
            staging = root / "artifacts" / "offline_staging"
            snaps = staging / "by_source"
            snaps.mkdir(parents=True)
            rows = []
            for i, sid in enumerate(ids):
                doc = _doc(sid, f"text-{i}", content_selector="page")
                write_snapshot_json(snaps / f"{sid}.json", doc)
                rows.append(_row(sid, doc.content_sha256, content_selector="faq:9.9"))
            write_manifest(staging / "corpus_manifest.csv", rows)
            with self.assertRaises(PublishError) as ctx:
                preflight_staged_bundle(
                    project_root=root,
                    staging_snapshots=snaps,
                    staging_manifest=staging / "corpus_manifest.csv",
                )
            self.assertIn("metadata mismatch", str(ctx.exception))

    def test_06_line_fallback_stops_at_any_foreign_section(self):
        html = """
        <html><body>
        2. Section Two
        body of two
        4. Section Four jumped
        leaked
        </body></html>
        """
        # Force line path (no data-section)
        result = extract_section(html, "section:2")
        self.assertEqual(result.extraction_strategy.value, "line_fallback")
        text = result.html_fragment
        self.assertIn("Section Two", text)
        self.assertNotIn("Section Four jumped", text)

    def test_07_structured_ref_path_must_stay_in_project(self):
        fact = FactEntry(
            fact_id="SAFE_UPDATE",
            evidence_kind=EvidenceKind.POLICY_RULE,
            evidence_status=EvidenceStatus.PENDING_LIVE_REVIEW,
            source_id=None,
            structured_evidence_refs=[
                StructuredEvidenceRef(
                    ref_type="policy_rule",
                    ref_id="escape",
                    path="config/../../etc/passwd",
                )
            ],
        )
        errs = validate_catalog_structure(
            [fact],
            {"SAFE_UPDATE"},
            catalog_scope="production-skeleton",
            project_root=PROJECT_ROOT,
        )
        self.assertTrue(any("escapes project root" in e or "must be project-relative" in e for e in errs))


class PassA12SupportingTests(unittest.TestCase):
    def test_custom_staging_outside_still_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "outside"
            outside.mkdir()
            with self.assertRaises(PipelineError):
                stage_snapshots(PROJECT_ROOT, mode="offline", staging_root=outside)

    def test_publish_success_updates_manifest_and_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = [f"GSM-TEST-{i:02d}" for i in range(18)]
            _seed_contract_manifest(root, ids)
            staging = root / "artifacts" / "offline_staging"
            snaps = staging / "by_source"
            snaps.mkdir(parents=True)
            target = root / "data" / "corpus" / "snapshots" / "by_source"
            target.parent.mkdir(parents=True)
            prod_manifest = root / "data" / "corpus" / "corpus_manifest.csv"
            rows = []
            for i, sid in enumerate(ids):
                doc = _doc(sid, f"text-{i}")
                write_snapshot_json(snaps / f"{sid}.json", doc)
                rows.append(_row(sid, doc.content_sha256))
            write_manifest(staging / "corpus_manifest.csv", rows)
            # pending production rows with matching ids
            write_manifest(
                prod_manifest,
                [_row(sid, "", snapshot_status="pending", fetched_at="") for sid in ids],
            )
            publish_staged_transaction(
                project_root=root,
                staging_snapshots=snaps,
                target_snapshots=target,
                staging_manifest=staging / "corpus_manifest.csv",
                production_manifest=prod_manifest,
                backup_root=root / "artifacts" / "publish_backup",
            )
            from poc_corpus.persist import read_manifest

            out = read_manifest(prod_manifest)
            self.assertTrue(all(r.snapshot_status == "snapshotted" for r in out))
            self.assertEqual(len(list(target.glob("*.json"))), 18)


if __name__ == "__main__":
    unittest.main()
