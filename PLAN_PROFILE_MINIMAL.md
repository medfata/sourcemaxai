# Profile Page Minimal Refactor

**Audience:** another AI agent implementing this. Junior-dev voice. Read the whole doc before touching code.

**Branch:** continue on `feat/ux-revamp` (existing branch — do not create a new one).

**Goal:** strip the profile page down to the components that actually drive the next user action (chat). Less crowding, more signal. No new backend dependencies. No schema changes.

---

## Why we are doing this

The profile step sits between summarization and chat. The user just waited several minutes for the pipeline; they land here with **blank-page anxiety**. The page must answer two questions in under five seconds:

1. **Trust** — did the pipeline get the right channel and capture real substance?
2. **Intent** — what should I ask?

Today the page shows: header → top themes bar → tone donut → activity area chart → frequently referenced pills → timeline. The middle two (tone, activity) are decoration. They eat the top fold without driving a question. The page also lacks a *seeded path into chat* — users stare at "Start chatting →" with nothing to type.

We are trimming the noise and adding two seed components built from data we already have on the client.

**This refactor is intentionally small.** No backend. No new aggregation pass. No new SSE events. No LLM-generated TL;DR. Everything below is computable from the existing `Profile` shape in `frontend/src/types.ts`.

---

## Tech choices (decided, do not relitigate)

- No new npm packages. `recharts` is already installed and stays.
- No `framer-motion`. Use Tailwind transitions.
- No new files unless a component exceeds ~80 lines. Prefer adding components inside `ProfilePage.tsx`.
- Do not edit `backend/`, `types.ts`, `api.ts`, or any other page.

---

## Target layout

```
┌──────────────────────────────────────────────┐
│ Header (avatar + name + N videos · dates)    │  ← unchanged
├──────────────────────────────────────────────┤
│ ╭─ Top themes ─╮  ╭─ Frequently referenced ╮ │  ← side-by-side, both
│ │ bar chart    │  │ pills (top 8)          │ │     high-signal
│ ╰──────────────╯  ╰────────────────────────╯ │
├──────────────────────────────────────────────┤
│ ╭─ Signature claims (NEW) ─────────────────╮ │  ← top 5 distinctive
│ │ "X argues that …" ↗ 12:34                │ │     claims with
│ │ "X opposes …"      ↗ 03:21                │ │     citation pills
│ ╰──────────────────────────────────────────╯ │
├──────────────────────────────────────────────┤
│ ╭─ Suggested questions (NEW) ──────────────╮ │  ← seed questions →
│ │ [ How did {creator} … {top_theme}? ]     │ │     click sends user
│ │ [ What does {creator} say about {ref}? ] │ │     to chat with
│ ╰──────────────────────────────────────────╯ │     prefilled input
├──────────────────────────────────────────────┤
│ ▸ Timeline (collapsed, N videos)             │  ← keep, collapsed
├──────────────────────────────────────────────┤
│ ▸ More stats                                 │  ← tone donut +
│   (collapsed by default — opens to show     │     activity chart
│    tone mix + activity over time)           │     demoted here
├──────────────────────────────────────────────┤
│ [ Start chatting → ]                         │  ← unchanged
└──────────────────────────────────────────────┘
```

Key principles:

- **Top fold = themes + references.** These are the two highest-signal cards for "what to ask". Side-by-side so the eye sees the whole channel at once.
- **Signature claims** prove the pipeline captured real substance and seed concrete questions.
- **Suggested questions** convert intent to action. The biggest unlock for users who don't know where to start.
- **Tone + activity demoted** to a collapsed "More stats" drawer. Not deleted — they still serve the competitive-analyst niche.

---

## Components

### 1. Keep (unchanged)

- Header card.
- `ThemesBarChart` (currently in `ProfilePage.tsx`). Stays as-is, click-to-filter behavior preserved.
- `TimelineRow` and the collapsible Timeline section.
- `Start chatting` footer button.

### 2. Move to side-by-side row

The current layout has the "Top themes" card paired with the **tone donut**. Replace that pairing with **themes + referenced**:

```tsx
<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
  <div>
    <SectionHeader>Top themes</SectionHeader>
    <Card>
      <ThemesBarChart ... />
      {/* keep existing "Show all" + clear-filter buttons */}
    </Card>
  </div>
  <div>
    <SectionHeader>Frequently referenced</SectionHeader>
    <Card>
      {/* existing referenced-pills code, slice(0, 8), with show-all toggle */}
    </Card>
  </div>
</div>
```

The standalone "Frequently referenced" section that lives below the activity chart today gets removed (it has been promoted into the row). Trim the visible default from 10 pills to 8 to match the chart's top-8 cap.

### 3. Add: Signature claims card (NEW)

**Goal:** show the 5 most distinctive claims this creator has ever made, each with a clickable timestamp link to the source video. Pure proof of substance.

**Data:** aggregate `profile.videos[].key_claims` and `profile.videos[].notable_opinions`. Both already carry `evidence: { start_seconds, quote }[]`.

**Selection heuristic** (no LLM, no backend):

```ts
interface AggregatedClaim {
  text: string
  videoId: string
  videoTitle: string
  uploadDate: string
  startSeconds: number
}

const signatureClaims = useMemo<AggregatedClaim[]>(() => {
  if (!profile) return []
  const all: AggregatedClaim[] = []
  for (const v of profile.videos) {
    // notable_opinions are stronger signal than key_claims — pull those first
    for (const op of v.notable_opinions) {
      if (op.evidence.length === 0) continue
      all.push({
        text: op.text,
        videoId: v.video_id,
        videoTitle: v.title,
        uploadDate: v.upload_date,
        startSeconds: op.evidence[0].start_seconds,
      })
    }
  }
  // fallback: if fewer than 5 notable_opinions across all videos, top up from key_claims
  if (all.length < 5) {
    for (const v of profile.videos) {
      for (const c of v.key_claims) {
        if (c.evidence.length === 0) continue
        all.push({
          text: c.text,
          videoId: v.video_id,
          videoTitle: v.title,
          uploadDate: v.upload_date,
          startSeconds: c.evidence[0].start_seconds,
        })
        if (all.length >= 5) break
      }
      if (all.length >= 5) break
    }
  }
  // dedupe by lowercased first 60 chars of text
  const seen = new Set<string>()
  const deduped: AggregatedClaim[] = []
  for (const c of all) {
    const key = c.text.slice(0, 60).toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    deduped.push(c)
    if (deduped.length >= 5) break
  }
  return deduped
}, [profile])
```

If `signatureClaims.length === 0`, **do not render the card** at all (do not show an empty state).

**UI:**

```tsx
<div>
  <SectionHeader>Signature claims</SectionHeader>
  <Card>
    <ul className="space-y-3">
      {signatureClaims.map((c, i) => (
        <li key={i} className="text-[15px] text-ios-text-primary dark:text-ios-text-primary-dark leading-relaxed">
          <span>{c.text}</span>
          <CitationPill videoId={c.videoId} startSeconds={c.startSeconds} />
          <div className="text-[12px] text-ios-text-secondary mt-0.5 truncate">
            {c.videoTitle} · {formatShortDate(c.uploadDate)}
          </div>
        </li>
      ))}
    </ul>
  </Card>
</div>
```

Reuse the existing `CitationPill` component already defined in `ProfilePage.tsx`.

### 4. Add: Suggested questions card (NEW)

**Goal:** four pre-baked prompts the user can click to enter chat with the input prefilled. Removes blank-page friction.

**Data:** templates filled from `profile.rollups.all_themes` and `profile.rollups.all_referenced`. No LLM.

**Templates** (use the top entry of each list; if a list is empty, skip that template):

```ts
const suggestedQuestions = useMemo<string[]>(() => {
  if (!profile) return []
  const themes = profile.rollups.all_themes
  const refs = profile.rollups.all_referenced
  const name = profile.channel_name
  const out: string[] = []
  if (themes[0]) out.push(`How does ${name} think about ${themes[0].theme}?`)
  if (themes[1]) out.push(`Has ${name}'s view on ${themes[1].theme} changed over time?`)
  if (refs[0]) out.push(`What does ${name} say about ${refs[0].name}?`)
  out.push(`Summarize the most distinctive opinions ${name} has shared.`)
  return out.slice(0, 4)
}, [profile])
```

**UI:**

```tsx
<div>
  <SectionHeader>Suggested questions</SectionHeader>
  <Card>
    <div className="flex flex-col gap-2">
      {suggestedQuestions.map((q, i) => (
        <button
          key={i}
          onClick={() => onStartChat(q)}
          className="text-left text-[15px] text-ios-text-primary dark:text-ios-text-primary-dark px-4 py-3 rounded-xl bg-ios-bg dark:bg-gray-800 hover:bg-ios-blue/10 hover:text-ios-blue transition-colors"
        >
          {q}
        </button>
      ))}
    </div>
  </Card>
</div>
```

**Wiring `onStartChat(question)` through to `ChatPage`:**

Today `ProfilePage` calls `onStartChat()` with no args. We need it to optionally pass a seed question.

Steps:

1. In `ProfilePage.tsx`, change the prop type:
   ```ts
   onStartChat: (seed?: string) => void
   ```
2. In `App.tsx` (or wherever `ProfilePage` is rendered — find with `grep -r "onStartChat" frontend/src`), accept the optional `seed` argument and stash it in state, e.g. `const [chatSeed, setChatSeed] = useState<string | undefined>()`. Pass it to `ChatPage` as a new prop `initialInput?: string`.
3. In `ChatPage.tsx`, if `initialInput` is provided on mount, prefill the input box (set the existing input state). **Do not auto-send** — the user reviews/edits the question first. Clear `initialInput` after first render so it does not refire.
4. The footer "Start chatting →" button keeps calling `onStartChat()` with no args (seed is undefined → no prefill).

If the wiring in step 2/3 turns out to require touching `ChatPage` in ways that conflict with other in-flight changes, **fall back** to: `onStartChat()` with no args, and stash the seed in `sessionStorage.setItem('chatSeed', q)`. `ChatPage` reads and clears it on mount. Document the fallback in the commit message if you take it.

### 5. Demote: tone donut + activity chart → "More stats" drawer

Wrap both inside a single collapsed section:

```tsx
const [moreStatsOpen, setMoreStatsOpen] = useState(false)

<div>
  <button
    onClick={() => setMoreStatsOpen(o => !o)}
    className="w-full flex items-center justify-between mb-3"
  >
    <SectionHeader className="mb-0">More stats</SectionHeader>
    <span className="text-[13px] text-ios-text-secondary">
      {moreStatsOpen ? '▾' : '▸'}
    </span>
  </button>
  {moreStatsOpen && (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <Card>
        <p className="text-[13px] text-ios-text-secondary mb-2">Tone mix</p>
        {/* existing ToneDonutChart / ToneBar fallback */}
      </Card>
      {monthlyCounts.length >= 2 && (
        <Card>
          <p className="text-[13px] text-ios-text-secondary mb-2">Activity over time</p>
          <UploadActivityChart data={monthlyCounts} />
        </Card>
      )}
    </div>
  )}
</div>
```

Do **not** delete `ToneDonutChart`, `ToneBar`, or `UploadActivityChart`. They keep working, just behind a click.

### 6. Final render order in `ProfilePage`

Top → bottom:

1. Header card
2. Themes + Referenced row (side-by-side)
3. Signature claims card *(skip if 0 claims)*
4. Suggested questions card
5. Timeline (collapsed when `videos.length > 30`, current behavior preserved)
6. More stats drawer (collapsed by default)
7. Footer `Start chatting →`

---

## Styling guardrails

- Cards keep `min-h-[200px]` only on chart cards. The new claims/questions cards size to content — do not add a min height.
- Spacing between top-level sections stays at the existing `space-y-6` on the outer container.
- Mobile: every grid stacks (`md:grid-cols-2` → `grid-cols-1` on small screens). Already handled by Tailwind classes shown above.
- Dark mode: reuse the existing `dark:` classes. No new color tokens.

---

## What NOT to do

- Do not generate a TL;DR / channel summary. That requires an LLM call we are not adding in this pass.
- Do not add a search bar or topic clustering. Out of scope.
- Do not add an "Evolution view" link. Out of scope.
- Do not change `ThemesBarChart`, `ToneDonutChart`, `UploadActivityChart`, or `TimelineRow` internals. Only their position/visibility changes.
- Do not delete unused-looking imports without verifying — `formatShortDate` is needed for the new claims card.
- Do not refactor `ChatPage` beyond the small `initialInput` prefill described in section 4. If it grows hairy, take the `sessionStorage` fallback.

---

## Implementation order

Do these in order. Commit after each step. Conventional prefixes (`feat:`, `refactor:`, `chore:`).

1. **Reorder + demote.** Move "Frequently referenced" into the top row beside themes. Wrap tone donut + activity chart in the "More stats" collapsed drawer. No new components yet. Verify the page still renders for a 110-video channel and a 3-video channel.
2. **Signature claims card.** Add the `signatureClaims` `useMemo` and the new card. Verify the citation pills open YouTube at the right timestamp. Verify the card is hidden when there are no notable opinions and no key claims.
3. **Suggested questions card** (data + UI only — no chat wiring yet). Verify the four templates render and skip gracefully when a rollup list is empty.
4. **Wire `onStartChat(seed?)` through to `ChatPage`'s `initialInput`.** Test that clicking a suggested question lands the user in chat with the input prefilled and *not* auto-sent. Test the plain `Start chatting →` button still works without prefill.
5. **Polish pass.** Dark mode, mobile (375px), 1440×900 desktop. Confirm the top fold (down to and including suggested questions) fits in roughly one viewport on the 110-video channel.

---

## Acceptance checks

Run all of these before opening the PR.

- [ ] **3-video channel**: page renders. No empty cards. Signature claims card hidden if no claims/opinions exist.
- [ ] **110-video channel**: top fold (header → themes+referenced → signature claims → suggested questions) fits in one viewport on a 1440×900 screen with no scroll on the suggested questions card.
- [ ] **Themes click**: clicking a bar in the themes chart still toggles the filter and auto-opens the timeline. Clear filter still works.
- [ ] **Citation pill**: clicking a timestamp pill in a signature claim opens the right YouTube video at the right second in a new tab.
- [ ] **Suggested question click**: clicking a suggested question lands on `ChatPage` with the input prefilled. Pressing Enter sends. Closing and reopening chat does not re-fire the seed.
- [ ] **Start chatting button**: clicking the footer button lands on `ChatPage` with an empty input.
- [ ] **More stats drawer**: closed by default. Opens to reveal tone donut + activity chart. Both render correctly on small N (donut falls back to `<ToneBar>` when tones < 3; activity hidden when months < 2 — same rules as today).
- [ ] **Dark mode**: all new cards legible. Hover states on suggested-question buttons visible.
- [ ] **Mobile (375px)**: every grid stacks vertically. No horizontal scroll. Claim citation pills do not overflow.
- [ ] `npm run build` passes with no new TypeScript errors.
- [ ] `cd backend && pytest` still passes (it should — backend untouched).

---

## Files you will touch

**Edit:**
- `frontend/src/pages/ProfilePage.tsx` (most of the work)
- `frontend/src/pages/ChatPage.tsx` (small: accept `initialInput`, prefill once)
- `frontend/src/App.tsx` *or wherever `ProfilePage` is rendered* (small: route the seed string through)

**Create:** none expected. Add components inline in `ProfilePage.tsx` unless one grows past ~80 lines.

**Do not touch:**
- Anything under `backend/`
- `frontend/src/types.ts`
- `frontend/src/api.ts`
- `frontend/src/hooks/useSSE.ts`
- `frontend/src/pages/VideoListPage.tsx`, `ChannelInputPage.tsx`, `TranscriptProgressPage.tsx`, `SummaryProgressPage.tsx`

---

## When you are stuck

- If `signatureClaims` ends up dominated by repetitive opinions from the same video, accept it for v1 — we can add per-video caps later. Don't over-engineer the heuristic now.
- If the suggested question buttons cause layout shift on hover, use `transition-colors` only (already in the snippet) — avoid `transition-all`.
- If you cannot find where `ProfilePage` is mounted, grep `frontend/src` for `<ProfilePage` and `onStartChat`.
- Recharts type errors with React 19: pass `data` as `any[]` (already the convention in this file).

Ship it.
