-- Phase 3: private Storage buckets for generated artifacts and exports.
-- Object paths are deterministic and begin with the owning auth user id:
-- {owner_id}/{channel_id}/{run_id}/...
--
-- The backend writes these objects with the server-only service role key, which
-- bypasses RLS. Frontend reads should go through signed URLs or backend proxy
-- endpoints, so this migration intentionally grants only owner-scoped SELECT
-- access to authenticated users and no client-side insert/update/delete access.

insert into storage.buckets (id, name, "public")
values
  ('channel-artifacts', 'channel-artifacts', false),
  ('exports', 'exports', false)
on conflict (id) do update
set
  name = excluded.name,
  "public" = false;

drop policy if exists "Authenticated users can read own private storage objects"
on storage.objects;

create policy "Authenticated users can read own private storage objects"
on storage.objects
for select
to authenticated
using (
  bucket_id in ('channel-artifacts', 'exports')
  and (select auth.uid()) is not null
  and (storage.foldername(name))[1] = (select auth.uid()::text)
);
