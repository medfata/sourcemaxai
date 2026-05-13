"""Video listing and selection routes."""

from fastapi import APIRouter, Depends, Query

from backend.auth import CurrentUser, get_current_user
from backend.models import (
    ApiResponse,
    PlaylistList,
    PlaylistVideos,
    Selection,
    SelectionPayload,
    VideoList,
)
from backend.pipeline.fetch_videos import (
    fetch_channel_playlists,
    fetch_channel_videos,
    fetch_playlist_video_ids,
)
from backend.storage import (
    load_channel_meta,
    load_playlist_video_ids,
    load_playlists,
    load_selection,
    load_videos,
    save_playlist_video_ids,
    save_playlists,
    save_selection,
    save_videos,
)

router = APIRouter()


def _channel_url_from_meta(channel_id: str, meta: dict) -> str:
    channel_url = str(meta.get("channel_url") or "").strip()
    if channel_url:
        return channel_url
    handle = str(meta.get("channel_handle") or "").strip()
    if handle:
        return f"https://www.youtube.com/@{handle.lstrip('@')}"
    return f"https://www.youtube.com/channel/{channel_id}"


@router.get("/api/videos")
def get_videos(
    channel_id: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[VideoList]:
    """Return the video list for a channel, fetching from yt-dlp if not cached."""
    owner_id = current_user.owner_id
    meta = load_channel_meta(channel_id, owner_id=owner_id)
    if not meta:
        return ApiResponse(ok=False, error="Channel not found")

    cached = load_videos(channel_id, owner_id=owner_id)
    if cached:
        for v in cached:
            if "is_short" not in v:
                duration = v.get("duration", 0) or 0
                v["is_short"] = 0 < duration <= 60
        return ApiResponse(
            ok=True, data=VideoList(channel_id=channel_id, videos=cached)
        )

    try:
        videos = fetch_channel_videos(_channel_url_from_meta(channel_id, meta))
        save_videos(channel_id, videos, owner_id=owner_id)
        return ApiResponse(
            ok=True, data=VideoList(channel_id=channel_id, videos=videos)
        )
    except Exception as exc:
        return ApiResponse(ok=False, error=str(exc))


@router.post("/api/videos/select")
def post_select(
    payload: SelectionPayload,
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[Selection]:
    """Persist the user's video selection."""
    owner_id = current_user.owner_id
    meta = load_channel_meta(payload.channel_id, owner_id=owner_id)
    if not meta:
        return ApiResponse(ok=False, error="Channel not found")

    save_selection(payload.channel_id, payload.video_ids, owner_id=owner_id)
    return ApiResponse(
        ok=True,
        data=Selection(
            channel_id=payload.channel_id, video_ids=payload.video_ids
        ),
    )


@router.get("/api/selection")
def get_selection(
    channel_id: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[Selection]:
    """Return the persisted selection for a channel."""
    owner_id = current_user.owner_id
    meta = load_channel_meta(channel_id, owner_id=owner_id)
    if not meta:
        return ApiResponse(ok=False, error="Channel not found")

    video_ids = load_selection(channel_id, owner_id=owner_id)
    if video_ids is None:
        # Default: all videos selected
        videos = load_videos(channel_id, owner_id=owner_id) or []
        video_ids = [v["id"] for v in videos]
        if video_ids:
            save_selection(channel_id, video_ids, owner_id=owner_id)

    return ApiResponse(
        ok=True, data=Selection(channel_id=channel_id, video_ids=video_ids)
    )


@router.get("/api/playlists")
def get_playlists(
    channel_id: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[PlaylistList]:
    """Return the playlist list for a channel, fetching from yt-dlp if not cached."""
    owner_id = current_user.owner_id
    meta = load_channel_meta(channel_id, owner_id=owner_id)
    if not meta:
        return ApiResponse(ok=False, error="Channel not found")

    cached = load_playlists(channel_id, owner_id=owner_id)
    if cached:
        return ApiResponse(
            ok=True, data=PlaylistList(channel_id=channel_id, playlists=cached)
        )

    try:
        playlists = fetch_channel_playlists(_channel_url_from_meta(channel_id, meta))
        save_playlists(channel_id, playlists, owner_id=owner_id)
        return ApiResponse(
            ok=True, data=PlaylistList(channel_id=channel_id, playlists=playlists)
        )
    except Exception as exc:
        return ApiResponse(ok=False, error=str(exc))


@router.get("/api/playlists/videos")
def get_playlist_videos(
    channel_id: str = Query(...),
    playlist_id: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[PlaylistVideos]:
    """Return the video IDs for a playlist, fetching from yt-dlp if not cached."""
    owner_id = current_user.owner_id
    meta = load_channel_meta(channel_id, owner_id=owner_id)
    if not meta:
        return ApiResponse(ok=False, error="Channel not found")

    cached = load_playlist_video_ids(channel_id, playlist_id, owner_id=owner_id)
    if cached is not None:
        return ApiResponse(
            ok=True,
            data=PlaylistVideos(playlist_id=playlist_id, video_ids=cached),
        )

    try:
        video_ids = fetch_playlist_video_ids(playlist_id)
        save_playlist_video_ids(channel_id, playlist_id, video_ids, owner_id=owner_id)
        return ApiResponse(
            ok=True,
            data=PlaylistVideos(playlist_id=playlist_id, video_ids=video_ids),
        )
    except Exception as exc:
        return ApiResponse(ok=False, error=str(exc))
