"""Build the LLM service from environment variables (backend/.env).

    LLM_PROVIDER          fake | openai_compat | course. Unset means the LLM is off
                          (LLMConfigError): deliberately not 'fake', so production
                          never answers with canned text by mistake.
    LLM_TIMEOUT_SECONDS   1 to 120, default 15. A web request must finish within
                          gunicorn's 30-second worker timeout, so keep it below that.
    LLM_DAILY_LIMIT       calls per UTC day, across every process, default 100.
                          0 turns the LLM off.
    openai_compat         LLM_BASE_URL, LLM_MODEL, LLM_API_KEY
    course                LLM_API_URL, LLM_API_KEY

Error messages name a variable, never its value: a key must never reach a log.
"""

from urllib.parse import urlsplit

from .errors import LLMConfigError
from .providers import CourseProvider, FakeProvider, OpenAICompatProvider
from .service import LLMService
from .usage import DbUsageStore

DEFAULT_TIMEOUT_SECONDS = 15
MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS = 1, 120
DEFAULT_DAILY_LIMIT = 100


def from_env(env, *, connect):
    """An LLMService set up from ``env`` (e.g. ``os.environ``) that logs to the
    llm_usage table through ``connect``, a callable returning a new DB connection.
    Raises LLMConfigError when a setting is missing or invalid."""
    name = _get(env, "LLM_PROVIDER")
    if not name:
        raise LLMConfigError("LLM_PROVIDER is not set, so the LLM is off "
                             f"(set it to one of: {', '.join(_BUILDERS)})")
    if name not in _BUILDERS:
        raise LLMConfigError(f"LLM_PROVIDER must be one of: {', '.join(_BUILDERS)}")
    provider = _BUILDERS[name](env, _timeout(env))
    return LLMService(provider, DbUsageStore(connect), daily_limit=_daily_limit(env))


def _get(env, name):
    return (env.get(name) or "").strip()


def _timeout(env):
    raw = _get(env, "LLM_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        seconds = float(raw)
    except ValueError:
        seconds = None
    # NaN fails both comparisons, so it is rejected too.
    if seconds is None or not MIN_TIMEOUT_SECONDS <= seconds <= MAX_TIMEOUT_SECONDS:
        raise LLMConfigError(f"LLM_TIMEOUT_SECONDS must be a number of seconds from "
                             f"{MIN_TIMEOUT_SECONDS} to {MAX_TIMEOUT_SECONDS}")
    return seconds


def _daily_limit(env):
    raw = _get(env, "LLM_DAILY_LIMIT")
    if not raw:
        return DEFAULT_DAILY_LIMIT
    try:
        limit = int(raw)
    except ValueError:
        limit = -1
    if limit < 0:
        raise LLMConfigError("LLM_DAILY_LIMIT must be a whole number, 0 or more")
    return limit


def _required(env, name, provider):
    value = _get(env, name)
    if not value:
        raise LLMConfigError(f"{name} is not set (LLM_PROVIDER={provider} needs it)")
    return value


def _url(env, name, provider):
    value = _required(env, name, provider)
    parts = urlsplit(value)
    try:
        parts.port  # a port that is not a number raises ValueError
    except ValueError:
        parts = None
    if parts is None or parts.scheme not in ("http", "https") or not parts.hostname:
        raise LLMConfigError(f"{name} must be an http:// or https:// URL")
    return value


def _fake(env, timeout):
    return FakeProvider()


def _openai_compat(env, timeout):
    return OpenAICompatProvider(
        base_url=_url(env, "LLM_BASE_URL", "openai_compat"),
        model=_required(env, "LLM_MODEL", "openai_compat"),
        api_key=_required(env, "LLM_API_KEY", "openai_compat"),
        timeout=timeout,
    )


def _course(env, timeout):
    return CourseProvider(
        url=_url(env, "LLM_API_URL", "course"),
        api_key=_required(env, "LLM_API_KEY", "course"),
        timeout=timeout,
    )


# LLM_PROVIDER -> how to build that provider from the environment. A new provider
# is a module in providers/ plus one entry here.
_BUILDERS = {
    FakeProvider.name: _fake,
    OpenAICompatProvider.name: _openai_compat,
    CourseProvider.name: _course,
}
