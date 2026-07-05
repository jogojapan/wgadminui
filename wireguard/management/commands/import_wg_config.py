"""
Management command: import_wg_config

Imports an existing WireGuard .conf file (e.g. /etc/wireguard/wg0.conf) into
the wgadminui database.  This is the typical first-run workflow when the host
already has a manually-configured WireGuard interface.

What it does:
  1. Parses the [Interface] section to extract ListenPort, Address (subnet),
     and PrivateKey.
  2. Derives the server public key from the private key.
  3. Creates or updates the WireguardInterface DB record.
  4. Parses all [Peer] sections and creates PeerConfig records for any peers
     not already tracked in the database.
  5. Assigns imported peers to the admin user specified by --admin-email.

Idempotent: safe to run multiple times.  Existing interface records are
updated; existing peers (matched by public key) are skipped.

Usage:
    python manage.py import_wg_config
    python manage.py import_wg_config --conf /etc/wireguard/wg0.conf
    python manage.py import_wg_config --admin-email admin@example.com
    python manage.py import_wg_config --dry-run
"""

import ipaddress
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from wireguard_tools import WireguardKey

from wireguard.models import PeerConfig, WireguardInterface

User = get_user_model()


def _parse_conf(conf_path: str) -> dict:
    """
    Parse a WireGuard .conf file and return a dict with:
        interface: {private_key, public_key, listen_port, address}
        peers: [{public_key, allowed_ips, comment, endpoint, persistent_keepalive}, ...]
    """
    with open(conf_path) as fh:
        content = fh.read()

    # Split into [Interface] and [Peer] sections
    sections = re.split(r"\n(?=\[)", content)

    interface_data: dict = {}
    peers: list[dict] = []
    pending_comment = ""  # comment line that precedes the next [Peer]

    for section in sections:
        section = section.strip()
        if not section:
            continue

        header_match = re.match(r"\[(\w+)\]", section)
        if not header_match:
            # No header — this is a comment block sitting between two
            # [Peer] sections (e.g. "# Alice's Laptop" on its own line
            # before the next [Peer]).  Save it and attach to the next peer.
            for line in section.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    pending_comment = stripped.lstrip("#").strip()
            continue

        section_type = header_match.group(1)

        # Extract key = value pairs
        kv = {}
        for line in section.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"(\w+)\s*=\s*(.+)", line)
            if m:
                kv[m.group(1)] = m.group(2).strip()

        if section_type == "Interface":
            interface_data = kv
        elif section_type == "Peer":
            # Prefer a comment inside the [Peer] section; fall back to a
            # pending comment that appeared right before this [Peer] block.
            comment = ""
            for line in section.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    comment = stripped.lstrip("#").strip()
                    break

            if not comment and pending_comment:
                comment = pending_comment

            pending_comment = ""  # consumed

            peers.append(
                {
                    "public_key": kv.get("PublicKey", ""),
                    "allowed_ips": kv.get("AllowedIPs", ""),
                    "comment": comment,
                    "endpoint": kv.get("Endpoint", ""),
                    "persistent_keepalive": kv.get("PersistentKeepalive", ""),
                }
            )

    return {"interface": interface_data, "peers": peers}


def _derive_public_key(private_key: str) -> str:
    """Derive the public key from a WireGuard private key."""
    key = WireguardKey(private_key)
    return str(key.public_key())


def _subnet_from_address(address: str) -> str:
    """
    Given an Address like '10.0.0.1/24', return the network address
    like '10.0.0.0/24'.
    """
    iface = ipaddress.ip_interface(address.strip())
    return str(iface.network)


class Command(BaseCommand):
    help = "Import an existing WireGuard .conf file into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--conf",
            default=None,
            help=(
                "Path to the WireGuard .conf file. "
                "Defaults to <WGADMINUI_WG_CONF_DIR>/<WGADMINUI_WG_INTERFACE>.conf "
                "(e.g. /etc/wireguard/wg0.conf)."
            ),
        )
        parser.add_argument(
            "--admin-email",
            default=None,
            help=(
                "Email of the admin user to assign imported peers to. "
                "Defaults to WGADMINUI_ADMIN_EMAIL from the environment."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and validate the conf file without writing to the database.",
        )
        parser.add_argument(
            "--force-peer-import",
            action="store_true",
            help=(
                "Import peers even if they already exist in the database "
                "(by default, existing peers are skipped)."
            ),
        )

    def handle(self, *args, **options):
        # Determine conf file path
        conf_path = options["conf"]
        if not conf_path:
            wg_conf_dir = getattr(settings, "WGADMINUI_WG_CONF_DIR", "/etc/wireguard")
            wg_interface = getattr(settings, "WGADMINUI_WG_INTERFACE", "wg0")
            conf_path = str(Path(wg_conf_dir) / f"{wg_interface}.conf")

        if not Path(conf_path).exists():
            raise CommandError(f"Configuration file not found: {conf_path}")

        self.stdout.write(f"Reading configuration from: {conf_path}")

        # Parse the conf file
        parsed = _parse_conf(conf_path)
        iface_data = parsed["interface"]
        peers_data = parsed["peers"]

        if not iface_data:
            raise CommandError(
                f"No [Interface] section found in {conf_path}. "
                "Is this a valid WireGuard configuration?"
            )

        # Derive server public key
        private_key = iface_data.get("PrivateKey", "")
        if not private_key:
            raise CommandError(
                "No PrivateKey found in [Interface] section. "
                "Cannot derive server public key."
            )

        try:
            server_public_key = _derive_public_key(private_key)
        except Exception as exc:
            raise CommandError(
                f"Failed to derive public key from PrivateKey: {exc}"
            ) from exc

        # Extract listen port
        listen_port = int(iface_data.get("ListenPort", 51820))

        # Extract subnet from Address
        address = iface_data.get("Address", "")
        if not address:
            raise CommandError(
                "No Address found in [Interface] section. "
                "Cannot determine peer subnet."
            )
        subnet = _subnet_from_address(address)

        # Determine interface name from the conf filename
        interface_name = Path(conf_path).stem  # e.g. "wg0"

        # Server endpoint from settings
        server_endpoint_host = getattr(
            settings, "WGADMINUI_WG_SERVER_PUBLIC_IP", ""
        )
        if not server_endpoint_host:
            self.stdout.write(
                self.style.WARNING(
                    "WGADMINUI_WG_SERVER_PUBLIC_IP is not set. "
                    "The server endpoint host will be empty — you should set it "
                    "in the admin panel or via environment variable."
                )
            )

        # Determine admin user
        admin_email = options["admin_email"]
        if not admin_email:
            from decouple import config as decouple_config
            admin_email = decouple_config("WGADMINUI_ADMIN_EMAIL", default="")

        if not admin_email:
            raise CommandError(
                "No admin email specified. Use --admin-email or set "
                "WGADMINUI_ADMIN_EMAIL in the environment."
            )

        try:
            admin_user = User.objects.get(email=admin_email)
        except User.DoesNotExist:
            raise CommandError(
                f"Admin user with email '{admin_email}' does not exist. "
                "Create the admin user first (e.g. via the create_initial_admin "
                "command or through the Django admin)."
            )

        if not admin_user.is_admin_user:
            self.stdout.write(
                self.style.WARNING(
                    f"User '{admin_email}' is not an admin. "
                    "Imported peers will still be assigned to this user."
                )
            )

        # --- Summary ---
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Parsed configuration:"))
        self.stdout.write(f"  Interface name:    {interface_name}")
        self.stdout.write(f"  Listen port:       {listen_port}")
        self.stdout.write(f"  Subnet:            {subnet}")
        self.stdout.write(f"  Server public key: {server_public_key}")
        self.stdout.write(f"  Endpoint host:     {server_endpoint_host or '(not set)'}")
        self.stdout.write(f"  Conf file path:    {conf_path}")
        self.stdout.write(f"  Peers found:       {len(peers_data)}")
        self.stdout.write(f"  Admin user:        {admin_email}")
        self.stdout.write("")

        if options["dry_run"]:
            self.stdout.write(self.style.NOTICE("DRY RUN — no changes made."))
            for i, peer in enumerate(peers_data, 1):
                name = peer["comment"] or f"peer-{i}"
                self.stdout.write(
                    f"  [{i}] {name}  "
                    f"PublicKey={peer['public_key'][:12]}...  "
                    f"AllowedIPs={peer['allowed_ips']}"
                )
            return

        # --- Create or update WireguardInterface ---
        iface, created = WireguardInterface.objects.update_or_create(
            name=interface_name,
            defaults={
                "listen_port": listen_port,
                "subnet": subnet,
                "server_public_key": server_public_key,
                "server_endpoint_host": server_endpoint_host,
                "conf_file_path": conf_path,
            },
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created WireguardInterface '{interface_name}'."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Updated existing WireguardInterface '{interface_name}'."
                )
            )

        # --- Import peers ---
        imported = 0
        skipped = 0
        errors = 0

        for i, peer_data in enumerate(peers_data, 1):
            public_key = peer_data["public_key"]
            allowed_ips = peer_data["allowed_ips"]

            if not public_key:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Peer #{i}: missing PublicKey — skipping."
                    )
                )
                errors += 1
                continue

            if not allowed_ips:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Peer #{i} ({public_key[:12]}...): "
                        "missing AllowedIPs — skipping."
                    )
                )
                errors += 1
                continue

            # Check if peer already exists (by public key)
            existing = PeerConfig.objects.filter(
                peer_public_key=public_key
            ).first()

            if existing and not options["force_peer_import"]:
                name = peer_data["comment"] or f"peer-{i}"
                self.stdout.write(
                    f"  Peer '{name}' ({public_key[:12]}...): "
                    "already exists — skipping."
                )
                skipped += 1
                continue

            # Determine peer name
            name = peer_data["comment"] or f"imported-peer-{i}"

            if existing and options["force_peer_import"]:
                # Update existing peer's interface association
                existing.interface = iface
                existing.allowed_ips = allowed_ips
                existing.name = name
                existing.setup_acknowledged = True
                existing.save(
                    update_fields=[
                        "interface", "allowed_ips", "name",
                        "setup_acknowledged"
                    ]
                )
                self.stdout.write(
                    f"  Peer '{name}' ({public_key[:12]}...): updated."
                )
                imported += 1
            else:
                PeerConfig.objects.create(
                    owner=admin_user,
                    interface=iface,
                    name=name,
                    peer_public_key=public_key,
                    allowed_ips=allowed_ips,
                    dns="1.1.1.1,1.0.0.1",
                    setup_acknowledged=True,
                )
                self.stdout.write(
                    f"  Peer '{name}' ({public_key[:12]}...): imported."
                )
                imported += 1

        # --- Final summary ---
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete: {imported} imported, "
                f"{skipped} skipped, {errors} errors."
            )
        )

        if imported > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    "The conf file has NOT been modified.  The next time a peer "
                    "is created, modified, or deleted through the web UI, the "
                    "conf file will be rebuilt from the database (preserving "
                    "the [Interface] section including the server private key)."
                )
            )