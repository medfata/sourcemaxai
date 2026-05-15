"""Tests for proxy-related runtime configuration."""

from __future__ import annotations

import pytest

from backend.config import (
    DEFAULT_PROXY_BLOCKLIST_TTL_HOURS,
    DEFAULT_PROXY_MAX_ATTEMPTS,
    DEFAULT_PROXY_SESSION_LIFETIME_MIN,
    DEFAULT_TRANSCRIPT_WORKERS,
    load_runtime_config,
)


PROXY_ENV_VARS = (
    "IPROYAL_PROXY_HOST",
    "IPROYAL_PROXY_USER",
    "IPROYAL_PROXY_PASS",
    "WEBSHARE_PROXY_USER",
    "WEBSHARE_PROXY_PASS",
    "PROXY_MAX_ATTEMPTS",
    "PROXY_SESSION_LIFETIME_MIN",
    "PROXY_BLOCKLIST_TTL_HOURS",
    "TRANSCRIPT_WORKERS",
)

PROD_BASE_ENV = {
    "APP_ENV": "production",
    "STORAGE_BACKEND": "supabase",
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
    "SUPABASE_JWT_SECRET": "jwt-secret",
    "MINIMAX_API_KEY": "minimax-key",
    "CORS_ORIGINS": "https://app.example.com",
    "PIPELINE_WORKER_MODE": "external",
    "LOG_FORMAT": "json",
}

PROD_PROXY_ENV = {
    "IPROYAL_PROXY_HOST": "geo.iproyal.com:12321",
    "IPROYAL_PROXY_USER": "iproyal-user",
    "IPROYAL_PROXY_PASS": "iproyal-pass",
    "WEBSHARE_PROXY_USER": "webshare-user",
    "WEBSHARE_PROXY_PASS": "webshare-pass",
}


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch):
    for name in PROXY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("PIPELINE_WORKER_MODE", raising=False)
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    monkeypatch.delenv("ALLOW_LOCAL_SUPABASE_EMBEDDED_WORKER", raising=False)


def _set_env(monkeypatch, env: dict[str, str]) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_proxy_defaults_when_env_unset():
    config = load_runtime_config()

    assert config.proxy.iproyal_host == ""
    assert config.proxy.iproyal_user == ""
    assert config.proxy.iproyal_pass == ""
    assert config.proxy.webshare_user == ""
    assert config.proxy.webshare_pass == ""
    assert config.proxy.max_attempts == DEFAULT_PROXY_MAX_ATTEMPTS
    assert config.proxy.session_lifetime_min == DEFAULT_PROXY_SESSION_LIFETIME_MIN
    assert config.proxy.blocklist_ttl_hours == DEFAULT_PROXY_BLOCKLIST_TTL_HOURS
    assert config.proxy.transcript_workers == DEFAULT_TRANSCRIPT_WORKERS
    assert config.proxy.iproyal_enabled is False
    assert config.proxy.webshare_enabled is False
    assert config.proxy.any_provider_enabled is False
    assert config.errors == []


def test_dev_does_not_require_proxy_creds():
    config = load_runtime_config()

    assert config.is_production is False
    assert config.errors == []
    assert all("IPROYAL" not in w for w in config.warnings)


def test_prod_requires_iproyal_credentials(monkeypatch):
    _set_env(monkeypatch, PROD_BASE_ENV)

    config = load_runtime_config()

    assert config.is_production is True
    assert "IPROYAL_PROXY_HOST is required in production" in config.errors
    assert "IPROYAL_PROXY_USER is required in production" in config.errors
    assert "IPROYAL_PROXY_PASS is required in production" in config.errors


def test_prod_warns_when_webshare_missing(monkeypatch):
    _set_env(monkeypatch, PROD_BASE_ENV)
    monkeypatch.setenv("IPROYAL_PROXY_HOST", PROD_PROXY_ENV["IPROYAL_PROXY_HOST"])
    monkeypatch.setenv("IPROYAL_PROXY_USER", PROD_PROXY_ENV["IPROYAL_PROXY_USER"])
    monkeypatch.setenv("IPROYAL_PROXY_PASS", PROD_PROXY_ENV["IPROYAL_PROXY_PASS"])

    config = load_runtime_config()

    assert config.errors == []
    assert config.proxy.iproyal_enabled is True
    assert config.proxy.webshare_enabled is False
    assert any("WEBSHARE_PROXY_USER/PASS" in w for w in config.warnings)


def test_prod_full_proxy_creds_no_diagnostics(monkeypatch):
    _set_env(monkeypatch, PROD_BASE_ENV)
    _set_env(monkeypatch, PROD_PROXY_ENV)

    config = load_runtime_config()

    assert config.errors == []
    assert config.proxy.iproyal_enabled is True
    assert config.proxy.webshare_enabled is True
    assert config.proxy.any_provider_enabled is True
    assert all("WEBSHARE_PROXY_USER/PASS" not in w for w in config.warnings)


@pytest.mark.parametrize(
    "name",
    [
        "PROXY_MAX_ATTEMPTS",
        "PROXY_SESSION_LIFETIME_MIN",
        "PROXY_BLOCKLIST_TTL_HOURS",
        "TRANSCRIPT_WORKERS",
    ],
)
def test_positive_int_helper_rejects_non_integer(monkeypatch, name):
    monkeypatch.setenv(name, "abc")

    config = load_runtime_config()

    assert any(name in err and "positive integer" in err for err in config.errors)


@pytest.mark.parametrize(
    "name",
    [
        "PROXY_MAX_ATTEMPTS",
        "PROXY_SESSION_LIFETIME_MIN",
        "PROXY_BLOCKLIST_TTL_HOURS",
        "TRANSCRIPT_WORKERS",
    ],
)
def test_positive_int_helper_rejects_zero(monkeypatch, name):
    monkeypatch.setenv(name, "0")

    config = load_runtime_config()

    assert any(name in err and "positive integer" in err for err in config.errors)


@pytest.mark.parametrize(
    "name",
    [
        "PROXY_MAX_ATTEMPTS",
        "PROXY_SESSION_LIFETIME_MIN",
        "PROXY_BLOCKLIST_TTL_HOURS",
        "TRANSCRIPT_WORKERS",
    ],
)
def test_positive_int_helper_rejects_negative(monkeypatch, name):
    monkeypatch.setenv(name, "-3")

    config = load_runtime_config()

    assert any(name in err and "positive integer" in err for err in config.errors)


def test_positive_int_helper_accepts_overrides(monkeypatch):
    monkeypatch.setenv("PROXY_MAX_ATTEMPTS", "9")
    monkeypatch.setenv("PROXY_SESSION_LIFETIME_MIN", "30")
    monkeypatch.setenv("PROXY_BLOCKLIST_TTL_HOURS", "12")
    monkeypatch.setenv("TRANSCRIPT_WORKERS", "2")

    config = load_runtime_config()

    assert config.errors == []
    assert config.proxy.max_attempts == 9
    assert config.proxy.session_lifetime_min == 30
    assert config.proxy.blocklist_ttl_hours == 12
    assert config.proxy.transcript_workers == 2
