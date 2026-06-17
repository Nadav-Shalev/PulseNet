# PulseNet - Assignment 5

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

Create the database from the project root:

```bash
mysql -u root -p < database/schema.sql
```

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

Backend tests:

```bash
cd backend
python -m unittest discover tests
```

Frontend lint and production build:

```bash
cd frontend
npm run lint
npm run build
```

## Documentation

- Backend details: [backend/README.md](backend/README.md)
- Database schema: [database/schema.sql](database/schema.sql)
- ER diagram: [docs/db-diagram.md](docs/db-diagram.md)
- Project structure: [docs/project_structure.md](docs/project_structure.md)
- AWS deployment notes: [docs/aws_deployment.md](docs/aws_deployment.md)
