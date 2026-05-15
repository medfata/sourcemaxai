"""Tests for pipeline routes and selection cap behavior."""

import asyncio
import importlib
import os
import tempfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

TEST_OWNER_ID = "test-user"


@pytest.fixture(autouse=True)
def temp_data_dir(monkeypatch):
    """Use a temporary directory for DATA_DIR and set a fake API key."""
    with tempfile.TemporaryDirectory() as tmpdir:
        old = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = tmpdir
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        # Reload storage so module-level DATA_DIR picks up the new env var
        from backend import storage

        importlib.reload(storage)
        yield tmpdir
        if old is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = old


@pytest.fixture
def client():
    """Create a TestClient with freshly-reloaded route modules."""
    import backend.routes.channel as channel_mod
    import backend.routes.chat as chat_mod
    import backend.routes.pipeline as pipeline_mod
    import backend.routes.profile as profile_mod
    import backend.routes.videos as videos_mod
    from backend import storage

    importlib.reload(channel_mod)
    importlib.reload(chat_mod)
    importlib.reload(pipeline_mod)
    importlib.reload(profile_mod)
    importlib.reload(videos_mod)

    # Patch reloaded storage helpers into pipeline so they use the temp dir
    pipeline_mod.get_channel_dir = storage.get_channel_dir
    pipeline_mod.load_selection = storage.load_selection
    pipeline_mod.load_videos = storage.load_videos
    pipeline_mod.read_json = storage.read_json

    # Patch videos module too
    videos_mod.load_channel_meta = storage.load_channel_meta
    videos_mod.load_selection = storage.load_selection
    videos_mod.save_selection = storage.save_selection
    videos_mod.load_videos = storage.load_videos

    import backend.main as main_mod
    from backend.auth import CurrentUser, get_current_user

    importlib.reload(main_mod)
    main_mod.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        owner_id=TEST_OWNER_ID,
        email="test@example.com",
        role="authenticated",
        claims={"sub": TEST_OWNER_ID, "role": "authenticated"},
    )

    return TestClient(main_mod.app)


def _setup_channel(channel_id: str, video_count: int = 5):
    from backend import storage

    channel_dir = storage.get_channel_dir(channel_id, owner_id=TEST_OWNER_ID)
    channel_dir.mkdir(parents=True, exist_ok=True)
    storage.write_json(
        channel_dir / "meta.json",
        {
            "channel_id": channel_id,
            "channel_name": "Test Channel",
            "channel_handle": "@test",
            "avatar_url": "http://example.com/avatar.jpg",
        },
    )
    videos = [
        {
            "id": f"vid_{i}",
            "title": f"Video {i}",
            "upload_date": "20230101",
            "duration": 60,
            "view_count": 100,
            "thumbnail": "http://example.com/thumb.jpg",
        }
        for i in range(video_count)
    ]
    storage.write_json(channel_dir / "videos.json", {"videos": videos})
    return [v["id"] for v in videos]


def test_select_301_videos_allowed(client):
    """Backend must allow >300 selections; cap is frontend-only warning."""
    from backend import storage

    channel_id = "UC_test_cap"
    video_ids = _setup_channel(channel_id, video_count=301)

    resp = client.post(
        "/api/videos/select",
        json={"channel_id": channel_id, "video_ids": video_ids},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]["video_ids"]) == 301

    sel = storage.load_selection(channel_id, owner_id=TEST_OWNER_ID)
    assert len(sel) == 301


def test_cancel_persists_pipeline_state(client):
    """Cancel endpoint should persist durable cancellation state."""
    from backend import storage
    from backend.routes import pipeline as pipeline_module

    channel_id = "UC_test_cancel"
    _setup_channel(channel_id, video_count=5)
    storage.save_selection(channel_id, [f"vid_{i}" for i in range(5)], owner_id=TEST_OWNER_ID)

    with storage.storage_owner(TEST_OWNER_ID):
        pipeline_module._write_pipeline_state(
            channel_id,
            {
                "status": "running",
                "current_stage": "transcripts",
                "stages": {"transcripts": {"status": "running", "videos": {}}},
            },
        )

    resp = client.post(
        "/api/pipeline/cancel",
        json={"channel_id": channel_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "cancelled"

    with storage.storage_owner(TEST_OWNER_ID):
        state = pipeline_module._read_pipeline_state(channel_id)
    assert state["status"] == "cancelled"


def test_resume_requires_awaiting_confirm_summaries_state(client):
    """Resume must fail unless pipeline is in awaiting_confirm_summaries state."""
    from backend import storage
    from backend.routes import pipeline as pipeline_module

    channel_id = "UC_test_resume"
    _setup_channel(channel_id, video_count=5)

    # Without proper state, resume should fail
    resp = client.post(
        "/api/pipeline/resume",
        json={"channel_id": channel_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "not awaiting confirmation" in body["error"]

    # Set up the correct state
    with storage.storage_owner(TEST_OWNER_ID):
        pipeline_module._write_pipeline_state(
            channel_id,
            {
                "status": "awaiting_confirm_summaries",
                "current_stage": "awaiting_confirm_summaries",
                "stages": {"transcripts": {"status": "done"}},
            },
        )

    async def fake_run(*args, **kwargs):
        pass

    with patch.object(pipeline_module, "_run_pipeline", fake_run):
        resp = client.post(
            "/api/pipeline/resume",
            json={"channel_id": channel_id},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["status"] == "resumed"


def test_start_blocks_when_concurrent_quota_rejects(client):
    """POST /api/pipeline/start must surface quota_exceeded when concurrency is full."""
    from backend import storage
    from backend.quotas import Quota
    from backend.routes import pipeline as pipeline_module
    from backend.tests.test_quotas import FakeQuotaStore

    channel_id = "UC_test_quota"
    _setup_channel(channel_id, video_count=10)
    storage.save_selection(channel_id, [f"vid_{i}" for i in range(10)], owner_id=TEST_OWNER_ID)

    blocking_store = FakeQuotaStore(
        quota=Quota(max_concurrent_runs=1),
        active_runs=1,
    )

    with patch.object(pipeline_module, "get_quota_store", return_value=blocking_store):
        resp = client.post(
            "/api/pipeline/start",
            json={"channel_id": channel_id},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "quota_exceeded"
    assert body["data"]["reason"] == "concurrent_run_limit"
    assert body["data"]["max_concurrent_runs"] == 1


def test_resume_blocks_when_transcript_quota_rejects(client):
    """Resume must enforce exact billable transcript minutes after transcripts exist."""
    from backend import storage
    from backend.pipeline.schema_versions import TRANSCRIPT_SCHEMA_VERSION
    from backend.quotas import MonthlyUsage, Quota
    from backend.routes import pipeline as pipeline_module
    from backend.tests.test_quotas import FakeQuotaStore

    channel_id = "UC_test_resume_quota"
    _setup_channel(channel_id, video_count=1)
    storage.save_selection(channel_id, ["vid_0"], owner_id=TEST_OWNER_ID)
    channel_dir = storage.get_channel_dir(channel_id, owner_id=TEST_OWNER_ID)
    storage.write_json(
        channel_dir / "transcripts" / "vid_0.json",
        {
            "schema_version": TRANSCRIPT_SCHEMA_VERSION,
            "video_id": "vid_0",
            "title": "Video 0",
            "upload_date": "20230101",
            "duration_seconds": 60,
            "transcript_text": "word " * 300,
            "word_count": 300,
            "source": "manual",
            "segments": [{"start": 0.0, "text": "word " * 300}],
        },
    )

    with storage.storage_owner(TEST_OWNER_ID):
        pipeline_module._write_pipeline_state(
            channel_id,
            {
                "status": "awaiting_confirm_summaries",
                "current_stage": "awaiting_confirm_summaries",
                "stages": {"transcripts": {"status": "done"}},
            },
        )

    blocking_store = FakeQuotaStore(
        quota=Quota(monthly_transcript_seconds=60),
        usage=MonthlyUsage(transcript_seconds=0),
    )

    with patch.object(pipeline_module, "get_quota_store", return_value=blocking_store):
        resp = client.post(
            "/api/pipeline/resume",
            json={"channel_id": channel_id},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "quota_exceeded"
    assert body["data"]["reason"] == "monthly_transcript_minutes_limit"
    assert body["data"]["run_transcript_seconds"] == 120
    assert body["data"]["estimate"]["estimated_transcript_seconds"] == 120


def test_start_returns_api_response_envelope(client):
    """POST /api/pipeline/start must return an ApiResponse envelope."""
    from backend import storage
    from backend.routes import pipeline as pipeline_module

    channel_id = "UC_test_start"
    _setup_channel(channel_id, video_count=3)
    storage.save_selection(channel_id, [f"vid_{i}" for i in range(3)], owner_id=TEST_OWNER_ID)

    async def fake_run(*args, **kwargs):
        pass

    with patch.object(pipeline_module, "_run_pipeline", fake_run):
        resp = client.post(
            "/api/pipeline/start",
            json={"channel_id": channel_id},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["channel_id"] == channel_id
        assert body["data"]["status"] == "started"


def test_pipeline_state_reports_stale_generated_files(client):
    """Pipeline state should expose stale generated files without rebuilding them."""
    from backend import storage

    channel_id = "UC_test_stale_report"
    _setup_channel(channel_id, video_count=1)
    storage.save_selection(channel_id, ["vid_0"], owner_id=TEST_OWNER_ID)
    channel_dir = storage.get_channel_dir(channel_id, owner_id=TEST_OWNER_ID)

    storage.write_json(
        channel_dir / "transcripts" / "vid_0.json",
        {
            "video_id": "vid_0",
            "title": "Old transcript",
            "transcript_text": "legacy transcript text",
        },
    )
    storage.write_json(
        channel_dir / "summaries" / "vid_0.json",
        {
            "video_id": "vid_0",
            "title": "Old summary",
            "upload_date": "20230101",
            "core_topic": "Legacy",
            "key_claims": ["old claim shape"],
            "recurring_themes": [],
            "tone_markers": [],
            "notable_opinions": [],
            "people_or_things_referenced": [],
        },
    )
    storage.write_json(
        channel_dir / "profile.json",
        {
            "channel_id": channel_id,
            "channel_name": "Test Channel",
            "video_count": 1,
            "date_range": {"first": "20230101", "last": "20230101"},
            "videos": [],
            "rollups": {},
            "generated_at": "2024-01-01T00:00:00",
        },
    )

    resp = client.get(f"/api/pipeline/state?channel_id={channel_id}")

    assert resp.status_code == 200
    body = resp.json()
    report = body["data"]["generated_files"]
    assert report["has_stale"] is True
    assert report["transcripts"]["counts"]["stale"] == 1
    assert report["summaries"]["counts"]["stale"] == 1
    assert report["profile"]["stale"] is True
    assert "missing_segments" in report["transcripts"]["items"]["vid_0"]["stale_reasons"]


def test_pipeline_state_reports_chunk_index_missing_stale_and_current(client):
    """Pipeline state should expose chunk index status without rebuilding it."""
    from backend import storage
    from backend.pipeline.schema_versions import CHUNK_INDEX_SCHEMA_VERSION

    channel_id = "UC_test_chunk_index_report"
    _setup_channel(channel_id, video_count=1)
    storage.save_selection(channel_id, ["vid_0"], owner_id=TEST_OWNER_ID)
    channel_dir = storage.get_channel_dir(channel_id, owner_id=TEST_OWNER_ID)

    resp = client.get(f"/api/pipeline/state?channel_id={channel_id}")
    assert resp.status_code == 200
    report = resp.json()["data"]["generated_files"]
    assert report["chunk_index"]["status"] == "missing"

    storage.write_json(
        channel_dir / "chunk_index.json",
        {"schema_version": CHUNK_INDEX_SCHEMA_VERSION},
    )
    resp = client.get(f"/api/pipeline/state?channel_id={channel_id}")
    assert resp.status_code == 200
    report = resp.json()["data"]["generated_files"]
    assert report["chunk_index"]["status"] == "stale"
    assert "missing_chunks" in report["chunk_index"]["stale_reasons"]

    storage.write_json(
        channel_dir / "chunk_index.json",
        {
            "schema_version": CHUNK_INDEX_SCHEMA_VERSION,
            "channel_id": channel_id,
            "generated_at": "2026-01-01T00:00:00+00:00",
            "chunking": {
                "target_seconds_min": 45,
                "target_seconds_max": 90,
                "target_words_min": 120,
                "target_words_max": 250,
                "overlap_seconds": 15,
            },
            "chunks": [],
        },
    )
    resp = client.get(f"/api/pipeline/state?channel_id={channel_id}")
    assert resp.status_code == 200
    report = resp.json()["data"]["generated_files"]
    assert report["chunk_index"]["status"] == "current"


@pytest.mark.asyncio
async def test_summary_stage_records_evidence_metrics_in_pipeline_state(client):
    """Summary progress should expose Phase 6 evidence metrics per video."""
    from backend import storage
    from backend.pipeline.schema_versions import CHUNK_INDEX_SCHEMA_VERSION
    from backend.routes import pipeline as pipeline_module

    channel_id = "UC_test_summary_metrics"
    _setup_channel(channel_id, video_count=1)
    storage.save_selection(channel_id, ["vid_0"], owner_id=TEST_OWNER_ID)
    channel_dir = storage.get_channel_dir(channel_id, owner_id=TEST_OWNER_ID)
    storage.write_json(
        channel_dir / "chunk_index.json",
        {
            "schema_version": CHUNK_INDEX_SCHEMA_VERSION,
            "channel_id": channel_id,
            "generated_at": "2026-01-01T00:00:00+00:00",
            "chunking": {
                "target_seconds_min": 45,
                "target_seconds_max": 90,
                "target_words_min": 120,
                "target_words_max": 250,
                "overlap_seconds": 15,
            },
            "chunks": [],
        },
    )
    with storage.storage_owner(TEST_OWNER_ID):
        pipeline_module._write_pipeline_state(
            channel_id,
            {
                "status": "awaiting_confirm_summaries",
                "current_stage": "awaiting_confirm_summaries",
                "stages": {"chunks": {"status": "done"}},
            },
        )

    async def fake_summarize(_channel_id: str, on_progress=None):
        if on_progress:
            on_progress(
                {
                    "video_id": "vid_0",
                    "status": "done",
                    "summary_confidence": 0.75,
                    "summary_evidence_rate": 0.667,
                    "claim_count": 3,
                    "supported_claim_count": 2,
                    "unsupported_claim_count": 1,
                }
            )
        await asyncio.sleep(0)
        return {"total": 1, "results": []}

    def fake_aggregate(_channel_id: str):
        return {}

    with (
        patch.object(pipeline_module, "summarize", fake_summarize),
        patch.object(pipeline_module, "aggregate", fake_aggregate),
    ):
        await pipeline_module._run_pipeline_for_owner(
            TEST_OWNER_ID,
            channel_id,
            from_stage="summaries",
        )

    with storage.storage_owner(TEST_OWNER_ID):
        state = pipeline_module._read_pipeline_state(channel_id)
    video_state = state["stages"]["summaries"]["videos"]["vid_0"]
    assert video_state["summary_confidence"] == 0.75
    assert video_state["summary_evidence_rate"] == 0.667
    assert video_state["claim_count"] == 3
    assert video_state["supported_claim_count"] == 2
    assert video_state["unsupported_claim_count"] == 1


def test_channels_dashboard_lists_owned_channels(client):
    """GET /api/channels returns owner-scoped dashboard summaries."""
    from backend import storage
    from backend.routes import pipeline as pipeline_module

    channel_id = "UC_test_dashboard"
    _setup_channel(channel_id, video_count=2)
    channel_dir = storage.get_channel_dir(channel_id, owner_id=TEST_OWNER_ID)
    storage.write_json(channel_dir / "profile.json", {"channel_id": channel_id})
    with storage.storage_owner(TEST_OWNER_ID):
        pipeline_module._write_pipeline_state(
            channel_id,
            {
                "run_id": "run_dashboard",
                "status": "completed",
                "current_stage": "done",
                "stages": {"profile": {"status": "done"}},
                "completed_at": "2026-01-02T00:00:00+00:00",
            },
        )

    resp = client.get("/api/channels")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["channels"] == [
        {
            "kind": "channel",
            "channel_id": channel_id,
            "channel_name": "Test Channel",
            "channel_handle": "@test",
            "avatar_url": "http://example.com/avatar.jpg",
            "subscriber_count": None,
            "total_video_count": None,
            "playlist_id": None,
            "playlist_title": None,
            "owner_channel_id": None,
            "owner_channel_name": None,
            "video_count": 2,
            "has_profile": True,
            "latest_run_status": "completed",
            "updated_at": "2026-01-02T00:00:00+00:00",
        }
    ]


def test_delete_channel_removes_local_channel_data(client):
    """DELETE /api/channels/{id} removes the channel directory and artifacts."""
    from backend import storage

    channel_id = "UC_test_delete"
    _setup_channel(channel_id, video_count=1)
    channel_dir = storage.get_channel_dir(channel_id, owner_id=TEST_OWNER_ID)
    storage.write_json(channel_dir / "profile.json", {"channel_id": channel_id})
    storage.write_json(channel_dir / "transcripts" / "vid_0.json", {"video_id": "vid_0"})

    resp = client.delete(f"/api/channels/{channel_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"] == {"channel_id": channel_id, "deleted": True}
    assert not channel_dir.exists()
    assert storage.load_channel_meta(channel_id, owner_id=TEST_OWNER_ID) is None


def test_refresh_channel_merges_new_videos(client):
    """POST /api/channels/{id}/refresh merges fetched videos into the catalog."""
    from backend import storage

    channel_id = "UC_test_refresh"
    _setup_channel(channel_id, video_count=5)
    fetched = [
        {
            "id": "vid_0",
            "title": "Video 0 updated",
            "upload_date": "20230101",
            "duration": 90,
            "view_count": 999,
            "thumbnail": "http://example.com/updated.jpg",
        },
        {
            "id": "vid_new",
            "title": "New video",
            "upload_date": "20230201",
            "duration": 120,
            "view_count": 5,
            "thumbnail": "http://example.com/new.jpg",
        },
    ]

    with patch("backend.routes.channel.fetch_channel_videos", return_value=fetched) as mock_fetch:
        resp = client.post(f"/api/channels/{channel_id}/refresh")

    assert resp.status_code == 200
    mock_fetch.assert_called_once_with("https://www.youtube.com/@test")
    body = resp.json()
    assert body["ok"] is True
    assert body["data"] == {"channel_id": channel_id, "added": 1, "total": 6}

    saved = storage.load_videos(channel_id, owner_id=TEST_OWNER_ID) or []
    by_id = {v["id"]: v for v in saved}
    assert by_id["vid_0"]["title"] == "Video 0 updated"
    assert by_id["vid_new"]["title"] == "New video"


def test_export_channel_markdown_returns_attachment(client):
    """POST /api/channels/{id}/export/markdown streams a useful Markdown report."""
    from backend import storage

    channel_id = "UC_test_export"
    _setup_channel(channel_id, video_count=1)
    channel_dir = storage.get_channel_dir(channel_id, owner_id=TEST_OWNER_ID)
    storage.write_json(
        channel_dir / "profile.json",
        {
            "channel_id": channel_id,
            "channel_name": "Test Channel",
            "channel_handle": "test",
            "video_count": 1,
            "date_range": {"first": "20230101", "last": "20230101"},
            "videos": [
                {
                    "video_id": "vid_0",
                    "title": "Video 0",
                    "upload_date": "20230101",
                    "core_topic": "Testing",
                    "key_claims": [
                        {
                            "text": "Claims are cited",
                            "evidence": [{"start_seconds": 42, "quote": "evidence"}],
                        }
                    ],
                    "recurring_themes": ["Reliability"],
                    "tone_markers": [],
                    "notable_opinions": [],
                    "people_or_things_referenced": ["Supabase"],
                }
            ],
            "rollups": {
                "all_themes": [{"theme": "Reliability", "count": 1}],
                "all_referenced": [{"name": "Supabase", "count": 1}],
                "tone_distribution": {"pragmatic": 1},
            },
            "generated_at": "2026-01-01T00:00:00+00:00",
        },
    )

    resp = client.post(f"/api/channels/{channel_id}/export/markdown")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert resp.headers["content-disposition"] == 'attachment; filename="test-channel.md"'
    assert "# Test Channel" in resp.text
    assert "## Top themes" in resp.text
    assert "- **Reliability**" in resp.text
    assert "[0:42](https://youtu.be/vid_0?t=42s)" in resp.text


def test_retry_failed_requeues_failed_videos(client):
    """POST /api/pipeline/runs/{run_id}/retry-failed resets only failed work."""
    from backend import storage
    from backend.routes import pipeline as pipeline_module

    channel_id = "UC_test_retry"
    run_id = "run_retry"
    _setup_channel(channel_id, video_count=2)
    with storage.storage_owner(TEST_OWNER_ID):
        pipeline_module._write_pipeline_state(
            channel_id,
            {
                "run_id": run_id,
                "status": "failed",
                "current_stage": "summaries",
                "stages": {
                    "summaries": {
                        "status": "error",
                        "total": 2,
                        "completed": 2,
                        "videos": {
                            "vid_0": {"status": "failed", "title": "Video 0"},
                            "vid_1": {"status": "done", "title": "Video 1"},
                        },
                    }
                },
                "error": "boom",
            },
        )

    async def fake_run(*args, **kwargs):
        return None

    with patch.object(pipeline_module, "_run_pipeline_for_owner", fake_run):
        resp = client.post(f"/api/pipeline/runs/{run_id}/retry-failed")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["run_id"] == run_id
    assert body["data"]["channel_id"] == channel_id
    assert body["data"]["retried"] == 1
    assert body["data"]["status"] == "queued"

    with storage.storage_owner(TEST_OWNER_ID):
        state = pipeline_module._read_pipeline_state(channel_id)
    assert state["status"] == "queued"
    assert state["current_stage"] == "summaries"
    assert state["stages"]["summaries"]["videos"]["vid_0"]["status"] == "queued"
    assert state["stages"]["summaries"]["videos"]["vid_1"]["status"] == "done"
