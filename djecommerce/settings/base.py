import importlib.util
import json
import logging
import os
from importlib import metadata

from decouple import config

from .env import env_bool, env_list, env_str, validate_settings

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Environment
# ENVIRONMENT is used to gate production hardening behavior.
# Supported values: local | development | production (others treated as non-local).
ENVIRONMENT = env_str("ENVIRONMENT", default="local")

# DEBUG defaults to False (safer), but development.py still explicitly sets DEBUG=True.
DEBUG = env_bool("DEBUG", default=False)

# SECRET_KEY
# In production this is required (validated below).
# In local/dev we keep a safe placeholder default to avoid breaking quick starts.
SECRET_KEY = env_str("SECRET_KEY", default="insecure-local-secret-key-change-me")

# Hosts
# ALLOWED_HOSTS can be a JSON list or comma-separated.
# In local/dev we default to localhost.
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])

# Allow safe preview host patterns (optional).
# Example: PREVIEW_ALLOWED_HOST_SUFFIXES=.kavia.app,.vercel.app
# This will match any subdomain ending with the suffix (leading dot is normalized).
preview_suffixes = env_list("PREVIEW_ALLOWED_HOST_SUFFIXES", default=[])
for sfx in preview_suffixes:
    sfx = sfx.strip()
    if not sfx:
        continue
    if not sfx.startswith("."):
        sfx = f".{sfx}"
    if sfx not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(sfx)

# Payments
# PAYMENT_MODE:
#   - 'dummy' (default) or 'stripe'
# Stripe keys are optional unless PAYMENT_MODE=stripe (enforced in production validation).
PAYMENT_MODE = (env_str("PAYMENT_MODE", default="dummy") or "dummy").strip().lower()
PAYMENT_DUMMY_OUTCOME = config(
    "PAYMENT_DUMMY_OUTCOME", default="success"
)  # success|fail|random
PAYMENT_DUMMY_FAIL_RATE = float(
    config("PAYMENT_DUMMY_FAIL_RATE", default="0.0")
)  # used when outcome=random

# Stripe keys are read here; production enforcement happens in validate_settings() when mode=stripe.
STRIPE_SECRET_KEY = env_str("STRIPE_SECRET_KEY", default="")
STRIPE_PUBLIC_KEY = env_str("STRIPE_PUBLIC_KEY", default="")

# Validate key configuration (fail-fast)
validate_settings(
    debug=DEBUG,
    environment=ENVIRONMENT,
    allowed_hosts=ALLOWED_HOSTS,
    payment_mode=PAYMENT_MODE,
)


def _get_crispy_template_pack() -> str:
    """
    Determine a crispy template pack that will not crash startup.

    - django-crispy-forms>=2.x requires an external template pack such as
      crispy-bootstrap4; if it's missing, using "bootstrap4" will typically fail
      at render time. We fall back to "bootstrap3" as a safe default.
    - django-crispy-forms<2.x historically shipped template packs internally,
      including "bootstrap4".
    """
    try:
        crispy_version = metadata.version("django-crispy-forms")
        major = int(crispy_version.split(".", 1)[0])
    except Exception:
        major = 1

    has_bootstrap4_pack = importlib.util.find_spec("crispy_bootstrap4") is not None
    if major >= 2 and not has_bootstrap4_pack:
        return "bootstrap3"
    return "bootstrap4"


CRISPY_TEMPLATE_PACK = _get_crispy_template_pack()

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "crispy_forms",
    "django_countries",
    # DRF (API layer; does not affect template rendering)
    "rest_framework",
    "django_filters",
    "core",
]

# If the bootstrap4 template pack is available, enable it.
if (
    CRISPY_TEMPLATE_PACK == "bootstrap4"
    and importlib.util.find_spec("crispy_bootstrap4") is not None
):
    INSTALLED_APPS.append("crispy_bootstrap4")

# Optional CORS support (only enabled if CORS_ALLOWED_ORIGINS is set).
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ENABLED = bool(CORS_ALLOWED_ORIGINS)

if CORS_ENABLED:
    INSTALLED_APPS = ["corsheaders"] + INSTALLED_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
]

if CORS_ENABLED:
    # Must be as high as possible per django-cors-headers docs.
    MIDDLEWARE += ["corsheaders.middleware.CorsMiddleware"]

MIDDLEWARE += [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Required by django-allauth>=0.60
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "djecommerce.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "djecommerce.wsgi.application"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Default primary key field type
# Keep AutoField to match existing migrations and avoid warnings on Django 4.x.
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
MEDIA_URL = "/media/"
STATICFILES_DIRS = [os.path.join(BASE_DIR, "static_in_env")]
STATIC_ROOT = os.path.join(BASE_DIR, "static_root")
MEDIA_ROOT = os.path.join(BASE_DIR, "media_root")

# Auth
AUTHENTICATION_BACKENDS = (
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
)
SITE_ID = 1
LOGIN_REDIRECT_URL = "/"

# Django REST Framework (DRF)
# - JWTAuthentication is used for API clients.
# - SessionAuthentication keeps existing browser-based sessions (django-allauth) working.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
}

# CSRF/CORS (optional)
# Values should be full origins (scheme+host), e.g. https://example.com
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", default=[])

# Secure defaults
# Secure-by-default in production; configurable via env vars.
_secure_defaults = (ENVIRONMENT or "").strip().lower() == "production"

SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", default=_secure_defaults)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", default=_secure_defaults)

# Harden cookie behavior in production; allow overrides if needed.
SESSION_COOKIE_HTTPONLY = env_bool("SESSION_COOKIE_HTTPONLY", default=True)
CSRF_COOKIE_HTTPONLY = env_bool(
    "CSRF_COOKIE_HTTPONLY", default=False
)  # Django default is False
SESSION_COOKIE_SAMESITE = env_str("SESSION_COOKIE_SAMESITE", default="Lax")
CSRF_COOKIE_SAMESITE = env_str("CSRF_COOKIE_SAMESITE", default="Lax")

SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", default=_secure_defaults)

# HSTS
SECURE_HSTS_SECONDS = int(
    env_str("SECURE_HSTS_SECONDS", default=str(31536000 if _secure_defaults else 0))
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=_secure_defaults
)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", default=_secure_defaults)

# Additional security headers
SECURE_CONTENT_TYPE_NOSNIFF = env_bool(
    "SECURE_CONTENT_TYPE_NOSNIFF", default=_secure_defaults
)
SECURE_REFERRER_POLICY = env_str("SECURE_REFERRER_POLICY", default="same-origin")

# Proxy SSL header (common with gunicorn behind reverse proxy/load balancer)
# Leave opt-in to avoid surprises for local dev.
if env_bool("USE_X_FORWARDED_PROTO", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# CRISPY FORMS
# NOTE: CRISPY_TEMPLATE_PACK is computed above in a startup-safe way.
CRISPY_ALLOWED_TEMPLATE_PACKS = (
    CRISPY_TEMPLATE_PACK,
    "bootstrap3",
    "bootstrap4",
    "uni_form",
)

# Logging (gunicorn-friendly)
# LOG_FORMAT: text | json
LOG_LEVEL = env_str("LOG_LEVEL", default="INFO").upper()
LOG_FORMAT = env_str("LOG_FORMAT", default="text").lower()


class _JsonFormatter(logging.Formatter):
    """Minimal JSON formatter to avoid external dependencies."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "text": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
        "json": {
            "()": _JsonFormatter,
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json" if LOG_FORMAT == "json" else "text",
            "level": LOG_LEVEL,
        }
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        # Reduce noisy loggers
        "django.server": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        # Log DRF/auth issues at warning+
        "rest_framework": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "rest_framework.authentication": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "rest_framework.permissions": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}
