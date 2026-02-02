from .base import *

DEBUG = True
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']

# In local dev, keep CSP in report-only mode by default to avoid blocking inline scripts/styles.
# You can override via DJANGO_CSP_REPORT_ONLY=false in your environment.
CSP_REPORT_ONLY = config('DJANGO_CSP_REPORT_ONLY', cast=bool, default=True)

# Dev runs on HTTP; keep secure redirect/cookies off unless explicitly enabled via env.
SECURE_SSL_REDIRECT = config('DJANGO_SECURE_SSL_REDIRECT', cast=bool, default=False)
SESSION_COOKIE_SECURE = config('DJANGO_SESSION_COOKIE_SECURE', cast=bool, default=False)
CSRF_COOKIE_SECURE = config('DJANGO_CSRF_COOKIE_SECURE', cast=bool, default=False)

INSTALLED_APPS += [
    'debug_toolbar'
]

MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware', ]

# DEBUG TOOLBAR SETTINGS

DEBUG_TOOLBAR_PANELS = [
    'debug_toolbar.panels.versions.VersionsPanel',
    'debug_toolbar.panels.timer.TimerPanel',
    'debug_toolbar.panels.settings.SettingsPanel',
    'debug_toolbar.panels.headers.HeadersPanel',
    'debug_toolbar.panels.request.RequestPanel',
    'debug_toolbar.panels.sql.SQLPanel',
    'debug_toolbar.panels.staticfiles.StaticFilesPanel',
    'debug_toolbar.panels.templates.TemplatesPanel',
    'debug_toolbar.panels.cache.CachePanel',
    'debug_toolbar.panels.signals.SignalsPanel',
    'debug_toolbar.panels.logging.LoggingPanel',
    'debug_toolbar.panels.redirects.RedirectsPanel',
]


def show_toolbar(request):
    return True


DEBUG_TOOLBAR_CONFIG = {
    'INTERCEPT_REDIRECTS': False,
    'SHOW_TOOLBAR_CALLBACK': show_toolbar
}

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}

# Stripe (test mode)
# Env vars required:
# - STRIPE_TEST_PUBLIC_KEY
# - STRIPE_TEST_SECRET_KEY
# Optional:
# - STRIPE_TEST_WEBHOOK_SECRET (Stripe endpoint signing secret; if absent webhook accepts unsigned events)
STRIPE_PUBLIC_KEY = config('STRIPE_TEST_PUBLIC_KEY')
STRIPE_SECRET_KEY = config('STRIPE_TEST_SECRET_KEY')
STRIPE_WEBHOOK_SECRET = config('STRIPE_TEST_WEBHOOK_SECRET', default='')
