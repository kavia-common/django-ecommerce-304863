"""
Runtime compatibility shims.

Historically, this project depended on legacy packages that imported
`django.utils.six` / `six` meta path importers that were incompatible with
Python 3.12.

The project has been upgraded to Django 4.2 LTS and modern dependency versions
that no longer rely on `django.utils.six`. This module is kept intentionally
as a safe no-op placeholder to avoid surprises in environments that may still
auto-import `sitecustomize`.
"""
