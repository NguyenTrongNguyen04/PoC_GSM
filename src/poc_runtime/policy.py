from __future__ import annotations

from pathlib import Path

import yaml

from poc_runtime.models import (
    ActionType,
    PolicyDecisionCode,
    PolicyResult,
    StructuredAction,
    TicketLookupCode,
    TicketLookupOutcome,
    TicketStatus,
)
from poc_runtime.state_machine import TicketStateMachine

GENERIC_TICKET_UNAVAILABLE = (
    "Không thể thực hiện thao tác với hồ sơ này trong phiên hiện tại."
)


class PolicyEngine:
    def __init__(
        self,
        project_root: Path,
        *,
        state_machine: TicketStateMachine | None = None,
    ) -> None:
        path = project_root / "config/policy.yaml"
        self.policy = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.hard_gates = self.policy.get("hard_gates") or {}
        self.state_machine = state_machine or TicketStateMachine.from_policy_file(project_root)

    def validate(
        self,
        *,
        trusted_user_id: str,
        action: StructuredAction,
        lookup: TicketLookupOutcome,
    ) -> PolicyResult:
        if action.user_id and action.user_id != trusted_user_id:
            return PolicyResult(
                decision=PolicyDecisionCode.DENY,
                reason_code="TRUSTED_IDENTITY_MISMATCH",
                message="LLM user_id does not match execution context",
                sanitized_action=None,
            )

        text = f"{action.reason} {action.answer_text}".lower()
        if any(
            phrase in text
            for phrase in (
                "hoàn tiền ngay",
                "cam kết hoàn",
                "bồi thường chắc chắn",
                "refund today",
                "guaranteed refund",
            )
        ):
            if int(self.hard_gates.get("refund_or_compensation_commitment", 0)) == 0:
                return PolicyResult(
                    decision=PolicyDecisionCode.DENY,
                    reason_code="REFUND_OR_COMPENSATION_COMMITMENT",
                    message="Refund/compensation commitment hard gate",
                    sanitized_action=None,
                )

        if any(p in text for p in ("trong 24 giờ", "within 24 hours", "sla ")):
            return PolicyResult(
                decision=PolicyDecisionCode.DENY,
                reason_code="INVENTED_SLA",
                message="Invented SLA hard gate",
                sanitized_action=None,
            )

        if action.action_type == ActionType.NONE:
            return PolicyResult(
                decision=PolicyDecisionCode.NONE,
                reason_code="NO_ACTION",
                message="No ticket mutation",
                sanitized_action=action.model_copy(update={"user_id": trusted_user_id}),
            )

        if action.action_type == ActionType.CLARIFY:
            return PolicyResult(
                decision=PolicyDecisionCode.CLARIFY,
                reason_code="CLARIFY_REQUIRED",
                message=action.reason or "Clarification required",
                sanitized_action=action.model_copy(update={"user_id": trusted_user_id}),
            )

        if action.action_type == ActionType.CREATE_TICKET:
            if not action.complaint_type:
                return PolicyResult(
                    decision=PolicyDecisionCode.CLARIFY,
                    reason_code="MISSING_COMPLAINT_TYPE",
                    message="complaint_type required",
                    sanitized_action=None,
                )
            return PolicyResult(
                decision=PolicyDecisionCode.ALLOW,
                reason_code="CREATE_OK",
                message="Create ticket allowed",
                sanitized_action=action.model_copy(update={"user_id": trusted_user_id}),
            )

        ticket_actions = {
            ActionType.UPDATE_TICKET,
            ActionType.CLOSE_TICKET,
            ActionType.GET_TICKET_STATUS,
        }
        if action.action_type in ticket_actions:
            if not action.ticket_id:
                return PolicyResult(
                    decision=PolicyDecisionCode.CLARIFY,
                    reason_code="MISSING_TICKET_ID",
                    message="ticket_id required",
                    sanitized_action=None,
                )
            if lookup.code == TicketLookupCode.ACCESS_DENIED:
                return PolicyResult(
                    decision=PolicyDecisionCode.DENY,
                    reason_code="TICKET_NOT_ACCESSIBLE",
                    message=GENERIC_TICKET_UNAVAILABLE,
                    sanitized_action=None,
                )
            if lookup.code == TicketLookupCode.NOT_FOUND:
                return PolicyResult(
                    decision=PolicyDecisionCode.CLARIFY,
                    reason_code="TICKET_NOT_FOUND_OR_UNAVAILABLE",
                    message=GENERIC_TICKET_UNAVAILABLE,
                    sanitized_action=None,
                )
            if lookup.code != TicketLookupCode.FOUND or lookup.ticket is None:
                return PolicyResult(
                    decision=PolicyDecisionCode.DENY,
                    reason_code="TICKET_LOOKUP_UNAVAILABLE",
                    message=GENERIC_TICKET_UNAVAILABLE,
                    sanitized_action=None,
                )

            current = lookup.ticket
            if current.status == TicketStatus.CLOSED and action.action_type != ActionType.GET_TICKET_STATUS:
                return PolicyResult(
                    decision=PolicyDecisionCode.DENY,
                    reason_code="CLOSED_IMMUTABLE",
                    message="Closed ticket cannot be mutated",
                    sanitized_action=None,
                )

            if action.action_type == ActionType.UPDATE_TICKET and action.requested_transition:
                if not self.state_machine.can_transition(current.status, action.requested_transition):
                    return PolicyResult(
                        decision=PolicyDecisionCode.DENY,
                        reason_code="INVALID_TRANSITION",
                        message=(
                            f"Transition {current.status.value} -> "
                            f"{action.requested_transition.value} not allowed"
                        ),
                        sanitized_action=None,
                    )

            if action.action_type == ActionType.CLOSE_TICKET:
                if current.status == TicketStatus.CLOSED:
                    return PolicyResult(
                        decision=PolicyDecisionCode.DENY,
                        reason_code="ALREADY_CLOSED",
                        message="Ticket already closed",
                        sanitized_action=None,
                    )
                if not self.state_machine.can_transition(current.status, TicketStatus.CLOSED):
                    return PolicyResult(
                        decision=PolicyDecisionCode.DENY,
                        reason_code="INVALID_TRANSITION",
                        message=(
                            f"Cannot close from {current.status.value}; "
                            "only RESOLVED -> CLOSED is allowed"
                        ),
                        sanitized_action=None,
                    )

            return PolicyResult(
                decision=PolicyDecisionCode.ALLOW,
                reason_code="ALLOW",
                message="Action allowed",
                sanitized_action=action.model_copy(update={"user_id": trusted_user_id}),
            )

        return PolicyResult(
            decision=PolicyDecisionCode.DENY,
            reason_code="UNKNOWN_ACTION",
            message="Unknown action type",
            sanitized_action=None,
        )
