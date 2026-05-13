"""Profile route — serve aggregated channel profile."""

from fastapi import APIRouter, Depends, Query

from backend.auth import CurrentUser, get_current_user
from backend.models import ApiResponse
from backend.storage import load_profile

router = APIRouter()


@router.get("/api/profile")
async def get_profile(
    channel_id: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[dict]:
    """Return the computed profile.json for a channel."""
    profile = load_profile(channel_id, owner_id=current_user.owner_id)
    if not profile:
        return ApiResponse(ok=False, error="profile_not_found")
    return ApiResponse(ok=True, data=profile)
