"""Tests for the Supabase JWT route guard."""

import importlib
import time

import jwt
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.delenv("SUPABASE_JWT_AUDIENCE", raising=False)

    import backend.main as main_mod

    importlib.reload(main_mod)
    main_mod.app.dependency_overrides.clear()
    return TestClient(main_mod.app)


def test_health_stays_public(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_protected_endpoint_requires_bearer_token(client):
    resp = client.get("/api/videos?channel_id=UC_missing")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


def test_protected_endpoint_fails_closed_without_auth_config(client):
    resp = client.get(
        "/api/videos?channel_id=UC_missing",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert resp.status_code == 503
    assert "SUPABASE_URL" in resp.json()["detail"]


def test_valid_supabase_hs256_token_allows_route(client, monkeypatch):
    supabase_url = "http://127.0.0.1:54321"
    secret = "test-jwt-secret"
    monkeypatch.setenv("SUPABASE_URL", supabase_url)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", secret)
    token = jwt.encode(
        {
            "iss": f"{supabase_url}/auth/v1",
            "aud": "authenticated",
            "exp": int(time.time()) + 3600,
            "sub": "00000000-0000-0000-0000-000000000001",
            "role": "authenticated",
            "email": "test@example.com",
        },
        secret,
        algorithm="HS256",
    )

    resp = client.get(
        "/api/videos?channel_id=UC_missing",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "data": None, "error": "Channel not found"}
