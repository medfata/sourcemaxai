# Proxy-Rotated Transcript Fetching + Per-User Fair-Use Plan

## Goal

Fix `RequestBlocked`/`IpBlocked` from `youtube-transcript-api` on Railway worker IP by routing transcript fetches through rotating residential proxies, with a fair-use system that prevents one user from exhausting the shared proxy pool and starving other users.

Primary proxy: **IPRoyal** (residential, $1.75/GB pay-as-you-go, no expiry).
Fallback proxy: **Webshare** (residential, native lib support, different IP space).

Drop-in to existing `backend/pipeline/fetch_transcripts.py`. Reuse existing `quotas.py` infrastructure for per-user limits.

---

## Architecture Overview

```
                       ┌──────────────────────────────┐
fetch_transcripts.py → │   TranscriptProvider chain   │
                       │                              │
                       │  1. cache hit (DB)           │ → done, $0
                       │  2. IPRoyal sticky session   │
                       │  3. Webshare sticky session  │
                       │  4. yt-dlp via proxy         │
                       │  5. dead-letter / requeue    │
                       └──────────────────────────────┘
                              ↑              ↓
                       proxy_blocklist   usage_events
                       (Supabase)        (per-user GB)
```

---

## Phase 1 — Provider Abstraction

### 1.1 New module `backend/pipeline/proxy_pool.py`

Single responsibility: hand out a fresh proxy URL on demand, track which sessions/IPs are blocked, fail over between providers.

```python
@dataclass(frozen=True)
class ProxyConfig:
    name: str                  # "iproyal" | "webshare"
    host: str                  # e.g. "geo.iproyal.com:12321"
    username: str
    password: str
    session_param: str         # "session" for IPRoyal, "session" for Webshare-residential
    rotate_per_request: bool   # False → sticky, True → endpoint rotation

class ProxyPool:
    def __init__(self, providers: list[ProxyConfig], blocklist: BlocklistStore): ...

    def acquire(self, video_id: str, attempt: int) -> tuple[ProxyConfig, str]:
        """Return (provider, session_id) avoiding blocked sessions."""

    def mark_blocked(self, provider: ProxyConfig, session_id: str, reason: str): ...

    def proxy_url(self, provider: ProxyConfig, session_id: str) -> str: ...
```

Session ID generation:
- Random 10-char alphanum per attempt.
- Format: `http://{user}-session-{sid}-lifetime-30m:{pass}@{host}`.
- Both IPRoyal and Webshare accept sticky-session params in username string.

### 1.2 Blocklist store

New table:

```sql
CREATE TABLE proxy_blocklist (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider text NOT NULL,
  session_id text NOT NULL,
  reason text NOT NULL,           -- 'ip_blocked' | 'request_blocked' | '429'
  blocked_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL DEFAULT (now() + interval '6 hours'),
  UNIQUE (provider, session_id)
);

CREATE INDEX idx_proxy_blocklist_active
  ON proxy_blocklist (provider, expires_at) WHERE expires_at > now();
```

`BlocklistStore` API:
- `is_blocked(provider, session_id) -> bool`
- `add(provider, session_id, reason)`
- `cleanup_expired()` — run from worker housekeeping every 10 min.

In-process LRU cache (~5min TTL) sits in front of DB to avoid per-request SELECT.

### 1.3 Refactor `fetch_single_transcript`

Replace:
```python
api = YouTubeTranscriptApi()
```

With:
```python
result = fetch_with_retry(
    video_id,
    pool=proxy_pool,
    max_attempts=5,
    owner_id=owner_id,
)
```

`fetch_with_retry` loop:
1. For each attempt 1..N:
   - `provider, session_id = pool.acquire(video_id, attempt)`
   - Build `GenericProxyConfig` (or `WebshareProxyConfig` if `provider.name == "webshare"`)
   - Call `YouTubeTranscriptApi(proxy_config=cfg).fetch(video_id)`
   - On `RequestBlocked` / `IpBlocked`: `pool.mark_blocked(provider, session_id, reason)`; continue
   - On `TranscriptsDisabled` / `NoTranscriptFound`: return unavailable (no retry — real video state, not IP issue)
   - On generic `Exception`: log; retry with new session up to limit
2. If all attempts exhausted: tier-2 fallback (yt-dlp through same proxy pool).
3. If everything fails: mark `transcript_status = 'ip_blocked'` in DB, dead-letter, return `{"status": "failed", "error": "all_proxies_blocked"}`.

### 1.4 Config additions (`backend/config.py`)

```
IPROYAL_PROXY_HOST          (e.g. "geo.iproyal.com:12321")
IPROYAL_PROXY_USER
IPROYAL_PROXY_PASS

WEBSHARE_PROXY_USER
WEBSHARE_PROXY_PASS

PROXY_MAX_ATTEMPTS=5
PROXY_SESSION_LIFETIME_MIN=10
PROXY_BLOCKLIST_TTL_HOURS=6
TRANSCRIPT_WORKERS=4              # lower from 8 — avoid burst on single proxy
```

Add to `.env.example`, `deploy/railway-api.env.example`, `deploy/railway-worker.env.example`.

Treat proxy creds as optional in dev (fall back to direct fetch) and required in prod.

---

## Phase 2 — Per-User Fair-Use (Anti-Abuse)

The existing `quotas.py` already tracks `monthly_transcript_seconds` per user. That alone is not enough — a user with quota left can still hammer the proxy pool with retries on blocked videos.

### 2.1 Two new per-user limits

Add to `plan_tiers`:

```sql
ALTER TABLE plan_tiers
  ADD COLUMN proxy_bytes_per_month bigint NOT NULL DEFAULT 524288000,   -- 500 MB free, 5 GB pro, 50 GB business
  ADD COLUMN proxy_requests_per_minute int NOT NULL DEFAULT 30,
  ADD COLUMN transcript_concurrency int NOT NULL DEFAULT 2;             -- worker slots per user
```

Defaults by tier:

| Tier | proxy_bytes_per_month | proxy_req_per_min | concurrency |
|------|----------------------|-------------------|-------------|
| free | 100 MB | 10 | 1 |
| pro | 2 GB | 60 | 4 |
| business | 20 GB | 200 | 8 |

100 MB ≈ ~5,000 transcript fetches → enough for one big channel scan on free.

### 2.2 Per-user proxy byte tracking

Extend `usage_events`:

```sql
ALTER TABLE usage_events
  ADD COLUMN proxy_bytes bigint NOT NULL DEFAULT 0,
  ADD COLUMN proxy_provider text;
```

After each successful proxy fetch, log:
- `event_type = 'transcript_fetch'`
- `proxy_bytes = response_content_length + request_size_estimate`
- `proxy_provider = 'iproyal' | 'webshare' | 'ytdlp'`

Get content length from `requests.Response.headers["content-length"]` (or `len(body)` if missing). For `youtube-transcript-api` we instrument by monkeypatching its `_session` to count, or simpler: estimate `~20 KB per transcript` × actual count.

### 2.3 Quota check pre-fetch

New function in `quotas.py`:

```python
def check_transcript_fetch(
    store: QuotaStore,
    owner_id: str,
    *,
    pending_video_count: int,
) -> QuotaDecision:
    """Block transcript fetch if user has no proxy budget left."""
```

Checks:
1. Monthly proxy bytes used vs `proxy_bytes_per_month`.
2. Estimated bytes for this batch = `pending_video_count * 25_000`.
3. If projected > limit: reject with `proxy_bytes_limit` reason.
4. Per-minute rate: count last 60s `transcript_fetch` events; reject if `>= proxy_requests_per_minute`.

Called from `routes/pipeline.py` before queuing the transcript step **and** from inside the worker loop per batch (queued runs that wait may exhaust quota between submit and execute).

### 2.4 Per-user concurrency

Replace top-level `ThreadPoolExecutor(max_workers=TRANSCRIPT_WORKERS)` with per-owner semaphore:

```python
class OwnerConcurrencyGate:
    """Per-owner semaphore tracked in Redis (or in-proc map for single worker)."""
    def acquire(self, owner_id: str, quota: Quota) -> ContextManager: ...
```

Simpler v1 (no Redis): in-process `dict[owner_id, Semaphore]`. Works for single-worker deployment. Document scale-out caveat.

When `n_workers = 4` globally and `quota.transcript_concurrency = 1` for free user, even if user submits 100 videos, only 1 fetches at a time → leaves 3 slots for other users.

### 2.5 Global circuit breaker

Pool-wide cap to protect proxy budget across all users:

```sql
CREATE TABLE proxy_circuit_state (
  provider text PRIMARY KEY,
  status text NOT NULL DEFAULT 'closed',     -- closed | half_open | open
  open_until timestamptz,
  consecutive_failures int NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now()
);
```

Rules:
- 10 consecutive block errors on a provider within 5 min → open circuit 15 min for that provider.
- All in-flight requests fall to next provider.
- After cool-down, half-open: one probe; success → close, failure → open another 15 min.

Prevents burning 1 GB of proxy budget on a provider whose pool is currently poisoned.

---

## Phase 3 — Wiring Into Existing Pipeline

### 3.1 `fetch_transcripts.py` changes

```python
def fetch_transcripts(channel_id: str, owner_id: str, on_progress=None) -> dict:
    quota_store = get_quota_store()
    decision = check_transcript_fetch(quota_store, owner_id, pending_video_count=len(selection))
    if not decision.allowed:
        return {"total": 0, "results": [], "blocked": decision}

    proxy_pool = build_proxy_pool()
    gate = OwnerConcurrencyGate.get()
    quota = quota_store.get_quota(owner_id)

    with ThreadPoolExecutor(max_workers=quota.transcript_concurrency) as exe:
        # submit per video; each task acquires gate, runs fetch_with_retry
        ...
```

Pass `owner_id` through. Current signature is `(channel_id, on_progress)` — need to thread `owner_id` from caller in `routes/pipeline.py`.

### 3.2 Worker housekeeping

Add task to `backend/worker.py` heartbeat loop:
- Every 10 min: `BlocklistStore.cleanup_expired()`
- Every 5 min: check `proxy_circuit_state` and probe half-open circuits.

### 3.3 New route: `GET /api/quota/proxy-usage`

Returns:
```json
{
  "tier_key": "pro",
  "proxy_bytes_used": 524288000,
  "proxy_bytes_limit": 2147483648,
  "proxy_bytes_remaining": 1623195648,
  "estimated_videos_remaining": 64928
}
```

Frontend `StudioPage` shows progress meter.

---

## Phase 4 — Frontend UX

### 4.1 Block error surfacing

When `routes/pipeline.py` returns `{"blocked": {"reason": "proxy_bytes_limit"}}`:
- `ChannelInputPage` → modal "You've reached your transcript proxy budget. Upgrade or wait until next month."
- Show used / limit / reset date.

When `transcript_status = 'ip_blocked'` per video in pipeline progress:
- Per-row status badge "Retrying with rotated proxy…" (transient)
- After dead-letter: "Failed — proxy exhausted. Will retry automatically."

### 4.2 Tier comparison

Update marketing copy to mention transcript quota explicitly:
- Free: 100 MB proxy bandwidth (~5k transcripts)
- Pro: 2 GB (~100k transcripts)
- Business: 20 GB

### 4.3 Concurrency feedback

When user is rate-gated (`proxy_requests_per_minute` hit), show "Throttled to N requests/min on your plan" with countdown.

---

## Phase 5 — Tests

### 5.1 Unit

`backend/tests/test_proxy_pool.py`:
- Pool rotates session IDs across attempts.
- `mark_blocked` excludes session from future `acquire`.
- Provider failover when primary blocked.
- Circuit-breaker opens after N consecutive failures.

`backend/tests/test_quotas.py` (extend):
- `check_transcript_fetch` blocks when projected proxy bytes > limit.
- Per-minute rate limit triggers on 11th call within 60s.
- Free-tier user with 1 concurrency slot serializes 5 videos.

`backend/tests/test_fetch_transcripts.py` (extend):
- Mock `YouTubeTranscriptApi` raising `IpBlocked`; assert retry with new session.
- Mock all attempts fail; assert dead-letter status.
- Assert `usage_events` row written with `proxy_bytes`.

### 5.2 Integration

Stub HTTP server simulating proxy + YouTube responses:
- 3 sessions return 200, 2 return 429.
- Assert end-to-end fetch succeeds within retry budget.

### 5.3 Manual acceptance

- Run pipeline against real channel (10 videos) using IPRoyal trial $1 → all succeed, proxy_bytes logged.
- Pull 50 videos as free-tier dummy user → throttled per quota.
- Force `IPROYAL_PROXY_HOST=invalid` → fallback to Webshare succeeds.

---

## Phase 6 — Operational

### 6.1 Observability

Add metrics:
- `proxy_fetch_total{provider, outcome}` — counter
- `proxy_fetch_bytes{provider}` — counter
- `proxy_fetch_duration_seconds{provider}` — histogram
- `proxy_circuit_state{provider}` — gauge (0=closed, 1=half_open, 2=open)
- `proxy_blocklist_size{provider}` — gauge

Surface in existing `backend/observability.py`.

### 6.2 Alerts

- `proxy_circuit_state == open` for >30 min → pager.
- `proxy_fetch_bytes` 7-day rate above budget → pager.
- Daily summary: bytes per provider, per tier, per user (top 10).

### 6.3 Cost monitoring

Reconcile billed GB from IPRoyal/Webshare dashboards monthly against summed `usage_events.proxy_bytes`. Discrepancy >20% → investigate (request overhead, retries, etc.).

---

## Phase 7 — Rollout

1. Deploy proxy_pool + tables migration; provider creds set; **feature-flagged off** (`USE_PROXY_POOL=false`).
2. Shadow mode: log what proxy would have been used, still fetch directly.
3. Switch on for 10% of users (`owner_id % 10 == 0`).
4. Full cutover. Monitor for 48 hours.
5. Remove direct-fetch path from `fetch_transcripts.py`.

Rollback: flip `USE_PROXY_POOL=false`, redeploy.

---

## Cost Model (verify post-launch)

Assume avg transcript ~25 KB (request+response).

| Tier | Monthly bandwidth | Cost (IPRoyal $1.75/GB) | Price | Margin |
|------|-------------------|------------------------|-------|--------|
| Free | 100 MB | $0.18 | $0 | -$0.18 (acquisition cost) |
| Pro | 2 GB | $3.50 | $9 | +$5.50 |
| Business | 20 GB | $35 | $49 | +$14 |

Add Webshare fallback usage ~10% of total = +10% on cost line. Still profitable.

If overage common: switch to per-overage credit-pack billing reusing existing `user_credit_grants` table.

---

## Open Questions

- Webshare residential plans have monthly minimums ($6 entry). Worth it just for IP diversity? Alternative: rent second IPRoyal sub-account on different geo (different IP ranges).
- Should free-tier proxy usage just hard-fail at quota, or queue + retry next month? Hard-fail is simpler, clearer UX.
- yt-dlp fallback adds ~5s latency per video. Worth keeping? Probably yes — last resort, rare invocation.
- Per-user concurrency in single Python process is straightforward; if we scale to multi-worker, need Redis or Postgres advisory locks. Defer.

---

## Relation to `PLAN_YT_TRANSCRIPT_EXTENSION.md`

That plan describes a Chrome extension as primary transcript source (user's own residential IP, $0 cost). This plan is **complementary**: proxy pool serves users who skip extension install or fail extension capture. Long-term hierarchy:

```
Tier 1: Extension (user IP)         — $0
Tier 2: Proxy pool (this plan)      — $0.00005/video
Tier 3: Supadata native             — $0.0033/video
Tier 4: Audio + ASR (Deepgram)      — $0.13/video
```

Proxy pool becomes the most-used path for non-extension users. Critical to implement even with extension shipped.
