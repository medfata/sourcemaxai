"""Unit tests for fetch_videos is_short flag."""

import base64
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from backend.pipeline import fetch_videos as fetch_videos_module
from backend.pipeline.fetch_videos import _run_ytdlp, fetch_channel_videos, resolve_channel


def _mock_stdout(videos: list[dict]) -> str:
    return "\n".join(json.dumps(v) for v in videos)


def test_is_short_true_for_duration_45():
    """duration=45 => is_short=True"""
    mock = _mock_stdout([
        {"id": "v1", "title": "Short", "duration": 45, "view_count": 10, "upload_date": "20230101"},
    ])
    with patch("backend.pipeline.fetch_videos._run_ytdlp", return_value=mock):
        videos = fetch_channel_videos("https://www.youtube.com/@test")
    assert len(videos) == 1
    assert videos[0]["is_short"] is True


def test_is_short_false_for_duration_300():
    """duration=300 => is_short=False"""
    mock = _mock_stdout([
        {"id": "v1", "title": "Long", "duration": 300, "view_count": 10, "upload_date": "20230101"},
    ])
    with patch("backend.pipeline.fetch_videos._run_ytdlp", return_value=mock):
        videos = fetch_channel_videos("https://www.youtube.com/@test")
    assert len(videos) == 1
    assert videos[0]["is_short"] is False


def test_is_short_false_for_duration_0():
    """duration=0 => is_short=False"""
    mock = _mock_stdout([
        {"id": "v1", "title": "Zero", "duration": 0, "view_count": 10, "upload_date": "20230101"},
    ])
    with patch("backend.pipeline.fetch_videos._run_ytdlp", return_value=mock):
        videos = fetch_channel_videos("https://www.youtube.com/@test")
    assert len(videos) == 1
    assert videos[0]["is_short"] is False


def test_is_short_false_for_missing_duration():
    """duration missing => is_short=False"""
    mock = _mock_stdout([
        {"id": "v1", "title": "No duration", "view_count": 10, "upload_date": "20230101"},
    ])
    with patch("backend.pipeline.fetch_videos._run_ytdlp", return_value=mock):
        videos = fetch_channel_videos("https://www.youtube.com/@test")
    assert len(videos) == 1
    assert videos[0]["is_short"] is False


def test_is_short_true_for_duration_60():
    """duration=60 => is_short=True (60 <= 60 is inclusive)"""
    mock = _mock_stdout([
        {"id": "v1", "title": "Edge", "duration": 60, "view_count": 10, "upload_date": "20230101"},
    ])
    with patch("backend.pipeline.fetch_videos._run_ytdlp", return_value=mock):
        videos = fetch_channel_videos("https://www.youtube.com/@test")
    assert len(videos) == 1
    assert videos[0]["is_short"] is True


def test_is_short_false_for_duration_61():
    """duration=61 => is_short=False"""
    mock = _mock_stdout([
        {
            "id": "v1",
            "title": "Too long",
            "duration": 61,
            "view_count": 10,
            "upload_date": "20230101",
        },
    ])
    with patch("backend.pipeline.fetch_videos._run_ytdlp", return_value=mock):
        videos = fetch_channel_videos("https://www.youtube.com/@test")
    assert len(videos) == 1
    assert videos[0]["is_short"] is False


def test_is_short_true_for_duration_1():
    """duration=1 => is_short=True"""
    mock = _mock_stdout([
        {"id": "v1", "title": "Second", "duration": 1, "view_count": 10, "upload_date": "20230101"},
    ])
    with patch("backend.pipeline.fetch_videos._run_ytdlp", return_value=mock):
        videos = fetch_channel_videos("https://www.youtube.com/@test")
    assert len(videos) == 1
    assert videos[0]["is_short"] is True


def test_run_ytdlp_uses_cookie_file_path(monkeypatch):
    """YTDLP_COOKIES_PATH is passed directly to yt-dlp."""
    monkeypatch.setenv("YTDLP_COOKIES_PATH", "/secrets/youtube-cookies.txt")
    monkeypatch.delenv("YTDLP_COOKIES_B64", raising=False)
    calls: dict[str, list[str]] = {}

    def fake_run(cmd, **_kwargs):
        calls["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    with patch("backend.pipeline.fetch_videos.subprocess.run", side_effect=fake_run):
        assert _run_ytdlp(["--dump-json", "https://www.youtube.com/@test"]) == "ok"

    assert calls["cmd"] == [
        "python",
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--no-warnings",
        "--no-check-certificates",
        "--cookies",
        "/secrets/youtube-cookies.txt",
        "--dump-json",
        "https://www.youtube.com/@test",
    ]


def test_run_ytdlp_decodes_base64_cookies_to_temp_file(monkeypatch, tmp_path):
    """YTDLP_COOKIES_B64 is decoded into a runtime cookies file."""
    cookies = "# Netscape HTTP Cookie File\r\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tvalue"
    monkeypatch.delenv("YTDLP_COOKIES_PATH", raising=False)
    encoded = base64.b64encode(cookies.encode("utf-8")).decode("ascii")
    monkeypatch.setenv("YTDLP_COOKIES_B64", f"{encoded[:24]}\n{encoded[24:]}")
    monkeypatch.setattr(fetch_videos_module.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(fetch_videos_module, "_RUNTIME_COOKIE_FILE", None)
    monkeypatch.setattr(fetch_videos_module, "_RUNTIME_COOKIE_SOURCE", None)
    calls: dict[str, list[str]] = {}

    def fake_run(cmd, **_kwargs):
        calls["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    with patch("backend.pipeline.fetch_videos.subprocess.run", side_effect=fake_run):
        assert _run_ytdlp(["--print", "%(id)s", "https://www.youtube.com/@test"]) == "ok"

    cookie_index = calls["cmd"].index("--cookies") + 1
    cookie_path = tmp_path / "trace-ytdlp-cookies.txt"
    assert calls["cmd"][cookie_index] == str(cookie_path)
    assert cookie_path.read_text(encoding="utf-8") == (
        "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tvalue\n"
    )


def test_resolve_channel_uses_flat_playlist_for_metadata():
    """Channel metadata resolution must not inspect a video's downloadable formats."""
    calls: list[list[str]] = []

    def fake_run_ytdlp(args):
        calls.append(args)
        if "--print" in args:
            return "UC123\nCreator Name\nhttps://www.youtube.com/@creator\n"
        return json.dumps({"thumbnails": [{"url": "https://example.test/avatar.jpg"}]})

    with patch("backend.pipeline.fetch_videos._run_ytdlp", side_effect=fake_run_ytdlp):
        meta = resolve_channel("https://www.youtube.com/@creator")

    assert meta == {
        "channel_id": "UC123",
        "channel_name": "Creator Name",
        "channel_handle": "creator",
        "avatar_url": "https://example.test/avatar.jpg",
    }
    assert calls[0] == [
        "--flat-playlist",
        "--skip-download",
        "--print",
        "%(channel_id)s",
        "--print",
        "%(channel)s",
        "--print",
        "%(channel_url)s",
        "--playlist-items",
        "1",
        "https://www.youtube.com/@creator",
    ]


def test_resolve_channel_falls_back_when_ytdlp_prints_na():
    """yt-dlp can emit NA for flat channel fields; do not persist that as an id."""
    calls: list[list[str]] = []

    def fake_run_ytdlp(args):
        calls.append(args)
        if "--print" in args:
            return "NA\nDavid Fragomeni\nNA\n"
        if "--dump-single-json" in args:
            return json.dumps(
                {
                    "id": "UCkcBDNWKUSczL9TIx-7h6Qw",
                    "title": "David Fragomeni",
                    "channel_url": "https://www.youtube.com/channel/UCkcBDNWKUSczL9TIx-7h6Qw",
                    "thumbnails": [{"url": "https://example.test/channel.jpg"}],
                }
            )
        return json.dumps({"thumbnails": [{"url": "https://example.test/avatar.jpg"}]})

    with patch("backend.pipeline.fetch_videos._run_ytdlp", side_effect=fake_run_ytdlp):
        meta = resolve_channel("https://www.youtube.com/@david.fragomeni")

    assert meta["channel_id"] == "UCkcBDNWKUSczL9TIx-7h6Qw"
    assert meta["channel_name"] == "David Fragomeni"
    assert calls[1] == [
        "--flat-playlist",
        "--dump-single-json",
        "--playlist-items",
        "1",
        "https://www.youtube.com/@david.fragomeni",
    ]


def test_run_ytdlp_rejects_invalid_base64_cookies(monkeypatch):
    """Bad cookie env values fail before spawning yt-dlp."""
    monkeypatch.delenv("YTDLP_COOKIES_PATH", raising=False)
    monkeypatch.setenv("YTDLP_COOKIES_B64", "not base64")

    with pytest.raises(RuntimeError, match="YTDLP_COOKIES_B64"):
        _run_ytdlp(["https://www.youtube.com/@test"])
