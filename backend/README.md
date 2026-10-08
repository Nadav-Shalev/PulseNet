# PulseNet Backend

Flask REST API backed by MySQL. It serves articles, users, auth/session flows,
social graph endpoints, and local image uploads for the React frontend.

## Folder Structure

```text
backend/
├── app.py
├── migrate.py        schema migrations (see ../database/README.md)
├── manage.py         admin commands: make-admin, llm-check
├── llm/              the LLM service: providers, daily limit, usage log, prompt helpers
├── moderation.py     checks posts and comments for toxic content before they are stored
├── ai_assist.py      prompts for AI help: correct a draft, draft a post, propose a comment
├── mock_data.py
├── seed_data.py
├── requirements.txt
├── .env.example
├── tests/
└── uploads/
```

The database schema lives outside the backend at `../database/schema.sql`.

## Setup

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Create a local environment file:

```bash
cp .env.example .env
```

Configure MySQL credentials in `.env`:

```env
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=pulsenet_db
```

Create the database (or apply pending schema changes) from the project root:

```bash
python backend/migrate.py
```

Schema changes are numbered files in `database/migrations/`; see
[`database/README.md`](../database/README.md).

Optionally seed the database:

```bash
python seed_data.py
```

Run the backend:

```bash
python app.py
```

The API runs at `http://localhost:5000`.

## API Notes

- CORS allows the local Vite frontend origin `http://localhost:5173`.
- Auth uses server-side sessions and an HttpOnly `session_id` cookie.
- Read endpoints can fall back to `mock_data.py` when the database is unavailable.
- Write endpoints require the database and return an error if it is unavailable.
- Uploaded images are stored in `backend/uploads/` and served from `/uploads/<filename>`.

Request helpers and frontend API shapes are documented in
`../frontend/src/api/README.md`.

## Admin Users

Every account starts with the role `user`. Admin-only endpoints are gated by
`require_admin` in `app.py`. The role is granted only by hand, never through the API
(signup and `PATCH /api/me` ignore it), from the project root:

```bash
python backend/manage.py make-admin <username> --dry-run   # show the target and what would change
python backend/manage.py make-admin <username>
```

Like `migrate.py`, it reads the database settings from `backend/.env`, and real
environment variables win. Before doing anything it prints the MySQL version, host
and database it is about to change, but never the credentials. On the server that is
the production database (RDS), so run it with `--dry-run` first.

## LLM Service

`llm/` is the one place that talks to a language model. Features call
`service.complete(prompt, system=..., purpose=..., user_id=...)`; agents (later) use
the same service from their own process. The package imports neither Flask nor the
app.

```text
llm/
├── config.py         from_env(): reads the LLM_* settings below
├── service.py        LLMService: daily limit, usage log, errors around each call
├── usage.py          the llm_usage table (DbUsageStore), MemoryUsageStore for tests
├── errors.py         LLMError and its subclasses
├── prompt.py         data_blocks()/data_rule(): user text as data, never instructions
├── parse.py          parse_json_object(): the JSON answer inside a reply
└── providers/        base.py (the Provider interface), fake.py, openai_compat.py, course.py
```

| `LLM_PROVIDER` | For | Settings |
| --- | --- | --- |
| `fake` | tests and the E2E run: canned replies, no network | none |
| `openai_compat` | development: any OpenAI-compatible chat API (Gemini in Google AI Studio, Groq, Ollama) | `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` |
| `course` | the final submission: the course endpoint (same contract as the class demo) | `LLM_API_URL`, `LLM_API_KEY` |

Unset `LLM_PROVIDER` means the LLM is off, so callers use their fallbacks. It is
not `fake` by default, so production never answers with canned text by mistake.

- `LLM_TIMEOUT_SECONDS` (1 to 120, default 15) is how long to wait for a reply. A web
  request must finish within gunicorn's 30-second worker timeout, so keep it below that.
- `LLM_DAILY_LIMIT` (default 100, 0 turns the LLM off) counts calls per UTC day,
  across every process, in the `llm_usage` table. Keep it below the provider's free
  quota (AI Studio shows the quota for your project).
- **Errors:** every failure is an `LLMError`, and the caller catches it and falls back.
  The subclasses are `LLMTimeout`, `LLMRateLimited` (the provider answered 429; it
  carries `retry_after`), `LLMLimitReached` (our own daily limit), `LLMConfigError`
  and `LLMBadReply` (it answered, but not in the shape asked for).
  There are no retries: a retry spends the quota twice and keeps the user waiting.
- **Usage log:** one `llm_usage` row per call, with provider, model, purpose, user,
  status, latency and sizes. The prompt and reply text are never stored. A warning
  line goes to the server log for every failed or refused call.
- **The limit is soft:** the count is read before a call and the row is written when
  the provider answers. Calls that run at the same moment all see the same count, so
  the limit can be exceeded by up to the number of concurrent calls. That is one or
  two today (one gunicorn worker); revisit if many agents ever call at once.

To use Gemini for free: create a key in Google AI Studio and put it in
`backend/.env` (never in git), with the `openai_compat` settings from `.env.example`.
Then check the whole path with one real call, from the project root:

```bash
python backend/manage.py llm-check
```

It prints the database, the provider, model and host (never the key), the reply,
the time it took and today's count. The call is logged and counts against the limit
like any other. A wrong key, model or URL shows up as a one-line error.

`app.py` builds the service once, at startup. A missing or broken `LLM_*` setting
leaves it off (one line in the server log names the variable) and every feature
uses its fallback.

**Prompt injection.** User text never sits next to instructions. `llm/prompt.py`
puts each field in its own block (`<post_title>...</post_title>`), neutralizes any
tag named like one of the prompt's blocks inside the text (`</post_body>` becomes
`&lt;/post_body>`), and every system text carries `data_rule()`: what is inside the
blocks is data, never instructions.

## Moderation

`moderation.py` checks a post (title, tags and visible body text) or a comment
before it is stored; a blocked one is a `422` with its category (`harassment`,
`hate` or `threat`) and nothing is saved.

- **One LLM call per publish**, purpose `moderation`, with the fields as data blocks
  and a strict answer: only `{"toxic": false, "category": "none"}` or
  `{"toxic": true, "category": "..."}` is a verdict.
- **Cache:** LLM verdicts are kept per process by a SHA-256 of the normalized text
  (LRU, 1024 entries), so the same text is never classified twice. No text is kept.
- **Fallback:** when the LLM is off or fails in any way (error, timeout, 429, the
  daily limit, a reply that is not a verdict), a word list of insults and threats
  aimed at a person decides. It holds no slurs, so with the LLM down general hate
  speech is not caught.
- **Long posts:** the LLM sees the first 8000 characters of the body, and the word
  list reads the whole text.
- A comment is checked after its post and parent are, so a `404` costs no LLM call.
  Moderation calls count against `LLM_DAILY_LIMIT`; once it is used up, the word
  list carries on alone.

## AI Assist

Three endpoints help write posts and comments (requirement c.i). They return a
suggestion and store nothing; whatever the user publishes from one goes through
moderation like anything else. Prompts are built in `ai_assist.py` with the same
data blocks as moderation.

| Endpoint | Body | Returns |
| --- | --- | --- |
| `POST /api/ai/correct` | `{"text": "...", "format": "text" or "html"}` | `{"text": "..."}`: the draft with its spelling and grammar fixed (HTML is sanitized before and after) |
| `POST /api/ai/suggest-post` | `{"title": "...", "tags": [...]}` | `{"body_html": "..."}`: a draft body from the title, written as Markdown and sanitized |
| `POST /api/ai/suggest-comment` | `{"post_id": 7, "parent_id": 3}` | `{"text": "..."}`: a proposed comment, or reply; the post and comment are read from the DB |

- All need a session. `AI_USER_DAILY_LIMIT` (default 20, 0 refuses everyone) caps
  each user's requests per UTC day, counting only these three purposes in
  `llm_usage`, so moderating a user's posts never uses up their AI help.
- Errors are meant for the user: `400` for bad input, `429` when the user's limit,
  the site's `LLM_DAILY_LIMIT` or the provider's rate limit is reached (with
  `Retry-After` when the provider sent one), and `503` when the LLM is off, too slow
  or failing.

## Tests

Run the backend test suite from `backend/`:

```bash
python -m unittest discover tests
```

The tests use Python `unittest` and patch the DB connection with test doubles, so
they do not require a running MySQL server.

## Security Notes

- Passwords are hashed with bcrypt.
- Sessions are stored server-side with expiration cleanup.
- User-submitted rich text is sanitized with bleach when available.
- Links opened in a new tab are protected with `rel="noopener noreferrer"`.
- Uploads are validated with Pillow and capped at 5 MB.
- LLM API keys live only in `.env`. They are never logged, printed or stored, and
  are scrubbed from provider error messages.
- When deploying over HTTPS, add the `Secure` attribute to the session cookie.
