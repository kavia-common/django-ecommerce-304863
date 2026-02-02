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


def env_str(name: str, default: str | None = None) -> str | None:
    """Read a string environment variable, returning default if missing/blank."""
    raw = os.environ.get(name, None)
    if raw is None:
        return default
    raw = str(raw).strip()
    if raw == "":
        return default
    return raw


def env_list(name: str, default: list[str] | None = None) -> list[str]:
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


def _validate_production_hosts(*, allowed_hosts: list[str]) -> None:
    """
    Ensure ALLOWED_HOSTS is explicitly set to something safer than wildcard.

    In production, we disallow:
    - empty list (would break requests)
    - "*" wildcard (too permissive for a typical deployment)
    """
    normalized = [str(h).strip() for h in (allowed_hosts or []) if str(h).strip()]
    if not normalized:
        raise ImproperlyConfigured("ALLOWED_HOSTS must not be empty in production.")
    if "*" in normalized:
        raise ImproperlyConfigured("ALLOWED_HOSTS must not contain '*' in production.")


def _validate_payment_mode(*, payment_mode: str) -> str:
    """
    Validate and normalize payment mode.

    Allowed:
    - dummy (default)
    - stripe
    """
    mode = (payment_mode or "dummy").strip().lower()
    if mode not in {"dummy", "stripe"}:
        raise ImproperlyConfigured("PAYMENT_MODE must be one of: dummy, stripe.")
    return mode


# PUBLIC_INTERFACE
def validate_settings(
    *,
    debug: bool,
    environment: str,
    allowed_hosts: list[str] | None = None,
    payment_mode: str | None = None,
) -> None:
    """
    Validate key settings at import time (fail fast).

    Parameters
    ----------
    debug:
        Django DEBUG flag.
    environment:
        Deployment environment selector. Typically: local | development | production
    allowed_hosts:
        The computed ALLOWED_HOSTS list (optional). When provided and environment=production,
        we validate it isn't empty or wildcard.
    payment_mode:
        The configured payment mode (optional). When provided and in production, we can
        enforce required keys for stripe mode.

    Validation Rules
    ----------------
    - DEBUG must not be True outside local/dev environments.
    - SECRET_KEY is required for production.
    - In production:
        - ALLOWED_HOSTS must be non-empty and must not contain '*'
        - If PAYMENT_MODE=stripe: STRIPE_PUBLIC_KEY and STRIPE_SECRET_KEY are required
    """
    env_norm = (environment or "").strip().lower()

    if debug and env_norm not in {"local", "development", "dev"}:
        raise ImproperlyConfigured(
            "DEBUG=True is not allowed in non-local environments. "
            "Set DEBUG=False and ensure secure settings are enabled."
        )

    if env_norm == "production":
        require_env(
            "SECRET_KEY",
            hint="Generate a strong secret key and set it in your environment.",
        )

        if allowed_hosts is not None:
            _validate_production_hosts(allowed_hosts=allowed_hosts)

        if payment_mode is not None:
            mode = _validate_payment_mode(payment_mode=payment_mode)
            if mode == "stripe":
                require_env(
                    "STRIPE_SECRET_KEY", hint="Required when PAYMENT_MODE=stripe."
                )
                require_env(
                    "STRIPE_PUBLIC_KEY", hint="Required when PAYMENT_MODE=stripe."
                )
