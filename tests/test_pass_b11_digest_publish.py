"""Pass B.1.1 acceptance: immutable bundle digest + publish-existing."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from poc_corpus.bundle import load_expected_source_ids
from poc_corpus.checksum import sha256_text
from poc_corpus.models import ManifestRow, SnapshotDocument
from poc_corpus.persist import write_manifest, write_snapshot_json
from poc_corpus.pipeline import PipelineError, publish_existing_bundle, stage_snapshots
from poc_corpus.provenance import (
    BundleProvenance,
    ProvenanceError,
    assert_publishable_live_provenance,
    compute_staging_bundle_digest,
    mark_research_approved,
    write_provenance,
)


def _doc(source_id: str, text: str) -> SnapshotDocument:
    digest = sha256_text(text)
    return SnapshotDocument(
        source_id=source_id,
        title="t",
        canonical_url="https://www.greensm.com/vn-vi/helps",
        requested_url="https://www.greensm.com/vn-vi/helps",
        final_url="https://www.greensm.com/vn-vi/helps",
        content_selector="page",
        fetched_at="2026-08-10T00:00:00+07:00",
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
        normalized_text=text,
        char_count=len(text),
        language="vi",
        publisher="Green SM",
    )


def _seed_live_staging(root: Path, ids: list[str], *, text_prefix: str = "text") -> Path:
    import yaml

    (root / "data" / "corpus").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "corpus_snapshot.yaml").write_text(
        yaml.safe_dump(
            {
                "parser_version": "0.2.0",
                "materializer_version": "0.2.0",
                "publish_enabled": True,
                "live_fetch_enabled": False,
                "paths": {
                    "manifest": "data/corpus/corpus_manifest.csv",
                    "snapshots_dir": "data/corpus/snapshots/by_source",
                    "publish_backup_dir": "artifacts/publish_backup",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / "data" / "corpus" / "corpus_contract.yaml").write_text(
        yaml.safe_dump(
            {"contract_version": "0.2.0", "retrieval_unit_count": 18, "source_ids": list(ids)},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
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
    staging = root / "artifacts" / "live_staging"
    snaps = staging / "by_source"
    snaps.mkdir(parents=True)
    rows = []
    for i, sid in enumerate(ids):
        doc = _doc(sid, f"{text_prefix}-{i}")
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
    digest, mapping = compute_staging_bundle_digest(staging, project_root=root)
    write_provenance(
        staging,
        BundleProvenance(
            data_origin="live",
            run_id="test-run",
            materializer_version="0.2.0",
            config_sha256="c" * 64,
            created_at="2026-08-10T00:00:00+07:00",
            promotion_status="staged_pending_research_approval",
            staged_bundle_sha256=digest,
            approved_bundle_sha256=None,
            bundle_file_sha256_by_path=mapping,
        ),
    )
    return staging


class PassB11DigestTests(unittest.TestCase):
    def test_post_approval_snapshot_mutation_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = [f"GSM-TEST-{i:02d}" for i in range(18)]
            staging = _seed_live_staging(root, ids)
            mark_research_approved(staging, project_root=root, reviewed_by="Research Lead")
            # mutate one snapshot byte
            path = staging / "by_source" / f"{ids[0]}.json"
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaises(ProvenanceError) as ctx:
                assert_publishable_live_provenance(
                    __import__("poc_corpus.provenance", fromlist=["read_provenance"]).read_provenance(
                        staging
                    ),
                    staging_root=staging,
                    project_root=root,
                )
            self.assertIn("REFUSED", str(ctx.exception))

    def test_post_approval_manifest_mutation_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = [f"GSM-TEST-{i:02d}" for i in range(18)]
            staging = _seed_live_staging(root, ids)
            mark_research_approved(staging, project_root=root, reviewed_by="Research Lead")
            man = staging / "corpus_manifest.csv"
            man.write_bytes(man.read_bytes() + b"\n")
            from poc_corpus.provenance import read_provenance

            with self.assertRaises(ProvenanceError) as ctx:
                assert_publishable_live_provenance(
                    read_provenance(staging), staging_root=staging, project_root=root
                )
            self.assertIn("REFUSED", str(ctx.exception))

    def test_consistent_dual_mutation_still_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = [f"GSM-TEST-{i:02d}" for i in range(18)]
            staging = _seed_live_staging(root, ids)
            mark_research_approved(staging, project_root=root, reviewed_by="Research Lead")
            # rewrite all snapshots + matching manifest (internally consistent, still != approved digest)
            rows = []
            for i, sid in enumerate(ids):
                doc = _doc(sid, f"mutated-{i}")
                write_snapshot_json(staging / "by_source" / f"{sid}.json", doc)
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
            from poc_corpus.provenance import read_provenance

            with self.assertRaises(ProvenanceError) as ctx:
                assert_publishable_live_provenance(
                    read_provenance(staging), staging_root=staging, project_root=root
                )
            self.assertIn("REFUSED", str(ctx.exception))

    def test_missing_approved_digest_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = [f"GSM-TEST-{i:02d}" for i in range(18)]
            staging = _seed_live_staging(root, ids)
            from poc_corpus.provenance import read_provenance

            prov = read_provenance(staging).model_copy(
                update={
                    "promotion_status": "research_approved",
                    "research_reviewed_by": "Research Lead",
                    "approved_bundle_sha256": None,
                }
            )
            write_provenance(staging, prov)
            with self.assertRaises(ProvenanceError):
                assert_publishable_live_provenance(
                    read_provenance(staging), staging_root=staging, project_root=root
                )

    def test_bad_digest_format_fails_validation(self):
        with self.assertRaises(Exception):
            BundleProvenance(
                data_origin="live",
                run_id="x",
                materializer_version="0.2.0",
                config_sha256="c" * 64,
                created_at="2026-08-10T00:00:00+07:00",
                promotion_status="staged_pending_research_approval",
                staged_bundle_sha256="not-a-hash",
            )

    def test_intact_bundle_preflight_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = [f"GSM-TEST-{i:02d}" for i in range(18)]
            staging = _seed_live_staging(root, ids)
            mark_research_approved(staging, project_root=root, reviewed_by="Research Lead")
            from poc_corpus.provenance import read_provenance

            digest = assert_publishable_live_provenance(
                read_provenance(staging), staging_root=staging, project_root=root
            )
            self.assertEqual(len(digest), 64)


class PassB11PublishExistingTests(unittest.TestCase):
    def test_publish_existing_does_not_call_fetch_or_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = [f"GSM-TEST-{i:02d}" for i in range(18)]
            staging = _seed_live_staging(root, ids)
            mark_research_approved(staging, project_root=root, reviewed_by="Research Lead")
            with mock.patch("poc_corpus.pipeline.stage_snapshots") as stage_mock, mock.patch(
                "poc_corpus.pipeline.fetch_url"
            ) as fetch_mock, mock.patch(
                "poc_corpus.pipeline.publish_staged_transaction"
            ) as pub_mock:
                pub_mock.return_value = mock.Mock(published=True, rolled_back=False, backup_dir=None)
                publish_existing_bundle(root, staging, allow_publish=True)
                stage_mock.assert_not_called()
                fetch_mock.assert_not_called()
                pub_mock.assert_called_once()

    def test_cli_publish_existing_mutually_exclusive_and_no_stage(self):
        proc = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "snapshot_corpus.py"),
                "--mode",
                "live",
                "--publish-existing",
                "artifacts/live_staging",
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("mutually exclusive", proc.stderr)

    def test_offline_plus_publish_snapshots_removed(self):
        proc = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "snapshot_corpus.py"),
                "--mode",
                "offline",
                "--publish-snapshots",
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        # unknown arg or refused — must not succeed publish
        self.assertNotEqual(proc.returncode, 0)

    def test_publish_existing_requires_publish_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ids = [f"GSM-TEST-{i:02d}" for i in range(18)]
            staging = _seed_live_staging(root, ids)
            mark_research_approved(staging, project_root=root, reviewed_by="Research Lead")
            # force publish_enabled false
            import yaml

            cfg_path = root / "config" / "corpus_snapshot.yaml"
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            cfg["publish_enabled"] = False
            cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
            with self.assertRaises(PipelineError) as ctx:
                publish_existing_bundle(root, staging, allow_publish=True)
            self.assertIn("publish disabled", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
