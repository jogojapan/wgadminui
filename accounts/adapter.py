"""
accounts/adapter.py — Language-aware allauth adapter.

Extends django-invitations' BaseInvitationsAdapter to send emails in the
recipient's preferred language.
"""

from allauth.account.signals import user_signed_up
from django.conf import settings
from django.utils import translation

from invitations.adapters import BaseInvitationsAdapter
from allauth.account.adapter import DefaultAccountAdapter

class LanguageAwareInvitationsAdapter(BaseInvitationsAdapter, DefaultAccountAdapter):
    """
    Custom adapter that activates the user's preferred language before
    sending emails, so invitation and verification emails are sent in
    the correct language.
    """

    def __init__(self, request=None):
        self.request = request

    def get_user_signed_up_signal(self):
        """Required by django-invitations views."""
        return user_signed_up

    def send_mail(self, template_prefix, email, context):
        """
        Override send_mail to activate the recipient's language before
        rendering the email template.

        The language can be provided via context (for invitations where
        the user doesn't exist yet) or looked up from the user record
        (for existing users).
        """
        language = context.get("language")

        # If no language in context, try to look it up from the user
        if not language:
            from accounts.models import User
            try:
                user = User.objects.get(email=email)
                language = user.language
            except User.DoesNotExist:
                language = settings.LANGUAGE_CODE

        with translation.override(language):
            return super().send_mail(template_prefix, email, context)