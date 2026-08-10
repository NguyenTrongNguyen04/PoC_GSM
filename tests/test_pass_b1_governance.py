"""Pass B.1 acceptance tests required by Research Review."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from poc_corpus.bundle import (
    BundleValidationError,
    load_expected_source_ids,
    validate_snapshot_manifest_bundle,
)
from poc_corpus.checksum import sha256_text
from poc_corpus.materialize import (
    MaterializeError,
    discover_regulation_assets,
    materialize_html,
    rich_html_to_structured_text,
)
from poc_corpus.models import SnapshotDocument
from poc_corpus.pipeline import PipelineError, publish_staged, stage_snapshots
from poc_corpus.persist import write_snapshot_json
from poc_corpus.provenance import BundleProvenance, write_provenance
from poc_corpus.validate_knowledge import KnowledgeValidationError, validate_knowledge


class PassB1GovernanceAcceptanceTests(unittest.TestCase):
    def test_offline_plus_publish_refused_cli(self):
        proc = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "snapshot_corpus.py"),
                "--mode",
                "offline",
                "--publish-existing",
                "artifacts/offline_staging",
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("REFUSED", proc.stderr)

    def test_offline_publish_refused_api(self):
        staging, _docs, _rows = stage_snapshots(PROJECT_ROOT, mode="offline")
        with self.assertRaises(PipelineError) as ctx:
            publish_staged(
                PROJECT_ROOT,
                staging,
                allow_publish=True,
                staging_mode="offline",
            )
        self.assertIn("mode != live", str(ctx.exception).lower())

    def test_contract_source_id_change_fails(self):
        contract_ids = load_expected_source_ids(PROJECT_ROOT)
        mutated = contract_ids[:-1] + ["GSM-FAKE-000"]
        with tempfile.TemporaryDirectory() as tmp:
            snaps = Path(tmp) / "by_source"
            snaps.mkdir()
            with self.assertRaises(BundleValidationError) as ctx:
                validate_snapshot_manifest_bundle(
                    snapshots_dir=snaps,
                    manifest_path=PROJECT_ROOT / "data/corpus/corpus_manifest.csv",
                    expected_ids=mutated,
                    require_snapshotted=True,
                )
            self.assertTrue(
                "exactly match" in str(ctx.exception).lower()
                or "18" in str(ctx.exception)
                or "missing" in str(ctx.exception).lower()
            )

    def test_candidate_evidence_not_ready(self):
        with self.assertRaises(KnowledgeValidationError) as ctx:
            validate_knowledge(PROJECT_ROOT, scope="production", strict=True)
        msg = str(ctx.exception).lower()
        self.assertTrue(
            "candidate" in msg or "lineage" in msg or "not fully approved" in msg or "bundle" in msg
        )

    def test_rich_html_has_no_literal_tags(self):
        raw = (
            "<div><p>Hello</p><table><tr><th>A</th><th>B</th></tr>"
            "<tr><td>1</td><td>2</td></td></tr></table></div>"
        )
        text = rich_html_to_structured_text(raw)
        self.assertNotIn("<", text)
        self.assertNotIn(">", text)
        self.assertIn("TABLE", text)
        self.assertIn("A | B", text)

    def test_regulations_without_asset_list_fails(self):
        html = "<html><body><main>Quy chế</main><script id='__NEXT_DATA__'>{}</script></body></html>"
        # Force regulations path with empty next data props
        html = (
            '<html><body><script id="__NEXT_DATA__">'
            '{"props":{"pageProps":{}}}'
            "</script></body></html>"
        )
        with self.assertRaises(MaterializeError) as ctx:
            materialize_html(
                html,
                canonical_url="https://www.greensm.com/vn-vi/terms-policies/regulations",
                fetch_text=lambda _u: "no assets here",
            )
        self.assertIn("no asset list", str(ctx.exception).lower())

    def test_snapshot_missing_materialization_lineage_fails(self):
        from poc_corpus.bundle import assert_materialization_lineage
        from poc_corpus.models import SnapshotDocument

        # Valid doc then strip lineage fields via model_copy-equivalent dict
        text = "hello"
        doc = SnapshotDocument(
            source_id="GSM-HELP-TRIP-002",
            title="t",
            canonical_url="https://www.greensm.com/vn-vi/helps",
            requested_url="https://www.greensm.com/vn-vi/helps",
            final_url="https://www.greensm.com/vn-vi/helps",
            content_selector="page",
            fetched_at="2026-08-09T20:00:00+07:00",
            http_status=200,
            content_type="text/html",
            raw_sha256="a" * 64,
            content_sha256=sha256_text(text),
            extraction_strategy="dom_semantic",
            parser_version="0.2.0",
            normalizer_version="0.1.0",
            materializer_version="",
            materialization_mode="",
            materialization_payload_sha256="",
            normalized_text=text,
            char_count=len(text),
        )
        with self.assertRaises(BundleValidationError) as ctx:
            assert_materialization_lineage(doc)
        self.assertIn("materialization lineage", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
