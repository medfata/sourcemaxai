"""FastAPI application entrypoint."""

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from backend.routes import channel, chat, pipeline, profile, videos  # noqa: E402

app = FastAPI(title="Channel Profiler", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(channel.router)
app.include_router(videos.router)
app.include_router(pipeline.router)
app.include_router(profile.router)
app.include_router(chat.router)


@app.get("/api/health")
def health_check() -> dict:
    """Return a simple health check response."""
    return {"ok": True}
