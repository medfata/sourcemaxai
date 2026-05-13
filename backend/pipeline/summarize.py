"""Per-video summarization via MiniMax Anthropic-compatible endpoint."""

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from anthropic import AsyncAnthropic
from backend.pipeline.schema_versions import (
    SUMMARY_MODEL,
    SUMMARY_SCHEMA_VERSION,
    get_summary_stale_reasons,
    get_transcript_stale_reasons,
)
from backend.quotas import (
    estimate_summary_cost_usd,
    get_quota_store,
    transcript_seconds_from_transcript,
)
from backend.storage import (
    current_owner_id,
    current_run_id,
    get_channel_dir,
    load_selection,
    load_videos,
    read_json,
    save_summary,
    write_json,
)
from pydantic import BaseModel, Field, ValidationError

SUMMARY_WORKERS = int(os.environ.get("SUMMARY_WORKERS", "5"))
MINIMAX_BASE_URL = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io/anthropic")

SUMMARIZE_SYSTEM_PROMPT = (
    "You analyze YouTube video transcripts and extract a structured profile of the content. "
    "Return ONLY valid JSON matching the schema. No prose, no markdown fences, no commentary.\n\n"
    "The transcript is provided as timestamped lines like [t=142s] <text>. "
    "For EVERY supported claim and EVERY supported opinion, include at least one evidence entry. "
    "Copy start_seconds directly from the [t=...s] prefix of the line that supports the claim. "
    "Copy the quote EXACTLY as it appears in that line, not paraphrased or summarized. "
    "Up to 3 evidence entries per claim. Each quote must be <=120 characters. "
    "If a claim or opinion is useful but no exact timestamped quote supports it, keep it with "
    '"evidence": [] instead of inventing evidence.\n\n'
    "The metadata fields are retrieval hints. Use concise, searchable phrases. "
    "questions_answered should be natural-language questions this video directly answers. "
    "concepts should be nouns or named ideas. tactics should be concrete actions, methods, "
    "or techniques. story_events should be concrete events, milestones, or anecdotes. "
    "audience should describe who would benefit from the video. "
    "summary_confidence is 0.0-1.0 based on transcript clarity and evidence coverage.\n\n"
    "Example mini-summary:\n"
    '{\n'
    '  "core_topic": "Why people-pleasing undermines authenticity",\n'
    '  "key_claims": [\n'
    '    {"text": "People-pleasing weakens authenticity", '
    '"evidence": [{"start_seconds": 142, '
    '"quote": "trying to please everyone makes you invisible"}]},\n'
    '    {"text": "Discomfort is the price of growth", '
    '"evidence": [{"start_seconds": 318, '
    '"quote": "discomfort is the toll you pay"}]}\n'
    '  ],\n'
    '  "recurring_themes": ["authenticity", "discipline"],\n'
    '  "tone_markers": ["earnest", "direct"],\n'
    '  "notable_opinions": [\n'
    '    {"text": "Self-discipline matters more than talent", '
    '"evidence": [{"start_seconds": 512, '
    '"quote": "discipline beats talent"}]}\n'
    '  ],\n'
    '  "people_or_things_referenced": ["David Goggins"],\n'
    '  "questions_answered": ["How does people-pleasing affect authenticity?"],\n'
    '  "concepts": ["authenticity", "self-discipline", "growth discomfort"],\n'
    '  "tactics": ["choose discomfort deliberately", "stop optimizing for approval"],\n'
    '  "story_events": [],\n'
    '  "audience": "people trying to build self-discipline and social confidence",\n'
    '  "summary_confidence": 0.87\n'
    '}\n\n'
    "Schema:\n"
    "{\n"
    '  "core_topic": "one-sentence summary of what this video is about",\n'
    '  "key_claims": [\n'
    '    {\n'
    '      "text": "specific assertion the speaker makes",\n'
    '      "evidence": [{"start_seconds": 142, "quote": "verbatim substring from transcript"}]\n'
    '    }\n'
    '  ],\n'
    '  "recurring_themes": ["broader themes touched on, 2-5 items"],\n'
    '  "tone_markers": ["adjectives describing how the speaker communicates, 2-4 items"],\n'
    '  "notable_opinions": [\n'
    '    {\n'
    '      "text": "distinctive opinion or hot take",\n'
    '      "evidence": [{"start_seconds": 318, "quote": "verbatim substring from transcript"}]\n'
    '    }\n'
    '  ],\n'
    '  "people_or_things_referenced": ["proper nouns mentioned with significance, 0-10 items"],\n'
    '  "questions_answered": ["searchable questions the video directly answers, 1-6 items"],\n'
    '  "concepts": ["important concepts, frameworks, named ideas, 2-10 items"],\n'
    '  "tactics": ["specific methods, actions, practices, 0-10 items"],\n'
    '  "story_events": ["specific stories, milestones, incidents, 0-8 items"],\n'
    '  "audience": "intended or best-fit audience in one short phrase",\n'
    '  "summary_confidence": 0.0\n'
    "}"
)

LEGACY_SUMMARIZE_SYSTEM_PROMPT = (
    "You analyze YouTube video transcripts and extract a structured profile of the content. "
    "Return ONLY valid JSON matching the schema. No prose, no markdown fences, no commentary.\n\n"
    "This transcript does not have per-sentence timestamps. "
    "Return claims and opinions as objects with text and evidence: []. "
    "Leave evidence empty; do not invent timestamps.\n\n"
    "Schema:\n"
    "{\n"
    '  "core_topic": "one-sentence summary of what this video is about",\n'
    '  "key_claims": [{"text": "assertion", "evidence": []}],\n'
    '  "recurring_themes": ["broader themes touched on, 2-5 items"],\n'
    '  "tone_markers": ["adjectives describing how the speaker communicates, 2-4 items"],\n'
    '  "notable_opinions": [{"text": "opinion", "evidence": []}],\n'
    '  "people_or_things_referenced": ["proper nouns mentioned with significance, 0-10 items"],\n'
    '  "questions_answered": ["searchable questions the video directly answers, 1-6 items"],\n'
    '  "concepts": ["important concepts, frameworks, named ideas, 2-10 items"],\n'
    '  "tactics": ["specific methods, actions, practices, 0-10 items"],\n'
    '  "story_events": ["specific stories, milestones, incidents, 0-8 items"],\n'
    '  "audience": "intended or best-fit audience in one short phrase",\n'
    '  "summary_confidence": 0.0\n'
    "}"
)


class Evidence(BaseModel):
    start_seconds: int
    quote: str


class Claim(BaseModel):
    text: str
    evidence: list[Evidence] = Field(default_factory=list)


class VideoSummary(BaseModel):
    """Structured summary of a single video."""

    core_topic: str
    key_claims: list[Claim] = Field(default_factory=list)
    recurring_themes: list[str] = Field(default_factory=list)
    tone_markers: list[str] = Field(default_factory=list)
    notable_opinions: list[Claim] = Field(default_factory=list)
    people_or_things_referenced: list[str] = Field(default_factory=list)
    questions_answered: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    tactics: list[str] = Field(default_factory=list)
    story_events: list[str] = Field(default_factory=list)
    audience: str = ""
    summary_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


def _extract_json(text: str) -> str:
    """Strip markdown fences and extraneous whitespace from a JSON string."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _prompt_hash(prompt: str) -> str:
    """Return a stable short hash for the summarizer prompt used."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def _format_transcript_for_summary(segments: list[dict]) -> str:
    """Emit one line per segment with its timestamp."""
    if not segments:
        return ""
    lines = []
    for seg in segments:
        start = int(seg.get("start", 0))
        text = seg.get("text", "")
        lines.append(f"[t={start}s] {text}")
    return "\n".join(lines)


def _collapse(text: str) -> str:
    """Case-insensitive, whitespace-collapsed string for fuzzy matching."""
    return "".join(text.split()).lower()


def _verify_claims(claims: list[dict], segments: list[dict]) -> list[dict]:
    """Drop evidence whose quote does not appear in the target segment or its neighbors."""
    if not segments:
        return [{"text": c.get("text", ""), "evidence": []} for c in claims]

    segment_collapsed = [_collapse(seg.get("text", "")) for seg in segments]
    start_to_index = {int(seg.get("start", 0)): i for i, seg in enumerate(segments)}

    verified = []
    for claim in claims:
        text = claim.get("text", "")
        evidence = claim.get("evidence", [])
        good = []
        for ev in evidence:
            quote = ev.get("quote", "")
            start_seconds = ev.get("start_seconds", 0)
            idx = start_to_index.get(start_seconds)
            if idx is None:
                continue
            quote_collapsed = _collapse(quote)
            found = False
            for j in range(max(0, idx - 1), min(len(segment_collapsed), idx + 2)):
                if quote_collapsed in segment_collapsed[j]:
                    found = True
                    break
            # Also check concatenation of neighbors for quotes that span segments
            if not found:
                concat_start = max(0, idx - 1)
                concat_end = min(len(segment_collapsed), idx + 2)
                combined = "".join(segment_collapsed[concat_start:concat_end])
                if quote_collapsed in combined:
                    found = True
            if found:
                good.append(ev)
        verified.append({"text": text, "evidence": good})
    return verified


def _summary_evidence_metrics(summary: dict) -> dict:
    """Return evidence coverage metrics for claim-like summary fields."""
    all_claims = []
    for field in ("key_claims", "notable_opinions"):
        items = summary.get(field, [])
        if isinstance(items, list):
            all_claims.extend(item for item in items if isinstance(item, dict))

    claim_count = len(all_claims)
    supported_claim_count = sum(1 for claim in all_claims if claim.get("evidence"))
    unsupported_claim_count = claim_count - supported_claim_count
    evidence_rate = supported_claim_count / claim_count if claim_count else 1.0
    return {
        "claim_count": claim_count,
        "supported_claim_count": supported_claim_count,
        "unsupported_claim_count": unsupported_claim_count,
        "summary_evidence_rate": round(evidence_rate, 3),
    }


def _cap_summary_confidence(summary: dict, *, legacy: bool) -> None:
    """Keep confidence bounded and tied to verified evidence coverage."""
    metrics = _summary_evidence_metrics(summary)
    try:
        model_confidence = float(summary.get("summary_confidence", 0.0))
    except (TypeError, ValueError):
        model_confidence = 0.0
    model_confidence = min(max(model_confidence, 0.0), 1.0)

    evidence_rate = float(metrics["summary_evidence_rate"])
    evidence_cap = 0.25 if legacy else 0.35 + 0.65 * evidence_rate
    summary["summary_confidence"] = round(min(model_confidence, evidence_cap), 3)


def _record_summary_usage(input_tokens: int, output_tokens: int) -> None:
    """Best-effort usage_events insert for the active owner/run."""
    owner_id = current_owner_id()
    if not owner_id:
        return
    cost = estimate_summary_cost_usd(input_tokens, output_tokens)
    try:
        get_quota_store().record_usage(
            owner_id,
            event_type="summary",
            run_id=current_run_id(),
            model=SUMMARY_MODEL,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[summarize] usage record failed: {exc}")


def _record_summary_transcript_usage(transcript_seconds: int) -> None:
    """Record billable transcript seconds after a summary is successfully written."""
    owner_id = current_owner_id()
    if not owner_id or transcript_seconds <= 0:
        return
    try:
        get_quota_store().record_usage(
            owner_id,
            event_type="summary_transcript",
            run_id=current_run_id(),
            model=SUMMARY_MODEL,
            transcript_seconds=transcript_seconds,
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[summarize] transcript usage record failed: {exc}")


def _summary_metadata(
    video_id: str,
    title: str,
    upload_date: str,
    system_prompt: str,
) -> dict:
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "summary_schema_version": SUMMARY_SCHEMA_VERSION,
        "video_id": video_id,
        "title": title,
        "upload_date": upload_date,
        "model": SUMMARY_MODEL,
        "prompt_hash": _prompt_hash(system_prompt),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def _summarize_one(
    client: AsyncAnthropic,
    video_id: str,
    title: str,
    upload_date: str,
    transcript_text: str,
    segments: list[dict],
) -> dict:
    """Call the LLM for a single video and return the parsed summary dict."""
    formatted = _format_transcript_for_summary(segments)
    if formatted:
        transcript_block = formatted
    else:
        transcript_block = transcript_text

    user_message = f"Title: {title}\nDate: {upload_date}\nTranscript:\n{transcript_block}"

    legacy = not segments

    for attempt in range(2):
        system = LEGACY_SUMMARIZE_SYSTEM_PROMPT if legacy else SUMMARIZE_SYSTEM_PROMPT
        if attempt > 0:
            system += (
                "\n\nIMPORTANT: Your previous response was invalid or had too few "
                "evidence entries. "
                "Return ONLY valid JSON matching the schema above. "
                "No markdown fences, no explanation. "
                "Every supported claim and opinion MUST include at least one evidence "
                "entry with start_seconds and a verbatim quote from the transcript. "
                "Do not skip evidence."
            )

        response = await client.messages.create(
            model=SUMMARY_MODEL,
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        usage = getattr(response, "usage", None)
        if usage is not None:
            _record_summary_usage(
                int(getattr(usage, "input_tokens", 0) or 0),
                int(getattr(usage, "output_tokens", 0) or 0),
            )
        raw = next(
            (block.text for block in response.content if getattr(block, "type", None) == "text"),
            "",
        )
        raw_json = _extract_json(raw)

        try:
            parsed = json.loads(raw_json)
            summary = VideoSummary.model_validate(parsed)
            dump = summary.model_dump()

            if legacy:
                _cap_summary_confidence(dump, legacy=True)
                return {**_summary_metadata(video_id, title, upload_date, system), **dump}

            dump["key_claims"] = _verify_claims(dump.get("key_claims", []), segments)
            dump["notable_opinions"] = _verify_claims(dump.get("notable_opinions", []), segments)
            _cap_summary_confidence(dump, legacy=False)

            metrics = _summary_evidence_metrics(dump)
            with_evidence = metrics["supported_claim_count"]
            total = metrics["claim_count"]
            if total > 0 and metrics["summary_evidence_rate"] < 0.5 and attempt == 0:
                print(
                    f"[summarize] Evidence rate {with_evidence}/{total} "
                    f"for {video_id} too low, retrying..."
                )
                continue

            return {**_summary_metadata(video_id, title, upload_date, system), **dump}
        except (json.JSONDecodeError, ValidationError) as exc:
            print(f"[summarize] Parse failed for {video_id} (attempt {attempt + 1}): {exc}")
            if attempt == 0:
                continue
            raise

    return {}


async def summarize_video(
    client: AsyncAnthropic,
    semaphore: asyncio.Semaphore,
    video_id: str,
    title: str,
    upload_date: str,
    channel_id: str,
    channel_dir: Path,
    on_progress=None,
) -> dict:
    """Summarize a single video, respecting the concurrency semaphore."""
    summary_path = channel_dir / "summaries" / f"{video_id}.json"
    if summary_path.exists():
        summary = read_json(summary_path)
        stale_reasons = get_summary_stale_reasons(summary)
        metrics = _summary_evidence_metrics(summary) if isinstance(summary, dict) else {}
        summary_confidence = (
            summary.get("summary_confidence") if isinstance(summary, dict) else None
        )
        if on_progress:
            on_progress(
                {
                    "video_id": video_id,
                    "status": "skipped",
                    "schema_current": not stale_reasons,
                    "stale": bool(stale_reasons),
                    "stale_reasons": stale_reasons,
                    "summary_confidence": summary_confidence,
                    **metrics,
                }
            )
        return {
            "video_id": video_id,
            "status": "skipped",
            "schema_current": not stale_reasons,
            "stale": bool(stale_reasons),
            "stale_reasons": stale_reasons,
            "summary_confidence": summary_confidence,
            **metrics,
        }

    transcript_path = channel_dir / "transcripts" / f"{video_id}.json"
    transcript = read_json(transcript_path)
    if not transcript:
        if on_progress:
            on_progress({"video_id": video_id, "status": "skipped"})
        return {"video_id": video_id, "status": "skipped"}

    transcript_stale_reasons = get_transcript_stale_reasons(transcript)
    if transcript_stale_reasons:
        if on_progress:
            on_progress(
                {
                    "video_id": video_id,
                    "status": "skipped",
                    "stale": True,
                    "stale_reasons": transcript_stale_reasons,
                }
            )
        return {
            "video_id": video_id,
            "status": "skipped",
            "stale": True,
            "stale_reasons": transcript_stale_reasons,
        }

    source = transcript.get("source", "")
    if source in ("unavailable", ""):
        if on_progress:
            on_progress({"video_id": video_id, "status": "skipped"})
        return {"video_id": video_id, "status": "skipped"}

    transcript_text = transcript.get("transcript_text", "")
    if not transcript_text:
        if on_progress:
            on_progress({"video_id": video_id, "status": "skipped"})
        return {"video_id": video_id, "status": "skipped"}

    segments = transcript.get("segments", [])
    if not segments:
        stale_reasons = ["missing_timestamped_segments"]
        if on_progress:
            on_progress(
                {
                    "video_id": video_id,
                    "status": "skipped",
                    "stale": True,
                    "stale_reasons": stale_reasons,
                }
            )
        return {
            "video_id": video_id,
            "status": "skipped",
            "stale": True,
            "stale_reasons": stale_reasons,
        }

    try:
        async with semaphore:
            if on_progress:
                on_progress({"video_id": video_id, "status": "fetching"})
            result = await _summarize_one(
                client, video_id, title, upload_date, transcript_text, segments
            )
        if not result:
            if on_progress:
                on_progress({"video_id": video_id, "status": "failed"})
            return {"video_id": video_id, "status": "failed"}

        write_json(summary_path, result)
        save_summary(channel_id, "manual", video_id, result)
        _record_summary_transcript_usage(transcript_seconds_from_transcript(transcript))
        metrics = _summary_evidence_metrics(result)
        if on_progress:
            on_progress(
                {
                    "video_id": video_id,
                    "status": "done",
                    "summary_confidence": result.get("summary_confidence"),
                    **metrics,
                }
            )
        return {
            "video_id": video_id,
            "status": "done",
            "summary_confidence": result.get("summary_confidence"),
            **metrics,
            "data": result,
        }

    except Exception as exc:
        print(f"[summarize] Failed {video_id}: {exc}")
        if on_progress:
            on_progress({"video_id": video_id, "status": "failed"})
        return {"video_id": video_id, "status": "failed", "error": str(exc)}


async def summarize(channel_id: str, on_progress=None) -> dict:
    """Summarize all selected videos for a channel."""
    channel_dir = get_channel_dir(channel_id)
    summaries_dir = channel_dir / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)

    selection = load_selection(channel_id)
    if not selection:
        return {"total": 0, "results": []}

    videos = load_videos(channel_id) or []
    video_map = {v["id"]: v for v in videos}

    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY environment variable is not set")

    async with AsyncAnthropic(
        api_key=api_key,
        base_url=MINIMAX_BASE_URL,
    ) as client:
        semaphore = asyncio.Semaphore(SUMMARY_WORKERS)

        tasks = []
        for vid in selection:
            info = video_map.get(vid, {})
            tasks.append(
                summarize_video(
                    client,
                    semaphore,
                    vid,
                    info.get("title", "Untitled"),
                    info.get("upload_date", ""),
                    channel_id,
                    channel_dir,
                    on_progress=on_progress,
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)
        parsed_results = []
        for r in results:
            if isinstance(r, Exception):
                print(f"[summarize] Task raised exception: {r}")
                continue
            parsed_results.append(r)

        return {"total": len(tasks), "results": parsed_results}
