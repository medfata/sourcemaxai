"""Pydantic data models for the Trace API."""

from typing import Any, Generic, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Standard API response wrapper."""

    ok: bool
    data: T | None = None
    error: str | None = None


class ChannelMeta(BaseModel):
    """Metadata for a YouTube channel or single-playlist scope."""

    kind: str = "channel"
    channel_id: str
    channel_name: str
    channel_handle: str | None = None
    avatar_url: str | None = None
    subscriber_count: int | None = None
    total_video_count: int | None = None
    playlist_id: str | None = None
    playlist_title: str | None = None
    owner_channel_id: str | None = None
    owner_channel_name: str | None = None


class ChannelSummary(BaseModel):
    """Channel dashboard row with aggregated state."""

    kind: str = "channel"
    channel_id: str
    channel_name: str
    channel_handle: str | None = None
    avatar_url: str | None = None
    subscriber_count: int | None = None
    total_video_count: int | None = None
    playlist_id: str | None = None
    playlist_title: str | None = None
    owner_channel_id: str | None = None
    owner_channel_name: str | None = None
    video_count: int = 0
    has_profile: bool = False
    latest_run_status: str | None = None
    updated_at: str | None = None


class ChannelList(BaseModel):
    """Owner-scoped list of channels for the dashboard."""

    channels: list[ChannelSummary]


class ChannelRefreshResult(BaseModel):
    """Result of refreshing a channel's video catalog."""

    channel_id: str
    added: int
    total: int


class RetryFailedResult(BaseModel):
    """Result of re-queuing failed videos in a pipeline run."""

    run_id: str
    channel_id: str
    retried: int
    status: str


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


class VideoPage(BaseModel):
    """Paginated slice of videos for a channel."""

    channel_id: str
    kind: str
    offset: int
    limit: int
    total: int
    videos: list[Video]
    has_more: bool


class ChannelCounts(BaseModel):
    """Total counts of videos/shorts/playlists for a channel."""

    channel_id: str
    videos: int
    shorts: int
    playlists: int


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


class WaitlistPayload(BaseModel):
    """Payload for joining the launch waitlist."""

    email: str
    youtube_channel: str | None = None


class WaitlistJoinResult(BaseModel):
    """Public response for a successful waitlist signup."""

    email: str
    youtube_channel: str | None = None
    transcript_minutes: int


class ChatMessage(BaseModel):
    """A single message in a chat conversation."""

    role: str
    content: str
    sources: list[dict[str, Any]] | None = None
    unknown_source_ids: list[str] | None = Field(
        default=None,
        validation_alias=AliasChoices("unknown_source_ids", "unknownSourceIds"),
    )


class ChatScope(BaseModel):
    """Filter scope for chat."""

    model_config = ConfigDict(populate_by_name=True)

    themes: list[str] = Field(default_factory=list)
    tones: list[str] = Field(default_factory=list)
    date_from: str | None = Field(
        default=None,
        validation_alias=AliasChoices("date_from", "dateFrom"),
    )
    date_to: str | None = Field(
        default=None,
        validation_alias=AliasChoices("date_to", "dateTo"),
    )


class ChatPayload(BaseModel):
    """Payload for POST /api/chat."""

    model_config = ConfigDict(populate_by_name=True)

    channel_id: str
    messages: list[ChatMessage]
    scope: ChatScope | None = None
    chat_session_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("chat_session_id", "chatSessionId"),
    )


class ChatSessionCreatePayload(BaseModel):
    """Payload for creating a saved chat session."""

    title: str | None = None


class ChatSessionRenamePayload(BaseModel):
    """Payload for renaming a saved chat session."""

    title: str


class PersistedChatMessage(BaseModel):
    """A chat message loaded from saved history."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    role: str
    content: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    unknown_source_ids: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("unknown_source_ids", "unknownSourceIds"),
    )
    created_at: str
    sequence: int


class ChatSessionSummary(BaseModel):
    """Summary row for a saved chat session."""

    id: str
    channel_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0


class ChatSessionList(BaseModel):
    """Saved chat sessions for one channel."""

    channel_id: str
    sessions: list[ChatSessionSummary]


class ChatSessionDetail(BaseModel):
    """A saved chat session and its messages."""

    session: ChatSessionSummary
    messages: list[PersistedChatMessage]


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
