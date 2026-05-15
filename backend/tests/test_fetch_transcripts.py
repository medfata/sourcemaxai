"""Tests for transcript fetching behavior."""

from __future__ import annotations

from backend.pipeline import fetch_transcripts as fetch_transcripts_module
from backend.pipeline.proxy_pool import ProxyConfig
from youtube_transcript_api import IpBlocked, RequestBlocked, TranscriptsDisabled


class _FakeProxyPool:
    def __init__(self):
        self.acquire_calls: list[tuple[str, int]] = []
        self.mark_blocked_calls: list[tuple] = []
        self._sessions = iter(["sess1", "sess2", "sess3", "sess4", "sess5"])

    def acquire(self, video_id, attempt):
        self.acquire_calls.append((video_id, attempt))
        provider = ProxyConfig(
            name="iproyal",
            host="h:1",
            username="u",
            password="p",
            session_param="session",
            rotate_per_request=False,
        )
        return provider, next(self._sessions, "sessX")

    def mark_blocked(self, provider, session_id, reason):
        self.mark_blocked_calls.append((provider.name, session_id, reason))

    def proxy_url(self, provider, session_id):
        return "http://u:p@h:1"


class _FakeTranscriptList:
    """Stub standing in for youtube_transcript_api.TranscriptList."""


def test_fetch_with_retry_retries_on_ip_blocked(monkeypatch):
    video_id = "vid_ip_blocked"
    pool = _FakeProxyPool()
    call_count = 0

    def fake_list(self, _video_id):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise IpBlocked("IP blocked")
        return _FakeTranscriptList()

    monkeypatch.setattr(
        fetch_transcripts_module.YouTubeTranscriptApi, "list", fake_list
    )

    result = fetch_transcripts_module.fetch_with_retry(
        video_id, pool=pool, max_attempts=5
    )

    assert isinstance(result, _FakeTranscriptList)
    assert call_count == 3
    assert len(pool.acquire_calls) == 3
    assert pool.acquire_calls == [(video_id, 1), (video_id, 2), (video_id, 3)]
    assert len(pool.mark_blocked_calls) == 2
    assert pool.mark_blocked_calls[0][0] == "iproyal"
    assert pool.mark_blocked_calls[0][1] == "sess1"
    assert pool.mark_blocked_calls[1][0] == "iproyal"
    assert pool.mark_blocked_calls[1][1] == "sess2"


def test_fetch_with_retry_retries_on_request_blocked(monkeypatch):
    video_id = "vid_req_blocked"
    pool = _FakeProxyPool()
    call_count = 0

    def fake_list(self, _video_id):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RequestBlocked("Request blocked")
        return _FakeTranscriptList()

    monkeypatch.setattr(
        fetch_transcripts_module.YouTubeTranscriptApi, "list", fake_list
    )

    result = fetch_transcripts_module.fetch_with_retry(
        video_id, pool=pool, max_attempts=5
    )

    assert isinstance(result, _FakeTranscriptList)
    assert call_count == 3
    assert len(pool.acquire_calls) == 3
    assert len(pool.mark_blocked_calls) == 2


def test_fetch_with_retry_all_proxies_blocked(monkeypatch):
    video_id = "vid_all_blocked"
    pool = _FakeProxyPool()

    def fake_list(self, _video_id):
        raise IpBlocked("IP blocked")

    monkeypatch.setattr(
        fetch_transcripts_module.YouTubeTranscriptApi, "list", fake_list
    )

    result = fetch_transcripts_module.fetch_with_retry(
        video_id, pool=pool, max_attempts=3
    )

    assert isinstance(result, dict)
    assert result["status"] == "failed"
    assert result["error"] == "all_proxies_blocked"
    assert len(pool.acquire_calls) == 3
    assert len(pool.mark_blocked_calls) == 3


def test_fetch_with_retry_no_retry_on_transcripts_disabled(monkeypatch):
    video_id = "vid_disabled"
    pool = _FakeProxyPool()

    def fake_list(self, _video_id):
        raise TranscriptsDisabled("Transcripts disabled")

    monkeypatch.setattr(
        fetch_transcripts_module.YouTubeTranscriptApi, "list", fake_list
    )

    result = fetch_transcripts_module.fetch_with_retry(
        video_id, pool=pool, max_attempts=5
    )

    assert isinstance(result, dict)
    assert result["status"] == "unavailable"
    assert result["video_id"] == video_id
    assert len(pool.acquire_calls) == 1
    assert len(pool.mark_blocked_calls) == 0


def test_fetch_transcripts_uses_parallel_worker_pattern(monkeypatch, tmp_path):
    channel_id = "UC_transcript_block"
    calls: list[str] = []
    progress: list[dict] = []

    monkeypatch.setattr(fetch_transcripts_module, "WORKERS", 8)
    monkeypatch.setattr(fetch_transcripts_module, "load_selection", lambda _channel_id: [
        "vid_0",
        "vid_1",
        "vid_2",
    ])
    monkeypatch.setattr(fetch_transcripts_module, "load_videos", lambda _channel_id: [
        {"id": "vid_0", "title": "Video 0"},
        {"id": "vid_1", "title": "Video 1"},
        {"id": "vid_2", "title": "Video 2"},
    ])
    monkeypatch.setattr(fetch_transcripts_module, "get_channel_dir", lambda _channel_id: tmp_path)

    def fake_fetch_single(vid, *_args, **_kwargs):
        calls.append(vid)
        return {"video_id": vid, "status": "done"}

    monkeypatch.setattr(fetch_transcripts_module, "fetch_single_transcript", fake_fetch_single)

    result = fetch_transcripts_module.fetch_transcripts(channel_id, on_progress=progress.append)

    assert set(calls) == {"vid_0", "vid_1", "vid_2"}
    assert result["total"] == 3
    assert {item["video_id"] for item in result["results"]} == {"vid_0", "vid_1", "vid_2"}
    assert all(item["status"] == "done" for item in result["results"])
    assert {item["video_id"] for item in progress} == {"vid_0", "vid_1", "vid_2"}
