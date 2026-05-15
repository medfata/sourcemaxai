# Trace — YouTube Channel Profiler

## Stack

- **Backend**: FastAPI (Python 3.11+), entrypoint `backend/main.py`. Routes in `backend/routes/`. Pipeline steps in `backend/pipeline/`.
- **Frontend**: React 18 + Vite + TypeScript. Source in `frontend/src/`. Pages in `frontend/src/pages/`, components in `frontend/src/components/`.
- **DB**: Supabase (Postgres + RLS). Migrations in `supabase/migrations/` (timestamped, applied in order).
- **Worker**: standalone process `backend/worker.py` claims durable queue (Supabase). Embedded mode allowed for dev only.
- **Storage abstraction**: `backend/storage.py` switches local-FS vs Supabase via `STORAGE_BACKEND` env. Dual-backend by design — every storage call goes through the abstraction.
- **Quotas**: `backend/quotas.py` — per-user tier limits (`plan_tiers` table), monthly usage tracking (`usage_events`), credit grants.
- **Auth**: Supabase JWT, validated in `backend/auth.py`.
- **Observability**: `backend/observability.py` — structured logging (JSON in prod), error reporting init.

## Run / Test

- Backend dev: `uvicorn backend.main:app --reload`
- Backend tests: `pytest backend/tests/`
- Frontend dev: `cd frontend && npm run dev`
- Worker (when running supabase backend): `python -m backend.worker`
- Type check: `cd frontend && npm run build` (catches TS errors)

## Env Behavior

- `APP_ENV=production` → strict config validation, requires Supabase + MiniMax keys, blocks embedded worker.
- `APP_ENV=development` (default) → relaxed, local FS storage works, embedded worker OK with `ALLOW_LOCAL_SUPABASE_EMBEDDED_WORKER=true`.
- Env templates: `.env.example` (root), `deploy/railway-api.env.example`, `deploy/railway-worker.env.example` — keep all three in sync when adding new vars.

## Pipeline Flow

```
fetch_videos → fetch_transcripts → chunk_transcripts → summarize → aggregate → chat-ready
```

Each step is independently queueable. State persisted in `pipeline_runs` (Supabase). Local file artifacts under `data/channels/{channel_id}/`.

## Active Work — Transcript Reliability

**Current pain**: `youtube-transcript-api` fails on Railway worker IP (cloud-IP block by YouTube). One user's batch can break the queue for all users.

**Active plan**: `PLAN_PROXY_TRANSCRIPT.md` — rotating residential proxies (IPRoyal primary + Webshare fallback), per-user proxy bandwidth quota, global circuit breaker. **This is the next implementation target.**

### Multi-Session Coordination — MANDATORY

`IMPLEMENTATION_STATUS.md` is the shared task board. Multiple Claude sessions may be working this plan in parallel.

Every session, before writing any proxy/transcript code:

1. **Read `IMPLEMENTATION_STATUS.md` end-to-end.**
2. Pick a task whose `status = todo` AND all `depends_on` tasks are `done`.
3. **Claim it**: edit the row to set `status = in_progress`, your session ID, branch name, and `started_at` (today's date in YYYY-MM-DD). Commit and push the claim BEFORE writing implementation code.
4. Skip rows where another session has claimed (`status = in_progress`) unless `started_at` is older than 24h with no commits on that branch (then claim is stale; clear it and reclaim).
5. On PR merge: set `status = done`, append PR link.
6. New design decisions → append to `Decision Log` section.
7. Blocked → append to `Blocker Log` section, then either pivot to another `todo` or stop and surface to user.

If you do not see `IMPLEMENTATION_STATUS.md`, STOP and tell the user — do not invent a plan from scratch.

**Related context** (read before starting transcript work):
- `PLAN_YT_TRANSCRIPT_EXTENSION.md` — Chrome MV3 extension as Tier-1 transcript source (user's own residential IP, $0). Complementary to proxy plan, not conflicting. Final fallback chain: extension → proxy pool → Supadata → Deepgram.
- `TRANSCRIPT_STRATEGY_RESEARCH.md` — comparison matrix of all transcript options, why CORS blocks pure client-side, why YouTube Data API doesn't work, vendor pricing.

## Coding Style

- **No comments unless WHY non-obvious**. Hidden constraint, subtle invariant, workaround for specific bug, surprising behavior. Never narrate WHAT — names already do that.
- **No premature abstraction**. Three similar lines beats a wrong helper. Don't design for hypothetical future requirements.
- **No backwards-compat shims**. If something is unused, delete it. No `// removed` comments, no re-exporting old types.
- **Trust internal code**. Validate at system boundaries (HTTP, external APIs, user input), not between functions you control.
- **No fallbacks for impossible cases**. If a code path can't happen, don't handle it. Let it crash loud.
- **Terse responses**. State results, not deliberation. End-of-turn = one or two sentences max.
- **Match scope to ask**. Bug fix doesn't include surrounding cleanup. One-shot script doesn't need a helper.
- **Storage layer is sacred**. Always go through `backend/storage.py` — never raw `open()` or direct Supabase calls outside that module.
- **Quota guards in routes, not pipeline**. `routes/pipeline.py` calls `check_*` functions before queuing work. Pipeline assumes auth + quota already passed.
- **Migration discipline**. New columns/tables = new timestamped file in `supabase/migrations/`. Never edit applied migrations.
- **Frontend types live in `frontend/src/types.ts`**. Keep in sync with backend Pydantic models in `backend/models.py`.

## Test Conventions

- Pytest, files named `test_*.py` under `backend/tests/`.
- Storage backend in tests defaults to local FS via fixture; Supabase tests use stub or skip.
- New pipeline step → add `test_<step>.py` with happy path + at least one failure mode.
