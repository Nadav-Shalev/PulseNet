"""Screening posts and comments for toxic content before they are published.

    moderator = Moderator(llm_service)    # None when the LLM is off
    verdict = moderator.check_comment(text, user_id=7)
    if verdict.blocked:
        ...                               # 422: not published

Each check makes at most one LLM call: a post's title, tags and body go in one
structured prompt, as delimited data (llm.prompt), and the model answers a strict
JSON verdict. The LLM's verdicts are cached by a hash of the normalized text, so
the same text is never classified twice. When the LLM is off or fails in any way
(error, timeout, rate limit, daily limit, a reply that is not a verdict), a word
list of insults and threats decides instead.

Like llm/, this module imports neither Flask nor the app: the agents (S14) run it
from their own process.
"""

import hashlib
import logging
import re
import threading
import unicodedata
from collections import OrderedDict
from typing import NamedTuple

from llm import LLMBadReply, LLMError, data_blocks, data_rule, parse_json_object

log = logging.getLogger("pulsenet.moderation")

CATEGORIES = ("harassment", "hate", "threat")
# A post's body (or a comment) is cut to this before it goes to the LLM; past the
# cut, the word list reads the rest. Title and tags are short and always sent whole.
MAX_TEXT_CHARS = 8000
DEFAULT_CACHE_SIZE = 1024

SYSTEM = (
    "You moderate PulseNet, a social network for software developers. You are given "
    "one post (in <post_title>, <post_tags> and <post_body>) or one comment (in "
    "<comment>). Decide whether it is toxic, and how:\n"
    "- harassment: it insults, demeans, bullies or harasses a person;\n"
    "- hate: it attacks or demeans a group of people for who they are (race, religion, "
    "nationality, gender, sexuality, disability and the like);\n"
    "- threat: it threatens violence or harm, or tells someone to hurt or kill themselves.\n"
    "Not toxic: criticism of ideas, code or products, however blunt; strong opinions; "
    "profanity that is not aimed at a person; quoting or discussing such words without "
    "using them against someone.\n"
    + data_rule("post_title", "post_tags", "post_body", "comment") + "\n"
    'Reply with only one JSON object and nothing else: {"toxic": false, "category": "none"} '
    'when it is not toxic, or {"toxic": true, "category": "harassment"} (or "hate", or '
    '"threat") when it is.'
)

# The fallback when the LLM cannot answer: phrases aimed at a person, which are
# toxic in almost any context. Matched as whole words on the normalized text, so
# "skills" never matches "kill". It has no slurs, so hate speech in general is
# caught only by the LLM: a known limit of the fallback.
BLOCKED_PHRASES = {
    "threat": (
        "kill yourself", "kill urself", "kys", "go die", "die in a fire", "hope you die",
        "you should die", "i will kill you", "i'll kill you", "i am going to kill you",
        "i'm going to kill you",
        "לך תמות", "שתמות", "תתאבד", "אני ארצח אותך",
    ),
    "harassment": (
        "fuck you", "fuck off", "f*ck you", "stfu", "piece of shit", "son of a bitch",
        "you idiot", "you moron", "you loser", "you're stupid", "you are stupid",
        "you're an idiot", "you are an idiot", "you're worthless", "you are worthless",
        "you're pathetic", "you are pathetic", "nobody likes you", "dumbass",
        "יא מטומטם", "יא אידיוט", "יא זבל", "יא אפס", "יא חתיכת חרא",
    ),
}

_ZERO_WIDTH = dict.fromkeys(map(ord, "­​‌‍⁠﻿"))
_QUOTES = str.maketrans({"‘": "'", "’": "'", "ʼ": "'"})


class Verdict(NamedTuple):
    blocked: bool
    category: str   # 'none' or one of CATEGORIES
    source: str     # 'llm', 'cache' (an earlier LLM verdict) or 'wordlist'


def normalize(text):
    """``text`` as the word list and the cache see it: NFKC, case-folded, no
    zero-width characters, curly apostrophes made straight, whitespace collapsed."""
    text = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH).translate(_QUOTES)
    return " ".join(text.casefold().split())


def _phrase_pattern(phrases):
    words = (r"\s+".join(map(re.escape, normalize(phrase).split())) for phrase in phrases)
    return re.compile(r"(?<!\w)(?:%s)(?!\w)" % "|".join(words))


_WORDLIST = [(category, _phrase_pattern(phrases)) for category, phrases in BLOCKED_PHRASES.items()]


def wordlist_verdict(text):
    """The word list's verdict on ``text``: threats first, then insults."""
    normalized = normalize(text)
    for category, pattern in _WORDLIST:
        if pattern.search(normalized):
            return Verdict(True, category, "wordlist")
    return Verdict(False, "none", "wordlist")


def parse_verdict(reply):
    """The LLM's reply as a Verdict. Only {"toxic": false, "category": "none"} or
    {"toxic": true, "category": <one of CATEGORIES>} pass; anything else is
    LLMBadReply, so the word list decides instead."""
    answer = parse_json_object(reply)
    toxic, category = answer.get("toxic"), answer.get("category")
    if isinstance(category, str):
        category = category.strip().lower()
    if toxic is False and category == "none":
        return Verdict(False, "none", "llm")
    if toxic is True and category in CATEGORIES:
        return Verdict(True, category, "llm")
    raise LLMBadReply("the moderation reply is not a valid verdict")


class Moderator:
    """Checks posts and comments with ``service`` (an llm.LLMService, or None when
    the LLM is off), and keeps up to ``cache_size`` LLM verdicts."""

    def __init__(self, service, *, cache_size=DEFAULT_CACHE_SIZE):
        self.service = service
        self._cache_size = cache_size
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    def check_post(self, title, body_text, tags=(), *, user_id=None):
        """One verdict for a whole post. ``body_text`` is its visible text (the
        HTML's text), never raw HTML; ``tags`` are its tag names."""
        return self._check((("post_title", title), ("post_tags", ", ".join(tags)),
                            ("post_body", body_text)), user_id)

    def check_comment(self, text, *, user_id=None):
        """The verdict on a comment's visible text."""
        return self._check((("comment", text),), user_id)

    def _check(self, fields, user_id):
        key = _cache_key(fields)
        verdict = self._recall(key)
        if verdict is None:
            verdict = self._ask(fields, user_id)
            if verdict is not None:
                self._remember(key, verdict)
        # The LLM saw only the first MAX_TEXT_CHARS of the last field: the word list
        # reads the whole text, so toxic text cannot hide past the cut.
        cut = len(fields[-1][1]) > MAX_TEXT_CHARS
        if verdict is None or (cut and not verdict.blocked):
            listed = wordlist_verdict("\n".join(text for _name, text in fields))
            if verdict is None or listed.blocked:
                verdict = listed
        if verdict.blocked:
            log.info("moderation blocked: category=%s source=%s user=%s",
                     verdict.category, verdict.source, user_id)
        return verdict

    def _ask(self, fields, user_id):
        """The LLM's verdict, or None when there is none to be had."""
        if self.service is None:
            return None
        *head, (name, text) = fields
        prompt = data_blocks(*head, (name, text[:MAX_TEXT_CHARS]))
        try:
            reply = self.service.complete(prompt, system=SYSTEM, purpose="moderation",
                                          user_id=user_id)
            return parse_verdict(reply)
        except LLMBadReply:
            log.warning("moderation: the LLM reply is not a verdict, so the word list decides")
            return None
        except LLMError:
            return None  # the service has logged why

    def _recall(self, key):
        with self._lock:
            verdict = self._cache.get(key)
            if verdict is None:
                return None
            self._cache.move_to_end(key)
        return verdict._replace(source="cache")

    def _remember(self, key, verdict):
        with self._lock:
            self._cache[key] = verdict
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)


def _cache_key(fields):
    """A hash of the normalized fields, names included: the cache keeps no text."""
    joined = "\x00".join(f"{name}\x01{normalize(text)}" for name, text in fields)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
