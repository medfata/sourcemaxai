"""Profile route — serve aggregated channel profile."""

from fastapi import APIRouter, Query

from backend.models import ApiResponse
from backend.storage import get_channel_dir, read_json

router = APIRouter()


@router.get("/api/profile")
async def get_profile(channel_id: str = Query(...)) -> ApiResponse[dict]:
    """Return the computed profile.json for a channel."""
    channel_dir = get_channel_dir(channel_id)
    profile = read_json(channel_dir / "profile.json")
    if not profile:
        return ApiResponse(ok=False, error="profile_not_found")
    return ApiResponse(ok=True, data=profile)
