"""Pipeline orchestration routes with SSE live updates."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from backend.models import ApiResponse
from backend.pipeline.aggregate import aggregate
from backend.pipeline.fetch_transcripts import fetch_transcripts
from backend.pipeline.summarize import summarize
from backend.storage import get_channel_dir, load_selection, load_videos, read_json, write_json

router = APIRouter()

running_tasks: dict[str, asyncio.Task] = {}
sse_queues: dict[str, list[asyncio.Queue]] = {}


def _pipeline_state_path(channel_id: str) -> Path:
    return get_channel_dir(channel_id) / "pipeline_state.json"


def _read_pipeline_state(channel_id: str) -> dict | None:
    return read_json(_pipeline_state_path(channel_id))


def _write_pipeline_state(channel_id: str, state: dict) -> None:
    write_json(_pipeline_state_path(channel_id), state)


def _broadcast(channel_id: str, event: str, data: dict) -> None:
    payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    for q in list(sse_queues.get(channel_id, [])):
        q.put_nowait(payload)


async def _run_pipeline(channel_id: str, from_stage: str = "transcripts") -> None:
    state = _read_pipeline_state(channel_id)

    if from_stage == "transcripts":
        state = {
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
        _write_pipeline_state(channel_id, state)
        _broadcast(channel_id, "stage_update", state)

    state = _read_pipeline_state(channel_id) or {}
    selection = load_selection(channel_id) or []
    videos = load_videos(channel_id) or []
    video_map = {v["id"]: v for v in videos}

    loop = asyncio.get_running_loop()

    def _handle_progress(result: dict, stage_name: str) -> None:
        vid = result["video_id"]
        status = result["status"]
        stage = state["stages"][stage_name]
        stage["videos"][vid] = {
            "status": status,
            "title": video_map.get(vid, {}).get("title", "Untitled"),
        }
        if status in ("done", "skipped", "unavailable", "failed"):
            stage["completed"] = sum(
                1
                for v in stage["videos"].values()
                if v["status"] in ("done", "skipped", "unavailable", "failed")
            )
        _write_pipeline_state(channel_id, state)
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
            state["stages"]["transcripts"]["total"] = len(selection)
            _write_pipeline_state(channel_id, state)

            await asyncio.to_thread(
                fetch_transcripts, channel_id, on_progress=make_on_progress("transcripts")
            )
            state["stages"]["transcripts"]["status"] = "done"
            _write_pipeline_state(channel_id, state)
            _broadcast(channel_id, "stage_update", state)

            # Pause for user confirmation before summaries
            state["status"] = "awaiting_confirm_summaries"
            state["current_stage"] = "awaiting_confirm_summaries"
            _write_pipeline_state(channel_id, state)
            _broadcast(channel_id, "stage_update", state)
            return

        # Stage 2: Summaries (resume path)
        state["status"] = "running"
        state["current_stage"] = "summaries"
        state["stages"]["summaries"] = {
            "status": "running",
            "total": len(selection),
            "completed": 0,
            "videos": {},
        }
        _write_pipeline_state(channel_id, state)
        _broadcast(channel_id, "stage_update", state)

        await summarize(channel_id, on_progress=make_on_progress("summaries"))
        state["stages"]["summaries"]["status"] = "done"
        _write_pipeline_state(channel_id, state)
        _broadcast(channel_id, "stage_update", state)

        # Stage 3: Profile (aggregation)
        state["current_stage"] = "profile"
        state["stages"]["profile"] = {
            "status": "running",
        }
        _write_pipeline_state(channel_id, state)
        _broadcast(channel_id, "stage_update", state)

        await asyncio.to_thread(aggregate, channel_id)
        state["stages"]["profile"]["status"] = "done"
        state["current_stage"] = "done"
        state["status"] = "completed"
        _write_pipeline_state(channel_id, state)
        _broadcast(channel_id, "pipeline_complete", state)
    except asyncio.CancelledError:
        # Clean exit after cancel
        pass
    except Exception as exc:
        state["status"] = "failed"
        current_stage = state.get("current_stage", "transcripts")
        if current_stage in state["stages"]:
            state["stages"][current_stage]["status"] = "error"
        state["error"] = str(exc)
        _write_pipeline_state(channel_id, state)
        _broadcast(channel_id, "pipeline_error", state)
    finally:
        if channel_id in running_tasks:
            del running_tasks[channel_id]


@router.post("/api/pipeline/start")
async def post_pipeline_start(payload: dict[str, Any]) -> ApiResponse[dict]:
    channel_id = payload.get("channel_id", "")
    if not channel_id:
        return ApiResponse(ok=False, error="channel_id is required")

    if channel_id in running_tasks and not running_tasks[channel_id].done():
        return ApiResponse(ok=True, data={"channel_id": channel_id, "status": "already_running"})

    task = asyncio.create_task(_run_pipeline(channel_id))
    running_tasks[channel_id] = task
    return ApiResponse(ok=True, data={"channel_id": channel_id, "status": "started"})


@router.post("/api/pipeline/cancel")
async def post_pipeline_cancel(payload: dict[str, Any]) -> ApiResponse[dict]:
    channel_id = payload.get("channel_id", "")
    if not channel_id:
        return ApiResponse(ok=False, error="channel_id is required")

    task = running_tasks.get(channel_id)
    if task and not task.done():
        task.cancel()

    state = _read_pipeline_state(channel_id) or {"status": "idle"}
    state["status"] = "cancelled"
    _write_pipeline_state(channel_id, state)
    _broadcast(channel_id, "pipeline_cancelled", state)

    return ApiResponse(ok=True, data={"status": "cancelled"})


@router.post("/api/pipeline/resume")
async def post_pipeline_resume(payload: dict[str, Any]) -> ApiResponse[dict]:
    channel_id = payload.get("channel_id", "")
    if not channel_id:
        return ApiResponse(ok=False, error="channel_id is required")

    state = _read_pipeline_state(channel_id)
    if not state or state.get("status") != "awaiting_confirm_summaries":
        return ApiResponse(ok=False, error="pipeline is not awaiting confirmation")

    if channel_id in running_tasks and not running_tasks[channel_id].done():
        return ApiResponse(ok=False, error="pipeline already running")

    task = asyncio.create_task(_run_pipeline(channel_id, from_stage="summaries"))
    running_tasks[channel_id] = task
    return ApiResponse(ok=True, data={"channel_id": channel_id, "status": "resumed"})


async def _sse_event_stream(channel_id: str):
    if channel_id not in sse_queues:
        sse_queues[channel_id] = []
    q: asyncio.Queue[str] = asyncio.Queue()
    sse_queues[channel_id].append(q)

    try:
        state = _read_pipeline_state(channel_id)
        if state:
            yield f"event: initial_state\ndata: {json.dumps(state)}\n\n"
        else:
            yield f"event: initial_state\ndata: {json.dumps({'status': 'idle'})}\n\n"

        while True:
            payload = await q.get()
            yield payload
    except asyncio.CancelledError:
        pass
    finally:
        if channel_id in sse_queues and q in sse_queues[channel_id]:
            sse_queues[channel_id].remove(q)


@router.get("/api/pipeline/state")
async def get_pipeline_state(channel_id: str = Query(...)) -> ApiResponse[dict]:
    state = _read_pipeline_state(channel_id) or {"status": "idle"}
    return ApiResponse(ok=True, data=state)


@router.get("/api/pipeline/stream")
def get_pipeline_stream(channel_id: str = Query(...)) -> StreamingResponse:
    return StreamingResponse(
        _sse_event_stream(channel_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/pipeline/cost")
async def get_pipeline_cost(channel_id: str = Query(...)) -> ApiResponse[dict]:
    """Estimate cost for summarizing selected videos."""
    selection = load_selection(channel_id) or []
    channel_dir = get_channel_dir(channel_id)

    total_input_tokens = 0
    video_count = 0

    for vid in selection:
        transcript_path = channel_dir / "transcripts" / f"{vid}.json"
        transcript = read_json(transcript_path)
        if not transcript:
            continue
        if transcript.get("source") == "unavailable":
            continue
        word_count = transcript.get("word_count", 0)
        total_input_tokens += int(word_count * 1.3)
        video_count += 1

    avg_output_tokens = 300
    input_cost = (total_input_tokens / 1_000_000) * 0.30
    output_cost = (video_count * avg_output_tokens / 1_000_000) * 1.20
    estimated_cost = input_cost + output_cost

    return ApiResponse(
        ok=True,
        data={
            "estimated_cost_usd": round(estimated_cost, 4),
            "video_count": video_count,
            "total_input_tokens": total_input_tokens,
        },
    )
