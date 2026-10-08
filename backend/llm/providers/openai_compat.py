"""openai_compat: any server that speaks the OpenAI Chat Completions API.

Google AI Studio (Gemini), Groq and Ollama all do. LLM_BASE_URL picks the server,
LLM_MODEL the model, and LLM_API_KEY goes in an Authorization header.

No max_tokens is sent: on "thinking" models (Gemini) the hidden reasoning counts
against it, and a small cap can use it all up and leave an empty reply.
"""

import requests

from ..errors import LLMError
from .base import host_of, post_json


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self, base_url, model, api_key, timeout, http=requests):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self._api_key = api_key
        self._timeout = timeout
        self._http = http

    def __repr__(self):  # no key: a repr can end up in a log or a traceback
        return f"OpenAICompatProvider(url={self.url!r}, model={self.model!r})"

    def describe(self):
        return f"openai_compat, model {self.model} at {host_of(self.url)}"

    def complete(self, prompt, system=None):
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt})
        data = post_json(
            self._http, self.url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            body={"model": self.model, "messages": messages},
            timeout=self._timeout, secret=self._api_key, provider=self.name,
        )
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError(f"{self.name}: unexpected reply (no choices[0].message.content)") from None
        if not isinstance(content, str) or not content.strip():
            # finish_reason says why: 'length' (out of tokens), 'content_filter', ...
            # (choice is a JSON object here: nothing else can be indexed by "message").
            raise LLMError(f"{self.name}: empty reply (finish_reason {choice.get('finish_reason')!r})")
        return content
