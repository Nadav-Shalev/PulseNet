"""Errors raised by the LLM service.

Every failure a caller should survive is an ``LLMError``: the caller catches it and
falls back (moderation to a word list, AI help to "try again later", an agent skips
its turn). The subclasses say why, for the usage log and for callers that want to
tell the user something more specific.
"""


class LLMError(Exception):
    """The LLM gave no usable reply. Callers catch this and fall back."""


class LLMConfigError(LLMError):
    """An LLM setting in the environment is missing or invalid. The message names
    the variable, never its value."""


class LLMTimeout(LLMError):
    """The provider did not answer within LLM_TIMEOUT_SECONDS."""


class LLMRateLimited(LLMError):
    """The provider answered 429: its quota or rate limit is used up.
    ``retry_after`` is its Retry-After header in seconds, when it sent a number."""

    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


class LLMLimitReached(LLMError):
    """Our own daily limit (LLM_DAILY_LIMIT) is used up, so nothing was sent."""


class LLMBadReply(LLMError):
    """The provider answered, but not in the shape the caller asked for (no JSON
    object, or one with the wrong fields). The call itself is logged as 'ok'."""
