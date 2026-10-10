# syntax=docker/dockerfile:1
# The PulseNet API (and its CLIs: migrate.py, manage.py) in one image.
# Built from the repo root, so the migrations come along:
#   docker build -f backend/Dockerfile -t pulsenet-backend .
# docker-compose.yml builds it and runs it three ways: migrate, backend, agents.
# Settings come from the environment (docker-compose.yml), never from a .env file.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend

# Dependencies first, so a code change does not reinstall them. gunicorn is the
# production server, as on the EC2 (where it is installed into the venv by hand).
COPY backend/requirements.txt .
RUN pip install -r requirements.txt gunicorn==26.2.0

COPY database/migrations /app/database/migrations
COPY backend/ .

# .dockerignore keeps backend/.env out of the build context; fail the build if
# one ever gets in anyway. Then a non-root user that owns the writable folders
# (uploads/ and outbox/ are volumes in docker-compose.yml).
RUN test ! -e .env \
 && useradd --system --uid 10001 --no-create-home pulsenet \
 && mkdir -p uploads outbox \
 && chown pulsenet:pulsenet uploads outbox
USER pulsenet

EXPOSE 5000
# Two processes of four threads: Flask's dev server (python app.py) is threaded
# too. The LLM's daily limit is soft by the number of concurrent calls.
# --no-control-socket: gunicorn's control interface (a socket under $HOME) is not
# used, and this user has no home directory.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", \
     "--timeout", "60", "--access-logfile", "-", "--no-control-socket", "app:app"]
