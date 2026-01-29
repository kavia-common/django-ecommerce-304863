import os

from django.core.wsgi import get_wsgi_application

# Default to development settings for preview/local environments.
# Production deployments should set DJANGO_SETTINGS_MODULE explicitly.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "djecommerce.settings.development")

application = get_wsgi_application()
