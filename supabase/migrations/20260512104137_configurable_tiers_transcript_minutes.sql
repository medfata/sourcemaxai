-- Configurable Free/Pro tiers using transcript minutes as the user-facing quota.
--
-- Transcript minutes are counted from processed transcript words, not raw
-- YouTube video duration. Backend code records transcript_seconds on summary
-- usage events and chat_messages on chat usage events.

create table public.plan_tiers (
  tier_key text primary key,
  display_name text not null,
  monthly_transcript_seconds int not null,
  monthly_chat_messages int not null,
  max_transcript_seconds_per_run int not null,
  monthly_token_limit int not null default 1000000,
  monthly_cost_limit_usd numeric not null default 5,
  max_concurrent_runs int not null default 1,
  chat_per_minute_limit int not null default 10,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint plan_tiers_tier_key_not_blank check (length(btrim(tier_key)) > 0),
  constraint plan_tiers_display_name_not_blank check (length(btrim(display_name)) > 0),
  constraint plan_tiers_monthly_transcript_seconds_nonnegative check (monthly_transcript_seconds >= 0),
  constraint plan_tiers_monthly_chat_messages_nonnegative check (monthly_chat_messages >= 0),
  constraint plan_tiers_max_transcript_seconds_per_run_nonnegative check (max_transcript_seconds_per_run >= 0),
  constraint plan_tiers_monthly_token_limit_nonnegative check (monthly_token_limit >= 0),
  constraint plan_tiers_monthly_cost_limit_nonnegative check (monthly_cost_limit_usd >= 0),
  constraint plan_tiers_max_concurrent_runs_positive check (max_concurrent_runs >= 1),
  constraint plan_tiers_chat_per_minute_limit_nonnegative check (chat_per_minute_limit >= 0)
);

create trigger plan_tiers_set_updated_at
before update on public.plan_tiers
for each row
execute function private.set_updated_at();

insert into public.plan_tiers (
  tier_key,
  display_name,
  monthly_transcript_seconds,
  monthly_chat_messages,
  max_transcript_seconds_per_run,
  monthly_token_limit,
  monthly_cost_limit_usd,
  max_concurrent_runs,
  chat_per_minute_limit
)
values
  ('free', 'Free', 9000, 20, 1800, 1000000, 5, 1, 10),
  ('pro', 'Pro', 60000, 500, 10800, 5000000, 20, 2, 20)
on conflict (tier_key) do update
set
  display_name = excluded.display_name,
  monthly_transcript_seconds = excluded.monthly_transcript_seconds,
  monthly_chat_messages = excluded.monthly_chat_messages,
  max_transcript_seconds_per_run = excluded.max_transcript_seconds_per_run,
  monthly_token_limit = excluded.monthly_token_limit,
  monthly_cost_limit_usd = excluded.monthly_cost_limit_usd,
  max_concurrent_runs = excluded.max_concurrent_runs,
  chat_per_minute_limit = excluded.chat_per_minute_limit;

alter table public.plan_tiers enable row level security;

create policy "Authenticated users can read plan tiers"
on public.plan_tiers for select
to authenticated
using (true);

revoke all on table public.plan_tiers from public, anon;
grant select on public.plan_tiers to authenticated;
grant all on table public.plan_tiers to service_role;

alter table public.user_quotas
add column if not exists tier_key text not null default 'free'
references public.plan_tiers(tier_key);

create index if not exists user_quotas_tier_key_idx on public.user_quotas (tier_key);

alter table public.usage_events
add column if not exists transcript_seconds int not null default 0,
add column if not exists chat_messages int not null default 0;

alter table public.usage_events
add constraint usage_events_transcript_seconds_nonnegative
check (transcript_seconds >= 0);

alter table public.usage_events
add constraint usage_events_chat_messages_nonnegative
check (chat_messages >= 0);

create index if not exists usage_events_owner_event_transcript_idx
  on public.usage_events (owner_id, event_type, created_at desc)
  where transcript_seconds > 0 or chat_messages > 0;

create table public.user_credit_grants (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  source text not null default 'waitlist',
  transcript_seconds int not null,
  remaining_transcript_seconds int not null,
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  constraint user_credit_grants_source_not_blank check (length(btrim(source)) > 0),
  constraint user_credit_grants_transcript_seconds_positive check (transcript_seconds > 0),
  constraint user_credit_grants_remaining_transcript_seconds_nonnegative check (remaining_transcript_seconds >= 0),
  constraint user_credit_grants_remaining_not_above_original check (remaining_transcript_seconds <= transcript_seconds)
);

create index user_credit_grants_owner_id_idx on public.user_credit_grants (owner_id);
create index user_credit_grants_owner_active_idx
  on public.user_credit_grants (owner_id, expires_at)
  where remaining_transcript_seconds > 0;

alter table public.user_credit_grants enable row level security;

create policy "Users can read own credit grants"
on public.user_credit_grants for select
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

revoke all on table public.user_credit_grants from public, anon;
grant select on public.user_credit_grants to authenticated;
grant all on table public.user_credit_grants to service_role;
