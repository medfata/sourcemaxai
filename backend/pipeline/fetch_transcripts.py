"""Fetch YouTube video transcripts using youtube-transcript-api."""

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from backend.config import load_runtime_config
from backend.pipeline.proxy_pool import ProxyPool, build_proxy_pool
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
from youtube_transcript_api.proxies import GenericProxyConfig

try:
    from youtube_transcript_api import IpBlocked, RequestBlocked

    _BLOCK_EXCEPTIONS: tuple[type[Exception], ...] = (RequestBlocked, IpBlocked)
except ImportError:
    _BLOCK_EXCEPTIONS = tuple()

WORKERS = int(os.environ.get("TRANSCRIPT_WORKERS", "8"))

MAX_ATTEMPTS = load_runtime_config().proxy.max_attempts

BRACKET_TAGS = re.compile(
    r"\[(Music|Applause|Laughter|Inaudible|inaudible|music|applause|laughter)\]",
    re.IGNORECASE,
)


def clean_text(text: str) -> str:
    text = BRACKET_TAGS.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _list_transcripts_direct(video_id: str):
    return YouTubeTranscriptApi().list(video_id)


def fetch_with_retry(
    video_id: str,
    *,
    pool: ProxyPool,
    max_attempts: int,
    owner_id: str | None = None,
):
    """Acquire a proxy session per attempt and return a transcript list, retrying on IP blocks.

    Returns the `TranscriptList` on success, or a dict `{"status": "unavailable" | "failed", ...}`
    when the caller should short-circuit without further proxy attempts.
    """
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        provider, session_id = pool.acquire(video_id, attempt)
        url = pool.proxy_url(provider, session_id)
        cfg = GenericProxyConfig(http_url=url, https_url=url)
        try:
            return YouTubeTranscriptApi(proxy_config=cfg).list(video_id)
        except (TranscriptsDisabled, NoTranscriptFound):
            return {"video_id": video_id, "status": "unavailable"}
        except _BLOCK_EXCEPTIONS as exc:
            pool.mark_blocked(provider, session_id, str(exc) or exc.__class__.__name__)
            last_error = exc
            continue
        except Exception as exc:
            last_error = exc
            print(f"[transcript] attempt {attempt} failed for {video_id}: {exc}")
            continue

    return {
        "video_id": video_id,
        "status": "failed",
        "error": "all_proxies_blocked",
        "last_error": str(last_error) if last_error else None,
    }


def fetch_single_transcript(
    video_id: str,
    title: str,
    upload_date: str,
    duration: int,
    channel_id: str,
    channel_dir: Path,
    on_progress=None,
    *,
    pool: ProxyPool | None = None,
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
        if pool is None:
            transcript_list = _list_transcripts_direct(video_id)
        else:
            outcome = fetch_with_retry(
                video_id,
                pool=pool,
                max_attempts=MAX_ATTEMPTS,
            )
            if isinstance(outcome, dict):
                if outcome.get("status") == "unavailable":
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
                return outcome
            transcript_list = outcome

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
        return {"video_id": video_id, "status": "failed", "error": str(exc)}


def fetch_transcripts(
    channel_id: str,
    owner_id: str | None = None,
    on_progress=None,
) -> dict:
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

    cfg = load_runtime_config()
    pool = build_proxy_pool() if cfg.use_proxy_pool else None

    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        future_to_vid = {
            executor.submit(
                fetch_single_transcript,
                vid,
                title,
                upload_date,
                duration,
                channel_id,
                channel_dir,
                on_progress,
                pool=pool,
            ): vid
            for vid, title, upload_date, duration in tasks
        }
        for future in as_completed(future_to_vid):
            result = future.result()
            results.append(result)
            if on_progress:
                on_progress(result)

    return {"total": len(tasks), "results": results}
