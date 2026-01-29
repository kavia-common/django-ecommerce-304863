import os

from .base import *  # noqa

DEBUG = True
validate_settings(
    debug=DEBUG,
    environment=ENVIRONMENT,
    allowed_hosts=ALLOWED_HOSTS,
    payment_mode=PAYMENT_MODE,
)

# Allow override via env, but default to local loopback.
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", default=["127.0.0.1", "localhost"])

INSTALLED_APPS += [
    "debug_toolbar",
]

MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]

# DEBUG TOOLBAR SETTINGS
DEBUG_TOOLBAR_PANELS = [
    "debug_toolbar.panels.versions.VersionsPanel",
    "debug_toolbar.panels.timer.TimerPanel",
    "debug_toolbar.panels.settings.SettingsPanel",
    "debug_toolbar.panels.headers.HeadersPanel",
    "debug_toolbar.panels.request.RequestPanel",
    "debug_toolbar.panels.sql.SQLPanel",
    "debug_toolbar.panels.staticfiles.StaticFilesPanel",
    "debug_toolbar.panels.templates.TemplatesPanel",
    "debug_toolbar.panels.cache.CachePanel",
    "debug_toolbar.panels.signals.SignalsPanel",
    "debug_toolbar.panels.logging.LoggingPanel",
    "debug_toolbar.panels.redirects.RedirectsPanel",
]


def show_toolbar(request):
    return True


DEBUG_TOOLBAR_CONFIG = {
    "INTERCEPT_REDIRECTS": False,
    "SHOW_TOOLBAR_CALLBACK": show_toolbar,
}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(BASE_DIR, "db.sqlite3"),
    }
}

# Stripe keys (dev/test keys). Optional when running dummy payment mode.
STRIPE_PUBLIC_KEY = env_str("STRIPE_PUBLIC_KEY", default="") or config(
    "STRIPE_TEST_PUBLIC_KEY", default=""
)
STRIPE_SECRET_KEY = env_str("STRIPE_SECRET_KEY", default="") or config(
    "STRIPE_TEST_SECRET_KEY", default=""
)
