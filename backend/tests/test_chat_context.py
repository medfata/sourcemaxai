"""Tests for compact retrieval-backed chat context construction."""

import importlib
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.models import ChatScope


@pytest.fixture
def chat_context_env(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("DATA_DIR", tmpdir)

        from backend import storage
        from backend.pipeline import chat_context

        importlib.reload(storage)
        importlib.reload(chat_context)
        yield Path(tmpdir), storage, chat_context


def _write_profile(storage, channel_id: str = "UC_context") -> None:
    profile = {
        "schema_version": 2,
        "channel_id": channel_id,
        "channel_name": "Context Channel",
        "video_count": 2,
        "date_range": {"first": "20230101", "last": "20231231"},
        "videos": [
            {
                "video_id": "v1",
                "title": "Old Full Profile Title",
                "upload_date": "20230101",
                "recurring_themes": ["AI"],
                "tone_markers": ["analytical"],
            },
            {
                "video_id": "v2",
                "title": "New Full Profile Title",
                "upload_date": "20231231",
                "recurring_themes": ["ML"],
                "tone_markers": ["energetic"],
            },
        ],
        "rollups": {
            "all_themes": [{"theme": "AI", "count": 3}, {"theme": "ML", "count": 2}],
            "all_referenced": [{"name": "OpenAI", "count": 2}],
            "tone_distribution": {"analytical": 2, "energetic": 1},
        },
        "generated_at": "2024-01-01T00:00:00",
    }
    storage.write_json(storage.get_channel_dir(channel_id) / "profile.json", profile)


def _source(source_id: str = "S1") -> dict:
    return {
        "source_id": source_id,
        "kind": "chunk",
        "chunk_id": "v2:0000",
        "video_id": "v2",
        "title": "Retrieved Video",
        "upload_date": "20231231",
        "start_seconds": 42,
        "end_seconds": 95,
        "quote": "retrieved quote about compounding evidence",
        "text": "The retrieved caption chunk explains compounding evidence in detail.",
        "score": 9.5,
    }


def test_context_builder_includes_channel_card_and_profile_hints(chat_context_env):
    _, storage, chat_context = chat_context_env
    channel_id = "UC_context"
    _write_profile(storage, channel_id)

    with patch.object(chat_context, "retrieve_context", return_value=[]):
        context = chat_context.build_chat_context(
            channel_id,
            [{"role": "user", "content": "What is this channel about?"}],
        )

    assert context.error is None
    assert "channel_name: Context Channel" in context.system_prompt
    assert "video_count: 2" in context.system_prompt
    assert "date_range: 20230101..20231231" in context.system_prompt
    assert "top_themes: AI (3), ML (2)" in context.system_prompt
    assert "top_references: OpenAI (2)" in context.system_prompt
    assert "tone_distribution: analytical (2), energetic (1)" in context.system_prompt
    assert "Old Full Profile Title" not in context.system_prompt
    assert "New Full Profile Title" not in context.system_prompt


def test_source_pack_includes_retrieved_chunks_and_source_ids(chat_context_env):
    _, storage, chat_context = chat_context_env
    channel_id = "UC_sources"
    _write_profile(storage, channel_id)

    with patch.object(chat_context, "retrieve_context", return_value=[_source("S1")]):
        context = chat_context.build_chat_context(
            channel_id,
            [{"role": "user", "content": "Explain compounding evidence"}],
        )

    assert "[S1] kind=chunk" in context.system_prompt
    assert "chunk_id=v2:0000" in context.system_prompt
    assert "quote: \"retrieved quote about compounding evidence\"" in context.system_prompt
    assert (
        "caption: \"The retrieved caption chunk explains compounding evidence in detail.\""
        in context.system_prompt
    )
    assert context.sources[0]["source_id"] == "S1"


def test_missing_profile_returns_profile_not_found(chat_context_env):
    _, _, chat_context = chat_context_env

    context = chat_context.build_chat_context(
        "UC_missing",
        [{"role": "user", "content": "hello"}],
    )

    assert context.error == "profile_not_found"


def test_empty_retrieval_adds_insufficient_caption_evidence_context(chat_context_env):
    _, storage, chat_context = chat_context_env
    channel_id = "UC_empty_retrieval"
    _write_profile(storage, channel_id)

    with patch.object(chat_context, "retrieve_context", return_value=[]):
        context = chat_context.build_chat_context(
            channel_id,
            [{"role": "user", "content": "What did they say about an obscure topic?"}],
        )

    assert "(no retrieved caption sources)" in context.system_prompt
    assert "not enough caption evidence" in context.system_prompt
    assert context.sources == []


def test_only_recent_conversation_history_is_included(chat_context_env):
    _, storage, chat_context = chat_context_env
    channel_id = "UC_history"
    _write_profile(storage, channel_id)
    messages = [
        {"role": "user", "content": f"old question {index}"}
        for index in range(10)
    ]
    messages.append({"role": "assistant", "content": "latest assistant"})
    messages.append({"role": "user", "content": "latest user query"})

    with patch.object(chat_context, "retrieve_context", return_value=[_source("S1")]):
        context = chat_context.build_chat_context(channel_id, messages)

    history_text = "\n".join(message["content"] for message in context.messages)
    assert len(context.messages) == chat_context.HISTORY_MESSAGE_LIMIT
    assert "old question 0" not in history_text
    assert "old question 1" not in history_text
    assert "latest assistant" in history_text
    assert "latest user query" in history_text
    assert "[S1] kind=chunk" in context.system_prompt


def test_scope_is_passed_into_retrieve_context(chat_context_env):
    _, storage, chat_context = chat_context_env
    channel_id = "UC_scope"
    _write_profile(storage, channel_id)
    scope = ChatScope(date_from="20231201", themes=["ML"])

    with patch.object(chat_context, "retrieve_context", return_value=[]) as mock_retrieve:
        chat_context.build_chat_context(
            channel_id,
            [{"role": "user", "content": "What changed recently?"}],
            scope,
        )

    mock_retrieve.assert_called_once()
    assert mock_retrieve.call_args.args[:2] == (channel_id, "What changed recently?")
    assert mock_retrieve.call_args.kwargs["scope"] is scope
    assert mock_retrieve.call_args.kwargs["limit"] == chat_context.SOURCE_LIMIT
