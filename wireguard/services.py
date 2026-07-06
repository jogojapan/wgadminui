"""
wireguard/services.py

High-level WireGuard business logic:
  - Keypair generation
  - Client .conf text building
  - QR code generation (PNG data URI)
  - IP allocation from interface subnet
  - Peer lifecycle (create, remove, regenerate)
  - Status queries
"""

import ipaddress
import io
import logging
import time
from typing import Any

import segno
from wireguard_tools import WireguardKey

from . import wg_sync
from .models import PeerConfig, WireguardInterface

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Keypair helpers
# ---------------------------------------------------------------------------


def generate_keypair() -> tuple[str, str]:
    """
    Generate a new WireGuard keypair.
    Returns (private_key_b64, public_key_b64).
    """
    private_key = WireguardKey.generate()
    public_key = private_key.public_key()
    return str(private_key), str(public_key)


# ---------------------------------------------------------------------------
# Client config text
# ---------------------------------------------------------------------------


def build_client_conf(
    private_key: str,
    peer_ip: str,
    server_public_key: str,
    server_endpoint: str,
    server_port: int,
    dns: str = "1.1.1.1,1.0.0.1",
    persistent_keepalive: int = 25,
) -> str:
    """
    Build the text content of a WireGuard client .conf file.

    Parameters
    ----------
    private_key : str
        The client's WireGuard private key (base64).
    peer_ip : str
        The client's assigned IP, e.g. "10.0.0.2".
    server_public_key : str
        The server's public key (base64).
    server_endpoint : str
        The server's public hostname or IP.
    server_port : int
        The server's listen port.
    dns : str
        Comma-separated DNS servers.
    persistent_keepalive : int
        Keepalive interval in seconds (useful for NAT traversal).
    """
    dns_line = f"DNS = {dns}\n" if dns else ""
    return (
        f"[Interface]\n"
        f"PrivateKey = {private_key}\n"
        f"Address = {peer_ip}/32\n"
        f"{dns_line}"
        f"\n"
        f"[Peer]\n"
        f"PublicKey = {server_public_key}\n"
        f"Endpoint = {server_endpoint}:{server_port}\n"
        f"AllowedIPs = 0.0.0.0/0, ::/0\n"
        f"PersistentKeepalive = {persistent_keepalive}\n"
    )


# ---------------------------------------------------------------------------
# QR code
# ---------------------------------------------------------------------------


def conf_to_qr_data_uri(conf_text: str) -> str:
    """
    Encode the conf text as a QR code and return a PNG data URI
    suitable for use directly in an <img src="..."> attribute.
    """
    qr = segno.make(conf_text, error="L")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=4, dark="#000000", light="#ffffff")
    import base64
    data = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{data}"


# ---------------------------------------------------------------------------
# IP allocation
# ---------------------------------------------------------------------------


def allocate_peer_ip(interface: WireguardInterface, manual_ip: str | None = None) -> str:
    """
    Allocate the next free host IP in the interface's subnet.

    If *manual_ip* is provided (e.g. "10.0.0.5"), validate it is in the
    subnet and not already used; raise ValueError if not.

    Skips:
      - Network address (.0)
      - Broadcast address (last)
      - First host address (.1 — assumed to be the server)

    Returns an IP string without prefix, e.g. "10.0.0.2".
    Raises ValueError if no free IP is available.
    """
    network = ipaddress.ip_network(interface.subnet, strict=False)

    # Gather used IPs from DB
    used_ips: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for peer in PeerConfig.objects.filter(interface=interface):
        try:
            used_ips.add(ipaddress.ip_interface(peer.allowed_ips).ip)
        except ValueError:
            pass

    # Also gather live IPs from the running interface (may include manually
    # added peers not in our DB)
    for live_peer in wg_sync.show_dump(interface.name):
        try:
            for aip in live_peer["allowed_ips"].split(","):
                used_ips.add(ipaddress.ip_interface(aip.strip()).ip)
        except ValueError:
            pass

    if manual_ip:
        ip = ipaddress.ip_address(manual_ip.strip())
        if ip not in network:
            raise ValueError(f"{manual_ip} is not within subnet {interface.subnet}")
        if ip in used_ips:
            raise ValueError(f"{manual_ip} is already in use")
        return str(ip)

    # Auto-allocate: skip network, broadcast, and .1 (server)
    hosts = list(network.hosts())
    # Reserve first host for the server
    reserved = {network.network_address, network.broadcast_address, hosts[0]}
    for host in hosts[1:]:
        if host not in used_ips and host not in reserved:
            return str(host)

    raise ValueError(f"No free IP addresses in subnet {interface.subnet}")


# ---------------------------------------------------------------------------
# Peer lifecycle
# ---------------------------------------------------------------------------


def create_peer(
    interface: WireguardInterface,
    owner: Any,  # accounts.User
    name: str,
    dns: str = "1.1.1.1,1.0.0.1",
    manual_ip: str | None = None,
) -> tuple[PeerConfig, str, str]:
    """
    Create a new WireGuard peer.

    1. Generate keypair
    2. Allocate IP
    3. Persist PeerConfig (public key only, private key discarded after return)
    4. Add peer to live interface + sync conf file

    Returns (peer_config, private_key, conf_text).
    The caller MUST show the private_key / conf_text to the user immediately;
    after this function returns the private key is not stored anywhere.
    """
    private_key, public_key = generate_keypair()
    peer_ip = allocate_peer_ip(interface, manual_ip=manual_ip)

    peer = PeerConfig.objects.create(
        owner=owner,
        interface=interface,
        name=name,
        peer_public_key=public_key,
        allowed_ips=f"{peer_ip}/32",
        dns=dns,
    )

    conf_text = build_client_conf(
        private_key=private_key,
        peer_ip=peer_ip,
        server_public_key=interface.server_public_key,
        server_endpoint=interface.server_endpoint_host,
        server_port=interface.listen_port,
        dns=dns,
    )

    # Apply to live interface
    try:
        wg_sync.set_peer(interface.name, public_key, f"{peer_ip}/32")
        _sync_conf_file(interface)
        peer.last_sync_at = _now()
        peer.save(update_fields=["last_sync_at"])
    except Exception as exc:
        logger.error("Failed to apply peer %s to interface: %s", peer.id, exc)
        # Peer exists in DB; admin can resync manually
        # Don't roll back the DB entry since the conf file may need updating

    return peer, private_key, conf_text


def regenerate_peer_keypair(peer: PeerConfig) -> tuple[str, str]:
    """
    Generate a fresh keypair for an existing peer.

    Removes the old public key from the live interface, registers the new
    one, updates the conf file, and saves the new public key to the DB.

    Returns (private_key, conf_text) — show-once, caller must display.
    """
    interface = peer.interface
    old_public_key = peer.peer_public_key

    private_key, new_public_key = generate_keypair()

    peer_ip = peer.peer_ip

    conf_text = build_client_conf(
        private_key=private_key,
        peer_ip=peer_ip,
        server_public_key=interface.server_public_key,
        server_endpoint=interface.server_endpoint_host,
        server_port=interface.listen_port,
        dns=peer.dns,
    )

    # Update live interface: remove old key, add new
    try:
        wg_sync.remove_peer(interface.name, old_public_key)
        wg_sync.set_peer(interface.name, new_public_key, peer.allowed_ips)
        _sync_conf_file(interface)
    except Exception as exc:
        logger.error("Failed to update peer keypair on interface: %s", exc)

    # Update DB
    peer.peer_public_key = new_public_key
    peer.setup_acknowledged = False
    peer.last_sync_at = _now()
    peer.save(update_fields=["peer_public_key", "setup_acknowledged", "last_sync_at"])

    return private_key, conf_text


def delete_peer(peer: PeerConfig) -> None:
    """Remove a peer from the live interface, conf file, and DB."""
    interface = peer.interface
    public_key = peer.peer_public_key
    # Delete from DB first so _sync_conf_file rebuilds the conf without this peer.
    peer.delete()
    try:
        wg_sync.remove_peer(interface.name, public_key)
        _sync_conf_file(interface)
    except Exception as exc:
        logger.error("Failed to remove peer from interface: %s", exc)


# ---------------------------------------------------------------------------
# Conf file management
# ---------------------------------------------------------------------------


def _sync_conf_file(interface: WireguardInterface) -> None:
    """
    Rebuild the WireGuard conf file from DB peers and call wg syncconf.
    """
    conf_text = _build_server_conf(interface)
    wg_sync.atomic_write(interface.conf_file_path, conf_text)
    wg_sync.syncconf(interface.name, interface.conf_file_path)


def _build_server_conf(interface: WireguardInterface) -> str:
    """
    Build the server-side WireGuard .conf file content from the DB.
    NOTE: This does NOT include the server private key (already in the file).
    We read the existing file, extract the [Interface] section, and rebuild
    the [Peer] sections from the DB.
    """
    import re

    # Read existing file to preserve the [Interface] section
    try:
        with open(interface.conf_file_path) as fh:
            existing = fh.read()
    except FileNotFoundError:
        existing = ""

    # Extract [Interface] block (everything up to the first [Peer])
    match = re.split(r"\n\[Peer\]", existing, maxsplit=1)
    interface_block = match[0].rstrip() + "\n"

    # Build [Peer] sections from DB
    peer_sections = []
    for peer in PeerConfig.objects.filter(interface=interface).order_by("created_at"):
        peer_sections.append(
            f"\n[Peer]\n"
            f"# {peer.name} ({peer.owner.email})\n"
            f"PublicKey = {peer.peer_public_key}\n"
            f"AllowedIPs = {peer.allowed_ips}\n"
        )

    return interface_block + "".join(peer_sections)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def get_peer_status(interface: WireguardInterface) -> dict[str, dict]:
    """
    Return live status for all peers, keyed by public key.
    Each value: {last_handshake, last_seen_ago_s, rx_bytes, tx_bytes, endpoint, online}
    """
    now = int(time.time())
    status: dict[str, dict] = {}
    for peer_data in wg_sync.show_dump(interface.name):
        lhs = peer_data["latest_handshake"]
        last_seen_ago = (now - lhs) if lhs else None
        status[peer_data["public_key"]] = {
            "last_handshake": lhs,
            "last_seen_ago_s": last_seen_ago,
            # WireGuard considers a peer "online" if it sent a handshake
            # within the last ~3 minutes (180s) — keys rotate every 3 min
            "online": last_seen_ago is not None and last_seen_ago < 180,
            "rx_bytes": peer_data["transfer_rx"],
            "tx_bytes": peer_data["transfer_tx"],
            "endpoint": peer_data["endpoint"],
        }
    return status


def get_interface_info(interface: WireguardInterface) -> dict:
    """
    Return a dict with live interface info and systemctl status text.
    Keys: running (bool), public_key, listen_port, systemctl_output
    """
    iface_data = wg_sync.show_interface(interface.name)
    running = iface_data is not None
    systemctl_output = wg_sync.systemctl_status(interface.name)

    return {
        "running": running,
        "public_key": iface_data["public_key"] if iface_data else None,
        "listen_port": iface_data["listen_port"] if iface_data else None,
        "systemctl_output": systemctl_output,
        "systemctl_available": systemctl_output is not None,
    }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _now():
    from django.utils import timezone
    return timezone.now()
