-- Public launch waitlist entries are written by the backend with the
-- service role key. Browser clients should not read or write this table.

create table public.waitlist_entries (
  id uuid primary key default gen_random_uuid(),
  email text not null,
  normalized_email text not null,
  youtube_channel text,
  transcript_minutes int not null default 1000,
  source text not null default 'waitlist_page',
  user_agent text,
  referrer text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint waitlist_entries_email_not_blank check (length(btrim(email)) > 0),
  constraint waitlist_entries_email_has_at check (position('@' in email) > 1),
  constraint waitlist_entries_normalized_email_matches check (normalized_email = lower(btrim(email))),
  constraint waitlist_entries_normalized_email_unique unique (normalized_email),
  constraint waitlist_entries_transcript_minutes_positive check (transcript_minutes > 0),
  constraint waitlist_entries_source_not_blank check (length(btrim(source)) > 0)
);

create index waitlist_entries_created_at_idx on public.waitlist_entries (created_at desc);

create trigger waitlist_entries_set_updated_at
before update on public.waitlist_entries
for each row
execute function private.set_updated_at();

alter table public.waitlist_entries enable row level security;

revoke all on table public.waitlist_entries from public, anon, authenticated;
grant all on table public.waitlist_entries to service_role;
