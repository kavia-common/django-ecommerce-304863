"""Production Django settings.

This module intentionally imports defaults from `base.py` and then overrides them
for a public internet deployment. It is designed to be *fail-safe*:
misconfiguration should raise an error early rather than running insecurely.
"""

from django.core.exceptions import ImproperlyConfigured
from decouple import config

from .base import *  # noqa: F403,F401  (importing base settings intentionally)


def _require_env(name: str) -> str:
    """Return env var value or raise ImproperlyConfigured if missing/blank."""
    value = config(name, default=None)
    if value is None or str(value).strip() == "":
        raise ImproperlyConfigured(
            f"{name} must be set in the environment when using production settings."
        )
    return str(value).strip()


def _env_bool(name: str, *, default=None):
    """Parse a boolean env var via python-decouple.

    If default is None and the variable is missing, returns None so caller can
    enforce explicit configuration.
    """
    if default is None:
        raw = config(name, default=None)
        if raw is None:
            return None
    return config(name, cast=bool, default=default)


# -----------------------------------------------------------------------------
# Core safety: DEBUG/SECRET_KEY/ALLOWED_HOSTS
# -----------------------------------------------------------------------------
# Fail fast if DEBUG isn't explicitly set to False in the environment.
# This prevents accidental deployments with DEBUG=True due to env mistakes.
DEBUG = _env_bool("DEBUG", default=None)
if DEBUG is not False:
    raise ImproperlyConfigured(
        "In production settings, DEBUG must be explicitly set to 'False' in the environment."
    )

# Require SECRET_KEY from environment; no fallbacks in production.
# base.py provides a dev fallback, but production MUST override it.
SECRET_KEY = _require_env("SECRET_KEY")  # noqa: F405

# Require non-empty ALLOWED_HOSTS from environment (comma-separated).
# Example: ALLOWED_HOSTS="example.com,www.example.com"
_allowed_hosts_raw = _require_env("ALLOWED_HOSTS")
_allowed_hosts = [h.strip() for h in _allowed_hosts_raw.split(",") if h.strip()]
# Common placeholders we treat as misconfiguration.
_placeholders = {"ip-address", "www.your-website.com", "yourdomain.com", "example.com"}
if not _allowed_hosts or any(h in _placeholders for h in _allowed_hosts):
    raise ImproperlyConfigured(
        "ALLOWED_HOSTS must be set to your real domain(s) (comma-separated) when using production settings."
    )
ALLOWED_HOSTS = _allowed_hosts  # noqa: F405

# -----------------------------------------------------------------------------
# Authentication hardening (keep behavior unchanged unless configured)
# -----------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [  # noqa: F405
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# django-allauth note:
# In real production, consider setting:
#   ACCOUNT_EMAIL_VERIFICATION = "mandatory"
# to reduce account takeover risks and improve deliverability hygiene.
# We keep current behavior (base.py sets "optional") unless the operator overrides it.

# -----------------------------------------------------------------------------
# Cookies / session / CSRF
# -----------------------------------------------------------------------------
# Only send cookies over HTTPS.
SESSION_COOKIE_SECURE = True  # noqa: F405
CSRF_COOKIE_SECURE = True  # noqa: F405

# Prevent JavaScript access to session cookies; reduces XSS impact.
SESSION_COOKIE_HTTPONLY = True  # noqa: F405

# CSRF cookie must typically be readable by JS only if you implement SPA-style
# CSRF token extraction. This project is server-rendered, but we set explicitly
# for clarity.
CSRF_COOKIE_HTTPONLY = False  # noqa: F405

# SameSite reduces CSRF risk. Lax is generally safe for classic web apps.
# Tradeoff note: Some third-party auth flows (including certain allauth/social)
# can require SameSite=None; Secure for cross-site POST callbacks.
SESSION_COOKIE_SAMESITE = "Lax"  # noqa: F405
CSRF_COOKIE_SAMESITE = "Lax"  # noqa: F405

# -----------------------------------------------------------------------------
# HTTPS & security headers
# -----------------------------------------------------------------------------
# Redirect all HTTP requests to HTTPS.
# If you run in a local staging environment without TLS termination, you can
# temporarily disable by setting SECURE_SSL_REDIRECT=False in env.
SECURE_SSL_REDIRECT = _env_bool("SECURE_SSL_REDIRECT", default=True)  # noqa: F405

# When behind a reverse proxy / load balancer that terminates TLS, Django must
# trust the forwarded proto header to correctly determine request.is_secure().
# Ensure your proxy sets X-Forwarded-Proto: https.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # noqa: F405

# Enable HSTS (HTTP Strict Transport Security).
# WARNING: Once browsers cache HSTS for your domain, they will require HTTPS.
SECURE_HSTS_SECONDS = 31536000  # 1 year  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = True  # noqa: F405
SECURE_HSTS_PRELOAD = True  # noqa: F405

# Misc security headers.
SECURE_CONTENT_TYPE_NOSNIFF = True  # noqa: F405
SECURE_REFERRER_POLICY = "same-origin"  # noqa: F405
X_FRAME_OPTIONS = "DENY"  # Clickjacking protection  # noqa: F405

# -----------------------------------------------------------------------------
# Database (kept as-is but env-driven)
# -----------------------------------------------------------------------------
DATABASES = {  # noqa: F405
    "default": {
        "ENGINE": "django.db.backends.postgresql_psycopg2",
        "NAME": _require_env("DB_NAME"),
        "USER": _require_env("DB_USER"),
        "PASSWORD": _require_env("DB_PASSWORD"),
        "HOST": _require_env("DB_HOST"),
        "PORT": config("DB_PORT", default=""),
    }
}

# -----------------------------------------------------------------------------
# Stripe (live keys from env only; no defaults)
# -----------------------------------------------------------------------------
STRIPE_PUBLIC_KEY = _require_env("STRIPE_LIVE_PUBLIC_KEY")  # noqa: F405
STRIPE_SECRET_KEY = _require_env("STRIPE_LIVE_SECRET_KEY")  # noqa: F405

# -----------------------------------------------------------------------------
# Logging (production-safe defaults)
# -----------------------------------------------------------------------------
# Goal: capture warnings+ for troubleshooting without dumping secrets.
# This config logs to stdout/stderr which works well in container platforms.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        # Only show DEBUG logs when DEBUG=True (which should never happen here).
        "require_debug_false": {"()": "django.utils.log.RequireDebugFalse"},
    },
    "formatters": {
        "simple": {
            "format": "[{levelname}] {asctime} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
            "filters": ["require_debug_false"],
        }
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        # Django request errors
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        # Security-related issues
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
