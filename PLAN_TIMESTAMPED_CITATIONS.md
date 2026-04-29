# Plan: Timestamped Video Citations in Chat

## Goal

When the chat assistant makes a claim about a channel, it should link the claim to the exact moment in the source video — e.g. `[stops people-pleasing](https://youtu.be/abc123?t=142s)` — instead of asserting things without evidence the user can verify.

## Why this matters

Today the chat model can name videos by title but cannot point at *where* inside a video a claim originates. The aggregated profile has no time-anchored data, so any timestamp the model emits would be hallucinated. To make citations real, we have to plumb timestamps end-to-end: transcript → summary → profile → chat prompt → rendered link.

---

## Current state (what exists, what's missing)

**Has timestamps but discards them**
- `backend/pipeline/fetch_transcripts.py:51-55` calls `transcript.fetch()` (which returns segments with `.start` and `.duration`), then immediately joins all segment text into one cleaned blob. Per-segment timing is thrown away.

**No time anchors in summary schema**
- `backend/pipeline/summarize.py:16-28` defines a flat schema (`key_claims`, `notable_opinions`, …) of bare strings. No way to attach evidence.
- `VideoSummary` Pydantic model at `summarize.py:31` mirrors that schema.

**Aggregation passes summaries through unchanged**
- `backend/pipeline/aggregate.py:138-156` copies summary fields into the profile verbatim. Whatever shape we give summaries lands in `profile.json`.

**Chat prompt has no link guidance**
- `backend/pipeline/ask.py:11-26` gives the model the serialized profile and tells it to cite by title/date. No mention of URLs or markdown links.

**Frontend renders plain text**
- `frontend/src/pages/ChatPage.tsx:296-301` renders assistant content inside a `whitespace-pre-wrap` `<div>`. Markdown links would show as raw `[text](url)`.

---

## Target data shapes

### Transcript file (`data/<channel>/transcripts/<video_id>.json`)

Add `segments`. Keep `transcript_text` (still useful for word counts and as a fallback).

```json
{
  "video_id": "abc123",
  "title": "...",
  "upload_date": "20240115",
  "duration_seconds": 612,
  "source": "manual",
  "transcript_text": "...",
  "word_count": 1842,
  "segments": [
    { "start": 0.0,  "text": "Hey everyone welcome back" },
    { "start": 4.2,  "text": "today I want to talk about" },
    { "start": 7.8,  "text": "people pleasing and why it's killing your potential" }
  ]
}
```

Drop `duration` from segments — start is enough for the `?t=` link, and ranges aren't worth the storage.

### Summary file (`data/<channel>/summaries/<video_id>.json`)

Replace bare-string claims with objects carrying evidence. Keep theme/tone/referenced as bare strings (they're aggregate-level concepts; pinning a single timestamp to "authenticity" would be misleading).

```json
{
  "video_id": "abc123",
  "title": "...",
  "upload_date": "20240115",
  "core_topic": "Why people-pleasing is a trap",
  "key_claims": [
    {
      "text": "Trying to be liked by everyone makes you authentic to no one",
      "evidence": [
        { "start_seconds": 142, "quote": "if you try to be liked by everyone you end up authentic to no one" }
      ]
    }
  ],
  "notable_opinions": [
    {
      "text": "Discomfort is the price of growth",
      "evidence": [
        { "start_seconds": 318, "quote": "discomfort is literally the toll you pay" }
      ]
    }
  ],
  "recurring_themes": ["authenticity", "discipline"],
  "tone_markers": ["earnest", "direct"],
  "people_or_things_referenced": ["David Goggins"]
}
```

Constraints:
- `start_seconds` is an int (round down).
- `quote` ≤ 120 chars, must be a verbatim substring of some segment's text (validated server-side; see Step 3).
- 1–3 evidence entries per claim. Empty `evidence: []` is allowed but the validator will downgrade the claim to "unsourced" and exclude it from links.

### Profile (`data/<channel>/profile.json`)

Same shape as the summary objects above. The `videos[]` list now contains structured claims that the chat prompt can reference by `(video_id, start_seconds)`.

---

## Implementation steps

Do these in order. Each step ends in a runnable, reviewable state.

### Step 1 — Persist transcript segments

**File:** `backend/pipeline/fetch_transcripts.py`

- Keep the existing `transcript_text`/`word_count`/`source` fields untouched (downstream code still reads them).
- After `segments = transcript.fetch()` (line 51), build a `segments` list of `{start: float, text: str}` where `text` is run through `clean_text()` and segments whose cleaned text is empty are dropped.
- Add `"segments": segments_list` to the `data` dict written at line 57.
- Unavailable-transcript path (line 69) writes `"segments": []`.

**Validation:** delete one transcript JSON, re-run the transcript step for that video, confirm `segments` array is populated and `start` values are monotonically increasing.

### Step 2 — Send timestamped transcript to summarizer; expand schema

**File:** `backend/pipeline/summarize.py`

- New helper `_format_transcript_for_summary(segments) -> str` that emits one line per segment: `[t=142s] if you try to be liked by everyone…`. Use the `start` floored to int. If `segments` is empty (legacy transcripts), fall back to current `transcript_text` and skip evidence (the model will return empty evidence arrays).
- Update `SUMMARIZE_SYSTEM_PROMPT` to:
  - Document the new schema (claims/opinions are objects with `text` + `evidence[]`).
  - Tell the model: each evidence quote must be copied **verbatim** from a transcript line (not paraphrased), and `start_seconds` must be the `[t=…s]` from that line.
  - Cap evidence at 3 entries per claim, quote at ~120 chars.
- Update `VideoSummary` Pydantic model:
  ```python
  class Evidence(BaseModel):
      start_seconds: int
      quote: str

  class Claim(BaseModel):
      text: str
      evidence: list[Evidence] = []

  class VideoSummary(BaseModel):
      core_topic: str
      key_claims: list[Claim]
      recurring_themes: list[str]
      tone_markers: list[str]
      notable_opinions: list[Claim]
      people_or_things_referenced: list[str]
  ```
- In `_summarize_one`, after parsing, run a verifier: for each evidence, check that `quote` (case-insensitive, whitespace-collapsed) appears in the segment whose start matches `start_seconds` *or* in the immediate neighbor segments (±1). If it doesn't match, drop that evidence entry. If a claim ends up with zero evidence after verification, keep the claim text but leave `evidence: []`.
- The retry-on-bad-JSON loop at lines 65-98 already handles schema failures — no change needed.

**Validation:** re-summarize one video (delete its summary file first), inspect output: every claim has 1–3 evidence entries, each `start_seconds` corresponds to a real segment, each `quote` is a real substring.

### Step 3 — Aggregate passes claim objects through

**File:** `backend/pipeline/aggregate.py`

- `REQUIRED_SUMMARY_FIELDS` (line 10) stays the same — the field names haven't changed.
- Field re-mapping at lines 141-155 only touches `recurring_themes`, `tone_markers`, `people_or_things_referenced` (still strings) — no change needed.
- `key_claims` and `notable_opinions` flow through `dict(summary)` unchanged.

**Validation:** rebuild profile.json and grep for `"start_seconds"` in it — should appear under each video's claims.

### Step 4 — Update chat prompt to emit markdown links

**File:** `backend/pipeline/ask.py`

- Update `CHAT_SYSTEM_PROMPT_TEMPLATE`:
  - Explain the data shape: each claim has `evidence[]` with `{start_seconds, quote}`. Each video has a `video_id`.
  - Instruct the model: when stating a claim that maps to evidence in the summaries, render it as a markdown link `[claim text](https://youtu.be/<video_id>?t=<start_seconds>s)`. Include the link inline, not as a footnote.
  - Multiple supporting moments → multiple links: "He returns to this idea — see [the marathon video](url1) and [the comparison rant](url2)."
  - If a statement is the model's synthesis across many videos (i.e., no single evidence entry matches), do **not** invent a link. Say "across the channel" or similar.
- Keep the existing conciseness guidance.

**No code change to `chat_stream`** — it already streams whatever the model returns.

**Validation:** ask the chat "what does Finn say about people-pleasing?" — response should contain at least one `https://youtu.be/...?t=...s` link, not bare titles.

### Step 5 — Render markdown in chat bubbles

**File:** `frontend/src/pages/ChatPage.tsx`

- Add `react-markdown` (and `remark-gfm` for autolinks/lists) to `frontend/package.json`.
- Replace the assistant message body at lines 296-310:
  - Keep the typing-indicator branch.
  - For non-empty assistant content, render `<ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ... }}>{msg.content}</ReactMarkdown>`.
  - The `a` component override sets `target="_blank" rel="noopener noreferrer"` and a Tailwind class for the iOS-blue underlined link style.
- Keep user bubbles as plain text (they don't need markdown).
- Drop `whitespace-pre-wrap` from the assistant bubble — markdown handles paragraphs. Keep it on user bubbles.

**Validation:** in dev, send a message, confirm `[text](url)` renders as a clickable link that opens YouTube at the right timestamp in a new tab.

### Step 6 — Migration / re-run

Existing channels have transcripts without `segments` and summaries without `evidence`. Two options:

- **Recommended:** delete `data/<channel_id>/transcripts/` and `data/<channel_id>/summaries/` for any channel you want citations on, then re-run the pipeline from the transcript step. Profile rebuilds automatically.
- **Auto-detect (optional):** in `fetch_single_transcript`, if the existing JSON lacks `segments`, treat it as missing and re-fetch. Same for summaries lacking `evidence` on any claim. Costs API calls but is one-shot.

Pick one based on how many channels are already profiled.

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Model invents `start_seconds` that don't match the transcript | Step 2 verifier drops bad evidence; bad claims become unsourced rather than wrongly cited. |
| Quote-substring check is too strict (model paraphrases slightly) | Use case-insensitive whitespace-collapsed substring match against the target segment **and ±1 neighbors**. If still too strict in practice, widen to fuzzy match (rapidfuzz partial_ratio ≥ 85). |
| Summary token cost rises | Quotes are capped at ~120 chars; evidence at 3 per claim. Estimated +25–35% output tokens vs. current schema. Acceptable for a one-time per-video cost. |
| `react-markdown` bundle size | ~40KB gzip. Acceptable for a personal tool. If concerned, use a tiny custom regex-to-anchor renderer instead. |
| Old transcripts/summaries become unusable for citations | Documented in Step 6. They still work for non-cited chat — verifier just yields `evidence: []` for everything. |
| Long videos with many segments inflate the summarize prompt | Already bounded by transcript size. If a video exceeds the model's context, this is a pre-existing problem; not in scope. |

---

## Out of scope

- Inline transcript viewer / hover previews of the quoted text. Click-out to YouTube is enough for v1.
- Re-ranking or scoring evidence quality. Trust the model + verifier.
- Citations for theme/tone aggregates. Those are intrinsically multi-video; per-moment citation doesn't apply.
- Caching the markdown-rendered output. Re-render cost on each token is negligible.

---

## Acceptance criteria

1. New transcripts contain a non-empty `segments` array with monotonic `start` values.
2. New summaries have ≥80% of claims carrying at least one verified evidence entry (sampled across 5 videos).
3. A chat response to "where does the creator talk about X?" contains at least one `youtu.be/...?t=Ns` link, and clicking it opens YouTube at the cited moment, which audibly matches the quoted text.
4. No regression: chat still works on old channels whose summaries lack evidence (links just don't appear).
5. Frontend renders links as clickable, opens in new tab, no raw markdown leaks.
