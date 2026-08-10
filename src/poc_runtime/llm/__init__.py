"""LLM provider package."""

from poc_runtime.llm.base import LLMClient
from poc_runtime.llm.errors import ProviderError, ProviderErrorCategory
from poc_runtime.llm.fake import FakeLLMClient
from poc_runtime.llm.types import LLMCallResult

__all__ = [
    "LLMClient",
    "FakeLLMClient",
    "LLMCallResult",
    "ProviderError",
    "ProviderErrorCategory",
]


def __getattr__(name: str):
    if name in {"GeminiLLMClient", "MockGeminiTransport"}:
        from poc_runtime.llm import gemini as _gemini

        return getattr(_gemini, name)
    raise AttributeError(name)
