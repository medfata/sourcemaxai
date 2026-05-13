-- Phase 5: make pipeline run state durable enough for the existing staged UI.
--
-- Phase 2 created the run tables, but the MVP pipeline pauses between chunks
-- and summaries and reports the same per-video status strings that the local
-- JSON state used. These constraints keep the durable tables compatible with
-- that state machine.

alter table public.pipeline_runs
drop constraint if exists pipeline_runs_status_check;

alter table public.pipeline_runs
add constraint pipeline_runs_status_check
check (
  status in (
    'queued',
    'running',
    'awaiting_confirm_summaries',
    'completed',
    'failed',
    'cancelled',
    'cancel_requested'
  )
);

alter table public.pipeline_run_videos
drop constraint if exists pipeline_run_videos_transcript_status_check;

alter table public.pipeline_run_videos
add constraint pipeline_run_videos_transcript_status_check
check (
  transcript_status in (
    'queued',
    'running',
    'fetching',
    'done',
    'completed',
    'failed',
    'skipped',
    'unavailable'
  )
);

alter table public.pipeline_run_videos
drop constraint if exists pipeline_run_videos_chunk_status_check;

alter table public.pipeline_run_videos
add constraint pipeline_run_videos_chunk_status_check
check (
  chunk_status in (
    'queued',
    'running',
    'done',
    'completed',
    'failed',
    'skipped'
  )
);

alter table public.pipeline_run_videos
drop constraint if exists pipeline_run_videos_summary_status_check;

alter table public.pipeline_run_videos
add constraint pipeline_run_videos_summary_status_check
check (
  summary_status in (
    'queued',
    'running',
    'fetching',
    'done',
    'completed',
    'failed',
    'skipped'
  )
);
