# Deployment

This repo is set up for:

- Frontend: Cloudflare Pages from `frontend`
- Backend API: Railway service using `backend/Dockerfile`
- Pipeline worker: a second Railway service using the same Dockerfile with `APP_PROCESS=worker`

Deploy the API first so you have the backend URL for the Cloudflare build variable.

## 1. Railway API

Create a Railway service from the GitHub repository. Use the repository root as the service root directory.

Do not set the Railway root directory to `backend`. The Dockerfile is stored under `backend/Dockerfile`, but it copies `backend/` from the repository root build context.

In the API service variables, paste the values from:

```text
deploy/railway-api.env.example
```

Important values:

- `RAILWAY_DOCKERFILE_PATH=backend/Dockerfile` tells Railway to use the backend Dockerfile.
- `APP_PROCESS=api` runs FastAPI.
- `CORS_ORIGINS` must include the Cloudflare Pages preview URL and the production frontend domain.
- `STORAGE_BACKEND=supabase` is required for production.
- `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`, and `MINIMAX_API_KEY` are secrets.
- Do not set a custom `PORT` variable. Railway provides `PORT`, and the container listens on it.

After deploy, generate a Railway public domain for the API service and verify:

```powershell
$API_URL = "https://<your-railway-api-domain>"
Invoke-RestMethod "$API_URL/api/health"
Invoke-RestMethod "$API_URL/api/ready"
```

`/api/ready` must return `"ok": true` before the frontend is considered production-ready.

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
