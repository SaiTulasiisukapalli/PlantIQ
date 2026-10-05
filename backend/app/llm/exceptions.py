"""Typed exceptions for LLM provider abstraction."""

from __future__ import annotations

from typing import Optional


class ProviderError(Exception):
    """Base exception for all LLM provider failures."""

    def __init__(self, message: str, provider: str = "", status_code: Optional[int] = None) -> None:
        self.message = message
        self.provider = provider
        self.status_code = status_code
        super().__init__(f"[{provider or 'LLM'}] {message}")


class ProviderTimeout(ProviderError):
    """Raised when an LLM provider request exceeds the configured timeout."""

    def __init__(self, message: str = "Request timed out", provider: str = "", timeout_s: float = 0.0) -> None:
        self.timeout_s = timeout_s
        super().__init__(f"{message} after {timeout_s:.1f}s", provider=provider, status_code=408)


class ProviderRateLimited(ProviderError):
    """Raised when an LLM provider returns a 429 Too Many Requests response."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        provider: str = "",
        retry_after: Optional[float] = None,
    ) -> None:
        self.retry_after = retry_after
        detail = f"{message} (retry_after: {retry_after}s)" if retry_after is not None else message
        super().__init__(detail, provider=provider, status_code=429)


class ProviderRefused(ProviderError):
    """Raised when an LLM provider explicitly rejects or refuses a request (e.g., safety, 400/403)."""

    def __init__(self, message: str = "Request refused by model", provider: str = "", status_code: int = 400) -> None:
        super().__init__(message, provider=provider, status_code=status_code)


class ProviderAuthenticationError(ProviderError):
    """Raised when API key or authorization fails (401)."""

    def __init__(self, message: str = "Invalid API key or unauthorized", provider: str = "") -> None:
        super().__init__(message, provider=provider, status_code=401)


class ProviderServiceUnavailable(ProviderError):
    """Raised when the remote service is unavailable (5xx error after retries)."""

    def __init__(self, message: str = "Service unavailable", provider: str = "", status_code: int = 503) -> None:
        super().__init__(message, provider=provider, status_code=status_code)
