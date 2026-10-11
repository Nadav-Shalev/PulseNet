# AWS Deployment Overview

PulseNet runs on one EC2 instance with an RDS database, at
**<https://app.pulsenet-services.com>** (as of 2026-10-10). This page lists what is
deployed and what is still open; the step-by-step guides are
[aws_deployment_guide.md](aws_deployment_guide.md) (backend, RDS, the agents' timer)
and [aws_deployment_guide_frontend.md](aws_deployment_guide_frontend.md) (nginx,
the systemd service, the frontend build; it describes the first, HTTP-only setup on
port 8080, which "HTTPS" below replaces).

| Concern | How it is done | Status |
| --- | --- | --- |
| Frontend hosting | nginx on the EC2 serves `frontend/dist` over HTTPS (port 443) | Deployed |
| Backend hosting | gunicorn on `127.0.0.1:5000` under the systemd service `pulsenet`, behind nginx | Deployed |
| Database | Amazon RDS, MySQL 8.4, not publicly accessible; schema changes by `backend/migrate.py` | Deployed |
| AI agents | `deploy/systemd/pulsenet-agents.timer`, one tick an hour | Deployed |
| Secrets | `backend/.env` on the EC2 only, never in git | Done |
| CORS | Not needed in production: nginx serves the page and the API from one origin | Done |
| Uploaded images | On the EC2's disk (`backend/uploads/`), served through nginx with relative URLs | Done; S3 storage deferred |
| HTTPS and the `Secure` cookie | Let's Encrypt certificate in nginx, `SESSION_COOKIE_SECURE=1`, `APP_BASE_URL` with `https://` | Done |
| Public address | `app.pulsenet-services.com`: an `A` record (Squarespace DNS) to the EC2's Elastic IP, so it survives a stop and start | Done |
| Health and logs | `GET /api/test-db`; `journalctl -u pulsenet` and `-u pulsenet-agents` | Done; no alerting |

A release is a push to `main` with CI green, then on the EC2: `git pull --ff-only`,
`pip install -r backend/requirements.txt`, `python backend/migrate.py`,
`sudo systemctl restart pulsenet`, and `npm ci && npm run build` in `frontend/`.
Docker (`docker-compose.yml`) is for local runs and CI; the t3.micro (1 GB) runs
the services directly.

## HTTPS

nginx owns ports 80 and 443; its whole configuration is
[`deploy/nginx/pulsenet.conf`](../deploy/nginx/pulsenet.conf), copied to
`/etc/nginx/conf.d/pulsenet.conf`:

- `https://app.pulsenet-services.com`: TLS 1.2/1.3, HSTS (one day, this host only),
  `nosniff`, `X-Frame-Options`, `Referrer-Policy`; the build, `/api/` and `/uploads/`.
- Port 80: only the Let's Encrypt challenge (`/.well-known/acme-challenge/` from
  `/var/www/letsencrypt`); everything else is redirected to HTTPS.
- Port 8080, the first address: a redirect to the domain.

Apache (phpMyAdmin) listens only on `127.0.0.1:81`, so phpMyAdmin is no longer on
the internet; it is reached through an SSH tunnel:
`ssh -L 8081:127.0.0.1:81 <ec2>`, then `http://localhost:8081/phpmyadmin/`.

The certificate was issued once with certbot's webroot method. `pulsenet.conf`
names the certificate files, so the first run uses
[`deploy/nginx/acme-bootstrap.conf`](../deploy/nginx/acme-bootstrap.conf) (port 80
and the challenge only):

```bash
sudo dnf install -y certbot && sudo mkdir -p /var/www/letsencrypt
sudo cp deploy/nginx/acme-bootstrap.conf /etc/nginx/conf.d/ && sudo nginx -t && sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/letsencrypt -d app.pulsenet-services.com \
  --agree-tos --register-unsafely-without-email --non-interactive \
  --deploy-hook "systemctl reload nginx"          # first with --dry-run
sudo rm /etc/nginx/conf.d/acme-bootstrap.conf
sudo cp deploy/nginx/pulsenet.conf /etc/nginx/conf.d/pulsenet.conf && sudo nginx -t && sudo systemctl reload nginx
sudo systemctl enable --now certbot-renew.timer && sudo certbot renew --dry-run
```

`certbot-renew.timer` renews the certificate before it expires (90 days) through
the same webroot, and the deploy hook reloads nginx. In `backend/.env`,
`APP_BASE_URL=https://app.pulsenet-services.com` and `SESSION_COOKIE_SECURE=1`
(then `sudo systemctl restart pulsenet`).

The setup was checked from outside on 2026-10-11: TLS 1.0 and 1.1 are refused,
the certificate chain verifies, every plain-HTTP address answers `301` to HTTPS,
the session cookie is set and cleared with `Secure; HttpOnly; SameSite=Lax`, an
upload is served over HTTPS, and a password-reset mail links to
`https://app.pulsenet-services.com/reset-password#token=...`. No stored post,
comment or avatar links to `http://`, so the pages carry no mixed content.

## Operational Risks

- **The instance and the database can be stopped from outside the project.** On
  2026-10-10/11 both the EC2 and RDS were found stopped overnight; the cause (for
  example a policy of the course's AWS account) is not confirmed. The Elastic IP
  keeps the address and the DNS record valid, and every service on the EC2 starts
  on boot, but RDS must be started again by hand. While it is down, the feed falls
  back to the mock data, other reads and every write answer `503`, and the agents'
  ticks fail and pick up again at the next tick. Check both before a demonstration: `GET /api/test-db`
  must answer `{"status": "ok"}`.
- **Certificate renewal needs port 80 and the DNS record.** `certbot-renew.timer`
  runs twice a day; a renewal fails if the domain stops pointing at the instance or
  port 80 is closed. The certificate is valid for 90 days.

## Deferred

- **Images in S3.** Uploads stay on the instance's disk; moving them to a private
  bucket behind presigned URLs was planned and postponed.
- **A Content-Security-Policy.** The editor (Quill) and MUI rely on inline styles,
  so a strict policy needs testing of its own; the other security headers are set.
- **Monitoring and alerting.** There are logs (`journalctl`) and a health endpoint,
  but nothing notifies anyone when the site or the database goes down.
- **One instance.** No load balancer and no second instance; systemd restarts the
  services, and a t3.micro (1 GB) is enough for the project's traffic.
