from .base import *

DEBUG = config('DEBUG', cast=bool)

# Allow hosts via env (preferred). If unset, fall back to a safe placeholder list you should replace.
if not globals().get("ALLOWED_HOSTS"):
    ALLOWED_HOSTS = ['ip-address', 'www.your-website.com']

# Production security defaults (can still be overridden via env in base.py)
SECURE_SSL_REDIRECT = config('DJANGO_SECURE_SSL_REDIRECT', cast=bool, default=True)
SESSION_COOKIE_SECURE = config('DJANGO_SESSION_COOKIE_SECURE', cast=bool, default=True)
CSRF_COOKIE_SECURE = config('DJANGO_CSRF_COOKIE_SECURE', cast=bool, default=True)

# Enable HSTS for 1 year by default in production (override with DJANGO_SECURE_HSTS_SECONDS if needed).
SECURE_HSTS_SECONDS = config('DJANGO_SECURE_HSTS_SECONDS', cast=int, default=31536000)

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST'),
        'PORT': ''
    }
}

STRIPE_PUBLIC_KEY = config('STRIPE_LIVE_PUBLIC_KEY')
STRIPE_SECRET_KEY = config('STRIPE_LIVE_SECRET_KEY')
STRIPE_WEBHOOK_SECRET = config('STRIPE_WEBHOOK_SECRET', default='')

# In production, CSP should usually be enforcing (not report-only).
CSP_REPORT_ONLY = config('DJANGO_CSP_REPORT_ONLY', cast=bool, default=False)
