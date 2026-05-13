# BRIEF: Trace

## Goal

Build a local tool that:

1. Takes a YouTube channel URL.
2. Lists every video on the channel.
3. Lets the user visually select which videos to include (thumbnails + checkboxes).
4. Fetches captions for the selected videos.
5. Summarizes each video into structured JSON via a cheap fast model.
6. Aggregates the summaries chronologically into a single channel "profile" digest.
7. Exposes a chat UI to ask questions against the aggregated digest using a stronger model.

This is a personal research tool, run locally. No auth, no multi-user, no deploy. Optimize for speed of iteration, not production hardening.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.11+ with FastAPI | Native fit for `yt-dlp`, `youtube-transcript-api`, Anthropic SDK. FastAPI gives async endpoints and SSE for streaming pipeline state. |
| Frontend | React + Vite + TypeScript + Tailwind CSS | Fast HMR, type safety on API contract, Tailwind for the iOS-style design system. |
| State streaming | Server-Sent Events (SSE) | Simpler than WebSockets, one-way is all we need (server → UI progress updates). |
| Storage | Flat JSON files on disk | "Start simple." No DB. Each pipeline step writes to a known path, idempotent. |
| Models | MiniMax API: `MiniMax-M2.7` (summarize), `MiniMax-M2.7-highspeed` (chat) | Same model family, identical output quality. Standard variant for batch jobs (cheaper), highspeed for interactive chat (lower latency). Use the Anthropic-compatible endpoint to keep SDK code minimal. |
| LLM SDK | `anthropic` Python SDK pointed at MiniMax's Anthropic-compatible endpoint | MiniMax exposes `https://api.minimax.io/anthropic` which speaks the Anthropic Messages API. Means the same client code works — just override `base_url` and use `MINIMAX_API_KEY` as the API key. |

**Project layout:**

```
channel-profiler/
├── backend/
│   ├── main.py                 # FastAPI app, route registration
│   ├── pipeline/
│   │   ├── fetch_videos.py     # yt-dlp channel listing
│   │   ├── fetch_transcripts.py# youtube-transcript-api per video
│   │   ├── summarize.py        # Haiku 4.5, per-video structured summary
│   │   ├── aggregate.py        # combine summaries chronologically
│   │   └── ask.py              # Sonnet 4.6 Q&A against profile
│   ├── routes/
│   │   ├── channel.py          # POST /api/channel
│   │   ├── videos.py           # GET /api/videos, POST /api/videos/select
│   │   ├── pipeline.py         # POST /api/pipeline/start, GET /api/pipeline/stream (SSE)
│   │   └── chat.py             # POST /api/chat
│   ├── models.py               # Pydantic schemas
│   └── storage.py              # data dir paths, read/write helpers
├── frontend/
│   ├── src/
│   │   ├── pages/              # one component per pipeline step
│   │   ├── components/         # PipelineStepper, VideoGrid, VideoCard, ChatBubble, etc.
│   │   ├── hooks/              # useSSE, usePipelineState
│   │   ├── api.ts              # typed fetch wrappers
│   │   └── App.tsx
│   └── tailwind.config.ts
├── data/                       # gitignored
│   ├── channels/{channel_id}/
│   │   ├── meta.json           # channel info
│   │   ├── videos.json         # full video list with thumbnails
│   │   ├── selection.json      # selected video IDs
│   │   ├── transcripts/{video_id}.json
│   │   ├── summaries/{video_id}.json
│   │   └── profile.json        # aggregated digest
└── README.md
```

---

## Pipeline stages (single source of truth)

The pipeline has six stages. The UI shows them as a horizontal stepper at the top of the app at all times. Each stage has a status: `pending | active | done | error`.

| # | Stage ID | Label | Backend module | UI screen |
|---|---|---|---|---|
| 1 | `channel_input` | Channel | — | Paste URL form |
| 2 | `video_list` | Videos | `fetch_videos.py` | Grid with thumbnails + checkboxes |
| 3 | `transcripts` | Transcripts | `fetch_transcripts.py` | Per-video progress list |
| 4 | `summaries` | Summaries | `summarize.py` | Per-video progress list |
| 5 | `profile` | Profile | `aggregate.py` | Profile preview (themes, timeline) |
| 6 | `chat` | Chat | `ask.py` | Chat interface |

The stepper component is the most important UI primitive — every screen renders below it.

---

## Stage 1 — Channel input

**UI:**
- Single screen. iOS-style centered card on a soft gray (`#F2F2F7`) background.
- Large heading: "Profile a channel"
- Single text input (rounded, `rounded-2xl`, system blue focus ring) with placeholder "Paste a YouTube channel URL"
- Single primary button "Continue" (iOS blue `#007AFF`, full-width, `rounded-2xl`, ~52px tall)
- Below: two example URLs as small gray text the user can click to autofill.

**Backend:** `POST /api/channel` with `{ url: string }`. Validates URL format, resolves channel ID via `yt-dlp --flat-playlist --print "%(channel_id)s"`. Returns `{ channel_id, channel_name, channel_handle, avatar_url }`. Persist to `data/channels/{channel_id}/meta.json`.

**Acceptance:**
- Valid `@handle`, `/c/`, `/channel/`, and full video URL all resolve to the same channel ID.
- Invalid URL → inline red error under the input, no toast.

---

## Stage 2 — Video list and selection

**Backend job:** `fetch_videos.py` runs yt-dlp:

```
yt-dlp --flat-playlist --dump-json {channel_url}
```

Parse each line as JSON. For each video extract: `id`, `title`, `upload_date`, `duration`, `view_count`, `thumbnail` (use `https://i.ytimg.com/vi/{id}/mqdefault.jpg` to ensure consistent sizing). Sort ascending by `upload_date` (oldest → newest). Write to `videos.json`.

**UI:**
- Pipeline stepper at top, stage 2 active.
- Header row: channel avatar + name on the left, "Select all / Select none / Last 50 / Last year" quick-action chips on the right.
- Body: grid of video cards.
  - Card: 16:9 thumbnail, rounded `rounded-xl`, subtle shadow, hover lifts (`hover:scale-[1.02] transition`).
  - Top-right corner: circular checkbox (iOS style — empty circle, fills with blue check when selected).
  - Below thumbnail: title (2 lines max, truncate), duration pill bottom-right of thumbnail, upload date in small gray text below title.
  - Selected state: 3px blue ring around card.
- Sticky bottom bar (iOS toolbar style, blur backdrop): "X of Y selected" on left, "Run pipeline" primary button on right (disabled if 0 selected).

**Important:** This is the pre-flight check the user explicitly asked for. They need to **see** which videos will feed the model before running. Default selection state = all videos selected. User narrows down.

**Backend:**
- `GET /api/videos?channel_id=...` returns the video list (paginated if >200, otherwise all).
- `POST /api/videos/select` with `{ channel_id, video_ids: [] }` writes `selection.json`.

**Acceptance:**
- Channels with 200+ videos render smoothly (virtualize the grid with `react-window` or similar if needed).
- Quick-action chips ("Last 50", "Last year") update selection state immediately, no server round-trip.
- Thumbnails lazy-load.

---

## Stage 3 — Transcript fetch

**Backend job:** `fetch_transcripts.py`. For each selected video ID:

```python
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
```

- Run a `ThreadPoolExecutor` with `max_workers=8`.
- Per video: try English transcript first, fall back to auto-generated. Catch `TranscriptsDisabled`, `NoTranscriptFound` → mark as `unavailable`, continue.
- Cleanup: join segment `text` fields with spaces, collapse whitespace, strip `[Music]` / `[Applause]` / `[Laughter]` / `[Inaudible]` bracket tags.
- Write `data/channels/{channel_id}/transcripts/{video_id}.json`:

```json
{
  "video_id": "...",
  "title": "...",
  "upload_date": "20240115",
  "duration_seconds": 612,
  "transcript_text": "...",
  "word_count": 1842,
  "source": "manual" | "auto" | "unavailable"
}
```

- Skip if file already exists (idempotent).

**UI:**
- Stepper shows stage 3 active.
- List of selected videos, one row each. Row has: thumbnail (small, 80px wide), title, status pill on the right.
- Status pill states: `Queued` (gray), `Fetching…` (blue, animated dots), `Done` (green check), `Unavailable` (yellow warning), `Failed` (red).
- Top: progress bar showing completed / total. Cancel button.
- Server pushes status updates via SSE: `data: {"video_id": "...", "status": "done"}\n\n`.

**Acceptance:**
- Videos with no captions don't break the run — they're flagged and skipped.
- Closing the browser tab does not stop the backend job.
- Reopening the app resumes the UI from current state (read from disk).

---

## Stage 4 — Per-video summarization

**Backend job:** `summarize.py`. For each transcript:

- Skip if `summaries/{video_id}.json` exists.
- Use the Anthropic SDK pointed at MiniMax's Anthropic-compatible endpoint:

```python
from anthropic import Anthropic

client = Anthropic(
    api_key=os.environ["MINIMAX_API_KEY"],
    base_url="https://api.minimax.io/anthropic",
)

response = client.messages.create(
    model="MiniMax-M2.7",          # standard variant — batch jobs don't need highspeed
    max_tokens=2000,
    system=SUMMARIZE_SYSTEM_PROMPT,
    messages=[{"role": "user", "content": user_message}],
    # IMPORTANT: do not enable extended thinking on this endpoint.
    # MiniMax emits reasoning_content as OpenAI-style deltas which can leak
    # into the visible response on the Anthropic-compatible streaming path.
)
```

- Concurrency: 5 requests in flight, gather with `asyncio.gather`.

**Prompt template** (system):

```
You analyze YouTube video transcripts and extract a structured profile of the
content. Return ONLY valid JSON matching the schema. No prose, no markdown
fences, no commentary.

Schema:
{
  "core_topic": "one-sentence summary of what this video is about",
  "key_claims": ["specific assertions the speaker makes, 3-7 items"],
  "recurring_themes": ["broader themes touched on, 2-5 items"],
  "tone_markers": ["adjectives describing how the speaker communicates, 2-4 items"],
  "notable_opinions": ["distinctive opinions or hot takes, 0-5 items"],
  "people_or_things_referenced": ["proper nouns mentioned with significance, 0-10 items"]
}
```

**User message:**

```
Title: {title}
Date: {upload_date}
Transcript:
{transcript_text}
```

- Parse response, validate against Pydantic model. On parse failure, retry once with a stricter "JSON only" reminder.
- Save to `summaries/{video_id}.json` with the schema above plus `video_id`, `title`, `upload_date`.

**UI:** identical row-list layout to stage 3, with the same status pills. Reuse the component.

**Acceptance:**
- Failed summaries (after retry) are flagged but don't block the rest.
- Cost estimate shown at top: "~$X.XX based on Y videos." Compute from average transcript length × MiniMax-M2.7 pricing ($0.30 / 1M input, $1.20 / 1M output).

---

## Stage 5 — Aggregation

**Backend job:** `aggregate.py`. Pure function, no API calls:

- Load all `summaries/*.json`.
- Sort by `upload_date` ascending.
- Build `profile.json`:

```json
{
  "channel_id": "...",
  "channel_name": "...",
  "video_count": 87,
  "date_range": { "first": "20210304", "last": "20251102" },
  "videos": [ /* full summary objects in date order */ ],
  "rollups": {
    "all_themes": ["theme1", "theme2", ...],          // deduped, sorted by frequency
    "all_referenced": ["name1", ...],                  // top 50 by frequency
    "tone_distribution": { "analytical": 23, "..." }   // counts
  }
}
```

The `rollups` section is computed from the per-video summaries — straight Python aggregation, no model call.

**UI — Profile preview:**

This is the most visually rich screen. iOS-style sectioned list (rounded white cards on gray background, grouped sections):

- **Header card:** channel avatar (large, circular), channel name, video count, date range. Background: subtle gradient.
- **Themes card:** "Recurring themes" section header, then a wrapped row of pill-shaped tags. Larger pills for higher-frequency themes. Tap a pill to filter.
- **Tone card:** small horizontal bar chart showing tone distribution. iOS-style — thin bars, system colors, no gridlines.
- **Timeline card:** vertical list of videos in date order. Each row: date on left, title in middle, theme pills on right. Tap to expand and see the full per-video summary inline.
- **People & things card:** wrapped pills of top-referenced names/concepts.
- **Footer:** primary button "Start chatting →" advances to stage 6.

**Acceptance:**
- All data is read from `profile.json` only — no live model calls on this screen.
- Loads instantly even for 200+ video profiles.

---

## Stage 6 — Chat

**Backend:** `POST /api/chat` with `{ channel_id, messages: [{role, content}] }`.

- System prompt: load `profile.json`, serialize compactly (drop the per-video transcripts; keep summaries). Inject as system message.
- Append user messages.
- Call `MiniMax-M2.7-highspeed` via the same Anthropic-compatible endpoint:

```python
stream = client.messages.stream(
    model="MiniMax-M2.7-highspeed",   # interactive — pay for lower latency
    max_tokens=4000,
    system=CHAT_SYSTEM_PROMPT,
    messages=conversation_history,
)
```

- Stream response back via SSE. Forward only `text_delta` events to the client; ignore any `reasoning_content` fields if they appear.
- Context budget: M2.7 has a 205k token window, max output 131k. The serialized profile for a 200-video channel is comfortably under 50k, so no truncation needed in v1.

**System prompt template:**

```
You are analyzing a YouTube channel based on structured summaries of its videos.
The summaries are listed chronologically (oldest first), so you can identify
how the creator's thinking, topics, and tone have evolved.

When asked questions:
- Cite specific videos by title and date when relevant.
- Distinguish between recurring patterns and one-off claims.
- Be direct. No hedging filler.
- If asked about something not covered in the summaries, say so explicitly.

CHANNEL: {channel_name}
VIDEOS: {video_count} (from {first_date} to {last_date})

SUMMARIES (chronological):
{serialized_summaries}
```

**UI:**
- iMessage-style chat. User bubbles right-aligned, blue background (`#007AFF`), white text. Assistant bubbles left-aligned, light gray background (`#E9E9EB`), black text. Both `rounded-3xl` with proper iOS tail corners (`rounded-br-md` on user, `rounded-bl-md` on assistant).
- Input bar pinned to bottom. Rounded text input with paper-plane send button.
- Suggested prompts shown as horizontally scrollable chips above the input on first load:
  - "What are this channel's main themes?"
  - "How has the creator's thinking evolved over time?"
  - "What does this person seem to believe most strongly?"
  - "What topics keep coming up?"
  - "Who or what does this channel reference most?"
- Streaming: tokens appear character-by-character in the latest assistant bubble.
- Top-right header: small channel avatar + name, tap to return to profile preview.

**Acceptance:**
- First token latency < 2s.
- Conversation history is kept in browser state only — no persistence needed in v1 (can add later).

---

## iOS-style design system

Tailwind config additions and rules every screen follows:

**Colors:**
- Background: `#F2F2F7` (iOS system gray 6)
- Card surface: `#FFFFFF` (light) / `#1C1C1E` (dark)
- Primary blue: `#007AFF`
- Success green: `#34C759`
- Warning yellow: `#FF9500`
- Error red: `#FF3B30`
- Text primary: `#000000` / `#FFFFFF`
- Text secondary: `#8E8E93`
- Separator: `#C6C6C8` at 30% opacity

**Typography:**
- Font stack: `-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", system-ui, sans-serif`
- Title (large): 34px / 700 weight
- Title 2: 28px / 700
- Headline: 17px / 600
- Body: 17px / 400
- Footnote: 13px / 400
- Caption: 12px / 400

**Shape:**
- Cards: `rounded-2xl` (16px)
- Buttons: `rounded-2xl` (16px), 52px tall for primary
- Pills/chips: `rounded-full`
- Inputs: `rounded-2xl`, 52px tall

**Shadow:**
- Cards: `shadow-[0_1px_2px_rgba(0,0,0,0.04),_0_4px_12px_rgba(0,0,0,0.04)]` — very subtle. iOS doesn't do heavy drop shadows.

**Motion:**
- All transitions `duration-200 ease-out`.
- Card hover: `scale-[1.02]`.
- Button press: `active:scale-95`.
- Stepper transitions between stages: slide-fade.

**Dark mode:** Yes, support via `prefers-color-scheme`. Use Tailwind `dark:` variants throughout.

**Layout:**
- Max content width: 1024px, centered. Gutters: 16px on mobile, 32px on desktop.
- Generous vertical whitespace between sections (Apple's "breathing room").

---

## Pipeline stepper component (most reused primitive)

Horizontal pill bar across the top of the viewport (sticky), shows all 6 stages.

- Each stage: small circle (24px) with stage number, label below.
- Connecting lines between circles.
- States visualized:
  - `pending`: gray circle, gray text.
  - `active`: blue filled circle with white number, animated pulse ring, blue label.
  - `done`: green filled circle with white check, gray label.
  - `error`: red filled circle with white `!`, red label.
- Clickable: clicking a `done` stage navigates back to its screen. Clicking `pending` stages does nothing.
- On mobile: horizontally scrollable.

---

## API contract summary

```
POST   /api/channel                 → resolve channel from URL
GET    /api/videos?channel_id=...   → list videos
POST   /api/videos/select           → save selection
POST   /api/pipeline/start          → kicks off transcripts → summaries → aggregate
GET    /api/pipeline/stream?channel_id=... (SSE) → live status updates
GET    /api/profile?channel_id=...  → return profile.json
POST   /api/chat                    → streaming chat (SSE)
```

All endpoints return `{ ok: bool, data?: ..., error?: string }`.

---

## Implementation order

Build in this order, end-to-end testing after each phase:

1. **Phase 0 — Skeleton.** Repo init, FastAPI hello world, Vite React app, Tailwind configured, both running locally with proxy.
2. **Phase 1 — Stage 1 + Stage 2.** Channel resolve, video list, video grid UI with selection. No pipeline yet, just verify thumbnails render and selection persists.
3. **Phase 2 — Stage 3.** Transcript fetch + SSE progress UI. End-to-end, real channel, ~10 videos.
4. **Phase 3 — Stage 4.** Summarization. Wire up the Anthropic SDK pointed at MiniMax's Anthropic-compatible endpoint. Real `MiniMax-M2.7` calls. Verify JSON output.
5. **Phase 4 — Stage 5.** Aggregate + profile preview screen. Static data, no model.
6. **Phase 5 — Stage 6.** Chat. `MiniMax-M2.7-highspeed`, streaming.
7. **Phase 6 — Polish.** Pipeline stepper animations, error states, dark mode, mobile layout, loading skeletons.

Do not skip ahead. Each phase should be a clean working slice before moving on.

---

## Open decisions / configuration

- `MINIMAX_API_KEY` from `.env` file. Don't commit. Get it from the MiniMax console at `platform.minimax.io`.
- `MINIMAX_BASE_URL=https://api.minimax.io/anthropic` — the Anthropic-compatible endpoint. Lets us reuse the official `anthropic` Python SDK with no other code changes.
- Concurrency limits exposed as env vars: `TRANSCRIPT_WORKERS=8`, `SUMMARY_WORKERS=5`.
- Hard cap on selectable videos in v1: 300. Show a warning if user selects more.
- All cost-incurring stages (transcripts are free, summaries and chat cost money) show an estimated cost before running. Use these rates:
  - `MiniMax-M2.7`: $0.30 per 1M input / $1.20 per 1M output
  - `MiniMax-M2.7-highspeed`: $0.60 per 1M input / $2.40 per 1M output
- Do not enable extended thinking / reasoning on the MiniMax Anthropic-compatible endpoint. MiniMax emits reasoning content as OpenAI-style delta chunks rather than native Anthropic thinking blocks, which can leak internal reasoning into the visible response stream.

---

## Out of scope for v1

- Vector DB / RAG over raw transcripts. Profile-level Q&A only. (Decided in spec phase.)
- Whisper re-transcription. Captions only. (Decided in spec phase.)
- User accounts, sharing, deploy, multi-channel comparison.
- Conversation persistence across sessions.
- Editing summaries by hand before aggregation.

These are reasonable v2 additions, not v1.

---

## Definition of done

A user can:
1. Paste a channel URL.
2. See every video on that channel as a thumbnail grid.
3. Uncheck videos they don't want included.
4. Click "Run pipeline," watch live progress through transcripts and summaries.
5. View an aggregated profile screen with themes, tone, timeline, references.
6. Open a chat and ask "what is this channel about" / "how has the creator evolved" and get streaming, grounded answers.

The whole flow runs locally, looks like a polished iOS app, and survives a browser refresh at any stage.
