# Channel Profiler

A local tool to profile YouTube channels: list videos, fetch captions, summarize, aggregate, and chat with the results.

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
