"""Preflight for docker compose: validate the files and refuse production secrets.

    python scripts/compose_preflight.py            # the stack `docker compose up` would start
    python scripts/compose_preflight.py --strict   # the E2E stack: fake LLM, no key at all

It runs ``docker compose config --format json`` from the repo root, with the files
Compose picks itself (COMPOSE_FILE, else docker-compose.yml): an invalid file or a
missing required variable fails here, before anything is built. Every profile is
included, so the agents service is checked too.

The resolved configuration holds the value of every variable, including whatever a
.env file in the repo root set. So it is parsed in memory and never printed: a
problem names the place (``services.backend.environment.LLM_API_KEY``) and the
reason, never the value.

Refused, always: an ``env_file`` (backend/.env must never be loaded), a DB_HOST that
is not the ``db`` container, the course (AWS) LLM provider or its URL, SMTP, and any
value that looks like a production credential (an AWS key id, the API Gateway or RDS
host, a secret key or token). With --strict also any LLM provider but ``fake`` (or none),
any LLM key, and a Google API key. Without it, a development key for openai_compat is
allowed, and only reported as set.

Only the standard library, so it runs on any Python 3.9+ (CI's runner included).
Exit codes: 0 ok, 1 problems found or Compose failed, 2 docker not found.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_CONFIG = ["docker", "compose", "--profile", "*", "config", "--format", "json"]
DB_SERVICE = "db"

# (what it looks like, pattern): the pre-commit hook's patterns, plus the RDS host.
SECRET_PATTERNS = [
    ("an AWS access key id", re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}")),
    ("the course LLM endpoint (AWS API Gateway)", re.compile(r"execute-api\.[a-z0-9-]+\.amazonaws\.com")),
    ("an RDS endpoint", re.compile(r"\.rds\.amazonaws\.com")),
    ("a secret API key (sk-...)", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}")),
    ("a GitHub token", re.compile(r"(?<![A-Za-z0-9])ghp_[A-Za-z0-9]{30,}")),
]
# A Gemini key is a development key: allowed in the local stack, not in E2E.
GOOGLE_KEY = ("a Google API key", re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{30,}"))

# Settings that must stay empty everywhere: production only.
PRODUCTION_ONLY = {
    "LLM_API_URL": "the course (AWS) LLM endpoint is production only",
    "SMTP_PASSWORD": "real mail is production only",
}


def _strings(node, path):
    """Yield (path, text) for every string in the parsed configuration."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _strings(value, f"{path}[{index}]")
    elif isinstance(node, str):
        yield path, node


def _environment(service):
    """A service's environment as {name: value}, with None (no value) as ''."""
    env = service.get("environment") or {}
    if isinstance(env, list):  # KEY=VALUE items; `config` normally gives a mapping
        env = dict(item.split("=", 1) if "=" in item else (item, "") for item in env)
    return {key: "" if value is None else str(value) for key, value in env.items()}


def find_problems(config, strict=False):
    """Every reason to refuse ``config`` (the parsed ``docker compose config``), as
    "<place>: <reason>" lines that never contain a value."""
    problems = []
    patterns = SECRET_PATTERNS + ([GOOGLE_KEY] if strict else [])
    for path, text in _strings(config, ""):
        for label, pattern in patterns:
            if pattern.search(text):
                problems.append(f"{path}: looks like {label}")

    services = config.get("services") or {}
    for name in sorted(services):
        service = services[name] or {}
        where = f"services.{name}"
        if service.get("env_file"):
            problems.append(f"{where}.env_file: not allowed (backend/.env must never be loaded; "
                            "set values in docker-compose.yml or the root .env)")
        env = _environment(service)
        place = f"{where}.environment"
        if "DB_HOST" in env and env["DB_HOST"] != DB_SERVICE:
            problems.append(f"{place}.DB_HOST: must be the {DB_SERVICE!r} container, not an outside database")
        provider = env.get("LLM_PROVIDER", "").strip().lower()
        if provider == "course":
            problems.append(f"{place}.LLM_PROVIDER: the course (AWS) provider is production only")
        elif strict and provider not in ("", "fake"):
            problems.append(f"{place}.LLM_PROVIDER: the E2E stack runs the fake provider only")
        if strict and env.get("LLM_API_KEY", "").strip():
            problems.append(f"{place}.LLM_API_KEY: the E2E stack needs no LLM key")
        if env.get("MAIL_PROVIDER", "").strip().lower() == "smtp":
            problems.append(f"{place}.MAIL_PROVIDER: real mail (smtp) is production only")
        for key, reason in PRODUCTION_ONLY.items():
            if env.get(key, "").strip():
                problems.append(f"{place}.{key}: {reason}")
    return problems


def key_notes(config):
    """What a reader should know but is allowed: LLM keys that are set (no value)."""
    services = config.get("services") or {}
    return [
        f"services.{name}.environment.LLM_API_KEY is set (a development key; value not shown)"
        for name in sorted(services)
        if _environment(services[name] or {}).get("LLM_API_KEY", "").strip()
    ]


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="compose_preflight.py",
        description="Validate the Compose files and refuse production secrets in what they resolve to.",
    )
    parser.add_argument("--strict", action="store_true",
                        help="the E2E stack: fake LLM only, no LLM key, no Google key")
    return parser.parse_args(argv)


def main(argv=None, run=subprocess.run):
    args = _parse_args(argv)

    def say(message, stream=sys.stdout):
        print(f"compose-preflight: {message}", file=stream)

    try:
        result = run(COMPOSE_CONFIG, cwd=ROOT, capture_output=True, text=True)
    except FileNotFoundError:
        say("docker not found: install Docker (with the compose plugin) first", sys.stderr)
        return 2
    if result.returncode != 0:
        # Compose's own error names a file, line or variable. Only a field Compose
        # validates (a port, a duration) can quote its value; an environment entry
        # is a free string, so a key or password never fails here.
        say(f"docker compose config failed:\n{result.stderr.strip()}", sys.stderr)
        return 1
    try:
        config = json.loads(result.stdout)
    except ValueError:
        say("docker compose config did not answer JSON", sys.stderr)
        return 1

    problems = find_problems(config, strict=args.strict)
    if problems:
        say(f"refused, {len(problems)} problem(s) (values not shown):", sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    names = ", ".join(sorted(config.get("services") or {}))
    say(f"ok{' (strict)' if args.strict else ''}: {names}")
    for note in key_notes(config):
        say(note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
