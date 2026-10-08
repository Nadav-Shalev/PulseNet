"""Test doubles for the LLM service (backend/llm), shared by the llm test modules.

This module is intentionally NOT named ``test_*`` so ``unittest discover`` never
collects it as a test case. It does not import ``app``, so the llm unit tests run
without the Flask app.

  * ``FakeResponse`` / ``FakeHttp`` stand in for ``requests``: each ``post()`` is
    recorded and answered from a queue, so provider tests never touch the network.
  * ``ScriptedProvider`` is a Provider whose replies (or exceptions) are queued
    per test, for the service tests.
"""

import json as _json
import logging
import sys
from pathlib import Path

# ``import llm`` works however the tests are launched.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# The LLM service and moderation log a line per call; with no handler, logging
# prints warnings to stderr and clutters the test output. Tests only (in production
# those warnings should reach the server log). assertLogs still captures them.
logging.getLogger("pulsenet").addHandler(logging.NullHandler())


class FakeResponse:
    """What ``requests.post`` returns: a status, a body and headers. ``json()``
    raises ValueError when no JSON body was given, like requests does on HTML."""

    def __init__(self, status_code=200, json_body=None, text=None, headers=None):
        self.status_code = status_code
        self._json_body = json_body
        if text is None:
            text = "" if json_body is None else _json.dumps(json_body)
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._json_body is None:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._json_body


class FakeHttp:
    """Records each ``post()`` call and answers with the queued results in order:
    a FakeResponse is returned, an exception is raised."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class ScriptedProvider:
    """A Provider that answers from a queue: a string is returned, an exception is
    raised. ``calls`` records each (prompt, system)."""

    name = "scripted"

    def __init__(self, *results, model="scripted-1"):
        self.results = list(results)
        self.model = model
        self.calls = []

    def describe(self):
        return "scripted (test double)"

    def complete(self, prompt, system=None):
        self.calls.append((prompt, system))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result
