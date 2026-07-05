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