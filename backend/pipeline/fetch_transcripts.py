"""Fetch YouTube video transcripts using youtube-transcript-api."""

import os
import random
import re
import time
from pathlib import Path

from backend.pipeline.schema_versions import (
    TRANSCRIPT_SCHEMA_VERSION,
    get_transcript_stale_reasons,
)
from backend.storage import (
    get_channel_dir,
    load_selection,
    load_videos,
    read_json,
    save_transcript,
    write_json,
)
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)

WORKERS = int(os.environ.get("TRANSCRIPT_WORKERS", "1"))
REQUEST_DELAY_SECONDS = float(os.environ.get("TRANSCRIPT_REQUEST_DELAY_SECONDS", "1.5"))
BATCH_SIZE = int(os.environ.get("TRANSCRIPT_BATCH_SIZE", "10"))
BATCH_DELAY_SECONDS = float(os.environ.get("TRANSCRIPT_BATCH_DELAY_SECONDS", "15"))
DELAY_JITTER_SECONDS = float(os.environ.get("TRANSCRIPT_DELAY_JITTER_SECONDS", "1.0"))
STOP_ON_BLOCK = os.environ.get("TRANSCRIPT_STOP_ON_BLOCK", "true").lower() != "false"

BLOCK_ERROR_MARKERS = (
    "blocking requests from your ip",
    "requestblocked",
    "ipblocked",
    "too many requests",
    "429",
)

BRACKET_TAGS = re.compile(
    r"\[(Music|Applause|Laughter|Inaudible|inaudible|music|applause|laughter)\]",
    re.IGNORECASE,
)


def clean_text(text: str) -> str:
    text = BRACKET_TAGS.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _is_youtube_block_error(error: str) -> bool:
    normalized = error.lower()
    return any(marker in normalized for marker in BLOCK_ERROR_MARKERS)


def _sleep_with_jitter(seconds: float) -> None:
    if seconds <= 0:
        return
    jitter = random.uniform(0, max(DELAY_JITTER_SECONDS, 0.0))
    time.sleep(seconds + jitter)


def fetch_single_transcript(
    video_id: str,
    title: str,
    upload_date: str,
    duration: int,
    channel_id: str,
    channel_dir: Path,
    on_progress=None,
) -> dict:
    transcript_path = channel_dir / "transcripts" / f"{video_id}.json"
    if transcript_path.exists():
        existing = read_json(transcript_path)
        if existing:
            stale_reasons = get_transcript_stale_reasons(existing)
            return {
                "video_id": video_id,
                "status": "skipped",
                "schema_current": not stale_reasons,
                "stale": bool(stale_reasons),
                "stale_reasons": stale_reasons,
                "data": existing,
            }

    if on_progress:
        on_progress({"video_id": video_id, "status": "fetching"})

    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        try:
            transcript = transcript_list.find_manually_created_transcript(["en"])
            source = "manual"
        except NoTranscriptFound:
            transcript = transcript_list.find_generated_transcript(["en"])
            source = "auto"

        segments = transcript.fetch()
        raw_text = " ".join(
            s.text if hasattr(s, "text") else s["text"] for s in segments
        )
        cleaned = clean_text(raw_text)

        segments_list = []
        for s in segments:
            seg_text = s.text if hasattr(s, "text") else s["text"]
            seg_start = s.start if hasattr(s, "start") else s.get("start", 0.0)
            cleaned_seg = clean_text(seg_text)
            if cleaned_seg:
                segments_list.append({"start": float(seg_start), "text": cleaned_seg})

        data = {
            "schema_version": TRANSCRIPT_SCHEMA_VERSION,
            "video_id": video_id,
            "title": title,
            "upload_date": upload_date,
            "duration_seconds": duration,
            "transcript_text": cleaned,
            "word_count": len(cleaned.split()) if cleaned else 0,
            "source": source,
            "segments": segments_list,
        }
        write_json(transcript_path, data)
        save_transcript(channel_id, "manual", video_id, data)
        return {"video_id": video_id, "status": "done", "data": data}

    except (TranscriptsDisabled, NoTranscriptFound):
        data = {
            "schema_version": TRANSCRIPT_SCHEMA_VERSION,
            "video_id": video_id,
            "title": title,
            "upload_date": upload_date,
            "duration_seconds": duration,
            "transcript_text": "",
            "word_count": 0,
            "source": "unavailable",
            "segments": [],
        }
        write_json(transcript_path, data)
        save_transcript(channel_id, "manual", video_id, data)
        return {"video_id": video_id, "status": "unavailable", "data": data}

    except Exception as exc:
        print(f"[transcript] Failed {video_id}: {exc}")
        error = str(exc)
        return {
            "video_id": video_id,
            "status": "failed",
            "error": error,
            "rate_limited": _is_youtube_block_error(error),
        }


def fetch_transcripts(channel_id: str, on_progress=None) -> dict:
    channel_dir = get_channel_dir(channel_id)
    transcripts_dir = channel_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)

    selection = load_selection(channel_id)
    if not selection:
        return {"total": 0, "results": []}

    videos = load_videos(channel_id) or []
    video_map = {v["id"]: v for v in videos}

    tasks = []
    for vid in selection:
        info = video_map.get(vid, {})
        tasks.append(
            (
                vid,
                info.get("title", "Untitled"),
                info.get("upload_date", ""),
                info.get("duration", 0),
            )
        )

    results = []
    worker_count = max(WORKERS, 1)
    if worker_count > 1:
        print(
            "[transcript] TRANSCRIPT_WORKERS>1 is ignored for transcript fetching; "
            "the queue runs serially to reduce YouTube blocking."
        )

    for index, (vid, title, upload_date, duration) in enumerate(tasks, start=1):
        result = fetch_single_transcript(
            vid,
            title,
            upload_date,
            duration,
            channel_id,
            channel_dir,
            on_progress,
        )
        results.append(result)
        if on_progress:
            on_progress(result)

        if STOP_ON_BLOCK and result.get("rate_limited"):
            remaining = tasks[index:]
            print(
                "[transcript] YouTube block detected; pausing transcript queue "
                f"with {len(remaining)} videos left."
            )
            for remaining_vid, *_ in remaining:
                skipped = {
                    "video_id": remaining_vid,
                    "status": "failed",
                    "error": "Transcript queue paused after YouTube blocked transcript requests.",
                    "rate_limited": True,
                }
                results.append(skipped)
                if on_progress:
                    on_progress(skipped)
            break

        if index < len(tasks):
            if BATCH_SIZE > 0 and index % BATCH_SIZE == 0:
                _sleep_with_jitter(BATCH_DELAY_SECONDS)
            else:
                _sleep_with_jitter(REQUEST_DELAY_SECONDS)

    return {"total": len(tasks), "results": results}
