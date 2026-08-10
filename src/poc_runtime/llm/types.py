from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from poc_runtime.models import StructuredAction


PROMPT_TEMPLATE_VERSION = "b0_action_v1"
RESPONSE_SCHEMA_VERSION = "structured_action_v1"

ALLOWED_FIELD_KEYS = frozenset({"summary", "note", "resolution", "ticket_id"})
ALLOWED_SYMBOLIC_TICKET_REFS = frozenset({"$INITIAL_TICKET", "$LATEST_OWNED_TICKET"})


class LLMCallResult(BaseModel):
    action: StructuredAction
    provider: str
    model_id: str
    prompt_template_version: str = PROMPT_TEMPLATE_VERSION
    response_schema_version: str = RESPONSE_SCHEMA_VERSION
    input_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 1
    finish_reason: str | None = None
    request_id: str | None = None
    raw_response_sha256: str | None = None
    estimated_cost_usd: float = 0.0
    actual_cost_usd: float = 0.0
    structured_output_valid: bool = True
    provider_error_category: str | None = None


def structured_action_json_schema() -> dict[str, Any]:
    """Versioned JSON Schema for Gemini response_json_schema."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "action_type",
            "reason",
            "confidence",
            "answer_text",
        ],
        "properties": {
            "action_type": {
                "type": "string",
                "enum": [
                    "NONE",
                    "CREATE_TICKET",
                    "UPDATE_TICKET",
                    "CLOSE_TICKET",
                    "CLARIFY",
                    "GET_TICKET_STATUS",
                ],
            },
            "user_id": {"type": ["string", "null"]},
            "ticket_id": {"type": ["string", "null"]},
            "complaint_type": {"type": ["string", "null"]},
            "requested_transition": {
                "anyOf": [
                    {
                        "type": "string",
                        "enum": [
                            "OPEN",
                            "WAITING_CUSTOMER",
                            "IN_REVIEW",
                            "RESOLVED",
                            "CLOSED",
                        ],
                    },
                    {"type": "null"},
                ]
            },
            "fields": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "summary": {"type": "string"},
                    "note": {"type": "string"},
                    "resolution": {"type": "string"},
                    "ticket_id": {"type": "string"},
                },
            },
            "reason": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "answer_text": {"type": "string"},
        },
    }


class ConversationTurn(BaseModel):
    user_message: str
    assistant_answer: str = ""
    action_type: str = "NONE"
    ticket_id: str | None = None


class EphemeralConversationContext(BaseModel):
    """Bounded in-run context — not MAG Memory."""

    max_turns: int = 4
    turns: list[ConversationTurn] = Field(default_factory=list)

    def append(self, turn: ConversationTurn) -> None:
        self.turns.append(turn)
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns :]

    def reset(self) -> None:
        self.turns.clear()

    def as_prompt_block(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for t in self.turns:
            out.append(
                {
                    "user_message": t.user_message,
                    "assistant_answer": t.assistant_answer,
                    "action_type": t.action_type,
                    "ticket_id": t.ticket_id or "",
                }
            )
        return out
