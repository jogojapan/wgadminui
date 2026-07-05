from django.apps import AppConfig
from django.utils import translation


class AccountsConfig(AppConfig):
    name = "accounts"

    def ready(self):
        # Connect signal to sync user language on login
        from allauth.account.signals import user_logged_in

        user_logged_in.connect(self._sync_language_on_login)

    @staticmethod
    def _sync_language_on_login(sender, request, user, **kwargs):
        """Copy the user's preferred language into the session on login."""
        if user.language:
            translation.activate(user.language)
