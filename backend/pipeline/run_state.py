"""Durable pipeline run state for local and Supabase backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from backend import storage

RUN_FINAL_STATUSES = {"completed", "failed", "cancelled"}
VIDEO_FINAL_STATUSES = {"done", "completed", "skipped", "unavailable", "failed"}
STAGE_STATUS_COLUMNS = {
    "transcripts": "transcript_status",
    "chunks": "chunk_status",
    "summaries": "summary_status",
}


def utc_now_iso() -> str:
    """Return an ISO 8601 UTC timestamp suitable for PostgREST payloads."""
    return datetime.now(timezone.utc).isoformat()


def from_stage_for_run(run: dict[str, Any] | None) -> str:
    """Choose the idempotent pipeline entry point for a claimed run."""
    current_stage = (run or {}).get("current_stage")
    if current_stage in {"summaries", "profile", "awaiting_confirm_summaries"}:
        return "summaries"
    return "transcripts"


class PipelineRunStore(ABC):
    """Persistence API for the pipeline route and worker."""

    is_durable = False

    @abstractmethod
    def create_run(self, owner_id: str, channel_id: str) -> dict[str, Any]:
        """Create a queued run and return its row-like metadata."""

    @abstractmethod
    def latest_run(self, owner_id: str, channel_id: str) -> dict[str, Any] | None:
        """Return the most recent run for a channel."""

    @abstractmethod
    def read_state(self, owner_id: str, channel_id: str) -> dict[str, Any] | None:
        """Return the frontend pipeline state for a channel."""

    @abstractmethod
    def write_state(self, owner_id: str, channel_id: str, state: dict[str, Any]) -> None:
        """Persist a frontend-shaped state snapshot."""

    @abstractmethod
    def claim_next_run(self) -> dict[str, Any] | None:
        """Claim one queued run for worker processing."""

    @abstractmethod
    def queue_resume(self, owner_id: str, channel_id: str) -> dict[str, Any] | None:
        """Move an awaiting run back to the queued state."""

    @abstractmethod
    def cancel_latest(self, owner_id: str, channel_id: str) -> dict[str, Any]:
        """Persist cancellation for the latest run."""

    @abstractmethod
    def is_cancelled(self, owner_id: str, channel_id: str, run_id: str | None) -> bool:
        """Return whether the current run should stop."""

    @abstractmethod
    def retry_failed(self, owner_id: str, run_id: str) -> dict[str, Any] | None:
        """Reset failed work in a run and re-queue it. Return updated run row."""

    def requeue_interrupted_runs(self) -> None:
        """Prepare interrupted work for a new worker process."""


class LocalPipelineRunStore(PipelineRunStore):
    """Local development run store using one JSON state file per channel."""

    def _state_path(self, owner_id: str, channel_id: str):
        return (
            storage.LocalStorageBackend().get_channel_dir(channel_id, owner_id)
            / "pipeline_run_state.json"
        )

    def create_run(self, owner_id: str, channel_id: str) -> dict[str, Any]:
        run = {
            "id": str(uuid4()),
            "owner_id": owner_id,
            "channel_id": channel_id,
            "status": "queued",
            "current_stage": "transcripts",
            "created_at": utc_now_iso(),
        }
        self.write_state(
            owner_id,
            channel_id,
            {
                "run_id": run["id"],
                "owner_id": owner_id,
                "channel_id": channel_id,
                "status": "queued",
                "current_stage": "transcripts",
                "stages": {},
                "created_at": run["created_at"],
            },
        )
        return run

    def latest_run(self, owner_id: str, channel_id: str) -> dict[str, Any] | None:
        state = self.read_state(owner_id, channel_id)
        if not state:
            return None
        return {
            "id": state.get("run_id"),
            "owner_id": owner_id,
            "channel_id": channel_id,
            "status": state.get("status"),
            "current_stage": state.get("current_stage"),
            "started_at": state.get("started_at"),
            "completed_at": state.get("completed_at"),
            "created_at": state.get("created_at"),
        }

    def read_state(self, owner_id: str, channel_id: str) -> dict[str, Any] | None:
        data = storage.LocalStorageBackend().read_json(self._state_path(owner_id, channel_id))
        return data if isinstance(data, dict) else None

    def write_state(self, owner_id: str, channel_id: str, state: dict[str, Any]) -> None:
        payload = dict(state)
        payload.setdefault("run_id", str(uuid4()))
        payload.setdefault("owner_id", owner_id)
        payload.setdefault("channel_id", channel_id)
        payload.setdefault("created_at", utc_now_iso())
        if payload.get("status") in RUN_FINAL_STATUSES:
            payload.setdefault("completed_at", utc_now_iso())
        storage.LocalStorageBackend().write_json(self._state_path(owner_id, channel_id), payload)

    def claim_next_run(self) -> dict[str, Any] | None:
        return None

    def queue_resume(self, owner_id: str, channel_id: str) -> dict[str, Any] | None:
        state = self.read_state(owner_id, channel_id)
        if not state or state.get("status") not in {
            "awaiting_confirm_summaries",
            "cancelled",
            "failed",
        }:
            return None
        state["status"] = "queued"
        state["current_stage"] = "summaries"
        state.pop("completed_at", None)
        state.pop("error", None)
        self.write_state(owner_id, channel_id, state)
        return self.latest_run(owner_id, channel_id)

    def cancel_latest(self, owner_id: str, channel_id: str) -> dict[str, Any]:
        state = self.read_state(owner_id, channel_id) or {
            "run_id": str(uuid4()),
            "status": "idle",
            "stages": {},
        }
        state["status"] = "cancelled"
        state["completed_at"] = utc_now_iso()
        self.write_state(owner_id, channel_id, state)
        return state

    def is_cancelled(self, owner_id: str, channel_id: str, run_id: str | None) -> bool:
        state = self.read_state(owner_id, channel_id)
        if not state:
            return False
        if run_id and state.get("run_id") != run_id:
            return False
        return state.get("status") == "cancelled"

    def retry_failed(self, owner_id: str, run_id: str) -> dict[str, Any] | None:
        # Local store keys state by channel; locate the channel hosting this run.
        users_dir = (
            storage.LocalStorageBackend().get_data_dir() / "users" / owner_id / "channels"
            if owner_id and owner_id != storage.LOCAL_OWNER_ID
            else storage.LocalStorageBackend().get_data_dir() / "channels"
        )
        if not users_dir.exists():
            return None
        for entry in users_dir.iterdir():
            if not entry.is_dir():
                continue
            state = self.read_state(owner_id, entry.name)
            if not state or state.get("run_id") != run_id:
                continue
            retried = 0
            entry_stage = "summaries"
            for stage_id in ("transcripts", "chunks", "summaries"):
                stage = (state.get("stages") or {}).get(stage_id) or {}
                videos = stage.get("videos") or {}
                for video_id, vstate in videos.items():
                    if vstate.get("status") == "failed":
                        videos[video_id] = {**vstate, "status": "queued"}
                        retried += 1
                        if stage_id == "transcripts" or (
                            stage_id == "chunks" and entry_stage == "summaries"
                        ):
                            entry_stage = stage_id
                stage["videos"] = videos
                if videos and any(v.get("status") == "failed" for v in videos.values()) is False:
                    completed = sum(
                        1 for v in videos.values() if v.get("status") in VIDEO_FINAL_STATUSES
                    )
                    stage["completed"] = completed
            if retried == 0:
                return None
            state["status"] = "queued"
            state["current_stage"] = entry_stage
            state.pop("completed_at", None)
            state.pop("error", None)
            self.write_state(owner_id, entry.name, state)
            run = self.latest_run(owner_id, entry.name) or {}
            run["retried"] = retried
            return run
        return None


class SupabasePipelineRunStore(PipelineRunStore):
    """Supabase Postgres-backed run store using service-role PostgREST calls."""

    is_durable = True

    def __init__(self, backend: storage.SupabaseStorageBackend) -> None:
        self.backend = backend

    @staticmethod
    def _eq(value: str) -> str:
        return f"eq.{value}"

    def _update(
        self,
        table: str,
        values: dict[str, Any],
        *,
        filters: dict[str, str],
        return_representation: bool = False,
    ) -> list[dict[str, Any]]:
        prefer = "return=representation" if return_representation else "return=minimal"
        headers = {**self.backend._headers(), "Prefer": prefer}
        result = self.backend._request_json(
            "PATCH",
            self.backend._rest_url(table, params=filters),
            payload=values,
            headers=headers,
        )
        if isinstance(result, dict):
            return [result]
        return result if isinstance(result, list) else []

    def _run_by_id(self, owner_id: str, run_id: str) -> dict[str, Any] | None:
        rows = self.backend._select(
            "pipeline_runs",
            filters={"owner_id": self._eq(owner_id), "id": self._eq(run_id)},
            limit=1,
        )
        return rows[0] if rows else None

    def _db_channel_id(self, owner_id: str, channel_id: str) -> str:
        return self.backend._resolve_channel_id(owner_id, channel_id)

    def _video_maps(
        self,
        owner_id: str,
        db_channel_id: str,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        rows = self.backend._video_rows(owner_id, db_channel_id)
        by_db_id = {str(row["id"]): row for row in rows}
        db_id_by_any_id: dict[str, str] = {}
        for row in rows:
            db_id = str(row["id"])
            db_id_by_any_id[db_id] = db_id
            db_id_by_any_id[str(row["youtube_video_id"])] = db_id
        return by_db_id, db_id_by_any_id

    def create_run(self, owner_id: str, channel_id: str) -> dict[str, Any]:
        db_channel_id = self._db_channel_id(owner_id, channel_id)
        run_rows = self.backend._insert(
            "pipeline_runs",
            {
                "owner_id": owner_id,
                "channel_id": db_channel_id,
                "status": "queued",
                "current_stage": "transcripts",
            },
            return_representation=True,
        )
        if not run_rows:
            raise storage.StorageError("Failed to create pipeline run")
        run = run_rows[0]

        video_rows, db_id_by_any_id = self._video_maps(owner_id, db_channel_id)
        selected = self.backend.load_selection(owner_id, db_channel_id)
        if selected is None:
            selected = [str(row["youtube_video_id"]) for row in video_rows.values()]
        run_video_rows = [
            {
                "run_id": run["id"],
                "owner_id": owner_id,
                "channel_id": db_channel_id,
                "video_id": db_id_by_any_id[video_id],
            }
            for video_id in selected
            if video_id in db_id_by_any_id
        ]
        if run_video_rows:
            self.backend._insert("pipeline_run_videos", run_video_rows)
        return run

    def latest_run(self, owner_id: str, channel_id: str) -> dict[str, Any] | None:
        db_channel_id = self._db_channel_id(owner_id, channel_id)
        rows = self.backend._select(
            "pipeline_runs",
            filters={
                "owner_id": self._eq(owner_id),
                "channel_id": self._eq(db_channel_id),
            },
            order="created_at.desc",
            limit=1,
        )
        return rows[0] if rows else None

    def _run_video_rows(self, owner_id: str, run_id: str) -> list[dict[str, Any]]:
        return self.backend._select(
            "pipeline_run_videos",
            filters={"owner_id": self._eq(owner_id), "run_id": self._eq(run_id)},
        )

    @staticmethod
    def _ui_status(status: Any) -> str:
        return "done" if status == "completed" else str(status or "queued")

    @staticmethod
    def _stage_status(
        *,
        run_status: str,
        current_stage: str | None,
        stage_id: str,
        statuses: list[str],
    ) -> str:
        if run_status == "failed" and current_stage == stage_id:
            return "error"
        if run_status == "cancelled" and current_stage == stage_id:
            return "cancelled"
        if run_status == "completed":
            return "done"
        if run_status == "awaiting_confirm_summaries":
            if stage_id in {"transcripts", "chunks"}:
                return "done"
            return "pending"
        if current_stage == stage_id and run_status in {"running", "cancel_requested"}:
            return "running"
        if statuses and all(status in VIDEO_FINAL_STATUSES for status in statuses):
            return "done"
        if any(status not in {"queued", "pending"} for status in statuses):
            return "running"
        return "pending"

    def read_state(self, owner_id: str, channel_id: str) -> dict[str, Any] | None:
        run = self.latest_run(owner_id, channel_id)
        if not run:
            return None
        db_channel_id = str(run["channel_id"])
        video_rows, _ = self._video_maps(owner_id, db_channel_id)
        run_video_rows = self._run_video_rows(owner_id, str(run["id"]))

        stages: dict[str, dict[str, Any]] = {}
        run_status = str(run.get("status") or "queued")
        current_stage = run.get("current_stage")
        for stage_id, status_column in STAGE_STATUS_COLUMNS.items():
            videos: dict[str, dict[str, Any]] = {}
            statuses: list[str] = []
            for row in run_video_rows:
                db_video_id = str(row["video_id"])
                video = video_rows.get(db_video_id, {})
                youtube_video_id = str(video.get("youtube_video_id") or db_video_id)
                status = self._ui_status(row.get(status_column))
                statuses.append(status)
                video_state: dict[str, Any] = {
                    "status": status,
                    "title": video.get("title") or "Untitled",
                }
                if stage_id == "summaries":
                    if row.get("summary_confidence") is not None:
                        video_state["summary_confidence"] = row["summary_confidence"]
                    if row.get("evidence_rate") is not None:
                        video_state["summary_evidence_rate"] = row["evidence_rate"]
                videos[youtube_video_id] = video_state
            stages[stage_id] = {
                "status": self._stage_status(
                    run_status=run_status,
                    current_stage=str(current_stage) if current_stage else None,
                    stage_id=stage_id,
                    statuses=statuses,
                ),
                "total": len(run_video_rows),
                "completed": sum(status in VIDEO_FINAL_STATUSES for status in statuses),
                "videos": videos,
            }

        profile_status = "pending"
        if run_status == "completed":
            profile_status = "done"
        elif run_status == "failed" and current_stage == "profile":
            profile_status = "error"
        elif run_status in {"running", "cancel_requested"} and current_stage == "profile":
            profile_status = "running"
        stages["profile"] = {"status": profile_status}

        state = {
            "run_id": run["id"],
            "owner_id": owner_id,
            "channel_id": db_channel_id,
            "status": run_status,
            "current_stage": current_stage,
            "stages": stages,
            "created_at": run.get("created_at"),
            "started_at": run.get("started_at"),
            "completed_at": run.get("completed_at"),
        }
        if run.get("error"):
            state["error"] = run["error"]
        return state

    def write_state(self, owner_id: str, channel_id: str, state: dict[str, Any]) -> None:
        run_id = str(state.get("run_id") or "")
        run = (
            self._run_by_id(owner_id, run_id)
            if run_id
            else self.latest_run(owner_id, channel_id)
        )
        if not run:
            return
        if (
            run.get("status") == "cancelled"
            and state.get("status") not in {"cancelled", "failed"}
        ):
            return

        db_channel_id = str(run["channel_id"])
        values: dict[str, Any] = {}
        for key in ("status", "current_stage", "started_at", "completed_at", "error"):
            if key in state:
                values[key] = state[key]
        if values.get("status") == "running" and not run.get("started_at"):
            values.setdefault("started_at", utc_now_iso())
        if values.get("status") in RUN_FINAL_STATUSES:
            values.setdefault("completed_at", utc_now_iso())
        if values:
            self._update(
                "pipeline_runs",
                values,
                filters={"owner_id": self._eq(owner_id), "id": self._eq(str(run["id"]))},
            )

        _, db_id_by_any_id = self._video_maps(owner_id, db_channel_id)
        for stage_id, status_column in STAGE_STATUS_COLUMNS.items():
            stage = (state.get("stages") or {}).get(stage_id) or {}
            for video_id, video_state in (stage.get("videos") or {}).items():
                db_video_id = db_id_by_any_id.get(str(video_id))
                if not db_video_id:
                    continue
                row_values: dict[str, Any] = {status_column: video_state.get("status", "queued")}
                if stage_id == "summaries":
                    if "summary_confidence" in video_state:
                        row_values["summary_confidence"] = video_state["summary_confidence"]
                    if "summary_evidence_rate" in video_state:
                        row_values["evidence_rate"] = video_state["summary_evidence_rate"]
                self._update(
                    "pipeline_run_videos",
                    row_values,
                    filters={
                        "owner_id": self._eq(owner_id),
                        "run_id": self._eq(str(run["id"])),
                        "video_id": self._eq(db_video_id),
                    },
                )

    def claim_next_run(self) -> dict[str, Any] | None:
        candidates = self.backend._select(
            "pipeline_runs",
            filters={"status": self._eq("queued")},
            order="created_at.asc",
            limit=5,
        )
        for run in candidates:
            values = {
                "status": "running",
                "current_stage": run.get("current_stage") or "transcripts",
                "started_at": run.get("started_at") or utc_now_iso(),
                "error": None,
            }
            rows = self._update(
                "pipeline_runs",
                values,
                filters={"id": self._eq(str(run["id"])), "status": self._eq("queued")},
                return_representation=True,
            )
            if rows:
                return rows[0]
        return None

    def queue_resume(self, owner_id: str, channel_id: str) -> dict[str, Any] | None:
        run = self.latest_run(owner_id, channel_id)
        if not run or run.get("status") not in {
            "awaiting_confirm_summaries",
            "cancelled",
            "failed",
        }:
            return None
        rows = self._update(
            "pipeline_runs",
            {
                "status": "queued",
                "current_stage": "summaries",
                "completed_at": None,
                "error": None,
            },
            filters={"owner_id": self._eq(owner_id), "id": self._eq(str(run["id"]))},
            return_representation=True,
        )
        return rows[0] if rows else None

    def cancel_latest(self, owner_id: str, channel_id: str) -> dict[str, Any]:
        run = self.latest_run(owner_id, channel_id)
        if not run:
            return {"status": "idle"}
        rows = self._update(
            "pipeline_runs",
            {"status": "cancelled", "completed_at": utc_now_iso()},
            filters={"owner_id": self._eq(owner_id), "id": self._eq(str(run["id"]))},
            return_representation=True,
        )
        return rows[0] if rows else {**run, "status": "cancelled"}

    def is_cancelled(self, owner_id: str, channel_id: str, run_id: str | None) -> bool:
        if not run_id:
            return False
        run = self._run_by_id(owner_id, run_id)
        return bool(run and run.get("status") == "cancelled")

    def retry_failed(self, owner_id: str, run_id: str) -> dict[str, Any] | None:
        run = self._run_by_id(owner_id, run_id)
        if not run:
            return None
        run_video_rows = self._run_video_rows(owner_id, run_id)
        retried_video_ids: list[str] = []
        entry_stage = "summaries"
        for row in run_video_rows:
            video_id = str(row.get("video_id") or "")
            failures: dict[str, Any] = {}
            if row.get("transcript_status") == "failed":
                failures["transcript_status"] = "queued"
                entry_stage = "transcripts"
            if row.get("chunk_status") == "failed":
                failures["chunk_status"] = "queued"
                if entry_stage != "transcripts":
                    entry_stage = "chunks"
            if row.get("summary_status") == "failed":
                failures["summary_status"] = "queued"
            if not failures:
                continue
            failures["error"] = None
            self._update(
                "pipeline_run_videos",
                failures,
                filters={
                    "owner_id": self._eq(owner_id),
                    "run_id": self._eq(run_id),
                    "video_id": self._eq(video_id),
                },
            )
            retried_video_ids.append(video_id)
        if not retried_video_ids:
            return None
        rows = self._update(
            "pipeline_runs",
            {
                "status": "queued",
                "current_stage": entry_stage,
                "completed_at": None,
                "error": None,
            },
            filters={"owner_id": self._eq(owner_id), "id": self._eq(run_id)},
            return_representation=True,
        )
        result = rows[0] if rows else dict(run)
        result["retried"] = len(retried_video_ids)
        return result

    def requeue_interrupted_runs(self) -> None:
        self._update(
            "pipeline_runs",
            {
                "status": "queued",
                "error": "Worker interrupted before completing this run.",
            },
            filters={"status": self._eq("running")},
        )


def get_pipeline_run_store() -> PipelineRunStore:
    """Return the run store matching the configured storage backend."""
    backend = storage.get_storage_backend()
    if isinstance(backend, storage.SupabaseStorageBackend):
        return SupabasePipelineRunStore(backend)
    return LocalPipelineRunStore()
