# UX Revamp: Profile Page + Progress Pages

**Audience:** another AI agent implementing this. You are a junior dev — I will explain the *why* in plain words and give you exact files, snippets, and acceptance checks. Read the whole doc before touching code.

**Branch:** create `feat/ux-revamp` off `main`.

**Why we are doing this:** the current build was tested on a 110-video channel (~100k tokens). Two pages broke down:

1. **`ProfilePage.tsx`** (the screen between summarization and chat) — rendered as a giant scroll of pill-clouds + a 110-row timeline. Visually crowded, no overview, hostile to scanning.
2. **`TranscriptProgressPage.tsx` / `SummaryProgressPage.tsx`** — when you select 100+ videos, the only "live" feedback is a row's tag flipping from `Queued` → `Fetching` → `Done`. You have to scroll to find what is currently running. Cursor and Claude Code show a live activity strip with the *current* operation animated; we should do the same.

We are NOT redesigning the whole app. Just these two areas. Scope discipline matters — do not refactor `ChatPage`, `VideoListPage`, `ChannelInputPage`, or the backend pipeline logic itself. Backend changes are limited to **one** new SSE event type (see Part B).

---

## Tech choices (decided, do not relitigate)

- **Charts:** add [`recharts`](https://recharts.org). Reasons: pure-React, declarative, ~95kb gzipped, plays nice with Tailwind, no canvas wrangling. Install with `npm install recharts` in `frontend/`.
- **Animations:** use Tailwind transitions + a tiny custom `<TypingDots />` component. Do **not** add framer-motion — overkill.
- **Virtualization:** if the timeline list goes over 200 rows we'd need it, but at ≤200 rows native scroll is fine. Skip virtualization for now. Add a `// TODO virtualize if profile.videos.length > 200` comment in code.
- **No new backend deps.**

---

## Part A — `ProfilePage.tsx` revamp

### A.1 The problem in concrete terms

Open `frontend/src/pages/ProfilePage.tsx`. Render order today:

1. Header card (avatar + name + "X videos · date range")
2. **Recurring themes card** — `flex-wrap` of pills sized by frequency. With 30+ themes this becomes a wall of text.
3. **Tone distribution card** — stacked horizontal bars, one per tone. With 8+ tones it just keeps going.
4. **Timeline card** — every video as a collapsible row (110 of them).
5. **Frequently referenced card** — another wall of pills.

Everything is text. Nothing is a graphic. The user sees a wall.

### A.2 New layout (target)

The screen should give a **dashboard-style overview at the top**, then the deep list below. Minimalist. Lots of whitespace. Charts > pill clouds.

```
┌──────────────────────────────────────────────┐
│ Header card (unchanged)                      │
├──────────────────────────────────────────────┤
│ ╭─ Top themes ─╮  ╭─ Tone mix ─╮             │  ← side-by-side row
│ │ horizontal   │  │ donut      │             │     of two charts
│ │ bar chart    │  │ chart      │             │
│ │ top 8        │  │            │             │
│ ╰──────────────╯  ╰────────────╯             │
├──────────────────────────────────────────────┤
│ ╭─ Activity over time ────────────────╮      │  ← single full-width
│ │ small area / bar chart of           │       │     chart
│ │ uploads/month                       │       │
│ ╰─────────────────────────────────────╯      │
├──────────────────────────────────────────────┤
│ Top referenced (top 10 only, "+ N more"      │
│ button to expand)                            │
├──────────────────────────────────────────────┤
│ Timeline (collapsed by default — toggle)     │
├──────────────────────────────────────────────┤
│ [ Start chatting → ]                         │
└──────────────────────────────────────────────┘
```

Key principles:

- **Top fold = visuals only.** No text walls above the timeline.
- **Charts replace pill clouds** for the top-level view. Pills survive only inside expanded timeline rows (those are still useful for filtering by theme).
- **Timeline starts collapsed** when `videos.length > 30`. User clicks "Show timeline" to expand. Saves cognitive load on big channels.

### A.3 Specific component changes

You will mostly **edit** `ProfilePage.tsx`. Add three new chart components in the same file (no new files unless they exceed ~80 lines).

#### A.3.a Add charts row

Replace the "Recurring themes" `Card` and "Tone distribution" `Card` (currently rendered separately) with a single grid:

```tsx
<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
  <ThemesBarChart themes={profile.rollups.all_themes.slice(0, 8)} />
  <ToneDonutChart tones={toneEntries} />
</div>
```

`ThemesBarChart`: horizontal bar chart, recharts `<BarChart layout="vertical">`. Top 8 themes by `count`. Click on a bar still toggles the theme filter (preserve the existing `selectedThemes` behavior — bind `onClick` on `<Bar>`). Add a small "Show all N" link below the chart that opens a modal/expandable with the full list as pills (you can keep the old `ThemePill` component for that expanded view).

`ToneDonutChart`: recharts `<PieChart>` with `innerRadius={50}` for donut look. Use the existing `toneEntries` data. Display top tone in the donut center (largest slice label).

Use Tailwind tokens for colors. Pull from existing palette: `--ios-blue` for primary, then a small fixed array for additional series. Define once at top of file:

```ts
const CHART_COLORS = ['#0a84ff', '#34c759', '#ff9f0a', '#ff453a', '#bf5af2', '#5ac8fa', '#ffd60a', '#8e8e93']
```

#### A.3.b Add upload-density chart

New component `UploadActivityChart`. Bins `profile.videos` by month and renders a small recharts `<AreaChart>`. ~120px tall, full width. Useful because the user can see "this channel posts heavily in 2024 then went quiet" at a glance.

Compute bins inside a `useMemo`:

```ts
const monthlyCounts = useMemo(() => {
  const map = new Map<string, number>()
  for (const v of profile.videos) {
    const key = v.upload_date.slice(0, 7) // 'YYYY-MM'
    map.set(key, (map.get(key) ?? 0) + 1)
  }
  return [...map.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, count]) => ({ month, count }))
}, [profile])
```

If `monthlyCounts.length < 2`, **do not render** the chart (one data point is meaningless).

#### A.3.c Trim "Frequently referenced"

Replace `profile.rollups.all_referenced.map(...)` with `.slice(0, 10).map(...)` and add a "Show all (N)" toggle that expands to the full list. Same pattern as themes. Use `useState<boolean>(false)` — no need for a modal.

#### A.3.d Collapse timeline by default

Add state `const [timelineOpen, setTimelineOpen] = useState(profile.videos.length <= 30)`.

Wrap the existing `<Card className="p-0 overflow-hidden">{filteredVideos.map(...)}</Card>` in a collapsible. Header looks like:

```tsx
<button
  onClick={() => setTimelineOpen(o => !o)}
  className="w-full flex items-center justify-between mb-3"
>
  <SectionHeader className="mb-0">Timeline</SectionHeader>
  <span className="text-[13px] text-ios-text-secondary">
    {filteredVideos.length} videos {timelineOpen ? '▾' : '▸'}
  </span>
</button>
{timelineOpen && (
  <Card className="p-0 overflow-hidden"> ... </Card>
)}
```

When the user picks a theme filter, **auto-open** the timeline (filtering is meaningless if the list is hidden). Add this effect:

```ts
useEffect(() => {
  if (selectedThemes.size > 0) setTimelineOpen(true)
}, [selectedThemes])
```

#### A.3.e Keep the existing `TimelineRow` component as-is

Once a row is expanded, the current pills layout is fine — that's a per-video drill-down, not the overview. Do not change `TimelineRow`.

### A.4 Styling guardrails

- Cards should have `min-h-[200px]` for the chart cards so the page doesn't jump while data loads.
- `ResponsiveContainer` from recharts is mandatory — never hardcode chart pixel widths.
- Dark mode: recharts inherits SVG `fill`/`stroke` you pass. Use `text-ios-text-primary` from CSS via `currentColor`, or pass colors explicitly. Test both light and dark.
- Mobile: charts row should stack (`md:grid-cols-2` → `grid-cols-1` on mobile, already in the snippet above).

### A.5 What NOT to do

- Do not delete the `ThemePill`, `ReferencedPill`, `ToneBar` components — `ThemePill` is reused in the "Show all" expanded view and `ToneBar` may still be useful as a fallback if there are <3 tones (donut looks dumb with 1-2 slices). If <3 tones, render `<ToneBar>` rows instead of the donut.
- Do not change anything in `types.ts` for this part. The existing `Profile` shape is sufficient.
- Do not add a "filter videos by date range" feature. Out of scope. We're trimming, not adding.

---

## Part B — Progress pages: live activity feed

This applies to BOTH `TranscriptProgressPage.tsx` and `SummaryProgressPage.tsx`. They are near-clones today; we'll keep them as separate files but extract the new "activity" behavior into shared components in `frontend/src/components/`.

### B.1 The problem

Open `TranscriptProgressPage.tsx`. With 100 selected videos:

- Top: avatar, "X of Y complete", a thin progress bar.
- Then: a flat list of 100 thumbnail rows. Status pill on the right of each.
- The user has no idea **which video is being processed right now** unless they scroll to find a row whose pill says `Fetching` (and there can be up to `SUMMARY_WORKERS=5` of them at once).
- No throughput info (videos/min, ETA, success rate, failure count).

The "Cursor / Claude Code" feel the user wants: a small panel near the top that shows live "what's happening" — currently active items with a typing/spinner indicator, plus a rolling activity log of the last few state transitions. The full list stays available below but is no longer the primary feedback channel.

### B.2 Target layout

```
┌──────────────────────────────────────────────┐
│ Header (avatar + title + Cancel button)      │
├──────────────────────────────────────────────┤
│ Stats strip: [ 42/110 ]  [ 38 done ]         │
│              [ 3 failed ] [ ~4 min left ]    │
├──────────────────────────────────────────────┤
│ Progress bar                                 │
├──────────────────────────────────────────────┤
│ ╭─ Live activity ──────────────────────────╮ │
│ │ ● Fetching: "How to be authentic..."     │ │
│ │ ● Fetching: "Stop people-pleasing..."    │ │
│ │ ● Fetching: "Discipline beats talent..." │ │
│ │ ─────────                                │ │
│ │ recent log:                              │ │
│ │ 14:02:11 ✓ "Why I quit"                  │ │
│ │ 14:02:09 ✗ "Lost video" (unavailable)    │ │
│ │ 14:02:07 ✓ "Mindset reset"               │ │
│ ╰──────────────────────────────────────────╯ │
├──────────────────────────────────────────────┤
│ ▸ All videos (110)  ← click to expand        │
│   (collapsed by default once count > 30)     │
└──────────────────────────────────────────────┘
```

### B.3 New shared components

Create `frontend/src/components/ProgressStats.tsx`:

```tsx
interface Props {
  total: number
  done: number
  failed: number
  unavailable?: number
  startedAt?: string  // ISO timestamp from pipeline state
}
```

Renders a flex row of pill-style stat cards (counts, ETA). ETA = `(elapsedSec / completed) * (total - completed)`. Show "—" if `completed === 0`. Format as "~3 min left" / "~12 sec left".

Create `frontend/src/components/LiveActivityPanel.tsx`:

```tsx
interface ActivityItem {
  videoId: string
  title: string
  status: 'fetching' | 'done' | 'failed' | 'unavailable' | 'skipped'
  ts: number  // Date.now() when status changed
}

interface Props {
  activeItems: ActivityItem[]      // currently 'fetching'
  recentLog: ActivityItem[]        // last 8 terminal transitions
  verb: string                     // 'Fetching' | 'Summarizing'
}
```

Layout:
- Top half: list of active items, each prefixed with a `<TypingDots />` (three pulsing dots in `ios-blue`). Truncate titles with `truncate` on a `min-w-0` flex item.
- Divider.
- Bottom half: last 8 terminal transitions, newest first, with `HH:MM:SS` timestamps and a status icon (✓ green, ✗ red, ! yellow). Auto-scroll: do NOT auto-scroll. Just render newest at top.
- If `activeItems.length === 0` AND `recentLog.length === 0`, render placeholder text "Waiting to start…".
- Cap log at 8 entries. Older ones drop off. `useRef` to retain across renders, see B.5.

`<TypingDots />` is 5 lines of JSX:

```tsx
function TypingDots() {
  return (
    <span className="inline-flex gap-0.5 items-center">
      <span className="w-1 h-1 rounded-full bg-ios-blue animate-pulse" style={{ animationDelay: '0ms' }} />
      <span className="w-1 h-1 rounded-full bg-ios-blue animate-pulse" style={{ animationDelay: '150ms' }} />
      <span className="w-1 h-1 rounded-full bg-ios-blue animate-pulse" style={{ animationDelay: '300ms' }} />
    </span>
  )
}
```

### B.4 Wiring it into the progress pages

In both `TranscriptProgressPage.tsx` and `SummaryProgressPage.tsx`:

1. Below the header, add `<ProgressStats ... />` using the same `videos` array we already compute.
2. Below the progress bar, add `<LiveActivityPanel ... />` (see B.5 for state).
3. Wrap the existing flat list of video rows in a collapsible — same pattern as A.3.d. Default-open when `videos.length <= 30`, otherwise default-closed. Header text: "All videos (N) ▸".
4. Stats: pass `startedAt={state?.started_at}` so the panel can compute ETA.

### B.5 Tracking the activity log on the client

Backend currently emits one `video_update` SSE event per status transition (see `backend/routes/pipeline.py:_handle_progress`). That's enough — we don't need a new event type. The data we want is already on each transition.

In the progress page, add:

```ts
const [activityLog, setActivityLog] = useState<ActivityItem[]>([])
const lastStatusRef = useRef<Record<string, string>>({})
```

In a `useEffect` keyed on `videos`, diff the latest status of each video against `lastStatusRef.current`. For every changed entry that moved into a *terminal* status, prepend an `ActivityItem` with `ts: Date.now()` and trim to length 8:

```ts
useEffect(() => {
  const newEntries: ActivityItem[] = []
  for (const v of videos) {
    const prev = lastStatusRef.current[v.id]
    if (prev !== v.status) {
      lastStatusRef.current[v.id] = v.status
      if (terminalStatuses.has(v.status)) {
        newEntries.push({ videoId: v.id, title: v.title, status: v.status as ActivityItem['status'], ts: Date.now() })
      }
    }
  }
  if (newEntries.length > 0) {
    setActivityLog(prev => [...newEntries, ...prev].slice(0, 8))
  }
}, [videos])
```

`activeItems` is derived in render:

```ts
const activeItems: ActivityItem[] = videos
  .filter(v => v.status === 'fetching')
  .map(v => ({ videoId: v.id, title: v.title, status: 'fetching', ts: 0 }))
```

`verb` prop: `"Fetching"` for transcripts page, `"Summarizing"` for summaries page.

### B.6 Optional backend enhancement (DO LAST, gate behind a feature toggle env var)

If time permits and you want the activity feed to feel even richer, add **one** new SSE event:

- Backend: in `backend/pipeline/fetch_transcripts.py` and `backend/pipeline/summarize.py`, when the worker actually starts a network call, emit a richer progress message via the existing `on_progress` callback. Currently the callback gets `{video_id, status}`. Extend it (carefully — there are tests in `backend/tests/`) to also include an optional `detail` string like `"transcript pull from youtube"` or `"calling MiniMax (4123 input tokens)"`.
- The existing `_broadcast` call in `pipeline.py:_handle_progress` would forward `detail` into the `video_update` event payload.
- Frontend `LiveActivityPanel` would render `detail` under the title in active items, italic gray.

If you do this, **only** add an optional `detail?: string` field. Do not change the existing event shape. Update tests accordingly. If unsure, skip this — the client-side log alone is already a big improvement.

---

## Implementation order

Do these in order. Test after each step before moving on.

1. **Setup**: `cd frontend && npm install recharts`. Verify `npm run dev` still works and bundle size hasn't ballooned past expectations.
2. **Part A.3.d** (collapse timeline) — smallest visible win, no new deps used. Easy to verify.
3. **Part A.3.c** (trim referenced).
4. **Part A.3.a** (themes bar + tone donut). First recharts use — confirm responsive container behaves.
5. **Part A.3.b** (upload activity chart).
6. **Part B.3** (build `ProgressStats` and `LiveActivityPanel` in isolation, render with mock data on a sandbox route or via a temporary prop).
7. **Part B.4 + B.5** (wire into both progress pages).
8. **Part B.6** only if 1-7 are clean.

Commit after each step. Conventional commit prefixes (`feat:`, `refactor:`, `chore:`).

---

## Acceptance checks

Run all of these before opening the PR.

### Profile page
- [ ] Load a profile with **only 3 videos** — page still looks good (charts shouldn't crash on small N; donut should fall back to `<ToneBar>` rows when tones < 3).
- [ ] Load the 110-video profile — top fold (above the timeline) fits in one viewport on a 1440×900 screen.
- [ ] Click a bar in the themes chart — the timeline auto-opens and filters. Clear filter works.
- [ ] Dark mode: all chart text/axes legible.
- [ ] Mobile (375px wide): charts stack vertically, no horizontal scroll.

### Progress pages
- [ ] Start a 100-video pipeline. Watch the live activity panel: it should always show 1-5 currently-fetching items (depends on `SUMMARY_WORKERS`).
- [ ] After 10 videos finish, the recent log shows the last 8 transitions, newest at top.
- [ ] Stats strip shows a sensible ETA after 5+ completions.
- [ ] Fail one video on purpose (e.g. unselect MINIMAX_API_KEY mid-run): "X failed" count increments, log shows the ✗ entry.
- [ ] "All videos" section is collapsed by default for 100 videos. Expanding works.

### Doesn't-regress checks
- [ ] `ChatPage`, `VideoListPage`, `ChannelInputPage` render unchanged (no incidental imports broken).
- [ ] `npm run build` passes with no new TypeScript errors.
- [ ] Existing backend tests still pass: `cd backend && pytest`.

---

## Files you will touch

**Edit:**
- `frontend/src/pages/ProfilePage.tsx`
- `frontend/src/pages/TranscriptProgressPage.tsx`
- `frontend/src/pages/SummaryProgressPage.tsx`
- `frontend/package.json` (recharts dep)
- `frontend/package-lock.json` (auto)

**Create:**
- `frontend/src/components/ProgressStats.tsx`
- `frontend/src/components/LiveActivityPanel.tsx`

**Do not touch (out of scope):**
- Anything under `backend/` (unless you do the optional B.6, in which case `backend/pipeline/{fetch_transcripts,summarize}.py` and `backend/routes/pipeline.py` only)
- `frontend/src/pages/ChatPage.tsx`
- `frontend/src/pages/VideoListPage.tsx`
- `frontend/src/pages/ChannelInputPage.tsx`
- `frontend/src/types.ts` (no schema changes)
- `frontend/src/api.ts`
- `frontend/src/hooks/useSSE.ts` — the existing SSE wiring is sufficient

---

## When you are stuck

- Recharts type errors with React 19: pass `data` as `any[]` if the generic gets unhappy. Recharts 2.x typings lag React 19.
- If `npm install recharts` produces a peer-dep warning about React 19, run with `--legacy-peer-deps`. It works at runtime.
- Don't try to "improve" `useSSE.ts`. It's fine. The activity log is fully derivable from the data it already exposes.
- If a test fails after step 6+, the most likely cause is you accidentally changed an import path in one of the page files. Run `git diff` and look for unintended edits.

Ship it.
