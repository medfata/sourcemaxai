"""Disk storage helpers for flat JSON files."""

import json
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent / "data"))


def get_data_dir() -> Path:
    """Return the root data directory."""
    path = DATA_DIR.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_channel_dir(channel_id: str) -> Path:
    """Return the directory for a specific channel."""
    path = get_data_dir() / "channels" / channel_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path) -> dict | list | None:
    """Read JSON from disk if it exists."""
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: dict | list) -> None:
    """Write JSON to disk atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


def load_channel_meta(channel_id: str) -> dict | None:
    """Load channel meta.json if it exists."""
    return read_json(get_channel_dir(channel_id) / "meta.json")


def save_channel_meta(channel_id: str, data: dict) -> None:
    """Persist channel meta.json."""
    write_json(get_channel_dir(channel_id) / "meta.json", data)


def load_videos(channel_id: str) -> list[dict] | None:
    """Load videos.json if it exists."""
    data = read_json(get_channel_dir(channel_id) / "videos.json")
    return data.get("videos") if isinstance(data, dict) else data


def save_videos(channel_id: str, videos: list[dict]) -> None:
    """Persist videos.json."""
    write_json(get_channel_dir(channel_id) / "videos.json", {"videos": videos})


def load_selection(channel_id: str) -> list[str] | None:
    """Load selection.json if it exists."""
    data = read_json(get_channel_dir(channel_id) / "selection.json")
    return data.get("video_ids") if isinstance(data, dict) else None


def save_selection(channel_id: str, video_ids: list[str]) -> None:
    """Persist selection.json."""
    write_json(get_channel_dir(channel_id) / "selection.json", {"video_ids": video_ids})
