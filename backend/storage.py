"""Storage adapters for local JSON files and Supabase persistence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

JsonData = dict[str, Any] | list[Any]

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent / "data"))
LOCAL_OWNER_ID = "local"
CHANNEL_ARTIFACTS_BUCKET = "channel-artifacts"
DEFAULT_RUN_ID = "manual"
DEFAULT_CHAT_SESSION_TITLE = "New chat"
WAITLIST_TRANSCRIPT_MINUTES = 1000
_CURRENT_OWNER_ID: ContextVar[str | None] = ContextVar("storage_owner_id", default=None)
_CURRENT_RUN_ID: ContextVar[str | None] = ContextVar("storage_run_id", default=None)
_WAITLIST_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class StorageError(RuntimeError):
    """Base error for storage adapter failures."""


class StorageConfigError(StorageError):
    """Raised when a configured storage backend cannot be initialized."""


class SupabaseStorageError(StorageError):
    """Raised when a Supabase REST or Storage request fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class StorageBackend(ABC):
    """Owner-aware storage interface for channel state and generated artifacts."""

    @abstractmethod
    def load_channel_meta(self, owner_id: str, channel_id: str) -> dict[str, Any] | None:
        """Load metadata for one channel."""

    @abstractmethod
    def save_channel_meta(self, owner_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Persist metadata for one channel."""

    @abstractmethod
    def load_videos(self, owner_id: str, channel_id: str) -> list[dict[str, Any]] | None:
        """Load the cached video catalog for one channel."""

    @abstractmethod
    def save_videos(
        self,
        owner_id: str,
        channel_id: str,
        videos: list[dict[str, Any]],
    ) -> None:
        """Persist the video catalog for one channel."""

    @abstractmethod
    def load_selection(self, owner_id: str, channel_id: str) -> list[str] | None:
        """Load selected YouTube video IDs for one channel."""

    @abstractmethod
    def save_selection(self, owner_id: str, channel_id: str, video_ids: list[str]) -> None:
        """Persist selected YouTube video IDs for one channel."""

    @abstractmethod
    def load_transcript(
        self,
        owner_id: str,
        channel_id: str,
        video_id: str,
    ) -> dict[str, Any] | None:
        """Load one transcript artifact."""

    @abstractmethod
    def save_transcript(
        self,
        owner_id: str,
        channel_id: str,
        run_id: str,
        video_id: str,
        data: dict[str, Any],
    ) -> None:
        """Persist one transcript artifact."""

    @abstractmethod
    def load_summary(
        self,
        owner_id: str,
        channel_id: str,
        video_id: str,
    ) -> dict[str, Any] | None:
        """Load one summary artifact."""

    @abstractmethod
    def save_summary(
        self,
        owner_id: str,
        channel_id: str,
        run_id: str,
        video_id: str,
        data: dict[str, Any],
    ) -> None:
        """Persist one summary artifact."""

    @abstractmethod
    def load_profile(self, owner_id: str, channel_id: str) -> dict[str, Any] | None:
        """Load the latest channel profile."""

    @abstractmethod
    def save_profile(
        self,
        owner_id: str,
        channel_id: str,
        run_id: str,
        data: dict[str, Any],
    ) -> None:
        """Persist one channel profile snapshot."""

    @abstractmethod
    def list_chat_sessions(self, owner_id: str, channel_id: str) -> list[dict[str, Any]]:
        """Return saved chat sessions for one channel."""

    @abstractmethod
    def create_chat_session(
        self,
        owner_id: str,
        channel_id: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Create a saved chat session."""

    @abstractmethod
    def load_chat_session(
        self,
        owner_id: str,
        channel_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Load one saved chat session with messages."""

    @abstractmethod
    def rename_chat_session(
        self,
        owner_id: str,
        channel_id: str,
        session_id: str,
        title: str,
    ) -> dict[str, Any] | None:
        """Rename a saved chat session."""

    @abstractmethod
    def delete_chat_session(self, owner_id: str, channel_id: str, session_id: str) -> bool:
        """Delete a saved chat session."""

    @abstractmethod
    def append_chat_messages(
        self,
        owner_id: str,
        channel_id: str,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Append messages to a saved chat session and return its summary."""

    @abstractmethod
    def list_channels(self, owner_id: str) -> list[dict[str, Any]]:
        """Return owner's channels with summary metadata for the dashboard."""

    @abstractmethod
    def delete_channel(self, owner_id: str, channel_id: str) -> bool:
        """Delete a channel and all related data. Return True if found+removed."""

    @abstractmethod
    def save_waitlist_entry(self, data: dict[str, Any]) -> dict[str, Any]:
        """Persist a launch waitlist entry."""


def _is_uuid(value: str) -> bool:
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_chat_title(value: Any) -> str:
    title = " ".join(str(value or "").strip().split())
    if not title:
        return DEFAULT_CHAT_SESSION_TITLE
    return title[:80]


def _normalize_waitlist_email(email: Any) -> str:
    normalized = str(email or "").strip().lower()
    if not normalized or len(normalized) > 254 or not _WAITLIST_EMAIL_RE.match(normalized):
        raise ValueError("Enter a valid email address")
    return normalized


def _clean_waitlist_channel(value: Any) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    return cleaned[:500]


def _waitlist_payload(data: dict[str, Any]) -> dict[str, Any]:
    normalized_email = _normalize_waitlist_email(data.get("email"))
    return {
        "email": normalized_email,
        "normalized_email": normalized_email,
        "youtube_channel": _clean_waitlist_channel(data.get("youtube_channel")),
        "transcript_minutes": WAITLIST_TRANSCRIPT_MINUTES,
        "source": str(data.get("source") or "waitlist_page").strip()[:80] or "waitlist_page",
        "user_agent": _clean_waitlist_channel(data.get("user_agent")),
        "referrer": _clean_waitlist_channel(data.get("referrer")),
    }


def current_owner_id() -> str | None:
    """Return the owner ID active for storage calls in the current request/task."""
    return _CURRENT_OWNER_ID.get()


def current_run_id() -> str | None:
    """Return the pipeline run ID active for artifact writes in this task."""
    return _CURRENT_RUN_ID.get()


@contextmanager
def storage_owner(owner_id: str | None) -> Iterator[None]:
    """Temporarily bind owner-aware storage helpers to a verified user."""
    token = _CURRENT_OWNER_ID.set(owner_id)
    try:
        yield
    finally:
        _CURRENT_OWNER_ID.reset(token)


@contextmanager
def storage_run(run_id: str | None) -> Iterator[None]:
    """Temporarily bind generated artifacts to a durable pipeline run."""
    token = _CURRENT_RUN_ID.set(run_id)
    try:
        yield
    finally:
        _CURRENT_RUN_ID.reset(token)


def _effective_owner_id(owner_id: str | None = None) -> str | None:
    return owner_id or current_owner_id()


def _effective_run_id(run_id: str | None = None) -> str:
    return current_run_id() or run_id or DEFAULT_RUN_ID


def get_data_dir() -> Path:
    """Return the root local data directory."""
    path = DATA_DIR.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json_file(path: Path) -> JsonData | None:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json_file(path: Path, data: JsonData) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


class LocalStorageBackend(StorageBackend):
    """Storage backend that preserves the original local flat-file layout."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir

    def get_data_dir(self) -> Path:
        path = (self._data_dir or DATA_DIR).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_channel_dir(self, channel_id: str, owner_id: str | None = None) -> Path:
        if owner_id and owner_id != LOCAL_OWNER_ID:
            safe_owner = owner_id.replace("/", "_").replace("\\", "_")
            path = self.get_data_dir() / "users" / safe_owner / "channels" / channel_id
        else:
            path = self.get_data_dir() / "channels" / channel_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def read_json(self, path: Path) -> JsonData | None:
        return _read_json_file(Path(path))

    def write_json(self, path: Path, data: JsonData) -> None:
        _write_json_file(Path(path), data)

    def load_channel_meta(self, owner_id: str, channel_id: str) -> dict[str, Any] | None:
        data = self.read_json(self.get_channel_dir(channel_id, owner_id) / "meta.json")
        return data if isinstance(data, dict) else None

    def save_channel_meta(self, owner_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        channel_id = str(data.get("channel_id") or data.get("youtube_channel_id") or "")
        if not channel_id:
            raise StorageError("Channel metadata must include channel_id")
        self.write_json(self.get_channel_dir(channel_id, owner_id) / "meta.json", data)
        return data

    def load_videos(self, owner_id: str, channel_id: str) -> list[dict[str, Any]] | None:
        data = self.read_json(self.get_channel_dir(channel_id, owner_id) / "videos.json")
        if isinstance(data, dict):
            videos = data.get("videos")
            return videos if isinstance(videos, list) else None
        return data if isinstance(data, list) else None

    def save_videos(
        self,
        owner_id: str,
        channel_id: str,
        videos: list[dict[str, Any]],
    ) -> None:
        self.write_json(
            self.get_channel_dir(channel_id, owner_id) / "videos.json",
            {"videos": videos},
        )

    def load_selection(self, owner_id: str, channel_id: str) -> list[str] | None:
        data = self.read_json(self.get_channel_dir(channel_id, owner_id) / "selection.json")
        if not isinstance(data, dict):
            return None
        video_ids = data.get("video_ids")
        return video_ids if isinstance(video_ids, list) else None

    def save_selection(self, owner_id: str, channel_id: str, video_ids: list[str]) -> None:
        self.write_json(
            self.get_channel_dir(channel_id, owner_id) / "selection.json",
            {"video_ids": video_ids},
        )

    def load_transcript(
        self,
        owner_id: str,
        channel_id: str,
        video_id: str,
    ) -> dict[str, Any] | None:
        data = self.read_json(
            self.get_channel_dir(channel_id, owner_id) / "transcripts" / f"{video_id}.json"
        )
        return data if isinstance(data, dict) else None

    def save_transcript(
        self,
        owner_id: str,
        channel_id: str,
        run_id: str,
        video_id: str,
        data: dict[str, Any],
    ) -> None:
        self.write_json(
            self.get_channel_dir(channel_id, owner_id) / "transcripts" / f"{video_id}.json",
            data,
        )

    def load_summary(
        self,
        owner_id: str,
        channel_id: str,
        video_id: str,
    ) -> dict[str, Any] | None:
        data = self.read_json(
            self.get_channel_dir(channel_id, owner_id) / "summaries" / f"{video_id}.json"
        )
        return data if isinstance(data, dict) else None

    def save_summary(
        self,
        owner_id: str,
        channel_id: str,
        run_id: str,
        video_id: str,
        data: dict[str, Any],
    ) -> None:
        self.write_json(
            self.get_channel_dir(channel_id, owner_id) / "summaries" / f"{video_id}.json",
            data,
        )

    def load_profile(self, owner_id: str, channel_id: str) -> dict[str, Any] | None:
        data = self.read_json(self.get_channel_dir(channel_id, owner_id) / "profile.json")
        return data if isinstance(data, dict) else None

    def save_profile(
        self,
        owner_id: str,
        channel_id: str,
        run_id: str,
        data: dict[str, Any],
    ) -> None:
        self.write_json(self.get_channel_dir(channel_id, owner_id) / "profile.json", data)

    def _chat_sessions_dir(self, channel_id: str, owner_id: str) -> Path:
        path = self.get_channel_dir(channel_id, owner_id) / "chat_sessions"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _chat_session_path(self, channel_id: str, owner_id: str, session_id: str) -> Path:
        safe_session_id = session_id.replace("/", "_").replace("\\", "_")
        return self._chat_sessions_dir(channel_id, owner_id) / f"{safe_session_id}.json"

    @staticmethod
    def _chat_session_summary(payload: dict[str, Any], channel_id: str) -> dict[str, Any] | None:
        session = payload.get("session")
        messages = payload.get("messages")
        if not isinstance(session, dict):
            return None
        session_id = str(session.get("id") or "")
        if not session_id:
            return None
        created_at = str(session.get("created_at") or _utc_now_iso())
        updated_at = str(session.get("updated_at") or created_at)
        return {
            "id": session_id,
            "channel_id": str(session.get("channel_id") or channel_id),
            "title": _clean_chat_title(session.get("title")),
            "created_at": created_at,
            "updated_at": updated_at,
            "message_count": len(messages) if isinstance(messages, list) else 0,
        }

    def list_chat_sessions(self, owner_id: str, channel_id: str) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        base = self._chat_sessions_dir(channel_id, owner_id)
        for entry in base.glob("*.json"):
            data = self.read_json(entry)
            if not isinstance(data, dict):
                continue
            summary = self._chat_session_summary(data, channel_id)
            if summary:
                sessions.append(summary)
        return sorted(sessions, key=lambda row: str(row.get("updated_at") or ""), reverse=True)

    def create_chat_session(
        self,
        owner_id: str,
        channel_id: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        now = _utc_now_iso()
        session = {
            "id": str(uuid4()),
            "channel_id": channel_id,
            "title": _clean_chat_title(title),
            "created_at": now,
            "updated_at": now,
        }
        payload = {"session": session, "messages": []}
        self.write_json(self._chat_session_path(channel_id, owner_id, session["id"]), payload)
        return {**session, "message_count": 0}

    def load_chat_session(
        self,
        owner_id: str,
        channel_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        data = self.read_json(self._chat_session_path(channel_id, owner_id, session_id))
        if not isinstance(data, dict):
            return None
        summary = self._chat_session_summary(data, channel_id)
        messages = data.get("messages")
        if not summary or not isinstance(messages, list):
            return None
        clean_messages = [m for m in messages if isinstance(m, dict)]
        clean_messages.sort(key=lambda message: int(message.get("sequence") or 0))
        return {"session": summary, "messages": clean_messages}

    def rename_chat_session(
        self,
        owner_id: str,
        channel_id: str,
        session_id: str,
        title: str,
    ) -> dict[str, Any] | None:
        path = self._chat_session_path(channel_id, owner_id, session_id)
        data = self.read_json(path)
        if not isinstance(data, dict) or not isinstance(data.get("session"), dict):
            return None
        data["session"]["title"] = _clean_chat_title(title)
        data["session"]["updated_at"] = _utc_now_iso()
        self.write_json(path, data)
        return self._chat_session_summary(data, channel_id)

    def delete_chat_session(self, owner_id: str, channel_id: str, session_id: str) -> bool:
        path = self._chat_session_path(channel_id, owner_id, session_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def append_chat_messages(
        self,
        owner_id: str,
        channel_id: str,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        path = self._chat_session_path(channel_id, owner_id, session_id)
        data = self.read_json(path)
        if not isinstance(data, dict) or not isinstance(data.get("session"), dict):
            return None
        existing = data.get("messages")
        if not isinstance(existing, list):
            existing = []
        existing_sequences = (
            int(message.get("sequence") or 0)
            for message in existing
            if isinstance(message, dict)
        )
        max_sequence = max(existing_sequences, default=0)
        now = _utc_now_iso()
        for offset, message in enumerate(messages, start=1):
            role = str(message.get("role") or "").strip()
            content = str(message.get("content") or "")
            if role not in {"user", "assistant"} or not content.strip():
                continue
            sources = message.get("sources")
            unknown_source_ids = message.get("unknown_source_ids")
            existing.append(
                {
                    "id": str(uuid4()),
                    "role": role,
                    "content": content,
                    "sources": sources if isinstance(sources, list) else [],
                    "unknown_source_ids": (
                        unknown_source_ids if isinstance(unknown_source_ids, list) else []
                    ),
                    "created_at": now,
                    "sequence": max_sequence + offset,
                }
            )
        data["messages"] = existing
        data["session"]["updated_at"] = now
        self.write_json(path, data)
        return self._chat_session_summary(data, channel_id)

    def list_channels(self, owner_id: str) -> list[dict[str, Any]]:
        if owner_id and owner_id != LOCAL_OWNER_ID:
            safe_owner = owner_id.replace("/", "_").replace("\\", "_")
            base = self.get_data_dir() / "users" / safe_owner / "channels"
        else:
            base = self.get_data_dir() / "channels"
        if not base.exists():
            return []
        out: list[dict[str, Any]] = []
        for entry in sorted(base.iterdir(), key=lambda p: p.name):
            if not entry.is_dir():
                continue
            meta = self.read_json(entry / "meta.json")
            if not isinstance(meta, dict):
                continue
            channel_id = str(meta.get("channel_id") or meta.get("youtube_channel_id") or entry.name)
            videos = self.read_json(entry / "videos.json")
            video_count = 0
            if isinstance(videos, dict) and isinstance(videos.get("videos"), list):
                video_count = len(videos["videos"])
            elif isinstance(videos, list):
                video_count = len(videos)
            profile = self.read_json(entry / "profile.json")
            run_state = self.read_json(entry / "pipeline_run_state.json")
            out.append(
                {
                    "channel_id": channel_id,
                    "channel_name": meta.get("channel_name") or channel_id,
                    "channel_handle": meta.get("channel_handle"),
                    "avatar_url": meta.get("avatar_url"),
                    "video_count": video_count,
                    "has_profile": isinstance(profile, dict),
                    "latest_run_status": (
                        (run_state or {}).get("status") if isinstance(run_state, dict) else None
                    ),
                    "updated_at": (
                        (run_state or {}).get("completed_at")
                        or (run_state or {}).get("started_at")
                        or (run_state or {}).get("created_at")
                        if isinstance(run_state, dict)
                        else None
                    ),
                }
            )
        return out

    def delete_channel(self, owner_id: str, channel_id: str) -> bool:
        if owner_id and owner_id != LOCAL_OWNER_ID:
            safe_owner = owner_id.replace("/", "_").replace("\\", "_")
            path = self.get_data_dir() / "users" / safe_owner / "channels" / channel_id
        else:
            path = self.get_data_dir() / "channels" / channel_id
        if not path.exists():
            return False
        shutil.rmtree(path, ignore_errors=True)
        return True

    def save_waitlist_entry(self, data: dict[str, Any]) -> dict[str, Any]:
        entry = _waitlist_payload(data)
        normalized_email = entry["email"]
        now = _utc_now_iso()
        path = self.get_data_dir() / "waitlist_entries.json"
        payload = self.read_json(path)
        entries = (
            payload.get("entries")
            if isinstance(payload, dict) and isinstance(payload.get("entries"), list)
            else []
        )

        existing = next(
            (
                row
                for row in entries
                if isinstance(row, dict)
                and str(row.get("normalized_email") or row.get("email") or "").lower()
                == normalized_email
            ),
            None,
        )
        if existing:
            existing.update(
                {
                    **entry,
                    "normalized_email": normalized_email,
                    "updated_at": now,
                }
            )
            saved = existing
        else:
            saved = {
                "id": str(uuid4()),
                **entry,
                "normalized_email": normalized_email,
                "created_at": now,
                "updated_at": now,
            }
            entries.append(saved)

        self.write_json(path, {"entries": entries})
        return saved

    def load_playlists(
        self,
        channel_id: str,
        owner_id: str | None = None,
    ) -> list[dict[str, Any]] | None:
        data = self.read_json(self.get_channel_dir(channel_id, owner_id) / "playlists.json")
        if not isinstance(data, dict):
            return None
        playlists = data.get("playlists")
        return playlists if isinstance(playlists, list) else None

    def save_playlists(
        self,
        channel_id: str,
        playlists: list[dict[str, Any]],
        owner_id: str | None = None,
    ) -> None:
        self.write_json(
            self.get_channel_dir(channel_id, owner_id) / "playlists.json",
            {"playlists": playlists},
        )

    def load_playlist_video_ids(
        self,
        channel_id: str,
        playlist_id: str,
        owner_id: str | None = None,
    ) -> list[str] | None:
        data = self.read_json(
            self.get_channel_dir(channel_id, owner_id) / "playlist_videos" / f"{playlist_id}.json"
        )
        if not isinstance(data, dict):
            return None
        video_ids = data.get("video_ids")
        return video_ids if isinstance(video_ids, list) else None

    def save_playlist_video_ids(
        self,
        channel_id: str,
        playlist_id: str,
        video_ids: list[str],
        owner_id: str | None = None,
    ) -> None:
        self.write_json(
            self.get_channel_dir(channel_id, owner_id) / "playlist_videos" / f"{playlist_id}.json",
            {"video_ids": video_ids},
        )


class SupabaseStorageBackend(StorageBackend):
    """Storage backend using Supabase PostgREST and private Storage objects.

    The adapter uses only the server-side service role key. Existing route code still
    uses local helpers until it can pass owner IDs from verified JWTs.
    """

    def __init__(
        self,
        supabase_url: str,
        service_role_key: str,
        *,
        channel_artifacts_bucket: str = CHANNEL_ARTIFACTS_BUCKET,
        timeout: float = 15.0,
    ) -> None:
        if not supabase_url.strip():
            raise StorageConfigError("SUPABASE_URL is required for Supabase storage")
        if not service_role_key.strip():
            raise StorageConfigError(
                "SUPABASE_SERVICE_ROLE_KEY is required for Supabase storage"
            )
        self.supabase_url = supabase_url.rstrip("/")
        self._service_role_key = service_role_key
        self.channel_artifacts_bucket = channel_artifacts_bucket
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "SupabaseStorageBackend":
        missing = [
            name
            for name in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
            if not os.environ.get(name)
        ]
        if missing:
            names = ", ".join(missing)
            raise StorageConfigError(f"STORAGE_BACKEND=supabase requires {names}")
        return cls(
            supabase_url=os.environ["SUPABASE_URL"],
            service_role_key=os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        )

    def _headers(self, *, content_type: str | None = "application/json") -> dict[str, str]:
        headers = {
            "apikey": self._service_role_key,
            "Authorization": f"Bearer {self._service_role_key}",
            "Accept": "application/json",
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        request = Request(url, data=body, headers=headers or {}, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            raise SupabaseStorageError(
                f"Supabase request failed with HTTP {exc.code}: {method} {url}",
                status_code=exc.code,
                body=response_body,
            ) from exc
        except URLError as exc:
            raise SupabaseStorageError(f"Supabase request failed: {exc.reason}") from exc

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        payload: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        body = None
        request_headers = headers or self._headers()
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        raw = self._request(method, url, body=body, headers=request_headers)
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))

    def _rest_url(self, table: str, params: dict[str, str] | None = None) -> str:
        url = f"{self.supabase_url}/rest/v1/{table}"
        if params:
            url = f"{url}?{urlencode(params, safe='(),.*')}"
        return url

    def _storage_url(self, bucket: str, path: str) -> str:
        encoded_path = quote(path, safe="/")
        return f"{self.supabase_url}/storage/v1/object/{bucket}/{encoded_path}"

    def _select(
        self,
        table: str,
        *,
        select: str = "*",
        filters: dict[str, str] | None = None,
        order: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        params = {"select": select}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)
        result = self._request_json("GET", self._rest_url(table, params=params))
        return result if isinstance(result, list) else []

    def _insert(
        self,
        table: str,
        rows: dict[str, Any] | list[dict[str, Any]],
        *,
        return_representation: bool = False,
    ) -> list[dict[str, Any]]:
        prefer = "return=representation" if return_representation else "return=minimal"
        headers = {**self._headers(), "Prefer": prefer}
        result = self._request_json("POST", self._rest_url(table), payload=rows, headers=headers)
        if isinstance(result, dict):
            return [result]
        return result if isinstance(result, list) else []

    def _update(
        self,
        table: str,
        row: dict[str, Any],
        *,
        filters: dict[str, str],
        return_representation: bool = False,
    ) -> list[dict[str, Any]]:
        prefer = "return=representation" if return_representation else "return=minimal"
        headers = {**self._headers(), "Prefer": prefer}
        result = self._request_json(
            "PATCH",
            self._rest_url(table, params=filters),
            payload=row,
            headers=headers,
        )
        if isinstance(result, dict):
            return [result]
        return result if isinstance(result, list) else []

    def _upsert(
        self,
        table: str,
        rows: dict[str, Any] | list[dict[str, Any]],
        *,
        on_conflict: str,
        return_representation: bool = False,
    ) -> list[dict[str, Any]]:
        prefer = "resolution=merge-duplicates"
        prefer += ",return=representation" if return_representation else ",return=minimal"
        headers = {**self._headers(), "Prefer": prefer}
        result = self._request_json(
            "POST",
            self._rest_url(table, params={"on_conflict": on_conflict}),
            payload=rows,
            headers=headers,
        )
        if isinstance(result, dict):
            return [result]
        return result if isinstance(result, list) else []

    def _delete(self, table: str, *, filters: dict[str, str]) -> None:
        headers = {**self._headers(), "Prefer": "return=minimal"}
        self._request_json(
            "DELETE",
            self._rest_url(table, params=filters),
            headers=headers,
        )

    def _list_storage_objects(self, prefix: str, *, limit: int = 1000) -> list[str]:
        """Recursively list object names under a bucket prefix."""
        url = f"{self.supabase_url}/storage/v1/object/list/{self.channel_artifacts_bucket}"
        results: list[str] = []
        stack = [prefix.rstrip("/")]
        while stack:
            current = stack.pop()
            offset = 0
            while True:
                payload = {
                    "prefix": current,
                    "limit": limit,
                    "offset": offset,
                    "sortBy": {"column": "name", "order": "asc"},
                }
                try:
                    body = self._request_json("POST", url, payload=payload)
                except SupabaseStorageError:
                    body = []
                if not isinstance(body, list) or not body:
                    break
                for item in body:
                    name = item.get("name") if isinstance(item, dict) else None
                    if not name:
                        continue
                    full = f"{current}/{name}" if current else name
                    metadata = item.get("metadata") if isinstance(item, dict) else None
                    if metadata is None and item.get("id") is None:
                        stack.append(full)
                    else:
                        results.append(full)
                if len(body) < limit:
                    break
                offset += limit
        return results

    def _delete_storage_objects(self, paths: list[str]) -> None:
        if not paths:
            return
        url = f"{self.supabase_url}/storage/v1/object/{self.channel_artifacts_bucket}"
        # Bulk delete in batches of 100
        for i in range(0, len(paths), 100):
            batch = paths[i : i + 100]
            body = json.dumps({"prefixes": batch}).encode("utf-8")
            try:
                self._request("DELETE", url, body=body, headers=self._headers())
            except SupabaseStorageError:
                continue

    def _upload_json(self, path: str, data: dict[str, Any]) -> str:
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        headers = {
            **self._headers(content_type="application/json"),
            "x-upsert": "true",
        }
        self._request(
            "POST",
            self._storage_url(self.channel_artifacts_bucket, path),
            body=body,
            headers=headers,
        )
        return hashlib.sha256(body).hexdigest()

    def _download_json(self, path: str) -> dict[str, Any] | None:
        try:
            raw = self._request(
                "GET",
                self._storage_url(self.channel_artifacts_bucket, path),
                headers=self._headers(content_type=None),
            )
        except SupabaseStorageError as exc:
            if exc.status_code == 404:
                return None
            raise
        if not raw:
            return None
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else None

    @staticmethod
    def _eq(value: str) -> str:
        return f"eq.{value}"

    @staticmethod
    def _is_null() -> str:
        return "is.null"

    def _channel_row(self, owner_id: str, channel_id: str) -> dict[str, Any] | None:
        filters = {"owner_id": self._eq(owner_id)}
        if _is_uuid(channel_id):
            rows = self._select(
                "channels",
                filters={**filters, "id": self._eq(channel_id)},
                limit=1,
            )
            if rows:
                return rows[0]
        rows = self._select(
            "channels",
            filters={**filters, "youtube_channel_id": self._eq(channel_id)},
            limit=1,
        )
        return rows[0] if rows else None

    def _resolve_channel_id(self, owner_id: str, channel_id: str) -> str:
        row = self._channel_row(owner_id, channel_id)
        if not row:
            raise StorageError(f"Channel not found in Supabase storage: {channel_id}")
        return str(row["id"])

    def _video_rows(self, owner_id: str, channel_id: str) -> list[dict[str, Any]]:
        db_channel_id = self._resolve_channel_id(owner_id, channel_id)
        return self._select(
            "videos",
            filters={
                "owner_id": self._eq(owner_id),
                "channel_id": self._eq(db_channel_id),
            },
            order="upload_date.desc",
        )

    def _video_row(
        self,
        owner_id: str,
        channel_id: str,
        video_id: str,
    ) -> dict[str, Any] | None:
        db_channel_id = self._resolve_channel_id(owner_id, channel_id)
        filters = {
            "owner_id": self._eq(owner_id),
            "channel_id": self._eq(db_channel_id),
        }
        if _is_uuid(video_id):
            rows = self._select(
                "videos",
                filters={**filters, "id": self._eq(video_id)},
                limit=1,
            )
            if rows:
                return rows[0]
        rows = self._select(
            "videos",
            filters={**filters, "youtube_video_id": self._eq(video_id)},
            limit=1,
        )
        return rows[0] if rows else None

    def _resolve_video_id(self, owner_id: str, channel_id: str, video_id: str) -> str:
        row = self._video_row(owner_id, channel_id, video_id)
        if not row:
            raise StorageError(f"Video not found in Supabase storage: {video_id}")
        return str(row["id"])

    @staticmethod
    def _channel_meta(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "channel_id": row.get("youtube_channel_id"),
            "youtube_channel_id": row.get("youtube_channel_id"),
            "storage_channel_id": row.get("id"),
            "channel_name": row.get("channel_name"),
            "channel_handle": row.get("channel_handle"),
            "avatar_url": row.get("avatar_url"),
        }

    @staticmethod
    def _video_dict(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("youtube_video_id"),
            "youtube_video_id": row.get("youtube_video_id"),
            "storage_video_id": row.get("id"),
            "title": row.get("title") or "",
            "upload_date": row.get("upload_date") or "",
            "duration": row.get("duration") or 0,
            "view_count": row.get("view_count") or 0,
            "thumbnail": row.get("thumbnail") or "",
            "is_short": bool(row.get("is_short")),
        }

    @staticmethod
    def artifact_path(
        owner_id: str,
        channel_id: str,
        run_id: str,
        kind: str,
        *,
        video_id: str | None = None,
    ) -> str:
        safe_run_id = run_id or DEFAULT_RUN_ID
        if kind == "transcript":
            if not video_id:
                raise StorageError("video_id is required for transcript artifacts")
            return f"{owner_id}/{channel_id}/{safe_run_id}/transcripts/{video_id}.json"
        if kind == "summary":
            if not video_id:
                raise StorageError("video_id is required for summary artifacts")
            return f"{owner_id}/{channel_id}/{safe_run_id}/summaries/{video_id}.json"
        if kind == "profile":
            return f"{owner_id}/{channel_id}/{safe_run_id}/profile.json"
        raise StorageError(f"Unsupported artifact kind: {kind}")

    def _latest_artifact_path(
        self,
        owner_id: str,
        channel_id: str,
        kind: str,
        *,
        video_id: str | None = None,
    ) -> str | None:
        filters = {
            "owner_id": self._eq(owner_id),
            "channel_id": self._eq(channel_id),
            "kind": self._eq(kind),
        }
        filters["video_id"] = self._eq(video_id) if video_id else self._is_null()
        rows = self._select(
            "artifacts",
            select="storage_path",
            filters=filters,
            order="created_at.desc",
            limit=1,
        )
        if not rows:
            return None
        storage_path = rows[0].get("storage_path")
        return str(storage_path) if storage_path else None

    def _save_json_artifact(
        self,
        *,
        owner_id: str,
        channel_id: str,
        run_id: str,
        kind: str,
        data: dict[str, Any],
        video_id: str | None = None,
    ) -> None:
        path = self.artifact_path(owner_id, channel_id, run_id, kind, video_id=video_id)
        digest = self._upload_json(path, data)
        db_run_id = run_id if _is_uuid(run_id) else None
        row = {
            "owner_id": owner_id,
            "channel_id": channel_id,
            "run_id": db_run_id,
            "video_id": video_id,
            "kind": kind,
            "schema_version": _positive_int(data.get("schema_version")),
            "storage_path": path,
            "hash": digest,
        }
        self._upsert("artifacts", row, on_conflict="storage_path")

    def load_channel_meta(self, owner_id: str, channel_id: str) -> dict[str, Any] | None:
        row = self._channel_row(owner_id, channel_id)
        return self._channel_meta(row) if row else None

    def save_channel_meta(self, owner_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        youtube_channel_id = str(data.get("youtube_channel_id") or data.get("channel_id") or "")
        channel_name = str(data.get("channel_name") or "").strip()
        if not youtube_channel_id:
            raise StorageError("Channel metadata must include channel_id or youtube_channel_id")
        if not channel_name:
            raise StorageError("Channel metadata must include channel_name")
        row = {
            "owner_id": owner_id,
            "youtube_channel_id": youtube_channel_id,
            "channel_name": channel_name,
            "channel_handle": data.get("channel_handle"),
            "avatar_url": data.get("avatar_url"),
        }
        rows = self._upsert(
            "channels",
            row,
            on_conflict="owner_id,youtube_channel_id",
            return_representation=True,
        )
        return self._channel_meta(rows[0]) if rows else None

    def load_videos(self, owner_id: str, channel_id: str) -> list[dict[str, Any]] | None:
        rows = self._video_rows(owner_id, channel_id)
        return [self._video_dict(row) for row in rows]

    def save_videos(
        self,
        owner_id: str,
        channel_id: str,
        videos: list[dict[str, Any]],
    ) -> None:
        db_channel_id = self._resolve_channel_id(owner_id, channel_id)
        rows = []
        for video in videos:
            youtube_video_id = str(video.get("youtube_video_id") or video.get("id") or "")
            if not youtube_video_id:
                raise StorageError("Video metadata must include id or youtube_video_id")
            duration = int(video.get("duration") or 0)
            is_short = video.get("is_short")
            rows.append(
                {
                    "owner_id": owner_id,
                    "channel_id": db_channel_id,
                    "youtube_video_id": youtube_video_id,
                    "title": str(video.get("title") or "Untitled"),
                    "upload_date": video.get("upload_date") or None,
                    "duration": duration,
                    "view_count": int(video.get("view_count") or 0),
                    "thumbnail": video.get("thumbnail") or None,
                    "is_short": bool(is_short) if is_short is not None else 0 < duration <= 60,
                }
            )
        if rows:
            self._upsert("videos", rows, on_conflict="channel_id,youtube_video_id")

    def load_selection(self, owner_id: str, channel_id: str) -> list[str] | None:
        db_channel_id = self._resolve_channel_id(owner_id, channel_id)
        selection_rows = self._select(
            "video_selections",
            select="video_id",
            filters={
                "owner_id": self._eq(owner_id),
                "channel_id": self._eq(db_channel_id),
                "selected": "eq.true",
            },
        )
        if not selection_rows:
            return None
        video_rows = self._video_rows(owner_id, db_channel_id)
        youtube_by_id = {str(row["id"]): str(row["youtube_video_id"]) for row in video_rows}
        return [
            youtube_by_id.get(str(row["video_id"]), str(row["video_id"]))
            for row in selection_rows
        ]

    def save_selection(self, owner_id: str, channel_id: str, video_ids: list[str]) -> None:
        db_channel_id = self._resolve_channel_id(owner_id, channel_id)
        videos = self._video_rows(owner_id, db_channel_id)
        id_by_any_id: dict[str, str] = {}
        for row in videos:
            db_video_id = str(row["id"])
            id_by_any_id[db_video_id] = db_video_id
            id_by_any_id[str(row["youtube_video_id"])] = db_video_id

        missing = [video_id for video_id in video_ids if video_id not in id_by_any_id]
        if missing:
            preview = ", ".join(missing[:3])
            raise StorageError(f"Cannot save selection for unknown videos: {preview}")

        self._delete(
            "video_selections",
            filters={
                "owner_id": self._eq(owner_id),
                "channel_id": self._eq(db_channel_id),
            },
        )
        rows = [
            {
                "owner_id": owner_id,
                "channel_id": db_channel_id,
                "video_id": id_by_any_id[video_id],
                "selected": True,
            }
            for video_id in video_ids
        ]
        if rows:
            self._upsert("video_selections", rows, on_conflict="channel_id,video_id")

    def load_transcript(
        self,
        owner_id: str,
        channel_id: str,
        video_id: str,
    ) -> dict[str, Any] | None:
        db_channel_id = self._resolve_channel_id(owner_id, channel_id)
        db_video_id = self._resolve_video_id(owner_id, db_channel_id, video_id)
        path = self._latest_artifact_path(
            owner_id,
            db_channel_id,
            "transcript",
            video_id=db_video_id,
        )
        return self._download_json(path) if path else None

    def save_transcript(
        self,
        owner_id: str,
        channel_id: str,
        run_id: str,
        video_id: str,
        data: dict[str, Any],
    ) -> None:
        db_channel_id = self._resolve_channel_id(owner_id, channel_id)
        db_video_id = self._resolve_video_id(owner_id, db_channel_id, video_id)
        self._save_json_artifact(
            owner_id=owner_id,
            channel_id=db_channel_id,
            run_id=run_id,
            kind="transcript",
            data=data,
            video_id=db_video_id,
        )

    def load_summary(
        self,
        owner_id: str,
        channel_id: str,
        video_id: str,
    ) -> dict[str, Any] | None:
        db_channel_id = self._resolve_channel_id(owner_id, channel_id)
        db_video_id = self._resolve_video_id(owner_id, db_channel_id, video_id)
        path = self._latest_artifact_path(
            owner_id,
            db_channel_id,
            "summary",
            video_id=db_video_id,
        )
        return self._download_json(path) if path else None

    def save_summary(
        self,
        owner_id: str,
        channel_id: str,
        run_id: str,
        video_id: str,
        data: dict[str, Any],
    ) -> None:
        db_channel_id = self._resolve_channel_id(owner_id, channel_id)
        db_video_id = self._resolve_video_id(owner_id, db_channel_id, video_id)
        self._save_json_artifact(
            owner_id=owner_id,
            channel_id=db_channel_id,
            run_id=run_id,
            kind="summary",
            data=data,
            video_id=db_video_id,
        )

    def load_profile(self, owner_id: str, channel_id: str) -> dict[str, Any] | None:
        db_channel_id = self._resolve_channel_id(owner_id, channel_id)
        rows = self._select(
            "channel_profiles",
            select="profile",
            filters={
                "owner_id": self._eq(owner_id),
                "channel_id": self._eq(db_channel_id),
            },
            order="generated_at.desc",
            limit=1,
        )
        if rows and isinstance(rows[0].get("profile"), dict):
            return rows[0]["profile"]
        path = self._latest_artifact_path(owner_id, db_channel_id, "profile")
        return self._download_json(path) if path else None

    def save_profile(
        self,
        owner_id: str,
        channel_id: str,
        run_id: str,
        data: dict[str, Any],
    ) -> None:
        db_channel_id = self._resolve_channel_id(owner_id, channel_id)
        self._save_json_artifact(
            owner_id=owner_id,
            channel_id=db_channel_id,
            run_id=run_id,
            kind="profile",
            data=data,
        )
        self._insert(
            "channel_profiles",
            {
                "owner_id": owner_id,
                "channel_id": db_channel_id,
                "run_id": run_id if _is_uuid(run_id) else None,
                "schema_version": _positive_int(data.get("schema_version")) or 1,
                "profile": data,
            },
        )

    def _chat_session_summary_from_row(
        self,
        owner_id: str,
        channel_id: str,
        row: dict[str, Any],
        *,
        message_count: int | None = None,
    ) -> dict[str, Any]:
        count = message_count
        if count is None:
            count = len(
                self._select(
                    "chat_messages",
                    select="id",
                    filters={
                        "owner_id": self._eq(owner_id),
                        "session_id": self._eq(str(row["id"])),
                    },
                )
            )
        return {
            "id": str(row["id"]),
            "channel_id": channel_id,
            "title": _clean_chat_title(row.get("title")),
            "created_at": str(row.get("created_at") or ""),
            "updated_at": str(row.get("updated_at") or row.get("created_at") or ""),
            "message_count": count,
        }

    def _chat_session_row(
        self,
        owner_id: str,
        channel_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        db_channel_id = self._resolve_channel_id(owner_id, channel_id)
        rows = self._select(
            "chat_sessions",
            filters={
                "owner_id": self._eq(owner_id),
                "channel_id": self._eq(db_channel_id),
                "id": self._eq(session_id),
            },
            limit=1,
        )
        return rows[0] if rows else None

    def list_chat_sessions(self, owner_id: str, channel_id: str) -> list[dict[str, Any]]:
        db_channel_id = self._resolve_channel_id(owner_id, channel_id)
        rows = self._select(
            "chat_sessions",
            filters={
                "owner_id": self._eq(owner_id),
                "channel_id": self._eq(db_channel_id),
            },
            order="updated_at.desc",
        )
        return [
            self._chat_session_summary_from_row(owner_id, channel_id, row)
            for row in rows
        ]

    def create_chat_session(
        self,
        owner_id: str,
        channel_id: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        db_channel_id = self._resolve_channel_id(owner_id, channel_id)
        rows = self._insert(
            "chat_sessions",
            {
                "owner_id": owner_id,
                "channel_id": db_channel_id,
                "title": _clean_chat_title(title),
            },
            return_representation=True,
        )
        if not rows:
            raise StorageError("Failed to create chat session")
        return self._chat_session_summary_from_row(
            owner_id,
            channel_id,
            rows[0],
            message_count=0,
        )

    def load_chat_session(
        self,
        owner_id: str,
        channel_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        session_row = self._chat_session_row(owner_id, channel_id, session_id)
        if not session_row:
            return None
        rows = self._select(
            "chat_messages",
            filters={
                "owner_id": self._eq(owner_id),
                "session_id": self._eq(session_id),
            },
            order="sequence.asc",
        )
        messages = [
            {
                "id": str(row["id"]),
                "role": row.get("role"),
                "content": row.get("content") or "",
                "sources": row.get("sources") if isinstance(row.get("sources"), list) else [],
                "unknown_source_ids": (
                    row.get("unknown_source_ids")
                    if isinstance(row.get("unknown_source_ids"), list)
                    else []
                ),
                "created_at": str(row.get("created_at") or ""),
                "sequence": int(row.get("sequence") or 0),
            }
            for row in rows
        ]
        return {
            "session": self._chat_session_summary_from_row(
                owner_id,
                channel_id,
                session_row,
                message_count=len(messages),
            ),
            "messages": messages,
        }

    def rename_chat_session(
        self,
        owner_id: str,
        channel_id: str,
        session_id: str,
        title: str,
    ) -> dict[str, Any] | None:
        session_row = self._chat_session_row(owner_id, channel_id, session_id)
        if not session_row:
            return None
        rows = self._update(
            "chat_sessions",
            {"title": _clean_chat_title(title)},
            filters={
                "owner_id": self._eq(owner_id),
                "id": self._eq(session_id),
            },
            return_representation=True,
        )
        row = rows[0] if rows else {**session_row, "title": title}
        return self._chat_session_summary_from_row(owner_id, channel_id, row)

    def delete_chat_session(self, owner_id: str, channel_id: str, session_id: str) -> bool:
        if not self._chat_session_row(owner_id, channel_id, session_id):
            return False
        self._delete(
            "chat_sessions",
            filters={
                "owner_id": self._eq(owner_id),
                "id": self._eq(session_id),
            },
        )
        return True

    def append_chat_messages(
        self,
        owner_id: str,
        channel_id: str,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        session_row = self._chat_session_row(owner_id, channel_id, session_id)
        if not session_row:
            return None
        db_channel_id = str(session_row["channel_id"])
        latest = self._select(
            "chat_messages",
            select="sequence",
            filters={
                "owner_id": self._eq(owner_id),
                "session_id": self._eq(session_id),
            },
            order="sequence.desc",
            limit=1,
        )
        max_sequence = int(latest[0].get("sequence") or 0) if latest else 0
        rows = []
        for offset, message in enumerate(messages, start=1):
            role = str(message.get("role") or "").strip()
            content = str(message.get("content") or "")
            if role not in {"user", "assistant"} or not content.strip():
                continue
            sources = message.get("sources")
            unknown_source_ids = message.get("unknown_source_ids")
            rows.append(
                {
                    "owner_id": owner_id,
                    "channel_id": db_channel_id,
                    "session_id": session_id,
                    "role": role,
                    "content": content,
                    "sources": sources if isinstance(sources, list) else [],
                    "unknown_source_ids": (
                        unknown_source_ids if isinstance(unknown_source_ids, list) else []
                    ),
                    "sequence": max_sequence + offset,
                }
            )
        if rows:
            self._insert("chat_messages", rows)
            self._update(
                "chat_sessions",
                {"updated_at": _utc_now_iso()},
                filters={"owner_id": self._eq(owner_id), "id": self._eq(session_id)},
            )
        fresh_row = self._chat_session_row(owner_id, channel_id, session_id) or session_row
        return self._chat_session_summary_from_row(owner_id, channel_id, fresh_row)

    def list_channels(self, owner_id: str) -> list[dict[str, Any]]:
        rows = self._select(
            "channels",
            filters={"owner_id": self._eq(owner_id)},
            order="updated_at.desc.nullslast",
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            db_channel_id = str(row["id"])
            video_count = len(
                self._select(
                    "videos",
                    select="id",
                    filters={
                        "owner_id": self._eq(owner_id),
                        "channel_id": self._eq(db_channel_id),
                    },
                )
            )
            profiles = self._select(
                "channel_profiles",
                select="id",
                filters={
                    "owner_id": self._eq(owner_id),
                    "channel_id": self._eq(db_channel_id),
                },
                limit=1,
            )
            latest_runs = self._select(
                "pipeline_runs",
                select="status,started_at,completed_at,created_at",
                filters={
                    "owner_id": self._eq(owner_id),
                    "channel_id": self._eq(db_channel_id),
                },
                order="created_at.desc",
                limit=1,
            )
            latest = latest_runs[0] if latest_runs else {}
            out.append(
                {
                    "channel_id": row.get("youtube_channel_id"),
                    "channel_name": row.get("channel_name"),
                    "channel_handle": row.get("channel_handle"),
                    "avatar_url": row.get("avatar_url"),
                    "video_count": video_count,
                    "has_profile": bool(profiles),
                    "latest_run_status": latest.get("status"),
                    "updated_at": (
                        latest.get("completed_at")
                        or latest.get("started_at")
                        or latest.get("created_at")
                        or row.get("updated_at")
                    ),
                }
            )
        return out

    def delete_channel(self, owner_id: str, channel_id: str) -> bool:
        row = self._channel_row(owner_id, channel_id)
        if not row:
            return False
        db_channel_id = str(row["id"])
        prefix = f"{owner_id}/{db_channel_id}"
        paths = self._list_storage_objects(prefix)
        if paths:
            self._delete_storage_objects(paths)
        # Delete dependent rows explicitly in case schema lacks ON DELETE CASCADE
        for table in (
            "chat_messages",
            "chat_sessions",
            "caption_chunks",
            "video_selections",
            "pipeline_run_videos",
            "channel_profiles",
            "artifacts",
            "videos",
            "pipeline_runs",
        ):
            self._delete(
                table,
                filters={
                    "owner_id": self._eq(owner_id),
                    "channel_id": self._eq(db_channel_id),
                },
            )
        self._delete(
            "channels",
            filters={"owner_id": self._eq(owner_id), "id": self._eq(db_channel_id)},
        )
        return True

    def save_waitlist_entry(self, data: dict[str, Any]) -> dict[str, Any]:
        row = _waitlist_payload(data)
        rows = self._upsert(
            "waitlist_entries",
            row,
            on_conflict="normalized_email",
            return_representation=True,
        )
        return rows[0] if rows else row


def get_storage_backend() -> StorageBackend:
    """Return the configured owner-aware storage backend."""
    backend = os.environ.get("STORAGE_BACKEND", "local").strip().lower()
    if backend in {"", "local"}:
        return LocalStorageBackend()
    if backend == "supabase":
        return SupabaseStorageBackend.from_env()
    raise StorageConfigError(
        f"Unsupported STORAGE_BACKEND={backend!r}; expected 'local' or 'supabase'"
    )


def _backend_for_owner(owner_id: str | None = None) -> StorageBackend:
    if _effective_owner_id(owner_id):
        return get_storage_backend()
    return LocalStorageBackend()


def get_channel_dir(channel_id: str, *, owner_id: str | None = None) -> Path:
    """Return the local directory for a specific channel."""
    return LocalStorageBackend().get_channel_dir(channel_id, _effective_owner_id(owner_id))


def read_json(path: Path) -> JsonData | None:
    """Read JSON from local disk if it exists."""
    return LocalStorageBackend().read_json(path)


def write_json(path: Path, data: JsonData) -> None:
    """Write JSON to local disk atomically."""
    LocalStorageBackend().write_json(path, data)


def load_channel_meta(channel_id: str, *, owner_id: str | None = None) -> dict[str, Any] | None:
    """Load channel metadata.

    Legacy callers omit owner_id and continue to read local disk. Owner-aware callers
    use the configured backend selected by STORAGE_BACKEND.
    """
    owner = _effective_owner_id(owner_id)
    return _backend_for_owner(owner).load_channel_meta(owner or LOCAL_OWNER_ID, channel_id)


def save_channel_meta(
    channel_id: str,
    data: dict[str, Any],
    *,
    owner_id: str | None = None,
) -> dict[str, Any] | None:
    """Persist channel metadata without breaking the original local call signature."""
    owner = _effective_owner_id(owner_id)
    payload = {**data, "channel_id": data.get("channel_id") or channel_id}
    return _backend_for_owner(owner).save_channel_meta(owner or LOCAL_OWNER_ID, payload)


def load_videos(channel_id: str, *, owner_id: str | None = None) -> list[dict[str, Any]] | None:
    """Load cached videos without breaking the original local call signature."""
    owner = _effective_owner_id(owner_id)
    return _backend_for_owner(owner).load_videos(owner or LOCAL_OWNER_ID, channel_id)


def save_videos(
    channel_id: str,
    videos: list[dict[str, Any]],
    *,
    owner_id: str | None = None,
) -> None:
    """Persist videos without breaking the original local call signature."""
    owner = _effective_owner_id(owner_id)
    _backend_for_owner(owner).save_videos(owner or LOCAL_OWNER_ID, channel_id, videos)


def load_selection(channel_id: str, *, owner_id: str | None = None) -> list[str] | None:
    """Load selected videos without breaking the original local call signature."""
    owner = _effective_owner_id(owner_id)
    return _backend_for_owner(owner).load_selection(owner or LOCAL_OWNER_ID, channel_id)


def save_selection(
    channel_id: str,
    video_ids: list[str],
    *,
    owner_id: str | None = None,
) -> None:
    """Persist selected videos without breaking the original local call signature."""
    owner = _effective_owner_id(owner_id)
    _backend_for_owner(owner).save_selection(owner or LOCAL_OWNER_ID, channel_id, video_ids)


def load_transcript(
    channel_id: str,
    video_id: str,
    *,
    owner_id: str | None = None,
) -> dict[str, Any] | None:
    """Load one transcript through the local or owner-aware backend."""
    owner = _effective_owner_id(owner_id)
    return _backend_for_owner(owner).load_transcript(
        owner or LOCAL_OWNER_ID,
        channel_id,
        video_id,
    )


def save_transcript(
    channel_id: str,
    run_id: str,
    video_id: str,
    data: dict[str, Any],
    *,
    owner_id: str | None = None,
) -> None:
    """Persist one transcript through the local or owner-aware backend."""
    owner = _effective_owner_id(owner_id)
    resolved_run_id = _effective_run_id(run_id)
    _backend_for_owner(owner).save_transcript(
        owner or LOCAL_OWNER_ID,
        channel_id,
        resolved_run_id,
        video_id,
        data,
    )


def load_summary(
    channel_id: str,
    video_id: str,
    *,
    owner_id: str | None = None,
) -> dict[str, Any] | None:
    """Load one summary through the local or owner-aware backend."""
    owner = _effective_owner_id(owner_id)
    return _backend_for_owner(owner).load_summary(
        owner or LOCAL_OWNER_ID,
        channel_id,
        video_id,
    )


def save_summary(
    channel_id: str,
    run_id: str,
    video_id: str,
    data: dict[str, Any],
    *,
    owner_id: str | None = None,
) -> None:
    """Persist one summary through the local or owner-aware backend."""
    owner = _effective_owner_id(owner_id)
    resolved_run_id = _effective_run_id(run_id)
    _backend_for_owner(owner).save_summary(
        owner or LOCAL_OWNER_ID,
        channel_id,
        resolved_run_id,
        video_id,
        data,
    )


def load_profile(channel_id: str, *, owner_id: str | None = None) -> dict[str, Any] | None:
    """Load the latest profile through the local or owner-aware backend."""
    owner = _effective_owner_id(owner_id)
    return _backend_for_owner(owner).load_profile(owner or LOCAL_OWNER_ID, channel_id)


def save_profile(
    channel_id: str,
    run_id: str,
    data: dict[str, Any],
    *,
    owner_id: str | None = None,
) -> None:
    """Persist one profile through the local or owner-aware backend."""
    owner = _effective_owner_id(owner_id)
    resolved_run_id = _effective_run_id(run_id)
    _backend_for_owner(owner).save_profile(
        owner or LOCAL_OWNER_ID,
        channel_id,
        resolved_run_id,
        data,
    )


def list_chat_sessions(
    channel_id: str,
    *,
    owner_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return saved chat sessions for one channel."""
    owner = _effective_owner_id(owner_id)
    return _backend_for_owner(owner).list_chat_sessions(owner or LOCAL_OWNER_ID, channel_id)


def create_chat_session(
    channel_id: str,
    title: str | None = None,
    *,
    owner_id: str | None = None,
) -> dict[str, Any]:
    """Create a saved chat session for one channel."""
    owner = _effective_owner_id(owner_id)
    return _backend_for_owner(owner).create_chat_session(
        owner or LOCAL_OWNER_ID,
        channel_id,
        title,
    )


def load_chat_session(
    channel_id: str,
    session_id: str,
    *,
    owner_id: str | None = None,
) -> dict[str, Any] | None:
    """Load one saved chat session and its messages."""
    owner = _effective_owner_id(owner_id)
    return _backend_for_owner(owner).load_chat_session(
        owner or LOCAL_OWNER_ID,
        channel_id,
        session_id,
    )


def rename_chat_session(
    channel_id: str,
    session_id: str,
    title: str,
    *,
    owner_id: str | None = None,
) -> dict[str, Any] | None:
    """Rename one saved chat session."""
    owner = _effective_owner_id(owner_id)
    return _backend_for_owner(owner).rename_chat_session(
        owner or LOCAL_OWNER_ID,
        channel_id,
        session_id,
        title,
    )


def delete_chat_session(
    channel_id: str,
    session_id: str,
    *,
    owner_id: str | None = None,
) -> bool:
    """Delete one saved chat session."""
    owner = _effective_owner_id(owner_id)
    return _backend_for_owner(owner).delete_chat_session(
        owner or LOCAL_OWNER_ID,
        channel_id,
        session_id,
    )


def append_chat_messages(
    channel_id: str,
    session_id: str,
    messages: list[dict[str, Any]],
    *,
    owner_id: str | None = None,
) -> dict[str, Any] | None:
    """Append messages to a saved chat session."""
    owner = _effective_owner_id(owner_id)
    return _backend_for_owner(owner).append_chat_messages(
        owner or LOCAL_OWNER_ID,
        channel_id,
        session_id,
        messages,
    )


def list_channels(*, owner_id: str | None = None) -> list[dict[str, Any]]:
    """Return owner's channel summaries via the configured backend."""
    owner = _effective_owner_id(owner_id)
    return _backend_for_owner(owner).list_channels(owner or LOCAL_OWNER_ID)


def delete_channel(channel_id: str, *, owner_id: str | None = None) -> bool:
    """Cascade-delete a channel via the configured backend."""
    owner = _effective_owner_id(owner_id)
    return _backend_for_owner(owner).delete_channel(owner or LOCAL_OWNER_ID, channel_id)


def save_waitlist_entry(
    email: str,
    *,
    youtube_channel: str | None = None,
    source: str = "waitlist_page",
    user_agent: str | None = None,
    referrer: str | None = None,
) -> dict[str, Any]:
    """Persist or update a public launch waitlist entry."""
    return get_storage_backend().save_waitlist_entry(
        {
            "email": email,
            "youtube_channel": youtube_channel,
            "source": source,
            "user_agent": user_agent,
            "referrer": referrer,
        }
    )


def load_playlists(channel_id: str, *, owner_id: str | None = None) -> list[dict[str, Any]] | None:
    """Load cached playlists from local disk."""
    return LocalStorageBackend().load_playlists(channel_id, _effective_owner_id(owner_id))


def save_playlists(
    channel_id: str,
    playlists: list[dict[str, Any]],
    *,
    owner_id: str | None = None,
) -> None:
    """Persist playlists to local disk."""
    LocalStorageBackend().save_playlists(channel_id, playlists, _effective_owner_id(owner_id))


def load_playlist_video_ids(
    channel_id: str,
    playlist_id: str,
    *,
    owner_id: str | None = None,
) -> list[str] | None:
    """Load cached playlist video IDs from local disk."""
    return LocalStorageBackend().load_playlist_video_ids(
        channel_id,
        playlist_id,
        _effective_owner_id(owner_id),
    )


def save_playlist_video_ids(
    channel_id: str,
    playlist_id: str,
    video_ids: list[str],
    *,
    owner_id: str | None = None,
) -> None:
    """Persist playlist video IDs to local disk."""
    LocalStorageBackend().save_playlist_video_ids(
        channel_id,
        playlist_id,
        video_ids,
        _effective_owner_id(owner_id),
    )
