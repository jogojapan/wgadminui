"""
Management command: create_initial_admin

Creates the first superuser/admin account from environment variables.
Reads WGADMINUI_ADMIN_EMAIL and WGADMINUI_ADMIN_PASSWORD.
Idempotent: does nothing if an admin already exists with that email.
"""

from decouple import config
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create initial admin user from WGADMINUI_ADMIN_EMAIL / WGADMINUI_ADMIN_PASSWORD env vars"

    def handle(self, *args, **options):
        User = get_user_model()

        email = config("WGADMINUI_ADMIN_EMAIL", default="")
        password = config("WGADMINUI_ADMIN_PASSWORD", default="")

        if not email or not password:
            raise CommandError(
                "WGADMINUI_ADMIN_EMAIL and WGADMINUI_ADMIN_PASSWORD must be set."
            )

        if User.objects.filter(email=email).exists():
            self.stdout.write(
                self.style.WARNING(f"Admin user '{email}' already exists — skipping.")
            )
            return

        # Derive username from email local-part, truncated to 150 chars
        username = email.split("@")[0][:150]
        # Ensure username uniqueness
        if User.objects.filter(username=username).exists():
            username = email[:150]

        user = User.objects.create_superuser(
            email=email,
            username=username,
            password=password,
        )
        user.role = User.Role.ADMIN
        user.save(update_fields=["role"])

        self.stdout.write(
            self.style.SUCCESS(f"Admin user '{email}' created successfully.")
        )
