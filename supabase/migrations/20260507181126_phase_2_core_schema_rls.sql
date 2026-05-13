create extension if not exists pgcrypto with schema extensions;

create schema if not exists private;
revoke all on schema private from public;

create table public.app_users (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  created_at timestamptz not null default now(),
  constraint app_users_email_not_blank check (email is null or length(btrim(email)) > 0)
);

create table public.channels (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  youtube_channel_id text not null,
  channel_name text not null,
  channel_handle text,
  avatar_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint channels_owner_id_id_key unique (owner_id, id),
  constraint channels_owner_youtube_channel_id_key unique (owner_id, youtube_channel_id),
  constraint channels_youtube_channel_id_not_blank check (length(btrim(youtube_channel_id)) > 0),
  constraint channels_channel_name_not_blank check (length(btrim(channel_name)) > 0),
  constraint channels_channel_handle_not_blank check (channel_handle is null or length(btrim(channel_handle)) > 0)
);

create table public.videos (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  channel_id uuid not null,
  youtube_video_id text not null,
  title text not null,
  upload_date text,
  duration int not null default 0,
  view_count bigint not null default 0,
  thumbnail text,
  is_short boolean not null default false,
  constraint videos_channel_owner_fkey
    foreign key (owner_id, channel_id)
    references public.channels(owner_id, id)
    on delete cascade,
  constraint videos_channel_youtube_video_id_key unique (channel_id, youtube_video_id),
  constraint videos_owner_channel_id_id_key unique (owner_id, channel_id, id),
  constraint videos_youtube_video_id_not_blank check (length(btrim(youtube_video_id)) > 0),
  constraint videos_title_not_blank check (length(btrim(title)) > 0),
  constraint videos_duration_nonnegative check (duration >= 0),
  constraint videos_view_count_nonnegative check (view_count >= 0)
);

create table public.video_selections (
  owner_id uuid not null references auth.users(id) on delete cascade,
  channel_id uuid not null,
  video_id uuid not null,
  selected boolean not null default true,
  constraint video_selections_pkey primary key (channel_id, video_id),
  constraint video_selections_channel_owner_fkey
    foreign key (owner_id, channel_id)
    references public.channels(owner_id, id)
    on delete cascade,
  constraint video_selections_video_owner_fkey
    foreign key (owner_id, channel_id, video_id)
    references public.videos(owner_id, channel_id, id)
    on delete cascade
);

create table public.pipeline_runs (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  channel_id uuid not null,
  status text not null default 'queued',
  current_stage text,
  started_at timestamptz,
  completed_at timestamptz,
  error text,
  estimated_cost_usd numeric not null default 0,
  actual_cost_usd numeric not null default 0,
  created_at timestamptz not null default now(),
  constraint pipeline_runs_channel_owner_fkey
    foreign key (owner_id, channel_id)
    references public.channels(owner_id, id)
    on delete cascade,
  constraint pipeline_runs_owner_id_id_key unique (owner_id, id),
  constraint pipeline_runs_owner_channel_id_id_key unique (owner_id, channel_id, id),
  constraint pipeline_runs_status_check
    check (status in ('queued', 'running', 'completed', 'failed', 'cancelled', 'cancel_requested')),
  constraint pipeline_runs_current_stage_not_blank
    check (current_stage is null or length(btrim(current_stage)) > 0),
  constraint pipeline_runs_estimated_cost_nonnegative check (estimated_cost_usd >= 0),
  constraint pipeline_runs_actual_cost_nonnegative check (actual_cost_usd >= 0),
  constraint pipeline_runs_completed_after_started
    check (completed_at is null or started_at is null or completed_at >= started_at)
);

create table public.pipeline_run_videos (
  run_id uuid not null,
  owner_id uuid not null references auth.users(id) on delete cascade,
  channel_id uuid not null,
  video_id uuid not null,
  transcript_status text not null default 'queued',
  chunk_status text not null default 'queued',
  summary_status text not null default 'queued',
  error text,
  summary_confidence numeric,
  evidence_rate numeric,
  constraint pipeline_run_videos_pkey primary key (run_id, video_id),
  constraint pipeline_run_videos_run_owner_fkey
    foreign key (owner_id, channel_id, run_id)
    references public.pipeline_runs(owner_id, channel_id, id)
    on delete cascade,
  constraint pipeline_run_videos_video_owner_fkey
    foreign key (owner_id, channel_id, video_id)
    references public.videos(owner_id, channel_id, id)
    on delete cascade,
  constraint pipeline_run_videos_transcript_status_check
    check (transcript_status in ('queued', 'running', 'completed', 'failed', 'skipped', 'unavailable')),
  constraint pipeline_run_videos_chunk_status_check
    check (chunk_status in ('queued', 'running', 'completed', 'failed', 'skipped')),
  constraint pipeline_run_videos_summary_status_check
    check (summary_status in ('queued', 'running', 'completed', 'failed', 'skipped')),
  constraint pipeline_run_videos_summary_confidence_range
    check (summary_confidence is null or (summary_confidence >= 0 and summary_confidence <= 1)),
  constraint pipeline_run_videos_evidence_rate_range
    check (evidence_rate is null or (evidence_rate >= 0 and evidence_rate <= 1))
);

create table public.caption_chunks (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  channel_id uuid not null,
  video_id uuid not null,
  chunk_id text not null,
  start_seconds numeric not null,
  end_seconds numeric,
  text text not null,
  created_at timestamptz not null default now(),
  constraint caption_chunks_video_owner_fkey
    foreign key (owner_id, channel_id, video_id)
    references public.videos(owner_id, channel_id, id)
    on delete cascade,
  constraint caption_chunks_channel_chunk_id_key unique (channel_id, chunk_id),
  constraint caption_chunks_chunk_id_not_blank check (length(btrim(chunk_id)) > 0),
  constraint caption_chunks_start_seconds_nonnegative check (start_seconds >= 0),
  constraint caption_chunks_end_after_start check (end_seconds is null or end_seconds >= start_seconds),
  constraint caption_chunks_text_not_blank check (length(btrim(text)) > 0)
);

create table public.channel_profiles (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  channel_id uuid not null,
  run_id uuid references public.pipeline_runs(id) on delete set null,
  schema_version int not null,
  profile jsonb not null,
  generated_at timestamptz not null default now(),
  constraint channel_profiles_channel_owner_fkey
    foreign key (owner_id, channel_id)
    references public.channels(owner_id, id)
    on delete cascade,
  constraint channel_profiles_schema_version_positive check (schema_version > 0),
  constraint channel_profiles_profile_object check (jsonb_typeof(profile) = 'object')
);

create table public.artifacts (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  channel_id uuid not null,
  run_id uuid,
  video_id uuid,
  kind text not null,
  schema_version int,
  storage_path text not null,
  hash text,
  created_at timestamptz not null default now(),
  constraint artifacts_channel_owner_fkey
    foreign key (owner_id, channel_id)
    references public.channels(owner_id, id)
    on delete cascade,
  constraint artifacts_run_owner_fkey
    foreign key (owner_id, channel_id, run_id)
    references public.pipeline_runs(owner_id, channel_id, id)
    on delete cascade,
  constraint artifacts_video_owner_fkey
    foreign key (owner_id, channel_id, video_id)
    references public.videos(owner_id, channel_id, id)
    on delete cascade,
  constraint artifacts_storage_path_key unique (storage_path),
  constraint artifacts_kind_check
    check (kind in ('transcript', 'summary', 'profile', 'export', 'profile_snapshot')),
  constraint artifacts_schema_version_positive check (schema_version is null or schema_version > 0),
  constraint artifacts_storage_path_not_blank check (length(btrim(storage_path)) > 0),
  constraint artifacts_hash_not_blank check (hash is null or length(btrim(hash)) > 0)
);

comment on table public.artifacts is
  'Metadata for generated files. Private storage buckets and storage.objects RLS are handled in Phase 3.';

create table public.usage_events (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  run_id uuid references public.pipeline_runs(id) on delete set null,
  event_type text not null,
  model text,
  input_tokens int not null default 0,
  output_tokens int not null default 0,
  cost_usd numeric not null default 0,
  created_at timestamptz not null default now(),
  constraint usage_events_event_type_not_blank check (length(btrim(event_type)) > 0),
  constraint usage_events_model_not_blank check (model is null or length(btrim(model)) > 0),
  constraint usage_events_input_tokens_nonnegative check (input_tokens >= 0),
  constraint usage_events_output_tokens_nonnegative check (output_tokens >= 0),
  constraint usage_events_cost_nonnegative check (cost_usd >= 0)
);

create index channels_owner_id_idx on public.channels (owner_id);
create index channels_owner_created_at_idx on public.channels (owner_id, created_at desc);

create index videos_owner_id_idx on public.videos (owner_id);
create index videos_owner_channel_id_idx on public.videos (owner_id, channel_id);
create index videos_owner_channel_upload_date_idx on public.videos (owner_id, channel_id, upload_date desc);
create index videos_youtube_video_id_idx on public.videos (youtube_video_id);

create index video_selections_owner_id_idx on public.video_selections (owner_id);
create index video_selections_owner_channel_video_idx on public.video_selections (owner_id, channel_id, video_id);

create index pipeline_runs_owner_id_idx on public.pipeline_runs (owner_id);
create index pipeline_runs_owner_channel_created_at_idx on public.pipeline_runs (owner_id, channel_id, created_at desc);
create index pipeline_runs_active_status_idx
  on public.pipeline_runs (status, created_at)
  where status in ('queued', 'running', 'cancel_requested');

create index pipeline_run_videos_owner_id_idx on public.pipeline_run_videos (owner_id);
create index pipeline_run_videos_owner_run_idx on public.pipeline_run_videos (owner_id, run_id);
create index pipeline_run_videos_owner_channel_video_idx on public.pipeline_run_videos (owner_id, channel_id, video_id);
create index pipeline_run_videos_summary_status_idx on public.pipeline_run_videos (owner_id, run_id, summary_status);

create index caption_chunks_owner_id_idx on public.caption_chunks (owner_id);
create index caption_chunks_owner_channel_video_idx on public.caption_chunks (owner_id, channel_id, video_id);
create index caption_chunks_owner_video_start_idx on public.caption_chunks (owner_id, video_id, start_seconds);

create index channel_profiles_owner_id_idx on public.channel_profiles (owner_id);
create index channel_profiles_owner_channel_generated_at_idx on public.channel_profiles (owner_id, channel_id, generated_at desc);
create index channel_profiles_run_id_idx on public.channel_profiles (run_id) where run_id is not null;

create index artifacts_owner_id_idx on public.artifacts (owner_id);
create index artifacts_owner_channel_run_kind_idx on public.artifacts (owner_id, channel_id, run_id, kind);
create index artifacts_owner_channel_video_kind_idx on public.artifacts (owner_id, channel_id, video_id, kind) where video_id is not null;
create index artifacts_run_id_idx on public.artifacts (run_id) where run_id is not null;
create index artifacts_video_id_idx on public.artifacts (video_id) where video_id is not null;

create index usage_events_owner_id_idx on public.usage_events (owner_id);
create index usage_events_owner_created_at_idx on public.usage_events (owner_id, created_at desc);
create index usage_events_run_id_idx on public.usage_events (run_id) where run_id is not null;

alter table public.app_users enable row level security;
alter table public.channels enable row level security;
alter table public.videos enable row level security;
alter table public.video_selections enable row level security;
alter table public.pipeline_runs enable row level security;
alter table public.pipeline_run_videos enable row level security;
alter table public.caption_chunks enable row level security;
alter table public.channel_profiles enable row level security;
alter table public.artifacts enable row level security;
alter table public.usage_events enable row level security;

create policy "Users can read own app user"
on public.app_users for select
to authenticated
using ((select auth.uid()) is not null and id = (select auth.uid()));

create policy "Users can read own channels"
on public.channels for select
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can insert own channels"
on public.channels for insert
to authenticated
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can update own channels"
on public.channels for update
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()))
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can delete own channels"
on public.channels for delete
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can read own videos"
on public.videos for select
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can insert own videos"
on public.videos for insert
to authenticated
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can update own videos"
on public.videos for update
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()))
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can delete own videos"
on public.videos for delete
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can read own video selections"
on public.video_selections for select
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can insert own video selections"
on public.video_selections for insert
to authenticated
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can update own video selections"
on public.video_selections for update
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()))
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can delete own video selections"
on public.video_selections for delete
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can read own pipeline runs"
on public.pipeline_runs for select
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can insert own pipeline runs"
on public.pipeline_runs for insert
to authenticated
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can update own pipeline runs"
on public.pipeline_runs for update
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()))
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can delete own pipeline runs"
on public.pipeline_runs for delete
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can read own pipeline run videos"
on public.pipeline_run_videos for select
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can insert own pipeline run videos"
on public.pipeline_run_videos for insert
to authenticated
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can update own pipeline run videos"
on public.pipeline_run_videos for update
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()))
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can delete own pipeline run videos"
on public.pipeline_run_videos for delete
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can read own caption chunks"
on public.caption_chunks for select
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can insert own caption chunks"
on public.caption_chunks for insert
to authenticated
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can update own caption chunks"
on public.caption_chunks for update
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()))
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can delete own caption chunks"
on public.caption_chunks for delete
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can read own channel profiles"
on public.channel_profiles for select
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can insert own channel profiles"
on public.channel_profiles for insert
to authenticated
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can update own channel profiles"
on public.channel_profiles for update
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()))
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can delete own channel profiles"
on public.channel_profiles for delete
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can read own artifacts"
on public.artifacts for select
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can insert own artifacts"
on public.artifacts for insert
to authenticated
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can update own artifacts"
on public.artifacts for update
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()))
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can delete own artifacts"
on public.artifacts for delete
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can read own usage events"
on public.usage_events for select
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can insert own usage events"
on public.usage_events for insert
to authenticated
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

revoke all on table
  public.app_users,
  public.channels,
  public.videos,
  public.video_selections,
  public.pipeline_runs,
  public.pipeline_run_videos,
  public.caption_chunks,
  public.channel_profiles,
  public.artifacts,
  public.usage_events
from public, anon;

grant select on public.app_users to authenticated;

grant select, insert, update, delete on table
  public.channels,
  public.videos,
  public.video_selections,
  public.pipeline_runs,
  public.pipeline_run_videos,
  public.caption_chunks,
  public.channel_profiles,
  public.artifacts
to authenticated;

grant select, insert on public.usage_events to authenticated;

grant all on table
  public.app_users,
  public.channels,
  public.videos,
  public.video_selections,
  public.pipeline_runs,
  public.pipeline_run_videos,
  public.caption_chunks,
  public.channel_profiles,
  public.artifacts,
  public.usage_events
to service_role;

create or replace function private.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

revoke all on function private.set_updated_at() from public;

create trigger channels_set_updated_at
before update on public.channels
for each row
execute function private.set_updated_at();

create or replace function private.sync_auth_user_to_app_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.app_users (id, email)
  values (new.id, new.email)
  on conflict (id) do update
    set email = excluded.email;

  return new;
end;
$$;

revoke all on function private.sync_auth_user_to_app_user() from public;

drop trigger if exists on_auth_user_sync_app_user on auth.users;
create trigger on_auth_user_sync_app_user
after insert or update of email on auth.users
for each row
execute function private.sync_auth_user_to_app_user();

insert into public.app_users (id, email)
select id, email
from auth.users
on conflict (id) do update
  set email = excluded.email;
