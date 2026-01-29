import pytest
from django.core.exceptions import ImproperlyConfigured

from djecommerce.settings.env import validate_settings


@pytest.mark.parametrize(
    "debug,environment,should_raise",
    [
        (True, "production", True),
        (True, "local", False),
        (
            False,
            "production",
            False,
        ),  # may still raise if SECRET_KEY missing; covered separately
    ],
)
def test_validate_settings_debug_gating(monkeypatch, debug, environment, should_raise):
    # Ensure SECRET_KEY present when production unless we want that to raise instead.
    if environment.strip().lower() == "production":
        monkeypatch.setenv("SECRET_KEY", "x")

    if should_raise:
        with pytest.raises(ImproperlyConfigured):
            validate_settings(
                debug=debug,
                environment=environment,
                allowed_hosts=["example.com"],
                payment_mode="dummy",
            )
    else:
        validate_settings(
            debug=debug,
            environment=environment,
            allowed_hosts=["example.com"],
            payment_mode="dummy",
        )


def test_validate_settings_requires_secret_key_in_production(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ImproperlyConfigured):
        validate_settings(
            debug=False,
            environment="production",
            allowed_hosts=["example.com"],
            payment_mode="dummy",
        )


def test_validate_settings_disallows_wildcard_allowed_hosts_in_production(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "x")
    with pytest.raises(ImproperlyConfigured):
        validate_settings(
            debug=False,
            environment="production",
            allowed_hosts=["*"],
            payment_mode="dummy",
        )


def test_validate_settings_requires_stripe_keys_when_stripe_mode_in_production(
    monkeypatch,
):
    monkeypatch.setenv("SECRET_KEY", "x")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_PUBLIC_KEY", raising=False)

    with pytest.raises(ImproperlyConfigured):
        validate_settings(
            debug=False,
            environment="production",
            allowed_hosts=["example.com"],
            payment_mode="stripe",
        )

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setenv("STRIPE_PUBLIC_KEY", "pk_test")
    validate_settings(
        debug=False,
        environment="production",
        allowed_hosts=["example.com"],
        payment_mode="stripe",
    )
