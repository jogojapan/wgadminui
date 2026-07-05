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
RUN apt-get update && apt-get install -y --no-install-recommends \
    wireguard-tools \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application source
COPY . /app

# Collect static files at build time (whitenoise serves them from staticfiles/)
ARG WGADMINUI_SECRET_KEY=build-phase-placeholder
ARG WGADMINUI_DEBUG=False
ARG WGADMINUI_ALLOWED_HOSTS=localhost
RUN python manage.py collectstatic --noinput

# Data directory (SQLite DB and any runtime files)
RUN mkdir -p /app/data

# Non-root user for the application process.
# Note: wg commands require NET_ADMIN capability (set in docker-compose);
# they do NOT require running as root — only the capability matters.
RUN groupadd -r wgadmin && useradd -r -g wgadmin -d /app wgadmin \
    && chown -R wgadmin:wgadmin /app

# Give the wg binary the cap_net_admin file capability so our non-root user
# can run it without sudo. This works because docker-compose grants NET_ADMIN
# to the container, making file-capability elevation effective.
RUN setcap cap_net_admin+ep /usr/bin/wg 2>/dev/null || true

USER wgadmin

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
