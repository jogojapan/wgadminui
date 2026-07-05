"""
wireguard/wg_sync.py

Low-level helpers for safe WireGuard conf file writes and applying
live changes to a running WireGuard interface via subprocess.

All subprocess calls require that the process has NET_ADMIN capability
and that the `wg` binary is available on PATH inside the container.
"""

import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)


def _run(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command, log it, and return the CompletedProcess."""
    logger.debug("wg_sync: running %s", " ".join(args))
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        logger.error(
            "wg_sync: command %s failed (rc=%d): %s",
            " ".join(args),
            result.returncode,
            result.stderr,
        )
        raise RuntimeError(
            f"Command {' '.join(args)!r} failed with rc={result.returncode}: "
            f"{result.stderr.strip()}"
        )
    return result


def atomic_write(path: str, content: str) -> None:
    """
    Write *content* to *path* atomically using a temp file + os.replace().
    Preserves directory ownership/permissions as much as possible.
    """
    dir_path = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, prefix=".wg_tmp_")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        # Same permissions as original if it exists
        try:
            orig_stat = os.stat(path)
            os.chmod(tmp_path, orig_stat.st_mode)
        except FileNotFoundError:
            os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
        logger.info("wg_sync: wrote %s atomically", path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def syncconf(interface_name: str, conf_path: str) -> None:
    """
    Apply the conf file to a running interface without disrupting existing
    sessions.  Uses `wg syncconf` which only adds/removes/changes peers
    that differ.
    """
    _run(["wg", "syncconf", interface_name, conf_path])
    logger.info("wg_sync: syncconf applied to %s", interface_name)


def set_peer(
    interface_name: str,
    public_key: str,
    allowed_ips: str,
    endpoint: str | None = None,
    persistent_keepalive: int | None = None,
) -> None:
    """
    Add or update a single peer live via `wg set`.
    Does NOT restart WireGuard.
    """
    args = ["wg", "set", interface_name, "peer", public_key, "allowed-ips", allowed_ips]
    if endpoint:
        args += ["endpoint", endpoint]
    if persistent_keepalive is not None:
        args += ["persistent-keepalive", str(persistent_keepalive)]
    _run(args)
    logger.info("wg_sync: set peer %s on %s", public_key[:8] + "…", interface_name)


def remove_peer(interface_name: str, public_key: str) -> None:
    """Remove a peer live via `wg set … remove`."""
    _run(["wg", "set", interface_name, "peer", public_key, "remove"])
    logger.info("wg_sync: removed peer %s from %s", public_key[:8] + "…", interface_name)


def show_dump(interface_name: str) -> list[dict]:
    """
    Run `wg show <iface> dump` and return a list of peer dicts.

    Each dict has keys:
        public_key, preshared_key, endpoint, allowed_ips,
        latest_handshake (int unix ts, 0 = never),
        transfer_rx (bytes), transfer_tx (bytes),
        persistent_keepalive (int or None)

    The first line (interface line) is skipped.
    Returns [] if wg is not available or interface is down.
    """
    try:
        result = _run(["wg", "show", interface_name, "dump"], check=True)
    except (RuntimeError, FileNotFoundError):
        logger.warning("wg_sync: show dump failed for %s", interface_name)
        return []

    peers = []
    lines = result.stdout.strip().splitlines()
    for line in lines[1:]:  # skip interface header line
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        pub, psk, endpoint, aips, last_hs, rx, tx, ka = parts[:8]
        peers.append(
            {
                "public_key": pub,
                "preshared_key": psk if psk != "(none)" else None,
                "endpoint": endpoint if endpoint != "(none)" else None,
                "allowed_ips": aips,
                "latest_handshake": int(last_hs),
                "transfer_rx": int(rx),
                "transfer_tx": int(tx),
                "persistent_keepalive": int(ka) if ka not in ("off", "0") else None,
            }
        )
    return peers


def show_interface(interface_name: str) -> dict | None:
    """
    Run `wg show <iface> dump` and return the interface line as a dict
    with keys: public_key, listen_port, fwmark.
    Returns None if unavailable.
    """
    try:
        result = _run(["wg", "show", interface_name, "dump"], check=True)
    except (RuntimeError, FileNotFoundError):
        return None
    lines = result.stdout.strip().splitlines()
    if not lines:
        return None
    parts = lines[0].split("\t")
    if len(parts) < 4:
        return None
    priv, pub, port, fwmark = parts[:4]
    return {
        "public_key": pub,
        "listen_port": int(port) if port.isdigit() else None,
        "fwmark": fwmark,
    }


def systemctl_status(interface_name: str) -> str | None:
    """
    Try to get systemctl status for wg-quick@<iface>.
    Returns the output text or None if unavailable (e.g. inside container
    without D-Bus access).
    """
    try:
        result = subprocess.run(
            ["systemctl", "status", f"wg-quick@{interface_name}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout + result.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
        return None
