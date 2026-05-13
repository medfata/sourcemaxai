"""Tests for storage adapter compatibility and configuration."""

import importlib

import pytest


def _reload_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from backend import storage

    return importlib.reload(storage)


def test_legacy_helpers_preserve_local_layout(monkeypatch, tmp_path):
    storage = _reload_storage(monkeypatch, tmp_path)
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)

    channel_id = "UC_storage"
    meta = {
        "channel_id": channel_id,
        "channel_name": "Storage Channel",
        "channel_handle": "@storage",
        "avatar_url": "https://example.com/avatar.jpg",
    }
    videos = [
        {
            "id": "vid_1",
            "title": "One",
            "upload_date": "20260101",
            "duration": 61,
            "view_count": 10,
            "thumbnail": "https://example.com/thumb.jpg",
            "is_short": False,
        }
    ]

    assert storage.load_channel_meta(channel_id) is None

    storage.save_channel_meta(channel_id, meta)
    storage.save_videos(channel_id, videos)
    storage.save_selection(channel_id, ["vid_1"])

    channel_dir = storage.get_channel_dir(channel_id)
    assert channel_dir == tmp_path.resolve() / "channels" / channel_id
    assert storage.load_channel_meta(channel_id) == meta
    assert storage.load_videos(channel_id) == videos
    assert storage.load_selection(channel_id) == ["vid_1"]

    storage.write_json(channel_dir / "custom.json", {"ok": True})
    assert storage.read_json(channel_dir / "custom.json") == {"ok": True}


def test_local_backend_owner_aware_artifacts(monkeypatch, tmp_path):
    storage = _reload_storage(monkeypatch, tmp_path)
    backend = storage.LocalStorageBackend()

    channel_id = "UC_artifacts"
    backend.save_transcript(
        "owner-a",
        channel_id,
        "run-1",
        "vid_1",
        {"schema_version": 1, "text": "transcript"},
    )
    backend.save_summary(
        "owner-a",
        channel_id,
        "run-1",
        "vid_1",
        {"schema_version": 1, "core_topic": "summary"},
    )
    backend.save_profile(
        "owner-a",
        channel_id,
        "run-1",
        {"schema_version": 1, "channel_id": channel_id},
    )

    assert backend.load_transcript("owner-a", channel_id, "vid_1") == {
        "schema_version": 1,
        "text": "transcript",
    }
    assert backend.load_summary("owner-a", channel_id, "vid_1") == {
        "schema_version": 1,
        "core_topic": "summary",
    }
    assert backend.load_profile("owner-a", channel_id) == {
        "schema_version": 1,
        "channel_id": channel_id,
    }
    assert backend.load_transcript("owner-b", channel_id, "vid_1") is None
    assert backend.load_summary("owner-b", channel_id, "vid_1") is None
    assert backend.load_profile("owner-b", channel_id) is None


def test_storage_owner_context_scopes_local_helpers(monkeypatch, tmp_path):
    storage = _reload_storage(monkeypatch, tmp_path)
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)

    channel_id = "UC_owner_context"

    with storage.storage_owner("owner-a"):
        storage.save_channel_meta(channel_id, {"channel_id": channel_id, "channel_name": "A"})
        storage.save_videos(channel_id, [{"id": "vid_a", "title": "A"}])

    with storage.storage_owner("owner-b"):
        assert storage.load_channel_meta(channel_id) is None
        storage.save_channel_meta(channel_id, {"channel_id": channel_id, "channel_name": "B"})
        storage.save_videos(channel_id, [{"id": "vid_b", "title": "B"}])

    with storage.storage_owner("owner-a"):
        assert storage.get_channel_dir(channel_id) == (
            tmp_path.resolve() / "users" / "owner-a" / "channels" / channel_id
        )
        assert storage.load_channel_meta(channel_id)["channel_name"] == "A"
        assert storage.load_videos(channel_id) == [{"id": "vid_a", "title": "A"}]

    with storage.storage_owner("owner-b"):
        assert storage.load_channel_meta(channel_id)["channel_name"] == "B"
        assert storage.load_videos(channel_id) == [{"id": "vid_b", "title": "B"}]


def test_get_storage_backend_defaults_to_local(monkeypatch, tmp_path):
    storage = _reload_storage(monkeypatch, tmp_path)
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)

    assert isinstance(storage.get_storage_backend(), storage.LocalStorageBackend)


def test_get_storage_backend_rejects_unknown_backend(monkeypatch, tmp_path):
    storage = _reload_storage(monkeypatch, tmp_path)
    monkeypatch.setenv("STORAGE_BACKEND", "unknown")

    with pytest.raises(storage.StorageConfigError, match="Unsupported STORAGE_BACKEND"):
        storage.get_storage_backend()


def test_supabase_backend_requires_url_and_service_role_key(monkeypatch, tmp_path):
    storage = _reload_storage(monkeypatch, tmp_path)
    monkeypatch.setenv("STORAGE_BACKEND", "supabase")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    with pytest.raises(storage.StorageConfigError, match="SUPABASE_URL"):
        storage.get_storage_backend()

    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    with pytest.raises(storage.StorageConfigError, match="SUPABASE_SERVICE_ROLE_KEY"):
        storage.get_storage_backend()

    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-secret")
    backend = storage.get_storage_backend()

    assert isinstance(backend, storage.SupabaseStorageBackend)
    assert backend.supabase_url == "https://project.supabase.co"


def test_legacy_helpers_stay_local_when_supabase_selected(monkeypatch, tmp_path):
    storage = _reload_storage(monkeypatch, tmp_path)
    monkeypatch.setenv("STORAGE_BACKEND", "supabase")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    channel_id = "UC_local_even_in_supabase_mode"
    storage.save_videos(channel_id, [{"id": "vid_1", "title": "Local"}])
    storage.save_selection(channel_id, ["vid_1"])

    assert storage.load_videos(channel_id) == [{"id": "vid_1", "title": "Local"}]
    assert storage.load_selection(channel_id) == ["vid_1"]


def test_supabase_artifact_paths_are_phase_3_deterministic():
    from backend import storage

    backend = storage.SupabaseStorageBackend(
        "https://project.supabase.co",
        "service-role-secret",
    )

    assert backend.artifact_path(
        "owner-id",
        "channel-id",
        "run-id",
        "transcript",
        video_id="video-id",
    ) == "owner-id/channel-id/run-id/transcripts/video-id.json"
    assert backend.artifact_path(
        "owner-id",
        "channel-id",
        "run-id",
        "summary",
        video_id="video-id",
    ) == "owner-id/channel-id/run-id/summaries/video-id.json"
    assert (
        backend.artifact_path("owner-id", "channel-id", "run-id", "profile")
        == "owner-id/channel-id/run-id/profile.json"
    )
