"""Unit tests for chat endpoint."""

import json
import os
import tempfile
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
    from backend.auth import CurrentUser, get_current_user
    from backend.main import app

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        owner_id="test-user",
        email="test@example.com",
        role="authenticated",
        claims={"sub": "test-user", "role": "authenticated"},
    )
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
    from backend import storage

    with storage.storage_owner("test-user"):
        storage.write_json(
            storage.get_channel_dir(channel_dir.name) / "profile.json",
            profile,
        )


def _retrieved_source(source_id: str = "S1") -> dict:
    return {
        "source_id": source_id,
        "kind": "chunk",
        "chunk_id": "abc123def45:0001",
        "video_id": "abc123def45",
        "title": "Retrieved Source Video",
        "upload_date": "20231231",
        "start_seconds": 42.8,
        "end_seconds": 86.1,
        "quote": "The retrieved quote grounds the assistant answer.",
        "text": "The retrieved quote grounds the assistant answer with more caption text.",
        "score": 12.4,
    }


def test_build_system_prompt_allows_literal_chart_schema(temp_data_dir):
    """Literal chart schema braces in the template must not be parsed as format fields."""
    channel_id = "UC_test"
    channel_dir = Path(temp_data_dir) / "channels" / channel_id
    _write_profile(channel_dir)

    from backend.pipeline.ask import build_system_prompt

    prompt = build_system_prompt(channel_id)

    assert prompt is not None
    assert "channel_name: Test Channel" in prompt
    assert '{ type:"evolution"' in prompt
    assert "{channel_name}" not in prompt


def test_chat_scope_accepts_camel_case_dates():
    """Frontend-style dateFrom/dateTo fields must populate the backend date filters."""
    from backend.models import ChatScope

    scope = ChatScope.model_validate({"dateFrom": "20230101", "dateTo": "20230630"})

    assert scope.date_from == "20230101"
    assert scope.date_to == "20230630"


def test_chat_rate_limited_returns_envelope(client, temp_data_dir):
    """When the quota store rejects the rate, chat must short-circuit with rate_limited."""
    channel_id = "UC_test"
    channel_dir = Path(temp_data_dir) / "channels" / channel_id
    _write_profile(channel_dir)

    from backend.quotas import Quota
    from backend.routes import chat as chat_module
    from backend.tests.test_quotas import FakeQuotaStore

    blocking_store = FakeQuotaStore(
        quota=Quota(chat_per_minute_limit=5),
        chat_window=5,
    )

    with patch.object(chat_module, "get_quota_store", return_value=blocking_store):
        resp = client.post(
            "/api/chat",
            json={
                "channel_id": channel_id,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "rate_limited"
    assert body["data"]["reason"] == "chat_rate_limit"
    assert body["data"]["limit"] == 5


def test_chat_monthly_quota_limited_returns_envelope(client, temp_data_dir):
    """When monthly chat quota is exhausted, chat must short-circuit before streaming."""
    channel_id = "UC_test"
    channel_dir = Path(temp_data_dir) / "channels" / channel_id
    _write_profile(channel_dir)

    from backend.quotas import MonthlyUsage, Quota
    from backend.routes import chat as chat_module
    from backend.tests.test_quotas import FakeQuotaStore

    blocking_store = FakeQuotaStore(
        quota=Quota(monthly_chat_messages=1),
        usage=MonthlyUsage(chat_messages=1),
    )

    with patch.object(chat_module, "get_quota_store", return_value=blocking_store):
        resp = client.post(
            "/api/chat",
            json={
                "channel_id": channel_id,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "quota_exceeded"
    assert body["data"]["reason"] == "monthly_chat_message_limit"
    assert body["data"]["monthly_chat_messages"] == 1


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


def test_chat_session_crud_routes(client, temp_data_dir):
    """Users can create, list, rename, load, and delete channel chat sessions."""
    channel_id = "UC_chat_sessions"
    from backend import storage

    storage.save_channel_meta(
        channel_id,
        {"channel_id": channel_id, "channel_name": "Session Channel"},
        owner_id="test-user",
    )

    created = client.post(
        f"/api/channels/{channel_id}/chat-sessions",
        json={"title": "First thread"},
    ).json()
    assert created["ok"] is True
    session_id = created["data"]["id"]
    assert created["data"]["title"] == "First thread"

    listed = client.get(f"/api/channels/{channel_id}/chat-sessions").json()
    assert listed["data"]["sessions"][0]["id"] == session_id

    renamed = client.patch(
        f"/api/channels/{channel_id}/chat-sessions/{session_id}",
        json={"title": "Renamed thread"},
    ).json()
    assert renamed["data"]["title"] == "Renamed thread"

    detail = client.get(f"/api/channels/{channel_id}/chat-sessions/{session_id}").json()
    assert detail["ok"] is True
    assert detail["data"]["session"]["id"] == session_id
    assert detail["data"]["messages"] == []

    deleted = client.delete(f"/api/channels/{channel_id}/chat-sessions/{session_id}").json()
    assert deleted == {"ok": True, "data": {"id": session_id, "deleted": True}, "error": None}


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
    data_lines = [line for line in lines if line.startswith("data: ")]
    frames = [json.loads(line.removeprefix("data: ")) for line in data_lines]

    deltas = [f for f in frames if f["type"] == "delta"]
    dones = [f for f in frames if f["type"] == "done"]

    assert len(deltas) == 1
    assert deltas[0]["text"] == "Hello"
    assert len(dones) == 1


@pytest.mark.asyncio
async def test_chat_sends_source_registry_before_deltas(client, temp_data_dir):
    """The chat stream should send backend-owned citation metadata before text."""
    channel_id = "UC_test"
    channel_dir = Path(temp_data_dir) / "channels" / channel_id
    _write_profile(channel_dir)

    mock_delta = MagicMock()
    mock_delta.text = "Answer with [S1]."
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

    with (
        patch(
            "backend.pipeline.chat_context.retrieve_with_coverage",
            return_value=([_retrieved_source()], {}),
        ),
        patch("backend.pipeline.ask.AsyncAnthropic", return_value=mock_client),
    ):
        resp = client.post(
            "/api/chat",
            json={
                "channel_id": channel_id,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 200
    frames = [
        json.loads(line.removeprefix("data: "))
        for line in resp.text.split("\n")
        if line.startswith("data: ")
    ]

    assert frames[0]["type"] == "session"
    assert frames[1]["type"] == "sources"
    assert frames[1]["sources"] == [
        {
            "source_id": "S1",
            "kind": "chunk",
            "chunk_id": "abc123def45:0001",
            "video_id": "abc123def45",
            "title": "Retrieved Source Video",
            "upload_date": "20231231",
            "start_seconds": 42,
            "end_seconds": 86,
            "quote": "The retrieved quote grounds the assistant answer.",
        }
    ]
    assert "text" not in frames[1]["sources"][0]
    assert frames[2] == {"type": "delta", "text": "Answer with [S1]."}
    assert frames[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_chat_warns_about_unknown_registry_citations(client, temp_data_dir):
    """Unknown [S99] markers should be reported without breaking done frames."""
    channel_id = "UC_test"
    channel_dir = Path(temp_data_dir) / "channels" / channel_id
    _write_profile(channel_dir)

    mock_delta = MagicMock()
    mock_delta.text = "Known [S1], unknown [S99]."
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

    with (
        patch(
            "backend.pipeline.chat_context.retrieve_with_coverage",
            return_value=([_retrieved_source()], {}),
        ),
        patch("backend.pipeline.ask.AsyncAnthropic", return_value=mock_client),
    ):
        resp = client.post(
            "/api/chat",
            json={
                "channel_id": channel_id,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert resp.status_code == 200
    frames = [
        json.loads(line.removeprefix("data: "))
        for line in resp.text.split("\n")
        if line.startswith("data: ")
    ]
    warning = next(frame for frame in frames if frame["type"] == "citation_warning")

    assert warning == {"type": "citation_warning", "unknown_source_ids": ["S99"]}
    assert frames[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_chat_camel_case_date_scope_filters_prompt(client, temp_data_dir):
    """A camelCase date scope should be reflected without sending full profile videos."""
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
                "messages": [{"role": "user", "content": "what changed recently?"}],
                "scope": {"dateFrom": "20231201"},
            },
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    system = mock_client.messages.stream.call_args.kwargs["system"]
    assert (
        "active_scope: restricted to 1 of 2 profile videos matching dates=20231201..end"
        in system
    )
    assert '"video_id":"v2"' not in system
    assert '"video_id":"v1"' not in system


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
    data_lines = [line for line in lines if line.startswith("data: ")]
    frames = [json.loads(line.removeprefix("data: ")) for line in data_lines]

    # Should only see the done frame, no delta for reasoning_content
    assert all("reasoning_content" not in json.dumps(f) for f in frames)
    assert any(f["type"] == "done" for f in frames)
    assert not any(f.get("type") == "delta" for f in frames)


@pytest.mark.asyncio
async def test_chat_persists_session_messages_and_sources(client, temp_data_dir):
    """A streamed chat request should save the user and final assistant messages."""
    channel_id = "UC_test"
    channel_dir = Path(temp_data_dir) / "channels" / channel_id
    _write_profile(channel_dir)

    mock_delta = MagicMock()
    mock_delta.text = "Answer with [S1]."
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

    with (
        patch(
            "backend.pipeline.chat_context.retrieve_with_coverage",
            return_value=([_retrieved_source()], {}),
        ),
        patch("backend.pipeline.ask.AsyncAnthropic", return_value=mock_client),
    ):
        resp = client.post(
            "/api/chat",
            json={
                "channel_id": channel_id,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    frames = [
        json.loads(line.removeprefix("data: "))
        for line in resp.text.split("\n")
        if line.startswith("data: ")
    ]
    session_id = frames[0]["session"]["id"]

    from backend import storage

    detail = storage.load_chat_session(channel_id, session_id, owner_id="test-user")
    assert detail is not None
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][0]["content"] == "hi"
    assert detail["messages"][1]["content"] == "Answer with [S1]."
    assert detail["messages"][1]["sources"][0]["source_id"] == "S1"
