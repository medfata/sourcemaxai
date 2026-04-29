"""Fetch video listings from a YouTube channel using yt-dlp."""

import json
import subprocess
from typing import Any


def _run_ytdlp(args: list[str]) -> str:
    """Run yt-dlp and return stdout. Raises RuntimeError on failure."""
    cmd = ["python", "-m", "yt_dlp", "--no-warnings", "--no-check-certificates"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        # yt-dlp exits non-zero for some valid operations; check if stdout is empty
        if not result.stdout.strip():
            raise RuntimeError(result.stderr.strip() or "yt-dlp failed")
    return result.stdout


def resolve_channel(url: str) -> dict[str, Any]:
    """Resolve a YouTube URL to channel metadata.

    Accepts channel URLs (@handle, /c/, /channel/), playlist URLs, and video URLs.
    Returns {"channel_id", "channel_name", "channel_handle", "avatar_url"}.
    """
    # Resolve using a single item to extract channel fields
    stdout = _run_ytdlp(
        [
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
    lines = [line.strip() for line in stdout.strip().splitlines() if line.strip()]
    if len(lines) < 3:
        raise RuntimeError("Could not resolve channel from URL")

    channel_id = lines[0]
    channel_name = lines[1]
    channel_url = lines[2]

    # Extract handle from URL if present
    handle: str | None = None
    if "@" in channel_url:
        handle = channel_url.split("@")[1].split("/")[0]

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
        "avatar_url": avatar_url,
    }


def fetch_channel_videos(channel_url: str) -> list[dict[str, Any]]:
    """Return every video on the channel as a list of dicts.

    Each dict contains: id, title, upload_date, duration, view_count, thumbnail.
    Sorted ascending by upload_date (oldest first).

    Uses --flat-playlist --dump-json for speed, with approximate_date fallback.
    """
    stdout = _run_ytdlp(
        [
            "--flat-playlist",
            "--dump-json",
            "--extractor-args",
            "youtubetab:approximate_date",
            channel_url,
        ]
    )
    videos: list[dict[str, Any]] = []
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        info = json.loads(line)
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
                "is_short": 0 < duration_val <= 60,
            }
        )

    # Sort by date if available; undated videos go to the end
    videos.sort(key=lambda v: v["upload_date"] or "99991231")
    return videos


def fetch_channel_playlists(channel_url: str) -> list[dict[str, Any]]:
    """Return every public playlist on the channel as a list of dicts.

    Each dict contains: id, title, video_count, thumbnail.
    Runs yt-dlp --flat-playlist --dump-json against <channel_url>/playlists.
    """
    url = channel_url.rstrip("/") + "/playlists"
    stdout = _run_ytdlp(["--flat-playlist", "--dump-json", url])
    playlists: list[dict[str, Any]] = []
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        info = json.loads(line)
        plid = info.get("id")
        if not plid:
            continue
        video_count = info.get("playlist_count") or info.get("video_count") or info.get("n_entries") or 0
        thumbnail = None
        thumbnails = info.get("thumbnails")
        if thumbnails and len(thumbnails) > 0:
            thumbnail = thumbnails[-1].get("url")
        playlists.append({
            "id": plid,
            "title": info.get("title", "Untitled"),
            "video_count": int(video_count),
            "thumbnail": thumbnail,
        })
    return playlists


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
