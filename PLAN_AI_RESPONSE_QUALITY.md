# Plan: Source-Grounded AI Chat Quality

## Goal

Improve the AI chat so it returns more accurate, specific, well-cited answers from
YouTube captions.

The current app is already useful for broad channel profiling, but the chat is
limited by a profile-only architecture: captions are summarized once, then the
chat model receives the whole profile JSON every turn. That loses detail,
increases token use, weakens attention, and lets citations depend too much on
model behavior.

The target architecture is:

1. Keep per-video summaries for overview and navigation.
2. Preserve caption chunks as the source of truth.
3. Retrieve only relevant caption chunks and verified claims at chat time.
4. Require model answers to cite server-provided source IDs.
5. Render and validate citations from backend-owned source metadata.
6. Measure answer quality with a repeatable evaluation set.

## Principles

- Captions are the ground truth. Summaries are an index, not the source of truth.
- Do not send the full profile to the model unless the selected channel is tiny.
- Do not trust the model to invent citation URLs. Give it source IDs and map them
  to URLs in code.
- Every specific factual claim should be supported by a retrieved source.
- Broad synthesis is allowed, but it must be labeled as synthesis across the
  channel when no single timestamp supports it.
- Keep the local-first design. Prefer deterministic files and SQLite before
  adding hosted services.
- Make every pipeline stage idempotent and schema-versioned.
- Improve quality with evaluation, not just subjective prompt tweaks.

## Current Problems

### 1. Chat context is too large and too unfocused

`backend/pipeline/ask.py` serializes the filtered profile and injects it into the
system prompt. For a 100+ video channel this can be a very large JSON blob. The
model has to search the full profile inside its attention window on every turn.

Result:
- Slower first-token latency.
- Higher chat cost.
- More generic answers.
- More missed details.
- Harder long conversations because previous messages compete with profile JSON.

### 2. Summaries drop too much caption detail

The summarizer extracts a small number of claims per video. If the user asks
about a detail not captured in those claims, chat cannot recover it because raw
captions are not retrieved at question time.

Result:
- Good answers to broad questions.
- Weak answers to niche, specific, or quote-seeking questions.
- False "not covered" answers when captions did contain the answer.

### 3. Citations are not backend-guaranteed

The prompt asks the model to output YouTube timestamp links. This works when the
model follows instructions, but the backend does not own the citation mapping.

Result:
- Possible malformed links.
- Possible links to timestamps that were not actually used.
- Harder UI source rendering.
- Harder evaluation.

### 4. Frontend data-shape bugs reduce current quality

Fix these before judging the model:

- `frontend/src/pages/ChatPage.tsx` fetches `/api/profile` and stores the whole
  API envelope instead of `body.data`.
- Citation extraction appears to parse the timestamp capture instead of the full
  citation href.
- Chat scope sends `dateFrom` and `dateTo`, while the backend model expects
  `date_from` and `date_to`.
- Evidence pane citation-strip filtering only shows the focused citation, not
  all citations from the same answer.
- Auto-focus after streaming uses stale message state, so the first citation may
  not load reliably.

### 5. No answer-quality evaluation

There is no repeatable test that says whether a change improved answers.

Result:
- Prompt changes are hard to compare.
- Retrieval quality is invisible.
- Citation regressions can slip in.

## Target Architecture

### Data Layers

Use three levels of data, each with a clear purpose.

#### Level 1: Transcript Segments

Already mostly present in transcript JSON:

```json
{
  "schema_version": 2,
  "video_id": "...",
  "title": "...",
  "upload_date": "20251130",
  "source": "manual",
  "segments": [
    { "start": 142.3, "text": "..." }
  ]
}
```

Best practice:
- Store `schema_version`.
- Store `duration` per segment if available.
- Preserve cleaned text and raw-ish text if possible.
- Keep `transcript_text` for quick previews and word counts.
- Detect old transcript files that lack `segments` and mark them stale.

#### Level 2: Caption Chunks

Add a deterministic chunking stage after transcripts.

Chunk shape:

```json
{
  "chunk_id": "videoid:0007",
  "video_id": "videoid",
  "title": "Video title",
  "upload_date": "20251130",
  "start_seconds": 315,
  "end_seconds": 398,
  "text": "caption text for this chunk...",
  "word_count": 180
}
```

Chunking rules:
- Merge adjacent transcript segments into 45-90 second chunks.
- Prefer 120-250 words per chunk.
- Add a small overlap, around 10-20 seconds, so ideas spanning boundaries are
  still retrievable.
- Use stable chunk IDs so cache files and citations do not churn.
- Keep chunks sorted by upload date, video, then timestamp.

Storage options:
- Phase 1: `data/channels/{channel_id}/chunks.jsonl`.
- Phase 2: SQLite with FTS5 for search.

Recommended local storage:

```sql
videos(video_id primary key, title, upload_date, duration_seconds, source)
chunks(chunk_id primary key, video_id, start_seconds, end_seconds, text, word_count)
chunks_fts(chunk_id, title, text) using FTS5
claims(claim_id primary key, video_id, start_seconds, text, quote, kind)
```

SQLite is the right default for this app: local, inspectable, fast enough, and no
extra service.

#### Level 3: Profile Summary

Keep the existing `profile.json`, but treat it as:

- Channel map.
- Theme/tone/reference rollup.
- Timeline overview.
- Retrieval hint source.

Do not treat it as the only chat source.

## Implementation Plan

### Phase 0: Fix Current Correctness Bugs

This phase should be small and should land before architecture changes.

Backend:
- Accept both `date_from/date_to` and `dateFrom/dateTo` for `ChatScope`, or map
  frontend fields before sending.
- Add tests for scoped chat date filters.

Frontend:
- In `ChatPage`, unwrap `/api/profile` as `body.data`.
- Fix citation regex/extraction so it passes the full href to
  `parseCitationHref`.
- Fix `extractCitations` to look inside `profile.videos[*].key_claims` and
  `profile.videos[*].notable_opinions`, not root-level profile fields.
- Fix evidence pane citation strip to show all refs from the same assistant
  message, not only the currently focused timestamp.
- Fix stream-complete auto-focus using the final assistant message from the
  state update, not stale `messages`.
- Add unit tests where practical and one Playwright/manual checklist item for
  citation click behavior.

Acceptance:
- Profile data appears in `ScopeChips`.
- Date filters actually reduce backend prompt videos.
- Clicking a citation opens the evidence pane with the correct quote.
- Existing backend tests still pass.

### Phase 1: Add Schema Versioning And Stale Detection

Add version fields to generated files:

- transcript JSON: `schema_version`
- summary JSON: `schema_version`
- profile JSON: `schema_version`
- chunk index: `schema_version`

Add helpers:

- `is_transcript_current(data)`.
- `is_summary_current(data)`.
- `is_profile_current(data)`.
- `is_chunk_index_current(data)`.

Best practice:
- Never silently mix old and new schema shapes.
- If a file is stale, mark it in pipeline state and regenerate when the relevant
  stage runs.
- Include `model`, `prompt_hash`, and `generated_at` in summaries.

Acceptance:
- Old summaries without evidence are detected as stale or legacy.
- Old transcripts without segments are detected as stale or legacy.
- Pipeline UI can tell the user what needs rebuilding.

### Phase 2: Build Caption Chunk Index

Create a new backend module:

`backend/pipeline/chunk_transcripts.py`

Responsibilities:
- Read selected transcript files.
- Skip unavailable transcripts.
- Build deterministic chunks from segments.
- Write `chunks.jsonl` and/or SQLite FTS index.
- Report progress through pipeline state.

Recommended first implementation:
- Write `chunks.jsonl` for easy inspection.
- Also create SQLite FTS if Python's built-in SQLite supports FTS5 on the target
  machine.
- If FTS5 is unavailable, fallback to JSONL plus simple BM25-like scoring or
  token overlap.

Pipeline placement:

`transcripts -> chunks -> summaries -> profile`

Summaries can still run per video. Chunking is a separate deterministic stage.

Acceptance:
- Every available transcript produces chunks.
- Chunk start/end times map to real transcript timestamps.
- Chunk index rebuild is idempotent.
- Basic query for a phrase returns the chunk containing that phrase.

### Phase 3: Add Retrieval Service

Create:

`backend/pipeline/retrieve.py`

Core function:

```python
def retrieve_context(channel_id: str, query: str, scope: ChatScope | None, limit: int = 12) -> list[Source]:
    ...
```

Source shape:

```json
{
  "source_id": "S1",
  "kind": "chunk",
  "video_id": "...",
  "title": "...",
  "upload_date": "20251130",
  "start_seconds": 315,
  "end_seconds": 398,
  "quote": "...",
  "text": "...",
  "score": 12.4
}
```

Retrieval strategy v1:
- Search FTS chunks with the user query.
- Search verified claims separately.
- Boost exact title, theme, referenced-person, and proper-noun matches.
- Apply scope filters before ranking.
- Deduplicate near-identical chunks from the same video.
- Keep chronological diversity for evolution questions.

Retrieval strategy v2:
- Add optional embeddings.
- Use hybrid ranking: lexical score + embedding score + recency/intent boosts.
- Rerank top 30 down to top 8-15 with a cheap model if needed.

Intent detection:

Use simple rules first:

- `overview`: broad channel questions.
- `specific`: asks about a topic, quote, person, tactic, belief.
- `evolution`: asks "changed", "over time", "evolved", "before vs now".
- `comparison`: asks "compare", "difference", "versus".
- `claims`: asks "top claims", "beliefs", "what does he think".

Intent affects retrieval:
- Overview: profile rollups + representative claims.
- Specific: chunks + claims.
- Evolution: chunks/claims across time buckets.
- Comparison: retrieve separately for each side.
- Claims: verified claims first, chunks second.

Acceptance:
- Retrieval returns relevant chunks for known phrases.
- Scope filters affect retrieval results.
- Evolution queries return sources spread across dates.
- No result outside selected videos or active scope.

### Phase 4: Replace Full-Profile Chat Prompt With Context Builder

Create:

`backend/pipeline/chat_context.py`

Responsibilities:
- Build a compact channel card from profile.
- Call retrieval for the user query.
- Format a source pack for the model.
- Format recent conversation history.
- Enforce a token/context budget.

Prompt structure:

```text
You answer questions about a YouTube channel using provided sources.

Rules:
- Use the source pack for specific claims.
- Cite source IDs like [S1] after supported clauses.
- Do not cite sources you did not use.
- If the source pack does not contain enough evidence, say what is missing.
- For broad synthesis, say "across the channel" and cite representative sources
  when available.

CHANNEL CARD:
...

SOURCE PACK:
[S1] title="..." date=20251130 t=315 quote="..."
[S2] title="..." date=20241002 t=91 quote="..."

PROFILE HINTS:
top themes, references, tone distribution, date range
```

Best practices:
- Put stable instructions in `system`.
- Put retrieved source pack in the latest user turn or an adjacent assistant-side
  context block, depending on SDK constraints.
- Keep source text compact.
- Do not include all videos by default.
- Include full profile only for tiny channels or explicit "whole channel
  overview" requests.

Conversation handling:
- Send the last N messages, not unlimited history.
- Add an optional rolling conversation summary after long chats.
- Never let conversation history displace the source pack.

Acceptance:
- Chat answers still stream.
- Context size drops substantially for 100+ video channels.
- Specific questions include citations from retrieved sources.
- If no source is retrieved, the answer says there is not enough caption evidence.

### Phase 5: Backend-Owned Citations

Change chat SSE protocol to include a source registry.

Before streaming text:

```json
data: {"type":"sources","sources":[{"source_id":"S1","video_id":"...","start_seconds":315,"quote":"...","title":"..."}]}
```

Then stream deltas as today:

```json
data: {"type":"delta","text":"... [S1] ..."}
```

Frontend:
- Store the latest source registry per assistant message.
- Render `[S1]` as the existing citation pill.
- Use registry metadata to open the evidence pane.
- Keep Cmd-click or middle-click behavior by generating the YouTube URL from the
  registry.

Backend validation:
- The source registry is created by retrieval, not by the model.
- After completion, optionally scan the answer for unknown `[S99]` markers and
  emit a warning frame or strip them in a post-processing path.

Streaming note:
- Do not wait until the full answer is complete to create citations. Send the
  source registry before deltas so the frontend can render markers as they
  arrive.

Acceptance:
- The model can only cite source IDs the backend provided.
- Unknown source IDs are visibly handled.
- Citation clicks no longer depend on parsing YouTube URLs from markdown.
- Evidence pane uses exact retrieved quote metadata.

### Phase 6: Improve Summarization For Retrieval

The current summarizer is useful but should be tuned for indexing.

Schema additions:

```json
{
  "summary_schema_version": 3,
  "core_topic": "...",
  "key_claims": [...],
  "notable_opinions": [...],
  "questions_answered": ["..."],
  "concepts": ["..."],
  "tactics": ["..."],
  "story_events": ["..."],
  "audience": "...",
  "summary_confidence": 0.0
}
```

Best practices:
- Keep evidence verification strict.
- Store unsupported claims, but mark them `evidence: []` and avoid using them as
  citation sources.
- Add prompt hash and model metadata.
- Retry when evidence rate is too low.
- Track per-video evidence rate in pipeline state.

Acceptance:
- Summary evidence rate improves.
- Unsupported claims are not used for source citations.
- Retrieval can search concepts/tactics/questions as metadata.

### Phase 7: Evaluation Harness

Create:

`backend/evals/chat_quality_cases.json`
`backend/evals/run_chat_eval.py`

Case shape:

```json
{
  "channel_id": "...",
  "question": "What does he say about brand?",
  "expected_video_ids": ["..."],
  "expected_terms": ["brand", "values", "promise"],
  "requires_citation": true,
  "notes": "Should cite the brand video."
}
```

Metrics:
- Citation validity: every cited source exists in registry.
- Citation grounding: cited quote actually appears in chunk/segment.
- Source recall: answer cited at least one expected video when specified.
- Faithfulness: judge whether answer claims are supported by provided sources.
- Refusal correctness: answer says "not enough evidence" when retrieval has no
  support.
- Latency and rough token count.

Testing layers:
- Unit tests for chunking.
- Unit tests for retrieval ranking.
- Unit tests for scope filters.
- Unit tests for citation registry rendering.
- Golden eval questions for qualitative regression.

Acceptance:
- At least 25 eval cases across 2-3 channels.
- Eval report compares old full-profile chat vs new retrieval chat.
- New architecture improves citation validity to near 100%.
- New architecture improves source recall on specific questions.

## Recommended Work Order

1. Fix current frontend/backend data-shape bugs.
2. Add schema versioning and stale detection.
3. Add caption chunk generation.
4. Add FTS retrieval over caption chunks.
5. Add chat context builder.
6. Switch `/api/chat` from full-profile prompt to retrieved source pack.
7. Add source registry SSE frame and frontend `[S1]` citation rendering.
8. Improve summary schema only after retrieval is working.
9. Add eval harness and compare both chat modes.
10. Remove or downgrade old full-profile chat path after eval proves the new path.

## Files Likely To Change

Backend:
- `backend/models.py`
- `backend/pipeline/fetch_transcripts.py`
- `backend/pipeline/summarize.py`
- `backend/pipeline/aggregate.py`
- `backend/pipeline/ask.py`
- `backend/pipeline/chunk_transcripts.py`
- `backend/pipeline/retrieve.py`
- `backend/pipeline/chat_context.py`
- `backend/routes/chat.py`
- `backend/routes/pipeline.py`
- `backend/storage.py`
- `backend/tests/test_chat.py`
- new retrieval/chunk/eval tests

Frontend:
- `frontend/src/pages/ChatPage.tsx`
- `frontend/src/components/EvidencePane.tsx`
- `frontend/src/components/EvidenceSheet.tsx`
- `frontend/src/components/ScopeChips.tsx`
- `frontend/src/components/ChartArtifact.tsx`
- `frontend/src/types.ts`

Data and tooling:
- `data/channels/{channel_id}/chunks.jsonl`
- optional `data/channels/{channel_id}/index.sqlite`
- `backend/evals/chat_quality_cases.json`
- `backend/evals/run_chat_eval.py`

## Migration Strategy

For existing channels:

1. Detect files with missing or old `schema_version`.
2. Show a "Rebuild for better citations" state in the UI.
3. Reuse existing transcripts when they already contain segments.
4. Rebuild chunks deterministically.
5. Rebuild summaries only when the summary schema changed or evidence is absent.
6. Rebuild profile after summaries.

Avoid automatic destructive deletion. The app should regenerate stale outputs
when the user reruns the pipeline.

## Definition Of Done

The system is done when:

- Specific chat questions retrieve raw caption chunks, not just profile summaries.
- The model receives a compact source pack instead of the entire profile for most
  questions.
- Every clickable citation comes from backend-provided source metadata.
- The frontend evidence pane opens the exact cited video timestamp and quote.
- Scope filters work for themes, tones, and dates.
- Old profiles are detected as legacy instead of silently mixed with new data.
- The eval harness shows better citation validity and source recall than the old
  full-profile chat.
- Full backend tests pass, and frontend build passes.

## Non-Goals

- Multi-user auth.
- Hosted vector database.
- Cross-channel comparison.
- Whisper re-transcription.
- Perfect semantic search in the first pass.
- Persisted chat history.

Those can be added later. The highest-value improvement now is source-grounded
retrieval over the captions already stored locally.
