"""Chat endpoint: POST /api/chat streaming SSE."""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.models import ApiResponse, ChatPayload, ChatScope
from backend.pipeline.ask import build_system_prompt, chat_stream, filter_videos
from backend.storage import get_channel_dir, read_json

router = APIRouter()


@router.post("/api/chat")
async def chat(payload: ChatPayload):
    """Stream chat completions via Server-Sent Events."""
    # Validate messages
    if not payload.messages:
        return ApiResponse(ok=False, error="messages array is empty")

    valid_roles = {"user", "assistant"}
    for i, msg in enumerate(payload.messages):
        if msg.role not in valid_roles:
            return ApiResponse(ok=False, error=f"invalid role: {msg.role}")
        # Allow trailing empty assistant placeholder — the UI creates this slot
        # for the in-progress response, so we shouldn't reject it.
        is_last = i == len(payload.messages) - 1
        if msg.role == "assistant" and is_last and msg.content == "":
            continue
        if not isinstance(msg.content, str) or msg.content.strip() == "":
            return ApiResponse(ok=False, error="content must be a non-empty string")

    # Check scope and filter videos
    scope = payload.scope if payload.scope else None
    channel_dir = get_channel_dir(payload.channel_id)
    profile = read_json(channel_dir / "profile.json")
    if not profile:
        return ApiResponse(ok=False, error="profile_not_found")

    if scope:
        filtered = filter_videos(profile.get("videos", []), scope)
        if len(filtered) == 0:
            return ApiResponse(ok=False, error="scope_empty")

    messages = [{"role": m.role, "content": m.content} for m in payload.messages]

    async def event_generator():
        async for frame in chat_stream(payload.channel_id, messages, scope):
            yield f"data: {frame}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )
