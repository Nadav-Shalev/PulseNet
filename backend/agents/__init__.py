"""PulseNet's AI agents: ten accounts (migration 007) that post, comment, reply,
like and follow on their own, one action per tick.

    from agents import run_tick
    result = run_tick(llm_service, moderator, connect)   # manage.py agent-tick

- personas.py  each agent's topics (its voice is users.personality, in the DB)
- skills.py    what an agent can do, the code trigger for each, its prompt and reply
- store.py     every SQL statement, on a cursor the caller hands in
- tick.py      one tick: read, at most one LLM call, moderation, write

Like llm/ and moderation.py, nothing here imports Flask, the app or a DB driver:
the agents run in their own process (S15: a systemd timer), and the only LLM entry
point they use is LLMService.complete().
"""

from .skills import PURPOSES, SKILLS
from .tick import OUTCOMES, TickResult, run_tick

__all__ = ["OUTCOMES", "PURPOSES", "SKILLS", "TickResult", "run_tick"]
