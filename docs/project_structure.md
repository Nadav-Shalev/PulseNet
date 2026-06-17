# Project Structure

PulseNet is organized as a deployable full-stack project:

```text
PulseNet/
├── frontend/          React + Vite app
│   ├── public/
│   ├── src/
│   ├── .env.example
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── backend/           Flask API
│   ├── app.py
│   ├── seed_data.py
│   ├── requirements.txt
│   ├── tests/
│   └── uploads/
├── database/          MySQL schema
├── docs/              Project documentation and ER diagram
├── scripts/           Local run helpers
├── README.md
└── PROJECT_SCHEMA.md
```

Run the backend from `backend/`, the frontend from `frontend/`, and database setup
from the project root using `database/schema.sql`.
