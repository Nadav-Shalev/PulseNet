"""The provider interface, and the HTTP plumbing the network providers share.

A provider turns a prompt (plus optional system text) into reply text with one
request, and does nothing else: the daily limit, the usage log and the log lines
live in LLMService, so adding a provider is one module in this package plus one
builder in ../config.py.
"""

from typing import Optional, Protocol, runtime_checkable
from urllib.parse import urlsplit

import requests

from ..errors import LLMError, LLMRateLimited, LLMTimeout

# The longest wait for the connection itself; the reply gets LLM_TIMEOUT_SECONDS.
CONNECT_TIMEOUT_SECONDS = 5
# A provider's error message is cut to this length before it reaches a log.
MAX_ERROR_CHARS = 200


@runtime_checkable
class Provider(Protocol):
    """What LLMService needs from a provider."""

    name: str              # 'fake', 'openai_compat' or 'course': the usage log's provider
    model: Optional[str]   # the usage log's model; None when the provider offers no choice

    def describe(self) -> str:
        """One line for whoever runs the app: provider, model and host, never the key."""

    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """The reply text, or an LLMError."""


def scrub(text, secret):
    """``text`` with every occurrence of ``secret`` (the API key) replaced by '***'."""
    return text.replace(secret, "***") if secret else text


def host_of(url):
    """The host (and port) of ``url``: never its path, query or a password in it."""
    parts = urlsplit(url)
    host = parts.hostname or "?"
    return f"{host}:{parts.port}" if parts.port else host


def post_json(http, url, *, headers, body, timeout, secret, provider):
    """POST ``body`` as JSON to ``url`` and return the decoded JSON reply.

    ``http`` is the requests module (or a test double). Every failure becomes an
    LLMError with ``secret`` scrubbed from its message: a 429 is LLMRateLimited and
    no answer within ``timeout`` seconds is LLMTimeout. No retries: see LLMService.
    """
    try:
        response = http.post(url, json=body, headers=headers,
                             timeout=(min(CONNECT_TIMEOUT_SECONDS, timeout), timeout))
    except requests.Timeout as exc:  # ConnectTimeout or ReadTimeout
        raise LLMTimeout(f"{provider}: timed out ({type(exc).__name__})") from None
    except requests.RequestException as exc:
        # Only the exception's type: its text can carry the full URL.
        raise LLMError(f"{provider}: cannot reach the server ({type(exc).__name__})") from None

    status = response.status_code
    if status == 429:
        raise LLMRateLimited(f"{provider}: rate limited (HTTP 429){_detail(response, secret)}",
                             retry_after=_retry_after(response.headers.get("Retry-After")))
    if status in (401, 403):
        raise LLMError(f"{provider}: the server rejected the API key "
                       f"(HTTP {status}){_detail(response, secret)}")
    if status == 404:
        raise LLMError(f"{provider}: model or URL not found (HTTP 404){_detail(response, secret)}")
    if status >= 400:
        raise LLMError(f"{provider}: HTTP {status}{_detail(response, secret)}")
    try:
        return response.json()
    except ValueError:
        raise LLMError(f"{provider}: the reply is not JSON (HTTP {status})") from None


def _retry_after(value):
    """Retry-After in whole seconds, or None (it may also be an HTTP date, which
    nothing here needs)."""
    value = (value or "").strip()
    return int(value) if value.isdigit() else None


def _detail(response, secret):
    """': <message>' from an error reply, scrubbed and then cut short, or ''.
    Scrubbing first matters: cutting first could leave half a key behind."""
    try:
        message = _error_message(response.json())
    except ValueError:
        message = None
    text = " ".join(str(response.text if message is None else message).split())
    text = scrub(text, secret)[:MAX_ERROR_CHARS]
    return f": {text}" if text else ""


def _error_message(data):
    """The message in an error body: OpenAI and Gemini send {"error": {"message"}}
    (Gemini sometimes inside a list), API Gateway sends {"message"}."""
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        return None
    error = data.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    if isinstance(error, str):
        return error
    message = data.get("message")
    return message if isinstance(message, str) else None
