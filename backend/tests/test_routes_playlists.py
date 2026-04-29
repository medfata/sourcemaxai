"""Tests for playlist API routes."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.main import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def temp_data_dir(monkeypatch):
    """Use a temporary directory for DATA_DIR."""
    with tempfile.TemporaryDirectory() as tmpdir:
        old = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = tmpdir
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        import importlib
        from backend import storage
        importlib.reload(storage)
        yield tmpdir
        if old is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = old


def _setup_channel(tmpdir: str, channel_id: str):
    """Write meta.json and videos.json for a test channel."""
    channel_dir = Path(tmpdir) / "channels" / channel_id
    channel_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "channel_id": channel_id,
        "channel_name": "Test Channel",
        "channel_handle": "@test",
        "avatar_url": "http://example.com/avatar.jpg",
    }
    with open(channel_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f)
    videos = [{
        "id": f"vid_{i}",
        "title": f"Video {i}",
        "upload_date": "20230101",
        "duration": 60,
        "view_count": 100,
        "thumbnail": "http://example.com/thumb.jpg",
    } for i in range(5)]
    with open(channel_dir / "videos.json", "w", encoding="utf-8") as f:
        json.dump({"videos": videos}, f)
    return channel_dir


def test_get_playlists_channel_not_found(client, temp_data_dir):
    """Missing channel returns error."""
    resp = client.get("/api/playlists?channel_id=nonexistent")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "Channel not found"


def test_get_playlists_cached(client, temp_data_dir):
    """Cached playlists are returned without fetching."""
    channel_id = "UC_test_cached"
    channel_dir = _setup_channel(temp_data_dir, channel_id)
    playlists = [
        {"id": "PL1", "title": "Playlist 1", "video_count": 5, "thumbnail": None},
        {"id": "PL2", "title": "Playlist 2", "video_count": 10, "thumbnail": "http://example.com/pl2.jpg"},
    ]
    with open(channel_dir / "playlists.json", "w", encoding="utf-8") as f:
        json.dump({"playlists": playlists}, f)

    resp = client.get(f"/api/playlists?channel_id={channel_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["channel_id"] == channel_id
    assert len(data["playlists"]) == 2
    assert data["playlists"][0]["id"] == "PL1"
    assert data["playlists"][1]["video_count"] == 10


def test_get_playlists_fetch(client, temp_data_dir):
    """Missing cached playlists triggers fetch and persist."""
    channel_id = "UC_test_fetch"
    _setup_channel(temp_data_dir, channel_id)
    mock_playlists = [
        {"id": "PL1", "title": "Fetched", "video_count": 7, "thumbnail": None},
    ]

    with patch("backend.routes.videos.fetch_channel_playlists", return_value=mock_playlists):
        resp = client.get(f"/api/playlists?channel_id={channel_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["playlists"][0]["id"] == "PL1"

    # Verify persisted to disk
    from backend import storage
    cached = storage.load_playlists(channel_id)
    assert cached is not None
    assert len(cached) == 1
    assert cached[0]["id"] == "PL1"


def test_get_playlist_videos_channel_not_found(client, temp_data_dir):
    """Missing channel returns error for playlist videos."""
    resp = client.get("/api/playlists/videos?channel_id=nonexistent&playlist_id=PL1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "Channel not found"


def test_get_playlist_videos_cached(client, temp_data_dir):
    """Cached playlist video IDs are returned without fetching."""
    channel_id = "UC_test_pl_vids"
    channel_dir = _setup_channel(temp_data_dir, channel_id)
    pl_vids_dir = channel_dir / "playlist_videos"
    pl_vids_dir.mkdir(parents=True, exist_ok=True)
    with open(pl_vids_dir / "PL1.json", "w", encoding="utf-8") as f:
        json.dump({"video_ids": ["v1", "v2", "v3"]}, f)

    resp = client.get(f"/api/playlists/videos?channel_id={channel_id}&playlist_id=PL1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["playlist_id"] == "PL1"
    assert body["data"]["video_ids"] == ["v1", "v2", "v3"]


def test_get_playlist_videos_fetch(client, temp_data_dir):
    """Missing cached playlist videos triggers fetch and persist."""
    channel_id = "UC_test_pl_fetch"
    _setup_channel(temp_data_dir, channel_id)

    with patch("backend.routes.videos.fetch_playlist_video_ids", return_value=["v1", "v2"]):
        resp = client.get(f"/api/playlists/videos?channel_id={channel_id}&playlist_id=PL_new")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["video_ids"] == ["v1", "v2"]

    # Verify persisted
    from backend import storage
    cached = storage.load_playlist_video_ids(channel_id, "PL_new")
    assert cached == ["v1", "v2"]
