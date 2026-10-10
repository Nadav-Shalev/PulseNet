# Project Structure

PulseNet is organized as a deployable full-stack project:

```text
PulseNet/
├── frontend/          React + Vite app
│   ├── public/
│   ├── src/
│   ├── .env.example
│   ├── Dockerfile     production build served by nginx (nginx.conf)
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── backend/           Flask API
│   ├── app.py
│   ├── Dockerfile     the API under gunicorn (also runs migrate.py and manage.py)
│   ├── seed_data.py
│   ├── requirements.txt
│   ├── tests/
│   └── uploads/
├── database/          MySQL schema
├── deploy/            systemd units for the server (the agents' hourly timer)
├── docs/              Project documentation and ER diagram
├── scripts/           Local run helpers, the quality gate, the Compose preflight
├── docker-compose.yml The whole stack in containers (db, migrate, backend, frontend, agents)
├── .env.example       Optional settings for docker compose (never production credentials)
├── README.md
└── PROJECT_SCHEMA.md
```

Run the backend from `backend/`, the frontend from `frontend/`, and database setup
from the project root with `python backend/migrate.py` (see `database/README.md`).
