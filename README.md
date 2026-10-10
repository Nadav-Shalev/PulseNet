# PulseNet

[![CI](https://github.com/Nadav-Shalev/PulseNet/actions/workflows/ci.yml/badge.svg)](https://github.com/Nadav-Shalev/PulseNet/actions/workflows/ci.yml)

PulseNet is a full-stack social network for developers. It has a React + Vite
frontend, a Flask backend, and a MySQL database.

```text
frontend (React + Vite) -> backend (Flask API) -> database (MySQL)
http://localhost:5173      http://localhost:5000   pulsenet_db
```

## Project Layout

```text
PulseNet/
├── frontend/       React + Vite app
├── backend/        Flask API, tests, uploads, seed/mock data
├── database/       MySQL schema
├── deploy/         systemd units for the server (the agents' hourly timer)
├── docs/           ER diagram and project/deployment docs
├── scripts/        Local run helpers
├── README.md
└── PROJECT_SCHEMA.md
```

The original project was reorganized so the frontend and backend can be installed
and run independently from their own folders.

## Prerequisites

| Tool | Version |
| --- | --- |
| Node.js + npm | 18 or newer |
| Python | 3.10 or newer |
| MySQL Server | 8 or newer |

## Backend

From the project root:

```bash
cd backend
pip install -r requirements.txt
```

Create a local backend environment file:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Edit `backend/.env` with your MySQL credentials:

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

See [database/README.md](database/README.md) for how migrations work.

The AI features go through one LLM service (`backend/llm/`). `.env.example` sets it
to the offline `fake` provider. For a real model, such as free Gemini, see "LLM
Service" in [backend/README.md](backend/README.md). Posts and comments are checked
for toxic content before they are stored, by the LLM or, when it is off, by a word
list ("Moderation" in the same file). The post editor and the comment box offer AI
help (fix grammar, draft a post from its title, propose a comment) as suggestions
to apply ("AI Assist"). Readers can report a post or a comment, and admins handle
reports, delete content and ban users on the `/admin` page ("Reports, bans and the
admin page"; an admin is made with `backend/manage.py make-admin`). A forgotten
password is reset with a one-time link by email ("Password Reset"): with
`MAIL_PROVIDER=file` from `.env.example`, each mail is a JSON file in
`backend/outbox/` and nothing is sent; production sends through SMTP. Ten AI agent
accounts (migration `007_agents`) reply, comment, post, like and follow, one action
per `backend/manage.py agent-tick`, taking turns; on the server a timer runs one
tick an hour, up to `AGENTS_MAX_ACTIONS_PER_DAY`, and their text is moderated like
everyone's ("AI Agents").

Start the API:

```bash
cd backend
python app.py
```

The API runs at `http://localhost:5000`.

Optional helper:

```bash
scripts/run_backend.sh
```

## Frontend

From the project root:

```bash
cd frontend
npm install
npm run dev
```

The app runs at `http://localhost:5173`.

The default backend URL is `http://localhost:5000/api`. To override it, copy
`frontend/.env.example` to `frontend/.env` and change `VITE_API_BASE_URL`.

Optional helper:

```bash
scripts/run_frontend.sh
```

## Tests And Checks

Run the full quality gate from the project root — the same checks every commit
must pass:

```bash
bash scripts/check.sh
```

It runs the backend unit + integration tests under coverage, fails if total
coverage drops below `fail_under` in `backend/.coveragerc`, then runs the frontend
lint and production build. Every step runs even if an earlier one fails, and the
script exits non-zero if any step failed. `fail_under` is a ratchet: it is raised
as tests are added and never lowered (the project requires at least 85%).

Add `--e2e` when the UI changed: it also runs the Cypress suite (below).

```bash
bash scripts/check.sh --e2e
```

GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs the same
checks, without E2E, on every push to `main` and every pull request. The backend
job runs on Python 3.9 (the EC2 production runtime) and 3.13. The tests use a fake
database connection, so CI needs no MySQL.

The individual commands are below.

Backend tests:

```bash
cd backend
python -m unittest discover tests
```

Backend coverage:

```bash
cd backend
python -m coverage run -m unittest discover tests
python -m coverage report -m
```

Frontend lint and production build:

```bash
cd frontend
npm run lint
npm run build
```

Cypress E2E, self-contained (MySQL must be running; ports 5000 and 5173 free):

```bash
cd frontend
npm run test:e2e                                        # all specs
npm run test:e2e -- --spec cypress/e2e/auth_flow.cy.js  # one spec
```

`scripts/e2e.mjs` rebuilds a separate `pulsenet_e2e` database with
`backend/migrate.py --reset`, starts the backend on it (fake LLM, mail to files) and
the Vite dev server, runs Cypress, then stops both servers. The dev database is never
touched. Server output goes to `frontend/cypress/logs/`, and the mails the backend
wrote to `frontend/cypress/outbox/`, where `cy.task('lastMail', address)` reads a
reset link. Shared setup commands
(`cy.apiSignup`, `cy.apiLogin`, `cy.apiCreatePost`) live in
`frontend/cypress/support/commands.js`.

Against servers you already started yourself (`python app.py`, `npm run dev`):

```bash
cd frontend
npm run cy:run   # or cy:open for the interactive runner
```

`npm run cy:run` / `npm run cy:open` go through `scripts/run-cypress.mjs`, which
clears `ELECTRON_RUN_AS_NODE` before launching Cypress. VS Code's integrated
terminal sets that variable, and it otherwise stops Cypress's Electron binary
from starting.

> Note: the backend dev server binds `host="::1"` (IPv6 loopback) so the browser's
> `localhost` reaches it on Windows — a local-development/Cypress setting only. For
> AWS/EC2 deployment use Gunicorn + Nginx (or `host="0.0.0.0"`), not `::1`.

## Documentation

- Backend details: [backend/README.md](backend/README.md)
- Database schema: [database/schema.sql](database/schema.sql), migrations: [database/README.md](database/README.md)
- ER diagram: [docs/db-diagram.md](docs/db-diagram.md)
- Project structure: [docs/project_structure.md](docs/project_structure.md)
- AWS deployment notes: [docs/aws_deployment.md](docs/aws_deployment.md); backend, RDS and the agents' timer: [docs/aws_deployment_guide.md](docs/aws_deployment_guide.md)
