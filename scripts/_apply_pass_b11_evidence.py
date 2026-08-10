from __future__ import annotations

import json
from pathlib import Path

import yaml

from poc_corpus.fact_catalog import make_span
from poc_corpus.provenance import (
    compute_staging_bundle_digest,
    read_provenance,
    write_provenance,
)

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "artifacts" / "live_staging"

INV_Q = (
    "Lưu ý:\n"
    "- Hóa đơn VAT sẽ được xuất ngay sau khi kết thúc chuyến đi\n"
    "- Quý khách cần yêu cầu xuất hóa đơn TRƯỚC khi chuyến đi kết thúc\n"
    "- Nếu không yêu cầu đúng thời điểm, Green SM sẽ không thể hỗ trợ xuất lại "
    "- theo quy định mới của Chính phủ"
)
CAN_Q = (
    "Tùy thuộc vào chính sách của từng ngân hàng, sẽ có ngân hàng chưa hỗ trợ "
    "thông báo qua tin nhắn SMS khi số tiền được hoàn về tài khoản, vì vậy bạn "
    "vui lòng kiểm tra sao kê, giao dịch với ngân hàng.\n"
    'Ngoài ra, bạn cũng có thể gửi yêu cầu tại mục "Trung tâm hỗ trợ" trên ứng '
    "dụng Green SM để được kiểm tra và giải đáp kịp thời."
)


def main() -> None:
    inv = json.loads((STAGING / "by_source/GSM-HELP-INVOICE-304.json").read_text(encoding="utf-8"))
    can = json.loads(
        (STAGING / "by_source/GSM-HELP-CANCELLED-CHARGE-306.json").read_text(encoding="utf-8")
    )
    if INV_Q not in inv["normalized_text"]:
        raise SystemExit("INVOICE quote missing from staged snapshot")
    if CAN_Q not in can["normalized_text"]:
        raise SystemExit("CANCELLED quote missing from staged snapshot")
    inv_span = make_span(inv["normalized_text"], INV_Q)
    can_span = make_span(can["normalized_text"], CAN_Q)

    cat_path = ROOT / "data/corpus/knowledge/fact_catalog.yaml"
    raw = yaml.safe_load(cat_path.read_text(encoding="utf-8"))
    for fact in raw["facts"]:
        if fact["fact_id"] == "INVOICE_GUIDANCE":
            fact["evidence_spans"] = [
                {
                    "quote": INV_Q,
                    "start_codepoint": inv_span.start_codepoint,
                    "end_codepoint": inv_span.end_codepoint,
                }
            ]
            fact["source_content_sha256"] = inv["content_sha256"]
            fact["evidence_status"] = "candidate_live"
        if fact["fact_id"] == "CANCELLED_CHARGE_GUIDANCE":
            fact["evidence_spans"] = [
                {
                    "quote": CAN_Q,
                    "start_codepoint": can_span.start_codepoint,
                    "end_codepoint": can_span.end_codepoint,
                }
            ]
            fact["source_content_sha256"] = can["content_sha256"]
            fact["evidence_status"] = "candidate_live"
    if raw.get("review", {}).get("review_status") != "pending_research_review":
        raise SystemExit("review_status must remain pending_research_review")
    if any(f["evidence_status"] != "candidate_live" for f in raw["facts"]):
        raise SystemExit("all facts must remain candidate_live")
    cat_path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print("catalog spans updated")

    prov = read_provenance(STAGING)
    digest, mapping = compute_staging_bundle_digest(STAGING, project_root=ROOT)
    updated = prov.model_copy(
        update={
            "staged_bundle_sha256": digest,
            "approved_bundle_sha256": None,
            "bundle_file_sha256_by_path": mapping,
            "promotion_status": "staged_pending_research_approval",
            "research_reviewed_by": None,
            "research_reviewed_at": None,
            "research_review_notes": "",
        }
    )
    write_provenance(STAGING, updated)
    print("staging digest", digest)


if __name__ == "__main__":
    main()
