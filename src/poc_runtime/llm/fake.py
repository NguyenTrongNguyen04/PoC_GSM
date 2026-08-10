from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from poc_runtime.llm.base import LLMClient
from poc_runtime.llm.types import (
    PROMPT_TEMPLATE_VERSION,
    RESPONSE_SCHEMA_VERSION,
    EphemeralConversationContext,
    LLMCallResult,
)
from poc_runtime.models import ActionType, StructuredAction, TicketStatus


class FakeLLMClient(LLMClient):
    """Deterministic offline LLM driven by explicit fixtures (not ground-truth labels)."""

    provider_name = "fake"
    model_id = "fake-b0-fixture"

    def __init__(
        self,
        fixtures: dict[str, StructuredAction] | None = None,
        *,
        fixture_path: Path | None = None,
    ) -> None:
        self.fixtures: dict[str, StructuredAction] = dict(fixtures or {})
        if fixture_path is not None:
            self.fixtures.update(load_fake_action_fixtures(fixture_path))

    def propose_action(
        self,
        *,
        trusted_user_id: str,
        user_message: str,
        context: dict[str, Any] | None = None,
        conversation: EphemeralConversationContext | None = None,
    ) -> LLMCallResult:
        _ = conversation  # Fake fixtures remain deterministic regardless of history.
        context = context or {}
        key = context.get("query_id") or user_message
        if key in self.fixtures:
            action = self.fixtures[key].model_copy(deep=True)
            if action.user_id is None:
                action = action.model_copy(update={"user_id": trusted_user_id})
        else:
            action = self._heuristic(trusted_user_id, user_message, context)
        return LLMCallResult(
            action=action,
            provider=self.provider_name,
            model_id=self.model_id,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            response_schema_version=RESPONSE_SCHEMA_VERSION,
            input_tokens=0,
            output_tokens=0,
            attempts=1,
            estimated_cost_usd=0.0,
            actual_cost_usd=0.0,
            structured_output_valid=True,
        )

    def _heuristic(
        self, trusted_user_id: str, user_message: str, context: dict[str, Any]
    ) -> StructuredAction:
        msg = user_message.lower()
        if "tạo hồ sơ" in msg or "tạo ticket" in msg or "khiếu nại" in msg:
            return StructuredAction(
                action_type=ActionType.CREATE_TICKET,
                user_id=trusted_user_id,
                complaint_type=context.get("complaint_type") or "CANCELLED_TRIP_CHARGE",
                reason="Create support ticket from user request",
                confidence=0.9,
                answer_text="Tôi sẽ tạo hồ sơ hỗ trợ theo yêu cầu của bạn.",
            )
        return StructuredAction(
            action_type=ActionType.NONE,
            user_id=trusted_user_id,
            reason="No ticket action needed",
            confidence=0.5,
            answer_text="Tôi đã ghi nhận câu hỏi. Hiện chưa cần tạo/cập nhật ticket.",
        )


def load_fake_action_fixtures(path: Path) -> dict[str, StructuredAction]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("actions") or data.get("fixtures") or data
    if isinstance(entries, dict) and "query_id" not in entries:
        out: dict[str, StructuredAction] = {}
        for qid, payload in entries.items():
            out[str(qid)] = _entry_to_action(str(qid), payload if isinstance(payload, dict) else {})
        return out
    if not isinstance(entries, list):
        raise ValueError(f"unsupported fake fixture format: {path}")
    out = {}
    for item in entries:
        qid = str(item["query_id"])
        out[qid] = _entry_to_action(qid, item)
    return out


def _entry_to_action(query_id: str, item: dict[str, Any]) -> StructuredAction:
    transition = item.get("requested_transition")
    ticket_ref = item.get("ticket_ref") or item.get("ticket_id")
    fields = dict(item.get("fields") or {})
    action_type = ActionType(str(item.get("action_type") or "NONE"))
    if action_type == ActionType.CREATE_TICKET and "ticket_id" not in fields:
        fields["ticket_id"] = f"TCK-FAKE-{query_id}"
    return StructuredAction(
        action_type=action_type,
        user_id=item.get("user_id"),
        ticket_id=str(ticket_ref) if ticket_ref else None,
        complaint_type=item.get("complaint_type"),
        requested_transition=TicketStatus(transition) if transition else None,
        fields=fields,
        reason=str(item.get("reason") or f"fixture:{query_id}"),
        confidence=float(item.get("confidence") or 1.0),
        answer_text=str(item.get("answer_text") or ""),
    )
