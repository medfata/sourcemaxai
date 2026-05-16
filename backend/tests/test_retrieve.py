"""Tests for deterministic caption chunk retrieval."""

import importlib
import tempfile

import pytest
from backend.models import ChatScope
from backend.pipeline.retrieve import (
    DEFAULT_CLOSING_WINDOW_SECONDS,
    DEFAULT_OPENING_WINDOW_SECONDS,
    classify_query,
)
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


OPENING_QUERIES: list[str] = [
    "what's the hook in every video",
    "describe the intro of these videos",
    "what happens at the start of each video",
    "how do videos start",
    "how does each video begin",
    "kick off pattern across videos",
    "what is the opening hook in the videos",
    "show me the first 10 seconds of every video",
    "first 30 seconds — what does he say",
    "first 5s of each video",
    "in the first 60 seconds what is mentioned",
    "begin with what kind of line",
]


CLOSING_QUERIES: list[str] = [
    "how do videos end",
    "what is in the outro",
    "describe the closing minute",
    "what is at the end of the video",
    "how does each video end",
    "wrap up patterns",
    "how does he sign off",
    "show me the last 30 seconds",
    "last 60 seconds across all episodes",
    "last 15s of every video",
    "end of the video — what does he say",
    "what does the outro say",
    "how do MrBeast videos typically end?",
    "how do his videos end usually",
]


GLOBAL_QUERIES: list[str] = [
    "what topics appear across all videos",
    "what is the money trend across every video",
    "in each video, what is the call to action",
    "all 50 episodes mention what",
    "every episode references which sponsor",
    "across every video, what is the recurring theme",
    "what people are referenced in all videos",
    "all of the videos cover what topic",
    "in all videos, what gets repeated",
    "what is in every video about food",
]


LEXICAL_QUERIES: list[str] = [
    "what did he say about feastables",
    "how much money was given away",
    "explain the engineering trade offs",
    "who is the cameraman",
    "what tool was used in episode three",
    "is the chocolate bar mentioned",
    "what is the recurring joke",
    "tell me about the cooking experiment",
    "what does he say about sponsors",
    "summarize the deep dive on architecture",
]


@pytest.mark.parametrize("query", OPENING_QUERIES)
def test_classify_query_opening_phrasings(query: str) -> None:
    intent = classify_query(query)
    assert intent.mode == "opening", f"expected opening for {query!r}, got {intent}"
    assert intent.seconds_window is not None
    assert intent.seconds_window > 0


@pytest.mark.parametrize("query", CLOSING_QUERIES)
def test_classify_query_closing_phrasings(query: str) -> None:
    intent = classify_query(query)
    assert intent.mode == "closing", f"expected closing for {query!r}, got {intent}"
    assert intent.seconds_window is not None
    assert intent.seconds_window > 0


@pytest.mark.parametrize("query", GLOBAL_QUERIES)
def test_classify_query_global_phrasings(query: str) -> None:
    intent = classify_query(query)
    assert intent.mode == "lexical_global", f"expected lexical_global for {query!r}, got {intent}"
    assert intent.seconds_window is None


@pytest.mark.parametrize("query", LEXICAL_QUERIES)
def test_classify_query_lexical_default(query: str) -> None:
    intent = classify_query(query)
    assert intent.mode == "lexical", f"expected lexical for {query!r}, got {intent}"
    assert intent.seconds_window is None


@pytest.mark.parametrize(
    "query,expected",
    [
        ("first 10 seconds of every video", 10),
        ("first 30 seconds", 30),
        ("first 5s of each video", 5),
        ("first 60 secs across the videos", 60),
        ("FIRST 45 Seconds", 45),
    ],
)
def test_classify_query_opening_numeric_window(query: str, expected: int) -> None:
    intent = classify_query(query)
    assert intent.mode == "opening"
    assert intent.seconds_window == expected


@pytest.mark.parametrize(
    "query,expected",
    [
        ("last 10 seconds", 10),
        ("show me the last 30 seconds of every video", 30),
        ("last 60s across episodes", 60),
        ("last 5 sec of each video", 5),
        ("LAST 90 seconds", 90),
    ],
)
def test_classify_query_closing_numeric_window(query: str, expected: int) -> None:
    intent = classify_query(query)
    assert intent.mode == "closing"
    assert intent.seconds_window == expected


def test_classify_query_default_windows() -> None:
    opening = classify_query("describe the intro of every video")
    assert opening.mode == "opening"
    assert opening.seconds_window == DEFAULT_OPENING_WINDOW_SECONDS

    closing = classify_query("describe the outro of every video")
    assert closing.mode == "closing"
    assert closing.seconds_window == DEFAULT_CLOSING_WINDOW_SECONDS


@pytest.mark.parametrize(
    "query,expected_mode",
    [
        ("I want to start using Feastables", "lexical"),
        ("how do I begin investing", "lexical"),
        ("an open conversation about engineering", "lexical"),
        ("we should start a new project together", "lexical"),
    ],
)
def test_classify_query_does_not_overfit_on_bare_verbs(query: str, expected_mode: str) -> None:
    intent = classify_query(query)
    assert intent.mode == expected_mode, f"{query!r} should be {expected_mode}, got {intent}"


def test_classify_query_empty_and_none_safe() -> None:
    for query in ("", "   "):
        intent = classify_query(query)
        assert intent.mode == "lexical"
        assert intent.seconds_window is None


def test_opening_mode_returns_first_chunk_per_video(synthetic_chunk_index):
    fixture = synthetic_chunk_index
    results = fixture.retrieve.retrieve_context(
        fixture.channel_id,
        "what is the hook in the first 10 seconds of every video",
        limit=12,
    )

    assert len(results) == 5
    assert len({source["video_id"] for source in results}) == 5
    assert all(source["start_seconds"] <= 10 for source in results)
    assert all(source["score"] == 1.0 for source in results)
    upload_dates = [source["upload_date"] for source in results]
    assert upload_dates == sorted(upload_dates), "expected upload_date ascending order"


def test_opening_mode_respects_seconds_window(synthetic_chunk_index):
    fixture = synthetic_chunk_index
    results = fixture.retrieve.retrieve_context(
        fixture.channel_id,
        "first 1 seconds of every video",
        limit=12,
    )

    assert {source["video_id"] for source in results} <= {"vid_0", "vid_1", "vid_2"}
    assert all(source["start_seconds"] <= 1 for source in results)


def test_closing_mode_returns_last_chunk_per_video(synthetic_chunk_index):
    fixture = synthetic_chunk_index
    results = fixture.retrieve.retrieve_context(
        fixture.channel_id,
        "how do videos end across every video",
        limit=12,
    )

    assert len(results) == 5
    assert len({source["video_id"] for source in results}) == 5
    for source in results:
        per_video_max_end = max(
            chunk["end_seconds"]
            for chunk in fixture.chunk_index["chunks"]
            if chunk["video_id"] == source["video_id"]
        )
        assert source["end_seconds"] == per_video_max_end


def test_lexical_global_bumps_limit_beyond_caller_value(synthetic_chunk_index):
    fixture = synthetic_chunk_index
    global_results = fixture.retrieve.retrieve_context(
        fixture.channel_id,
        "money across every video",
        limit=1,
    )
    plain_results = fixture.retrieve.retrieve_context(
        fixture.channel_id,
        "money",
        limit=1,
    )

    assert len(global_results) > len(plain_results), (
        "lexical_global limit should widen beyond caller's limit=1"
    )
    assert len({source["video_id"] for source in global_results}) >= 2


def test_structural_modes_respect_date_scope(synthetic_chunk_index):
    fixture = synthetic_chunk_index
    scope = ChatScope(date_from="20250301")

    results = fixture.retrieve.retrieve_context(
        fixture.channel_id,
        "hook in the first 10 seconds of every video",
        scope=scope,
        limit=12,
    )

    returned_dates = {source["upload_date"] for source in results}
    assert returned_dates, "expected at least one structural pick after date filter"
    assert all(date >= "20250301" for date in returned_dates)
    assert {source["video_id"] for source in results} == {"vid_2", "vid_3", "vid_4"}
