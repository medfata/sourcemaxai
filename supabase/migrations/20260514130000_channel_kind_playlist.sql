-- Add channel kind + playlist scoping fields so a single playlist can be
-- traced as its own dashboard entity (kind='playlist') alongside the owning
-- channel (kind='channel'). Existing rows default to kind='channel'.

alter table public.channels
    add column if not exists kind text not null default 'channel',
    add column if not exists playlist_id text,
    add column if not exists playlist_title text,
    add column if not exists owner_channel_id text,
    add column if not exists owner_channel_name text;

alter table public.channels
    drop constraint if exists channels_kind_check;

alter table public.channels
    add constraint channels_kind_check
        check (kind in ('channel', 'playlist'));

alter table public.channels
    drop constraint if exists channels_playlist_id_when_playlist;

alter table public.channels
    add constraint channels_playlist_id_when_playlist
        check (kind <> 'playlist' or (playlist_id is not null and length(btrim(playlist_id)) > 0));
