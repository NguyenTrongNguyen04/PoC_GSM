from __future__ import annotations

import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from poc_corpus.materialize import materialize_html, materialize_helps_faq
from poc_corpus.selectors import extract_normalized


class MaterializePassBTests(unittest.TestCase):
    def test_helps_materialize_supports_selectors(self):
        page_props = {
            "contentFaq": {
                "setUpFaq": [
                    {
                        "question": "Dành cho người dùng",
                        "setUpQuestion": [
                            {
                                "title": "An toàn",
                                "setUpTitle": [{"label": "A", "value": "body a"}],
                            },
                            {
                                "title": "Di chuyển",
                                "setUpTitle": [
                                    {"label": "x", "value": "pad"},
                                    {"label": "x", "value": "pad"},
                                    {"label": "x", "value": "pad"},
                                    {"label": "x", "value": "pad"},
                                    {"label": "x", "value": "pad"},
                                    {"label": "x", "value": "pad"},
                                    {"label": "x", "value": "pad"},
                                    {"label": "x", "value": "pad"},
                                    {"label": "x", "value": "pad"},
                                    {"label": "x", "value": "pad"},
                                    {"label": "x", "value": "pad"},
                                    {"label": "x", "value": "pad"},
                                    {
                                        "label": "Tôi bỏ quên đồ trên chuyến xe",
                                        "value": "Nếu bạn để quên đồ trên xe, hãy báo mất đồ.",
                                    },
                                ],
                            },
                        ],
                    }
                ]
            }
        }
        html = materialize_helps_faq(page_props)
        text, result = extract_normalized(html, "faq:2.13")
        self.assertEqual(result.extraction_strategy.value, "dom_semantic")
        self.assertIn("bỏ quên", text)
        self.assertIn("báo mất đồ", text)

    def test_identity_for_fixture_html(self):
        fixture = (PROJECT_ROOT / "tests/fixtures/corpus/helps_sample.html").read_text(
            encoding="utf-8"
        )
        result = materialize_html(
            fixture, canonical_url="https://www.greensm.com/vn-vi/helps"
        )
        self.assertEqual(result.mode, "identity")
        self.assertEqual(result.html, fixture)


if __name__ == "__main__":
    unittest.main()
