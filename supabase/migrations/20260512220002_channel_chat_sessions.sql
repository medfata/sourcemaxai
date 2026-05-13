create table public.chat_sessions (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  channel_id uuid not null,
  title text not null default 'New chat',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint chat_sessions_channel_owner_fkey
    foreign key (owner_id, channel_id)
    references public.channels(owner_id, id)
    on delete cascade,
  constraint chat_sessions_owner_channel_id_id_key unique (owner_id, channel_id, id),
  constraint chat_sessions_title_not_blank check (length(btrim(title)) > 0)
);

create table public.chat_messages (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  channel_id uuid not null,
  session_id uuid not null,
  role text not null,
  content text not null,
  sources jsonb not null default '[]'::jsonb,
  unknown_source_ids text[] not null default '{}',
  sequence int not null,
  created_at timestamptz not null default now(),
  constraint chat_messages_session_owner_fkey
    foreign key (owner_id, channel_id, session_id)
    references public.chat_sessions(owner_id, channel_id, id)
    on delete cascade,
  constraint chat_messages_role_check check (role in ('user', 'assistant')),
  constraint chat_messages_content_not_blank check (length(btrim(content)) > 0),
  constraint chat_messages_sources_array check (jsonb_typeof(sources) = 'array'),
  constraint chat_messages_sequence_positive check (sequence > 0),
  constraint chat_messages_session_sequence_key unique (session_id, sequence)
);

create index chat_sessions_owner_id_idx on public.chat_sessions (owner_id);
create index chat_sessions_owner_channel_updated_idx
  on public.chat_sessions (owner_id, channel_id, updated_at desc);

create index chat_messages_owner_id_idx on public.chat_messages (owner_id);
create index chat_messages_owner_session_sequence_idx
  on public.chat_messages (owner_id, session_id, sequence asc);
create index chat_messages_owner_channel_created_idx
  on public.chat_messages (owner_id, channel_id, created_at desc);

alter table public.chat_sessions enable row level security;
alter table public.chat_messages enable row level security;

create policy "Users can read own chat sessions"
on public.chat_sessions for select
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can insert own chat sessions"
on public.chat_sessions for insert
to authenticated
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can update own chat sessions"
on public.chat_sessions for update
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()))
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can delete own chat sessions"
on public.chat_sessions for delete
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can read own chat messages"
on public.chat_messages for select
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can insert own chat messages"
on public.chat_messages for insert
to authenticated
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can update own chat messages"
on public.chat_messages for update
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()))
with check ((select auth.uid()) is not null and owner_id = (select auth.uid()));

create policy "Users can delete own chat messages"
on public.chat_messages for delete
to authenticated
using ((select auth.uid()) is not null and owner_id = (select auth.uid()));

revoke all on table public.chat_sessions, public.chat_messages from public, anon;

grant select, insert, update, delete on table
  public.chat_sessions,
  public.chat_messages
to authenticated;

grant all on table
  public.chat_sessions,
  public.chat_messages
to service_role;

create trigger chat_sessions_set_updated_at
before update on public.chat_sessions
for each row
execute function private.set_updated_at();
