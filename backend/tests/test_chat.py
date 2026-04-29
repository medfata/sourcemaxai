"""Unit tests for chat endpoint."""

import json
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


class _AsyncIter:
    """Turn a list into an async iterator for mock streams."""

    def __init__(self, items):
        self._items = items
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._idx]
        self._idx += 1
        return item


@pytest.fixture
def client():
    """Create a TestClient with a fresh app import."""
    from backend.main import app

    return TestClient(app)


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


def _write_profile(channel_dir: Path, channel_name: str = "Test Channel"):
    channel_dir.mkdir(parents=True, exist_ok=True)
    profile = {
        "channel_id": channel_dir.name,
        "channel_name": channel_name,
        "video_count": 2,
        "date_range": {"first": "20230101", "last": "20231231"},
        "videos": [
            {
                "video_id": "v1",
                "title": "Video 1",
                "upload_date": "20230101",
                "core_topic": "topic1",
                "key_claims": ["claim1"],
                "recurring_themes": ["AI"],
                "tone_markers": ["analytical"],
                "notable_opinions": ["op1"],
                "people_or_things_referenced": ["OpenAI"],
            },
            {
                "video_id": "v2",
                "title": "Video 2",
                "upload_date": "20231231",
                "core_topic": "topic2",
                "key_claims": ["claim2"],
                "recurring_themes": ["ML"],
                "tone_markers": ["enthusiastic"],
                "notable_opinions": ["op2"],
                "people_or_things_referenced": ["Google"],
            },
        ],
        "rollups": {
            "all_themes": [],
            "all_referenced": [],
            "tone_distribution": {},
        },
        "generated_at": "2024-01-01T00:00:00",
    }
    with open(channel_dir / "profile.json", "w", encoding="utf-8") as f:
        json.dump(profile, f)


def test_chat_profile_not_found(client):
    """Missing profile should return a 200-style ApiResponse with ok=False (not an SSE stream)."""
    resp = client.post(
        "/api/chat",
        json={
            "channel_id": "UC_missing",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "profile_not_found"


def test_chat_empty_messages(client, temp_data_dir):
    channel_id = "UC_test"
    channel_dir = Path(temp_data_dir) / "channels" / channel_id
    _write_profile(channel_dir)

    resp = client.post(
        "/api/chat",
        json={"channel_id": channel_id, "messages": []},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False


def test_chat_invalid_role(client, temp_data_dir):
    channel_id = "UC_test"
    channel_dir = Path(temp_data_dir) / "channels" / channel_id
    _write_profile(channel_dir)

    resp = client.post(
        "/api/chat",
        json={
            "channel_id": channel_id,
            "messages": [{"role": "system", "content": "hello"}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False


@pytest.mark.asyncio
async def test_chat_text_delta_forwarded(client, temp_data_dir):
    """text_delta chunks should be forwarded as SSE data: {"type":"delta","text":"..."}."""
    channel_id = "UC_test"
    channel_dir = Path(temp_data_dir) / "channels" / channel_id
    _write_profile(channel_dir)

    # Build a mock AsyncAnthropic / stream context manager
    mock_delta = MagicMock()
    mock_delta.text = "Hello"
    mock_event = MagicMock()
    mock_event.type = "content_block_delta"
    mock_event.delta = mock_delta

    mock_stream = MagicMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=False)
    mock_stream.__aiter__ = lambda self: _AsyncIter([mock_event])

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.stream = MagicMock(return_value=mock_stream)

    with patch("backend.pipeline.ask.AsyncAnthropic", return_value=mock_client):
        resp = client.post(
            "/api/chat",
            json={
                "channel_id": channel_id,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    lines = resp.text.split("\n")
    data_lines = [l for l in lines if l.startswith("data: ")]
    frames = [json.loads(l.removeprefix("data: ")) for l in data_lines]

    deltas = [f for f in frames if f["type"] == "delta"]
    dones = [f for f in frames if f["type"] == "done"]

    assert len(deltas) == 1
    assert deltas[0]["text"] == "Hello"
    assert len(dones) == 1


@pytest.mark.asyncio
async def test_chat_accepts_multi_turn(client, temp_data_dir):
    """A realistic multi-turn conversation (user + assistant + user) must be accepted."""
    channel_id = "UC_test"
    channel_dir = Path(temp_data_dir) / "channels" / channel_id
    _write_profile(channel_dir)

    mock_stream = MagicMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=False)
    mock_stream.__aiter__ = lambda self: _AsyncIter([])

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.stream = MagicMock(return_value=mock_stream)

    with patch("backend.pipeline.ask.AsyncAnthropic", return_value=mock_client):
        resp = client.post(
            "/api/chat",
            json={
                "channel_id": channel_id,
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "Hello!"},
                    {"role": "user", "content": "what's up"},
                ],
            },
        )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")


@pytest.mark.asyncio
async def test_chat_accepts_trailing_empty_assistant(client, temp_data_dir):
    """The frontend may send a trailing empty assistant placeholder; it must be accepted."""
    channel_id = "UC_test"
    channel_dir = Path(temp_data_dir) / "channels" / channel_id
    _write_profile(channel_dir)

    mock_stream = MagicMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=False)
    mock_stream.__aiter__ = lambda self: _AsyncIter([])

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.stream = MagicMock(return_value=mock_stream)

    with patch("backend.pipeline.ask.AsyncAnthropic", return_value=mock_client):
        resp = client.post(
            "/api/chat",
            json={
                "channel_id": channel_id,
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": ""},
                ],
            },
        )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")


@pytest.mark.asyncio
async def test_chat_reasoning_content_dropped(client, temp_data_dir):
    """Any reasoning_content delta must be dropped and NOT forwarded to the client."""
    channel_id = "UC_test"
    channel_dir = Path(temp_data_dir) / "channels" / channel_id
    _write_profile(channel_dir)

    mock_reasoning = MagicMock()
    mock_reasoning.text = None
    mock_reasoning.reasoning_content = "some secret reasoning"
    mock_event = MagicMock()
    mock_event.type = "content_block_delta"
    mock_event.delta = mock_reasoning

    mock_stream = MagicMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=False)
    mock_stream.__aiter__ = lambda self: _AsyncIter([mock_event])

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.stream = MagicMock(return_value=mock_stream)

    with patch("backend.pipeline.ask.AsyncAnthropic", return_value=mock_client):
        resp = client.post(
            "/api/chat",
            json={
                "channel_id": channel_id,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert resp.status_code == 200
    lines = resp.text.split("\n")
    data_lines = [l for l in lines if l.startswith("data: ")]
    frames = [json.loads(l.removeprefix("data: ")) for l in data_lines]

    # Should only see the done frame, no delta for reasoning_content
    assert all("reasoning_content" not in json.dumps(f) for f in frames)
    assert any(f["type"] == "done" for f in frames)
    assert not any(f.get("type") == "delta" for f in frames)
