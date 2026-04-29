"""Video listing and selection routes."""

from fastapi import APIRouter, Query

from backend.models import ApiResponse, Selection, SelectionPayload, VideoList
from backend.pipeline.fetch_videos import fetch_channel_videos
from backend.storage import (
    load_channel_meta,
    load_selection,
    load_videos,
    save_selection,
    save_videos,
)

router = APIRouter()


@router.get("/api/videos")
def get_videos(channel_id: str = Query(...)) -> ApiResponse[VideoList]:
    """Return the video list for a channel, fetching from yt-dlp if not cached."""
    meta = load_channel_meta(channel_id)
    if not meta:
        return ApiResponse(ok=False, error="Channel not found")

    cached = load_videos(channel_id)
    if cached is not None:
        return ApiResponse(
            ok=True, data=VideoList(channel_id=channel_id, videos=cached)
        )

    # Build canonical channel URL from meta
    handle = meta.get("channel_handle")
    if handle:
        channel_url = f"https://www.youtube.com/@{handle}"
    else:
        channel_url = f"https://www.youtube.com/channel/{channel_id}"

    try:
        videos = fetch_channel_videos(channel_url)
        save_videos(channel_id, videos)
        return ApiResponse(
            ok=True, data=VideoList(channel_id=channel_id, videos=videos)
        )
    except Exception as exc:
        return ApiResponse(ok=False, error=str(exc))


@router.post("/api/videos/select")
def post_select(payload: SelectionPayload) -> ApiResponse[Selection]:
    """Persist the user's video selection."""
    meta = load_channel_meta(payload.channel_id)
    if not meta:
        return ApiResponse(ok=False, error="Channel not found")

    save_selection(payload.channel_id, payload.video_ids)
    return ApiResponse(
        ok=True,
        data=Selection(
            channel_id=payload.channel_id, video_ids=payload.video_ids
        ),
    )


@router.get("/api/selection")
def get_selection(channel_id: str = Query(...)) -> ApiResponse[Selection]:
    """Return the persisted selection for a channel."""
    meta = load_channel_meta(channel_id)
    if not meta:
        return ApiResponse(ok=False, error="Channel not found")

    video_ids = load_selection(channel_id)
    if video_ids is None:
        # Default: all videos selected
        videos = load_videos(channel_id) or []
        video_ids = [v["id"] for v in videos]
        save_selection(channel_id, video_ids)

    return ApiResponse(
        ok=True, data=Selection(channel_id=channel_id, video_ids=video_ids)
    )
