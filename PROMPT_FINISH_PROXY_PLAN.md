# Finish PLAN_PROXY_TRANSCRIPT.md — Remaining Tasks

You are picking up the proxy-rotated transcript plan after PRs #9, #10, #11 merged. Repo: `D:\my_projects\ytb-channel-profilor` (Windows, PowerShell).

## Read first

1. `IMPLEMENTATION_STATUS.md` — full task board and coordination contract.
2. `PLAN_PROXY_TRANSCRIPT.md` — design.
3. `CLAUDE.md` — project conventions.
4. After reading, claim each task you start: edit the row to `status = in_progress`, fill `session`, `branch`, `started_at`. Commit + push the claim BEFORE writing implementation code. Mark `done` only after PR merged.

## What's left

Five tasks. P5.2 + P7.2 codeable now. P7.3 → P7.5 are staged rollout — do them in order, one PR per task.

| ID | Task | Deps |
|----|------|------|
| P5.2 | Quota meter component reading `/api/quota/proxy-usage` | P3.4 done |
| P7.2 | Shadow mode: log intended proxy without using it | P7.1 done |
| P7.3 | 10% canary by `owner_id % 10 == 0` | P3.1, P3.2 done |
| P7.4 | Full cutover; monitor 48h | P7.3, P6.1 |
| P7.5 | Remove direct-fetch path from `fetch_transcripts.py` | P7.4 |

---

## P5.2 — Frontend quota meter

**Backend already exists:** `GET /api/quota/proxy-usage` (auth required). Returns:

```json
{
  "ok": true,
  "data": {
    "tier_key": "pro",
    "proxy_bytes_used": 524288000,
    "proxy_bytes_limit": 2147483648,
    "proxy_bytes_remaining": 1623195648,
    "estimated_videos_remaining": 64928
  }
}
```

**Where it goes:** `StudioPage.tsx` header strip, near other usage indicators. If no existing usage strip, put it above the work list in the transcripts view.

**Component spec:**
- File: `frontend/src/components/ProxyQuotaMeter.tsx`
- Self-fetches on mount via existing `api` client (look at how `pipelineStart` is called in `StudioPage.tsx` → same pattern, hit `/api/quota/proxy-usage`).
- Re-fetch when transcripts complete (subscribe to whatever signal `StudioPage` already uses — `statusMap` change, or pass a `refreshKey` prop).
- Skeleton on load. Hide entirely on 401 (anon) or `tier_key === 'free' && limit === 0`.

**Design theme — match existing components** (see `ChannelInputPage.tsx` "Transcript proxy bandwidth" section, `StudioPage.tsx` modal):

- Tailwind. Font: `font-display` for numbers, default sans for labels.
- Card: `rounded-3xl bg-white/60 dark:bg-white/[0.03] backdrop-blur-md border border-black/[0.06] dark:border-white/10 p-5`.
- Heading label: `text-[11px] uppercase tracking-[0.22em] text-ink-400`.
- Number: `text-[28px] font-display tracking-tight text-ink-900 dark:text-cream`.
- Subtext: `text-[13px] text-ink-500 dark:text-white/60`.
- Progress bar:
  - Container: `h-1.5 rounded-full bg-black/[0.06] dark:bg-white/10 overflow-hidden`.
  - Fill: `h-full rounded-full transition-all duration-500`.
  - Color by pct: <70% `bg-emerald-500/80`, 70–90% `bg-amber-500/80`, >90% `bg-red-500/80`.
- Motion: framer-motion `initial={{opacity:0, y:8}} animate={{opacity:1, y:0}} transition={{duration:0.35}}`.

**Display:**

```
TRANSCRIPT BANDWIDTH                    PRO
─────────────────────────────
500 MB / 2 GB                  ~64,928 videos left
████████░░░░░░░░░░░░░░░░░░░░░░  24%
```

**Edge cases:**
- `proxy_bytes_remaining === 0` → meter full red, subtext "Limit reached — upgrade for more". Click → same `proxyQuotaBlocked` modal state lift (or just link to pricing).
- API 5xx → hide silently (do not block UI).

**Types:** add to `frontend/src/types.ts`:
```ts
export type ProxyQuotaUsage = {
  tier_key: string
  proxy_bytes_used: number
  proxy_bytes_limit: number
  proxy_bytes_remaining: number
  estimated_videos_remaining: number
}
```

**API client:** add `getProxyUsage()` method to whatever module owns `pipelineStart` (likely `frontend/src/api.ts` — grep for it). Same auth header pattern.

**Status update:** claim P5.2 with branch `proxy/p5-2-quota-meter`. After merge: status `done`, append PR link.

---

## P7.2 — Shadow mode

**Goal:** log what proxy *would* have been chosen for each fetch, without actually routing through it. Lets you verify pool/breaker logic against real traffic before flipping the kill switch.

**Implementation:**
- New env var `PROXY_POOL_SHADOW=false` (default), wire through `backend/config.py` like `USE_PROXY_POOL`. Update all three env example files.
- In `backend/pipeline/fetch_transcripts.py`:
  - When `USE_PROXY_POOL=false` AND `PROXY_POOL_SHADOW=true`: build the pool anyway, call `pool.acquire(video_id, 1)`, log `{event: "proxy_shadow", video_id, provider, session_id_prefix: session_id[:4]}`, then fetch *without* proxy (direct path).
  - Do NOT call `record_usage` (no real bytes spent).
  - Do NOT mark blocklist (no real proxy hit).
- Honor breaker `is_open` checks anyway and log `proxy_shadow_skipped_open` — verifies breaker state plumbing without affecting traffic.

**Tests:** extend `test_fetch_transcripts.py`. Monkeypatch `_list_transcripts_direct` to succeed, assert log captures shadow event, assert no `record_usage` calls, no `pool.mark_blocked` calls.

**Branch:** `proxy/p7-2-shadow-mode`.

---

## P7.3 — 10% canary

**Gate:** in `fetch_transcripts.py`, when `USE_PROXY_POOL=true`:
- Hash `owner_id` deterministically. Cheap: `int(hashlib.md5(owner_id.encode()).hexdigest()[:8], 16) % 10 == 0` → 10%.
- Outside the 10%: fall through to direct fetch (same path as `USE_PROXY_POOL=false`).
- New env `PROXY_CANARY_PCT=10` (default 0). 0 disables; 100 = full cutover.

**Logging:** every fetch logs `{event: "proxy_routing", owner_id_hash, canary_pct, routed: "proxy"|"direct"}` so you can spot-check the split.

**Tests:** parametrize on hashed owner_ids covering buckets 0..9; assert ~10% routed when pct=10.

**Branch:** `proxy/p7-3-canary`.

**Note:** keep `USE_PROXY_POOL` boolean kill switch. `PROXY_CANARY_PCT=100` + `USE_PROXY_POOL=true` = full cutover.

---

## P7.4 — Full cutover + 48h monitor

**Pure rollout task. No code beyond config flip.** Document in `IMPLEMENTATION_STATUS.md` Decision Log:

1. `PROXY_CANARY_PCT=100` deployed to prod.
2. Monitor for 48h:
   - `proxy_fetch_total{outcome="success"}` rate
   - `proxy_fetch_total{outcome="blocked"}` rate
   - `proxy_circuit_state` per provider
   - `usage_events.proxy_bytes` daily sum vs forecast
   - User-reported transcript failure rate
3. Rollback trigger: success rate < 90% sustained 15 min → `USE_PROXY_POOL=false`, investigate.

**Branch:** `proxy/p7-4-cutover` (just the IMPLEMENTATION_STATUS.md update + decision log entry).

---

## P7.5 — Remove direct-fetch path

**Only after P7.4 stable 48h.**

- Delete `_list_transcripts_direct` from `fetch_transcripts.py`.
- Delete the `if pool is None:` branch in `fetch_single_transcript`.
- Delete `USE_PROXY_POOL` flag (config, env examples).
- Keep `PROXY_CANARY_PCT` — useful for emergency partial rollback.
- Update tests: remove tests for direct-fetch fallback.

**Branch:** `proxy/p7-5-remove-direct`.

---

## Open questions to surface to user (don't decide alone)

Already in plan §Open Questions and status §Open Questions:

1. Webshare $6/mo minimum vs second IPRoyal sub-account for IP diversity.
2. Free-tier proxy quota exhaustion: hard-fail vs queue-and-retry-next-month.
3. Keep yt-dlp tier-2 fallback or drop?

Flag these before P7.4 — answers affect rollout shape.

---

## Workflow per task

1. Read `IMPLEMENTATION_STATUS.md`. Pick top task with deps `done` and status `todo`.
2. Claim row (edit + commit + push).
3. Branch `proxy/<id-slug>`.
4. Implement.
5. Run `python -m pytest backend/tests/` — match baseline pass count (pre-existing failures: auth, pipeline resume, playlists).
6. For frontend: `cd frontend && npm run build` to catch TS errors. Smoke-test in browser if dev server reachable.
7. Open PR. Body: summary, test results, status table delta.
8. After merge: status `done`, append PR link, append Decision Log if any non-obvious choices made.

## Style reminders (from CLAUDE.md)

- No comments unless WHY non-obvious.
- No backwards-compat shims. Delete unused code.
- Storage layer is sacred — always go through `backend/storage.py`.
- Quota guards in routes, not pipeline.
- Frontend types live in `frontend/src/types.ts`.
- Migration discipline: new files only, never edit applied.
- Trust internal code. Validate at system boundaries only.

Today's date: 2026-05-15. Convert relative dates to absolute in any status/log entries.
