"""PlantIQ LLM Provider Abstraction Package."""

from backend.app.llm.anthropic import AnthropicProvider
from backend.app.llm.base import BaseProvider
from backend.app.llm.exceptions import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderRateLimited,
    ProviderRefused,
    ProviderServiceUnavailable,
    ProviderTimeout,
)
from backend.app.llm.factory import get_llm_provider
from backend.app.llm.hooks import InMemoryUsageRecorder, UsageRecord, UsageRecorder
from backend.app.llm.openai_compatible import OpenAICompatibleProvider
from backend.app.llm.types import (
    Message,
    ProviderResponse,
    Role,
    StopReason,
    StreamDelta,
    TextBlock,
    ToolDefinition,
    ToolUseBlock,
    Usage,
)

__all__ = [
    "BaseProvider",
    "AnthropicProvider",
    "OpenAICompatibleProvider",
    "get_llm_provider",
    "ProviderError",
    "ProviderTimeout",
    "ProviderRateLimited",
    "ProviderRefused",
    "ProviderAuthenticationError",
    "ProviderServiceUnavailable",
    "Message",
    "ProviderResponse",
    "Role",
    "StopReason",
    "StreamDelta",
    "TextBlock",
    "ToolDefinition",
    "ToolUseBlock",
    "Usage",
    "UsageRecorder",
    "UsageRecord",
    "InMemoryUsageRecorder",
]
