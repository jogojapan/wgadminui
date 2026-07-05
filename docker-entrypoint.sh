#!/bin/sh
# docker-entrypoint.sh — runs on every container start
#
# Starts as root so it can create / chown the data directory for bind-mount
# setups, then drops to the wgadmin user via gosu before running Django.
set -e

# Ensure the data directory exists and is owned by wgadmin.
# This is a no-op for named volumes (already correct) but essential for
# bind-mounts where the host directory may be owned by root or another user.
DATA_DIR="${WGADMINUI_DATA_DIR:-/app/data}"
mkdir -p "$DATA_DIR"
chown wgadmin:wgadmin "$DATA_DIR"

echo "[entrypoint] Applying database migrations..."
gosu wgadmin python manage.py migrate --noinput

echo "[entrypoint] Creating initial admin user (if not exists)..."
gosu wgadmin python manage.py create_initial_admin || true

echo "[entrypoint] Starting gunicorn..."
exec gosu wgadmin gunicorn wgadminui.wsgi:application \
    --bind "0.0.0.0:${WGADMINUI_PORT:-8000}" \
    --workers "${WGADMINUI_GUNICORN_WORKERS:-3}" \
    --timeout "${WGADMINUI_GUNICORN_TIMEOUT:-60}" \
    --access-logfile - \
    --error-logfile -
