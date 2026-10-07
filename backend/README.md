# PulseNet Backend

Flask REST API backed by MySQL. It serves articles, users, auth/session flows,
social graph endpoints, and local image uploads for the React frontend.

## Folder Structure

```text
backend/
├── app.py
├── migrate.py        schema migrations (see ../database/README.md)
├── manage.py         admin commands, e.g. make-admin
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
- When deploying over HTTPS, add the `Secure` attribute to the session cookie.
