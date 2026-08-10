from __future__ import annotations

import csv
import hashlib
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from poc_corpus.checksum import codepoint_span, sha256_text
from poc_corpus.fetch import FetchError, assert_allowed_url, assert_html_content_type, validate_fetch_payload
from poc_corpus.pipeline import PipelineError, stage_snapshots
from poc_corpus.selectors import SelectorError, extract_normalized, extract_section
from poc_corpus.validate_knowledge import (
    KnowledgeValidationError,
    protect_eval_dataset,
    sha256_file,
    validate_knowledge,
)


FIXTURE = PROJECT_ROOT / "tests/fixtures/corpus/helps_sample.html"
PRIVACY = PROJECT_ROOT / "tests/fixtures/corpus/terms_privacy_sample.html"


class SelectorCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helps_html = FIXTURE.read_text(encoding="utf-8")
        cls.privacy_html = PRIVACY.read_text(encoding="utf-8")

    def test_faq_xy_dom(self):
        text, result = extract_normalized(self.helps_html, "faq:3.4")
        self.assertEqual(result.extraction_strategy.value, "dom_semantic")
        self.assertIn("hóa đơn VAT", text)
        self.assertNotIn("TÌM KIẾM", text)

    def test_faq_range_keeps_boundary(self):
        text, result = extract_normalized(self.helps_html, "faq:4.1-4.4")
        self.assertEqual(result.faq_range, ["4.1", "4.2", "4.3", "4.4"])
        self.assertIn("Ưu đãi", text)
        self.assertNotIn("không nhận được điểm Xanh", text)

    def test_section_n(self):
        text, result = extract_normalized(self.helps_html, "section:2")
        self.assertEqual(result.extraction_strategy.value, "dom_semantic")
        self.assertIn("Di chuyển", text)
        self.assertIn("2.13", text)
        self.assertNotIn("3.1. Hướng dẫn thêm mới", text)

    def test_page_selector(self):
        text, result = extract_normalized(self.privacy_html, "page")
        self.assertIn("Chính sách bảo vệ dữ liệu cá nhân", text)

    def test_faq_miss_no_full_page_fallback(self):
        with self.assertRaises(SelectorError):
            extract_section(self.helps_html, "faq:9.99")


class NormalizeAndChecksumTests(unittest.TestCase):
    def test_idempotent_checksum(self):
        html = FIXTURE.read_text(encoding="utf-8")
        text1, _ = extract_normalized(html, "faq:2.13")
        text2, _ = extract_normalized(html, "faq:2.13")
        self.assertEqual(sha256_text(text1), sha256_text(text2))

    def test_codepoint_offsets_nfc(self):
        text, _ = extract_normalized(FIXTURE.read_text(encoding="utf-8"), "faq:3.4")
        quote = "Để xuất hóa đơn VAT, vào lịch sử chuyến và chọn yêu cầu hóa đơn."
        start, end = codepoint_span(text, quote)
        self.assertEqual(text[start:end], quote)


class FetchGuardTests(unittest.TestCase):
    def test_rejects_non_https(self):
        with self.assertRaises(FetchError):
            assert_allowed_url("http://www.greensm.com/vn-vi/helps", ["www.greensm.com"])

    def test_rejects_other_host(self):
        with self.assertRaises(FetchError):
            assert_allowed_url("https://evil.example/x", ["www.greensm.com"])

    def test_html_mime_only(self):
        with self.assertRaises(FetchError):
            assert_html_content_type("application/json")
        assert_html_content_type("text/html; charset=utf-8")


class OfflinePipelineTests(unittest.TestCase):
    def test_stage_18_units_and_roles(self):
        manifest_path = PROJECT_ROOT / "data/corpus/corpus_manifest.csv"
        before = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as f:
            before_statuses = {r["snapshot_status"] for r in csv.DictReader(f)}
        staging, docs, rows = stage_snapshots(PROJECT_ROOT, mode="offline")
        self.assertEqual(len(docs), 18)
        self.assertTrue(str(staging).replace("\\", "/").endswith("artifacts/offline_staging"))
        by_id = {d.source_id: d for d in docs}
        self.assertEqual(by_id["GSM-HELP-TRIP-002"].retrieval_role.value, "parent_context")
        self.assertEqual(by_id["GSM-HELP-LOST-ITEM-213"].parent_source_id, "GSM-HELP-TRIP-002")
        after = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as f:
            after_statuses = {r["snapshot_status"] for r in csv.DictReader(f)}
        self.assertEqual(before_statuses, after_statuses)

    def test_line_fallback_path(self):
        html = """
        <html><body>
        8.1. Synthetic FAQ One
        Body one.
        8.2. Synthetic FAQ Two
        Body two.
        </body></html>
        """
        text, result = extract_normalized(html, "faq:8.1")
        self.assertEqual(result.extraction_strategy.value, "line_fallback")
        self.assertIn("Body one", text)
        self.assertNotIn("Body two", text)


class KnowledgeValidationTests(unittest.TestCase):
    def test_eval_sha_stable(self):
        pre, post = protect_eval_dataset(PROJECT_ROOT)
        self.assertEqual(pre, post)

    def test_offline_fixture_strict(self):
        summary = validate_knowledge(PROJECT_ROOT, scope="offline-fixture", strict=True)
        self.assertEqual(summary["production_knowledge_readiness"], "NOT_READY")
        self.assertEqual(summary["fact_count"], 34)

    def test_production_strict_not_ready_until_research_approval(self):
        with self.assertRaises(KnowledgeValidationError):
            validate_knowledge(PROJECT_ROOT, scope="production", strict=True)

    def test_production_non_strict_candidate_not_ready(self):
        summary = validate_knowledge(PROJECT_ROOT, scope="production", strict=False)
        self.assertEqual(summary["production_knowledge_readiness"], "NOT_READY")
        self.assertIn(
            summary["production_phase"],
            {"production-candidate", "production-invalid", "production-skeleton"},
        )


if __name__ == "__main__":
    unittest.main()
