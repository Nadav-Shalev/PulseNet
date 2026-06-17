# PulseNet Backend

Flask REST API backed by MySQL. It serves articles, users, auth/session flows,
social graph endpoints, and local image uploads for the React frontend.

## Folder Structure

```text
backend/
├── app.py
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

Create the database from the project root:

```bash
mysql -u root -p < database/schema.sql
```

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
