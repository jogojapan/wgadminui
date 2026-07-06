"""
dashboard/views.py — All UI views for wgadminui.

Access control:
  - All views require login (@login_required / LoginRequiredMixin).
  - AdminRequiredMixin additionally requires is_admin_user.
"""

import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils import translation
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from invitations.utils import get_invitation_model

from wireguard import services as wg_services
from wireguard.models import PeerConfig, WireguardInterface

from .forms import PeerCreateForm

User = get_user_model()
Invitation = get_invitation_model()


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------


class AdminRequiredMixin(LoginRequiredMixin):
    """Restrict a view to admin users (role=ADMIN or superuser)."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_admin_user:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Language switching
# ---------------------------------------------------------------------------


class LanguageSetView(LoginRequiredMixin, View):
    """POST-only view that persists the user's language choice."""

    def post(self, request):
        language = request.POST.get("language")
        valid_langs = dict(settings.LANGUAGES)
        if language in valid_langs:
            request.user.language = language
            request.user.save(update_fields=["language"])
            translation.activate(language)
        # Redirect back to the referring page, or dashboard as fallback
        next_url = request.META.get("HTTP_REFERER", "/")
        return redirect(next_url)


def _get_default_interface():
    """Return the first WireguardInterface, or None."""
    return WireguardInterface.objects.first()


# ---------------------------------------------------------------------------
# Dashboard (home)
# ---------------------------------------------------------------------------


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        interface = _get_default_interface()
        ctx["interface"] = interface

        if interface:
            if self.request.user.is_admin_user:
                peers = PeerConfig.objects.filter(interface=interface).select_related("owner")
            else:
                peers = PeerConfig.objects.filter(
                    interface=interface, owner=self.request.user
                )
            # Attach live status
            status_map = wg_services.get_peer_status(interface)
            for peer in peers:
                peer.live_status = status_map.get(peer.peer_public_key)
            ctx["peers"] = peers
            ctx["interface_info"] = wg_services.get_interface_info(interface)
        else:
            ctx["peers"] = []
            ctx["interface_info"] = None

        return ctx


# ---------------------------------------------------------------------------
# Peer create
# ---------------------------------------------------------------------------


class PeerCreateView(LoginRequiredMixin, View):
    template_name = "dashboard/peer_create.html"

    def get_interface(self):
        interface = _get_default_interface()
        if interface is None:
            raise Http404(_("No WireGuard interface configured."))
        return interface

    def get(self, request):
        form = PeerCreateForm()
        return render(request, self.template_name, {"form": form, "interface": self.get_interface()})

    def post(self, request):
        form = PeerCreateForm(request.POST)
        interface = self.get_interface()
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "interface": interface})

        try:
            peer, private_key, conf_text = wg_services.create_peer(
                interface=interface,
                owner=request.user,
                name=form.cleaned_data["name"],
                dns=form.cleaned_data.get("dns") or "1.1.1.1,1.0.0.1",
                manual_ip=form.cleaned_data.get("manual_ip") or None,
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, {"form": form, "interface": interface})
        except Exception as exc:
            messages.error(request, _("Failed to create peer: %s") % exc)
            return render(request, self.template_name, {"form": form, "interface": interface})

        # Store conf_text + private_key in session for the one-time setup page
        request.session["peer_setup"] = {
            "peer_id": str(peer.id),
            "conf_text": conf_text,
            "private_key": private_key,
            "qr_data_uri": wg_services.conf_to_qr_data_uri(conf_text),
        }
        return redirect("peer_setup", pk=peer.id)


# ---------------------------------------------------------------------------
# Peer setup (show-once page)
# ---------------------------------------------------------------------------


class PeerSetupView(LoginRequiredMixin, View):
    template_name = "dashboard/peer_setup.html"

    def _get_peer(self, request, pk):
        peer = get_object_or_404(PeerConfig, pk=pk)
        if peer.owner != request.user and not request.user.is_admin_user:
            raise PermissionDenied
        return peer

    def get(self, request, pk):
        peer = self._get_peer(request, pk)
        setup_data = request.session.get("peer_setup", {})
        if setup_data.get("peer_id") != str(peer.id):
            # Session expired or wrong peer — key is gone
            messages.warning(
                request,
                _("The private key for this configuration is no longer available. "
                  "You can regenerate the keypair to get a new one."),
            )
            return redirect("peer_detail", pk=peer.id)
        return render(request, self.template_name, {"peer": peer, "setup": setup_data})

    def post(self, request, pk):
        """User clicked 'I have saved my config' — mark acknowledged."""
        peer = self._get_peer(request, pk)
        peer.setup_acknowledged = True
        peer.save(update_fields=["setup_acknowledged"])
        # Clear session data
        request.session.pop("peer_setup", None)
        messages.success(request, _("Configuration for '%s' is ready.") % peer.name)
        return redirect("peer_detail", pk=peer.id)


# ---------------------------------------------------------------------------
# Peer detail
# ---------------------------------------------------------------------------


class PeerDetailView(LoginRequiredMixin, View):
    template_name = "dashboard/peer_detail.html"

    def _get_peer(self, request, pk):
        peer = get_object_or_404(PeerConfig, pk=pk)
        if peer.owner != request.user and not request.user.is_admin_user:
            raise PermissionDenied
        return peer

    def get(self, request, pk):
        peer = self._get_peer(request, pk)
        status_map = wg_services.get_peer_status(peer.interface)
        live_status = status_map.get(peer.peer_public_key)
        return render(request, self.template_name, {"peer": peer, "live_status": live_status})


# ---------------------------------------------------------------------------
# Peer QR (HTMX endpoint — returns <img> fragment)
# ---------------------------------------------------------------------------


@login_required
def peer_qr_view(request, pk):
    """
    Returns an HTML fragment (for HTMX) containing the QR code image.
    Only accessible for the owner or an admin.
    """
    peer = get_object_or_404(PeerConfig, pk=pk)
    if peer.owner != request.user and not request.user.is_admin_user:
        raise PermissionDenied

    # QR code requires the conf text which includes the private key.
    # Since we don't store the private key, this endpoint only works
    # while the setup session is active (first-time display).
    setup_data = request.session.get("peer_setup", {})
    if setup_data.get("peer_id") == str(peer.id):
        qr_data_uri = setup_data["qr_data_uri"]
    else:
        return HttpResponse(
            _('<p class="text-muted small">QR code unavailable — private key no longer stored. '
              'Use "Regenerate keypair" to create a new one.</p>')
        )

    return render(request, "dashboard/partials/qr_fragment.html", {"qr_data_uri": qr_data_uri, "peer": peer})


# ---------------------------------------------------------------------------
# Peer regenerate keypair
# ---------------------------------------------------------------------------


class PeerRegenerateView(LoginRequiredMixin, View):
    template_name = "dashboard/peer_regenerate_confirm.html"

    def _get_peer(self, request, pk):
        peer = get_object_or_404(PeerConfig, pk=pk)
        if peer.owner != request.user and not request.user.is_admin_user:
            raise PermissionDenied
        return peer

    def get(self, request, pk):
        peer = self._get_peer(request, pk)
        return render(request, self.template_name, {"peer": peer})

    def post(self, request, pk):
        peer = self._get_peer(request, pk)
        try:
            private_key, conf_text = wg_services.regenerate_peer_keypair(peer)
        except Exception as exc:
            messages.error(request, _("Failed to regenerate keypair: %s") % exc)
            return redirect("peer_detail", pk=peer.id)

        request.session["peer_setup"] = {
            "peer_id": str(peer.id),
            "conf_text": conf_text,
            "private_key": private_key,
            "qr_data_uri": wg_services.conf_to_qr_data_uri(conf_text),
        }
        return redirect("peer_setup", pk=peer.id)


# ---------------------------------------------------------------------------
# Peer delete
# ---------------------------------------------------------------------------


class PeerDeleteView(LoginRequiredMixin, View):
    template_name = "dashboard/peer_delete_confirm.html"

    def _get_peer(self, request, pk):
        peer = get_object_or_404(PeerConfig, pk=pk)
        if peer.owner != request.user and not request.user.is_admin_user:
            raise PermissionDenied
        return peer

    def get(self, request, pk):
        peer = self._get_peer(request, pk)
        return render(request, self.template_name, {"peer": peer})

    def post(self, request, pk):
        peer = self._get_peer(request, pk)
        name = peer.name
        try:
            wg_services.delete_peer(peer)
            messages.success(request, _("Peer '%s' deleted.") % name)
        except Exception as exc:
            messages.error(request, _("Error deleting peer: %s") % exc)
        return redirect("dashboard")


# ---------------------------------------------------------------------------
# Admin: user list + invite
# ---------------------------------------------------------------------------


class AdminUsersView(AdminRequiredMixin, View):
    template_name = "dashboard/admin_users.html"

    def get(self, request):
        users = User.objects.all().order_by("email")
        pending = Invitation.objects.filter(accepted=False).order_by("-sent")
        return render(request, self.template_name, {"users": users, "pending_invitations": pending})

    def post(self, request):
        email = request.POST.get("email", "").strip().lower()
        language = request.POST.get("language", settings.LANGUAGE_CODE)
        if not email:
            messages.error(request, _("Please provide an email address."))
            return redirect("admin_users")
        if User.objects.filter(email=email).exists():
            messages.warning(request, _("%s is already a registered user.") % email)
            return redirect("admin_users")
        if Invitation.objects.filter(email=email, accepted=False).exists():
            messages.warning(request, _("An invitation is already pending for %s.") % email)
            return redirect("admin_users")
        invite = Invitation.create(email=email, inviter=request.user)
        invite.send_invitation(request, extra_context={"language": language})
        messages.success(request, _("Invitation sent to %s.") % email)
        return redirect("admin_users")


# ---------------------------------------------------------------------------
# Admin: interface status
# ---------------------------------------------------------------------------


class InterfaceStatusView(AdminRequiredMixin, TemplateView):
    template_name = "dashboard/interface_status.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        interface = _get_default_interface()
        ctx["interface"] = interface

        if interface:
            ctx["interface_info"] = wg_services.get_interface_info(interface)
            status_map = wg_services.get_peer_status(interface)
            peers = PeerConfig.objects.filter(interface=interface).select_related("owner")
            annotated = []
            now = datetime.datetime.now(tz=datetime.timezone.utc)
            for peer in peers:
                live = status_map.get(peer.peer_public_key)
                if live and live["last_handshake"]:
                    last_seen = datetime.datetime.fromtimestamp(
                        live["last_handshake"], tz=datetime.timezone.utc
                    )
                    live["last_seen_dt"] = last_seen
                    live["last_seen_delta"] = now - last_seen
                annotated.append((peer, live))
            ctx["annotated_peers"] = annotated
        else:
            ctx["interface_info"] = None
            ctx["annotated_peers"] = []

        return ctx
