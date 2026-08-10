from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TicketStatus(StrEnum):
    OPEN = "OPEN"
    WAITING_CUSTOMER = "WAITING_CUSTOMER"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class ActionType(StrEnum):
    NONE = "NONE"
    CREATE_TICKET = "CREATE_TICKET"
    UPDATE_TICKET = "UPDATE_TICKET"
    CLOSE_TICKET = "CLOSE_TICKET"
    CLARIFY = "CLARIFY"
    GET_TICKET_STATUS = "GET_TICKET_STATUS"


class PolicyDecisionCode(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    CLARIFY = "CLARIFY"
    NONE = "NONE"


class TicketLookupCode(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    NOT_REQUESTED = "NOT_REQUESTED"


class StructuredAction(BaseModel):
    action_type: ActionType
    user_id: str | None = None  # LLM-proposed; must not override trusted context
    ticket_id: str | None = None
    complaint_type: str | None = None
    requested_transition: TicketStatus | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    confidence: float = 0.0
    answer_text: str = ""


class PolicyResult(BaseModel):
    decision: PolicyDecisionCode
    reason_code: str
    message: str
    sanitized_action: StructuredAction | None = None


class TicketRecord(BaseModel):
    ticket_id: str
    user_id: str
    complaint_type: str
    status: TicketStatus
    summary: str = ""
    resolution: str | None = None
    version: int = 1
    created_at: str
    updated_at: str


class TicketLookupOutcome(BaseModel):
    code: TicketLookupCode
    ticket: TicketRecord | None = None


class ExecutionTrace(BaseModel):
    baseline: str = "B0"
    run_id: str = ""
    scenario_id: str = ""
    query_id: str = ""
    session_id: str = ""
    trusted_user_id: str
    provider: str
    model_id: str
    prompt_template_version: str = ""
    response_schema_version: str = ""
    scenario_db_path: str = ""
    initial_state_sha256: str = ""
    final_state_sha256: str = ""
    ticket_lookup_outcome: str = TicketLookupCode.NOT_REQUESTED.value
    policy_reason_code: str | None = None
    proposed_action: dict[str, Any] | None = None
    policy_decision: dict[str, Any] | None = None
    executed_action: dict[str, Any] | None = None
    ticket_ids: list[str] = Field(default_factory=list)
    answer: str = ""
    latency_ms: float = 0.0
    token_estimate: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    provider_attempts: int = 0
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0
    cumulative_run_cost_usd: float = 0.0
    finish_reason: str | None = None
    request_id: str | None = None
    raw_response_sha256: str | None = None
    provider_error_category: str | None = None
    structured_output_valid: bool | None = None
    error: str | None = None
    memory_enabled: bool = False
    timestamp: str = ""
