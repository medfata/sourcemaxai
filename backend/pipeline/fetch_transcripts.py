"""Fetch YouTube video transcripts using youtube-transcript-api."""

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)

from backend.storage import get_channel_dir, load_videos, load_selection, read_json, write_json

WORKERS = int(os.environ.get("TRANSCRIPT_WORKERS", "8"))

BRACKET_TAGS = re.compile(r"\[(Music|Applause|Laughter|Inaudible|inaudible|music|applause|laughter)\]", re.IGNORECASE)


def clean_text(text: str) -> str:
    text = BRACKET_TAGS.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_single_transcript(video_id: str, title: str, upload_date: str, duration: int, channel_dir: Path, on_progress=None) -> dict:
    transcript_path = channel_dir / "transcripts" / f"{video_id}.json"
    if transcript_path.exists():
        existing = read_json(transcript_path)
        if existing:
            return {
                "video_id": video_id,
                "status": "skipped",
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
        return {"video_id": video_id, "status": "done", "data": data}

    except (TranscriptsDisabled, NoTranscriptFound):
        data = {
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
        return {"video_id": video_id, "status": "unavailable", "data": data}

    except Exception as exc:
        print(f"[transcript] Failed {video_id}: {exc}")
        return {"video_id": video_id, "status": "failed", "error": str(exc)}


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
            (vid, info.get("title", "Untitled"), info.get("upload_date", ""), info.get("duration", 0))
        )

    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        future_to_vid = {
            executor.submit(fetch_single_transcript, vid, title, upload_date, duration, channel_dir, on_progress): vid
            for vid, title, upload_date, duration in tasks
        }
        for future in as_completed(future_to_vid):
            result = future.result()
            results.append(result)
            if on_progress:
                on_progress(result)

    return {"total": len(tasks), "results": results}
