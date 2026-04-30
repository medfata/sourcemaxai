import pytest
from backend.pipeline.ask import filter_videos
from backend.models import ChatScope


def test_filter_videos_no_scope():
    """When scope is None, all videos are returned."""
    videos = [
        {"video_id": "v1", "recurring_themes": ["ai", "tech"], "tone_markers": ["analytical"], "upload_date": "20240101"},
        {"video_id": "v2", "recurring_themes": ["productivity"], "tone_markers": ["energetic"], "upload_date": "20240201"},
    ]
    result = filter_videos(videos, None)
    assert len(result) == 2
    assert result == videos


def test_filter_videos_by_theme():
    """Videos are filtered by theme."""
    videos = [
        {"video_id": "v1", "recurring_themes": ["ai", "tech"], "tone_markers": ["analytical"], "upload_date": "20240101"},
        {"video_id": "v2", "recurring_themes": ["productivity"], "tone_markers": ["energetic"], "upload_date": "20240201"},
        {"video_id": "v3", "recurring_themes": ["AI", "Productivity"], "tone_markers": ["analytical"], "upload_date": "20240301"},
    ]
    scope = ChatScope(themes=["ai"])
    result = filter_videos(videos, scope)
    assert len(result) == 2
    assert result[0]["video_id"] == "v1"
    assert result[1]["video_id"] == "v3"


def test_filter_videos_by_tone():
    """Videos are filtered by tone."""
    videos = [
        {"video_id": "v1", "recurring_themes": ["ai"], "tone_markers": ["analytical"], "upload_date": "20240101"},
        {"video_id": "v2", "recurring_themes": ["productivity"], "tone_markers": ["energetic"], "upload_date": "20240201"},
        {"video_id": "v3", "recurring_themes": ["ai"], "tone_markers": ["ANALYTICAL"], "upload_date": "20240301"},
    ]
    scope = ChatScope(tones=["analytical"])
    result = filter_videos(videos, scope)
    assert len(result) == 2
    assert result[0]["video_id"] == "v1"
    assert result[1]["video_id"] == "v3"


def test_filter_videos_by_date_from():
    """Videos are filtered by date_from."""
    videos = [
        {"video_id": "v1", "upload_date": "20240101"},
        {"video_id": "v2", "upload_date": "20240201"},
        {"video_id": "v3", "upload_date": "20240301"},
    ]
    scope = ChatScope(date_from="20240201")
    result = filter_videos(videos, scope)
    assert len(result) == 2
    assert result[0]["video_id"] == "v2"
    assert result[1]["video_id"] == "v3"


def test_filter_videos_by_date_to():
    """Videos are filtered by date_to."""
    videos = [
        {"video_id": "v1", "upload_date": "20240101"},
        {"video_id": "v2", "upload_date": "20240201"},
        {"video_id": "v3", "upload_date": "20240301"},
    ]
    scope = ChatScope(date_to="20240201")
    result = filter_videos(videos, scope)
    assert len(result) == 2
    assert result[0]["video_id"] == "v1"
    assert result[1]["video_id"] == "v2"


def test_filter_videos_by_date_range():
    """Videos are filtered by date range."""
    videos = [
        {"video_id": "v1", "upload_date": "20240101"},
        {"video_id": "v2", "upload_date": "20240201"},
        {"video_id": "v3", "upload_date": "20240301"},
        {"video_id": "v4", "upload_date": "20240401"},
    ]
    scope = ChatScope(date_from="20240201", date_to="20240301")
    result = filter_videos(videos, scope)
    assert len(result) == 2
    assert result[0]["video_id"] == "v2"
    assert result[1]["video_id"] == "v3"


def test_filter_videos_combined_filters():
    """Videos are filtered by combined scope (theme + tone + date)."""
    videos = [
        {"video_id": "v1", "recurring_themes": ["ai"], "tone_markers": ["analytical"], "upload_date": "20240101"},
        {"video_id": "v2", "recurring_themes": ["productivity"], "tone_markers": ["energetic"], "upload_date": "20240201"},
        {"video_id": "v3", "recurring_themes": ["ai"], "tone_markers": ["analytical"], "upload_date": "20240201"},
        {"video_id": "v4", "recurring_themes": ["ai"], "tone_markers": ["energetic"], "upload_date": "20240301"},
    ]
    scope = ChatScope(themes=["ai"], tones=["analytical"], date_from="20240201")
    result = filter_videos(videos, scope)
    assert len(result) == 1
    assert result[0]["video_id"] == "v3"


def test_filter_videos_empty_result():
    """Filter that matches nothing returns empty list."""
    videos = [
        {"video_id": "v1", "recurring_themes": ["ai"], "upload_date": "20240101"},
        {"video_id": "v2", "recurring_themes": ["productivity"], "upload_date": "20240201"},
    ]
    scope = ChatScope(themes=["nonexistent"])
    result = filter_videos(videos, scope)
    assert len(result) == 0