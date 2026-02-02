"""
Test/runtime compatibility shims.

This repository is a legacy Django 2.2 codebase, but our execution environment uses
Python 3.12. Some legacy dependencies (notably django-allauth==0.39.1 and
django-countries==5.3.3) still import `django.utils.six.moves...`, which relies on
a PEP302-only importer that does not work on Python 3.12 (needs `find_spec`).

Python automatically imports `sitecustomize` on interpreter startup (when present
on sys.path). By placing this at the project root (same directory as manage.py),
it is importable and executed before Django loads INSTALLED_APPS.

We patch the meta_path importer used by six/django.utils.six to implement find_spec,
restoring support for imports like:
    from django.utils.six.moves.urllib.parse import urlsplit
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys


def _patch_six_importer(module_name: str) -> None:
    """Patch six-like meta importers to support Python 3.12+ (PEP451 find_spec)."""
    mod = sys.modules.get(module_name)
    if mod is None:
        return

    # The legacy six implementation registers a meta_path importer instance
    # `_SixMetaPathImporter` with `find_module/load_module` only.
    importer = getattr(mod, "_importer", None)
    if importer is None:
        return

    if hasattr(importer, "find_spec"):
        # Already patched / modern enough.
        return

    def find_spec(fullname: str, path=None, target=None):  # noqa: ANN001
        loader = importer.find_module(fullname, path)
        if loader is None:
            return None
        # Use is_package when available; six sets __path__ to indicate packages.
        is_pkg = False
        try:
            is_pkg = bool(importer.is_package(fullname))
        except Exception:
            is_pkg = False
        return importlib.machinery.ModuleSpec(fullname, loader, is_package=is_pkg)

    # Monkey-patch method onto the importer instance
    importer.find_spec = find_spec  # type: ignore[attr-defined]


# Ensure both `six` and `django.utils.six` (django-utils-six) are importable.
# Importing them registers their meta_path importers; then we patch.
try:
    import six  # noqa: F401

    _patch_six_importer("six")
except Exception:
    # If six isn't importable we can't patch it, but the project depends on it;
    # tests will fail loudly elsewhere.
    pass

try:
    import django.utils.six  # noqa: F401

    _patch_six_importer("django.utils.six")
except Exception:
    pass
