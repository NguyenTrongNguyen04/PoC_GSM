from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from poc_runtime.cost_guard import CostGuard
from poc_runtime.llm.base import LLMClient
from poc_runtime.llm.errors import ProviderError
from poc_runtime.llm.types import ConversationTurn, EphemeralConversationContext
from poc_runtime.models import (
    ActionType,
    ExecutionTrace,
    PolicyDecisionCode,
    StructuredAction,
    TicketLookupCode,
    TicketLookupOutcome,
)
from poc_runtime.policy import PolicyEngine
from poc_runtime.state_machine import TicketStateMachine
from poc_runtime.ticket_service import TicketService


class ConversationOrchestrator:
    def __init__(
        self,
        *,
        project_root: Path,
        ticket_service: TicketService,
        llm: LLMClient,
        cost_guard: CostGuard | None = None,
        provider_is_paid: bool = False,
        state_machine: TicketStateMachine | None = None,
        run_id: str = "",
        scenario_db_path: str = "",
        initial_state_sha256: str = "",
        conversation: EphemeralConversationContext | None = None,
    ) -> None:
        self.project_root = project_root
        self.tickets = ticket_service
        self.llm = llm
        self.state_machine = state_machine or ticket_service.state_machine
        self.policy = PolicyEngine(project_root, state_machine=self.state_machine)
        self.cost_guard = cost_guard or CostGuard(zero_cost=not provider_is_paid)
        self.provider_is_paid = provider_is_paid
        self.run_id = run_id
        self.scenario_db_path = scenario_db_path
        self.initial_state_sha256 = initial_state_sha256
        self.conversation = conversation or EphemeralConversationContext()

    def handle_query(
        self,
        *,
        trusted_user_id: str,
        user_message: str,
        scenario_id: str = "",
        query_id: str = "",
        session_id: str = "",
        context: dict | None = None,
    ) -> ExecutionTrace:
        started = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
        trace = ExecutionTrace(
            trusted_user_id=trusted_user_id,
            provider=self.llm.provider_name,
            model_id=self.llm.model_id,
            run_id=self.run_id,
            scenario_id=scenario_id,
            query_id=query_id,
            session_id=session_id,
            scenario_db_path=self.scenario_db_path,
            initial_state_sha256=self.initial_state_sha256,
            memory_enabled=False,
            timestamp=started.isoformat(timespec="seconds"),
        )
        ctx = dict(context or {})
        ctx.setdefault("query_id", query_id)
        ctx.setdefault("scenario_id", scenario_id)
        if "owned_ticket_ids" not in ctx:
            ctx["owned_ticket_ids"] = [
                t.ticket_id for t in self.tickets.list_user_tickets(trusted_user_id=trusted_user_id)
            ]

        action_executed = False
        try:
            call = self.llm.propose_action(
                trusted_user_id=trusted_user_id,
                user_message=user_message,
                context=ctx,
                conversation=self.conversation,
            )
            action = call.action
            self._apply_call_metadata(trace, call)

            # Resolve symbolic ticket refs using scenario-local store (not ground truth).
            action = self._resolve_ticket_refs(trusted_user_id, action)
            trace.proposed_action = action.model_dump(mode="json")

            lookup = self._lookup_for_action(trusted_user_id, action)
            trace.ticket_lookup_outcome = lookup.code.value

            decision = self.policy.validate(
                trusted_user_id=trusted_user_id,
                action=action,
                lookup=lookup,
            )
            trace.policy_decision = decision.model_dump(mode="json")
            trace.policy_reason_code = decision.reason_code

            if decision.decision in {
                PolicyDecisionCode.DENY,
                PolicyDecisionCode.CLARIFY,
                PolicyDecisionCode.NONE,
            }:
                if decision.decision == PolicyDecisionCode.NONE:
                    trace.answer = action.answer_text or decision.message
                elif decision.decision == PolicyDecisionCode.CLARIFY:
                    trace.answer = action.answer_text or decision.message
                else:
                    trace.answer = decision.message
                trace.executed_action = None
                self._remember(user_message, trace.answer, action.action_type.value, None)
                return self._finalize(trace, started)

            # ALLOW — execute at most once (retries happen only inside provider before return).
            sanitized = decision.sanitized_action
            assert sanitized is not None
            if action_executed:
                raise RuntimeError("invariant: duplicate action execution blocked")
            executed = self._execute(trusted_user_id, sanitized)
            action_executed = True
            trace.executed_action = {
                "action_type": sanitized.action_type.value,
                "result": executed,
            }
            ticket_id = executed.get("ticket_id")
            if ticket_id:
                trace.ticket_ids = [ticket_id]
            trace.answer = sanitized.answer_text or "Action executed."
            self._remember(
                user_message,
                trace.answer,
                sanitized.action_type.value,
                ticket_id if isinstance(ticket_id, str) else None,
            )
            return self._finalize(trace, started)

        except ProviderError as exc:
            trace.provider_error_category = exc.category.value
            trace.error = exc.safe_message
            trace.structured_output_valid = (
                False
                if exc.category.value == "SCHEMA_VALIDATION_ERROR"
                else trace.structured_output_valid
            )
            if not trace.answer:
                trace.answer = "Xin lỗi, yêu cầu không thể xử lý."
            trace.executed_action = None
            self._remember(user_message, trace.answer, "ERROR", None)
            return self._finalize(trace, started)
        except Exception as exc:
            msg = str(exc)
            if "AIza" in msg or "api_key" in msg.lower() or "Bearer " in msg:
                msg = "runtime error (credential redacted)"
            trace.error = msg
            if not trace.answer:
                trace.answer = "Xin lỗi, yêu cầu không thể xử lý."
            if (trace.policy_decision or {}).get("decision") != PolicyDecisionCode.ALLOW.value:
                trace.executed_action = None
            return self._finalize(trace, started)

    def _apply_call_metadata(self, trace: ExecutionTrace, call) -> None:
        trace.prompt_template_version = call.prompt_template_version
        trace.response_schema_version = call.response_schema_version
        trace.input_tokens = call.input_tokens
        trace.output_tokens = call.output_tokens
        trace.provider_attempts = call.attempts
        trace.token_estimate = call.input_tokens + call.output_tokens
        trace.estimated_cost_usd = call.estimated_cost_usd
        trace.actual_cost_usd = call.actual_cost_usd
        trace.finish_reason = call.finish_reason
        trace.request_id = call.request_id
        trace.raw_response_sha256 = call.raw_response_sha256
        trace.structured_output_valid = call.structured_output_valid
        if call.provider_error_category:
            trace.provider_error_category = call.provider_error_category

    def _remember(
        self,
        user_message: str,
        answer: str,
        action_type: str,
        ticket_id: str | None,
    ) -> None:
        self.conversation.append(
            ConversationTurn(
                user_message=user_message,
                assistant_answer=answer,
                action_type=action_type,
                ticket_id=ticket_id,
            )
        )

    def _lookup_for_action(
        self, trusted_user_id: str, action: StructuredAction
    ) -> TicketLookupOutcome:
        needs_ticket = action.action_type in {
            ActionType.UPDATE_TICKET,
            ActionType.CLOSE_TICKET,
            ActionType.GET_TICKET_STATUS,
        }
        if not needs_ticket:
            return TicketLookupOutcome(code=TicketLookupCode.NOT_REQUESTED, ticket=None)
        return self.tickets.lookup_ticket(
            trusted_user_id=trusted_user_id, ticket_id=action.ticket_id
        )

    def _resolve_ticket_refs(
        self, trusted_user_id: str, action: StructuredAction
    ) -> StructuredAction:
        ref = action.ticket_id
        if not ref or not str(ref).startswith("$"):
            return action
        owned = self.tickets.list_user_tickets(trusted_user_id=trusted_user_id)
        if ref == "$INITIAL_TICKET":
            if len(owned) != 1:
                return action.model_copy(
                    update={
                        "action_type": ActionType.CLARIFY,
                        "ticket_id": None,
                        "reason": "Ambiguous ticket reference; clarification required",
                    }
                )
            return action.model_copy(update={"ticket_id": owned[0].ticket_id})
        if ref == "$LATEST_OWNED_TICKET":
            if not owned:
                return action.model_copy(
                    update={
                        "action_type": ActionType.CLARIFY,
                        "ticket_id": None,
                        "reason": "No owned ticket available",
                    }
                )
            return action.model_copy(update={"ticket_id": owned[-1].ticket_id})
        return action.model_copy(
            update={
                "action_type": ActionType.CLARIFY,
                "ticket_id": None,
                "reason": f"Unknown symbolic ticket ref: {ref}",
            }
        )

    def _execute(self, trusted_user_id: str, action: StructuredAction) -> dict:
        if action.action_type == ActionType.CREATE_TICKET:
            ticket = self.tickets.create_ticket(
                trusted_user_id=trusted_user_id,
                complaint_type=action.complaint_type or "GENERAL",
                summary=action.fields.get("summary") or action.reason,
                ticket_id=action.fields.get("ticket_id"),
            )
            return {"ticket_id": ticket.ticket_id, "status": ticket.status.value}

        if action.action_type == ActionType.UPDATE_TICKET:
            assert action.ticket_id
            if action.requested_transition:
                ticket = self.tickets.transition_ticket(
                    trusted_user_id=trusted_user_id,
                    ticket_id=action.ticket_id,
                    to_status=action.requested_transition,
                )
            else:
                note = action.fields.get("note") or action.fields.get("summary")
                ticket = self.tickets.update_ticket(
                    trusted_user_id=trusted_user_id,
                    ticket_id=action.ticket_id,
                    summary=note if note is not None else action.fields.get("summary"),
                    resolution=action.fields.get("resolution"),
                )
            return {"ticket_id": ticket.ticket_id, "status": ticket.status.value}

        if action.action_type == ActionType.CLOSE_TICKET:
            assert action.ticket_id
            ticket = self.tickets.close_ticket(
                trusted_user_id=trusted_user_id, ticket_id=action.ticket_id
            )
            return {"ticket_id": ticket.ticket_id, "status": ticket.status.value}

        if action.action_type == ActionType.GET_TICKET_STATUS:
            assert action.ticket_id
            ticket = self.tickets.get_ticket(
                trusted_user_id=trusted_user_id, ticket_id=action.ticket_id
            )
            return {"ticket_id": ticket.ticket_id, "status": ticket.status.value}

        return {}

    def _finalize(self, trace: ExecutionTrace, started: datetime) -> ExecutionTrace:
        ended = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
        trace.latency_ms = (ended - started).total_seconds() * 1000.0
        trace.final_state_sha256 = self.tickets.business_state_sha256()
        trace.cumulative_run_cost_usd = self.cost_guard.cumulative_run_cost_usd
        if not trace.timestamp:
            trace.timestamp = ended.isoformat(timespec="seconds")
        return trace
