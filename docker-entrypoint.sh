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
chown -R wgadmin:wgadmin "$DATA_DIR"

# Fix WireGuard config directory permissions so the wgadmin user can
# read and write .conf files after we drop privileges.  The host's
# /etc/wireguard is typically 0700 root:root; without this fix the
# application will get PermissionError on every conf file operation.
# This is safe because:
#   - wg-quick and systemd run as root (bypass all permission checks)
#   - The container already has NET_ADMIN on the host network namespace
if [ -d /etc/wireguard ]; then
    chown -R wgadmin:wgadmin /etc/wireguard
    chmod 750 /etc/wireguard
    find /etc/wireguard -name '*.conf' -exec chmod 640 {} \;
fi

echo "[entrypoint] Applying database migrations..."
gosu wgadmin python manage.py migrate --noinput

echo "[entrypoint] Syncing site domain and name..."
gosu wgadmin python manage.py sync_site || true

echo "[entrypoint] Creating initial admin user (if not exists)..."
gosu wgadmin python manage.py create_initial_admin || true

echo "[entrypoint] Starting gunicorn..."
# With network_mode: host, Gunicorn binds directly to the host's port.
# WGADMINUI_PORT controls the actual bind port (default 8000).
exec gosu wgadmin gunicorn wgadminui.wsgi:application \
    --bind "0.0.0.0:${WGADMINUI_PORT:-8000}" \
    --workers "${WGADMINUI_GUNICORN_WORKERS:-3}" \
    --timeout "${WGADMINUI_GUNICORN_TIMEOUT:-60}" \
    --access-logfile - \
    --error-logfile -
