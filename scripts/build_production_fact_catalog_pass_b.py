"""Build production fact_catalog.yaml evidence as candidate_live only (Pass B.1)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from poc_corpus.fact_catalog import load_fact_catalog, make_span
from poc_corpus.models import EvidenceKind, EvidenceStatus, ReviewStatus

# Expanded guidance quotes from live/staged snapshot text (must occur verbatim).
EXACT_QUOTES: dict[str, str] = {
    "INVOICE_GUIDANCE": (
        "Để yêu cầu xuất hóa đơn VAT cho chuyến xe Green SM, bạn cần tuân theo các hướng dẫn sau đây:\n"
        "I. Với các chuyến xe đặt qua ứng dụng\n"
        "Cách 1: Tạo yêu cầu xuất hóa đơn VAT - trước khi đặt xe"
    ),
    "INVOICE_CHECK": (
        "III. Cách kiểm tra hóa đơn\n"
        "- Hóa đơn sẽ được gửi qua email mà Quý khách đã đăng ký khi tạo yêu cầu. "
        "Vui lòng kiểm tra hòm thư chính, quảng cáo và thư rác để không bỏ sót\n"
        "- Với các chuyến đặt qua ứng dụng, Quý khách có thể xem lại tại:\n"
        "Hoạt động > Chuyến đi tương ứng > Xuất hóa đơn."
    ),
    "INVOICE_DIFF_GUIDANCE": (
        "Cước phí hiển thị trên hóa đơn giá trị gia tăng (VAT) sẽ không bao gồm các loại phí sau (nếu có):\n"
        "– Phí cầu đường, bến bãi, sân bay, đỗ xe,…\n"
        "– Phí bảo hiểm chuyến đi Green SM Care."
    ),
    "CANCELLED_CHARGE_GUIDANCE": (
        "Ngoài ra, bạn cũng có thể gửi yêu cầu tại mục \"Trung tâm hỗ trợ\" trên ứng dụng Green SM "
        "để được kiểm tra và giải đáp kịp thời."
    ),
    "PROMO_USAGE": (
        "Để dùng mã khuyến mãi/ưu đãi giảm giá:\n"
        "1/ Tại màn hình đặt xe, nhập Điểm đón và Điểm đến.\n"
        "2/ Chọn dịch vụ di chuyển.\n"
        "3/ Nhấn “Ưu đãi” trên nút “Đặt xe”, nhập mã.\n"
        "4/ Kiểm tra cước phí sau giảm và chọn thanh toán.\n"
        "5/ Bấm “Đặt xe” và bắt đầu chuyến đi cùng Green SM."
    ),
    "PROMO_STEP": (
        "1/ Tại màn hình đặt xe, nhập Điểm đón và Điểm đến.\n"
        "2/ Chọn dịch vụ di chuyển.\n"
        "3/ Nhấn “Ưu đãi” trên nút “Đặt xe”, nhập mã."
    ),
    "LOYALTY_GUIDANCE": (
        "Nếu chuyến xe của bạn không nhận Điểm Xanh, hãy liên hệ Green SM để được kiểm tra và giải đáp ngay.\n"
        "Kiểm tra Điểm Xanh tại mục Tài khoản -> Hạng thành viên -> Lịch sử điểm của tôi."
    ),
    "SUPPORT_CHANNEL": (
        "Để gửi yêu cầu hỗ trợ trên ứng dụng, bạn vui lòng thực hiện theo các bước sau:\n"
        "Bước 1: Trên màn hình chính, chọn “Tài khoản” ở góc dưới bên phải, tiếp tục chọn “Trung tâm hỗ trợ”.\n"
        "Bước 2: Lựa chọn loại yêu cầu tương ứng (phản hồi chất lượng Tài xế/phương tiện, dịch vụ và chính sách,...)."
    ),
    "CREATE_COMPLAINT": (
        "Bước 1: Trên màn hình chính, chọn “Tài khoản” ở góc dưới bên phải, tiếp tục chọn “Trung tâm hỗ trợ”.\n"
        "Bước 2: Lựa chọn loại yêu cầu tương ứng (phản hồi chất lượng Tài xế/phương tiện, dịch vụ và chính sách,...).\n"
        "Bước 3: Nhập đầy đủ các thông tin cần thiết theo hướng dẫn"
    ),
    "LOST_ITEM_GUIDANCE": (
        "Nếu bạn để quên đồ trên xe, hãy làm theo các bước sau:\n"
        "1/ Gọi tài xế ngay lập tức nếu có số điện thoại của tài xế ở phần lịch sử cuộc gọi, "
        "hoặc gọi Hotline Green SM 1555 nếu không tìm thấy số."
    ),
}


def _load_texts(snap_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    texts: dict[str, str] = {}
    shas: dict[str, str] = {}
    for path in sorted(snap_dir.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        texts[doc["source_id"]] = doc["normalized_text"]
        shas[doc["source_id"]] = doc["content_sha256"]
    return texts, shas


def main() -> None:
    # Prefer Research staging bundle; fall back to production snapshots.
    staged = ROOT / "artifacts" / "live_staging" / "by_source"
    prod = ROOT / "data" / "corpus" / "snapshots" / "by_source"
    snap_dir = staged if staged.exists() and any(staged.glob("*.json")) else prod
    catalog_path = ROOT / "data/corpus/knowledge/fact_catalog.yaml"
    _meta, facts, _review = load_fact_catalog(catalog_path)
    texts, shas = _load_texts(snap_dir)

    out_facts = []
    for fact in facts:
        item = fact.model_dump(mode="json")
        if fact.evidence_kind == EvidenceKind.CORPUS:
            sid = fact.source_id or ""
            text = texts[sid]
            quote = EXACT_QUOTES[fact.fact_id]
            if quote not in text:
                raise SystemExit(f"{fact.fact_id}: exact quote missing in {sid} ({snap_dir})")
            span = make_span(text, quote)
            item["evidence_spans"] = [span.model_dump(mode="json")]
            item["source_content_sha256"] = shas[sid]
            item["evidence_status"] = EvidenceStatus.CANDIDATE_LIVE.value
            item["structured_evidence_refs"] = []
            item["notes"] = (
                "Pass B.1 candidate_live evidence proposed by Code Lead. "
                "Must NOT be treated as approved. Awaiting Research Lead review."
            )
        else:
            item["evidence_spans"] = []
            item["source_content_sha256"] = None
            item["evidence_status"] = EvidenceStatus.CANDIDATE_LIVE.value
            item["notes"] = (
                "Pass B.1 candidate_live structured evidence. Awaiting Research Lead review."
            )
        out_facts.append(item)

    doc = {
        "catalog_version": "0.2.1",
        "parser_contract": "corpus_snapshot_v0.2",
        "catalog_role": "production",
        "notes": (
            "Pass B.1 production catalog: candidate_live only. "
            "READY requires Research Lead approval of evidence + reviewed snapshot hash."
        ),
        "review": {
            "reviewed_by": None,
            "reviewed_at": None,
            "review_status": ReviewStatus.PENDING_RESEARCH_REVIEW.value,
            "reviewed_snapshot_sha256": None,
        },
        "facts": out_facts,
    }
    catalog_path.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"wrote {catalog_path} facts={len(out_facts)} status=candidate_live snap_dir={snap_dir}")


if __name__ == "__main__":
    main()
