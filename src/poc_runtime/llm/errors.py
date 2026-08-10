from __future__ import annotations

from enum import StrEnum


class ProviderErrorCategory(StrEnum):
    CONFIG_ERROR = "CONFIG_ERROR"
    AUTH_ERROR = "AUTH_ERROR"
    PERMISSION_ERROR = "PERMISSION_ERROR"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    SERVER_ERROR = "SERVER_ERROR"
    SCHEMA_VALIDATION_ERROR = "SCHEMA_VALIDATION_ERROR"
    SAFETY_BLOCKED = "SAFETY_BLOCKED"
    BUDGET_REJECTED = "BUDGET_REJECTED"
    UNKNOWN_PROVIDER_ERROR = "UNKNOWN_PROVIDER_ERROR"


class ProviderError(Exception):
    """Safe provider error — never attach API keys or auth headers."""

    def __init__(
        self,
        category: ProviderErrorCategory,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        self.category = category
        self.retryable = retryable
        self.status_code = status_code
        # Strip common secret patterns from message surfaces.
        safe = message
        for token in ("Bearer ", "AIza", "api_key=", "API_KEY="):
            if token in safe:
                safe = "provider error (credential redacted)"
                break
        super().__init__(safe)
        self.safe_message = safe


TRANSIENT_CATEGORIES = {
    ProviderErrorCategory.RATE_LIMITED,
    ProviderErrorCategory.TIMEOUT,
    ProviderErrorCategory.SERVER_ERROR,
}
