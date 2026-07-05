import ipaddress
import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class WireguardInterface(models.Model):
    """
    Represents a WireGuard interface on the host (e.g. wg0).
    Initially a single interface is expected; the model is designed to
    support multiple interfaces in future.
    """

    name = models.CharField(
        max_length=15,
        unique=True,
        help_text=_("Interface name, e.g. wg0"),
    )
    listen_port = models.PositiveIntegerField(default=51820)
    # Subnet from which peer IPs are allocated, e.g. "10.0.0.0/24"
    subnet = models.CharField(
        max_length=43,
        help_text=_("Subnet for peer IP allocation, e.g. 10.0.0.0/24"),
    )
    # Server-side public key (read from the conf file on first sync)
    server_public_key = models.CharField(max_length=44, blank=True)
    # Server endpoint that clients will connect to
    server_endpoint_host = models.CharField(
        max_length=253,
        help_text=_("Public IP or hostname clients use to reach this server"),
    )
    conf_file_path = models.CharField(
        max_length=255,
        help_text=_("Absolute path to the .conf file, e.g. /etc/wireguard/wg0.conf"),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _("WireGuard interface")
        verbose_name_plural = _("WireGuard interfaces")


class UserInterfaceAccess(models.Model):
    """
    Controls which users may create peers on which interface.
    Admin users can create on all interfaces regardless of this table.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="interface_access",
    )
    interface = models.ForeignKey(
        WireguardInterface,
        on_delete=models.CASCADE,
        related_name="user_access",
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_access",
    )

    class Meta:
        unique_together = ("user", "interface")
        verbose_name = _("user interface access")
        verbose_name_plural = _("user interface accesses")

    def __str__(self):
        return f"{self.user} → {self.interface}"


class PeerConfig(models.Model):
    """
    Represents a WireGuard peer / client configuration.

    SECURITY NOTE: The private key is NEVER stored here.
    It is generated, used to build the client .conf text + QR code,
    shown to the user exactly once, then discarded.
    Only the public key is persisted.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="peer_configs",
    )
    interface = models.ForeignKey(
        WireguardInterface,
        on_delete=models.CASCADE,
        related_name="peers",
    )
    name = models.CharField(
        max_length=100,
        help_text=_("Friendly name for this client device"),
    )
    peer_public_key = models.CharField(
        max_length=44,
        unique=True,
        help_text=_("WireGuard public key for this peer"),
    )
    # Allocated peer IP with prefix, e.g. "10.0.0.2/32"
    allowed_ips = models.CharField(
        max_length=43,
        help_text=_("IP/CIDR assigned to this peer, e.g. 10.0.0.2/32"),
    )
    # Optional DNS servers to include in the client config
    dns = models.CharField(
        max_length=255,
        blank=True,
        default="1.1.1.1,1.0.0.1",
        help_text=_("Comma-separated DNS servers for the client config"),
    )
    # Flag: set to True after the setup page has been acknowledged
    setup_acknowledged = models.BooleanField(
        default=False,
        help_text=_("User has confirmed they saved the private key / QR code"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("peer configuration")
        verbose_name_plural = _("peer configurations")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.owner.email})"

    @property
    def peer_ip(self):
        """Return just the IP address without prefix length."""
        return self.allowed_ips.split("/")[0]

    @property
    def ip_address(self):
        return ipaddress.ip_interface(self.allowed_ips).ip
