"""Tests for runtime configuration safeguards."""

from backend.config import embedded_worker_enabled, load_runtime_config


def test_local_supabase_api_does_not_enable_embedded_worker_by_default(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("PIPELINE_WORKER_MODE", "embedded")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.delenv("ALLOW_LOCAL_SUPABASE_EMBEDDED_WORKER", raising=False)

    config = load_runtime_config("api")

    assert embedded_worker_enabled() is False
    assert any("embedded is ignored" in warning for warning in config.warnings)


def test_local_supabase_api_can_explicitly_enable_embedded_worker(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("STORAGE_BACKEND", "supabase")
    monkeypatch.setenv("PIPELINE_WORKER_MODE", "embedded")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("ALLOW_LOCAL_SUPABASE_EMBEDDED_WORKER", "true")

    assert embedded_worker_enabled() is True
