"""Reading structured answers out of LLM replies.

Asked for "only a JSON object", models still wrap it in a ```json fence or add a
sentence before or after it. parse_json_object() takes the first JSON object it
finds and leaves checking its fields to the caller.
"""

import json
import re

from .errors import LLMBadReply

# A fenced block: ```json ... ``` (or a bare ``` ... ```), anywhere in the reply.
_FENCE = re.compile(r"```[a-zA-Z]*[ \t]*\r?\n?(.*?)```", re.DOTALL)
_decoder = json.JSONDecoder()


def parse_json_object(reply):
    """The first JSON object in ``reply`` as a dict, looking inside a fenced
    block first when there is one. LLMBadReply when there is none; its message
    then says why the first '{' did not decode (the decoder's message and a
    position, never the reply's text), so a bad reply can be told apart in a log."""
    if not isinstance(reply, str):
        raise LLMBadReply("the reply is not text")
    fenced = _FENCE.search(reply)
    reason = None
    for text in ((fenced.group(1), reply) if fenced else (reply,)):
        found, error = _first_object(text)
        if found is not None:
            return found
        reason = reason or error
    raise LLMBadReply("the reply has no JSON object" + (f" ({reason})" if reason else ""))


def _first_object(text):
    """(The first '{' that starts a JSON object, decoded, or None; why the first
    '{' did not decode, or None)."""
    first_error = None
    start = text.find("{")
    while start != -1:
        try:
            value, _end = _decoder.raw_decode(text, start)
        except ValueError as exc:
            value = None
            if first_error is None and isinstance(exc, json.JSONDecodeError):
                first_error = str(exc)   # "<message>: line L column C (char N)"
        if isinstance(value, dict):
            return value, None
        start = text.find("{", start + 1)
    return None, first_error
