# wgadminui

A secure web UI for administering WireGuard client configurations.

Built with **Django 6.0**, **django-allauth** (passkeys + email verification),
**wireguard-tools**, and **HTMX + Bootstrap 5**.

---

## Features

- **Invite-only** user registration (admin sends invitation email; no self-signup)
- **Passkey (WebAuthn) support** via django-allauth — enroll Touch ID, Face ID, Windows Hello, or hardware keys
- **Email verification** required for all accounts
- **Role-based access**: Admin users can manage all peers and invite new users; Members manage only their own
- **Per-interface peer management**: create, view, delete, and regenerate WireGuard client configurations
- **Live peer updates**: new peers are applied via `wg set`/`wg syncconf` without restarting WireGuard
- **QR code generation**: scan your configuration directly from the browser
- **Show-once private key**: private key is displayed exactly once and never stored
- **Status dashboard**: live `wg show` data (last handshake, bytes transferred, endpoint) per peer
- **IP auto-allocation**: next free address in the interface subnet is assigned automatically
- Traefik-ready docker-compose with documented labels

---

## Host prerequisites

The host machine must have WireGuard installed and configured:

```bash
# Debian/Ubuntu
sudo apt install wireguard wireguard-tools

# The interface must exist and be running
sudo wg-quick up wg0
```

The container bind-mounts `/etc/wireguard` from the host (read-write) and uses
the `NET_ADMIN` Linux capability to run `wg` commands without a full restart.

---

## Quick start

### 1. Clone and configure

```bash
git clone https://github.com/yourorg/wgadminui.git
cd wgadminui
cp .env.example .env
$EDITOR .env        # fill in all required values
```

### 2. Create the Traefik external network (if using Traefik)

```bash
docker network create traefik_network
```

### 3. Start the container

```bash
docker compose up -d
docker compose logs -f   # watch for startup messages
```

On first start the container will:
1. Apply all database migrations
2. Create the initial admin user (`WGADMINUI_ADMIN_EMAIL` / `WGADMINUI_ADMIN_PASSWORD`)
3. Start gunicorn on port 8000

### 4. Configure the WireGuard interface in the admin

Open `https://wgadminui.example.com` (or `http://localhost:8000`), log in as admin,
then go to **Django Admin → WireGuard → WireGuard interfaces → Add** and fill in:

| Field | Example | Notes |
|---|---|---|
| Name | `wg0` | Must match the `.conf` filename |
| Listen port | `51820` | Must match `[Interface] ListenPort` in the conf |
| Subnet | `10.0.0.0/24` | Subnet for peer IP allocation |
| Server public key | _(auto-fill)_ | Read from the running interface |
| Server endpoint host | `1.2.3.4` | Public IP/hostname for client configs |
| Conf file path | `/etc/wireguard/wg0.conf` | Absolute path in the container |

> **Tip:** The server public key can be found with `wg show wg0 public-key` on the host.

---

## Environment variables

All variables are prefixed `WGADMINUI_`. See `.env.example` for a full annotated list.

| Variable | Required | Default | Description |
|---|---|---|---|
| `WGADMINUI_SECRET_KEY` | ✅ | — | Django secret key (generate randomly) |
| `WGADMINUI_ALLOWED_HOSTS` | ✅ | `localhost` | Comma-separated hostnames |
| `WGADMINUI_ADMIN_EMAIL` | ✅ | — | Initial admin email |
| `WGADMINUI_ADMIN_PASSWORD` | ✅ | — | Initial admin password (change after first login) |
| `WGADMINUI_WG_SERVER_PUBLIC_IP` | ✅ | — | Server public IP for client config generation |
| `WGADMINUI_WG_INTERFACE` | | `wg0` | WireGuard interface name |
| `WGADMINUI_WG_SERVER_PORT` | | `51820` | WireGuard listen port |
| `WGADMINUI_PORT` | | `8000` | Gunicorn bind port |
| `WGADMINUI_DEBUG` | | `False` | Django debug mode |
| `WGADMINUI_TIME_ZONE` | | `UTC` | Display timezone |
| `WGADMINUI_EMAIL_BACKEND` | | console | `django.core.mail.backends.smtp.EmailBackend` for production |
| `WGADMINUI_EMAIL_HOST` | | `localhost` | SMTP host |
| `WGADMINUI_EMAIL_PORT` | | `587` | SMTP port |
| `WGADMINUI_EMAIL_USER` | | | SMTP username |
| `WGADMINUI_EMAIL_PASSWORD` | | | SMTP password |
| `WGADMINUI_EMAIL_USE_TLS` | | `True` | SMTP STARTTLS |
| `WGADMINUI_DEFAULT_FROM_EMAIL` | | `noreply@example.com` | Sender address |
| `WGADMINUI_WEBAUTHN_ALLOW_INSECURE_ORIGIN` | | `False` | Allow passkeys over HTTP (dev only) |
| `WGADMINUI_LOG_LEVEL` | | `INFO` | Python logging level |
| `WGADMINUI_GUNICORN_WORKERS` | | `3` | Gunicorn worker count |

---

## Traefik integration

The docker-compose file includes Traefik v2/v3 labels. Key labels:

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.wgadminui.rule=Host(`wgadminui.example.com`)"
  - "traefik.http.routers.wgadminui.entrypoints=websecure"
  - "traefik.http.routers.wgadminui.tls=true"
  - "traefik.http.routers.wgadminui.tls.certresolver=le"
  - "traefik.http.services.wgadminui.loadbalancer.server.port=8000"
```

Set `WGADMINUI_DOMAIN` and `TRAEFIK_CERTRESOLVER` in your `.env`.
Traefik terminates TLS; Django trusts the `X-Forwarded-Proto` header automatically.

---

## WireGuard configuration notes

### How peer changes are applied

When a new peer is created or deleted, wgadminui:
1. Updates the server-side `.conf` file (atomically, using a temp file + `os.replace()`)
2. Calls `wg syncconf wg0 /etc/wireguard/wg0.conf` to apply the diff live

Existing tunnels are **not disrupted**. No WireGuard restart is required.

### Private key security

The peer's private key is generated, used to build the client `.conf` and QR code,
shown to the user **exactly once**, and then **discarded** — it is never stored in
the database. Only the public key is persisted.

If a user loses their configuration, they can click **Regenerate keypair** on the
peer detail page. This generates a new keypair, replaces the server-side peer
entry, and presents the new configuration for saving.

### Logging and activity data

WireGuard kernel logging is available if `dyndbg` is enabled on the host:

```bash
echo module wireguard +p > /sys/kernel/debug/dynamic_debug/control
journalctl -k --grep wireguard -f
```

The status dashboard reads activity data via `wg show wg0 dump`, which provides
per-peer last-handshake timestamp, bytes transferred, and endpoint address
without requiring kernel logging.

---

## Development setup

```bash
python3 -m venv venv
source venv/bin/activate        # or: fish: source venv/bin/activate.fish
pip install -r requirements.txt

# Run with dev server
WGADMINUI_SECRET_KEY=dev WGADMINUI_DEBUG=True python manage.py migrate
WGADMINUI_SECRET_KEY=dev WGADMINUI_DEBUG=True \
  WGADMINUI_ADMIN_EMAIL=admin@example.com \
  WGADMINUI_ADMIN_PASSWORD=devpassword \
  python manage.py create_initial_admin
WGADMINUI_SECRET_KEY=dev WGADMINUI_DEBUG=True python manage.py runserver
```

Or use docker-compose in dev mode:

```bash
cp docker-compose.override.yml.example docker-compose.override.yml
docker compose up
```

---

## Project structure

```
wgadminui/
├── accounts/               # Custom User model, admin, management commands
│   └── management/commands/create_initial_admin.py
├── wireguard/              # WireGuard models, service layer, low-level wg helpers
│   ├── models.py           # WireguardInterface, PeerConfig, UserInterfaceAccess
│   ├── services.py         # keypair gen, IP allocation, peer lifecycle, status
│   └── wg_sync.py          # subprocess wrappers for wg CLI + atomic file writes
├── dashboard/              # UI views, forms, URLs
│   ├── views.py
│   └── urls.py
├── templates/              # Django templates (Bootstrap 5 + HTMX)
│   ├── base.html
│   └── dashboard/
├── wgadminui/              # Django project settings, root URLs, wsgi
├── Dockerfile
├── docker-compose.yml
├── docker-entrypoint.sh
├── .env.example
└── requirements.txt
```

---

## License

MIT
