# Chat Revamp: Evidence Pane + Structured Artifacts + Scoping

**Audience:** another AI agent implementing this. You are a junior dev. Read the whole doc before touching code.

**Branch:** `feat/chat-revamp` off the current `feat/ux-revamp`.

**Why we are doing this:** the chat is the headline feature of the app, but today it is a plain iMessage clone with markdown. The profile is loaded with structured data (claims with evidence timestamps, themes, tone, references, chronology) and the chat collapses all of it into a wall of prose with citation pills that open a new browser tab. Three concrete problems:

1. **No grounding surface.** Citations exist (`[↗ M:SS]` markdown links — see `backend/pipeline/ask.py:11-49` for the prompt rules) but clicking one tears the user out of the app. The whole point of citations is staying inside the conversation while you verify.
2. **Prose-only answers.** Questions like *"how did the creator's stance on X evolve"* or *"compare 2022 vs 2024"* want a chart, a timeline, or a table. The model writes paragraphs because the channel has no other render path.
3. **No scoping.** Every turn ships the full profile (~50k tokens for a 110-video channel). User has no way to say "only consider videos tagged `productivity` since 2024" — the model has to filter implicitly each turn, which dilutes answers and burns context.

This plan ships in three phases. Each phase is a clean working slice. Do not skip ahead.

---

## Tech choices (decided, do not relitigate)

- **YouTube embed:** plain `<iframe>` to `https://www.youtube.com/embed/{id}?start={s}&autoplay=1`. No `youtube-iframe-api`. Reload the iframe on each citation click — cheap, deterministic.
- **Charts:** reuse `recharts` (already installed for the profile page). No new chart libs.
- **Structured artifact format:** model emits a fenced code block with language tag `chart`, body is JSON. Frontend intercepts these blocks via the existing `react-markdown` `code` component override. No new SSE event type, no tool-use API. Keeps the backend stream untouched.
- **Scoping:** filter chips on the chat input. Selected chips reduce the system prompt server-side (filter `profile.videos` before serialization). Pure server logic — no new endpoint.
- **No persistence yet.** Out of scope for this PR. Conversation stays in browser state.
- **No comparison mode.** Out of scope. Single-channel only.

---

## Part A — Evidence pane (split workspace)

### A.1 Target layout

`ChatPage.tsx` becomes a 2-column flex layout on desktop. Left = chat (existing). Right = evidence pane (new). On mobile (<lg breakpoint), evidence pane collapses into a slide-up bottom sheet.

```
┌─────────────────────────┬──────────────────────────────┐
│ Header (back + channel) │  (header continues full width)│
├─────────────────────────┼──────────────────────────────┤
│ messages...             │  [tab: Sources | Videos]     │
│ user bubble             │                              │
│ assistant bubble with   │  ┌── currently focused ────┐ │
│   citation pills [↗2:22]│  │ <iframe youtube embed>  │ │
│                         │  │ jumps to t=142          │ │
│                         │  └─────────────────────────┘ │
│                         │  Quote (verbatim from        │
│                         │  evidence): "..."            │
│                         │  ─────                       │
│                         │  Other citations from this   │
│                         │  reply (chips)               │
│                         │  ─────                       │
│                         │  Cited videos in this        │
│                         │  conversation (list)         │
│ ─── sticky input ───    │                              │
└─────────────────────────┴──────────────────────────────┘
```

Default split: `lg:grid-cols-[1fr_440px]`. The pane is fixed-width on desktop, full-width drawer on mobile.

### A.2 Citation marker — store more than the link

Today citations render as styled `<a>` (see `ChatPage.tsx:11-37`). We need to (a) intercept clicks and (b) resolve `video_id` → title/quote without re-parsing later.

**Step 1.** Extend the `markdownComponents.a` override. When the href matches the citation pattern (`isYouTubeCitationHref`), parse `video_id` and `start_seconds` out of the URL. Render a `<button>` instead of `<a>` so the click stays in-app.

```ts
// helpers (top of file)
function parseCitationHref(href: string): { videoId: string; startSeconds: number } | null {
  const m = href.match(/(?:youtu\.be\/|v=)([\w-]{11}).*[?&]t=(\d+)s?/)
  if (!m) return null
  return { videoId: m[1], startSeconds: Number(m[2]) }
}
```

The new `<button>` carries the same visible text (the timestamp pill) and calls `onCitationClick(videoId, startSeconds, messageIdx)` from a context provider (see A.4). Right-click / Cmd-click still need to open YouTube in a new tab — render as `<a>` with `onClick={(e) => { e.preventDefault(); ... }}` so middle-click and Cmd-click fall through to the browser's default open-in-tab.

**Step 2.** Build a per-conversation citation index. Memoize over `messages`:

```ts
interface CitedRef { videoId: string; startSeconds: number; messageIdx: number; profileVideo?: ProfileVideo; evidenceQuote?: string }
const citedRefs = useMemo(() => extractCitations(messages, profile), [messages, profile])
```

`extractCitations` scans assistant messages for the citation regex, looks up `profile.videos[*].title` by `video_id`, and tries to find the matching `evidence` entry by `start_seconds` (look in both `key_claims[*].evidence[]` and `notable_opinions[*].evidence[]`). If found, attach the verbatim `quote`. The citation pill in chat is small; the evidence pane is where we render the full quote.

### A.3 New components

Create `frontend/src/components/EvidencePane.tsx`:

```tsx
interface Props {
  focusedRef: CitedRef | null         // currently selected citation
  conversationRefs: CitedRef[]        // all citations across all assistant replies
  onSelectRef: (ref: CitedRef) => void
  channelName: string
}
```

Layout (top → bottom):
1. **Tab bar:** "Sources" (default) / "Videos cited" — second tab is a deduped list of all videos referenced.
2. **Player card** (Sources tab): aspect-video iframe. Use `key={`${videoId}-${startSeconds}`}` so React re-mounts the iframe on each click — that's how we force YouTube to seek. URL: `https://www.youtube.com/embed/{videoId}?start={startSeconds}&autoplay=1&rel=0`.
3. **Quote block:** italic, `border-l-2 border-ios-blue/40`, the `evidenceQuote` if available. Otherwise show "No quote captured for this timestamp."
4. **Citation strip:** every `CitedRef` from the same `messageIdx` as `focusedRef`, rendered as horizontally scrollable chips `[↗ 2:22 — Video title]`. Click switches `focusedRef`.
5. **Divider.**
6. **Videos cited list:** dedupe `conversationRefs` by `videoId`. Each row: thumbnail (`https://i.ytimg.com/vi/{videoId}/mqdefault.jpg`), title, count of citations across the conversation. Click jumps to first citation for that video.

Empty state (no citations yet): centered icon + "Citations will appear here as the assistant answers."

Create `frontend/src/components/EvidenceSheet.tsx` for mobile — a bottom sheet that wraps the same content. Open via a floating "View sources" pill on the chat that appears once `conversationRefs.length > 0`. Close on backdrop click or swipe-down. Don't add a swipe-gesture lib; a click-outside handler is enough.

### A.4 Wiring

`ChatPage.tsx` owns the focused-ref state:

```ts
const [focusedRef, setFocusedRef] = useState<CitedRef | null>(null)
const [sheetOpen, setSheetOpen] = useState(false)        // mobile only

const handleCitationClick = useCallback((videoId, startSeconds, messageIdx) => {
  const ref = citedRefs.find(r => r.videoId === videoId && r.startSeconds === startSeconds && r.messageIdx === messageIdx) ?? null
  setFocusedRef(ref)
  setSheetOpen(true)   // no-op visually on desktop (sheet hidden via lg:hidden)
}, [citedRefs])
```

Pass `handleCitationClick` to the markdown components via a React context (`CitationContext`) — `markdownComponents` is defined at module scope today and we don't want to rebuild it per-render.

**Auto-focus:** when streaming completes, if no citation has been clicked yet and the latest reply contains citations, set `focusedRef` to the first citation in that reply automatically. Once the user clicks any citation, stop auto-focusing for the rest of the session.

### A.5 Acceptance

- [ ] Click a `[↗ 2:22]` pill → right pane player loads at t=142, autoplays. Video does not open in a new tab.
- [ ] Cmd-click / middle-click → opens YouTube in a new tab (default browser behavior preserved).
- [ ] Citation marker for a video that exists in `profile.videos` shows the verbatim quote in the pane.
- [ ] Citation marker for a video NOT in profile (model hallucinated an ID) renders pill normally but pane shows "Video not in profile" and no iframe.
- [ ] Mobile (<1024px wide): pane is hidden, "View sources (N)" pill appears bottom-right of chat once at least one citation exists. Click → bottom sheet with the same content. Close → returns to chat.
- [ ] Streaming a long answer with multiple citations does not cause iframe re-renders until the user actually clicks one.
- [ ] After the assistant finishes a reply that has citations, the first citation auto-loads in the pane on desktop only (not on mobile — don't pop the sheet automatically).
- [ ] Existing `onComplete` and `retryLast` flows still work.

---

## Part B — Structured artifacts (chart blocks)

### B.1 The format

Model emits an artifact as a fenced code block with language `chart`. Body is JSON. Frontend `markdownComponents.code` already exists (`ChatPage.tsx:66-86`) — we extend it.

Three artifact types in v1:

```json
// type 1: evolution — slope over time for a single theme/topic
{
  "type": "evolution",
  "title": "Stance on AI tools",
  "theme": "ai",
  "points": [
    { "video_id": "abc", "upload_date": "20220314", "score": -0.6, "label": "skeptical" },
    { "video_id": "def", "upload_date": "20240901", "score":  0.7, "label": "pragmatic adopter" }
  ]
}

// type 2: comparison_table — generic structured rows
{
  "type": "comparison_table",
  "title": "2022 vs 2024",
  "columns": ["Topic", "Early stance", "Recent stance"],
  "rows": [
    ["AI tools", "Skeptical", "Pragmatic"],
    ["Productivity", "Time-blocking", "Energy management"]
  ]
}

// type 3: claim_cluster — grouped claims
{
  "type": "claim_cluster",
  "title": "Recurring claims about discipline",
  "groups": [
    { "label": "Discipline > motivation", "claims": [
      { "text": "...", "video_id": "abc", "start_seconds": 412 }
    ]}
  ]
}
```

### B.2 Prompt changes

Edit `backend/pipeline/ask.py:CHAT_SYSTEM_PROMPT_TEMPLATE`. After the `FORMATTING:` section, insert:

```
ARTIFACTS — when to emit a chart instead of prose:
- If the question asks about evolution over time of a topic, theme, or stance → emit an `evolution` artifact.
- If the question asks for a side-by-side comparison of two periods/topics → emit a `comparison_table`.
- If the question asks for "top claims", "all claims about X", or to enumerate beliefs → emit a `claim_cluster`.
- Format: a fenced block with language `chart`, body is JSON matching one of the schemas below. Place the artifact after a 1-2 sentence intro paragraph. Do not repeat the artifact's content as prose.
- Schemas:
  evolution:        { type:"evolution", title:string, theme:string, points:[{video_id, upload_date, score(-1..1), label}] }
  comparison_table: { type:"comparison_table", title:string, columns:[string], rows:[[string]] }
  claim_cluster:    { type:"claim_cluster", title:string, groups:[{label:string, claims:[{text, video_id, start_seconds}]}] }
- Score in evolution is a stance scalar from -1 (strongly against) to +1 (strongly for). Use 0 for neutral/mixed.
- Only emit an artifact when the question naturally calls for one. For straightforward Q&A, plain prose with citations is correct.
```

Update the few-shot suggested prompts on the frontend (`ChatPage.tsx:111-117`) to include one that triggers an artifact, e.g. `"How has the creator's stance on AI evolved?"`.

### B.3 Frontend rendering

Create `frontend/src/components/ChartArtifact.tsx`:

```tsx
type ChartSpec =
  | { type: 'evolution'; title: string; theme: string; points: { video_id: string; upload_date: string; score: number; label?: string }[] }
  | { type: 'comparison_table'; title: string; columns: string[]; rows: string[][] }
  | { type: 'claim_cluster'; title: string; groups: { label: string; claims: { text: string; video_id: string; start_seconds: number }[] }[] }

interface Props {
  spec: ChartSpec
  profile: Profile
  onCitationClick: (videoId: string, startSeconds: number) => void
}
```

Renderers:

- **evolution** → recharts `<LineChart>` with x = `upload_date` (parse `YYYYMMDD`), y = `score`. Markers = dots; click a dot → `onCitationClick(videoId, 0)`. Below chart: small list of the points with their labels and dates.
- **comparison_table** → plain `<table>` styled like the existing markdown table override.
- **claim_cluster** → grouped list. Each group: bold header (`label`), then claims as small cards with the quote text and a `[↗ M:SS]` button that calls `onCitationClick`.

Wrap the artifact in a card: `rounded-2xl border border-ios-separator dark:border-white/[0.08] p-4 my-3 bg-white dark:bg-ios-card-dark`. So it visually breaks the prose flow inside the assistant bubble.

### B.4 Hooking into the markdown stream

In `ChatPage.tsx`, extend `markdownComponents.code`:

```tsx
code: ({ node, className, children, ...props }) => {
  const isChartBlock = typeof className === 'string' && className === 'language-chart'
  if (isChartBlock) {
    const raw = String(children).trim()
    try {
      const spec = JSON.parse(raw) as ChartSpec
      return <ChartArtifact spec={spec} profile={profile} onCitationClick={...} />
    } catch {
      // streaming may not be complete — render placeholder
      return <div className="text-[13px] text-ios-text-secondary italic my-2">Generating chart…</div>
    }
  }
  // ... existing block / inline code branches
}
```

Pass `profile` into `ChatPage` (read it once on mount via `GET /api/profile?channel_id=...` if not already in scope — check existing app state, profile is loaded by `ProfilePage` and may need to be lifted to App level or fetched here). Add a small `useProfile(channelId)` hook in `frontend/src/hooks/` if needed.

### B.5 Acceptance

- [ ] Ask "how has the creator's stance on AI evolved" — model emits an `evolution` block, frontend renders a slope chart with at least 2 points. Clicking a dot loads that video in the evidence pane at t=0.
- [ ] Ask "compare early videos vs recent" — model emits a `comparison_table`, frontend renders a styled table.
- [ ] Ask "what are the strongest claims about discipline" — model emits `claim_cluster`, each claim has a clickable timestamp.
- [ ] Streaming a chart block: while JSON is incomplete, "Generating chart…" placeholder shows. Once complete, the chart renders. No JSON parse errors thrown into the console.
- [ ] Bare questions like "what is this channel about" do NOT produce artifacts — model emits prose only.
- [ ] Markdown after the chart block (e.g. a closing sentence) renders correctly.

---

## Part C — Scope chips (filter the system prompt)

### C.1 UI

Above the chat input bar, add a chip row. Chips: themes (top 8 from `profile.rollups.all_themes`), date ranges (`Since 2024`, `Since 2023`, `2022 only`, etc. — derived from `profile.date_range`), tones (top 4 from `profile.rollups.tone_distribution`).

Selected chips show with `bg-ios-blue text-white`, unselected with `bg-white border border-ios-separator`. Click toggles. A small "Clear" link appears when ≥1 chip is selected.

State: `const [scope, setScope] = useState<{ themes: string[]; dateFrom?: string; dateTo?: string; tones: string[] }>({ themes: [], tones: [] })`

Selected scope is sent on each turn:

```ts
body: JSON.stringify({
  channel_id: channel.channel_id,
  messages: ...,
  scope: scope.themes.length || scope.tones.length || scope.dateFrom ? scope : undefined,
})
```

### C.2 Backend filter

Edit `backend/models.py` — extend `ChatPayload`:

```python
class ChatScope(BaseModel):
    themes: list[str] = Field(default_factory=list)
    tones: list[str] = Field(default_factory=list)
    date_from: str | None = None     # YYYYMMDD
    date_to: str | None = None       # YYYYMMDD

class ChatPayload(BaseModel):
    channel_id: str
    messages: list[ChatMessage]
    scope: ChatScope | None = None
```

Edit `backend/pipeline/ask.py:build_system_prompt`. Accept an optional `scope` argument. After loading `profile`, filter `videos`:

```python
def filter_videos(videos: list[dict], scope: ChatScope | None) -> list[dict]:
    if scope is None:
        return videos
    out = videos
    if scope.themes:
        wanted = {t.lower() for t in scope.themes}
        out = [v for v in out if any(t.lower() in wanted for t in v.get("recurring_themes", []))]
    if scope.tones:
        wanted = {t.lower() for t in scope.tones}
        out = [v for v in out if any(t.lower() in wanted for t in v.get("tone_markers", []))]
    if scope.date_from:
        out = [v for v in out if v.get("upload_date", "") >= scope.date_from]
    if scope.date_to:
        out = [v for v in out if v.get("upload_date", "") <= scope.date_to]
    return out
```

When scope is active, prepend a line to the system prompt:

```
SCOPE: this conversation is restricted to {N} of {M} videos matching the user's filters: themes={...}, tones={...}, dates={from..to}. Do not reference videos outside this set.
```

Update `chat_stream` and `routes/chat.py` to pass `scope` through. Keep the `build_system_prompt(channel_id)`-returns-`None`-if-missing-profile behavior.

### C.3 Acceptance

- [ ] Select theme chip "productivity" → next user turn ships scope; backend filters `videos` to those tagged productivity; system prompt declares the scope.
- [ ] Empty scope after filtering (e.g. theme that matches 0 videos) → backend returns `{type: "error", message: "scope_empty"}` immediately, no model call. Frontend shows red banner "No videos match the current filter."
- [ ] Clearing chips restores full-channel behavior on the next turn.
- [ ] Scope persists across turns within a session, but is NOT sent on existing turns already in `messages` — only the system prompt changes.
- [ ] Existing tests in `backend/tests/` still pass. Add one new test: `test_chat_scope.py` covering the filter function directly.

---

## Out of scope for this PR (future work)

- Conversation persistence to disk.
- Saved questions / scheduled re-runs.
- Comparison mode (two channels).
- Export to markdown/PDF.
- Theme co-occurrence heatmap on the profile page.
- Quote extraction page (top N strongest claims).
- Backend tool-use API for artifacts (the fenced-block approach is fine for v1).

If you finish A+B+C cleanly with time left, start a `feat/chat-persistence` branch — don't bundle.

---

## Implementation order

1. **A.2** — refactor citation marker to a `<button>` + parse out videoId/startSeconds. Keep behavior identical (still opens new tab via `window.open`). Smallest change, lets you verify nothing regresses.
2. **A.3** + **A.4** — build `EvidencePane`, wire `focusedRef`, hook clicks. Desktop only first. Verify with a real channel.
3. **A.3 mobile sheet** — `EvidenceSheet` + floating pill.
4. **B.2** — prompt change + suggested prompt update. Manually test that the model emits chart blocks.
5. **B.3** + **B.4** — artifact components + markdown hook. Render `evolution` first (highest novelty), then `comparison_table`, then `claim_cluster`.
6. **C.1** + **C.2** — scope chips + backend filter. Add the new test.
7. Final pass: dark mode on every new surface, mobile breakpoints, loading states.

Commit after each numbered step. Conventional Commits prefixes (`feat:`, `refactor:`, `test:`).

---

## Files you will touch

**Edit:**
- `frontend/src/pages/ChatPage.tsx` (citation hook, layout split, code-block override)
- `backend/pipeline/ask.py` (prompt template, scope filter, `build_system_prompt` signature)
- `backend/routes/chat.py` (forward scope)
- `backend/models.py` (`ChatScope`, `ChatPayload.scope`)

**Create:**
- `frontend/src/components/EvidencePane.tsx`
- `frontend/src/components/EvidenceSheet.tsx`
- `frontend/src/components/ChartArtifact.tsx`
- `frontend/src/components/ScopeChips.tsx`
- `frontend/src/contexts/CitationContext.tsx` (or inline in ChatPage if <40 lines)
- `frontend/src/hooks/useProfile.ts` (only if profile isn't already in scope)
- `backend/tests/test_chat_scope.py`

**Do not touch:**
- `frontend/src/pages/ProfilePage.tsx` (recently revamped, separate concern)
- `frontend/src/pages/{ChannelInput,VideoList,TranscriptProgress,SummaryProgress}Page.tsx`
- `frontend/src/hooks/useSSE.ts`
- `backend/pipeline/{aggregate,fetch_transcripts,summarize,fetch_videos}.py`
- `backend/storage.py`

---

## When you are stuck

- **Iframe doesn't seek on second click of same video:** add `key={`${videoId}-${startSeconds}-${clickNonce}`}` where `clickNonce` is a counter you bump on every citation click. Forces remount even when video+start are the same.
- **Model emits a chart block but JSON is malformed:** check that the prompt example in B.2 is exact. Models tend to add trailing commas or markdown fences inside the JSON; if that keeps happening, harden the parser by stripping common malformations before `JSON.parse`.
- **Citation regex misses a real citation:** the prompt enforces `[↗ M:SS](https://youtu.be/<id>?t=<s>s)` but the model occasionally emits `youtube.com/watch?v=...&t=...s`. Update the regex and the existing `isYouTubeCitationHref` to accept both forms.
- **Scope filter empties the corpus mid-conversation:** that's user error, but make the error message specific: include which filter cleared the set.
- **Recharts type errors on React 19:** cast data arrays to `any[]` (already a known issue per `PLAN_UX_REVAMP.md`).

Ship it.
