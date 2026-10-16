"""Exception types for the AI layer."""


class AIError(Exception):
    """Base class for AI-layer errors."""


class AIConfigError(AIError):
    """Raised when a required provider is not configured (missing API key)."""


class AIProviderError(AIError):
    """Raised when a provider call fails (timeout, rate limit, invalid response)."""


class AIInvalidResponseError(AIProviderError):
    """Raised when a provider returns an unusable response."""
