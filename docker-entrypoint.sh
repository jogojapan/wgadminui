#!/bin/sh
# docker-entrypoint.sh — runs on every container start
set -e

echo "[entrypoint] Applying database migrations..."
python manage.py migrate --noinput

echo "[entrypoint] Creating initial admin user (if not exists)..."
python manage.py create_initial_admin || true

echo "[entrypoint] Starting gunicorn..."
exec gunicorn wgadminui.wsgi:application \
    --bind "0.0.0.0:${WGADMINUI_PORT:-8000}" \
    --workers "${WGADMINUI_GUNICORN_WORKERS:-3}" \
    --timeout "${WGADMINUI_GUNICORN_TIMEOUT:-60}" \
    --access-logfile - \
    --error-logfile -
