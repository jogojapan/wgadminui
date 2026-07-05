from django.contrib import admin

from .models import PeerConfig, UserInterfaceAccess, WireguardInterface


@admin.register(WireguardInterface)
class WireguardInterfaceAdmin(admin.ModelAdmin):
    list_display = ("name", "listen_port", "subnet", "server_endpoint_host", "conf_file_path")
    search_fields = ("name",)


@admin.register(PeerConfig)
class PeerConfigAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "interface", "allowed_ips", "setup_acknowledged", "created_at", "last_sync_at")
    list_filter = ("interface", "setup_acknowledged")
    search_fields = ("name", "owner__email", "peer_public_key")
    readonly_fields = ("id", "peer_public_key", "created_at", "last_sync_at")


@admin.register(UserInterfaceAccess)
class UserInterfaceAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "interface", "granted_by", "granted_at")
    list_filter = ("interface",)
