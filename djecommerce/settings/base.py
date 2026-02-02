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

    # API layer (JWT is used only for API endpoints; template views keep allauth+session auth)
    'rest_framework',

    'core'
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
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

# DRF / JWT (API auth) ----------------------------------------------------------
#
# IMPORTANT:
# - Template-rendered views continue to use Django sessions + allauth unchanged.
# - API endpoints authenticate via "Authorization: Bearer <access_token>".
#
# Env vars required:
# - JWT_SIGNING_KEY: secret used to sign JWTs (separate from Django SECRET_KEY to allow rotation)
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
