# Implementation Status — Proxy Transcript Plan

**Goal**: ship `PLAN_PROXY_TRANSCRIPT.md` end-to-end so YouTube transcripts fetch reliably from cloud workers without one user starving others.

**Coordination contract** (every session MUST follow):

1. **Read this file first** before starting any work.
2. **Claim** a task by editing its row: set `status = in_progress`, fill `session`, `branch`, `started_at`. Commit & push the claim before writing code.
3. **Skip claimed tasks** unless `started_at` is older than 24h with no commits on the claimed branch (then it's stale — clear claim, reclaim).
4. **Mark `done`** only after PR merged to main. Append PR link.
5. **Tasks have explicit dependencies** in `depends_on`. Do not start a task until its deps are `done`.
6. **One task at a time per session.** If you need to do prep work that touches multiple tasks, claim the parent task and document scope.

Session ID format: any short identifier (e.g. `s-2026-05-14-a`, your branch name, or initials + date).

---

## Phase 1 — Provider Abstraction

| ID | Task | Status | Depends_on | Session | Branch | Started_at | PR |
|----|------|--------|-----------|---------|--------|------------|-----|
| P1.1 | Add `proxy_blocklist` migration (SQL in plan §1.2) | done | — | agent-p1.1-retry-2026-05-15 | proxy/p1-1-blocklist-migration | 2026-05-15 | https://github.com/medfata/sourcemaxai/pull/3 |
| P1.2 | New module `backend/pipeline/proxy_pool.py` (`ProxyConfig`, `ProxyPool`, `BlocklistStore`) | in_progress | P1.1 | agent-p1.2-2026-05-15 | proxy/p1-2-proxy-pool | 2026-05-15 | |
| P1.3 | Add proxy env vars to `backend/config.py` + 3 env example files | done | — | agent-p1.3-retry-2026-05-15 | proxy/p1-3-config-env-vars | 2026-05-15 | https://github.com/medfata/sourcemaxai/pull/2 |
| P1.4 | Refactor `fetch_single_transcript` to use `fetch_with_retry(pool, ...)` | todo | P1.2, P1.3 | | | | |
| P1.5 | Tests: `backend/tests/test_proxy_pool.py` (rotation, blocklist, failover) | todo | P1.2 | | | | |
| P1.6 | Tests: extend `test_fetch_transcripts.py` (mock IpBlocked → retry → success) | todo | P1.4 | | | | |

## Phase 2 — Per-User Fair-Use

| ID | Task | Status | Depends_on | Session | Branch | Started_at | PR |
|----|------|--------|-----------|---------|--------|------------|-----|
| P2.1 | Migration: extend `plan_tiers` (`proxy_bytes_per_month`, `proxy_requests_per_minute`, `transcript_concurrency`) | in_progress | — | agent-p2.1-2026-05-15 | proxy/p2-1-plan-tiers-migration | 2026-05-15 | https://github.com/medfata/sourcemaxai/pull/5 |
| P2.2 | Migration: extend `usage_events` (`proxy_bytes`, `proxy_provider`) | in_progress | — | agent-p2.2-2026-05-15 | proxy/p2-2-usage-events-migration | 2026-05-15 | |
| P2.3 | `Quota` dataclass + `SupabaseQuotaStore` updates for new columns | todo | P2.1 | | | | |
| P2.4 | New `check_transcript_fetch` in `quotas.py` (bytes + per-min rate) | todo | P2.3 | | | | |
| P2.5 | Per-byte logging in `fetch_with_retry` → `record_usage(proxy_bytes=...)` | todo | P2.2, P1.4 | | | | |
| P2.6 | `OwnerConcurrencyGate` (in-proc semaphore map) integrated into `fetch_transcripts` | todo | P2.3 | | | | |
| P2.7 | Tests: `test_quotas.py` extensions (proxy bytes limit, per-min rate, concurrency) | todo | P2.4, P2.6 | | | | |

## Phase 3 — Pipeline Wiring

| ID | Task | Status | Depends_on | Session | Branch | Started_at | PR |
|----|------|--------|-----------|---------|--------|------------|-----|
| P3.1 | Thread `owner_id` into `fetch_transcripts(channel_id, owner_id, ...)` from `routes/pipeline.py` | todo | P2.6 | | | | |
| P3.2 | Quota pre-check in `routes/pipeline.py` returning 402-style block payload | todo | P2.4 | | | | |
| P3.3 | Worker housekeeping: blocklist cleanup + circuit-breaker probe in `backend/worker.py` | todo | P1.2, P4.1 | | | | |
| P3.4 | New route `GET /api/quota/proxy-usage` | todo | P2.3 | | | | |

## Phase 4 — Circuit Breaker

| ID | Task | Status | Depends_on | Session | Branch | Started_at | PR |
|----|------|--------|-----------|---------|--------|------------|-----|
| P4.1 | Migration: `proxy_circuit_state` table | in_progress | — | agent-p4.1-2026-05-15 | proxy/p4-1-circuit-state-migration | 2026-05-15 | https://github.com/medfata/sourcemaxai/pull/7 |
| P4.2 | `CircuitBreaker` class in `proxy_pool.py` (closed/half_open/open transitions) | todo | P4.1, P1.2 | | | | |
| P4.3 | Wire breaker into `fetch_with_retry` (skip provider when open) | todo | P4.2, P1.4 | | | | |
| P4.4 | Tests: breaker opens after N failures, half-open probe behavior | todo | P4.2 | | | | |

## Phase 5 — Frontend

| ID | Task | Status | Depends_on | Session | Branch | Started_at | PR |
|----|------|--------|-----------|---------|--------|------------|-----|
| P5.1 | Block error surfacing in `ChannelInputPage.tsx` (proxy_bytes_limit modal) | todo | P3.2 | | | | |
| P5.2 | Quota meter component reading `/api/quota/proxy-usage` | todo | P3.4 | | | | |
| P5.3 | Per-row "retrying with rotated proxy" status in `StudioPage.tsx` | todo | P3.1 | | | | |
| P5.4 | Tier comparison copy update (transcript bandwidth quota) | todo | P5.1 | | | | |

## Phase 6 — Observability

| ID | Task | Status | Depends_on | Session | Branch | Started_at | PR |
|----|------|--------|-----------|---------|--------|------------|-----|
| P6.1 | Metrics in `backend/observability.py` (proxy_fetch_total, _bytes, _duration, circuit_state, blocklist_size) | todo | P1.4, P4.2 | | | | |
| P6.2 | Daily summary log: bytes per provider/tier/top-10-users | todo | P2.5 | | | | |
| P6.3 | Cost reconciliation script: compare `usage_events.proxy_bytes` sum vs provider invoice | todo | P2.5 | | | | |

## Phase 7 — Rollout

| ID | Task | Status | Depends_on | Session | Branch | Started_at | PR |
|----|------|--------|-----------|---------|--------|------------|-----|
| P7.1 | `USE_PROXY_POOL` feature flag in config; default off | todo | P1.4 | | | | |
| P7.2 | Shadow mode: log intended proxy without using it | todo | P7.1 | | | | |
| P7.3 | 10% canary by `owner_id % 10 == 0` | todo | P3.1, P3.2 | | | | |
| P7.4 | Full cutover; monitor 48h | todo | P7.3, P6.1 | | | | |
| P7.5 | Remove direct-fetch path from `fetch_transcripts.py` | todo | P7.4 | | | | |

---

## Decision Log

Append decisions taken during implementation. Format: `YYYY-MM-DD | session | decision | reason`.

- 2026-05-14 | s-init | Plan accepted, IPRoyal primary + Webshare fallback | cheapest pay-as-you-go + native lib support
- 2026-05-14 | agent-p1.1-2026-05-14 | `idx_proxy_blocklist_active` dropped `WHERE expires_at > now()` predicate | Postgres rejects non-IMMUTABLE `now()` in partial-index predicates; plain `(provider, expires_at)` btree still serves the active-lookup query (`WHERE provider = ? AND expires_at > now()`) efficiently. Plan §1.2 explicitly allows this adjustment.
- 2026-05-14 | agent-p1.3-2026-05-14 | Prod validation strictness: require IPROYAL_* host/user/pass, Webshare optional fallback; PROXY_MAX_ATTEMPTS/SESSION_LIFETIME/BLOCKLIST_TTL must be positive ints | Plan §1.4 calls IPRoyal primary and Webshare fallback; rejecting prod boot when Webshare creds missing would block deploys whenever fallback is unused.
- 2026-05-15 | agent-p1.2-2026-05-15 | `proxy_pool.ProxyConfig` is the per-provider dataclass per plan §1.1; this collides on bare name with `backend.config.ProxyConfig` (the runtime-config dataclass added by P1.3). Both are kept, importers must use full module path. | Plan §1.1 explicitly names the per-provider dataclass `ProxyConfig`; renaming it would diverge from the published API and the P1.4 spec.
- 2026-05-15 | agent-p1.2-2026-05-15 | Webshare host hard-coded to `p.webshare.io:80` inside `_webshare_from_config` because P1.3 did not add a `WEBSHARE_PROXY_HOST` env var (only USER/PASS). | Webshare's documented rotating-residential endpoint is `p.webshare.io:80`; adding a config var is in-scope for a follow-up but not blocking. If users need region-specific endpoints, P7.x or a tiny P1.3 patch can add `WEBSHARE_PROXY_HOST` env later.
- 2026-05-15 | agent-p4.1-2026-05-15 | `proxy_circuit_state` matches `proxy_blocklist` system-table conventions: no RLS enable, no GRANT, no `public.` schema prefix. CHECK constraint inlined on `status` (no separate ALTER) — matches the simpler-is-better style of `proxy_blocklist`. No trigger on `updated_at`; P4.2 breaker writes it explicitly per spec.
- 2026-05-15 | agent-p2.1-2026-05-15 | P2.1 migration includes `UPDATE ... WHERE tier_key = 'business'` even though `20260512104137_configurable_tiers_transcript_minutes.sql` seeds only `free` + `pro`. UPDATE is a safe no-op until a `business` row exists. | Task brief explicitly forbids inventing new tier rows but asks to land the business defaults so they apply automatically whenever business is seeded later.
- 

## Blocker Log

Append blockers needing user input. Format: `YYYY-MM-DD | session | blocker | resolved? | resolution`.

- 2026-05-15 | agent-p1.1-retry-2026-05-15 | `gh` CLI not installed/in PATH on this host (checked common Windows install paths + scoop shims; no GH_TOKEN env either), so the agent could not run `gh pr create` for P1.1. Branch `proxy/p1-1-blocklist-migration` is pushed with both the claim commit and the migration commit. | open | User to either (a) run `gh pr create --title "P1.1 proxy_blocklist migration" --body ...` locally, or (b) open the PR via the GitHub compare URL printed by `git push`: https://github.com/medfata/sourcemaxai/pull/new/proxy/p1-1-blocklist-migration, then paste the resulting PR URL into the P1.1 row.
- 2026-05-15 | agent-p1.2-2026-05-15 | `gh` CLI installed but not authenticated; could not run `gh pr create` for P1.2. | resolved | User ran `gh auth login` 2026-05-15. PR #4 opened by main session and merged.
- 2026-05-15 | agent-p4.1-2026-05-15 | `gh` CLI installed but not authenticated; could not run `gh pr create` for P4.1. | resolved | User ran `gh auth login` 2026-05-15. PR #7 opened by main session: https://github.com/medfata/sourcemaxai/pull/7
- 2026-05-15 | agent-p2.1-2026-05-15 | `gh` CLI installed but not authenticated; could not run `gh pr create` for P2.1. | resolved | User ran `gh auth login` 2026-05-15. PR #5 opened by main session: https://github.com/medfata/sourcemaxai/pull/5
- 

## Open Questions (from plan §Open Questions)

- Webshare worth $6/mo minimum, or use second IPRoyal sub-account for IP diversity?
- Free-tier proxy quota exhaustion: hard-fail or queue-and-retry-next-month?
- Keep yt-dlp tier-2 fallback or drop?
- Per-user concurrency: in-process v1 OK; revisit if scaling beyond 1 worker process.
