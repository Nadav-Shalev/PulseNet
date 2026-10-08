"""course: the course's LLM endpoint, with the contract of the class demo
(community_bot/llm.py).

It takes one flat prompt, with no chat roles, so the system text goes first and
the prompt after it. LLM_API_URL is the endpoint and LLM_API_KEY goes in an
x-api-key header; both live only in backend/.env. The reply text is the first of
the keys in REPLY_KEYS. Stricter than the demo, which falls back to the raw body:
any other reply is an error, so a contract mismatch shows up at once.
"""

import requests

from ..errors import LLMError
from .base import host_of, post_json

REPLY_KEYS = ("completion", "text", "response", "output")


class CourseProvider:
    name = "course"
    model = None

    def __init__(self, url, api_key, timeout, http=requests):
        self._url = url
        self._api_key = api_key
        self._timeout = timeout
        self._http = http

    def __repr__(self):  # host only: neither the key nor the endpoint's path
        return f"CourseProvider(host={host_of(self._url)!r})"

    def describe(self):
        return f"course endpoint at {host_of(self._url)}"

    def complete(self, prompt, system=None):
        flat = f"{system}\n\n{prompt}" if system else prompt
        data = post_json(
            self._http, self._url,
            headers={"x-api-key": self._api_key},
            body={"prompt": flat},
            timeout=self._timeout, secret=self._api_key, provider=self.name,
        )
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            for key in REPLY_KEYS:
                if isinstance(data.get(key), str):
                    return data[key]
        raise LLMError(f"{self.name}: unexpected reply (no {'/'.join(REPLY_KEYS)} text)")
