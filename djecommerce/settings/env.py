"""
Environment parsing + validation helpers for Django settings.

These helpers are intentionally dependency-light (no new packages required).
They provide:
- consistent parsing of booleans and list-like env vars
- validation to fail fast for missing critical configuration in production

This project uses python-decouple for many settings; we keep that and add
additional safety validation where required.
"""

import json
import os
from typing import List, Optional

from django.core.exceptions import ImproperlyConfigured


def _truthy(val: str) -> bool:
    return str(val).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def env_bool(name: str, default: bool = False) -> bool:
    """
    Read a boolean environment variable.

    Supports: 1/0, true/false, yes/no, on/off (case-insensitive).
    """
    raw = os.environ.get(name, None)
    if raw is None or str(raw).strip() == "":
        return bool(default)
    return _truthy(raw)


def env_str(name: str, default: Optional[str] = None) -> Optional[str]:
    """Read a string environment variable, returning default if missing/blank."""
    raw = os.environ.get(name, None)
    if raw is None:
        return default
    raw = str(raw).strip()
    if raw == "":
        return default
    return raw


def env_list(name: str, default: Optional[List[str]] = None) -> List[str]:
    """
    Read a list environment variable.

    Supported formats:
      - JSON array: ["a.com", "b.com"]
      - comma-separated: a.com,b.com
      - whitespace separated: a.com b.com

    Returns a list with blanks stripped and removed.
    """
    raw = os.environ.get(name, None)
    if raw is None or str(raw).strip() == "":
        return list(default or [])

    raw_s = str(raw).strip()

    # JSON list support for safety (allows commas inside values if needed).
    if raw_s.startswith("["):
        try:
            parsed = json.loads(raw_s)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            # fall back to split parsing below
            pass

    # comma and whitespace separated fallback
    parts = []
    for chunk in raw_s.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts.extend([p.strip() for p in chunk.split() if p.strip()])

    return [p for p in parts if p]


def require_env(name: str, *, hint: str = "") -> str:
    """
    Require a non-empty environment variable, otherwise raise ImproperlyConfigured.
    """
    value = env_str(name, default=None)
    if value is None:
        message = f"Missing required environment variable: {name}."
        if hint:
            message += f" {hint}"
        raise ImproperlyConfigured(message)
    return value


def validate_settings(*, debug: bool, environment: str) -> None:
    """
    Validate key settings at import time (fail fast).

    Rules implemented per request:
    - DEBUG defaults to False and must not be True outside local/dev environments.
    - SECRET_KEY is required for production.
    """
    env_norm = (environment or "").strip().lower()

    if debug and env_norm not in {"local", "development", "dev"}:
        raise ImproperlyConfigured(
            "DEBUG=True is not allowed in non-local environments. "
            "Set DEBUG=False and ensure secure settings are enabled."
        )
    if env_norm == "production":
        # Keep requirement strict: SECRET_KEY must be present.
        require_env(
            "SECRET_KEY",
            hint="Generate a strong secret key and set it in your environment.",
        )
