"""Channel resolution and management routes."""

from datetime import datetime, timezone
from typing import Any

from backend.auth import CurrentUser, get_current_user
from backend.models import (
    ApiResponse,
    ChannelList,
    ChannelMeta,
    ChannelRefreshResult,
    ChannelSummary,
    ChannelUrlPayload,
)
from backend.pipeline.fetch_videos import fetch_channel_videos, resolve_channel
from backend.storage import (
    delete_channel,
    list_channels,
    load_channel_meta,
    load_profile,
    load_videos,
    save_channel_meta,
    save_videos,
)
from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

router = APIRouter()


def _channel_url_from_meta(channel_id: str, meta: dict) -> str:
    channel_url = str(meta.get("channel_url") or "").strip()
    if channel_url:
        return channel_url
    handle = str(meta.get("channel_handle") or "").strip()
    if handle:
        return f"https://www.youtube.com/@{handle.lstrip('@')}"
    return f"https://www.youtube.com/channel/{channel_id}"


@router.post("/api/channel")
def post_channel(
    payload: ChannelUrlPayload,
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[ChannelMeta]:
    """Resolve a YouTube URL to a channel and persist metadata."""
    try:
        meta_dict = resolve_channel(payload.url)
        channel_id = meta_dict["channel_id"]

        # Merge with any existing owner-scoped meta (preserves fields yt-dlp might miss on re-run)
        existing_meta = load_channel_meta(channel_id, owner_id=current_user.owner_id)
        if existing_meta:
            meta_dict = {**existing_meta, **meta_dict}

        save_channel_meta(channel_id, meta_dict, owner_id=current_user.owner_id)
        return ApiResponse(ok=True, data=ChannelMeta(**meta_dict))
    except RuntimeError as exc:
        return ApiResponse(ok=False, error=str(exc))
    except Exception as exc:
        return ApiResponse(ok=False, error=f"Unexpected error: {exc}")


@router.get("/api/channels")
def get_channels(
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[ChannelList]:
    """Return all channels owned by the current user."""
    rows = list_channels(owner_id=current_user.owner_id)
    summaries = [ChannelSummary(**row) for row in rows]
    return ApiResponse(ok=True, data=ChannelList(channels=summaries))


@router.delete("/api/channels/{channel_id}")
def delete_channel_route(
    channel_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[dict]:
    """Cascade-delete a channel, its artifacts, and pipeline state."""
    if not load_channel_meta(channel_id, owner_id=current_user.owner_id):
        return ApiResponse(ok=False, error="Channel not found")
    removed = delete_channel(channel_id, owner_id=current_user.owner_id)
    if not removed:
        return ApiResponse(ok=False, error="Channel not found")
    return ApiResponse(ok=True, data={"channel_id": channel_id, "deleted": True})


@router.post("/api/channels/{channel_id}/refresh")
def refresh_channel_route(
    channel_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[ChannelRefreshResult]:
    """Re-fetch the channel's video catalog and merge new videos."""
    owner_id = current_user.owner_id
    meta = load_channel_meta(channel_id, owner_id=owner_id)
    if not meta:
        return ApiResponse(ok=False, error="Channel not found")

    try:
        fetched = fetch_channel_videos(_channel_url_from_meta(channel_id, meta))
    except Exception as exc:
        return ApiResponse(ok=False, error=str(exc))

    existing = load_videos(channel_id, owner_id=owner_id) or []
    by_id: dict[str, dict] = {str(v.get("id")): dict(v) for v in existing if v.get("id")}
    added = 0
    for video in fetched:
        vid = str(video.get("id") or "")
        if not vid:
            continue
        if vid not in by_id:
            by_id[vid] = video
            added += 1
        else:
            # Refresh mutable fields (view_count, title, thumbnail) without overwriting
            # generated state captured by other code.
            merged = {**by_id[vid], **video}
            by_id[vid] = merged
    merged_list = sorted(
        by_id.values(),
        key=lambda v: v.get("upload_date") or "99991231",
    )
    save_videos(channel_id, merged_list, owner_id=owner_id)
    return ApiResponse(
        ok=True,
        data=ChannelRefreshResult(channel_id=channel_id, added=added, total=len(merged_list)),
    )


def _safe_filename(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in name.strip())
    cleaned = "-".join(filter(None, cleaned.split("-")))
    return cleaned.lower() or "channel"


def _format_timestamp(seconds: float) -> str:
    total = int(max(seconds, 0))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _claim_lines(claims: list[Any], video_id: str) -> list[str]:
    lines: list[str] = []
    for claim in claims or []:
        if isinstance(claim, dict):
            text = str(claim.get("text") or "").strip()
            if not text:
                continue
            evidence = claim.get("evidence") or []
            cites = []
            for ev in evidence:
                if not isinstance(ev, dict):
                    continue
                start = ev.get("start_seconds")
                if isinstance(start, (int, float)):
                    timestamp = _format_timestamp(float(start))
                    url = f"https://youtu.be/{video_id}?t={int(start)}s"
                    cites.append(
                        f"[{timestamp}]({url})"
                    )
            suffix = f" - {' | '.join(cites)}" if cites else ""
            lines.append(f"- {text}{suffix}")
        elif isinstance(claim, str) and claim.strip():
            lines.append(f"- {claim.strip()}")
    return lines


def _build_markdown(profile: dict[str, Any]) -> str:
    name = str(profile.get("channel_name") or "Unknown channel")
    handle = profile.get("channel_handle")
    video_count = int(profile.get("video_count") or 0)
    date_range = profile.get("date_range") or {}
    rollups = profile.get("rollups") or {}
    videos = profile.get("videos") or []

    lines: list[str] = []
    lines.append(f"# {name}")
    if handle:
        lines.append(f"_@{handle}_")
    lines.append("")
    lines.append(
        f"**Videos analyzed:** {video_count}  \n"
        f"**Date range:** {date_range.get('first') or 'n/a'} - "
        f"{date_range.get('last') or 'n/a'}  \n"
        f"**Generated:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}"
    )
    lines.append("")

    themes = rollups.get("all_themes") or []
    if themes:
        lines.append("## Top themes")
        for theme in themes[:25]:
            if isinstance(theme, dict):
                lines.append(f"- **{theme.get('theme', '')}** - {int(theme.get('count') or 0)}")
        lines.append("")

    referenced = rollups.get("all_referenced") or []
    if referenced:
        lines.append("## Frequently referenced")
        for ref in referenced[:25]:
            if isinstance(ref, dict):
                lines.append(f"- {ref.get('name', '')} ({int(ref.get('count') or 0)})")
        lines.append("")

    tone = rollups.get("tone_distribution") or {}
    if isinstance(tone, dict) and tone:
        lines.append("## Tone mix")
        for label, count in sorted(tone.items(), key=lambda kv: kv[1], reverse=True):
            lines.append(f"- {label}: {int(count)}")
        lines.append("")

    if videos:
        lines.append("## Timeline")
        for video in videos:
            if not isinstance(video, dict):
                continue
            video_id = str(video.get("video_id") or "")
            title = str(video.get("title") or "Untitled")
            upload_date = str(video.get("upload_date") or "")
            url = f"https://youtu.be/{video_id}" if video_id else ""
            heading = f"### {title}"
            if upload_date:
                heading += f" - {upload_date}"
            lines.append(heading)
            if url:
                lines.append(f"<{url}>")
            core_topic = str(video.get("core_topic") or "").strip()
            if core_topic:
                lines.append("")
                lines.append(f"**Core topic:** {core_topic}")
            key_claims = _claim_lines(video.get("key_claims") or [], video_id)
            if key_claims:
                lines.append("")
                lines.append("**Key claims**")
                lines.extend(key_claims)
            opinions = _claim_lines(video.get("notable_opinions") or [], video_id)
            if opinions:
                lines.append("")
                lines.append("**Notable opinions**")
                lines.extend(opinions)
            recurring = video.get("recurring_themes") or []
            if recurring:
                lines.append("")
                lines.append(
                    "**Themes:** " + ", ".join(str(t) for t in recurring if t)
                )
            referenced_in_video = video.get("people_or_things_referenced") or []
            if referenced_in_video:
                lines.append(
                    "**Referenced:** "
                    + ", ".join(str(r) for r in referenced_in_video if r)
                )
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


@router.post("/api/channels/{channel_id}/export/markdown")
def export_channel_markdown(
    channel_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stream a Markdown report of the channel profile for download."""
    owner_id = current_user.owner_id
    if not load_channel_meta(channel_id, owner_id=owner_id):
        return ApiResponse(ok=False, error="Channel not found")
    profile = load_profile(channel_id, owner_id=owner_id)
    if not profile:
        return ApiResponse(ok=False, error="profile_not_found")
    markdown = _build_markdown(profile)
    filename = f"{_safe_filename(str(profile.get('channel_name') or channel_id))}.md"
    return PlainTextResponse(
        markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
