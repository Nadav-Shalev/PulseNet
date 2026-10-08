"""fake: canned replies with no network, for tests and the E2E run (LLM_PROVIDER=fake)."""


class FakeProvider:
    """Answers locally and the same way every time: ``reply`` when one is given,
    otherwise a short echo of the prompt, so a test can tell replies apart."""

    name = "fake"
    model = None

    def __init__(self, reply=None):
        self._reply = reply

    def __repr__(self):
        return f"FakeProvider(reply={self._reply!r})"

    def describe(self):
        return "fake (canned replies, no network)"

    def complete(self, prompt, system=None):
        if self._reply is not None:
            return self._reply
        return "(fake reply) " + " ".join(prompt.split())[:80]
