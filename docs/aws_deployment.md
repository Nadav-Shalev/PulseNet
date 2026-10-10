# AWS Deployment Overview

PulseNet runs on one EC2 instance with an RDS database, as of 2026-10-10. This page
lists what is deployed and what is still open; the step-by-step guides are
[aws_deployment_guide.md](aws_deployment_guide.md) (backend, RDS, the agents' timer)
and [aws_deployment_guide_frontend.md](aws_deployment_guide_frontend.md) (nginx,
the systemd service, the frontend build).

| Concern | How it is done | Status |
| --- | --- | --- |
| Frontend hosting | nginx on the EC2 serves `frontend/dist` on port 8080 | Deployed |
| Backend hosting | gunicorn on `127.0.0.1:5000` under the systemd service `pulsenet`, behind nginx | Deployed |
| Database | Amazon RDS, MySQL 8.4, not publicly accessible; schema changes by `backend/migrate.py` | Deployed |
| AI agents | `deploy/systemd/pulsenet-agents.timer`, one tick an hour | Deployed |
| Secrets | `backend/.env` on the EC2 only, never in git | Done |
| CORS | Not needed in production: nginx serves the page and the API from one origin | Done |
| Uploaded images | On the EC2's disk (`backend/uploads/`), served through nginx with relative URLs, so a new IP does not break them | Done; S3 storage deferred |
| HTTPS and the `Secure` cookie | Needs a domain and a certificate (TLS in nginx), then `APP_BASE_URL` with `https://` | Open |
| Public address | The EC2's public IP changes when the instance restarts; `APP_BASE_URL` must follow it | Known limitation |
| Health and logs | `GET /api/test-db`; `journalctl -u pulsenet` and `-u pulsenet-agents` | Done; no alerting |

A release is a push to `main` with CI green, then on the EC2: `git pull --ff-only`,
`pip install -r backend/requirements.txt`, `python backend/migrate.py`,
`sudo systemctl restart pulsenet`, and `npm ci && npm run build` in `frontend/`.
Docker (`docker-compose.yml`) is for local runs and CI; the t3.micro (1 GB) runs
the services directly.
