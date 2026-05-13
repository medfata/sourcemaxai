"""Tests for the public waitlist route."""

import importlib
import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        old_data_dir = os.environ.get("DATA_DIR")
        old_storage_backend = os.environ.get("STORAGE_BACKEND")
        monkeypatch.setenv("DATA_DIR", tmpdir)
        monkeypatch.setenv("STORAGE_BACKEND", "local")

        import backend.main as main_mod
        from backend import storage
        from backend.routes import waitlist

        importlib.reload(storage)
        importlib.reload(waitlist)
        importlib.reload(main_mod)

        yield TestClient(main_mod.app), tmpdir

        if old_data_dir is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = old_data_dir
        if old_storage_backend is None:
            os.environ.pop("STORAGE_BACKEND", None)
        else:
            os.environ["STORAGE_BACKEND"] = old_storage_backend


def test_join_waitlist_is_public_and_persists_entry(client):
    test_client, tmpdir = client

    resp = test_client.post(
        "/api/waitlist",
        json={
            "email": "USER@Example.com",
            "youtube_channel": "https://youtube.com/@trace",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "ok": True,
        "data": {
            "email": "user@example.com",
            "youtube_channel": "https://youtube.com/@trace",
            "transcript_minutes": 1000,
        },
        "error": None,
    }

    with open(os.path.join(tmpdir, "waitlist_entries.json"), encoding="utf-8") as f:
        stored = json.load(f)
    assert len(stored["entries"]) == 1
    assert stored["entries"][0]["normalized_email"] == "user@example.com"


def test_join_waitlist_rejects_invalid_email(client):
    test_client, _tmpdir = client

    resp = test_client.post("/api/waitlist", json={"email": "not-an-email"})

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": False,
        "data": None,
        "error": "Enter a valid email address",
    }


def test_join_waitlist_updates_existing_email(client):
    test_client, tmpdir = client

    test_client.post("/api/waitlist", json={"email": "user@example.com"})
    resp = test_client.post(
        "/api/waitlist",
        json={"email": "USER@example.com", "youtube_channel": "https://youtube.com/@new"},
    )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    with open(os.path.join(tmpdir, "waitlist_entries.json"), encoding="utf-8") as f:
        stored = json.load(f)
    assert len(stored["entries"]) == 1
    assert stored["entries"][0]["youtube_channel"] == "https://youtube.com/@new"
