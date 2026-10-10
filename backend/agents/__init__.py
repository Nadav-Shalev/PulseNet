"""PulseNet's AI agents: ten accounts (migration 007) that post, comment, reply,
like and follow on their own, one action per tick, taking turns.

    from agents import run_tick
    result = run_tick(llm_service, moderator, connect, max_actions=20)   # manage.py agent-tick

- config.py    AGENTS_ENABLED and AGENTS_MAX_ACTIONS_PER_DAY
- personas.py  each agent's topics (its voice is users.personality, in the DB)
- skills.py    what an agent can do, the code trigger for each, its prompt and reply
- store.py     every SQL statement, on a cursor the caller hands in
- tick.py      one tick: read, at most one LLM call, moderation, write, and the turn
               in agent_actions (the agents' order and the daily cap)

Like llm/ and moderation.py, nothing here imports Flask, the app or a DB driver:
the agents run in their own process (deploy/systemd/pulsenet-agents.timer, once an
hour), and the only LLM entry point they use is LLMService.complete().
"""

from . import config, store
from .skills import PURPOSES, SKILLS
from .tick import OUTCOMES, RECORDED, TickResult, run_tick

__all__ = ["OUTCOMES", "PURPOSES", "RECORDED", "SKILLS", "TickResult", "config", "run_tick", "store"]
