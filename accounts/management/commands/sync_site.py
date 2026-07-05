"""
Management command: sync_site

Updates the django.contrib.sites Site object (id=1) with the domain and
name from WGADMINUI_DOMAIN / WGADMINUI_SITE_NAME environment variables.

This ensures that django-allauth generates correct URLs in email
verification, password reset, and other emails.
"""

from decouple import config
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Sync Site (id=1) domain/name from WGADMINUI_DOMAIN / WGADMINUI_SITE_NAME env vars"

    def handle(self, *args, **options):
        domain = config("WGADMINUI_DOMAIN", default="")
        name = config("WGADMINUI_SITE_NAME", default="wgadminui")

        if not domain:
            self.stdout.write(
                self.style.WARNING(
                    "WGADMINUI_DOMAIN not set — skipping site sync. "
                    "Email links may use the default 'example.com' domain."
                )
            )
            return

        site, created = Site.objects.get_or_create(
            pk=1,
            defaults={"domain": domain, "name": name},
        )

        updated = False
        if site.domain != domain:
            site.domain = domain
            updated = True
        if site.name != name:
            site.name = name
            updated = True

        if updated:
            site.save(update_fields=["domain", "name"])
            self.stdout.write(
                self.style.SUCCESS(
                    f"Site updated: domain='{domain}', name='{name}'"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Site already up to date: domain='{domain}', name='{name}'"
                )
            )