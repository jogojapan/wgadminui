from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """
    Custom user model using email as the primary identifier.
    username field is kept for django-allauth compatibility but email is
    the USERNAME_FIELD so login is always by email.
    """

    class Role(models.TextChoices):
        ADMIN = "admin", _("Admin")
        MEMBER = "member", _("Member")

    # Override email to make it unique and required
    email = models.EmailField(_("email address"), unique=True)

    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.MEMBER,
        help_text=_("Admin users can manage all peers and invite new users."),
    )

    USERNAME_FIELD = "email"
    # username is still required by AbstractUser; we keep it but auto-populate
    REQUIRED_FIELDS = ["username"]

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def __str__(self):
        return self.email

    @property
    def is_admin_user(self):
        return self.role == self.Role.ADMIN or self.is_superuser
