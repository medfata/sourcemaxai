# YouTube Transcript Strategy — Research & Decision Notes

## Problem

Backend pipeline uses `youtube-transcript-api` to fetch transcripts. YouTube blocks requests from cloud/server IPs (Railway/AWS/GCP). One user selecting ~100 videos triggered `RequestBlocked` / `IpBlocked` failures, which affected all users because the worker IP is shared.

The immediate symptom (app hang) was fixed by failing runs cleanly on block errors and disabling local embedded workers from claiming the shared Supabase queue. The core issue — server-side transcript fetching on shared cloud IP — remains.

Current architecture:
- Users select videos in web app
- Backend pipeline fetches transcripts → caches as JSON
- Pipeline chunks → summarizes → aggregates profile → enables chat
- Queue global at worker level, runs user-scoped by `owner_id`
- Rate limit / IP block shared at worker IP, not per user

---

## Options Compared

| # | Option | Cloud-IP reliability (2025-26) | $/100 videos (~3,000 min) | Complexity (1-5) | No-caption fallback |
|---|--------|-------------------------------|---------------------------|------------------|---------------------|
| 1 | Direct Innertube + timedtext (`ytranscript`, `YouTube.js`) | Poor on shared cloud IPs; same IP block as `youtube-transcript-api`. POT requirement creeping in. | $0 + proxy | 4 | No |
| 2 | `youtube-transcript-api` + Webshare residential | Mixed — official integration but issue #511 (Aug 2025) reports sporadic blocks; generally works with rotation | ~$2-4 (1-2 GB @ $2.25-3.50/GB) | 2 | No |
| 3 | **Supadata** | High (managed, abstracts IP/POT) | ~$1.70 (Pro $17/3k credits, native mode 1 credit/video) | 1 | Yes (`mode=generate` = 2 credits/min) |
| 4a | Apify `supreme_coder/youtube-transcript-scraper` | High (managed) | **$0.05** ($0.50/1k native captions) | 2 | Per-actor variant |
| 4b | Scrapingdog YT Transcripts | High (managed) | ~$1-5 (1 credit/video) | 2 | No |
| 4c | SearchAPI YouTube Transcripts | High (managed) | ~$1-2 (1 credit/req) | 2 | No |
| 5 | YouTube Data API v3 `captions.download` | N/A — **owner-uploaded only**, OAuth required. Confirmed restricted 2025. | Unusable for 3rd-party channels | n/a | No |
| 6 | yt-dlp on cloud | Poor — needs `bgutil-ytdlp-pot-provider` sidecar + cookies; SABR forced even with premium cookies (yt-dlp #14390) | Infra + proxy | 4 | Via audio path |
| 7 | Audio download + Deepgram Nova-3 | Audio fetch same IP-block problem; needs yt-dlp + proxy. Nova-3 batch $0.0043/min × 3000 = **~$12.90** | $12.90 + bandwidth | 4 | Yes |
| 7b | Audio + AssemblyAI Universal | Same fetch problem. $0.0025/min = **~$7.50** | $7.50 | 4 | Yes |
| 8 | Chrome MV3 extension (client IP) | High (user residential IP, browser session) | **$0** | 3 | No |

---

## Why Pure Client-Side `ytranscript` Doesn't Work

Tempting to call `ytranscript` from the web app's JS directly. **CORS blocks this.**

YouTube internal endpoints (`/youtubei/v1/player`, `/api/timedtext`) send no `Access-Control-Allow-Origin` header for 3rd-party origins. Browser SOP refuses to read the response.

```
Access to fetch at 'https://www.youtube.com/youtubei/v1/player' from origin
'https://yourapp.com' has been blocked by CORS policy: No 'Access-Control-Allow-Origin'
header is present on the requested resource.
```

Workarounds and why they fail:
- `no-cors` mode → response opaque, body unreadable
- CORS proxy server → proxy IP = server IP = blocked again
- iframe + postMessage → YT sends `X-Frame-Options: SAMEORIGIN` + frame-ancestors CSP
- Embed page scraping → embed strips player config + caption tracks
- Direct `timedtext` XML fetch → CORS block + URL needs signed params

**Only extensions bypass this.** MV3 `host_permissions: ["*://*.youtube.com/*"]` grants privileged fetch with YT cookies and no CORS preflight enforcement on response.

---

## Recommended Architecture

**Hybrid: web app + thin extension as transcript worker.**

```
yourapp.com (full studio UI, React, all features)
   ↕ chrome.runtime.sendMessage (externally_connectable)
Extension (~200 LOC — fetch caption tracks, return JSON)
   ↕ upload normalized JSON
Backend (accepts transcript artifacts, skips fetch step)
```

### Fallback chain

```
Tier 1: Extension (ytranscript via client IP)   — $0, best reliability
Tier 2: Supadata native mode                     — ~$0.0033/video, no-install users
Tier 3: Supadata generate mode / Deepgram        — no-caption / audio fallback
Cache:  existing JSON artifacts keyed by videoId+lang (already in place)
```

### Why hybrid beats full-extension-app

- Studio stays at `yourapp.com` → SEO, sharing, OAuth, deep links work
- Extension is invisible utility (popup shows "Connected ✓")
- No duplicate React build inside extension
- Updates ship via web deploy, not Chrome Web Store review (1-7 days)
- Extension stays tiny + boring → rare updates, fast reviews

### Manifest sketch

```json
{
  "manifest_version": 3,
  "name": "YT Channel Profiler — Transcript Helper",
  "host_permissions": ["*://*.youtube.com/*"],
  "externally_connectable": {
    "matches": ["https://yourapp.com/*"]
  },
  "background": { "service_worker": "sw.js" },
  "action": { "default_popup": "popup.html" }
}
```

### Web app → extension call

```js
chrome.runtime.sendMessage(EXTENSION_ID, {
  type: 'fetch_transcripts',
  videoIds: [...]
}, (response) => {
  // response.transcripts = [{ videoId, segments: [{text, offset, duration}] }]
});
```

### Pacing in extension

- Concurrency 1
- Delay 1-3 seconds between requests
- Stop on clear block signal
- Cache permanently by `videoId+lang`

### Extension UI surfaces (for reference)

| Surface | Size | Use |
|---|---|---|
| Popup | ~800x600 max | Status, quick actions |
| Side panel | Full vertical, 400-600px wide | Persistent companion |
| Options page | Full tab | Settings |
| Extension page | Full tab, any size | Could host whole app if needed |
| Content script overlay | Injected into YT | In-context UI |
| Offscreen document | Hidden | Long-running DOM work |

Studio stays in web app. Extension only needs the popup for status.

---

## Why Extension Beats Supadata-Only

Initial recommendation was Supadata primary. Reversed after weighing:

| Factor | Extension | Supadata |
|---|---|---|
| Cost | $0 forever | OPEX scales with users |
| Reliability | User residential IP = same as logged-in YT browsing | High but vendor-dependent |
| POT/SABR arms race | Browser handles natively | Vendor absorbs (for now) |
| Auth-gated content | Access via user session | No |
| Vendor risk | None | Pivot/shutdown/price hike |
| Data path | Client → backend direct | Through 3rd party |
| Big channels (500+ videos) | Free | Burns credits |

Real cons of extension (not deal-breakers):
- Install friction → optional, "free + faster" framing during onboarding
- Chrome-only v1 → 70%+ desktop share; Edge supports MV3 same code
- User must be logged in → already are when watching YT
- MV3 service worker dies after 30s idle → use offscreen document or re-wake per video
- Chrome Web Store review 1-7 days first publish → keep extension dumb, logic in web app

---

## Backend Changes (in current repo)

- `backend/pipeline/fetch_transcripts.py` — replace `youtube-transcript-api` call with `TranscriptProvider` abstraction (extension upload → Supadata → audio fallback)
- `backend/config.py` — add `SUPADATA_API_KEY`
- `backend/routes/pipeline.py` — add endpoint to accept transcript upload from extension (`POST /api/transcripts/upload`), validate shape, write to existing cache
- **Drop `youtube-cookies.txt` from prod** — cookie auth risks account ban per `youtube-transcript-api` README; not needed once extension primary
- Per-tier circuit breaker + retry-with-next-tier
- Keep queue + per-user `owner_id`

---

## Unit Economics

Assume avg user run = 100 videos × 30 min = 3,000 min.

| Path | Cost per run | Notes |
|---|---|---|
| Extension hit | **$0** | All users with extension installed |
| Supadata native | $0.34 | Pro $17 / 3,000 credits = $0.0033/video × 100 |
| Supadata generate (no captions) | $20 | 2 credits/min × 30 min × 100 = 6,000 credits |
| Deepgram Nova-3 | $12.90 | $0.0043/min × 3,000 |

If 60% users install extension → 60% of runs free. Remaining 40% via Supadata ≈ $0.14 blended per run.

---

## Open Questions / Risks

- YT could ship anti-extension content-script-defeating measures. Low prob short term.
- Chrome Web Store policy: extension must declare purpose clearly. "Helps users export their own viewing data for personal analysis" framing.
- Extension can't run when browser closed → for long batches, user must keep tab open. Document this UX clearly.
- Some videos lack captions entirely → falls to Supadata generate or audio path. Detect early to avoid wasted extension calls.

---

## Sources

- [jdepoix/youtube-transcript-api README — cloud IP blocks](https://github.com/jdepoix/youtube-transcript-api)
- [Issue #511: Webshare still blocked (Aug 2025)](https://github.com/jdepoix/youtube-transcript-api/issues/511)
- [Issue #79: AWS EC2 blocks](https://github.com/jdepoix/youtube-transcript-api/issues/79)
- [Supadata Pricing](https://supadata.ai/pricing)
- [Supadata YouTube Transcript API](https://supadata.ai/youtube-transcript-api)
- [Webshare Pricing](https://www.webshare.io/pricing)
- [Webshare YouTube proxies help article](https://help.webshare.io/en/articles/11432234-youtube-proxies)
- [yt-dlp PO Token Guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide)
- [yt-dlp issue #14390 — SABR forced with cookies](https://github.com/yt-dlp/yt-dlp/issues/14390)
- [bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider)
- [Deepgram Pricing (Nova-3 $0.0043/min batch)](https://deepgram.com/pricing)
- [AssemblyAI Pricing](https://www.assemblyai.com/pricing/)
- [Apify $0.5/1k YouTube Transcript Scraper](https://apify.com/supreme_coder/youtube-transcript-scraper)
- [Scrapingdog YouTube Transcripts API](https://www.scrapingdog.com/youtube-transcripts-api/)
- [SearchAPI YouTube Transcripts](https://www.searchapi.io/docs/youtube-transcripts)
- [YouTube Data API captions.download docs](https://developers.google.com/youtube/v3/docs/captions/download)
- [Chrome MV3 externally_connectable docs](https://developer.chrome.com/docs/extensions/reference/manifest/externally-connectable)
- [Chrome MV3 host_permissions](https://developer.chrome.com/docs/extensions/reference/manifest/host-permissions)
