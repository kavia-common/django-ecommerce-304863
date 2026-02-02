import os
from datetime import timedelta

from decouple import config

BASE_DIR = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

SECRET_KEY = config('SECRET_KEY')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'crispy_forms',
    'crispy_bootstrap4',
    'django_countries',

    # Security headers
    'csp',

    # API layer (JWT is used only for API endpoints; template views keep allauth+session auth)
    'rest_framework',

    'core'
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',

    # CSP should run early so responses consistently include CSP headers.
    # It must run after SecurityMiddleware (recommended by django-csp docs).
    'csp.middleware.CSPMiddleware',

    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'djecommerce.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'djecommerce.wsgi.application'

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)

STATIC_URL = '/static/'
MEDIA_URL = '/media/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static_in_env')]
STATIC_ROOT = os.path.join(BASE_DIR, 'static_root')
MEDIA_ROOT = os.path.join(BASE_DIR, 'media_root')

# Auth

AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend'
)
SITE_ID = 1
LOGIN_REDIRECT_URL = '/'

# --------------------------------------------------------------------------------------
# Security hardening (env-driven, production-ready defaults)
# --------------------------------------------------------------------------------------
# NOTE: These are safe defaults for production, but made environment-togglable so local dev
# doesn't break when running on http://127.0.0.1.
#
# Env vars supported:
# - DJANGO_SECURE_SSL_REDIRECT (bool, default False)
# - DJANGO_SECURE_HSTS_SECONDS (int, default 0)  # set to 31536000 in prod
# - DJANGO_SECURE_PROXY_SSL_HEADER (string, default '')  # e.g. "HTTP_X_FORWARDED_PROTO,https"
# - DJANGO_ALLOWED_HOSTS (comma-separated, default '')
# - DJANGO_CSRF_TRUSTED_ORIGINS (comma-separated, default '')
#
# - DJANGO_SESSION_COOKIE_SECURE (bool, default follows DJANGO_SECURE_SSL_REDIRECT)
# - DJANGO_CSRF_COOKIE_SECURE (bool, default follows DJANGO_SECURE_SSL_REDIRECT)
#
# IMPORTANT: When running behind a reverse proxy/ingress that terminates TLS, configure
# DJANGO_SECURE_PROXY_SSL_HEADER and ensure your proxy sets that header correctly.

SECURE_SSL_REDIRECT = config('DJANGO_SECURE_SSL_REDIRECT', cast=bool, default=False)

# Cookie flags: secure defaults for prod, but allow toggles.
SESSION_COOKIE_SECURE = config('DJANGO_SESSION_COOKIE_SECURE', cast=bool, default=SECURE_SSL_REDIRECT)
CSRF_COOKIE_SECURE = config('DJANGO_CSRF_COOKIE_SECURE', cast=bool, default=SECURE_SSL_REDIRECT)

SESSION_COOKIE_HTTPONLY = True
# Django constraint: CSRF cookie must be readable by JS in some scenarios, keep False.
CSRF_COOKIE_HTTPONLY = False

SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

# HSTS (set seconds to 31536000 for 1 year in production; keep 0 in dev)
SECURE_HSTS_SECONDS = config('DJANGO_SECURE_HSTS_SECONDS', cast=int, default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

_proxy_header = config('DJANGO_SECURE_PROXY_SSL_HEADER', default='').strip()
if _proxy_header:
    # Expected format: "HTTP_X_FORWARDED_PROTO,https"
    try:
        header_name, header_value = [p.strip() for p in _proxy_header.split(',', 1)]
        SECURE_PROXY_SSL_HEADER = (header_name, header_value)
    except ValueError:
        # Misconfiguration should be visible during startup rather than silently insecure.
        raise ValueError(
            "DJANGO_SECURE_PROXY_SSL_HEADER must be in format 'HTTP_HEADER_NAME,expected_value'"
        )

# Host/CSRF origin allowlists (env-driven)
_allowed_hosts_raw = config('DJANGO_ALLOWED_HOSTS', default='').strip()
if _allowed_hosts_raw:
    ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts_raw.split(',') if h.strip()]

_csrf_trusted_raw = config('DJANGO_CSRF_TRUSTED_ORIGINS', default='').strip()
if _csrf_trusted_raw:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_trusted_raw.split(',') if o.strip()]

# --------------------------------------------------------------------------------------
# Content Security Policy (CSP)
# --------------------------------------------------------------------------------------
# Baseline policy must allow Stripe.js for the payment page and keep template flows working.
#
# Env vars supported:
# - DJANGO_CSP_REPORT_ONLY (bool, default True in DEBUG, else False)
#
# You can extend sources with:
# - DJANGO_CSP_ADDITIONAL_SCRIPT_SRC (comma-separated)
# - DJANGO_CSP_ADDITIONAL_STYLE_SRC (comma-separated)
# - DJANGO_CSP_ADDITIONAL_CONNECT_SRC (comma-separated)
# - DJANGO_CSP_ADDITIONAL_IMG_SRC (comma-separated)
# - DJANGO_CSP_ADDITIONAL_FRAME_SRC (comma-separated)
#
# Note: We keep 'unsafe-inline' for scripts/styles because templates include inline <script>/<style>.
# If you want to tighten later, migrate to nonces/hashes and remove 'unsafe-inline'.

DEBUG = config('DEBUG', cast=bool, default=False)

CSP_REPORT_ONLY = config('DJANGO_CSP_REPORT_ONLY', cast=bool, default=DEBUG)

def _parse_csp_extra(env_name: str):
    raw = config(env_name, default='').strip()
    if not raw:
        return []
    return [v.strip() for v in raw.split(',') if v.strip()]

CSP_DEFAULT_SRC = ("'self'",)

CSP_SCRIPT_SRC = (
    "'self'",
    "'unsafe-inline'",
    "https://js.stripe.com",
    *_parse_csp_extra('DJANGO_CSP_ADDITIONAL_SCRIPT_SRC'),
)

CSP_STYLE_SRC = (
    "'self'",
    "'unsafe-inline'",
    *_parse_csp_extra('DJANGO_CSP_ADDITIONAL_STYLE_SRC'),
)

CSP_IMG_SRC = (
    "'self'",
    "data:",
    *_parse_csp_extra('DJANGO_CSP_ADDITIONAL_IMG_SRC'),
)

CSP_FRAME_SRC = (
    "https://js.stripe.com",
    *_parse_csp_extra('DJANGO_CSP_ADDITIONAL_FRAME_SRC'),
)

CSP_CONNECT_SRC = (
    "'self'",
    "https://api.stripe.com",
    *_parse_csp_extra('DJANGO_CSP_ADDITIONAL_CONNECT_SRC'),
)

# --------------------------------------------------------------------------------------
# DRF / JWT (API auth) + throttling
# --------------------------------------------------------------------------------------
#
# IMPORTANT:
# - Template-rendered views continue to use Django sessions + allauth unchanged.
# - API endpoints authenticate via "Authorization: Bearer <access_token>".
#
# Env vars required:
# - JWT_SIGNING_KEY: secret used to sign JWTs (separate from Django SECRET_KEY to allow rotation)
#
# Throttling env vars:
# - DRF_THROTTLE_ANON (default "60/min")
# - DRF_THROTTLE_USER (default "600/min")
#
# If JWT_SIGNING_KEY is not provided, we fall back to SECRET_KEY for backwards compatibility
# in local/dev, but production SHOULD set JWT_SIGNING_KEY.
JWT_SIGNING_KEY = config('JWT_SIGNING_KEY', default=SECRET_KEY)

REST_FRAMEWORK = {
    # Keep API auth separate from template auth; session auth remains for browser views.
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),

    # Throttling defaults (defense-in-depth against brute force / abusive clients).
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': config('DRF_THROTTLE_ANON', default='60/min'),
        'user': config('DRF_THROTTLE_USER', default='600/min'),
    },
}

SIMPLE_JWT = {
    # Use a dedicated signing key so it can be rotated independently from Django's SECRET_KEY.
    'SIGNING_KEY': JWT_SIGNING_KEY,
    'ALGORITHM': 'HS256',

    # Reasonable defaults; can be adjusted later via settings/env-driven strategy.
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=5),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),

    # Reduce token replay risk when refresh is used.
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': False,  # blacklist app not installed; keep False unless added later

    'AUTH_HEADER_TYPES': ('Bearer',),
}

# CRISPY FORMS

CRISPY_TEMPLATE_PACK = 'bootstrap4'

# --------------------------------------------------------------------------------------
# Logging hygiene
# --------------------------------------------------------------------------------------
# Avoid leaking secrets by keeping default Django request/exception logs concise.
# Add explicit security logger handlers for SuspiciousOperation and related warnings.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '[{levelname}] {name}: {message}', 'style': '{'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'simple'},
    },
    'loggers': {
        # Core Django logging
        'django': {'handlers': ['console'], 'level': config('DJANGO_LOG_LEVEL', default='INFO')},
        # Security-related events (bad hosts, suspicious requests, etc.)
        'django.security': {'handlers': ['console'], 'level': config('DJANGO_SECURITY_LOG_LEVEL', default='WARNING'), 'propagate': False},
        # Explicitly capture SuspiciousOperation
        'django.security.SuspiciousOperation': {'handlers': ['console'], 'level': config('DJANGO_SECURITY_LOG_LEVEL', default='WARNING'), 'propagate': False},
    },
}
