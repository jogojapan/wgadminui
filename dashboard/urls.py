from django.urls import path

from . import views

urlpatterns = [
    # Dashboard home
    path("", views.DashboardView.as_view(), name="dashboard"),

    # Peer management
    path("peers/new/", views.PeerCreateView.as_view(), name="peer_create"),
    path("peers/<uuid:pk>/", views.PeerDetailView.as_view(), name="peer_detail"),
    path("peers/<uuid:pk>/setup/", views.PeerSetupView.as_view(), name="peer_setup"),
    path("peers/<uuid:pk>/qr/", views.peer_qr_view, name="peer_qr"),
    path("peers/<uuid:pk>/regenerate/", views.PeerRegenerateView.as_view(), name="peer_regenerate"),
    path("peers/<uuid:pk>/delete/", views.PeerDeleteView.as_view(), name="peer_delete"),

    # Admin views
    path("admin-panel/users/", views.AdminUsersView.as_view(), name="admin_users"),
    path("admin-panel/status/", views.InterfaceStatusView.as_view(), name="interface_status"),
]
