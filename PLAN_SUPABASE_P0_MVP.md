# Plan: Supabase P0 MVP Readiness

## Goal

Move Trace from a local-only research tool to a deployable MVP for real users by adding:

- Supabase Auth and per-user isolation.
- Supabase Postgres for durable app state.
- Supabase Storage for generated artifacts.
- Durable pipeline runs and resumable workers.
- Cost, quota, and abuse controls.
- User-facing delete, refresh, retry, and export workflows.
- Deployment and CI readiness.

This plan focuses on P0 production requirements. Product expansion features like comparison mode, scheduled digests, and advanced search can come after this foundation is stable.

## Target Architecture

Keep the current FastAPI backend and Python pipeline worker. Use Supabase as the durable control plane.

- Frontend: React app with Supabase Auth session handling.
- Backend API: FastAPI, validates Supabase JWTs on every app endpoint.
- Worker: Python process for YouTube fetching, transcript fetching, chunking, summarization, profile aggregation, and retrieval indexing.
- Supabase Auth: user identity and sessions.
- Supabase Postgres: users' channels, videos, selections, pipeline runs, per-video statuses, caption chunks, profile metadata, and usage ledger.
- Supabase Storage: transcript JSON, summary JSON, profile snapshots, and exports.

Do not move heavy `yt-dlp`, transcript, or LLM pipeline work into Supabase Edge Functions. Keep those jobs in Python workers.

## Phase 1: Auth And Backend JWT Guard

Add Supabase Auth to the frontend and require authentication for all app APIs.

Tasks:

- Install `@supabase/supabase-js`.
- Add login, signup, logout, and session restore screens.
- Attach `Authorization: Bearer <access_token>` to every `/api/*` request.
- Add a FastAPI auth dependency, for example `get_current_user`.
- Verify Supabase JWTs server-side.
- Derive `owner_id` only from the verified token. Never trust a user ID from request bodies.

Protect these routes:

```txt
POST /api/channel
GET  /api/videos
POST /api/videos/select
GET  /api/selection
GET  /api/playlists
GET  /api/playlists/videos
POST /api/pipeline/start
POST /api/pipeline/cancel
POST /api/pipeline/resume
GET  /api/pipeline/state
GET  /api/pipeline/stream
GET  /api/profile
POST /api/chat
```

Acceptance:

- Anonymous users cannot call app APIs.
- User A cannot access User B's channel, profile, run, or artifacts by guessing IDs.
- Sign-out clears frontend app state.

## Phase 2: Supabase Schema And RLS

Create the initial durable data model in Postgres. Enable RLS on every exposed table.

Core tables:

```sql
app_users (
  id uuid primary key references auth.users(id),
  email text,
  created_at timestamptz default now()
);

channels (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id),
  youtube_channel_id text not null,
  channel_name text not null,
  channel_handle text,
  avatar_url text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

videos (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id),
  channel_id uuid not null references channels(id) on delete cascade,
  youtube_video_id text not null,
  title text not null,
  upload_date text,
  duration int default 0,
  view_count bigint default 0,
  thumbnail text,
  is_short boolean default false,
  unique(channel_id, youtube_video_id)
);

video_selections (
  owner_id uuid not null references auth.users(id),
  channel_id uuid not null references channels(id) on delete cascade,
  video_id uuid not null references videos(id) on delete cascade,
  selected boolean not null default true,
  primary key(channel_id, video_id)
);

pipeline_runs (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id),
  channel_id uuid not null references channels(id) on delete cascade,
  status text not null,
  current_stage text,
  started_at timestamptz,
  completed_at timestamptz,
  error text,
  estimated_cost_usd numeric default 0,
  actual_cost_usd numeric default 0,
  created_at timestamptz default now()
);

pipeline_run_videos (
  run_id uuid not null references pipeline_runs(id) on delete cascade,
  owner_id uuid not null references auth.users(id),
  channel_id uuid not null references channels(id) on delete cascade,
  video_id uuid not null references videos(id) on delete cascade,
  transcript_status text default 'queued',
  chunk_status text default 'queued',
  summary_status text default 'queued',
  error text,
  summary_confidence numeric,
  evidence_rate numeric,
  primary key(run_id, video_id)
);

caption_chunks (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id),
  channel_id uuid not null references channels(id) on delete cascade,
  video_id uuid not null references videos(id) on delete cascade,
  chunk_id text not null,
  start_seconds numeric not null,
  end_seconds numeric,
  text text not null,
  created_at timestamptz default now(),
  unique(channel_id, chunk_id)
);

channel_profiles (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id),
  channel_id uuid not null references channels(id) on delete cascade,
  run_id uuid references pipeline_runs(id) on delete set null,
  schema_version int not null,
  profile jsonb not null,
  generated_at timestamptz default now()
);

artifacts (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id),
  channel_id uuid not null references channels(id) on delete cascade,
  run_id uuid references pipeline_runs(id) on delete cascade,
  video_id uuid references videos(id) on delete cascade,
  kind text not null,
  schema_version int,
  storage_path text not null,
  hash text,
  created_at timestamptz default now()
);

usage_events (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id),
  run_id uuid references pipeline_runs(id) on delete set null,
  event_type text not null,
  model text,
  input_tokens int default 0,
  output_tokens int default 0,
  cost_usd numeric default 0,
  created_at timestamptz default now()
);
```

RLS policy pattern:

```sql
alter table channels enable row level security;

create policy "Users can read own channels"
on channels for select
to authenticated
using (auth.uid() is not null and owner_id = auth.uid());
```

For MVP, add `owner_id` directly to child tables. That keeps policies simple and avoids expensive joins inside RLS.

Acceptance:

- All exposed tables have RLS enabled.
- Each table has owner-scoped select/insert/update/delete policies where needed.
- No policy uses user-editable metadata for authorization.

## Phase 3: Private Supabase Storage

Create private buckets:

```txt
channel-artifacts
exports
```

Use deterministic storage paths:

```txt
{owner_id}/{channel_id}/{run_id}/transcripts/{video_id}.json
{owner_id}/{channel_id}/{run_id}/summaries/{video_id}.json
{owner_id}/{channel_id}/{run_id}/profile.json
{owner_id}/{channel_id}/exports/{export_id}.md
```

Rules:

- Backend writes artifacts using the service role key.
- Frontend never receives the service role key.
- Frontend reads artifacts through signed URLs or backend proxy endpoints.
- Store metadata for each object in the `artifacts` table.

Acceptance:

- User A cannot read User B's artifact path.
- Backend can write transcripts, summaries, profiles, and exports.
- Deleting a channel removes or orphan-cleans related storage objects.

## Phase 4: Storage Adapter Refactor

Do not rewrite all pipeline code in one pass. Add a storage abstraction around the current `backend/storage.py` behavior.

Interface:

```python
class StorageBackend:
    def load_channel_meta(self, owner_id: str, channel_id: str): ...
    def save_channel_meta(self, owner_id: str, data: dict): ...
    def load_videos(self, owner_id: str, channel_id: str): ...
    def save_videos(self, owner_id: str, channel_id: str, videos: list[dict]): ...
    def load_selection(self, owner_id: str, channel_id: str): ...
    def save_selection(self, owner_id: str, channel_id: str, video_ids: list[str]): ...
    def load_transcript(self, owner_id: str, channel_id: str, video_id: str): ...
    def save_transcript(self, owner_id: str, channel_id: str, run_id: str, video_id: str, data: dict): ...
    def load_summary(self, owner_id: str, channel_id: str, video_id: str): ...
    def save_summary(self, owner_id: str, channel_id: str, run_id: str, video_id: str, data: dict): ...
    def load_profile(self, owner_id: str, channel_id: str): ...
    def save_profile(self, owner_id: str, channel_id: str, run_id: str, data: dict): ...
```

Implement:

```txt
LocalStorageBackend
SupabaseStorageBackend
```

Use env:

```txt
STORAGE_BACKEND=local|supabase
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_PUBLISHABLE_KEY=
```

Migration order:

1. Channel metadata and videos to Postgres.
2. Selection to Postgres.
3. Pipeline state to Postgres.
4. Transcript, summary, profile artifacts to Storage.
5. Caption chunks to Postgres for retrieval.

Acceptance:

- Local mode still works.
- Supabase mode persists state across backend restarts.
- Pipeline code calls the adapter rather than raw filesystem helpers.

## Phase 5: Durable Pipeline Runs

Replace in-memory task state with DB-backed run state.

Current in-memory state:

- `running_tasks`
- `sse_queues`
- `pipeline_state.json`

New flow:

1. `POST /api/pipeline/start`
   - Creates `pipeline_runs` row.
   - Creates `pipeline_run_videos` rows.
   - Marks run `queued`.

2. Worker loop
   - Claims one queued run.
   - Marks it `running`.
   - Updates current stage.
   - Updates per-video statuses.
   - Writes artifacts and chunks.
   - Marks run `completed`, `failed`, or `cancelled`.

3. UI progress
   - Keep FastAPI SSE initially.
   - SSE reads and streams DB state.
   - Later, consider Supabase Realtime.

Simple MVP worker claim:

```sql
update pipeline_runs
set status = 'running', started_at = coalesce(started_at, now())
where id = (
  select id
  from pipeline_runs
  where status = 'queued'
  order by created_at
  limit 1
  for update skip locked
)
returning *;
```

Acceptance:

- If the backend restarts, run state is still present.
- If the worker restarts, queued or running jobs can resume or become retryable.
- Cancel persists in DB and the worker respects it.
- Refreshing the browser restores true pipeline state.

## Phase 6: Quotas, Cost, And Abuse Controls

Add account-level limits before public launch.

Tables:

```sql
user_quotas (
  owner_id uuid primary key references auth.users(id),
  monthly_video_limit int not null default 300,
  monthly_token_limit int not null default 1000000,
  monthly_cost_limit_usd numeric not null default 5,
  max_concurrent_runs int not null default 1
);
```

Rules:

- Estimate cost before summaries.
- Block pipeline start if selected videos exceed quota.
- Block or require confirmation when estimated cost exceeds remaining budget.
- Track actual usage in `usage_events`.
- Rate-limit chat by user.
- Prevent multiple concurrent runs per user.

MVP defaults:

```txt
max selected videos: 100-300
max concurrent runs per user: 1
monthly free cost cap: configurable
chat rate limit: configurable per user
```

Acceptance:

- A user cannot accidentally launch unlimited expensive jobs.
- Every model call records usage.
- The UI shows estimated remaining budget before paid stages.

## Phase 7: User Data Controls

Add the operational controls real users expect.

Features:

- Channel dashboard.
- Delete channel/profile/run.
- Retry failed videos only.
- Rebuild stale generated files.
- Refresh channel video catalog.
- Export profile and selected Q&A as Markdown.

Minimum endpoints:

```txt
GET    /api/channels
DELETE /api/channels/:id
POST   /api/channels/:id/refresh
POST   /api/pipeline/:run_id/retry-failed
POST   /api/channels/:id/export/markdown
```

Acceptance:

- User can delete a channel and all associated DB rows/artifacts.
- User can rerun only failed work.
- User can refresh a channel to discover new videos.
- User can export a useful Markdown report.

## Phase 8: Deployment And CI

Before deploy:

- Dockerfile for backend API.
- Separate worker process.
- Separate frontend build/deploy.
- Startup env validation.
- Health and readiness endpoints.
- Structured logs.
- Error reporting.

CI checks:

```txt
frontend: npm run build
frontend: npm run lint
backend: pytest
backend: ruff check
```

Current known blockers:

- `npm run build` passes.
- `npm run lint` passes after narrowing lint to `src` and ignoring cache/build folders.
- Backend tests did not run locally because this environment resolves `python.exe` to a broken WindowsApps stub.

Phase 8 progress:

- Added backend API Dockerfile.
- Added standalone worker entrypoint: `python -m backend.worker`.
- Added separate frontend Dockerfile and static nginx config.
- Added startup/runtime env validation and public `/api/ready`.
- Added public `/api/health` liveness check remains unchanged.
- Added structured request/error logging and optional Sentry initialization.
- Added GitHub Actions CI for frontend build/lint and backend ruff/pytest.
- Added `.env.example`, `frontend/.env.example`, and deployment docs.

Acceptance:

- CI runs cleanly on a normal environment.
- Backend, frontend, and worker can be deployed independently.
- Secrets are supplied through deployment environment variables.

## Recommended Implementation Order

1. Auth and backend JWT guard.
2. Supabase schema and RLS.
3. Channel, videos, and selections in Postgres.
4. Pipeline runs and per-video status in Postgres.
5. Artifacts in Supabase Storage.
6. Worker resume, cancel, and retry.
7. Caption chunks in Postgres retrieval.
8. Quotas and usage ledger.
9. Delete, refresh, retry, and export UX.
10. Deployment and CI hardening.

## Non-Goals For This P0 Plan

- Multi-channel comparison.
- Scheduled digests.
- Payments/subscriptions.
- Full PDF export.
- Hosted vector database.
- Whisper retranscription.
- Admin dashboard beyond basic database inspection.

## Supabase Notes

- Enable RLS on every table in exposed schemas.
- Use `auth.uid()` in policies and explicitly check it is not null.
- Do not use user-editable metadata for authorization.
- Keep service role keys server-only.
- Storage permissions are controlled with RLS policies on `storage.objects`.
- Supabase Queues are a good later upgrade for durable job delivery.
- Supabase Edge Functions are useful for short orchestration and webhooks, not the heavy YouTube/model pipeline.

References:

- https://supabase.com/docs/guides/auth
- https://supabase.com/docs/guides/database/postgres/row-level-security
- https://supabase.com/docs/guides/storage/security/access-control
- https://supabase.com/docs/guides/functions
- https://supabase.com/docs/guides/queues
