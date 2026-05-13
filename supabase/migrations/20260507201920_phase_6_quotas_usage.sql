-- Phase 6: per-user quotas, usage ledger indexing, and chat rate limit support.
--
-- The MVP enforces hard ceilings on monthly video count, monthly token count,
-- monthly model spend, and concurrent runs per user. usage_events already
-- exists; we add an index to support sliding-window chat rate limits and a
-- per-user quota row table seeded from the same auth.users source as app_users.

create table public.user_quotas (
  owner_id uuid primary key references auth.users(id) on delete cascade,
  monthly_video_limit int not null default 100,
  monthly_token_limit int not null default 1000000,
  monthly_cost_limit_usd numeric not null default 5,
  max_concurrent_runs int not null default 1,
  chat_per_minute_limit int not null default 10,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint user_quotas_monthly_video_limit_nonnegative check (monthly_video_limit >= 0),
  constraint user_quotas_monthly_token_limit_nonnegative check (monthly_token_limit >= 0),
  constraint user_quotas_monthly_cost_limit_nonnegative check (monthly_cost_limit_usd >= 0),
  constraint user_quotas_max_concurrent_runs_positive check (max_concurrent_runs >= 1),
  constraint user_quotas_chat_per_minute_limit_nonnegative check (chat_per_minute_limit >= 0)
);

create index user_quotas_owner_id_idx on public.user_quotas (owner_id);

create trigger user_quotas_set_updated_at
before update on public.user_quotas
for each row
execute function private.set_updated_at();

alter table public.user_quotas enable row level security;

create policy "Users can read own quota"
on public.user_quotas for select
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

revoke all on table public.user_quotas from public, anon;
grant select on public.user_quotas to authenticated;
grant all on table public.user_quotas to service_role;

create or replace function private.sync_auth_user_to_quota()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.user_quotas (owner_id)
  values (new.id)
  on conflict (owner_id) do nothing;
  return new;
end;
$$;

revoke all on function private.sync_auth_user_to_quota() from public;

drop trigger if exists on_auth_user_sync_quota on auth.users;
create trigger on_auth_user_sync_quota
after insert on auth.users
for each row
execute function private.sync_auth_user_to_quota();

insert into public.user_quotas (owner_id)
select id from auth.users
on conflict (owner_id) do nothing;

-- Sliding-window chat rate limit reads usage_events filtered by event_type.
create index if not exists usage_events_owner_event_created_at_idx
  on public.usage_events (owner_id, event_type, created_at desc);
