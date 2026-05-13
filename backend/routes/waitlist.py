"""Public waitlist route."""

import logging

from backend.models import ApiResponse, WaitlistJoinResult, WaitlistPayload
from backend.storage import save_waitlist_entry
from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/waitlist")
def join_waitlist(
    payload: WaitlistPayload,
    request: Request,
) -> ApiResponse[WaitlistJoinResult]:
    """Join or update a public launch waitlist entry."""
    try:
        entry = save_waitlist_entry(
            payload.email,
            youtube_channel=payload.youtube_channel,
            user_agent=request.headers.get("user-agent"),
            referrer=request.headers.get("referer"),
        )
    except ValueError as exc:
        return ApiResponse(ok=False, error=str(exc))
    except Exception:
        logger.exception("waitlist_join_failed")
        return ApiResponse(ok=False, error="Could not join waitlist. Please try again.")

    return ApiResponse(
        ok=True,
        data=WaitlistJoinResult(
            email=str(entry["email"]),
            youtube_channel=entry.get("youtube_channel"),
            transcript_minutes=int(entry["transcript_minutes"]),
        ),
    )
