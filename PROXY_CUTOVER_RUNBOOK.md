# Proxy Pool Cutover Runbook (P7.4)

End-to-end procedure for promoting the proxy pool from canary to default transcript-fetch path. Companion to `PLAN_PROXY_TRANSCRIPT.md` §7 and `IMPLEMENTATION_STATUS.md` rows P7.1–P7.5.

All flag flips happen in **Railway env vars** (`api` service + `worker` service). Code is already deployed; this runbook only flips switches and watches dials.

---

## Pre-flight

Before starting, confirm:

- PR #13 merged to main and deployed to both Railway services.
- `runtime_report()` (`GET /api/health/ready` or equivalent) shows:
  - `proxy.iproyal_enabled = true`
  - `proxy.webshare_enabled = true` (warn-only if false; IPRoyal alone OK)
  - `use_proxy_pool = false`, `proxy_pool_shadow = false`, `proxy_pool_canary = false`
- Supabase tables exist: `proxy_blocklist`, `proxy_circuit_state`, `usage_events.proxy_bytes` column.
- Current proxy provider balance covers ~2× expected 48h traffic. Top up if marginal.

If any check fails, stop. Fix before proceeding.

---

## Stage 1 — Shadow (24h, optional)

Already shipped in PR #12. Skip if shadow has already run cleanly in prod.

| Service | Var | Value |
|--------|------|-------|
| api | `PROXY_POOL_SHADOW` | `true` |
| worker | `PROXY_POOL_SHADOW` | `true` |

Watch:
- `proxy_shadow` log lines appear at roughly the rate of transcript fetches.
- `proxy_shadow_skipped_open` lines stay near zero (means breaker is healthy even though no real traffic yet).
- No regressions in `transcript_fetch` success rate (shadow does not change real fetches).

After 24h clean → proceed to Stage 2.

---

## Stage 2 — Canary (24h)

| Service | Var | Value |
|--------|------|-------|
| api | `PROXY_POOL_SHADOW` | `false` |
| api | `PROXY_POOL_CANARY` | `true` |
| worker | `PROXY_POOL_SHADOW` | `false` |
| worker | `PROXY_POOL_CANARY` | `true` |

10% of owners (`md5(owner_id) % 10 == 0`) now route through the real proxy pool. Other 90% remain direct.

Watch metrics over 24h:
- `proxy_canary_active` log line fires once per pipeline run for in-bucket owners.
- `proxy_fetch_total{outcome="success"}` rate ≈ 10% of total pipeline transcript volume.
- `proxy_fetch_total{outcome="failed"}` < 5% of canary requests.
- `proxy_circuit_state` stays `closed` for both providers (or transient `half_open` only).
- `proxy_blocklist_size` grows but stabilises; not unbounded.
- `proxy_fetch_bytes` extrapolated to 100% traffic stays inside the per-tier budgets in Phase 2 plan.
- No spike in `transcript_status = 'failed'` for in-bucket owners vs out-of-bucket baseline.

Compare canary owners vs control:
```sql
select
  case when (encode(digest(owner_id::text, 'md5'), 'hex')::text)::bytea is null then 'x' end
  -- alternatively, log owner_id+canary flag to usage_events and group there
;
```
(Easiest: filter `usage_events` rows for the last 24h grouping by `proxy_provider IS NULL` to compare bucket vs non-bucket success rates.)

**Abort criteria** — if any of these trip, set `PROXY_POOL_CANARY=false` and stop:
- Canary failure rate > 2× baseline direct-path failure rate.
- Either provider's circuit opens > 2 times in 24h.
- Combined provider bandwidth burn > 1.5× projection.

After 24h clean → proceed to Stage 3.

---

## Stage 3 — Full cutover (48h observation)

| Service | Var | Value |
|--------|------|-------|
| api | `USE_PROXY_POOL` | `true` |
| api | `PROXY_POOL_CANARY` | `false` |
| worker | `USE_PROXY_POOL` | `true` |
| worker | `PROXY_POOL_CANARY` | `false` |

`USE_PROXY_POOL=true` overrides everything else (canary, shadow). 100% of authenticated transcript fetches now go through the proxy pool. Anonymous traffic still uses direct path until P7.5 removes it.

Watch for **48 hours**:
- Same metrics as Stage 2 but at full traffic.
- Daily summary log (P6.2): bytes per provider/tier/top-10-users — confirm no single user is burning the whole budget.
- Quota-block events (`proxy_bytes_limit` reason in `routes/pipeline.py`): confirm free-tier users hit their quota cleanly with the modal showing.
- Cost reconciliation: at 24h mark, run `backend/scripts/reconcile_proxy_cost.py` (P6.3) and compare to provider dashboard.

**Rollback** — at any point during the 48h:
| Service | Var | Value |
|--------|------|-------|
| api + worker | `USE_PROXY_POOL` | `false` |

Direct-path code is still present until P7.5 ships, so this fully restores pre-cutover behavior. No code redeploy required — env-var change + Railway restart is enough.

---

## Stage 4 — Mark P7.4 done, unblock P7.5

After 48h clean cutover:

1. Update `IMPLEMENTATION_STATUS.md` row P7.4 → `status = done`, append a tiny PR linking this runbook update (or a status-only commit).
2. Append a Decision Log entry summarising: total proxy bytes burned, success rate, any breaker openings, IPRoyal vs Webshare share.
3. Claim P7.5 — code change to delete:
   - `_list_transcripts_direct` and the `pool is None` / `shadow` branches in `fetch_transcripts.py`.
   - `_owner_in_canary_bucket` and the canary mode-selection block in `fetch_transcripts`.
   - `proxy_pool_shadow` and `proxy_pool_canary` fields in `RuntimeConfig`.
   - `PROXY_POOL_SHADOW` and `PROXY_POOL_CANARY` lines from the 3 env example files.
   - Tests for shadow/canary behaviour in `test_fetch_transcripts.py`.
4. Plan §7 step 5 done = plan complete.

---

## Quick reference

| Stage | `USE_PROXY_POOL` | `PROXY_POOL_CANARY` | `PROXY_POOL_SHADOW` | Effect |
|-------|------------------|---------------------|---------------------|--------|
| pre   | false | false | false | Direct fetch only |
| shadow| false | false | true  | Direct fetch + log intended proxy |
| canary| false | true  | false | 10% real proxy, 90% direct |
| cutover | true | (any) | (any) | 100% real proxy |
| rollback | false | false | false | Back to direct fetch |
