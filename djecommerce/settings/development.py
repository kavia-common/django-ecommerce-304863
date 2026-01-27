"""Development Django settings.

This module intentionally overlays settings on top of `base.py` using a star import
to keep settings overrides concise and familiar to Django users.
"""

from .base import *  # noqa: F403,F401  # pylint: disable=wildcard-import,unused-wildcard-import

DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1"]

INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405

MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]  # noqa: F405

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


def show_toolbar(_request):
    return True


DEBUG_TOOLBAR_CONFIG = {
    "INTERCEPT_REDIRECTS": False,
    "SHOW_TOOLBAR_CALLBACK": show_toolbar,
}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(BASE_DIR, "db.sqlite3"),  # noqa: F405
    }
}

STRIPE_PUBLIC_KEY = config("STRIPE_TEST_PUBLIC_KEY", default="")  # noqa: F405
STRIPE_SECRET_KEY = config("STRIPE_TEST_SECRET_KEY", default="")  # noqa: F405
