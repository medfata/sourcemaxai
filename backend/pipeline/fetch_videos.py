"""Fetch video listings from a YouTube channel using yt-dlp."""

import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urlparse


_HANDLE_RE = re.compile(r"^@[A-Za-z0-9._-]+$")
_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}


def _run_ytdlp(args: list[str]) -> str:
    """Run yt-dlp and return stdout. Raises RuntimeError on failure."""
    cmd = [
        "python",
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--no-warnings",
        "--no-check-certificates",
        *args,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        # yt-dlp exits non-zero for some valid operations; check if stdout is empty
        if not result.stdout.strip():
            raise RuntimeError(result.stderr.strip() or "yt-dlp failed")
    return result.stdout


def _clean_ytdlp_value(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text in {"NA", "None", "null"} else text


def _is_channel_id(value: str) -> bool:
    return value.startswith("UC")


def _channel_id_from_url(url: Any) -> str:
    text = _clean_ytdlp_value(url)
    if not text:
        return ""
    path_parts = [part for part in urlparse(text).path.split("/") if part]
    if len(path_parts) >= 2 and path_parts[0] == "channel" and _is_channel_id(path_parts[1]):
        return path_parts[1]
    return ""


def _normalize_input(url: str) -> str:
    """Accept bare ``@handle`` and rewrite to a YouTube URL.

    All other inputs returned unchanged. Empty/whitespace returned as ``""``.
    """
    text = (url or "").strip()
    if not text:
        return ""
    if _HANDLE_RE.match(text):
        return f"https://www.youtube.com/{text}"
    return text


def _extract_playlist_id(url: str) -> str | None:
    """Return playlist id from ``?list=PL...``-style URLs, ``None`` otherwise.

    Rejects auto-generated mix radios (``RD`` prefix) and channel uploads
    (``UU`` prefix) so they fall through to channel resolution instead.
    """
    text = (url or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if host not in _YT_HOSTS:
        return None
    qs = parse_qs(parsed.query or "")
    list_vals = qs.get("list") or []
    if not list_vals:
        return None
    pid = (list_vals[0] or "").strip()
    if not pid or pid.startswith("RD") or pid.startswith("UU"):
        return None
    return pid


def _channel_handle_from_url(url: Any) -> str:
    text = _clean_ytdlp_value(url)
    if not text:
        return ""
    path_parts = [part for part in urlparse(text).path.split("/") if part]
    for part in path_parts:
        if part.startswith("@"):
            return part[1:]
    return ""


def _strip_tab(channel_url: str) -> str:
    base = channel_url.rstrip("/")
    for tab in ("/videos", "/shorts", "/streams", "/playlists", "/featured", "/community"):
        if base.endswith(tab):
            return base[: -len(tab)]
    return base


def channel_videos_url(channel_url: str) -> str:
    """Return the channel Videos tab URL for yt-dlp flat listing."""
    return f"{_strip_tab(channel_url)}/videos"


def channel_shorts_url(channel_url: str) -> str:
    """Return the channel Shorts tab URL for yt-dlp flat listing."""
    return f"{_strip_tab(channel_url)}/shorts"


def channel_playlists_url(channel_url: str) -> str:
    """Return the channel Playlists tab URL for yt-dlp flat listing."""
    return f"{_strip_tab(channel_url)}/playlists"


def _metadata_from_info(info: dict[str, Any]) -> dict[str, str]:
    channel_url = _clean_ytdlp_value(
        info.get("channel_url") or info.get("uploader_url") or info.get("webpage_url")
    )
    raw_channel_id = _clean_ytdlp_value(info.get("channel_id"))
    raw_id = _clean_ytdlp_value(info.get("id"))
    channel_id = (
        (raw_channel_id if _is_channel_id(raw_channel_id) else "")
        or _channel_id_from_url(channel_url)
        or (raw_id if _is_channel_id(raw_id) else "")
    )
    channel_name = (
        _clean_ytdlp_value(info.get("channel"))
        or _clean_ytdlp_value(info.get("uploader"))
        or _clean_ytdlp_value(info.get("title"))
    )
    return {
        "channel_id": channel_id,
        "channel_name": channel_name,
        "channel_url": channel_url,
    }


def _metadata_from_json(stdout: str) -> dict[str, str]:
    if not stdout.strip():
        return {"channel_id": "", "channel_name": "", "channel_url": ""}

    info = json.loads(stdout)
    metadata = _metadata_from_info(info)
    if metadata["channel_id"] and metadata["channel_name"]:
        return metadata

    entries = info.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_metadata = _metadata_from_info(entry)
            if not metadata["channel_id"] and entry_metadata["channel_id"]:
                metadata["channel_id"] = entry_metadata["channel_id"]
            if not metadata["channel_name"] and entry_metadata["channel_name"]:
                metadata["channel_name"] = entry_metadata["channel_name"]
            if not metadata["channel_url"] and entry_metadata["channel_url"]:
                metadata["channel_url"] = entry_metadata["channel_url"]
            if metadata["channel_id"] and metadata["channel_name"]:
                return metadata

    return metadata


def _pick_avatar_from_thumbnails(thumbnails: Any) -> str | None:
    """Pick the largest square avatar URL from a yt-dlp thumbnails array."""
    if not isinstance(thumbnails, list) or not thumbnails:
        return None
    avatars = [t for t in thumbnails if isinstance(t, dict) and t.get("url")]
    if not avatars:
        return None
    # Prefer thumbnails tagged as avatar/profile (yt-dlp uses ids like "avatar_uncropped").
    tagged = [
        t for t in avatars
        if "avatar" in str(t.get("id") or "").lower()
        or "avatar" in str(t.get("preference") or "").lower()
    ]
    pool = tagged or avatars
    pool_sorted = sorted(
        pool,
        key=lambda t: int(t.get("width") or 0) * int(t.get("height") or 0),
    )
    return str(pool_sorted[-1].get("url") or "") or None


def resolve_channel(url: str) -> dict[str, Any]:
    """Resolve a YouTube URL/handle to channel or playlist metadata.

    Accepts channel URLs (``@handle``, ``/c/``, ``/channel/``), bare handles
    (``@name``), playlist URLs (``?list=PL...``), and video URLs. Playlist
    URLs are dispatched to :func:`resolve_playlist` and returned with
    ``kind='playlist'``; everything else returns ``kind='channel'``.
    """
    normalized = _normalize_input(url)
    if not normalized:
        raise RuntimeError("Empty URL")

    playlist_id = _extract_playlist_id(normalized)
    if playlist_id:
        return resolve_playlist(normalized)

    # Resolve through the flat channel listing so yt-dlp does not inspect a
    # video format when all we need is channel metadata.
    stdout = _run_ytdlp(
        [
            "--flat-playlist",
            "--skip-download",
            "--print",
            "%(channel_id)s",
            "--print",
            "%(channel)s",
            "--print",
            "%(channel_url)s",
            "--playlist-items",
            "1",
            normalized,
        ]
    )
    lines = [_clean_ytdlp_value(line) for line in stdout.strip().splitlines()]
    printed_channel_id = lines[0] if len(lines) >= 1 and _is_channel_id(lines[0]) else ""
    metadata = {
        "channel_id": printed_channel_id,
        "channel_name": lines[1] if len(lines) >= 2 else "",
        "channel_url": lines[2] if len(lines) >= 3 else "",
    }

    if not metadata["channel_id"] or not metadata["channel_name"]:
        info_stdout = _run_ytdlp(
            [
                "--flat-playlist",
                "--dump-single-json",
                "--playlist-items",
                "1",
                normalized,
            ]
        )
        json_metadata = _metadata_from_json(info_stdout)
        metadata = {
            "channel_id": metadata["channel_id"] or json_metadata["channel_id"],
            "channel_name": metadata["channel_name"] or json_metadata["channel_name"],
            "channel_url": metadata["channel_url"] or json_metadata["channel_url"],
        }

    if not metadata["channel_id"] or not metadata["channel_name"]:
        raise RuntimeError("Could not resolve channel from URL")

    channel_id = metadata["channel_id"]
    channel_name = metadata["channel_name"]
    channel_url = metadata["channel_url"] or f"https://www.youtube.com/channel/{channel_id}"

    # Extract handle from URL if present
    handle = _channel_handle_from_url(channel_url) or _channel_handle_from_url(normalized) or None

    # Fetch channel envelope (avatar, subscriber count) AND the /videos tab
    # count in parallel — both are independent yt-dlp subprocess calls and
    # account for the bulk of POST /api/channel latency. The home page's
    # playlist_count is the featured-section count, not total videos, so we
    # still pull total_video_count from the /videos tab.
    avatar_url: str | None = None
    subscriber_count: int | None = None
    total_video_count: int | None = None

    def _fetch_envelope() -> dict[str, Any]:
        try:
            stdout = _run_ytdlp(
                [
                    "--flat-playlist",
                    "--dump-single-json",
                    "--playlist-items",
                    "1",
                    channel_url,
                ]
            )
            return json.loads(stdout) if stdout.strip() else {}
        except Exception:
            return {}

    def _fetch_videos_count() -> int:
        try:
            return fetch_tab_count(channel_videos_url(channel_url))
        except Exception:
            return 0

    with ThreadPoolExecutor(max_workers=2) as pool:
        envelope_future = pool.submit(_fetch_envelope)
        count_future = pool.submit(_fetch_videos_count)
        info = envelope_future.result()
        videos_count = count_future.result()

    if isinstance(info, dict):
        avatar_url = _pick_avatar_from_thumbnails(info.get("thumbnails"))
        followers = info.get("channel_follower_count")
        if isinstance(followers, (int, float)) and followers > 0:
            subscriber_count = int(followers)
    if videos_count > 0:
        total_video_count = videos_count

    return {
        "kind": "channel",
        "channel_id": channel_id,
        "channel_name": channel_name,
        "channel_handle": handle,
        "channel_url": channel_url,
        "avatar_url": avatar_url,
        "subscriber_count": subscriber_count,
        "total_video_count": total_video_count,
        "playlist_id": None,
        "playlist_title": None,
    }


def resolve_playlist(url: str) -> dict[str, Any]:
    """Resolve a playlist URL to playlist-as-channel metadata.

    Returns a channel-shaped dict with ``kind='playlist'``. The virtual
    ``channel_id`` is the playlist id (``PL...``), ``channel_name`` is the
    playlist title, and ``playlist_id`` / ``playlist_title`` are populated
    so the UI can label the entity correctly.
    """
    playlist_id = _extract_playlist_id(url)
    if not playlist_id:
        raise RuntimeError("Could not parse playlist id from URL")

    canonical_url = f"https://www.youtube.com/playlist?list={playlist_id}"

    info_stdout = _run_ytdlp(
        [
            "--flat-playlist",
            "--dump-single-json",
            "--playlist-items",
            "1",
            canonical_url,
        ]
    )
    info: dict[str, Any] = {}
    if info_stdout.strip():
        info = json.loads(info_stdout)

    playlist_title = _clean_ytdlp_value(info.get("title")) or playlist_id

    # The playlist envelope's ``title`` is the playlist title, not the owning
    # channel name — only treat envelope channel/uploader fields as owner info.
    owner = {
        "channel_id": _clean_ytdlp_value(info.get("channel_id"))
            if _is_channel_id(_clean_ytdlp_value(info.get("channel_id"))) else "",
        "channel_name": _clean_ytdlp_value(info.get("channel"))
            or _clean_ytdlp_value(info.get("uploader")),
        "channel_url": _clean_ytdlp_value(
            info.get("channel_url") or info.get("uploader_url")
        ),
    }
    if not owner["channel_id"] or not owner["channel_name"]:
        entries = info.get("entries") if isinstance(info, dict) else None
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                em = _metadata_from_info(entry)
                if not owner["channel_id"] and em["channel_id"]:
                    owner["channel_id"] = em["channel_id"]
                if not owner["channel_name"] and em["channel_name"]:
                    owner["channel_name"] = em["channel_name"]
                if not owner["channel_url"] and em["channel_url"]:
                    owner["channel_url"] = em["channel_url"]
                if owner["channel_id"] and owner["channel_name"]:
                    break

    handle = (
        _channel_handle_from_url(owner["channel_url"])
        or _channel_handle_from_url(url)
        or None
    )

    avatar_url = _pick_avatar_from_thumbnails(info.get("thumbnails"))

    total_video_count: int | None = None
    pcount = info.get("playlist_count") if isinstance(info, dict) else None
    if isinstance(pcount, int) and pcount > 0:
        total_video_count = pcount
    if total_video_count is None:
        try:
            total_video_count = fetch_playlist_count(playlist_id) or None
        except Exception:
            total_video_count = None

    return {
        "kind": "playlist",
        "channel_id": playlist_id,
        "channel_name": playlist_title,
        "channel_handle": handle,
        "channel_url": canonical_url,
        "avatar_url": avatar_url,
        "subscriber_count": None,
        "total_video_count": total_video_count,
        "playlist_id": playlist_id,
        "playlist_title": playlist_title,
        "owner_channel_id": owner["channel_id"] or None,
        "owner_channel_name": owner["channel_name"] or None,
    }


def _parse_video_entries(stdout: str, *, is_short: bool) -> list[dict[str, Any]]:
    videos, _ = _parse_video_entries_with_total(stdout, is_short=is_short)
    return videos


def _parse_video_entries_with_total(
    stdout: str, *, is_short: bool
) -> tuple[list[dict[str, Any]], int | None]:
    videos: list[dict[str, Any]] = []
    total: int | None = None
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        info = json.loads(line)
        if total is None:
            raw_total = info.get("playlist_count") or info.get("n_entries")
            if isinstance(raw_total, int) and raw_total > 0:
                total = raw_total
        vid = info.get("id")
        if not vid:
            continue
        upload_date = info.get("upload_date")
        duration = info.get("duration") or 0
        view_count = info.get("view_count") or 0
        duration_val = int(duration) if duration else 0
        videos.append(
            {
                "id": vid,
                "title": info.get("title", "Untitled"),
                "upload_date": upload_date if upload_date and upload_date != "19700101" else "",
                "duration": duration_val,
                "view_count": int(view_count) if view_count else 0,
                "thumbnail": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                "is_short": True if is_short else (0 < duration_val <= 60),
            }
        )
    return videos, total


def _playlist_items_arg(start: int, end: int | None) -> str:
    start = max(int(start), 1)
    if end is None or int(end) <= 0:
        return f"{start}:"
    return f"{start}:{int(end)}"


def fetch_channel_videos(
    channel_url: str,
    *,
    start: int = 1,
    end: int | None = None,
) -> list[dict[str, Any]]:
    """Return videos from the channel /videos tab as a list of dicts.

    Each dict contains: id, title, upload_date, duration, view_count, thumbnail, is_short.
    Order: YouTube's listing order (newest first by default).

    Pagination via 1-based ``start`` and inclusive ``end`` indices.
    """
    videos, _ = fetch_channel_videos_page(channel_url, start=start, end=end)
    return videos


def fetch_channel_videos_page(
    channel_url: str,
    *,
    start: int = 1,
    end: int | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    """Same as :func:`fetch_channel_videos` but also returns the tab's total count.

    ``total`` is the channel's tab-wide ``playlist_count`` reported by yt-dlp on
    each entry; ``None`` when yt-dlp did not emit it (rare).
    """
    stdout = _run_ytdlp(
        [
            "--flat-playlist",
            "--dump-json",
            "--extractor-args",
            "youtubetab:approximate_date",
            "--playlist-items",
            _playlist_items_arg(start, end),
            channel_videos_url(channel_url),
        ]
    )
    return _parse_video_entries_with_total(stdout, is_short=False)


def fetch_channel_shorts(
    channel_url: str,
    *,
    start: int = 1,
    end: int | None = None,
) -> list[dict[str, Any]]:
    """Return shorts from the channel /shorts tab as a list of dicts.

    yt-dlp on the /shorts tab returns each short flat (often without duration).
    We mark every entry ``is_short=True`` since the tab is short-form by definition.
    """
    videos, _ = fetch_channel_shorts_page(channel_url, start=start, end=end)
    return videos


def fetch_channel_shorts_page(
    channel_url: str,
    *,
    start: int = 1,
    end: int | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    """Same as :func:`fetch_channel_shorts` but also returns the tab's total count."""
    stdout = _run_ytdlp(
        [
            "--flat-playlist",
            "--dump-json",
            "--extractor-args",
            "youtubetab:approximate_date",
            "--playlist-items",
            _playlist_items_arg(start, end),
            channel_shorts_url(channel_url),
        ]
    )
    return _parse_video_entries_with_total(stdout, is_short=True)


def fetch_playlist_videos_page(
    playlist_id: str,
    *,
    start: int = 1,
    end: int | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    """Return a paginated slice of videos from a single playlist.

    Mirrors :func:`fetch_channel_videos_page` but targets the
    ``playlist?list=<id>`` URL so the entries come from one playlist rather
    than a channel tab.
    """
    url = f"https://www.youtube.com/playlist?list={playlist_id}"
    stdout = _run_ytdlp(
        [
            "--flat-playlist",
            "--dump-json",
            "--playlist-items",
            _playlist_items_arg(start, end),
            url,
        ]
    )
    return _parse_video_entries_with_total(stdout, is_short=False)


def fetch_tab_count(tab_url: str) -> int:
    """Return total item count for a channel tab (videos/shorts/playlists).

    Uses ``--print "%(playlist_count)s"`` with ``--playlist-items 1`` so yt-dlp
    only emits the top-level count without paginating through every entry.
    Returns 0 when the count cannot be parsed.
    """
    try:
        stdout = _run_ytdlp(
            [
                "--flat-playlist",
                "--skip-download",
                "--playlist-items",
                "1",
                "--print",
                "playlist:%(playlist_count)s",
                tab_url,
            ]
        )
    except RuntimeError:
        return 0
    for line in stdout.strip().splitlines():
        token = _clean_ytdlp_value(line)
        if token.isdigit():
            return int(token)
    return 0


def fetch_channel_playlists(channel_url: str) -> list[dict[str, Any]]:
    """Return every public playlist on the channel as a list of dicts.

    Each dict contains: id, title, video_count, thumbnail.
    Per-playlist ``video_count`` is resolved with one yt-dlp call per playlist
    (run in parallel) because the /playlists tab listing reports the outer
    count on each entry, not the size of each individual playlist.
    """
    url = channel_playlists_url(channel_url)
    stdout = _run_ytdlp(["--flat-playlist", "--dump-json", url])
    raw: list[dict[str, Any]] = []
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        info = json.loads(line)
        plid = info.get("id")
        if not plid:
            continue
        thumbnail = None
        thumbnails = info.get("thumbnails")
        if thumbnails and len(thumbnails) > 0:
            thumbnail = thumbnails[-1].get("url")
        raw.append({
            "id": plid,
            "title": info.get("title", "Untitled"),
            "thumbnail": thumbnail,
        })

    if not raw:
        return []

    counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(raw))) as pool:
        futures = {pool.submit(fetch_playlist_count, item["id"]): item["id"] for item in raw}
        for fut in as_completed(futures):
            plid = futures[fut]
            try:
                counts[plid] = int(fut.result() or 0)
            except Exception:
                counts[plid] = 0

    return [
        {
            "id": item["id"],
            "title": item["title"],
            "video_count": counts.get(item["id"], 0),
            "thumbnail": item["thumbnail"],
        }
        for item in raw
    ]


def fetch_playlist_count(playlist_id: str) -> int:
    """Return the total number of videos in a playlist.

    Fast path: one yt-dlp call with ``--playlist-items 1`` so YouTube returns
    the playlist_count without iterating through every entry.
    """
    url = f"https://www.youtube.com/playlist?list={playlist_id}"
    try:
        stdout = _run_ytdlp(
            [
                "--flat-playlist",
                "--skip-download",
                "--playlist-items",
                "1",
                "--print",
                "playlist:%(playlist_count)s",
                url,
            ]
        )
    except RuntimeError:
        # Fallback: count IDs explicitly
        try:
            return len(fetch_playlist_video_ids(playlist_id))
        except Exception:
            return 0
    for line in stdout.strip().splitlines():
        token = _clean_ytdlp_value(line)
        if token.isdigit():
            return int(token)
    try:
        return len(fetch_playlist_video_ids(playlist_id))
    except Exception:
        return 0


def fetch_playlist_video_ids(playlist_id: str) -> list[str]:
    """Return all video IDs in a playlist.

    URL format: https://www.youtube.com/playlist?list=<playlist_id>
    Uses --flat-playlist --print '%(id)s' for speed.
    """
    url = f"https://www.youtube.com/playlist?list={playlist_id}"
    stdout = _run_ytdlp(["--flat-playlist", "--print", "%(id)s", url])
    ids: list[str] = []
    for line in stdout.strip().splitlines():
        line = line.strip()
        if line:
            ids.append(line)
    return ids
