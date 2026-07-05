"""
Django settings for wgadminui.

All user-configurable values are read from environment variables prefixed
with WGADMINUI_ via python-decouple.  A .env file in the project root can
be used for local development.
"""

from pathlib import Path

from decouple import Csv, config

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

# SQLite database stored in /app/data inside the container (mounted volume)
DATA_DIR = Path(config("WGADMINUI_DATA_DIR", default=str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Core Django
# ---------------------------------------------------------------------------

SECRET_KEY = config("WGADMINUI_SECRET_KEY", default="django-insecure-change-me-in-production")
DEBUG = config("WGADMINUI_DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("WGADMINUI_ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# When running behind Traefik (which terminates TLS) Django needs to trust
# the X-Forwarded-Proto header to know the request came in over HTTPS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ---------------------------------------------------------------------------
# Application definition
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    # Django built-ins
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.sites",
    # Third-party
    "allauth",
    "allauth.account",
    "allauth.mfa",
    "allauth.mfa.webauthn",
    "invitations",
    # Local apps
    "accounts",
    "wireguard",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "wgadminui.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "wgadminui.wsgi.application"

# ---------------------------------------------------------------------------
# Database — SQLite stored in the DATA_DIR volume mount
# ---------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "allauth.account.auth_backends.AuthenticationBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# django-allauth
# ---------------------------------------------------------------------------

# allauth 65.x settings
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_USER_MODEL_USERNAME_FIELD = "username"
ACCOUNT_LOGIN_BY_CODE_ENABLED = False
# Use the invitations adapter so django-invitations can hook into allauth signals
ACCOUNT_ADAPTER = "invitations.models.InvitationsAdapter"

# Passkeys / WebAuthn
MFA_SUPPORTED_TYPES = ["totp", "webauthn", "recovery_codes"]
MFA_PASSKEY_LOGIN_ENABLED = True
MFA_WEBAUTHN_ALLOW_INSECURE_ORIGIN = config(
    "WGADMINUI_WEBAUTHN_ALLOW_INSECURE_ORIGIN", default=False, cast=bool
)

LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

SITE_ID = 1

# ---------------------------------------------------------------------------
# django-invitations
# ---------------------------------------------------------------------------

INVITATIONS_INVITATION_ONLY = True
INVITATIONS_ACCEPT_INVITE_AFTER_SIGNUP = True
INVITATIONS_EMAIL_SUBJECT_PREFIX = "[wgadminui] "

# ---------------------------------------------------------------------------
# Email / SMTP
# ---------------------------------------------------------------------------

EMAIL_BACKEND = config(
    "WGADMINUI_EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = config("WGADMINUI_EMAIL_HOST", default="localhost")
EMAIL_PORT = config("WGADMINUI_EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("WGADMINUI_EMAIL_USER", default="")
EMAIL_HOST_PASSWORD = config("WGADMINUI_EMAIL_PASSWORD", default="")
EMAIL_USE_TLS = config("WGADMINUI_EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_USE_SSL = config("WGADMINUI_EMAIL_USE_SSL", default=False, cast=bool)
DEFAULT_FROM_EMAIL = config("WGADMINUI_DEFAULT_FROM_EMAIL", default="noreply@example.com")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# ---------------------------------------------------------------------------
# WireGuard
# ---------------------------------------------------------------------------

WGADMINUI_WG_INTERFACE = config("WGADMINUI_WG_INTERFACE", default="wg0")
WGADMINUI_WG_CONF_DIR = config("WGADMINUI_WG_CONF_DIR", default="/etc/wireguard")
WGADMINUI_WG_SERVER_PUBLIC_IP = config("WGADMINUI_WG_SERVER_PUBLIC_IP", default="")
WGADMINUI_WG_SERVER_PORT = config("WGADMINUI_WG_SERVER_PORT", default=51820, cast=int)

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
}

# ---------------------------------------------------------------------------
# Security (active when not DEBUG)
# ---------------------------------------------------------------------------

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = config("WGADMINUI_TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": config("WGADMINUI_LOG_LEVEL", default="INFO"),
    },
    "loggers": {
        "wireguard": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}
