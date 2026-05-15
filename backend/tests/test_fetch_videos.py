"""Unit tests for fetch_videos is_short flag."""

import json
from types import SimpleNamespace
from unittest.mock import patch

from backend.pipeline.fetch_videos import (
    _extract_playlist_id,
    _normalize_input,
    _run_ytdlp,
    fetch_channel_shorts,
    fetch_channel_videos,
    fetch_playlist_videos_page,
    fetch_tab_count,
    resolve_channel,
    resolve_playlist,
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
        if any("playlist:%(playlist_count)s" in a for a in args):
            return "1300\n"
        if "--print" in args:
            return "UC123\nCreator Name\nhttps://www.youtube.com/@creator\n"
        return json.dumps({
            "thumbnails": [{"url": "https://example.test/avatar.jpg"}],
            "channel_follower_count": 5_620_000,
        })

    with patch("backend.pipeline.fetch_videos._run_ytdlp", side_effect=fake_run_ytdlp):
        meta = resolve_channel("https://www.youtube.com/@creator")

    assert meta == {
        "kind": "channel",
        "channel_id": "UC123",
        "channel_name": "Creator Name",
        "channel_handle": "creator",
        "channel_url": "https://www.youtube.com/@creator",
        "avatar_url": "https://example.test/avatar.jpg",
        "subscriber_count": 5_620_000,
        "total_video_count": 1300,
        "playlist_id": None,
        "playlist_title": None,
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


def test_normalize_input_rewrites_bare_handle():
    assert _normalize_input("@melrobbins") == "https://www.youtube.com/@melrobbins"
    assert _normalize_input("  @lex.fridman  ") == "https://www.youtube.com/@lex.fridman"


def test_normalize_input_preserves_urls_and_blanks():
    assert _normalize_input("https://www.youtube.com/@x") == "https://www.youtube.com/@x"
    assert _normalize_input("") == ""
    # Bare text without leading @ stays untouched (yt-dlp will fail clearly).
    assert _normalize_input("melrobbins") == "melrobbins"


def test_extract_playlist_id_canonical_url():
    pid = _extract_playlist_id("https://www.youtube.com/playlist?list=PLabc123")
    assert pid == "PLabc123"


def test_extract_playlist_id_in_watch_url():
    pid = _extract_playlist_id(
        "https://www.youtube.com/watch?v=xxx&list=PLabc123&index=2"
    )
    assert pid == "PLabc123"


def test_extract_playlist_id_rejects_radio_mix():
    assert _extract_playlist_id("https://www.youtube.com/watch?v=x&list=RD123") is None


def test_extract_playlist_id_rejects_uploads_playlist():
    # UU... uploads playlists should fall through to channel resolution.
    assert _extract_playlist_id("https://www.youtube.com/playlist?list=UU123") is None


def test_extract_playlist_id_non_youtube_host():
    assert _extract_playlist_id("https://example.com/playlist?list=PLabc") is None


def test_resolve_channel_dispatches_playlist_url():
    """A ``?list=PL...`` URL routes through resolve_playlist (kind=playlist)."""
    info = json.dumps(
        {
            "id": "PLxyz",
            "title": "Best Of Mel",
            "channel_id": "UCmel",
            "channel": "Mel Robbins",
            "channel_url": "https://www.youtube.com/@melrobbins",
            "thumbnails": [{"url": "https://example.test/playlist.jpg"}],
            "playlist_count": 42,
        }
    )

    def fake_run_ytdlp(args):
        if "--dump-single-json" in args:
            return info
        # fetch_playlist_count fallback should not run when playlist_count present.
        return ""

    with patch("backend.pipeline.fetch_videos._run_ytdlp", side_effect=fake_run_ytdlp):
        meta = resolve_channel("https://www.youtube.com/playlist?list=PLxyz")

    assert meta["kind"] == "playlist"
    assert meta["channel_id"] == "PLxyz"
    assert meta["playlist_id"] == "PLxyz"
    assert meta["playlist_title"] == "Best Of Mel"
    assert meta["channel_name"] == "Best Of Mel"
    assert meta["channel_url"] == "https://www.youtube.com/playlist?list=PLxyz"
    assert meta["channel_handle"] == "melrobbins"
    assert meta["owner_channel_id"] == "UCmel"
    assert meta["owner_channel_name"] == "Mel Robbins"
    assert meta["total_video_count"] == 42


def test_resolve_playlist_extracts_owner_from_first_entry():
    """Owner channel info can come from entries[0] when envelope lacks it."""
    info = json.dumps(
        {
            "id": "PLowner",
            "title": "Saved Picks",
            "thumbnails": [],
            "entries": [
                {
                    "id": "vid1",
                    "channel_id": "UCowner",
                    "channel": "Owner Name",
                    "channel_url": "https://www.youtube.com/@ownerhandle",
                }
            ],
        }
    )

    def fake_run_ytdlp(args):
        if "--dump-single-json" in args:
            return info
        if any("playlist:%(playlist_count)s" in a for a in args):
            return "5\n"
        return ""

    with patch("backend.pipeline.fetch_videos._run_ytdlp", side_effect=fake_run_ytdlp):
        meta = resolve_playlist("https://www.youtube.com/playlist?list=PLowner")

    assert meta["owner_channel_id"] == "UCowner"
    assert meta["owner_channel_name"] == "Owner Name"
    assert meta["channel_handle"] == "ownerhandle"
    assert meta["total_video_count"] == 5


def test_fetch_playlist_videos_page_uses_playlist_url():
    calls: list[list[str]] = []
    mock = _mock_stdout([
        {
            "id": "v1",
            "title": "Episode",
            "duration": 600,
            "view_count": 100,
            "upload_date": "20240101",
        },
    ])

    def fake_run_ytdlp(args):
        calls.append(args)
        return mock

    with patch("backend.pipeline.fetch_videos._run_ytdlp", side_effect=fake_run_ytdlp):
        videos, _ = fetch_playlist_videos_page("PLabc", start=1, end=50)

    assert calls[0][-1] == "https://www.youtube.com/playlist?list=PLabc"
    assert "1:50" in calls[0]
    assert videos[0]["is_short"] is False
