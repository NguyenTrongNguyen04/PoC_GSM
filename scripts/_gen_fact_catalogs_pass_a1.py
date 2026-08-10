from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]

meta = {
    "INVOICE_GUIDANCE": ("CORPUS", "GSM-HELP-INVOICE-304", "guidance", "Hướng dẫn phải dựa trên mục FAQ về hóa đơn VAT."),
    "INVOICE_CHECK": ("CORPUS", "GSM-HELP-INVOICE-304", "guidance", "Nêu đúng cách kiểm tra hóa đơn theo nguồn."),
    "INVOICE_DIFF_GUIDANCE": ("CORPUS", "GSM-HELP-INVOICE-DIFF-305", "guidance", "Giải thích chênh lệch ứng dụng và hóa đơn VAT."),
    "CANCELLED_CHARGE_GUIDANCE": ("CORPUS", "GSM-HELP-CANCELLED-CHARGE-306", "guidance", "Hướng dẫn khi hủy chuyến nhưng vẫn bị trừ tiền."),
    "NO_GUARANTEE": ("NEGATIVE_CONSTRAINT", None, "forbid", "Không cam kết hoàn tiền tức thì."),
    "PROMO_USAGE": ("CORPUS", "GSM-HELP-PROMO-401", "guidance", "Cách sử dụng mã khuyến mại."),
    "PROMO_STEP": ("CORPUS", "GSM-HELP-PROMO-401", "guidance", "Các bước nhập mã ưu đãi."),
    "LOYALTY_GUIDANCE": ("CORPUS", "GSM-HELP-LOYALTY-405", "guidance", "Hướng dẫn khi thiếu điểm Xanh."),
    "SUPPORT_CHANNEL": ("CORPUS", "GSM-HELP-SUPPORT-604", "guidance", "Kênh gửi yêu cầu hỗ trợ trên ứng dụng."),
    "CREATE_COMPLAINT": ("CORPUS", "GSM-HELP-SUPPORT-604", "guidance", "Tạo yêu cầu hỗ trợ/khiếu nại qua ứng dụng."),
    "LOST_ITEM_GUIDANCE": ("CORPUS", "GSM-HELP-LOST-ITEM-213", "guidance", "Hướng dẫn báo mất đồ."),
    "WAITING_ITEM_DETAIL": ("TICKET_FIXTURE", None, "state", "Chờ người dùng bổ sung chi tiết đồ thất lạc."),
    "NEXT_STEP_EVIDENCE": ("POLICY_RULE", None, "policy", "Bước tiếp theo phải có căn cứ policy/ticket."),
    "TICKET_STATUS": ("TICKET_FIXTURE", None, "state", "Trạng thái ticket theo Ticket Store."),
    "TICKET_STATUS_IN_REVIEW": ("TICKET_FIXTURE", None, "state", "Ticket đang IN_REVIEW."),
    "TICKET_IN_REVIEW": ("TICKET_FIXTURE", None, "state", "Nhận diện ticket IN_REVIEW."),
    "TICKET_WAITING": ("TICKET_FIXTURE", None, "state", "Ticket WAITING_CUSTOMER."),
    "RESOLVE_ONE_TICKET": ("TICKET_FIXTURE", None, "state", "Chỉ resolve đúng một ticket đã chọn."),
    "NEXT_STEP": ("TICKET_FIXTURE", None, "state", "Nêu bước tiếp theo theo trạng thái ticket."),
    "PRIOR_STEP": ("TICKET_FIXTURE", None, "state", "Tham chiếu bước trước trong cùng ticket thread."),
    "CONTINUITY": ("TICKET_FIXTURE", None, "state", "Duy trì liên tục ngữ cảnh ticket đa lượt."),
    "SAFE_UPDATE": ("POLICY_RULE", None, "policy", "Cập nhật ticket chỉ qua structured action được phép."),
    "PREFERENCE_UPDATE": ("MEMORY_FIXTURE", None, "memory", "Cập nhật preference memory hợp lệ."),
    "PREFERENCE_APP": ("MEMORY_FIXTURE", None, "memory", "Preference giao hóa đơn qua app."),
    "PREFERENCE_CONFIRM": ("MEMORY_FIXTURE", None, "memory", "Xác nhận preference đã lưu."),
    "DELETED_NOT_RECALLED": ("MEMORY_FIXTURE", None, "memory", "Memory DELETED không được recall."),
    "DELETE_WINS": ("MEMORY_FIXTURE", None, "memory", "Trạng thái DELETED thắng vector candidate cũ."),
    "FORBID_INVENTED_SLA": ("NEGATIVE_CONSTRAINT", None, "forbid", "Không tự tạo thời hạn xử lý khi nguồn không nêu."),
    "FORBID_REFUND_GUARANTEE": ("NEGATIVE_CONSTRAINT", None, "forbid", "Không cam kết chắc chắn hoàn tiền hoặc bồi thường."),
    "FORBID_RETROACTIVE_DISCOUNT": ("NEGATIVE_CONSTRAINT", None, "forbid", "Không hứa áp mã khuyến mại ngược."),
    "FORBID_OLD_PREFERENCE": ("NEGATIVE_CONSTRAINT", None, "forbid", "Không dùng preference đã supersede."),
    "FORBID_ACCOUNT_BALANCE": ("NEGATIVE_CONSTRAINT", None, "forbid", "Không tiết lộ số dư tài khoản giả định."),
    "FORBID_CROSS_USER_DATA": ("NEGATIVE_CONSTRAINT", None, "forbid", "Không tiết lộ dữ liệu user khác."),
    "FORBID_DELETED_MEMORY": ("NEGATIVE_CONSTRAINT", None, "forbid", "Không tái sử dụng nội dung memory đã xóa."),
}

refs = {
    "WAITING_ITEM_DETAIL": [{"ref_type": "ticket_fixture", "ref_id": "WAITING_CUSTOMER", "path": "data/scenarios/scenarios_dev.yaml", "notes": "Await customer item detail"}],
    "NEXT_STEP_EVIDENCE": [{"ref_type": "policy_rule", "ref_id": "memory.read_order", "path": "config/policy.yaml", "notes": "Hybrid next-step grounding"}],
    "TICKET_STATUS": [{"ref_type": "ticket_fixture", "ref_id": "ticket.status", "path": "schemas/ticket.schema.json", "notes": "Ticket Store SoR"}],
    "TICKET_STATUS_IN_REVIEW": [{"ref_type": "ticket_fixture", "ref_id": "IN_REVIEW", "path": "config/policy.yaml", "notes": "IN_REVIEW state"}],
    "TICKET_IN_REVIEW": [{"ref_type": "ticket_fixture", "ref_id": "IN_REVIEW", "path": "config/policy.yaml", "notes": "IN_REVIEW alias"}],
    "TICKET_WAITING": [{"ref_type": "ticket_fixture", "ref_id": "WAITING_CUSTOMER", "path": "config/policy.yaml", "notes": "Waiting state"}],
    "RESOLVE_ONE_TICKET": [{"ref_type": "ticket_fixture", "ref_id": "ambiguous_ticket_behavior", "path": "config/policy.yaml", "notes": "CLARIFY / single ticket"}],
    "NEXT_STEP": [{"ref_type": "ticket_fixture", "ref_id": "ticket.next_step", "path": "data/scenarios/scenarios_dev.yaml", "notes": "Scenario ticket continuity"}],
    "PRIOR_STEP": [{"ref_type": "ticket_fixture", "ref_id": "ticket.prior_step", "path": "data/scenarios/scenarios_dev.yaml", "notes": "Prior turn ticket context"}],
    "CONTINUITY": [{"ref_type": "ticket_fixture", "ref_id": "multi_turn_continuity", "path": "data/scenarios/scenarios_dev.yaml", "notes": "Multi-turn ticket thread"}],
    "SAFE_UPDATE": [{"ref_type": "policy_rule", "ref_id": "llm_direct_database_write=false", "path": "config/policy.yaml", "notes": "Structured action only"}],
    "PREFERENCE_UPDATE": [{"ref_type": "memory_fixture", "ref_id": "SUPPORT_PREFERENCE", "path": "config/policy.yaml", "notes": "Preference update"}],
    "PREFERENCE_APP": [{"ref_type": "memory_fixture", "ref_id": "invoice_delivery=app", "path": "data/personas/personas.yaml", "notes": "Persona preference"}],
    "PREFERENCE_CONFIRM": [{"ref_type": "memory_fixture", "ref_id": "SUPPORT_PREFERENCE.confirm", "path": "schemas/memory.schema.json", "notes": "Confirm stored preference"}],
    "DELETED_NOT_RECALLED": [{"ref_type": "memory_fixture", "ref_id": "DELETED", "path": "config/policy.yaml", "notes": "Filter DELETED before rank"}],
    "DELETE_WINS": [{"ref_type": "memory_fixture", "ref_id": "lifecycle_filter", "path": "config/policy.yaml", "notes": "DELETE wins over stale vector hit"}],
    "NO_GUARANTEE": [{"ref_type": "negative_rule", "ref_id": "refund_or_compensation_commitment", "path": "config/policy.yaml", "notes": "Hard gate: no refund guarantee"}],
    "FORBID_INVENTED_SLA": [{"ref_type": "negative_rule", "ref_id": "no_invented_sla", "path": "docs/DATA_CONTRACT.md", "notes": "No invented SLA"}],
    "FORBID_REFUND_GUARANTEE": [{"ref_type": "negative_rule", "ref_id": "refund_or_compensation_commitment", "path": "config/policy.yaml", "notes": "Hard gate"}],
    "FORBID_RETROACTIVE_DISCOUNT": [{"ref_type": "negative_rule", "ref_id": "no_retroactive_discount", "path": "docs/DATA_CONTRACT.md", "notes": "Negative constraint"}],
    "FORBID_OLD_PREFERENCE": [{"ref_type": "negative_rule", "ref_id": "no_superseded_preference", "path": "config/policy.yaml", "notes": "Superseded preference forbidden"}],
    "FORBID_ACCOUNT_BALANCE": [{"ref_type": "negative_rule", "ref_id": "no_account_balance", "path": "config/policy.yaml", "notes": "No fabricated balance"}],
    "FORBID_CROSS_USER_DATA": [{"ref_type": "negative_rule", "ref_id": "cross_user_leakage", "path": "config/policy.yaml", "notes": "Isolation hard gate"}],
    "FORBID_DELETED_MEMORY": [{"ref_type": "negative_rule", "ref_id": "invalid_lifecycle_reuse", "path": "config/policy.yaml", "notes": "Deletion hard gate"}],
}

spans = {
    "INVOICE_GUIDANCE": [("Để xuất hóa đơn VAT, vào lịch sử chuyến và chọn yêu cầu hóa đơn.", 92, 156)],
    "INVOICE_CHECK": [("Nếu chưa thấy hóa đơn, kiểm tra mục Hóa đơn trong Tài khoản hoặc email đã đăng ký.", 157, 239)],
    "INVOICE_DIFF_GUIDANCE": [("Số tiền trên ứng dụng và hóa đơn VAT có thể khác nhau do làm tròn thuế hoặc khoản điều chỉnh theo quy định.", 88, 195)],
    "CANCELLED_CHARGE_GUIDANCE": [("Nếu chuyến đã hủy mà thẻ vẫn bị trừ, hãy tạo yêu cầu hỗ trợ để được kiểm tra giao dịch.", 58, 145)],
    "PROMO_USAGE": [("Tại màn hình đặt xe, nhấn Ưu đãi, nhập mã rồi kiểm tra cước sau giảm trước khi Đặt xe.", 46, 132)],
    "PROMO_STEP": [("Tại màn hình đặt xe, nhấn Ưu đãi, nhập mã rồi kiểm tra cước sau giảm trước khi Đặt xe.", 46, 132)],
    "LOYALTY_GUIDANCE": [("Điểm Xanh có thể được cập nhật sau chuyến hợp lệ", 49, 97)],
    "SUPPORT_CHANNEL": [("Chọn Tài khoản, mở Trung tâm hỗ trợ, chọn chủ đề và tạo yêu cầu hỗ trợ trên ứng dụng.", 48, 133)],
    "CREATE_COMPLAINT": [("Chọn Tài khoản, mở Trung tâm hỗ trợ, chọn chủ đề và tạo yêu cầu hỗ trợ trên ứng dụng.", 48, 133)],
    "LOST_ITEM_GUIDANCE": [("Nếu bạn bỏ quên đồ trên chuyến xe, hãy vào lịch sử chuyến và chọn Báo mất đồ", 36, 112)],
}

prod_facts = []
fix_facts = []
for fid, (kind, sid, ctype, desc) in meta.items():
    base = {
        "fact_id": fid,
        "evidence_kind": kind,
        "source_id": sid,
        "claim_type": ctype,
        "description": desc,
        "evidence_spans": [],
        "structured_evidence_refs": refs.get(fid, []),
        "notes": "",
    }
    prod = dict(base)
    prod["evidence_status"] = "pending_live_review"
    if kind == "CORPUS":
        prod["structured_evidence_refs"] = []
        prod["notes"] = "Skeleton only; awaiting live snapshot + Research review (Pass B)"
    else:
        prod["notes"] = "Structured refs only; pending Research approval"
    prod_facts.append(prod)

    fix = dict(base)
    if kind == "CORPUS":
        fix["evidence_status"] = "candidate"
        fix["evidence_spans"] = [
            {"quote": q, "start_codepoint": s, "end_codepoint": e} for q, s, e in spans[fid]
        ]
        fix["structured_evidence_refs"] = []
        fix["notes"] = "Offline fixture candidate only; not production evidence"
    else:
        fix["evidence_status"] = "candidate"
        fix["notes"] = "Offline fixture structured evidence candidate"
    fix_facts.append(fix)

prod_doc = {
    "catalog_version": "0.1.1",
    "parser_contract": "corpus_snapshot_v0.1",
    "catalog_role": "production",
    "notes": "Pass A.1 production skeleton. No fixture evidence spans. CORPUS pending_live_review.",
    "facts": prod_facts,
}
fix_doc = {
    "catalog_version": "0.1.1",
    "parser_contract": "corpus_snapshot_v0.1",
    "catalog_role": "offline_fixture",
    "notes": "Pass A.1 fixture catalog for offline tests only. NO_GUARANTEE is NEGATIVE_CONSTRAINT.",
    "facts": fix_facts,
}

out_prod = root / "data/corpus/knowledge/fact_catalog.yaml"
out_fix = root / "data/corpus/knowledge/fact_catalog_fixture.yaml"
out_prod.write_text(yaml.safe_dump(prod_doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
out_fix.write_text(yaml.safe_dump(fix_doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
print("wrote", out_prod, len(prod_facts))
print("wrote", out_fix, len(fix_facts))
