"""
Test settings for the project.

This module is designed for CI / automated tests where production secrets are
not available. It provides safe dummy values for required environment variables
and configures faster, test-friendly defaults.
"""

from .base import *  # noqa: F403,F401


# --------------------------------------------------------------------------------------
# Core test flags
# --------------------------------------------------------------------------------------
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

# Keep CSP non-blocking during tests.
CSP_REPORT_ONLY = True

# Tests run over HTTP; don't force redirects/secure cookies.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Use a deterministic but non-production secret to satisfy settings import.
# (Django requires a SECRET_KEY; tests should never use real secrets.)
SECRET_KEY = "dummy-secret-key-for-tests-only"  # noqa: S105

# JWT signing key used by SIMPLE_JWT in base settings.
JWT_SIGNING_KEY = "dummy-jwt-signing-key-for-tests-only"  # noqa: S105

# Stripe dummy values (tests should mock Stripe API calls / webhook signatures)
STRIPE_PUBLISHABLE_KEY = "pk_test_dummy"
STRIPE_SECRET_KEY = "sk_test_dummy"
STRIPE_WEBHOOK_SECRET = "whsec_dummy"

# Some code paths/settings variants reference *_TEST_* or *_LIVE_* keys; provide them too.
STRIPE_TEST_PUBLIC_KEY = STRIPE_PUBLISHABLE_KEY
STRIPE_TEST_SECRET_KEY = STRIPE_SECRET_KEY
STRIPE_TEST_WEBHOOK_SECRET = STRIPE_WEBHOOK_SECRET
STRIPE_LIVE_PUBLIC_KEY = "pk_live_dummy"
STRIPE_LIVE_SECRET_KEY = "sk_live_dummy"

# --------------------------------------------------------------------------------------
# Speed up tests
# --------------------------------------------------------------------------------------
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# --------------------------------------------------------------------------------------
# Disable debug toolbar in tests (even if installed in dev settings)
# --------------------------------------------------------------------------------------
if "debug_toolbar" in INSTALLED_APPS:  # noqa: F405
    INSTALLED_APPS = [app for app in INSTALLED_APPS if app != "debug_toolbar"]  # noqa: F405

# Remove middleware if present (defensive; base.py doesn't add it).
MIDDLEWARE = [  # noqa: F405
    mw for mw in MIDDLEWARE  # noqa: F405
    if mw != "debug_toolbar.middleware.DebugToolbarMiddleware"
]
