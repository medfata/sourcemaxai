"""Quota and usage routes."""

from fastapi import APIRouter, Depends

from backend.auth import CurrentUser, get_current_user
from backend.models import ApiResponse
from backend.quotas import ESTIMATED_BYTES_PER_TRANSCRIPT, get_quota_store

router = APIRouter()


@router.get("/api/quota/proxy-usage")
async def get_proxy_usage(
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[dict]:
    """Return the user's proxy bandwidth usage for the current month."""
    quota_store = get_quota_store()
    quota = quota_store.get_quota(current_user.owner_id)
    usage = quota_store.get_monthly_usage(current_user.owner_id)

    limit = quota.proxy_bytes_per_month
    used = usage.proxy_bytes
    remaining = max(limit - used, 0)
    estimated_videos = remaining // ESTIMATED_BYTES_PER_TRANSCRIPT if remaining > 0 else 0

    return ApiResponse(
        ok=True,
        data={
            "tier_key": quota.tier_key,
            "proxy_bytes_used": used,
            "proxy_bytes_limit": limit,
            "proxy_bytes_remaining": remaining,
            "estimated_videos_remaining": estimated_videos,
        },
    )
