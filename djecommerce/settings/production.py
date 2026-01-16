"""Production Django settings."""

from .base import *  # noqa: F403,F401  (importing base settings intentionally)

DEBUG = config("DEBUG", cast=bool)  # noqa: F405
ALLOWED_HOSTS = ["ip-address", "www.your-website.com"]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql_psycopg2",
        "NAME": config("DB_NAME"),  # noqa: F405
        "USER": config("DB_USER"),  # noqa: F405
        "PASSWORD": config("DB_PASSWORD"),  # noqa: F405
        "HOST": config("DB_HOST"),  # noqa: F405
        "PORT": "",
    }
}

STRIPE_PUBLIC_KEY = config("STRIPE_LIVE_PUBLIC_KEY")  # noqa: F405
STRIPE_SECRET_KEY = config("STRIPE_LIVE_SECRET_KEY")  # noqa: F405
