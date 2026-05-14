"""Fetch video listings from a YouTube channel using yt-dlp."""

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse


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


def resolve_channel(url: str) -> dict[str, Any]:
    """Resolve a YouTube URL to channel metadata.

    Accepts channel URLs (@handle, /c/, /channel/), playlist URLs, and video URLs.
    Returns {"channel_id", "channel_name", "channel_handle", "avatar_url"}.
    """
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
            url,
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
                url,
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
    handle = _channel_handle_from_url(channel_url) or _channel_handle_from_url(url) or None

    # Try to get avatar via --dump-json on the channel page (one item)
    avatar_url: str | None = None
    try:
        info_stdout = _run_ytdlp(
            [
                "--flat-playlist",
                "--dump-json",
                "--playlist-items",
                "1",
                channel_url,
            ]
        )
        first_line = info_stdout.strip().splitlines()[0]
        info = json.loads(first_line)
        # thumbnails array often has avatar at the channel level
        thumbnails = info.get("thumbnails", [])
        if thumbnails:
            avatar_url = thumbnails[-1].get("url")
    except Exception:
        pass

    return {
        "channel_id": channel_id,
        "channel_name": channel_name,
        "channel_handle": handle,
        "channel_url": channel_url,
        "avatar_url": avatar_url,
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
