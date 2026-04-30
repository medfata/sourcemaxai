"""Pydantic data models for the Channel Profiler API."""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Standard API response wrapper."""

    ok: bool
    data: T | None = None
    error: str | None = None


class ChannelMeta(BaseModel):
    """Metadata for a YouTube channel."""

    channel_id: str
    channel_name: str
    channel_handle: str | None = None
    avatar_url: str | None = None


class Video(BaseModel):
    """A single video entry from a channel."""
    id: str
    title: str
    upload_date: str
    duration: int
    view_count: int
    thumbnail: str
    is_short: bool = False


class VideoList(BaseModel):
    """List of videos for a channel."""

    channel_id: str
    videos: list[Video]


class Playlist(BaseModel):
    """A YouTube playlist."""
    id: str
    title: str
    video_count: int
    thumbnail: str | None = None


class PlaylistList(BaseModel):
    """List of playlists for a channel."""
    channel_id: str
    playlists: list[Playlist]


class PlaylistVideos(BaseModel):
    """Video IDs belonging to a single playlist."""
    playlist_id: str
    video_ids: list[str]


class ChannelUrlPayload(BaseModel):
    """Payload for POST /api/channel."""

    url: str


class ChatMessage(BaseModel):
    """A single message in a chat conversation."""

    role: str
    content: str


class ChatScope(BaseModel):
    """Filter scope for chat."""

    themes: list[str] = Field(default_factory=list)
    tones: list[str] = Field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None


class ChatPayload(BaseModel):
    """Payload for POST /api/chat."""

    channel_id: str
    messages: list[ChatMessage]
    scope: ChatScope | None = None


class SelectionPayload(BaseModel):
    """Payload for POST /api/videos/select."""

    channel_id: str
    video_ids: list[str]


class Selection(BaseModel):
    """Persisted video selection for a channel."""

    channel_id: str
    video_ids: list[str]


class ThemeCount(BaseModel):
    """A recurring theme and its frequency."""

    theme: str
    count: int


class ReferencedCount(BaseModel):
    """A referenced person/thing and its frequency."""

    name: str
    count: int


class ProfileRollups(BaseModel):
    """Aggregated counters across all video summaries."""

    all_themes: list[ThemeCount]
    all_referenced: list[ReferencedCount]
    tone_distribution: dict[str, int]


class DateRange(BaseModel):
    """Date range of summarized videos."""

    first: str | None
    last: str | None


class Profile(BaseModel):
    """Aggregated channel profile digest."""

    channel_id: str
    channel_name: str
    channel_handle: str | None = None
    avatar_url: str | None = None
    video_count: int
    date_range: DateRange
    videos: list[dict]
    rollups: ProfileRollups
    generated_at: str
