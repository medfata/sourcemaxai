"""Fetch video listings from a YouTube channel using yt-dlp."""

import base64
import binascii
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_RUNTIME_COOKIE_FILE: Path | None = None
_RUNTIME_COOKIE_SOURCE: str | None = None


def _normalize_cookie_text(cookies: str) -> str:
    normalized = cookies.replace("\r\n", "\n").replace("\r", "\n")
    if normalized and not normalized.endswith("\n"):
        normalized += "\n"
    return normalized


def _write_runtime_cookie_file(cookies: str) -> Path:
    global _RUNTIME_COOKIE_FILE, _RUNTIME_COOKIE_SOURCE

    normalized = _normalize_cookie_text(cookies)
    if not normalized.strip():
        raise RuntimeError("YTDLP_COOKIES_B64 is set but does not contain any cookies")

    if (
        _RUNTIME_COOKIE_FILE
        and _RUNTIME_COOKIE_SOURCE == normalized
        and _RUNTIME_COOKIE_FILE.exists()
    ):
        return _RUNTIME_COOKIE_FILE

    cookie_path = Path(tempfile.gettempdir()) / "trace-ytdlp-cookies.txt"
    cookie_path.write_text(normalized, encoding="utf-8", newline="\n")
    try:
        cookie_path.chmod(0o600)
    except OSError:
        pass

    _RUNTIME_COOKIE_FILE = cookie_path
    _RUNTIME_COOKIE_SOURCE = normalized
    return cookie_path


def _ytdlp_cookie_args() -> list[str]:
    """Return yt-dlp cookie options from deployment environment."""
    cookies_path = os.environ.get("YTDLP_COOKIES_PATH", "").strip()
    if cookies_path:
        return ["--cookies", cookies_path]

    cookies_b64 = "".join(os.environ.get("YTDLP_COOKIES_B64", "").split())
    if not cookies_b64:
        return []

    try:
        cookies = base64.b64decode(cookies_b64, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise RuntimeError(
            "YTDLP_COOKIES_B64 must be base64-encoded UTF-8 Netscape cookies.txt content"
        ) from exc

    return ["--cookies", str(_write_runtime_cookie_file(cookies))]


def _run_ytdlp(args: list[str]) -> str:
    """Run yt-dlp and return stdout. Raises RuntimeError on failure."""
    cmd = [
        "python",
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--no-warnings",
        "--no-check-certificates",
        *_ytdlp_cookie_args(),
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
    channel_url = metadata["channel_url"]

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
        # Note: do NOT use info.get("n_entries") here. On the /playlists tab
        # listing, n_entries is the count of the outer tab (= number of
        # playlists), not the size of each individual playlist.
        video_count = info.get("playlist_count") or info.get("video_count") or 0
        if not video_count:
            try:
                video_count = len(fetch_playlist_video_ids(plid))
            except Exception:
                video_count = 0
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
