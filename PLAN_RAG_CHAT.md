# PLAN — Chat Retrieval Fix (Hybrid Summary + Smart RAG)

## Problem

Current chat retrieval is pure lexical keyword match over 1948 chunks, returning top 12 by token overlap (`backend/pipeline/retrieve.py:_score_chunk`). Two failure modes observed on the MrBeast 50-video channel:

1. **Structural questions fail.** Asking "what's in the first 10 seconds of every video" matches chunks where words like *opening*, *wilderness*, *money* appear mid-video. Only one opening chunk (S7) was returned out of 12. LLM correctly reported "not enough evidence" — retrieval threw away 42 perfectly indexed opening chunks (all videos have `chunk_0000` at `start_seconds < 1`).
2. **Cross-video synthesis fails.** Questions phrased as *across every video* / *all 50* are still constrained to 12 chunks total. LLM cannot synthesize patterns it cannot see.

Pipeline state confirmed clean:
- `fetch_videos` ✓
- `fetch_transcripts` ✓ — all transcripts start at t=0.0–0.3
- `chunk_transcripts` ✓ — 1948 chunks, every video has `chunk_0000`
- `summarize` ✓ — 43 summary files, 223 KB total
- `aggregate` ✓ — profile + rollups present
- `retrieve` / `chat_context` ✗ — bug lives here

## Token Budget

| Source | Size (50 MrBeast vids) |
|---|---|
| Full chunk text | ~342k words ≈ **455k tokens** (over budget) |
| Per-video summaries | ~50k words ≈ **55k tokens** |
| Aggregate (profile + rollups) | ~5-10k tokens |
| Recent chat history (current cap) | ~5k tokens |
| Reserve for response | 4k tokens |

**MiniMax-M2.7-highspeed context window**: 204,800 input tokens / 131,072 output tokens (confirmed 2026-05-16).

**Budget plan**: system prompt ≤ 120k tokens. Summaries baseline (~55k) + retrieved chunks (~40-60k) + scaffolding + history (~10k) + response reserve (~10k) = ~115k. Fits with ~85k headroom for growth.

## Architectural Contract

**Selected: Contract C — Hybrid Summary + Smart RAG.**

- LLM always receives per-video summary digests (channel-wide global view, cheap).
- Retrieval pulls full caption chunks on top of that for detail and direct quotes.
- Intent-aware retrieval: structural queries (openings, endings) bypass lexical scoring and return chunk-position-based selections.
- Dynamic chunk limit: queries flagged as global (`across all`, `every video`, `compare`) raise the limit.

Rejected:
- **Contract A** (stuff full captions): 455k tokens > model context. Dies at 50 videos.
- **Contract B** (pure smarter retrieval): leaves summaries pipeline unused; LLM still has no global view.

## Implementation Phases

### Phase 1 — Wire summaries into system prompt
**Touches:** `backend/pipeline/chat_context.py`, `backend/storage.py` (read summary digests).

Tasks:
- R1.1 — Add `load_summary_digests(channel_id)` to storage layer. Reads per-video summary files, returns compact list `[{video_id, title, upload_date, summary_text, key_claims, themes}]`. One source of truth for which fields make it in.
- R1.2 — Add `SUMMARY_DIGEST_MAX_CHARS` per-video cap (e.g. 800 chars). Tune so 50 vids ≈ 40-55k tokens.
- R1.3 — Extend `CHAT_SYSTEM_PROMPT_TEMPLATE` with `VIDEO_DIGESTS:` section between `PROFILE_HINTS` and `LATEST_USER_QUERY`.
- R1.4 — Update system prompt rules: "Use VIDEO_DIGESTS for cross-video patterns and synthesis. Use SOURCE_PACK for direct quotes and specific factual claims."
- R1.5 — Telemetry: log digest token estimate and source pack token estimate per chat turn.

Exit criteria: chat turn on MrBeast channel includes all 43 video digests in system prompt; total prompt < 100k tokens.

### Phase 2 — Query intent detection
**Touches:** `backend/pipeline/retrieve.py` (new module-level helper).

Tasks:
- R2.1 — Add `classify_query(query: str) -> QueryIntent` dataclass with fields: `mode: Literal["lexical", "opening", "closing", "lexical_global"]`, `seconds_window: int | None`.
- R2.2 — Pattern rules (lowercased substring match, document the full list in source):
  - `mode="opening"`: `hook`, `open`, `intro`, `start of`, `first N seconds`, `how do videos start`, `how does .* begin`
  - `mode="closing"`: `outro`, `closing`, `end of`, `last N seconds`, `how do videos end`
  - `lexical_global` flag: `every video`, `across all`, `each video`, `all 50`, `every episode`
- R2.3 — Extract numeric window when present: "first 30 seconds" → `seconds_window=30`. Default opening window = 30s, closing = 60s.
- R2.4 — Unit tests covering at least 10 query phrasings per mode.

Exit criteria: `classify_query("what's the hook in every video")` returns `QueryIntent(mode="opening", seconds_window=10)`.

### Phase 3 — Structural retrieval branches
**Touches:** `backend/pipeline/retrieve.py:retrieve_context`.

Tasks:
- R3.1 — Add `_retrieve_openings(index, scope, seconds_window, per_video_limit=1) -> list[dict]`. For each video in `selected_video_ids`, pick chunks with `start_seconds <= seconds_window`, prefer lowest start, cap one per video.
- R3.2 — Add `_retrieve_closings(index, scope, seconds_window, per_video_limit=1)`. Symmetric: for each video, last chunk whose `end_seconds >= (video_end - seconds_window)`. Requires knowing video duration; if missing, fall back to highest-`start_seconds` chunk per video.
- R3.3 — Wire `retrieve_context` to dispatch on `QueryIntent`:
  - `mode="opening"` → `_retrieve_openings` (limit = number of selected videos, capped at 100)
  - `mode="closing"` → `_retrieve_closings`
  - `mode="lexical_global"` → existing lexical path but limit = min(2 × video_count, 60)
  - `mode="lexical"` (default) → existing path unchanged
- R3.4 — Preserve scope filtering (`_matches_scope`) in all branches.
- R3.5 — Set `score=1.0` for structural picks; sort by `(upload_date, video_id, start_seconds)` so output is deterministic per video.

Exit criteria: `retrieve_context(mrbeast_id, "hooks in first 10s of every video", limit=12)` returns 43 chunks all with `start_seconds <= 10`.

### Phase 4 — Coverage metadata for LLM
**Touches:** `backend/pipeline/chat_context.py:format_source_pack`.

Tasks:
- R4.1 — Add coverage header to source pack: `coverage: N chunks from M of K selected videos (mode=opening, window=10s)`.
- R4.2 — Update system prompt rules: "Trust coverage header; do not claim missing data when coverage matches the question scope."
- R4.3 — When mode is structural and a selected video lacks a qualifying chunk, append `missing_openings: [video_id_1, ...]` so LLM can acknowledge gap honestly.

Exit criteria: LLM no longer says "only S7 starts at t=0" when 43 opening chunks are present.

### Phase 5 — Tests
**Touches:** `backend/tests/test_retrieve.py`, `backend/tests/test_chat_context.py`.

Tasks:
- R5.1 — Fixture: small synthetic chunk index with 5 videos, 3 chunks each.
- R5.2 — Test `mode="opening"` returns first chunk per video and respects `seconds_window`.
- R5.3 — Test `mode="closing"` returns last chunk per video.
- R5.4 — Test `mode="lexical_global"` bumps limit.
- R5.5 — Test scope filtering (date_from/date_to) applies to structural modes.
- R5.6 — Test `build_chat_context` includes summary digests under token budget.
- R5.7 — End-to-end (mock LLM): given MrBeast fixture + opening question, assert source pack contains chunks from all videos.

Exit criteria: `pytest backend/tests/test_retrieve.py backend/tests/test_chat_context.py` green.

### Phase 6 — Manual demo verification
**Touches:** none (verification only).

Tasks:
- R6.1 — Run MrBeast channel chat: "What hook patterns appear in the first 10 seconds of every video?" Verify answer references >20 distinct video openings.
- R6.2 — Run: "How much money does MrBeast give away across all 50 videos?" Verify lexical_global path retrieves >40 chunks.
- R6.3 — Run: "How do MrBeast videos typically end?" Verify closing branch fires.
- R6.4 — Sanity check existing narrow questions still work ("what did MrBeast say about Feastables").

Exit criteria: all four demo prompts return answers grounded in correct chunks.

## Schema Notes

- Chunk index schema unchanged. No migration needed. `start_seconds` already present on every chunk.
- Summary digest format derived from existing per-video summary files; no new persisted schema.
- System prompt template updated → consider bumping `CHAT_SYSTEM_PROMPT_VERSION` constant if telemetry tracks prompt versions (currently does not — skip).

## Out of Scope (Deferred)

- **Embeddings / semantic retrieval.** Lexical + structural covers ~90% of expected queries. Add embeddings only when telemetry shows users hitting semantic gaps. Owner: future ticket.
- **Tool-calling / function-calling pattern.** LLM dynamically requesting chunks would be cleaner but adds latency + complexity. Defer until proven necessary.
- **Per-channel retrieval tuning.** Treat all channels the same for now.
- **Frontend changes.** No UI work. Retriever API signature unchanged.

## Risks

| Risk | Mitigation |
|---|---|
| Summaries blow token budget on big channels (>100 vids) | Cap per-video digest length + truncate to top-K videos by relevance when over budget |
| Intent classifier false positives (e.g. "I want to start using Feastables" triggers opening mode) | Require structural keyword to dominate (e.g. "first 10 seconds" pattern, not just "start") |
| MiniMax context exceeded on huge channels (200+ vids) | Cap per-video digest length; truncate to top-K videos when over budget |
| Mixing retrieval changes with active proxy work on `proxy/p7-5-*` branch | Work on separate branch off `main`; PR independently |

## Decision Log

- **2026-05-16**: Selected Contract C (hybrid) over A (impossible — 455k tokens) and B (wastes summaries pipeline).
- **2026-05-16**: Defer embeddings until lexical + structural coverage is proven insufficient via real user queries.
- **2026-05-16**: MiniMax-M2.7-highspeed context confirmed at 204,800 input / 131,072 output tokens. Phase 1 unblocked. No digest truncation needed at current channel sizes (≤100 videos).

## Status

| ID | Task | Status | Branch | Started | PR |
|---|---|---|---|---|---|
| R1.1 | `load_summary_digests` in storage | in_progress | chat/rag-hybrid-summary | 2026-05-16 | — |
| R1.2 | Per-video digest cap | in_progress | chat/rag-hybrid-summary | 2026-05-16 | — |
| R1.3 | `VIDEO_DIGESTS` section in prompt | in_progress | chat/rag-hybrid-summary | 2026-05-16 | — |
| R1.4 | Updated system prompt rules | in_progress | chat/rag-hybrid-summary | 2026-05-16 | — |
| R1.5 | Token estimate telemetry | in_progress | chat/rag-hybrid-summary | 2026-05-16 | — |
| R2.1 | `classify_query` + `QueryIntent` | in_progress | chat/rag-hybrid-summary | 2026-05-16 | — |
| R2.2 | Intent pattern rules | in_progress | chat/rag-hybrid-summary | 2026-05-16 | — |
| R2.3 | Numeric window extraction | in_progress | chat/rag-hybrid-summary | 2026-05-16 | — |
| R2.4 | Intent unit tests | in_progress | chat/rag-hybrid-summary | 2026-05-16 | — |
| R3.1 | `_retrieve_openings` | todo | — | — | — |
| R3.2 | `_retrieve_closings` | todo | — | — | — |
| R3.3 | Dispatcher in `retrieve_context` | todo | — | — | — |
| R3.4 | Scope filtering preserved | todo | — | — | — |
| R3.5 | Deterministic structural ordering | todo | — | — | — |
| R4.1 | Coverage header in source pack | todo | — | — | — |
| R4.2 | Prompt rule for coverage trust | todo | — | — | — |
| R4.3 | `missing_openings` gap surfacing | todo | — | — | — |
| R5.1 | Synthetic chunk index fixture | in_progress | chat/rag-hybrid-summary | 2026-05-16 | — |
| R5.2 | Opening mode test | todo | — | — | — |
| R5.3 | Closing mode test | todo | — | — | — |
| R5.4 | Global limit bump test | todo | — | — | — |
| R5.5 | Scope filtering test | todo | — | — | — |
| R5.6 | Digest budget test | todo | — | — | — |
| R5.7 | End-to-end mock LLM test | todo | — | — | — |
| R6.1 | Demo: openings question | todo | — | — | — |
| R6.2 | Demo: global money question | todo | — | — | — |
| R6.3 | Demo: closings question | todo | — | — | — |
| R6.4 | Demo: existing narrow question regression | todo | — | — | — |

## Blocker Log

(none yet)
