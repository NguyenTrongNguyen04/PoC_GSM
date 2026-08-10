from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from pydantic import ValidationError

from poc_runtime.cost_guard import CostGuard
from poc_runtime.llm.base import LLMClient
from poc_runtime.llm.errors import (
    TRANSIENT_CATEGORIES,
    ProviderError,
    ProviderErrorCategory,
)
from poc_runtime.llm.prompt import build_gemini_request_payload
from poc_runtime.llm.types import (
    ALLOWED_FIELD_KEYS,
    ALLOWED_SYMBOLIC_TICKET_REFS,
    PROMPT_TEMPLATE_VERSION,
    RESPONSE_SCHEMA_VERSION,
    EphemeralConversationContext,
    LLMCallResult,
    structured_action_json_schema,
)
from poc_runtime.models import StructuredAction


@dataclass
class GeminiTransportResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str | None = None
    request_id: str | None = None
    status_code: int = 200


class GeminiTransport(Protocol):
    def generate(self, *, model: str, payload: dict[str, Any], timeout_seconds: float) -> GeminiTransportResponse:
        ...


class MockGeminiTransport:
    """Offline deterministic transport for tests — never opens a network socket."""

    def __init__(
        self,
        responses: list[GeminiTransportResponse] | None = None,
        *,
        errors: list[ProviderError] | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.errors = list(errors or [])
        self.calls: list[dict[str, Any]] = []

    def generate(
        self, *, model: str, payload: dict[str, Any], timeout_seconds: float
    ) -> GeminiTransportResponse:
        self.calls.append({"model": model, "payload": payload, "timeout": timeout_seconds})
        if self.errors:
            raise self.errors.pop(0)
        if not self.responses:
            raise ProviderError(
                ProviderErrorCategory.UNKNOWN_PROVIDER_ERROR,
                "mock transport exhausted",
                retryable=False,
            )
        return self.responses.pop(0)


class LiveGeminiTransport:
    """Official google-genai transport. Must not be constructed without live gates."""

    def __init__(self, *, api_key: str) -> None:
        # Lazy import — import itself does not call network.
        from google import genai  # type: ignore

        self._client = genai.Client(api_key=api_key)

    def generate(
        self, *, model: str, payload: dict[str, Any], timeout_seconds: float
    ) -> GeminiTransportResponse:
        from google.genai import types  # type: ignore

        user_message = payload.get("user_message") or ""
        system = payload.get("system_instruction") or ""
        # Bundle non-label context as a single user content block.
        contents = json.dumps(
            {
                "execution_context": payload.get("execution_context"),
                "conversation_window": payload.get("conversation_window"),
                "user_message": user_message,
            },
            ensure_ascii=False,
        )
        try:
            response = self._client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_json_schema=structured_action_json_schema(),
                    http_options={"timeout": int(timeout_seconds * 1000)},
                ),
            )
        except Exception as exc:  # noqa: BLE001 — mapped to typed categories
            raise _map_sdk_exception(exc) from None

        text = getattr(response, "text", None) or ""
        usage = getattr(response, "usage_metadata", None)
        in_tok = int(getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
        out_tok = int(getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
        finish = None
        if getattr(response, "candidates", None):
            finish = str(getattr(response.candidates[0], "finish_reason", None) or "") or None
        return GeminiTransportResponse(
            text=text,
            input_tokens=in_tok,
            output_tokens=out_tok,
            finish_reason=finish,
            request_id=None,
            status_code=200,
        )


def _map_sdk_exception(exc: Exception) -> ProviderError:
    msg = str(exc)
    low = msg.lower()
    # Never surface secrets.
    if "aiza" in low or "api key" in low or "authorization" in low:
        msg = "provider authentication/configuration error"
    if "401" in low or "unauthor" in low or "api key" in low:
        return ProviderError(ProviderErrorCategory.AUTH_ERROR, msg, retryable=False, status_code=401)
    if "403" in low or "permission" in low:
        return ProviderError(ProviderErrorCategory.PERMISSION_ERROR, msg, retryable=False, status_code=403)
    if "404" in low or "not found" in low or "model" in low and "not" in low:
        return ProviderError(ProviderErrorCategory.MODEL_NOT_FOUND, msg, retryable=False, status_code=404)
    if "429" in low or "rate" in low:
        return ProviderError(ProviderErrorCategory.RATE_LIMITED, msg, retryable=True, status_code=429)
    if "timeout" in low or "timed out" in low:
        return ProviderError(ProviderErrorCategory.TIMEOUT, msg, retryable=True)
    if "500" in low or "502" in low or "503" in low or "504" in low:
        return ProviderError(ProviderErrorCategory.SERVER_ERROR, msg, retryable=True, status_code=500)
    if "safety" in low or "blocked" in low:
        return ProviderError(ProviderErrorCategory.SAFETY_BLOCKED, msg, retryable=False)
    return ProviderError(ProviderErrorCategory.UNKNOWN_PROVIDER_ERROR, msg, retryable=False)


class GeminiLLMClient(LLMClient):
    """
    Gemini structured-action provider.

    Live network requires allow_paid=True + live_enabled config + CLI confirmation.
    Tests inject MockGeminiTransport — no network, no SDK call required.
    """

    provider_name = "gemini"
    model_id = "gemini-3.5-flash-lite"
    model_runtime_validation = "pending_canary"

    def __init__(
        self,
        *,
        model_id: str | None = None,
        api_key: str | None = None,
        allow_paid: bool = False,
        live_enabled: bool = False,
        timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        cost_guard: CostGuard | None = None,
        transport: GeminiTransport | None = None,
        sleeper: Callable[[float], None] | None = None,
        backoff_seconds: tuple[float, ...] = (1.0, 2.0),
    ) -> None:
        self.model_id = model_id or os.environ.get("GEMINI_MODEL", self.model_id)
        self._api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY")
        self.allow_paid = allow_paid
        self.live_enabled = live_enabled
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.cost_guard = cost_guard
        self.sleeper = sleeper or time.sleep
        self.backoff_seconds = backoff_seconds
        if transport is not None:
            self.transport = transport
        elif allow_paid and live_enabled:
            if not self._api_key:
                raise ProviderError(
                    ProviderErrorCategory.CONFIG_ERROR,
                    "GEMINI_API_KEY missing",
                    retryable=False,
                )
            self.transport = LiveGeminiTransport(api_key=self._api_key)
        else:
            self.transport = None

    def propose_action(
        self,
        *,
        trusted_user_id: str,
        user_message: str,
        context: dict[str, Any] | None = None,
        conversation: EphemeralConversationContext | None = None,
    ) -> LLMCallResult:
        if self.transport is None:
            raise ProviderError(
                ProviderErrorCategory.CONFIG_ERROR,
                "Gemini live gate closed (live_enabled/allow_paid/transport)",
                retryable=False,
            )
        context = context or {}
        payload = build_gemini_request_payload(
            trusted_user_id=trusted_user_id,
            user_message=user_message,
            query_id=str(context.get("query_id") or ""),
            scenario_id=str(context.get("scenario_id") or ""),
            conversation=conversation,
            owned_ticket_ids=list(context.get("owned_ticket_ids") or []),
        )

        attempts = 0
        last_error: ProviderError | None = None
        while attempts < self.max_attempts:
            attempts += 1
            est_in = max(1, len(json.dumps(payload, ensure_ascii=False)) // 4)
            est_out = 256
            estimate = None
            if self.cost_guard is not None:
                estimate = self.cost_guard.estimate(input_tokens=est_in, output_tokens=est_out)
                self.cost_guard.authorize(estimate)
            try:
                raw = self.transport.generate(
                    model=self.model_id,
                    payload=payload,
                    timeout_seconds=self.timeout_seconds,
                )
                action = self._parse_structured(raw.text)
                actual_est = None
                actual_cost = 0.0
                if self.cost_guard is not None:
                    actual_est = self.cost_guard.estimate(
                        input_tokens=raw.input_tokens or est_in,
                        output_tokens=raw.output_tokens or 0,
                    )
                    actual_cost = actual_est.estimated_usd
                    self.cost_guard.commit(actual_est, actual_usd=actual_cost)
                raw_hash = hashlib.sha256(raw.text.encode("utf-8")).hexdigest()
                return LLMCallResult(
                    action=action,
                    provider=self.provider_name,
                    model_id=self.model_id,
                    prompt_template_version=PROMPT_TEMPLATE_VERSION,
                    response_schema_version=RESPONSE_SCHEMA_VERSION,
                    input_tokens=raw.input_tokens,
                    output_tokens=raw.output_tokens,
                    attempts=attempts,
                    finish_reason=raw.finish_reason,
                    request_id=raw.request_id,
                    raw_response_sha256=raw_hash,
                    estimated_cost_usd=estimate.estimated_usd if estimate else 0.0,
                    actual_cost_usd=actual_cost,
                    structured_output_valid=True,
                )
            except ProviderError as exc:
                last_error = exc
                if estimate is not None and self.cost_guard is not None:
                    # Conservative: charge reserved estimate when usage unknown.
                    self.cost_guard.release_reservation_keep_charge(estimate)
                if not exc.retryable or exc.category not in TRANSIENT_CATEGORIES:
                    raise
                if attempts >= self.max_attempts:
                    raise
                delay = self.backoff_seconds[min(attempts - 1, len(self.backoff_seconds) - 1)]
                delay = min(delay, 60.0)
                self.sleeper(delay)
            except ValidationError as exc:
                if estimate is not None and self.cost_guard is not None:
                    self.cost_guard.release_reservation_keep_charge(estimate)
                raise ProviderError(
                    ProviderErrorCategory.SCHEMA_VALIDATION_ERROR,
                    f"structured output validation failed: {exc.error_count()} error(s)",
                    retryable=False,
                ) from None

        assert last_error is not None
        raise last_error

    def _parse_structured(self, text: str) -> StructuredAction:
        if not text or not text.strip():
            raise ProviderError(
                ProviderErrorCategory.SCHEMA_VALIDATION_ERROR,
                "empty structured response",
                retryable=False,
            )
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError(
                ProviderErrorCategory.SCHEMA_VALIDATION_ERROR,
                f"invalid JSON: {exc.msg}",
                retryable=False,
            ) from None
        if not isinstance(data, dict):
            raise ProviderError(
                ProviderErrorCategory.SCHEMA_VALIDATION_ERROR,
                "structured response must be an object",
                retryable=False,
            )
        fields = data.get("fields") or {}
        if not isinstance(fields, dict):
            raise ProviderError(
                ProviderErrorCategory.SCHEMA_VALIDATION_ERROR,
                "fields must be an object",
                retryable=False,
            )
        unknown = set(fields) - ALLOWED_FIELD_KEYS
        if unknown:
            raise ProviderError(
                ProviderErrorCategory.SCHEMA_VALIDATION_ERROR,
                f"fields contain non-allowlisted keys: {sorted(unknown)}",
                retryable=False,
            )
        ticket_id = data.get("ticket_id")
        if isinstance(ticket_id, str) and ticket_id.startswith("$"):
            if ticket_id not in ALLOWED_SYMBOLIC_TICKET_REFS:
                data = {
                    **data,
                    "action_type": "CLARIFY",
                    "ticket_id": None,
                    "reason": f"Unknown symbolic ticket ref: {ticket_id}",
                }
        try:
            return StructuredAction.model_validate(data)
        except ValidationError as exc:
            raise ProviderError(
                ProviderErrorCategory.SCHEMA_VALIDATION_ERROR,
                f"pydantic validation failed: {exc.error_count()} error(s)",
                retryable=False,
            ) from None
