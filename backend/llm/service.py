"""LLMService: one LLM call, with the house rules around it.

    reply = service.complete(text, system="You are a careful editor.",
                             purpose="ai_correct", user_id=42)

Around every call: the daily limit (LLM_DAILY_LIMIT calls per UTC day, counted in
the usage log), the provider's timeout, one usage row and one log line. Every
failure is an LLMError, which the caller catches to fall back. There are no
retries: a retry spends the quota twice and keeps the user waiting, and the
caller's fallback covers a failed call anyway.

The limit is soft. The count is read before the call and the row is written after
the provider answers, seconds later, so every caller that checks in between sees
the same count: the limit can be exceeded by up to the number of calls running at
the same moment. Today that is one gunicorn worker, plus later the agents' timer.
If many agents ever call at once, revisit with a reservation row (insert first,
then count) or a daily counter row updated under SELECT ... FOR UPDATE.
"""

import logging
import re
import time
from datetime import datetime, timezone

from .errors import LLMError, LLMLimitReached, LLMRateLimited, LLMTimeout
from .usage import UsageRecord

log = logging.getLogger("pulsenet.llm")

# Prompt and system text together. Callers trim long input (a whole article, say)
# before asking: this cap only stops a runaway request.
MAX_PROMPT_CHARS = 20000
_PURPOSE = re.compile(r"[a-z][a-z0-9_]{0,31}")


def _utc_now():
    return datetime.now(timezone.utc)


def _status_of(error):
    if isinstance(error, LLMRateLimited):
        return "rate_limited"
    if isinstance(error, LLMTimeout):
        return "timeout"
    return "error"


def _describe_failure(exc):
    """The type of a failure (and a MySQL error number): never its text, which
    could hold a URL or a user name."""
    errno = getattr(exc, "errno", None)
    return f"{type(exc).__name__} {errno}" if errno else type(exc).__name__


class LLMService:
    """Calls ``provider`` (a providers.Provider) and logs to ``store`` (a
    usage.UsageStore). ``now`` and ``clock`` are injectable for tests."""

    def __init__(self, provider, store, *, daily_limit, now=_utc_now, clock=time.monotonic):
        self.provider = provider
        self.store = store
        self.daily_limit = daily_limit
        self._now = now
        self._clock = clock

    def describe(self):
        return self.provider.describe()

    def usage_today(self):
        """(calls today, daily limit). LLMError if the usage log cannot be read."""
        return self._count(self._today()), self.daily_limit

    def complete(self, prompt, *, system=None, purpose, user_id=None):
        """The reply to ``prompt``, stripped, or an LLMError.

        ``system`` is the standing instructions (a persona, the task), ``purpose``
        names the caller in the usage log (lower_snake_case), and ``user_id`` is who
        the call is for, if anyone. A wrong argument is a bug: ValueError.
        If the usage log cannot be read, the call is refused (LLMError): without the
        count the limit cannot hold, and the quota must not be spent blind.
        """
        _check_arguments(prompt, system, purpose, user_id)
        prompt_chars = len(prompt) + len(system or "")
        day = self._today()
        used = self._count(day)
        if used >= self.daily_limit:
            refused = LLMLimitReached(f"daily LLM limit reached ({used}/{self.daily_limit})")
            self._record(day, purpose, user_id, "over_limit", None, prompt_chars, 0, refused)
            raise refused

        started = self._clock()
        status, reply, failure = "error", "", None
        try:
            reply = self._ask(prompt, system)
            status = "ok"
            return reply
        except LLMError as exc:
            status, failure = _status_of(exc), exc
            raise
        finally:
            latency_ms = int((self._clock() - started) * 1000)
            self._record(day, purpose, user_id, status, latency_ms, prompt_chars, len(reply), failure)

    def _today(self):
        return self._now().date()

    def _count(self, day):
        try:
            return self.store.count(day)
        except Exception as exc:
            log.warning("llm usage count failed (%s)", _describe_failure(exc))
            raise LLMError("the LLM usage log is unavailable") from None

    def _ask(self, prompt, system):
        try:
            reply = self.provider.complete(prompt, system)
        except LLMError:
            raise
        except Exception as exc:
            # A provider bug becomes an LLMError, so the caller still falls back
            # instead of failing the user's request.
            raise LLMError(f"{self.provider.name} failed ({_describe_failure(exc)})") from None
        if not isinstance(reply, str) or not reply.strip():
            raise LLMError(f"{self.provider.name}: empty reply")
        return reply.strip()

    def _record(self, day, purpose, user_id, status, latency_ms, prompt_chars, reply_chars,
                failure=None):
        """One usage row and one log line per call. Never raises: the call has
        already happened (and may have been paid for), so a reply is kept even when
        the log misses it."""
        entry = UsageRecord(day, self.provider.name, self.provider.model, purpose, user_id,
                            status, latency_ms, prompt_chars, reply_chars)
        try:
            self.store.record(entry)
        except Exception as exc:
            log.warning("llm usage not recorded (%s)", _describe_failure(exc))
        # Sizes, never text. An LLMError's message is safe to log: providers
        # scrub the key out of it.
        line = "llm %s purpose=%s status=%s ms=%s in=%d out=%d"
        args = [self.provider.name, purpose, status, latency_ms, prompt_chars, reply_chars]
        if failure is not None:
            line += ": %s"
            args.append(failure)
        log.log(logging.INFO if status == "ok" else logging.WARNING, line, *args)


def _check_arguments(prompt, system, purpose, user_id):
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")
    if system is not None and not isinstance(system, str):
        raise ValueError("system must be a string or None")
    if len(prompt) + len(system or "") > MAX_PROMPT_CHARS:
        raise ValueError(f"prompt and system text are over {MAX_PROMPT_CHARS} characters")
    if not isinstance(purpose, str) or not _PURPOSE.fullmatch(purpose):
        raise ValueError("purpose must be lower_snake_case, 1 to 32 characters")
    # bool is an int in Python: True would log as user 1.
    if user_id is not None and (isinstance(user_id, bool) or not isinstance(user_id, int)):
        raise ValueError("user_id must be an int or None")
