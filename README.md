# Trace

Trace turns YouTube channels into searchable, cited maps of a creator's themes, claims, tone, and recurring ideas.

Domain: https://traceai.online

## Run locally

**Terminal 1 — Backend:**
```bash
python -m uvicorn backend.main:app --reload --port 8000
```

**Terminal 2 — Frontend:**
```bash
cd frontend
npm run dev
```

Open http://localhost:5173 in your browser.

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for the Cloudflare Pages frontend and Railway backend deployment flow.

For local Docker smoke tests, build from the repository root:

```bash
docker build -f backend/Dockerfile -t trace-backend .
docker run --env-file .env -e PORT=8000 -p 8000:8000 trace-backend
docker run --env-file .env -e APP_PROCESS=worker trace-backend
```

Health endpoints:

- `GET /api/health` is a public liveness check.
- `GET /api/ready` validates deployment configuration without exposing secrets.

Copy `.env.example` and `frontend/.env.example` for the required deployment variables.
