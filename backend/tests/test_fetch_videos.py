"""Unit tests for fetch_videos is_short flag."""

import json
from unittest.mock import patch

from backend.pipeline.fetch_videos import fetch_channel_videos


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
        {"id": "v1", "title": "Too long", "duration": 61, "view_count": 10, "upload_date": "20230101"},
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
