"""Channel resolution route."""

from fastapi import APIRouter

from backend.models import ApiResponse, ChannelMeta, ChannelUrlPayload
from backend.pipeline.fetch_videos import resolve_channel
from backend.storage import load_channel_meta, save_channel_meta

router = APIRouter()


@router.post("/api/channel")
def post_channel(payload: ChannelUrlPayload) -> ApiResponse[ChannelMeta]:
    """Resolve a YouTube URL to a channel and persist metadata."""
    try:
        meta_dict = resolve_channel(payload.url)
        channel_id = meta_dict["channel_id"]

        # Merge with any existing disk meta (preserves fields yt-dlp might miss on re-run)
        disk_meta = load_channel_meta(channel_id)
        if disk_meta:
            meta_dict = {**disk_meta, **meta_dict}

        save_channel_meta(channel_id, meta_dict)
        return ApiResponse(ok=True, data=ChannelMeta(**meta_dict))
    except RuntimeError as exc:
        return ApiResponse(ok=False, error=str(exc))
    except Exception as exc:
        return ApiResponse(ok=False, error=f"Unexpected error: {exc}")
