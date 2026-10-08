"""PulseNet's LLM service: the one place that talks to a language model.

    import llm

    service = llm.from_env(os.environ, connect=get_db_connection)  # LLMConfigError if unset
    try:
        reply = service.complete(text, system=INSTRUCTIONS, purpose="moderation")
    except llm.LLMError:
        ...  # fall back

The providers (LLM_PROVIDER: fake, openai_compat, course) live in providers/, the
settings in config.py, and the rules around each call (daily limit, usage log,
errors) in service.py. prompt.py fences user text off from instructions, and
parse.py reads a JSON answer out of a reply. The package imports neither Flask nor
the app, so the API and a separate process (the agents, later) can both use it.
"""

from .config import from_env
from .errors import (LLMBadReply, LLMConfigError, LLMError, LLMLimitReached, LLMRateLimited,
                     LLMTimeout)
from .parse import parse_json_object
from .prompt import data_blocks, data_rule
from .providers import CourseProvider, FakeProvider, OpenAICompatProvider, Provider
from .service import MAX_PROMPT_CHARS, LLMService
from .usage import STATUSES, DbUsageStore, MemoryUsageStore, UsageRecord, UsageStore

__all__ = [
    "from_env", "LLMService", "MAX_PROMPT_CHARS",
    "data_blocks", "data_rule", "parse_json_object",
    "LLMError", "LLMConfigError", "LLMTimeout", "LLMRateLimited", "LLMLimitReached",
    "LLMBadReply",
    "Provider", "FakeProvider", "OpenAICompatProvider", "CourseProvider",
    "UsageStore", "UsageRecord", "DbUsageStore", "MemoryUsageStore", "STATUSES",
]
