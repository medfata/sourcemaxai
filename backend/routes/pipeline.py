"""Pipeline orchestration routes with SSE live updates."""

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any

from backend.auth import CurrentUser, get_current_user
from backend.config import embedded_worker_enabled
from backend.models import ApiResponse, RetryFailedResult
from backend.pipeline.aggregate import aggregate
from backend.pipeline.chunk_transcripts import build_chunk_index
from backend.pipeline.fetch_transcripts import fetch_transcripts
from backend.pipeline.run_state import (
    from_stage_for_run,
    get_pipeline_run_store,
    utc_now_iso,
)
from backend.pipeline.schema_versions import (
    get_generated_file_report,
    get_summary_stale_reasons,
)
from backend.pipeline.summarize import summarize
from backend.quotas import (
    SUMMARY_INPUT_USD_PER_M_TOKENS,
    SUMMARY_OUTPUT_USD_PER_M_TOKENS,
    check_pipeline_start,
    get_quota_store,
    remaining_budget,
    transcript_seconds_from_transcript,
)
from backend.storage import (
    LOCAL_OWNER_ID,
    current_owner_id,
    get_channel_dir,
    load_channel_meta,
    load_selection,
    load_videos,
    read_json,
    storage_owner,
    storage_run,
)
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

AVG_SUMMARY_OUTPUT_TOKENS = 300

router = APIRouter()

_worker_task: asyncio.Task | None = None


def _estimate_pipeline_tokens(
    channel_id: str,
    selection: list[str],
) -> tuple[int, int]:
    """Return ``(input_tokens, video_count_with_data)`` for the selected videos.

    Prefers transcript word counts when transcripts already exist (cost endpoint
    use case). Falls back to a duration-based heuristic so the start-time guard
    can still block obviously oversized runs.
    """
    channel_dir = get_channel_dir(channel_id)
    videos = load_videos(channel_id) or []
    duration_by_id = {str(v.get("id")): int(v.get("duration") or 0) for v in videos}

    total_input_tokens = 0
    counted = 0
    for vid in selection:
        transcript = read_json(channel_dir / "transcripts" / f"{vid}.json")
        if isinstance(transcript, dict) and transcript.get("source") != "unavailable":
            word_count = transcript.get("word_count")
            if isinstance(word_count, int) and word_count > 0:
                total_input_tokens += int(word_count * 1.3)
                counted += 1
                continue
        # Fallback: ~150 spoken words per minute, 1.3 tokens per word.
        duration_seconds = duration_by_id.get(vid, 0)
        if duration_seconds > 0:
            words = max(int(duration_seconds / 60 * 150), 50)
            total_input_tokens += int(words * 1.3)
            counted += 1
    return total_input_tokens, counted


def _estimate_pipeline_transcript_seconds(channel_id: str, selection: list[str]) -> int:
    """Return estimated transcript seconds for selected videos.

    Uses exact transcript word counts when available. Before transcripts exist,
    falls back to raw YouTube duration only for display/estimation.
    """
    channel_dir = get_channel_dir(channel_id)
    videos = load_videos(channel_id) or []
    duration_by_id = {str(v.get("id")): int(v.get("duration") or 0) for v in videos}

    total = 0
    for vid in selection:
        transcript = read_json(channel_dir / "transcripts" / f"{vid}.json")
        transcript_seconds = transcript_seconds_from_transcript(transcript)
        if transcript_seconds > 0:
            total += transcript_seconds
            continue
        total += max(duration_by_id.get(vid, 0), 0)
    return total


def _estimate_summary_work(channel_id: str, selection: list[str]) -> dict[str, Any]:
    """Return exact billable work for summaries that would run now."""
    channel_dir = get_channel_dir(channel_id)
    total_transcript_seconds = 0
    total_input_tokens = 0
    video_count = 0

    for vid in selection:
        summary = read_json(channel_dir / "summaries" / f"{vid}.json")
        if isinstance(summary, dict) and not get_summary_stale_reasons(summary):
            continue

        transcript = read_json(channel_dir / "transcripts" / f"{vid}.json")
        transcript_seconds = transcript_seconds_from_transcript(transcript)
        if transcript_seconds <= 0:
            continue

        word_count = int(transcript.get("word_count") or 0) if isinstance(transcript, dict) else 0
        total_transcript_seconds += transcript_seconds
        total_input_tokens += int(max(word_count, 0) * 1.3)
        video_count += 1

    total_output_tokens = video_count * AVG_SUMMARY_OUTPUT_TOKENS
    input_cost = total_input_tokens / 1_000_000 * SUMMARY_INPUT_USD_PER_M_TOKENS
    output_cost = total_output_tokens / 1_000_000 * SUMMARY_OUTPUT_USD_PER_M_TOKENS
    return {
        "estimated_cost_usd": round(input_cost + output_cost, 4),
        "estimated_input_tokens": total_input_tokens,
        "estimated_output_tokens": total_output_tokens,
        "estimated_transcript_seconds": total_transcript_seconds,
        "video_count": video_count,
        "total_input_tokens": total_input_tokens,
    }


def _estimate_pipeline_cost(
    channel_id: str,
    selection: list[str],
) -> dict[str, Any]:
    """Return a cost breakdown shared by the start guard and the cost endpoint."""
    total_input_tokens, video_count = _estimate_pipeline_tokens(channel_id, selection)
    total_output_tokens = video_count * AVG_SUMMARY_OUTPUT_TOKENS
    input_cost = total_input_tokens / 1_000_000 * SUMMARY_INPUT_USD_PER_M_TOKENS
    output_cost = total_output_tokens / 1_000_000 * SUMMARY_OUTPUT_USD_PER_M_TOKENS
    estimated_cost = round(input_cost + output_cost, 6)
    return {
        "estimated_cost_usd": round(estimated_cost, 4),
        "estimated_input_tokens": total_input_tokens,
        "estimated_output_tokens": total_output_tokens,
        "estimated_transcript_seconds": _estimate_pipeline_transcript_seconds(
            channel_id,
            selection,
        ),
        "video_count": video_count,
        "total_input_tokens": total_input_tokens,
    }


class PipelineCancelled(Exception):
    """Raised internally after a persisted cancellation is observed."""


def _state_owner_id(owner_id: str | None = None) -> str:
    return owner_id or current_owner_id() or LOCAL_OWNER_ID


def _read_pipeline_state(channel_id: str, owner_id: str | None = None) -> dict | None:
    return get_pipeline_run_store().read_state(_state_owner_id(owner_id), channel_id)


def _write_pipeline_state(
    channel_id: str,
    state: dict,
    owner_id: str | None = None,
) -> None:
    get_pipeline_run_store().write_state(_state_owner_id(owner_id), channel_id, state)


def _with_generated_file_report(channel_id: str, state: dict) -> dict:
    enriched = dict(state)
    report_channel_id = str(enriched.get("channel_id") or channel_id)
    enriched["generated_files"] = get_generated_file_report(report_channel_id)
    return enriched


def _broadcast(channel_id: str, event: str, data: dict) -> None:
    """Compatibility hook; SSE now polls durable state instead of memory queues."""


async def _run_pipeline_for_owner(
    owner_id: str,
    channel_id: str,
    from_stage: str = "transcripts",
    run_id: str | None = None,
) -> None:
    if run_id is None:
        run = get_pipeline_run_store().latest_run(owner_id, channel_id)
        run_id = str(run["id"]) if run and run.get("id") else None
    with storage_owner(owner_id), storage_run(run_id):
        await _run_pipeline(
            channel_id,
            from_stage=from_stage,
            run_id=run_id,
        )


async def _run_pipeline(
    channel_id: str,
    from_stage: str = "transcripts",
    run_id: str | None = None,
) -> None:
    owner_id = _state_owner_id()
    store = get_pipeline_run_store()

    def _ensure_not_cancelled(state: dict) -> None:
        if store.is_cancelled(owner_id, channel_id, run_id):
            state["status"] = "cancelled"
            state["completed_at"] = utc_now_iso()
            _write_pipeline_state(channel_id, state, owner_id=owner_id)
            _broadcast(
                channel_id,
                "pipeline_cancelled",
                _with_generated_file_report(channel_id, state),
            )
            raise PipelineCancelled()

    state = _read_pipeline_state(channel_id)

    if from_stage == "transcripts":
        state = {
            "run_id": run_id,
            "status": "running",
            "current_stage": "transcripts",
            "stages": {
                "transcripts": {
                    "status": "running",
                    "total": 0,
                    "completed": 0,
                    "videos": {},
                }
            },
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_pipeline_state(channel_id, state, owner_id=owner_id)
        _broadcast(channel_id, "stage_update", _with_generated_file_report(channel_id, state))

    state = _read_pipeline_state(channel_id) or {}
    if run_id:
        state["run_id"] = run_id
    selection = load_selection(channel_id) or []
    videos = load_videos(channel_id) or []
    video_map = {v["id"]: v for v in videos}

    loop = asyncio.get_running_loop()

    def _handle_progress(result: dict, stage_name: str) -> None:
        if store.is_cancelled(owner_id, channel_id, run_id):
            return
        vid = result["video_id"]
        status = result["status"]
        stage = state["stages"][stage_name]
        video_state = {
            "status": status,
            "title": video_map.get(vid, {}).get("title", "Untitled"),
        }
        for key in (
            "schema_current",
            "stale",
            "stale_reasons",
            "summary_confidence",
            "summary_evidence_rate",
            "claim_count",
            "supported_claim_count",
            "unsupported_claim_count",
            "rate_limited",
            "error",
        ):
            if key in result:
                video_state[key] = result[key]
        if "chunk_count" in result:
            video_state["chunk_count"] = result["chunk_count"]
        stage["videos"][vid] = video_state
        if status in ("done", "skipped", "unavailable", "failed"):
            stage["completed"] = sum(
                1
                for v in stage["videos"].values()
                if v["status"] in ("done", "skipped", "unavailable", "failed")
            )
        try:
            _write_pipeline_state(channel_id, state, owner_id=owner_id)
        except Exception as exc:
            print(f"[pipeline] progress state write failed: {exc}")
        _broadcast(
            channel_id,
            "video_update",
            {"video_id": vid, "status": status, "stage": stage, "stage_id": stage_name},
        )

    def make_on_progress(stage_name: str):
        def on_progress(result: dict) -> None:
            loop.call_soon_threadsafe(_handle_progress, result, stage_name)

        return on_progress

    try:
        if from_stage == "transcripts":
            # Stage 1: Transcripts
            _ensure_not_cancelled(state)
            state["stages"]["transcripts"]["total"] = len(selection)
            _write_pipeline_state(channel_id, state, owner_id=owner_id)

            await asyncio.to_thread(
                fetch_transcripts, channel_id, on_progress=make_on_progress("transcripts")
            )
            _ensure_not_cancelled(state)
            state["stages"]["transcripts"]["status"] = "done"
            _write_pipeline_state(channel_id, state, owner_id=owner_id)
            _broadcast(channel_id, "stage_update", _with_generated_file_report(channel_id, state))

            # Stage 2: Caption chunks
            state["current_stage"] = "chunks"
            state["stages"]["chunks"] = {
                "status": "running",
                "total": len(selection),
                "completed": 0,
                "videos": {},
            }
            _write_pipeline_state(channel_id, state, owner_id=owner_id)
            _broadcast(channel_id, "stage_update", _with_generated_file_report(channel_id, state))

            _ensure_not_cancelled(state)
            await asyncio.to_thread(
                build_chunk_index, channel_id, on_progress=make_on_progress("chunks")
            )
            _ensure_not_cancelled(state)
            state["stages"]["chunks"]["status"] = "done"
            _write_pipeline_state(channel_id, state, owner_id=owner_id)
            _broadcast(channel_id, "stage_update", _with_generated_file_report(channel_id, state))

            # Pause for user confirmation before summaries
            state["status"] = "awaiting_confirm_summaries"
            state["current_stage"] = "awaiting_confirm_summaries"
            _write_pipeline_state(channel_id, state, owner_id=owner_id)
            _broadcast(channel_id, "stage_update", _with_generated_file_report(channel_id, state))
            return

        chunks_stage = state.get("stages", {}).get("chunks")
        chunk_index_status = get_generated_file_report(channel_id)["chunk_index"]["status"]
        if (
            not chunks_stage
            or chunks_stage.get("status") != "done"
            or chunk_index_status != "current"
        ):
            state["status"] = "running"
            state["current_stage"] = "chunks"
            state.setdefault("stages", {})["chunks"] = {
                "status": "running",
                "total": len(selection),
                "completed": 0,
                "videos": {},
            }
            _write_pipeline_state(channel_id, state, owner_id=owner_id)
            _broadcast(channel_id, "stage_update", _with_generated_file_report(channel_id, state))

            _ensure_not_cancelled(state)
            await asyncio.to_thread(
                build_chunk_index, channel_id, on_progress=make_on_progress("chunks")
            )
            _ensure_not_cancelled(state)
            state["stages"]["chunks"]["status"] = "done"
            _write_pipeline_state(channel_id, state, owner_id=owner_id)
            _broadcast(channel_id, "stage_update", _with_generated_file_report(channel_id, state))

        # Stage 3: Summaries (resume path)
        state["status"] = "running"
        state["current_stage"] = "summaries"
        state["stages"]["summaries"] = {
            "status": "running",
            "total": len(selection),
            "completed": 0,
            "videos": {},
        }
        _write_pipeline_state(channel_id, state, owner_id=owner_id)
        _broadcast(channel_id, "stage_update", _with_generated_file_report(channel_id, state))

        _ensure_not_cancelled(state)
        await summarize(channel_id, on_progress=make_on_progress("summaries"))
        _ensure_not_cancelled(state)
        state["stages"]["summaries"]["status"] = "done"
        _write_pipeline_state(channel_id, state, owner_id=owner_id)
        _broadcast(channel_id, "stage_update", _with_generated_file_report(channel_id, state))

        # Stage 4: Profile (aggregation)
        state["current_stage"] = "profile"
        state["stages"]["profile"] = {
            "status": "running",
        }
        _write_pipeline_state(channel_id, state, owner_id=owner_id)
        _broadcast(channel_id, "stage_update", _with_generated_file_report(channel_id, state))

        _ensure_not_cancelled(state)
        await asyncio.to_thread(aggregate, channel_id)
        _ensure_not_cancelled(state)
        state["stages"]["profile"]["status"] = "done"
        state["current_stage"] = "done"
        state["status"] = "completed"
        state["completed_at"] = utc_now_iso()
        _write_pipeline_state(channel_id, state, owner_id=owner_id)
        _broadcast(channel_id, "pipeline_complete", _with_generated_file_report(channel_id, state))
    except PipelineCancelled:
        pass
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        state["status"] = "failed"
        current_stage = state.get("current_stage", "transcripts")
        if current_stage in state["stages"]:
            state["stages"][current_stage]["status"] = "error"
        state["error"] = str(exc)
        state["completed_at"] = utc_now_iso()
        _write_pipeline_state(channel_id, state, owner_id=owner_id)
        _broadcast(channel_id, "pipeline_error", _with_generated_file_report(channel_id, state))


async def _process_queued_runs() -> None:
    store = get_pipeline_run_store()
    while True:
        run = store.claim_next_run()
        if not run:
            return
        await _run_pipeline_for_owner(
            str(run["owner_id"]),
            str(run["channel_id"]),
            from_stage=from_stage_for_run(run),
            run_id=str(run["id"]),
        )


async def process_queued_runs_once() -> None:
    """Process all currently queued durable runs, then return."""
    await _process_queued_runs()


def ensure_pipeline_worker_started() -> None:
    """Start the lightweight worker loop if one is not already active."""
    global _worker_task
    if not embedded_worker_enabled():
        return
    store = get_pipeline_run_store()
    if not store.is_durable:
        return
    if _worker_task and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_process_queued_runs())


def requeue_interrupted_pipeline_runs() -> None:
    """Make runs left in `running` by a dead worker claimable again."""
    if os.environ.get("PIPELINE_REQUEUE_INTERRUPTED_RUNS", "true").lower() == "false":
        return
    store = get_pipeline_run_store()
    if store.is_durable:
        store.requeue_interrupted_runs()


@router.post("/api/pipeline/start")
async def post_pipeline_start(
    payload: dict[str, Any],
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[dict]:
    channel_id = payload.get("channel_id", "")
    if not channel_id:
        return ApiResponse(ok=False, error="channel_id is required")

    owner_id = current_user.owner_id
    if not load_channel_meta(channel_id, owner_id=owner_id):
        return ApiResponse(ok=False, error="Channel not found")

    store = get_pipeline_run_store()
    latest = store.latest_run(owner_id, channel_id)
    if latest and latest.get("status") in {"queued", "running"}:
        return ApiResponse(
            ok=True,
            data={
                "channel_id": channel_id,
                "run_id": latest.get("id"),
                "status": "already_running",
            },
        )

    quota_store = get_quota_store()
    if quota_store.is_enforced:
        decision = check_pipeline_start(quota_store, owner_id)
        if not decision.allowed:
            return ApiResponse(
                ok=False,
                error="quota_exceeded",
                data={"reason": decision.reason, **decision.detail},
            )

    run = store.create_run(owner_id, channel_id)
    if store.is_durable:
        if embedded_worker_enabled():
            ensure_pipeline_worker_started()
    else:
        asyncio.create_task(
            _run_pipeline_for_owner(owner_id, channel_id, run_id=str(run["id"]))
        )
    return ApiResponse(
        ok=True,
        data={"channel_id": channel_id, "run_id": run.get("id"), "status": "started"},
    )


@router.post("/api/pipeline/cancel")
async def post_pipeline_cancel(
    payload: dict[str, Any],
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[dict]:
    channel_id = payload.get("channel_id", "")
    if not channel_id:
        return ApiResponse(ok=False, error="channel_id is required")

    owner_id = current_user.owner_id
    if not load_channel_meta(channel_id, owner_id=owner_id):
        return ApiResponse(ok=False, error="Channel not found")

    store = get_pipeline_run_store()
    store.cancel_latest(owner_id, channel_id)
    with storage_owner(owner_id):
        state = _read_pipeline_state(channel_id) or {"status": "cancelled"}
        _broadcast(channel_id, "pipeline_cancelled", _with_generated_file_report(channel_id, state))

    return ApiResponse(ok=True, data={"status": "cancelled"})


@router.post("/api/pipeline/resume")
async def post_pipeline_resume(
    payload: dict[str, Any],
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[dict]:
    channel_id = payload.get("channel_id", "")
    if not channel_id:
        return ApiResponse(ok=False, error="channel_id is required")

    owner_id = current_user.owner_id
    if not load_channel_meta(channel_id, owner_id=owner_id):
        return ApiResponse(ok=False, error="Channel not found")

    with storage_owner(owner_id):
        state = _read_pipeline_state(channel_id)
    if not state or state.get("status") != "awaiting_confirm_summaries":
        return ApiResponse(ok=False, error="pipeline is not awaiting confirmation")

    quota_store = get_quota_store()
    if quota_store.is_enforced:
        with storage_owner(owner_id):
            selection = load_selection(channel_id) or []
            estimate = _estimate_summary_work(channel_id, selection)
        decision = check_pipeline_start(
            quota_store,
            owner_id,
            run_transcript_seconds=int(estimate["estimated_transcript_seconds"]),
            estimated_cost_usd=float(estimate["estimated_cost_usd"]),
            estimated_input_tokens=int(estimate["estimated_input_tokens"]),
            check_concurrent=False,
        )
        if not decision.allowed:
            return ApiResponse(
                ok=False,
                error="quota_exceeded",
                data={"reason": decision.reason, **decision.detail, "estimate": estimate},
            )

    store = get_pipeline_run_store()
    run = store.queue_resume(owner_id, channel_id)
    if not run:
        return ApiResponse(ok=False, error="pipeline is not awaiting confirmation")

    if store.is_durable:
        if embedded_worker_enabled():
            ensure_pipeline_worker_started()
    else:
        asyncio.create_task(
            _run_pipeline_for_owner(
                owner_id,
                channel_id,
                from_stage="summaries",
                run_id=str(run["id"]),
            )
        )
    return ApiResponse(
        ok=True,
        data={"channel_id": channel_id, "run_id": run.get("id"), "status": "resumed"},
    )


async def _sse_event_stream(owner_id: str, channel_id: str):
    poll_seconds = float(os.environ.get("PIPELINE_SSE_POLL_SECONDS", "1.0"))
    last_payload: str | None = None
    try:
        if not load_channel_meta(channel_id, owner_id=owner_id):
            data = {"status": "idle", "error": "Channel not found"}
            yield f"event: initial_state\ndata: {json.dumps(data)}\n\n"
            return

        with storage_owner(owner_id):
            state = _read_pipeline_state(channel_id)
            if state:
                data = _with_generated_file_report(channel_id, state)
            else:
                data = _with_generated_file_report(channel_id, {"status": "idle"})
            last_payload = json.dumps(data, sort_keys=True)
            yield f"event: initial_state\ndata: {json.dumps(data)}\n\n"

        while True:
            await asyncio.sleep(poll_seconds)
            with storage_owner(owner_id):
                state = _read_pipeline_state(channel_id) or {"status": "idle"}
                data = _with_generated_file_report(channel_id, state)
            payload = json.dumps(data, sort_keys=True)
            if payload == last_payload:
                continue
            last_payload = payload
            status = data.get("status")
            if status == "completed":
                event = "pipeline_complete"
            elif status == "failed":
                event = "pipeline_error"
            elif status == "cancelled":
                event = "pipeline_cancelled"
            else:
                event = "stage_update"
            yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
    except asyncio.CancelledError:
        pass


@router.get("/api/pipeline/state")
async def get_pipeline_state(
    channel_id: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[dict]:
    if not load_channel_meta(channel_id, owner_id=current_user.owner_id):
        return ApiResponse(ok=False, error="Channel not found")

    with storage_owner(current_user.owner_id):
        state = _read_pipeline_state(channel_id) or {"status": "idle"}
        return ApiResponse(ok=True, data=_with_generated_file_report(channel_id, state))


@router.get("/api/pipeline/stream")
def get_pipeline_stream(
    channel_id: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
) -> StreamingResponse:
    return StreamingResponse(
        _sse_event_stream(current_user.owner_id, channel_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/pipeline/runs/{run_id}/retry-failed")
async def post_pipeline_retry_failed(
    run_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[RetryFailedResult]:
    """Re-queue any failed videos in a run and resume the worker."""
    owner_id = current_user.owner_id
    store = get_pipeline_run_store()
    run = store.retry_failed(owner_id, run_id)
    if not run:
        return ApiResponse(ok=False, error="No failed videos to retry")

    channel_id = str(run.get("channel_id") or "")
    # For Supabase the row carries the DB UUID; resolve to youtube_channel_id
    # so the SSE stream and UI continue to work with the public ID.
    from backend import storage as _storage

    backend = _storage.get_storage_backend()
    if isinstance(backend, _storage.SupabaseStorageBackend):
        rows = backend._select(
            "channels",
            select="youtube_channel_id",
            filters={"id": backend._eq(channel_id)},
            limit=1,
        )
        if rows:
            channel_id = str(rows[0].get("youtube_channel_id") or channel_id)

    if store.is_durable:
        if embedded_worker_enabled():
            ensure_pipeline_worker_started()
    else:
        asyncio.create_task(
            _run_pipeline_for_owner(
                owner_id,
                channel_id,
                from_stage=from_stage_for_run(run),
                run_id=str(run["id"]),
            )
        )
    return ApiResponse(
        ok=True,
        data=RetryFailedResult(
            run_id=str(run["id"]),
            channel_id=channel_id,
            retried=int(run.get("retried") or 0),
            status="queued",
        ),
    )


@router.get("/api/pipeline/cost")
async def get_pipeline_cost(
    channel_id: str = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[dict]:
    """Estimate cost for summarizing selected videos and report remaining budget."""
    with storage_owner(current_user.owner_id):
        selection = load_selection(channel_id) or []
        estimate = _estimate_pipeline_cost(channel_id, selection)

    payload: dict[str, Any] = {
        "estimated_cost_usd": estimate["estimated_cost_usd"],
        "estimated_transcript_seconds": estimate["estimated_transcript_seconds"],
        "video_count": estimate["video_count"],
        "total_input_tokens": estimate["total_input_tokens"],
        "selection_count": len(selection),
    }

    quota_store = get_quota_store()
    if quota_store.is_enforced:
        quota = quota_store.get_quota(current_user.owner_id)
        usage = quota_store.get_monthly_usage(current_user.owner_id)
        payload["budget"] = remaining_budget(quota, usage)

    return ApiResponse(ok=True, data=payload)


@router.get("/api/usage/summary")
async def get_usage_summary(
    current_user: CurrentUser = Depends(get_current_user),
) -> ApiResponse[dict]:
    """Return the user's quota and current-month usage for the dashboard UI."""
    quota_store = get_quota_store()
    quota = quota_store.get_quota(current_user.owner_id)
    usage = quota_store.get_monthly_usage(current_user.owner_id)
    return ApiResponse(
        ok=True,
        data={
            "enforced": quota_store.is_enforced,
            "quota": {
                "tier_key": quota.tier_key,
                "display_name": quota.display_name,
                "monthly_transcript_seconds": quota.monthly_transcript_seconds,
                "credit_transcript_seconds": quota.credit_transcript_seconds,
                "monthly_chat_messages": quota.monthly_chat_messages,
                "max_transcript_seconds_per_run": quota.max_transcript_seconds_per_run,
                "monthly_token_limit": quota.monthly_token_limit,
                "monthly_cost_limit_usd": quota.monthly_cost_limit_usd,
                "max_concurrent_runs": quota.max_concurrent_runs,
                "chat_per_minute_limit": quota.chat_per_minute_limit,
            },
            "usage": {
                "videos": usage.videos,
                "transcript_seconds": usage.transcript_seconds,
                "chat_messages": usage.chat_messages,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
                "cost_usd": round(usage.cost_usd, 6),
            },
            "remaining": remaining_budget(quota, usage),
        },
    )
