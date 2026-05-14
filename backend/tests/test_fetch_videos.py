"""Unit tests for fetch_videos is_short flag."""

import json
from types import SimpleNamespace
from unittest.mock import patch

from backend.pipeline.fetch_videos import (
    _run_ytdlp,
    fetch_channel_shorts,
    fetch_channel_videos,
    fetch_tab_count,
    resolve_channel,
)


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


def test_fetch_channel_videos_uses_videos_tab():
    calls: list[list[str]] = []
    mock = _mock_stdout([
        {
            "id": "v1",
            "title": "Video",
            "duration": 300,
            "view_count": 10,
            "upload_date": "20230101",
        },
    ])

    def fake_run_ytdlp(args):
        calls.append(args)
        return mock

    with patch("backend.pipeline.fetch_videos._run_ytdlp", side_effect=fake_run_ytdlp):
        fetch_channel_videos("https://www.youtube.com/@creator")

    assert calls[0][-1] == "https://www.youtube.com/@creator/videos"


def test_fetch_channel_videos_pagination_range():
    """Pagination passes the --playlist-items range to yt-dlp."""
    calls: list[list[str]] = []

    def fake_run_ytdlp(args):
        calls.append(args)
        return ""

    with patch("backend.pipeline.fetch_videos._run_ytdlp", side_effect=fake_run_ytdlp):
        fetch_channel_videos(
            "https://www.youtube.com/@creator", start=51, end=100
        )
    assert "51:100" in calls[0]


def test_fetch_channel_shorts_uses_shorts_tab_and_marks_short():
    mock = _mock_stdout([
        {"id": "s1", "title": "Short clip", "upload_date": "20230101"},
    ])
    calls: list[list[str]] = []

    def fake_run_ytdlp(args):
        calls.append(args)
        return mock

    with patch("backend.pipeline.fetch_videos._run_ytdlp", side_effect=fake_run_ytdlp):
        shorts = fetch_channel_shorts("https://www.youtube.com/@creator")

    assert calls[0][-1] == "https://www.youtube.com/@creator/shorts"
    assert shorts[0]["is_short"] is True


def test_fetch_tab_count_parses_playlist_count():
    with patch(
        "backend.pipeline.fetch_videos._run_ytdlp", return_value="123\n"
    ):
        assert fetch_tab_count("https://www.youtube.com/@x/videos") == 123


def test_fetch_tab_count_zero_on_failure():
    def boom(_args):
        raise RuntimeError("nope")

    with patch("backend.pipeline.fetch_videos._run_ytdlp", side_effect=boom):
        assert fetch_tab_count("https://www.youtube.com/@x/videos") == 0


def test_run_ytdlp_uses_fast_flat_command_without_cookies():
    """yt-dlp should run with the base fast options only."""
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
        "--dump-json",
        "https://www.youtube.com/@test",
    ]


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
        "channel_url": "https://www.youtube.com/@creator",
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
    assert meta["channel_handle"] == "david.fragomeni"
    assert calls[1] == [
        "--flat-playlist",
        "--dump-single-json",
        "--playlist-items",
        "1",
        "https://www.youtube.com/@david.fragomeni",
    ]
