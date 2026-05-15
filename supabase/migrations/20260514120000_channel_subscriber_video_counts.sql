alter table public.channels
  add column if not exists subscriber_count bigint,
  add column if not exists total_video_count integer;

alter table public.channels
  add constraint channels_subscriber_count_nonnegative
    check (subscriber_count is null or subscriber_count >= 0);

alter table public.channels
  add constraint channels_total_video_count_nonnegative
    check (total_video_count is null or total_video_count >= 0);
