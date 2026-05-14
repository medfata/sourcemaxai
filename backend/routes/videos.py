"""Video listing and selection routes."""

from fastapi import APIRouter, Depends, Query

from backend.auth import CurrentUser, get_current_user
from backend.models import (
    ApiResponse,
    ChannelCounts,
    PlaylistList,
    PlaylistVideos,
    Selection,
    SelectionPayload,
    VideoList,
    VideoPage,
)
from backend.pipeline.fetch_videos import (
    channel_playlists_url,
    channel_shorts_url,
    channel_videos_url,
    fetch_channel_playlists,
    fetch_channel_shorts_page,
    fetch_channel_videos_page,
    fetch_playlist_video_ids,
    fetch_tab_count,
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

PAGE_LIMIT_DEFAULT = 50
PAGE_LIMIT_MAX = 100


def _channel_url_from_meta(channel_id: str, meta: dict) -> str:
    channel_url = str(meta.get("channel_url") or "").strip()
    if channel_url:
        return channel_url
    handle = str(meta.get("channel_handle") or "").strip()
    if handle:
        return f"https://www.youtube.com/@{handle.lstrip('@')}"
    return f"https://www.youtube.com/channel/{channel_id}"


def _normalize_cached(videos: list[dict]) -> list[dict]:
    for v in videos:
        if "is_short" not in v:
            duration = v.get("duration", 0) or 0
            v["is_short"] = 0 < duration <= 60
    return videos


def _sort_newest_first(videos: list[dict]) -> list[dict]:
    """Sort videos by upload_date DESC; empties go to the end."""
    return sorted(videos, key=lambda v: v.get("upload_date") or "", reverse=True)


def _merge_videos(cached: list[dict], fetched: list[dict]) -> list[dict]:
    """Merge fetched videos into cache, dedupe by id, sort newest-first."""
    by_id = {str(v.get("id")): dict(v) for v in cached if v.get("id")}
    for v in fetched:
        vid = str(v.get("id") or "")
        if not vid:
            continue
        if vid in by_id:
            by_id[vid] = {**by_id[vid], **v}
        else:
            by_id[vid] = v
    return _sort_newest_first(by_id.values())


@router.get("/api/videos")
def get_videos(
    channel_id: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[VideoList]:
    """Return the cached video list for a channel.

    Used by pipeline progress views which need every video the user previously
    loaded. Does NOT trigger a full channel-wide fetch — paginated UI requests
    go through ``/api/videos/page``.
    """
    owner_id = current_user.owner_id
    meta = load_channel_meta(channel_id, owner_id=owner_id)
    if not meta:
        return ApiResponse(ok=False, error="Channel not found")

    cached = load_videos(channel_id, owner_id=owner_id) or []
    _normalize_cached(cached)
    return ApiResponse(ok=True, data=VideoList(channel_id=channel_id, videos=cached))


@router.get("/api/videos/page")
def get_videos_page(
    channel_id: str = Query(...),
    kind: str = Query("videos", pattern="^(videos|shorts)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(PAGE_LIMIT_DEFAULT, ge=1, le=PAGE_LIMIT_MAX),
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[VideoPage]:
    """Return a paginated slice of long-form videos or shorts.

    Trusts the cache when it already covers ``offset+limit`` items of the
    requested kind; otherwise fetches a yt-dlp page covering the missing range
    and merges it back into the persisted cache.
    """
    owner_id = current_user.owner_id
    meta = load_channel_meta(channel_id, owner_id=owner_id)
    if not meta:
        return ApiResponse(ok=False, error="Channel not found")

    channel_url = _channel_url_from_meta(channel_id, meta)
    cached = _sort_newest_first(
        _normalize_cached(load_videos(channel_id, owner_id=owner_id) or [])
    )

    want_short = kind == "shorts"
    filtered = [v for v in cached if bool(v.get("is_short")) is want_short]

    # Cursor-pagination probe: fetch one extra entry so we can tell whether
    # more items exist without trusting yt-dlp's unreliable ``playlist_count``.
    needed = offset + limit + 1
    fetched_total: int | None = None
    if len(filtered) < needed:
        fetch_start = len(filtered) + 1
        fetch_end = needed
        try:
            if want_short:
                new_videos, fetched_total = fetch_channel_shorts_page(
                    channel_url, start=fetch_start, end=fetch_end
                )
            else:
                new_videos, fetched_total = fetch_channel_videos_page(
                    channel_url, start=fetch_start, end=fetch_end
                )
        except Exception as exc:
            return ApiResponse(ok=False, error=str(exc))

        merged = _merge_videos(cached, new_videos)
        save_videos(channel_id, merged, owner_id=owner_id)
        cached = merged
        filtered = [v for v in cached if bool(v.get("is_short")) is want_short]

    page = filtered[offset : offset + limit]
    has_more = len(filtered) > offset + limit
    total = max(fetched_total or 0, len(filtered))
    return ApiResponse(
        ok=True,
        data=VideoPage(
            channel_id=channel_id,
            kind=kind,
            offset=offset,
            limit=limit,
            total=total,
            videos=page,
            has_more=has_more,
        ),
    )


@router.get("/api/videos/counts")
def get_video_counts(
    channel_id: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[ChannelCounts]:
    """Return total counts of videos, shorts, and playlists for the channel."""
    owner_id = current_user.owner_id
    meta = load_channel_meta(channel_id, owner_id=owner_id)
    if not meta:
        return ApiResponse(ok=False, error="Channel not found")

    channel_url = _channel_url_from_meta(channel_id, meta)
    try:
        videos = fetch_tab_count(channel_videos_url(channel_url))
        shorts = fetch_tab_count(channel_shorts_url(channel_url))
        playlists = fetch_tab_count(channel_playlists_url(channel_url))
    except Exception as exc:
        return ApiResponse(ok=False, error=str(exc))

    return ApiResponse(
        ok=True,
        data=ChannelCounts(
            channel_id=channel_id,
            videos=videos,
            shorts=shorts,
            playlists=playlists,
        ),
    )


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
        video_ids = []

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
