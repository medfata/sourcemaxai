"""Per-video summarization via MiniMax Anthropic-compatible endpoint."""

import asyncio
import json
import os
from pathlib import Path

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError

from backend.storage import get_channel_dir, load_selection, load_videos, read_json, write_json

SUMMARY_WORKERS = int(os.environ.get("SUMMARY_WORKERS", "5"))
MINIMAX_BASE_URL = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io/anthropic")

SUMMARIZE_SYSTEM_PROMPT = (
    "You analyze YouTube video transcripts and extract a structured profile of the content. "
    "Return ONLY valid JSON matching the schema. No prose, no markdown fences, no commentary.\n\n"
    "The transcript is provided as timestamped lines like [t=142s] <text>. "
    "For EVERY claim and EVERY opinion, you MUST include at least one evidence entry. "
    "Copy the start_seconds directly from the [t=…s] prefix of the line that supports the claim. "
    "Copy the quote EXACTLY as it appears in that line (not paraphrased, not summarized). "
    "Up to 3 evidence entries per claim. Each quote must be ≤120 characters.\n\n"
    "Example mini-summary:\n"
    '{\n'
    '  "core_topic": "Why people-pleasing undermines authenticity",\n'
    '  "key_claims": [\n'
    '    {"text": "Trying to be liked by everyone makes you authentic to no one", "evidence": [{"start_seconds": 142, "quote": "if you try to be liked by everyone you end up authentic to no one"}]},\n'
    '    {"text": "Discomfort is the price of growth", "evidence": [{"start_seconds": 318, "quote": "discomfort is literally the toll you pay"}]}\n'
    '  ],\n'
    '  "recurring_themes": ["authenticity", "discipline"],\n'
    '  "tone_markers": ["earnest", "direct"],\n'
    '  "notable_opinions": [\n'
    '    {"text": "Self-discipline matters more than talent", "evidence": [{"start_seconds": 512, "quote": "discipline will beat talent every single time"}]}\n'
    '  ],\n'
    '  "people_or_things_referenced": ["David Goggins"]\n'
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
    '  "people_or_things_referenced": ["proper nouns mentioned with significance, 0-10 items"]\n'
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
    '  "people_or_things_referenced": ["proper nouns mentioned with significance, 0-10 items"]\n'
    "}"
)


class Evidence(BaseModel):
    start_seconds: int
    quote: str


class Claim(BaseModel):
    text: str
    evidence: list[Evidence] = []


class VideoSummary(BaseModel):
    """Structured summary of a single video."""

    core_topic: str
    key_claims: list[Claim] = []
    recurring_themes: list[str] = []
    tone_markers: list[str] = []
    notable_opinions: list[Claim] = []
    people_or_things_referenced: list[str] = []


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
                "\n\nIMPORTANT: Your previous response was invalid or had too few evidence entries. "
                "Return ONLY valid JSON matching the schema above. "
                "No markdown fences, no explanation. "
                "Every claim and opinion MUST include at least one evidence entry with start_seconds and a verbatim quote from the transcript. "
                "Do not skip evidence."
            )

        response = await client.messages.create(
            model="MiniMax-M2.7",
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": user_message}],
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
                return {
                    "video_id": video_id,
                    "title": title,
                    "upload_date": upload_date,
                    **dump,
                }

            dump["key_claims"] = _verify_claims(dump.get("key_claims", []), segments)
            dump["notable_opinions"] = _verify_claims(dump.get("notable_opinions", []), segments)

            all_claims = dump.get("key_claims", []) + dump.get("notable_opinions", [])
            with_evidence = sum(1 for c in all_claims if c.get("evidence"))
            total = len(all_claims)
            if total > 0 and with_evidence / total < 0.5 and attempt == 0:
                print(f"[summarize] Evidence rate {with_evidence}/{total} for {video_id} too low, retrying...")
                continue

            return {
                "video_id": video_id,
                "title": title,
                "upload_date": upload_date,
                **dump,
            }
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
    channel_dir: Path,
    on_progress=None,
) -> dict:
    """Summarize a single video, respecting the concurrency semaphore."""
    summary_path = channel_dir / "summaries" / f"{video_id}.json"
    if summary_path.exists():
        if on_progress:
            on_progress({"video_id": video_id, "status": "skipped"})
        return {"video_id": video_id, "status": "skipped"}

    transcript_path = channel_dir / "transcripts" / f"{video_id}.json"
    transcript = read_json(transcript_path)
    if not transcript:
        if on_progress:
            on_progress({"video_id": video_id, "status": "skipped"})
        return {"video_id": video_id, "status": "skipped"}

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
        if on_progress:
            on_progress({"video_id": video_id, "status": "done"})
        return {"video_id": video_id, "status": "done", "data": result}

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
