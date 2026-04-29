"""Tests for pipeline routes and selection cap behavior."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def temp_data_dir(monkeypatch):
    """Use a temporary directory for DATA_DIR and set a fake API key."""
    with tempfile.TemporaryDirectory() as tmpdir:
        old = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = tmpdir
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        # Reload storage so module-level DATA_DIR picks up the new env var
        import importlib
        from backend import storage
        importlib.reload(storage)
        yield tmpdir
        if old is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = old


@pytest.fixture
def client():
    """Create a TestClient with freshly-reloaded route modules."""
    import importlib

    from backend import storage
    from backend.routes import (
        channel as channel_mod,
        chat as chat_mod,
        pipeline as pipeline_mod,
        profile as profile_mod,
        videos as videos_mod,
    )

    importlib.reload(channel_mod)
    importlib.reload(chat_mod)
    importlib.reload(pipeline_mod)
    importlib.reload(profile_mod)
    importlib.reload(videos_mod)

    # Patch reloaded storage helpers into pipeline so they use the temp dir
    pipeline_mod.get_channel_dir = storage.get_channel_dir
    pipeline_mod.load_selection = storage.load_selection
    pipeline_mod.load_videos = storage.load_videos
    pipeline_mod.read_json = storage.read_json
    pipeline_mod.write_json = storage.write_json

    # Patch videos module too
    videos_mod.load_channel_meta = storage.load_channel_meta
    videos_mod.load_selection = storage.load_selection
    videos_mod.save_selection = storage.save_selection
    videos_mod.load_videos = storage.load_videos

    import backend.main as main_mod
    importlib.reload(main_mod)

    return TestClient(main_mod.app)


def _setup_channel(channel_id: str, video_count: int = 5):
    from backend import storage

    channel_dir = storage.get_channel_dir(channel_id)
    channel_dir.mkdir(parents=True, exist_ok=True)
    storage.write_json(
        channel_dir / "meta.json",
        {
            "channel_id": channel_id,
            "channel_name": "Test Channel",
            "channel_handle": "@test",
            "avatar_url": "http://example.com/avatar.jpg",
        },
    )
    videos = [
        {
            "id": f"vid_{i}",
            "title": f"Video {i}",
            "upload_date": "20230101",
            "duration": 60,
            "view_count": 100,
            "thumbnail": "http://example.com/thumb.jpg",
        }
        for i in range(video_count)
    ]
    storage.write_json(channel_dir / "videos.json", {"videos": videos})
    return [v["id"] for v in videos]


def test_select_301_videos_allowed(client):
    """Backend must allow >300 selections; cap is frontend-only warning."""
    from backend import storage

    channel_id = "UC_test_cap"
    video_ids = _setup_channel(channel_id, video_count=301)

    resp = client.post(
        "/api/videos/select",
        json={"channel_id": channel_id, "video_ids": video_ids},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["video_ids"]) == 301

    sel = storage.load_selection(channel_id)
    assert len(sel) == 301


def test_cancel_terminates_running_task(client):
    """Cancel endpoint should cancel the running task and update state."""
    from backend import storage
    from backend.routes import pipeline as pipeline_module

    channel_id = "UC_test_cancel"
    _setup_channel(channel_id, video_count=5)
    storage.save_selection(channel_id, [f"vid_{i}" for i in range(5)])

    # Inject a mock running task
    mock_task = MagicMock()
    mock_task.done.return_value = False
    pipeline_module.running_tasks[channel_id] = mock_task

    resp = client.post(
        "/api/pipeline/cancel",
        json={"channel_id": channel_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "cancelled"

    mock_task.cancel.assert_called_once()

    state = pipeline_module._read_pipeline_state(channel_id)
    assert state["status"] == "cancelled"

    # Clean up
    pipeline_module.running_tasks.pop(channel_id, None)


def test_resume_requires_awaiting_confirm_summaries_state(client):
    """Resume must fail unless pipeline is in awaiting_confirm_summaries state."""
    from backend import storage
    from backend.routes import pipeline as pipeline_module

    channel_id = "UC_test_resume"
    _setup_channel(channel_id, video_count=5)

    # Without proper state, resume should fail
    resp = client.post(
        "/api/pipeline/resume",
        json={"channel_id": channel_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "not awaiting confirmation" in body["error"]

    # Set up the correct state
    pipeline_module._write_pipeline_state(
        channel_id,
        {
            "status": "awaiting_confirm_summaries",
            "current_stage": "awaiting_confirm_summaries",
            "stages": {"transcripts": {"status": "done"}},
        },
    )

    async def fake_run(*args, **kwargs):
        pass

    with patch.object(pipeline_module, "_run_pipeline", fake_run):
        resp = client.post(
            "/api/pipeline/resume",
            json={"channel_id": channel_id},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "resumed"

    # Clean up
    pipeline_module.running_tasks.pop(channel_id, None)


def test_start_returns_api_response_envelope(client):
    """POST /api/pipeline/start must return an ApiResponse envelope."""
    from backend import storage
    from backend.routes import pipeline as pipeline_module

    channel_id = "UC_test_start"
    _setup_channel(channel_id, video_count=3)
    storage.save_selection(channel_id, [f"vid_{i}" for i in range(3)])

    async def fake_run(*args, **kwargs):
        pass

    with patch.object(pipeline_module, "_run_pipeline", fake_run):
        resp = client.post(
            "/api/pipeline/start",
            json={"channel_id": channel_id},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["channel_id"] == channel_id
        assert body["data"]["status"] == "started"

    # Clean up
    pipeline_module.running_tasks.pop(channel_id, None)
