"""scripts/compose_preflight.py: what it refuses in a resolved Compose configuration.

The checks run on dicts shaped like ``docker compose config --format json``, and
``main`` on a fake ``run``, so no Docker is needed. The values in these tests are
made up; the point of several tests is that a value never reaches the output.
"""

import contextlib
import importlib.util
import io
import json
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent

_spec = importlib.util.spec_from_file_location("compose_preflight", ROOT / "scripts" / "compose_preflight.py")
preflight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preflight)

# Made-up values that only look like credentials.
FAKE_AWS_KEY_ID = "AKIA" + "Q" * 16
FAKE_GOOGLE_KEY = "AIza" + "x" * 35
# Split, so the source itself does not look like an endpoint to the pre-commit hook.
FAKE_GATEWAY = "https://abc123." + "execute-api" + ".eu-central-1.amazonaws.com/prod"


def backend_env(**overrides):
    env = {
        "DB_HOST": "db", "DB_USER": "pulsenet", "DB_PASSWORD": "pulsenet", "DB_NAME": "pulsenet_db",
        "LLM_PROVIDER": "", "LLM_API_KEY": "", "MAIL_PROVIDER": "file",
    }
    env.update(overrides)
    return env


def config(**services):
    base = {
        "db": {"image": "mysql:8.4", "environment": {"MYSQL_DATABASE": "pulsenet_db"}},
        "backend": {"image": "pulsenet-backend", "environment": backend_env()},
    }
    base.update(services)
    return {"name": "pulsenet", "services": base}


class FindProblemsTests(unittest.TestCase):
    def test_the_default_stack_passes(self):
        self.assertEqual(preflight.find_problems(config()), [])
        self.assertEqual(preflight.find_problems(config(), strict=True), [])

    def test_an_env_file_is_refused(self):
        cfg = config(backend={"environment": backend_env(), "env_file": [{"path": "backend/.env"}]})
        problems = preflight.find_problems(cfg)
        self.assertEqual(len(problems), 1)
        self.assertIn("services.backend.env_file", problems[0])

    def test_db_host_must_be_the_db_container(self):
        for host in ("database-x.abc.eu-central-1.rds.amazonaws.com", "localhost", ""):
            with self.subTest(host=host):
                problems = preflight.find_problems(config(backend={"environment": backend_env(DB_HOST=host)}))
                self.assertTrue(any("environment.DB_HOST: must be" in p for p in problems), problems)

    def test_an_rds_host_anywhere_is_refused(self):
        cfg = config(backend={"environment": backend_env(), "command": ["x", "db.rds.amazonaws.com"]})
        self.assertEqual(preflight.find_problems(cfg), ["services.backend.command[1]: looks like an RDS endpoint"])

    def test_the_course_provider_and_its_url_are_refused(self):
        cfg = config(backend={"environment": backend_env(LLM_PROVIDER="Course", LLM_API_URL=FAKE_GATEWAY)})
        problems = preflight.find_problems(cfg)
        self.assertIn("services.backend.environment.LLM_PROVIDER: the course (AWS) provider is production only",
                      problems)
        self.assertIn("services.backend.environment.LLM_API_URL: the course (AWS) LLM endpoint is production only",
                      problems)
        self.assertIn("services.backend.environment.LLM_API_URL: looks like the course LLM endpoint (AWS API Gateway)",
                      problems)

    def test_smtp_is_refused(self):
        cfg = config(backend={"environment": backend_env(MAIL_PROVIDER="smtp", SMTP_PASSWORD="hunter2-made-up")})
        problems = preflight.find_problems(cfg)
        self.assertIn("services.backend.environment.MAIL_PROVIDER: real mail (smtp) is production only", problems)
        self.assertIn("services.backend.environment.SMTP_PASSWORD: real mail is production only", problems)

    def test_credential_shaped_values_are_refused_wherever_they_are(self):
        cases = {
            FAKE_AWS_KEY_ID: "an AWS access key id",
            "sk-" + "a" * 24: "a secret API key (sk-...)",
            "ghp_" + "b" * 36: "a GitHub token",
        }
        for value, label in cases.items():
            with self.subTest(label=label):
                cfg = config(agents={"environment": backend_env(**{"LLM_API_KEY": value})})
                self.assertIn(f"services.agents.environment.LLM_API_KEY: looks like {label}",
                              preflight.find_problems(cfg))

    def test_a_word_that_merely_contains_sk_dash_passes(self):
        cfg = config(backend={"environment": backend_env(), "command": ["disk-" + "c" * 30]})
        self.assertEqual(preflight.find_problems(cfg), [])

    def test_a_dev_key_is_allowed_unless_strict(self):
        cfg = config(backend={"environment": backend_env(LLM_PROVIDER="openai_compat", **{"LLM_API_KEY": FAKE_GOOGLE_KEY})})
        self.assertEqual(preflight.find_problems(cfg), [])
        strict = preflight.find_problems(cfg, strict=True)
        self.assertIn("services.backend.environment.LLM_PROVIDER: the E2E stack runs the fake provider only", strict)
        self.assertIn("services.backend.environment.LLM_API_KEY: the E2E stack needs no LLM key", strict)
        self.assertIn("services.backend.environment.LLM_API_KEY: looks like a Google API key", strict)

    def test_strict_accepts_the_fake_provider(self):
        cfg = config(backend={"environment": backend_env(LLM_PROVIDER="fake")})
        self.assertEqual(preflight.find_problems(cfg, strict=True), [])

    def test_no_problem_ever_contains_the_value(self):
        env = backend_env(DB_HOST="secret-host.rds.amazonaws.com", LLM_PROVIDER="course",
                          LLM_API_URL=FAKE_GATEWAY, **{"LLM_API_KEY": FAKE_AWS_KEY_ID}, SMTP_PASSWORD="made-up-pw-123")
        problems = preflight.find_problems(config(backend={"environment": env}), strict=True)
        self.assertGreaterEqual(len(problems), 6)
        for value in ("secret-host", FAKE_GATEWAY, "abc123", FAKE_AWS_KEY_ID, "made-up-pw-123"):
            for problem in problems:
                self.assertNotIn(value, problem)

    def test_a_list_environment_and_null_values_are_read(self):
        cfg = config(backend={"environment": ["DB_HOST=elsewhere", "LLM_API_KEY"]},
                     db={"environment": {"MYSQL_PASSWORD": None}})
        self.assertEqual(preflight.find_problems(cfg),
                         ["services.backend.environment.DB_HOST: must be the 'db' container, not an outside database"])


class KeyNotesTests(unittest.TestCase):
    def test_names_the_services_with_a_key_but_not_the_key(self):
        cfg = config(agents={"environment": backend_env(**{"LLM_API_KEY": FAKE_GOOGLE_KEY})})
        notes = preflight.key_notes(cfg)
        self.assertEqual(notes, ["services.agents.environment.LLM_API_KEY is set (a development key; value not shown)"])
        self.assertNotIn(FAKE_GOOGLE_KEY, notes[0])


class MainTests(unittest.TestCase):
    def run_main(self, argv, stdout="", stderr="", returncode=0, error=None):
        calls = []

        def run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            if error:
                raise error
            return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = preflight.main(argv, run=run)
        return code, out.getvalue(), err.getvalue(), calls

    def test_ok_lists_the_services_and_runs_compose_config_with_every_profile(self):
        code, out, err, calls = self.run_main([], stdout=json.dumps(config()))
        self.assertEqual(code, 0)
        self.assertIn("ok: backend, db", out)
        self.assertEqual(err, "")
        cmd, kwargs = calls[0]
        self.assertEqual(cmd, ["docker", "compose", "--profile", "*", "config", "--format", "json"])
        self.assertEqual(kwargs["cwd"], preflight.ROOT)
        self.assertTrue(kwargs["capture_output"])

    def test_problems_exit_1_without_values(self):
        cfg = config(backend={"environment": backend_env(**{"LLM_API_KEY": FAKE_AWS_KEY_ID})})
        code, out, err, _ = self.run_main(["--strict"], stdout=json.dumps(cfg))
        self.assertEqual(code, 1)
        self.assertIn("refused, 2 problem(s)", err)
        self.assertNotIn(FAKE_AWS_KEY_ID, out + err)

    def test_a_dev_key_is_reported_as_set_only(self):
        cfg = config(backend={"environment": backend_env(LLM_PROVIDER="openai_compat", **{"LLM_API_KEY": FAKE_GOOGLE_KEY})})
        code, out, _, _ = self.run_main([], stdout=json.dumps(cfg))
        self.assertEqual(code, 0)
        self.assertIn("LLM_API_KEY is set", out)
        self.assertNotIn(FAKE_GOOGLE_KEY, out)

    def test_compose_failure_and_bad_output_exit_1(self):
        code, _, err, _ = self.run_main([], stderr="yaml: line 3: bad indentation", returncode=15)
        self.assertEqual((code, "line 3" in err), (1, True))
        code, _, err, _ = self.run_main([], stdout="not json")
        self.assertEqual((code, "did not answer JSON" in err), (1, True))

    def test_no_docker_exits_2(self):
        code, _, err, _ = self.run_main([], error=FileNotFoundError("docker"))
        self.assertEqual(code, 2)
        self.assertIn("docker not found", err)


if __name__ == "__main__":
    unittest.main()
