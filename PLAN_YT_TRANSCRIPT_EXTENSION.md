# YouTube Transcript Extension + Onboarding Plan

## Summary

Build a Chrome Manifest V3 extension that captures selected YouTube video transcripts from the user's browser/IP, uploads normalized transcript JSON to Trace, and lets the existing pipeline reuse those cached transcripts. During first authenticated onboarding, the web app recommends installing the extension, but users can skip and rely on cloud fallback.

## Key Changes

- Add a new `extensions/trace-youtube-capture` package with:
  - Chrome MV3 `manifest.json`, background service worker, app-origin content script, and YouTube transcript fetch module.
  - Host permissions for `youtube.com`, local app, and production app origins.
  - A paced local queue: concurrency `1`, default delay `1-3s`, progress events, stop-on-block behavior.
- Add a web-app bridge:
  - Web app sends `TRACE_EXTENSION_PING` and receives `TRACE_EXTENSION_READY`.
  - Web app sends selected video IDs/channel metadata via `TRACE_CAPTURE_SELECTED`.
  - Extension returns per-video `queued | fetching | uploaded | skipped | failed | blocked`.
  - Extension must not persist Supabase access tokens; it receives a short-lived bearer token per capture command and uses it only for uploads.
- Add backend transcript import API:
  - `POST /api/transcripts/import`
  - Authenticated with existing bearer auth.
  - Payload includes `channel_id`, `video_id`, `language`, `source`, and `segments`.
  - Backend validates user owns the channel, video belongs to cached channel videos, segments are non-empty/sane, then saves using the existing transcript artifact shape and `TRANSCRIPT_SCHEMA_VERSION`.
- Add transcript readiness API:
  - `POST /api/transcripts/status`
  - Input: `channel_id`, `video_ids`.
  - Output: per-video `cached | missing | stale`, plus counts.
  - Used before capture and before pipeline start.
- Update pipeline behavior:
  - Pipeline checks cached/imported transcripts first.
  - For missing transcripts, use cloud fallback only when enabled/quota allows.
  - Do not call the current server-side YouTube transcript provider by default for production Pro flow.

## Onboarding + UX

- On first authenticated `/channels` visit, show an extension onboarding panel/modal if local browser state has not dismissed it and extension detection fails.
- Onboarding options:
  - Primary: "Install Chrome extension" linking to `VITE_TRACE_EXTENSION_STORE_URL`.
  - Secondary: "I installed it" re-runs detection.
  - Tertiary: "Skip for now" stores local dismissal per user/browser.
- In the video selection run flow:
  - Save selected videos.
  - Call transcript status.
  - If missing transcripts exist and extension is detected, offer "Capture with extension" before starting pipeline.
  - Show live extension capture progress in the same workspace style.
  - If extension is skipped/fails, proceed to cloud fallback within quota and clearly show remaining uncaptured videos.
- Keep onboarding state in browser local storage for v1, keyed by authenticated user ID.

## Extension Transcript Strategy

- Fetch transcripts via direct Innertube/timedtext flow, not `yt-dlp`:
  - Call YouTube Innertube player endpoint for caption tracks.
  - Prefer manual English captions, then auto English, then first available track.
  - Fetch caption `baseUrl` with `fmt=json3`.
  - Parse events into `{start, text}` segments.
- Failure behavior:
  - `no_captions`: upload nothing; web app can use cloud fallback.
  - `blocked`/`429`/bot-check-like response: stop local queue and report cooldown state.
  - `private`, `age_restricted`, `region_blocked`: mark failed with reason.
- Extension batch defaults:
  - concurrency: `1`
  - delay: randomized `1000-3000ms`
  - soft batch: selected videos from app, initially allow up to `100`
  - stop on first clear IP block

## Tests And Acceptance Criteria

- Backend tests:
  - import rejects unauthenticated requests.
  - import rejects channels/videos not owned by user.
  - import rejects empty/oversized/invalid segments.
  - import writes transcript artifact readable by existing chunk/summarize stages.
  - transcript status returns cached/missing/stale accurately.
- Frontend tests/manual scenarios:
  - first authenticated user sees install step when extension missing.
  - skip hides onboarding for that browser/user.
  - extension detection changes UI state without page reload.
  - selected-video run flow starts extension capture before pipeline.
  - partial capture falls back to cloud provider or skips per quota policy.
- Extension tests/manual scenarios:
  - captures a known captioned YouTube video.
  - uploads transcript to local backend with bearer auth.
  - handles no-caption video.
  - handles 20-video and 100-video paced batches without concurrent blasts.
  - stops and reports blocked state when YouTube returns block-like errors.

## Assumptions

- V1 targets Chrome Manifest V3 only.
- Distribution target is Chrome Web Store; development can still use unpacked loading.
- Extension installation is recommended, not required.
- Cloud fallback remains available for skipped/missing/failed extension captures.
- Onboarding status is browser-local for v1; no user-profile migration is required.
