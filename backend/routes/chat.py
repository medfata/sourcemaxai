"""Chat endpoint: POST /api/chat streaming SSE."""

import json

from backend.auth import CurrentUser, get_current_user
from backend.models import (
    ApiResponse,
    ChatPayload,
    ChatSessionCreatePayload,
    ChatSessionDetail,
    ChatSessionList,
    ChatSessionRenamePayload,
    ChatSessionSummary,
    PersistedChatMessage,
)
from backend.pipeline.ask import chat_stream, filter_videos
from backend.quotas import check_chat_monthly, check_chat_rate, get_quota_store
from backend.storage import (
    append_chat_messages,
    create_chat_session,
    delete_chat_session,
    list_chat_sessions,
    load_channel_meta,
    load_chat_session,
    load_profile,
    rename_chat_session,
    storage_owner,
)
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

router = APIRouter()


def _title_from_message(content: str) -> str:
    title = " ".join(content.strip().split())
    if not title:
        return "New chat"
    return title[:80]


def _latest_user_message(messages: list[dict[str, str]]) -> dict[str, str] | None:
    for message in reversed(messages):
        if message.get("role") == "user" and str(message.get("content") or "").strip():
            return message
    return None


def _session_summary(data: dict) -> ChatSessionSummary:
    return ChatSessionSummary(**data)


def _session_detail(data: dict) -> ChatSessionDetail:
    return ChatSessionDetail(
        session=ChatSessionSummary(**data["session"]),
        messages=[PersistedChatMessage(**message) for message in data["messages"]],
    )


@router.get("/api/channels/{channel_id}/chat-sessions")
def get_chat_sessions(
    channel_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[ChatSessionList]:
    """List saved chat sessions for one channel."""
    if not load_channel_meta(channel_id, owner_id=current_user.owner_id):
        return ApiResponse(ok=False, error="Channel not found")
    sessions = [
        _session_summary(session)
        for session in list_chat_sessions(channel_id, owner_id=current_user.owner_id)
    ]
    return ApiResponse(ok=True, data=ChatSessionList(channel_id=channel_id, sessions=sessions))


@router.post("/api/channels/{channel_id}/chat-sessions")
def post_chat_session(
    channel_id: str,
    payload: ChatSessionCreatePayload,
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[ChatSessionSummary]:
    """Create a saved chat session for one channel."""
    if not load_channel_meta(channel_id, owner_id=current_user.owner_id):
        return ApiResponse(ok=False, error="Channel not found")
    session = create_chat_session(
        channel_id,
        payload.title,
        owner_id=current_user.owner_id,
    )
    return ApiResponse(ok=True, data=_session_summary(session))


@router.get("/api/channels/{channel_id}/chat-sessions/{session_id}")
def get_chat_session(
    channel_id: str,
    session_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[ChatSessionDetail]:
    """Load one saved chat session and its messages."""
    data = load_chat_session(channel_id, session_id, owner_id=current_user.owner_id)
    if not data:
        return ApiResponse(ok=False, error="Chat session not found")
    return ApiResponse(ok=True, data=_session_detail(data))


@router.patch("/api/channels/{channel_id}/chat-sessions/{session_id}")
def patch_chat_session(
    channel_id: str,
    session_id: str,
    payload: ChatSessionRenamePayload,
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[ChatSessionSummary]:
    """Rename one saved chat session."""
    session = rename_chat_session(
        channel_id,
        session_id,
        payload.title,
        owner_id=current_user.owner_id,
    )
    if not session:
        return ApiResponse(ok=False, error="Chat session not found")
    return ApiResponse(ok=True, data=_session_summary(session))


@router.delete("/api/channels/{channel_id}/chat-sessions/{session_id}")
def delete_chat_session_route(
    channel_id: str,
    session_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[dict]:
    """Delete one saved chat session."""
    deleted = delete_chat_session(channel_id, session_id, owner_id=current_user.owner_id)
    if not deleted:
        return ApiResponse(ok=False, error="Chat session not found")
    return ApiResponse(ok=True, data={"id": session_id, "deleted": True})


@router.post("/api/chat")
async def chat(
    payload: ChatPayload,
    current_user: CurrentUser = Depends(get_current_user),
):
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

    quota_store = get_quota_store()
    monthly_decision = check_chat_monthly(quota_store, current_user.owner_id)
    if not monthly_decision.allowed:
        return ApiResponse(
            ok=False,
            error="quota_exceeded",
            data={"reason": monthly_decision.reason, **monthly_decision.detail},
        )

    rate_decision = check_chat_rate(quota_store, current_user.owner_id)
    if not rate_decision.allowed:
        return ApiResponse(
            ok=False,
            error="rate_limited",
            data={"reason": rate_decision.reason, **rate_decision.detail},
        )

    # Check scope and filter videos
    scope = payload.scope if payload.scope else None
    profile = load_profile(payload.channel_id, owner_id=current_user.owner_id)
    if not profile:
        return ApiResponse(ok=False, error="profile_not_found")

    if scope:
        filtered = filter_videos(profile.get("videos", []), scope)
        if len(filtered) == 0:
            return ApiResponse(ok=False, error="scope_empty")

    messages = [{"role": m.role, "content": m.content} for m in payload.messages]
    latest_user = _latest_user_message(messages)
    if not latest_user:
        return ApiResponse(ok=False, error="messages must include a user message")

    if payload.chat_session_id:
        session_detail = load_chat_session(
            payload.channel_id,
            payload.chat_session_id,
            owner_id=current_user.owner_id,
        )
        if not session_detail:
            return ApiResponse(ok=False, error="Chat session not found")
        session = session_detail["session"]
        if session.get("title") == "New chat" and session.get("message_count") == 0:
            renamed = rename_chat_session(
                payload.channel_id,
                payload.chat_session_id,
                _title_from_message(latest_user["content"]),
                owner_id=current_user.owner_id,
            )
            if renamed:
                session = renamed
    else:
        session = create_chat_session(
            payload.channel_id,
            _title_from_message(latest_user["content"]),
            owner_id=current_user.owner_id,
        )

    session_id = str(session["id"])
    appended = append_chat_messages(
        payload.channel_id,
        session_id,
        [{"role": "user", "content": latest_user["content"]}],
        owner_id=current_user.owner_id,
    )
    if appended:
        session = appended

    async def event_generator():
        yield f"data: {json.dumps({'type': 'session', 'session': session})}\n\n"
        assistant_content = ""
        assistant_sources = []
        unknown_source_ids = []
        with storage_owner(current_user.owner_id):
            async for frame in chat_stream(payload.channel_id, messages, scope):
                try:
                    parsed = json.loads(frame)
                except json.JSONDecodeError:
                    yield f"data: {frame}\n\n"
                    continue

                if parsed.get("type") == "sources" and isinstance(parsed.get("sources"), list):
                    assistant_sources = parsed["sources"]
                elif parsed.get("type") == "delta" and isinstance(parsed.get("text"), str):
                    assistant_content += parsed["text"]
                elif (
                    parsed.get("type") == "citation_warning"
                    and isinstance(parsed.get("unknown_source_ids"), list)
                ):
                    unknown_source_ids = [
                        value
                        for value in parsed["unknown_source_ids"]
                        if isinstance(value, str)
                    ]
                elif parsed.get("type") == "done":
                    if assistant_content.strip():
                        updated = append_chat_messages(
                            payload.channel_id,
                            session_id,
                            [
                                {
                                    "role": "assistant",
                                    "content": assistant_content,
                                    "sources": assistant_sources,
                                    "unknown_source_ids": unknown_source_ids,
                                }
                            ],
                            owner_id=current_user.owner_id,
                        )
                        if updated:
                            yield (
                                "data: "
                                + json.dumps({"type": "session", "session": updated})
                                + "\n\n"
                            )
                    yield f"data: {frame}\n\n"
                    return

                yield f"data: {frame}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )
