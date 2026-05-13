"""Tests for deterministic transcript chunk index generation."""

import importlib
import tempfile

import pytest


@pytest.fixture
def chunk_env(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("DATA_DIR", tmpdir)
        from backend import storage
        from backend.pipeline import chunk_transcripts

        importlib.reload(storage)
        importlib.reload(chunk_transcripts)
        yield storage, chunk_transcripts


def _setup_channel(storage, channel_id: str, video_ids: list[str]) -> None:
    videos = [
        {
            "id": video_id,
            "title": f"Video {index}",
            "upload_date": f"202401{index + 1:02d}",
            "duration": 240,
            "view_count": 100,
            "thumbnail": "https://example.com/thumb.jpg",
        }
        for index, video_id in enumerate(video_ids)
    ]
    channel_dir = storage.get_channel_dir(channel_id)
    storage.write_json(channel_dir / "videos.json", {"videos": videos})
    storage.save_selection(channel_id, video_ids)


def _segments(count: int = 20, step: int = 10) -> list[dict]:
    return [
        {
            "start": index * step,
            "text": " ".join(f"word{index}_{word}" for word in range(24)),
        }
        for index in range(count)
    ]


def _write_transcript(
    storage,
    channel_id: str,
    video_id: str,
    *,
    title: str = "Transcript title",
    upload_date: str = "20240101",
    source: str = "manual",
    segments: list[dict] | None = None,
    schema_version: int | None = None,
) -> None:
    from backend.pipeline.schema_versions import TRANSCRIPT_SCHEMA_VERSION

    transcript_segments = segments if segments is not None else _segments()
    transcript_text = " ".join(segment["text"] for segment in transcript_segments)
    data = {
        "video_id": video_id,
        "title": title,
        "upload_date": upload_date,
        "duration_seconds": 240,
        "transcript_text": transcript_text,
        "word_count": len(transcript_text.split()),
        "source": source,
        "segments": transcript_segments,
    }
    if schema_version is None:
        data["schema_version"] = TRANSCRIPT_SCHEMA_VERSION
    elif schema_version >= 0:
        data["schema_version"] = schema_version
    storage.write_json(
        storage.get_channel_dir(channel_id) / "transcripts" / f"{video_id}.json",
        data,
    )


def test_chunk_index_has_deterministic_ids_and_stable_output(chunk_env):
    storage, chunk_transcripts = chunk_env
    channel_id = "UC_chunks_stable"
    _setup_channel(storage, channel_id, ["vid_a"])
    _write_transcript(storage, channel_id, "vid_a")

    first_result = chunk_transcripts.build_chunk_index(
        channel_id,
        generated_at="2026-01-01T00:00:00+00:00",
    )
    first = storage.read_json(storage.get_channel_dir(channel_id) / "chunk_index.json")

    second_result = chunk_transcripts.build_chunk_index(
        channel_id,
        generated_at="2099-01-01T00:00:00+00:00",
    )
    second = storage.read_json(storage.get_channel_dir(channel_id) / "chunk_index.json")

    assert [chunk["chunk_id"] for chunk in first["chunks"]] == [
        f"vid_a:{index:04d}" for index in range(len(first["chunks"]))
    ]
    assert first == second
    assert first_result["chunk_count"] == second_result["chunk_count"]


def test_chunk_start_and_end_are_real_segment_timestamps(chunk_env):
    storage, chunk_transcripts = chunk_env
    channel_id = "UC_chunks_timestamps"
    starts = {segment["start"] for segment in _segments(count=24, step=10)}
    _setup_channel(storage, channel_id, ["vid_a"])
    _write_transcript(storage, channel_id, "vid_a", segments=_segments(count=24, step=10))

    result = chunk_transcripts.build_chunk_index(channel_id)
    chunks = result["data"]["chunks"]

    assert chunks
    for chunk in chunks:
        assert chunk["start_seconds"] in starts
        assert chunk["end_seconds"] in starts
        assert chunk["start_seconds"] <= chunk["end_seconds"]


def test_stale_and_legacy_transcripts_are_skipped(chunk_env):
    storage, chunk_transcripts = chunk_env
    from backend.pipeline.schema_versions import TRANSCRIPT_SCHEMA_VERSION

    channel_id = "UC_chunks_stale"
    _setup_channel(storage, channel_id, ["current", "legacy", "no_segments"])
    _write_transcript(storage, channel_id, "current")
    _write_transcript(storage, channel_id, "legacy", schema_version=-1)
    storage.write_json(
        storage.get_channel_dir(channel_id) / "transcripts" / "no_segments.json",
        {
            "schema_version": TRANSCRIPT_SCHEMA_VERSION,
            "video_id": "no_segments",
            "title": "No segments",
            "upload_date": "20240103",
            "source": "manual",
        },
    )

    result = chunk_transcripts.build_chunk_index(channel_id)
    index = result["data"]

    assert {chunk["video_id"] for chunk in index["chunks"]} == {"current"}
    skipped = {item["video_id"]: item["reasons"] for item in index["skipped"]}
    assert "missing_schema_version" in skipped["legacy"]
    assert "missing_segments" in skipped["no_segments"]


def test_unavailable_transcripts_are_skipped(chunk_env):
    storage, chunk_transcripts = chunk_env
    channel_id = "UC_chunks_unavailable"
    _setup_channel(storage, channel_id, ["available", "unavailable"])
    _write_transcript(storage, channel_id, "available")
    _write_transcript(
        storage,
        channel_id,
        "unavailable",
        source="unavailable",
        segments=[],
    )

    result = chunk_transcripts.build_chunk_index(channel_id)
    index = result["data"]

    assert {chunk["video_id"] for chunk in index["chunks"]} == {"available"}
    skipped = {item["video_id"]: item["reasons"] for item in index["skipped"]}
    assert skipped["unavailable"] == ["unavailable"]


def test_newly_written_chunk_index_is_current(chunk_env):
    storage, chunk_transcripts = chunk_env
    from backend.pipeline.schema_versions import is_chunk_index_current

    channel_id = "UC_chunks_current"
    _setup_channel(storage, channel_id, ["vid_a"])
    _write_transcript(storage, channel_id, "vid_a")

    result = chunk_transcripts.build_chunk_index(channel_id)

    assert is_chunk_index_current(result["data"])
