# ── Build stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into an isolated prefix so we can copy them
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Runtime stage ────────────────────────────────────────────────────────────
FROM python:3.12-slim

# Runtime system dependencies:
#   wireguard-tools  → provides the `wg` binary
#   iproute2         → provides `ip` (needed by wg-quick, useful for diagnostics)
#   gosu             → used by the entrypoint to drop from root to wgadmin after
#                      fixing bind-mount directory ownership at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    wireguard-tools \
    iproute2 \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application source
COPY . /app

# Collect static files at build time (whitenoise serves them from staticfiles/)
# Using inline env vars instead of ARG to avoid Docker's "SecretsUsedInArgOrEnv" warning
RUN WGADMINUI_SECRET_KEY=build-phase-placeholder \
    WGADMINUI_DEBUG=False \
    WGADMINUI_ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput

# Non-root user for the application process.
# Note: wg commands require NET_ADMIN capability (set in docker-compose);
# they do NOT require running as root — only the capability matters.
#
# A fixed UID/GID (1000) is used so that bind-mounted host directories can be
# pre-owned with a known UID (e.g. `sudo chown -R 1000:1000 /fastspace/wgadminui/data`).
RUN groupadd -g 1000 wgadmin && useradd -u 1000 -g wgadmin -d /app wgadmin \
    && mkdir -p /app/data \
    && chown -R wgadmin:wgadmin /app

# Give the wg binary the cap_net_admin file capability so our non-root user
# can run it without sudo. This works because docker-compose grants NET_ADMIN
# to the container, making file-capability elevation effective.
RUN setcap cap_net_admin+ep /usr/bin/wg 2>/dev/null || true

# The entrypoint starts as root so it can fix bind-mount ownership, then
# drops to wgadmin via gosu before exec-ing the application.
# Do NOT add USER here.

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
