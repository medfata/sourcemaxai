"""Tests for deterministic caption chunk retrieval."""

import importlib
import tempfile

import pytest
from backend.models import ChatScope
from backend.pipeline.schema_versions import CHUNK_INDEX_SCHEMA_VERSION


@pytest.fixture
def retrieve_env(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("DATA_DIR", tmpdir)

        from backend import storage
        from backend.pipeline import retrieve

        importlib.reload(storage)
        importlib.reload(retrieve)
        yield storage, retrieve


def _chunk(
    chunk_id: str,
    *,
    video_id: str | None = None,
    title: str = "Video",
    upload_date: str = "20240101",
    start_seconds: int = 0,
    end_seconds: int = 60,
    text: str = "caption text",
) -> dict:
    return {
        "chunk_id": chunk_id,
        "video_id": video_id or chunk_id.split(":")[0],
        "title": title,
        "upload_date": upload_date,
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
        "text": text,
        "word_count": len(text.split()),
    }


def _write_chunk_index(storage, channel_id: str, chunks: list[dict], **overrides) -> None:
    data = {
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
        "chunks": chunks,
    }
    data.update(overrides)
    storage.write_json(storage.get_channel_dir(channel_id) / "chunk_index.json", data)


def test_missing_stale_and_invalid_chunk_index_return_empty(retrieve_env):
    storage, retrieve = retrieve_env

    assert retrieve.retrieve_context("UC_missing", "alpha beta") == []

    channel_id = "UC_stale"
    storage.write_json(
        storage.get_channel_dir(channel_id) / "chunk_index.json",
        {"schema_version": CHUNK_INDEX_SCHEMA_VERSION, "channel_id": channel_id},
    )
    assert retrieve.retrieve_context(channel_id, "alpha beta") == []

    channel_id = "UC_invalid"
    storage.write_json(storage.get_channel_dir(channel_id) / "chunk_index.json", [])
    assert retrieve.retrieve_context(channel_id, "alpha beta") == []


def test_relevant_phrase_retrieves_expected_chunk(retrieve_env):
    storage, retrieve = retrieve_env
    channel_id = "UC_phrase"
    _write_chunk_index(
        storage,
        channel_id,
        [
            _chunk("vid_a:0000", text="This section is about cooking pasta and tomato sauce."),
            _chunk(
                "vid_b:0000",
                title="Building durable software",
                text="The team explains delayed gratification as a core engineering habit.",
            ),
        ],
    )

    results = retrieve.retrieve_context(channel_id, "delayed gratification")

    assert results[0]["chunk_id"] == "vid_b:0000"
    assert results[0]["source_id"] == "S1"
    assert results[0]["kind"] == "chunk"


def test_exact_phrase_match_beats_loose_token_match(retrieve_env):
    storage, retrieve = retrieve_env
    channel_id = "UC_exact_phrase"
    _write_chunk_index(
        storage,
        channel_id,
        [
            _chunk(
                "loose:0000",
                text=(
                    "Alpha is introduced first. Several unrelated ideas appear before "
                    "beta returns."
                ),
            ),
            _chunk("exact:0000", text="The useful idea here is alpha beta working together."),
        ],
    )

    results = retrieve.retrieve_context(channel_id, "alpha beta")

    assert [result["chunk_id"] for result in results[:2]] == ["exact:0000", "loose:0000"]
    assert results[0]["score"] > results[1]["score"]


def test_date_scope_filters_results(retrieve_env):
    storage, retrieve = retrieve_env
    channel_id = "UC_date_scope"
    _write_chunk_index(
        storage,
        channel_id,
        [
            _chunk("old:0000", upload_date="20230101", text="The roadmap mentions alpha beta."),
            _chunk("new:0000", upload_date="20240101", text="The roadmap mentions alpha beta."),
        ],
    )

    results = retrieve.retrieve_context(
        channel_id,
        "alpha beta",
        scope=ChatScope(date_from="20240101"),
    )

    assert [result["chunk_id"] for result in results] == ["new:0000"]


def test_index_selected_video_ids_filter_results(retrieve_env):
    storage, retrieve = retrieve_env
    channel_id = "UC_selected_only"
    _write_chunk_index(
        storage,
        channel_id,
        [
            _chunk("inside:0000", video_id="inside", text="selection token"),
            _chunk("outside:0000", video_id="outside", text="selection token"),
        ],
        source={"selected_video_ids": ["inside"]},
    )

    results = retrieve.retrieve_context(channel_id, "selection")

    assert [result["chunk_id"] for result in results] == ["inside:0000"]


def test_source_ids_and_tie_ordering_are_deterministic(retrieve_env):
    storage, retrieve = retrieve_env
    channel_id = "UC_ordering"
    _write_chunk_index(
        storage,
        channel_id,
        [
            _chunk("vid_c:0000", video_id="vid_c", upload_date="20240102", text="shared token"),
            _chunk(
                "vid_b:0000",
                video_id="vid_b",
                upload_date="20240101",
                start_seconds=10,
                text="shared token",
            ),
            _chunk(
                "vid_a:0001",
                video_id="vid_a",
                upload_date="20240101",
                start_seconds=20,
                text="shared token",
            ),
            _chunk(
                "vid_a:0000",
                video_id="vid_a",
                upload_date="20240101",
                start_seconds=10,
                text="shared token",
            ),
        ],
    )

    first = retrieve.retrieve_context(channel_id, "shared")
    second = retrieve.retrieve_context(channel_id, "shared")

    assert first == second
    assert [result["source_id"] for result in first] == ["S1", "S2", "S3", "S4"]
    assert [result["chunk_id"] for result in first] == [
        "vid_a:0000",
        "vid_a:0001",
        "vid_b:0000",
        "vid_c:0000",
    ]


def test_limit_is_respected(retrieve_env):
    storage, retrieve = retrieve_env
    channel_id = "UC_limit"
    _write_chunk_index(
        storage,
        channel_id,
        [
            _chunk(f"vid_{index}:0000", video_id=f"vid_{index}", text="limit token")
            for index in range(5)
        ],
    )

    results = retrieve.retrieve_context(channel_id, "limit", limit=2)

    assert len(results) == 2
    assert [result["source_id"] for result in results] == ["S1", "S2"]


def test_quote_contains_matched_terms_when_practical(retrieve_env):
    storage, retrieve = retrieve_env
    channel_id = "UC_quote"
    text = (
        " ".join(f"intro{index}" for index in range(80))
        + " durable retrieval evidence should appear in this nearby quote "
        + " ".join(f"outro{index}" for index in range(80))
    )
    _write_chunk_index(storage, channel_id, [_chunk("vid_quote:0000", text=text)])

    results = retrieve.retrieve_context(channel_id, "durable retrieval")

    assert len(results) == 1
    assert "durable retrieval" in results[0]["quote"].casefold()
    assert len(results[0]["quote"]) <= 240
