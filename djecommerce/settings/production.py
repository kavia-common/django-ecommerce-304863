import os

from decouple import config

from .base import *  # noqa

# Production should use env-driven DEBUG with safe defaults.
DEBUG = env_bool("DEBUG", default=False)

# Hosts should be driven by env.
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", default=ALLOWED_HOSTS)

# Re-validate with possibly overridden production values.
validate_settings(
    debug=DEBUG,
    environment=ENVIRONMENT,
    allowed_hosts=ALLOWED_HOSTS,
    payment_mode=PAYMENT_MODE,
)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Database:
# - If DATABASE_URL is provided, use it (no new dependency); otherwise keep existing config.
# Supported minimal format:
#   postgres://USER:PASSWORD@HOST:PORT/NAME
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if DATABASE_URL:
    try:
        from urllib.parse import urlparse

        u = urlparse(DATABASE_URL)
        if u.scheme not in {"postgres", "postgresql"}:
            raise ValueError("Only postgres/postgresql URLs are supported without extra dependencies.")
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.postgresql_psycopg2",
                "NAME": (u.path or "").lstrip("/"),
                "USER": u.username or "",
                "PASSWORD": u.password or "",
                "HOST": u.hostname or "",
                "PORT": str(u.port or ""),
            }
        }
    except Exception:
        # Fail fast if misconfigured; production should not silently run with wrong DB.
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured("Invalid DATABASE_URL. Expected postgres://USER:PASSWORD@HOST:PORT/NAME")
else:
    # If explicit DB_* vars are not provided, allow non-production preview to start
    # (e.g., ephemeral environments running on sqlite). In true production, fail fast.
    if (ENVIRONMENT or "").strip().lower() == "production":
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.postgresql_psycopg2",
                "NAME": config("DB_NAME"),
                "USER": config("DB_USER"),
                "PASSWORD": config("DB_PASSWORD"),
                "HOST": config("DB_HOST"),
                "PORT": "",
            }
        }
    else:
        # Preview/local fallback: use sqlite so the app can boot without external DB env.
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": os.path.join(BASE_DIR, "db.sqlite3"),
            }
        }

# Stripe keys:
# In this codebase, Stripe keys are referenced as STRIPE_* in base.py.
# We keep backward compatibility with older STRIPE_LIVE_* env vars if present.
if PAYMENT_MODE == "stripe":
    STRIPE_PUBLIC_KEY = env_str("STRIPE_PUBLIC_KEY", default="") or env_str("STRIPE_LIVE_PUBLIC_KEY", default="")
    STRIPE_SECRET_KEY = env_str("STRIPE_SECRET_KEY", default="") or env_str("STRIPE_LIVE_SECRET_KEY", default="")
else:
    STRIPE_PUBLIC_KEY = env_str("STRIPE_PUBLIC_KEY", default="") or env_str("STRIPE_LIVE_PUBLIC_KEY", default="")
    STRIPE_SECRET_KEY = env_str("STRIPE_SECRET_KEY", default="") or env_str("STRIPE_LIVE_SECRET_KEY", default="")
