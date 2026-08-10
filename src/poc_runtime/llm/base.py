from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from poc_runtime.llm.types import EphemeralConversationContext, LLMCallResult


class LLMClient(ABC):
    provider_name: str = "base"
    model_id: str = "unknown"

    @abstractmethod
    def propose_action(
        self,
        *,
        trusted_user_id: str,
        user_message: str,
        context: dict[str, Any] | None = None,
        conversation: EphemeralConversationContext | None = None,
    ) -> LLMCallResult:
        raise NotImplementedError
