# Deployment

This repo is set up for:

- Frontend: Cloudflare Pages from `frontend`
- Backend API: Railway service using `backend/Dockerfile`
- Pipeline worker: a second Railway service using the same Dockerfile with `APP_PROCESS=worker`

Deploy the API first so you have the backend URL for the Cloudflare build variable.

## 1. Railway API

Create a Railway service from the GitHub repository. Use the repository root as the service root directory.

Do not set the Railway root directory to `backend`. The Dockerfile is stored under `backend/Dockerfile`, but it copies `backend/` from the repository root build context.

The root `railway.json` forces Railway to use `backend/Dockerfile`. If Railway still tries Railpack, check that `railway.json` has been pushed and that the service root is the repository root.

The same `railway.json` sets Railway's health check to `/api/health`. Use `/api/ready` yourself after deploy to confirm production secrets and storage settings are complete.

In the API service variables, paste the values from:

```text
deploy/railway-api.env.example
```

Important values:

- `RAILWAY_DOCKERFILE_PATH=backend/Dockerfile` is included as a dashboard fallback, but `railway.json` already points Railway at the backend Dockerfile.
- `APP_PROCESS=api` runs FastAPI.
- `CORS_ORIGINS` must include the Cloudflare Pages preview URL and the production frontend domain.
- `STORAGE_BACKEND=supabase` is required for production.
- `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`, and `MINIMAX_API_KEY` are secrets.
- `YTDLP_COOKIES_B64` is recommended for production because hosted IPs can trigger YouTube bot checks during channel/video metadata fetches.
- Do not set a custom `PORT` variable. Railway provides `PORT`, and the container listens on it.

After deploy, generate a Railway public domain for the API service and verify:

```powershell
$API_URL = "https://<your-railway-api-domain>"
Invoke-RestMethod "$API_URL/api/health"
Invoke-RestMethod "$API_URL/api/ready"
```

`/api/ready` must return `"ok": true` before the frontend is considered production-ready.

### YouTube cookie setup

If the deployed app returns `Sign in to confirm you're not a bot` from `yt-dlp`, provide YouTube cookies that `yt-dlp` can pass with `--cookies`. Use a dedicated account if possible, and treat the exported file as a secret.

To create a cookies file that survives YouTube's browser cookie rotation:

1. Open a private/incognito browser window and log into YouTube.
2. In the same window and tab, navigate to `https://www.youtube.com/robots.txt`.
3. Export `youtube.com` cookies in Netscape `cookies.txt` format using a trusted cookies exporter extension.
4. Close that private/incognito window so the session is not reused in the browser.

Then encode the exported file from your local machine:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("youtube-cookies.txt")) | Set-Clipboard
```

On macOS/Linux, encode with `base64 -w0 youtube-cookies.txt`.

Paste the copied value into the Railway API service variable `YTDLP_COOKIES_B64`, then redeploy or restart the API service. If you provide a cookies file in the container instead, set `YTDLP_COOKIES_PATH` to that file path.

## 2. Railway Worker

The pipeline worker is a long-running process. Create a second Railway service from the same GitHub repository.

Use the same repository root and paste the values from:

```text
deploy/railway-worker.env.example
```

Important values:

- `RAILWAY_DOCKERFILE_PATH=backend/Dockerfile` uses the same image build.
- `APP_PROCESS=worker` runs `python -m backend.worker` instead of Uvicorn.
- The worker does not need a public domain.
- Keep one worker service running unless you intentionally want multiple workers polling the queue.

For a simpler first launch, you can skip the separate worker service and set `PIPELINE_WORKER_MODE=embedded` on the API service. That runs API requests and pipeline work in one Railway service. The separate worker is cleaner once real users are using the app.

## 3. Cloudflare Pages Frontend

Create a Cloudflare Pages project connected to this repository:

- Root directory: `frontend`
- Build command: `npm run build`
- Build output directory: `dist`
- Node version: `22` is pinned by `frontend/.node-version`

Set these Cloudflare Pages environment variables before building:

```text
VITE_API_BASE_URL=https://<your-railway-api-domain>
VITE_SUPABASE_URL=https://<project-ref>.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=<publishable-key>
```

Vite bakes these into the static build, so redeploy Cloudflare Pages after changing them.

## 4. Final Production Wiring

After Cloudflare gives you the preview and production URLs:

1. Update `CORS_ORIGINS` on the Railway API service to include those exact frontend origins.
2. In Supabase Auth, set the site URL and allowed redirect URLs to the production frontend domain.
3. If you add a custom API domain such as `https://api.traceai.online`, update Cloudflare `VITE_API_BASE_URL` and redeploy the frontend.
4. Recheck `GET /api/ready` and sign in through the deployed frontend.

Official references:

- Cloudflare Pages React guide: https://developers.cloudflare.com/pages/framework-guides/deploy-a-react-site/
- Railway Dockerfile path: https://docs.railway.com/builds/dockerfiles
- Railway public networking and `PORT`: https://docs.railway.com/deploy/exposing-your-app
- Railway variables: https://docs.railway.com/variables
- yt-dlp cookies FAQ: https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp
- yt-dlp YouTube cookie notes: https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies
