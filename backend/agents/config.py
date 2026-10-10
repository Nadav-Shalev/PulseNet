"""The agents' settings, from environment variables (backend/.env).

    AGENTS_ENABLED              1, true, yes or on runs the ticks; 0, false, no, off,
                                empty or unset turns them off. Off by default, like
                                LLM_PROVIDER, so a new server never starts agents by
                                surprise. The timer keeps running; each tick just stops.
    AGENTS_MAX_ACTIONS_PER_DAY  the agents' turns per UTC day, all agents together
                                (agent_actions), 1 to 500, default 20. A turn that
                                failed counts too: its LLM calls were already spent.

Each tick is a new process (manage.py agent-tick), so a change in .env applies from
the next tick, with no restart. Error messages name a variable, never its value.
"""

from typing import NamedTuple

DEFAULT_MAX_ACTIONS_PER_DAY = 20
MIN_ACTIONS_PER_DAY, MAX_ACTIONS_PER_DAY = 1, 500
_ON = ("1", "true", "yes", "on")
_OFF = ("", "0", "false", "no", "off")


class AgentsConfigError(ValueError):
    """An AGENTS_* setting is invalid."""


class AgentsConfig(NamedTuple):
    enabled: bool
    max_actions_per_day: int


def from_env(env):
    """The AgentsConfig in ``env`` (e.g. ``os.environ``); AgentsConfigError when a
    setting is invalid."""
    return AgentsConfig(_enabled(env), _max_actions(env))


def _get(env, name):
    return (env.get(name) or "").strip()


def _enabled(env):
    raw = _get(env, "AGENTS_ENABLED").lower()
    if raw in _ON:
        return True
    if raw in _OFF:
        return False
    raise AgentsConfigError(f"AGENTS_ENABLED must be one of: {', '.join(_ON + _OFF[1:])} (or empty)")


def _max_actions(env):
    raw = _get(env, "AGENTS_MAX_ACTIONS_PER_DAY")
    if not raw:
        return DEFAULT_MAX_ACTIONS_PER_DAY
    try:
        limit = int(raw)
    except ValueError:
        limit = None
    if limit is None or not MIN_ACTIONS_PER_DAY <= limit <= MAX_ACTIONS_PER_DAY:
        raise AgentsConfigError(f"AGENTS_MAX_ACTIONS_PER_DAY must be a whole number from "
                                f"{MIN_ACTIONS_PER_DAY} to {MAX_ACTIONS_PER_DAY}")
    return limit
