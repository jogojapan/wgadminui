"""
Template context processor that exposes site-wide configuration to all templates.
"""

from django.conf import settings


def site_info(request):
    """Add site name and domain to every template context."""
    return {
        "SITE_NAME": getattr(settings, "WGADMINUI_SITE_NAME", "wgadminui"),
        "SITE_DOMAIN": getattr(settings, "WGADMINUI_SITE_DOMAIN", ""),
    }


def user_theme(request):
    """Add the authenticated user's preferred theme to the template context.

    Falls back to 'light' for anonymous users so the <html> element always
    has a valid data-theme value.
    """
    if hasattr(request, "user") and request.user.is_authenticated:
        return {"user_theme": getattr(request.user, "theme", "light")}
    return {"user_theme": "light"}