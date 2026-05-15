"""Fetch YouTube video transcripts using youtube-transcript-api."""

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from backend import storage
from backend.config import load_runtime_config
from backend.pipeline.proxy_pool import CircuitBreaker, ProxyPool, build_proxy_pool
from backend.pipeline.schema_versions import (
    TRANSCRIPT_SCHEMA_VERSION,
    get_transcript_stale_reasons,
)
from backend.quotas import ESTIMATED_BYTES_PER_TRANSCRIPT, OwnerConcurrencyGate, get_quota_store
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
    # Dev-only path: prod config validation rejects boot without IPRoyal creds
    # (backend/config.py:171), so build_proxy_pool() never returns None in prod
    # and this is unreachable there. In local dev without proxy creds it is the
    # only way to fetch a transcript.
    return YouTubeTranscriptApi().list(video_id)


def _build_circuit_breaker() -> CircuitBreaker | None:
    """Construct a Supabase-backed breaker, or `None` when storage is local-only."""
    if os.environ.get("STORAGE_BACKEND", "local").strip().lower() != "supabase":
        return None
    try:
        return CircuitBreaker(storage.SupabaseStorageBackend.from_env())
    except storage.StorageConfigError:
        return None


def fetch_with_retry(
    video_id: str,
    *,
    pool: ProxyPool,
    max_attempts: int,
    owner_id: str | None = None,
    breaker: CircuitBreaker | None = None,
):
    """Acquire a proxy session per attempt and return a transcript list, retrying on IP blocks.

    Returns the `TranscriptList` on success, or a dict `{"status": "unavailable" | "failed", ...}`
    when the caller should short-circuit without further proxy attempts.
    """
    last_error: Exception | None = None
    if breaker is None:
        breaker = _build_circuit_breaker()
    open_providers: set[str] = set()
    known_providers: set[str] | None = None
    for attempt in range(1, max_attempts + 1):
        provider, session_id = pool.acquire(video_id, attempt)
        if breaker is not None and breaker.is_open(provider.name):
            open_providers.add(provider.name)
            if known_providers is None:
                known_providers = {p.name for p in getattr(pool, "providers", [])}
            if known_providers and open_providers >= known_providers:
                return {
                    "video_id": video_id,
                    "status": "failed",
                    "error": "circuit_open",
                    "providers_open": sorted(open_providers),
                }
            continue
        url = pool.proxy_url(provider, session_id)
        cfg = GenericProxyConfig(http_url=url, https_url=url)
        try:
            result = YouTubeTranscriptApi(proxy_config=cfg).list(video_id)
            if breaker is not None:
                breaker.record_success(provider.name)
            if owner_id is not None:
                get_quota_store().record_usage(
                    owner_id=owner_id,
                    event_type="transcript_fetch",
                    proxy_bytes=ESTIMATED_BYTES_PER_TRANSCRIPT,
                    proxy_provider=provider.name,
                )
            return result
        except (TranscriptsDisabled, NoTranscriptFound):
            return {"video_id": video_id, "status": "unavailable"}
        except _BLOCK_EXCEPTIONS as exc:
            if breaker is not None:
                breaker.record_failure(provider.name, reason=str(exc) or exc.__class__.__name__)
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


def _fetch_with_gate(
    video_id: str,
    title: str,
    upload_date: str,
    duration: int,
    channel_id: str,
    channel_dir: Path,
    on_progress,
    pool: ProxyPool | None,
    semaphore: threading.Semaphore | None,
    owner_id: str | None,
    breaker: CircuitBreaker | None,
) -> dict:
    if semaphore is not None:
        with semaphore:
            return fetch_single_transcript(
                video_id,
                title,
                upload_date,
                duration,
                channel_id,
                channel_dir,
                on_progress,
                pool=pool,
                owner_id=owner_id,
                breaker=breaker,
            )
    return fetch_single_transcript(
        video_id,
        title,
        upload_date,
        duration,
        channel_id,
        channel_dir,
        on_progress,
        pool=pool,
        owner_id=owner_id,
        breaker=breaker,
    )


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
    owner_id: str | None = None,
    breaker: CircuitBreaker | None = None,
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
                owner_id=owner_id,
                breaker=breaker,
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

    pool = build_proxy_pool()
    breaker = _build_circuit_breaker() if pool is not None else None

    semaphore: threading.Semaphore | None = None
    if owner_id is not None:
        quota_store = get_quota_store()
        quota = quota_store.get_quota(owner_id)
        semaphore = OwnerConcurrencyGate.get().acquire(owner_id, quota.transcript_concurrency)

    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        future_to_vid = {
            executor.submit(
                _fetch_with_gate,
                vid,
                title,
                upload_date,
                duration,
                channel_id,
                channel_dir,
                on_progress,
                pool,
                semaphore,
                owner_id,
                breaker,
            ): vid
            for vid, title, upload_date, duration in tasks
        }
        for future in as_completed(future_to_vid):
            result = future.result()
            results.append(result)
            if on_progress:
                on_progress(result)

    return {"total": len(tasks), "results": results}
