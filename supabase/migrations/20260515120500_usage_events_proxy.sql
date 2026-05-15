-- P2.2: per-user proxy bandwidth tracking on usage_events.
--
-- Spec: PLAN_PROXY_TRANSCRIPT.md §2.2. After each transcript fetch through the
-- proxy pool, the worker records proxy_bytes (request + response byte estimate)
-- and proxy_provider ('iproyal' | 'webshare' | 'ytdlp') so quotas.py can enforce
-- per-user monthly proxy bandwidth and per-minute rate ceilings.
--
-- Index note: the per-minute rate check in P2.4 counts last-60s rows by
-- (owner_id, event_type, created_at desc). That exact index already exists from
-- 20260507201920_phase_6_quotas_usage.sql as `usage_events_owner_event_created_at_idx`,
-- so no new index is added here.

alter table public.usage_events
  add column if not exists proxy_bytes bigint not null default 0,
  add column if not exists proxy_provider text;

alter table public.usage_events
  add constraint usage_events_proxy_bytes_nonnegative
  check (proxy_bytes >= 0);

alter table public.usage_events
  add constraint usage_events_proxy_provider_not_blank
  check (proxy_provider is null or length(btrim(proxy_provider)) > 0);
