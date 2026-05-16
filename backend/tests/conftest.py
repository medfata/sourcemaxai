"""Shared pytest fixtures for backend tests."""

from __future__ import annotations

import importlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from backend.pipeline.schema_versions import (
    CHUNK_INDEX_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION,
    SUMMARY_SCHEMA_VERSION,
)

SYNTHETIC_CHANNEL_ID = "UC_synthetic_rag"

_VIDEO_SPECS: list[dict[str, Any]] = [
    {
        "video_id": "vid_0",
        "title": "Wilderness opening with a hook",
        "upload_date": "20250101",
        "duration_seconds": 300,
        "themes": ["adventure", "survival"],
        "tones": ["energetic"],
        "chunks": [
            {
                "start": 0,
                "end": 90,
                "text": (
                    "Today I am stranded in the wilderness and the first hook you "
                    "will see is whether I can survive the opening minutes alone."
                ),
            },
            {
                "start": 95,
                "end": 195,
                "text": (
                    "Halfway in we build a shelter and discuss why the first ten "
                    "seconds of every adventure decide whether viewers stay."
                ),
            },
            {
                "start": 200,
                "end": 295,
                "text": (
                    "Finally at the end I thank the crew and remind everyone to "
                    "subscribe before the closing shot fades to black."
                ),
            },
        ],
    },
    {
        "video_id": "vid_1",
        "title": "Studio chat about creative work",
        "upload_date": "20250201",
        "duration_seconds": 320,
        "themes": ["creative", "studio"],
        "tones": ["analytical"],
        "chunks": [
            {
                "start": 1,
                "end": 95,
                "text": (
                    "Watch this from the start because the hook today is a "
                    "behind the scenes intro you have never seen before."
                ),
            },
            {
                "start": 100,
                "end": 210,
                "text": (
                    "Mid video we break down studio workflow and the tools we "
                    "rely on for editing long form creative output."
                ),
            },
            {
                "start": 215,
                "end": 315,
                "text": (
                    "As we wrap up the outro recap covers the lessons learned "
                    "and the closing call to action for next week."
                ),
            },
        ],
    },
    {
        "video_id": "vid_2",
        "title": "Money giveaway across the city",
        "upload_date": "20250301",
        "duration_seconds": 280,
        "themes": ["money", "giveaway"],
        "tones": ["energetic"],
        "chunks": [
            {
                "start": 0,
                "end": 80,
                "text": (
                    "Right at the start of this video I am about to hand out "
                    "money to strangers and the hook lands in seconds."
                ),
            },
            {
                "start": 85,
                "end": 190,
                "text": (
                    "We give away money on every block, more money than last "
                    "time, and the money keeps flowing through the whole city."
                ),
            },
            {
                "start": 195,
                "end": 275,
                "text": (
                    "By the end of the day the money is gone and we close out "
                    "with a thank you to the team that made it happen."
                ),
            },
        ],
    },
    {
        "video_id": "vid_3",
        "title": "Engineering deep dive",
        "upload_date": "20250401",
        "duration_seconds": 360,
        "themes": ["engineering", "deep_dive"],
        "tones": ["analytical"],
        "chunks": [
            {
                "start": 2,
                "end": 110,
                "text": (
                    "Welcome back, the intro hook here is a system design "
                    "puzzle we will solve together inside the first minute."
                ),
            },
            {
                "start": 115,
                "end": 240,
                "text": (
                    "In the middle section we walk through trade offs and "
                    "compare three architectures for durable retrieval."
                ),
            },
            {
                "start": 245,
                "end": 355,
                "text": (
                    "The ending recaps the trade off matrix and points to a "
                    "follow up video that closes out the deep dive series."
                ),
            },
        ],
    },
    {
        "video_id": "vid_4",
        "title": "Cooking experiment finale",
        "upload_date": "20250501",
        "duration_seconds": 240,
        "themes": ["cooking", "experiment"],
        "tones": ["playful"],
        "chunks": [
            {
                "start": 3,
                "end": 80,
                "text": (
                    "From the very start watch what happens when I open the "
                    "fridge for the hook of this cooking experiment."
                ),
            },
            {
                "start": 85,
                "end": 165,
                "text": (
                    "Halfway through we taste the dish and react to whether "
                    "the unusual ingredient combination actually works."
                ),
            },
            {
                "start": 170,
                "end": 235,
                "text": (
                    "At the end of the cook we plate up, score the dish, and "
                    "the outro thanks viewers for sticking around."
                ),
            },
        ],
    },
]


@dataclass(frozen=True)
class SyntheticChunkIndex:
    """Handle to a synthetic chunk index written under a temp DATA_DIR."""

    channel_id: str
    data_dir: Path
    chunk_index: dict[str, Any]
    profile: dict[str, Any]
    storage: Any
    retrieve: Any


def _build_chunks() -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for spec in _VIDEO_SPECS:
        for chunk_index, chunk in enumerate(spec["chunks"]):
            text = chunk["text"]
            chunks.append(
                {
                    "chunk_id": f"{spec['video_id']}:{chunk_index:04d}",
                    "video_id": spec["video_id"],
                    "title": spec["title"],
                    "upload_date": spec["upload_date"],
                    "start_seconds": chunk["start"],
                    "end_seconds": chunk["end"],
                    "text": text,
                    "word_count": len(text.split()),
                }
            )
    return chunks


def _build_profile(channel_id: str) -> dict[str, Any]:
    videos = []
    for spec in _VIDEO_SPECS:
        videos.append(
            {
                "video_id": spec["video_id"],
                "title": spec["title"],
                "upload_date": spec["upload_date"],
                "core_topic": f"core topic of {spec['video_id']}",
                "key_claims": [
                    {
                        "text": f"primary claim about {spec['themes'][0]}",
                        "evidence": [
                            {"start_seconds": spec["chunks"][0]["start"], "quote": spec["chunks"][0]["text"][:80]}
                        ],
                    }
                ],
                "recurring_themes": spec["themes"],
                "tone_markers": spec["tones"],
                "notable_opinions": [],
                "people_or_things_referenced": [],
                "questions_answered": [],
                "concepts": list(spec["themes"]),
                "tactics": [],
                "story_events": [],
                "audience": "general",
                "summary_confidence": 0.9,
            }
        )

    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "channel_id": channel_id,
        "channel_name": "Synthetic RAG Channel",
        "video_count": len(videos),
        "date_range": {"first": "20250101", "last": "20250501"},
        "videos": videos,
        "rollups": {
            "all_themes": [{"theme": "money", "count": 1}, {"theme": "adventure", "count": 1}],
            "all_referenced": [],
            "tone_distribution": {"energetic": 2, "analytical": 2, "playful": 1},
            "all_concepts": [],
            "all_tactics": [],
            "all_questions_answered": [],
            "audience_distribution": {"general": 5},
            "summary_quality": {"average_confidence": 0.9},
        },
        "generated_at": "2026-05-16T00:00:00+00:00",
    }


def _build_summary(spec: dict[str, Any]) -> dict[str, Any]:
    first_chunk = spec["chunks"][0]
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "summary_schema_version": SUMMARY_SCHEMA_VERSION,
        "video_id": spec["video_id"],
        "title": spec["title"],
        "upload_date": spec["upload_date"],
        "core_topic": f"core topic of {spec['video_id']}",
        "key_claims": [
            {
                "text": f"primary claim about {spec['themes'][0]}",
                "evidence": [
                    {"start_seconds": first_chunk["start"], "quote": first_chunk["text"][:80]}
                ],
            }
        ],
        "recurring_themes": spec["themes"],
        "tone_markers": spec["tones"],
        "notable_opinions": [],
        "people_or_things_referenced": [],
        "questions_answered": [],
        "concepts": list(spec["themes"]),
        "tactics": [],
        "story_events": [],
        "audience": "general",
        "summary_confidence": 0.9,
    }


@pytest.fixture
def synthetic_chunk_index(monkeypatch):
    """Provision DATA_DIR with a 5-video / 3-chunks-each synthetic chunk index.

    The fixture writes chunk_index.json, profile.json, and per-video summary
    files into a temporary DATA_DIR. It reloads `backend.storage` and
    `backend.pipeline.retrieve` so they pick up the temp directory, matching
    the pattern used by other tests in this suite.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("DATA_DIR", tmpdir)

        from backend import storage
        from backend.pipeline import retrieve

        importlib.reload(storage)
        importlib.reload(retrieve)

        channel_id = SYNTHETIC_CHANNEL_ID
        chunks = _build_chunks()

        chunk_index = {
            "schema_version": CHUNK_INDEX_SCHEMA_VERSION,
            "channel_id": channel_id,
            "generated_at": "2026-05-16T00:00:00+00:00",
            "chunking": {
                "target_seconds_min": 45,
                "target_seconds_max": 90,
                "target_words_min": 120,
                "target_words_max": 250,
                "overlap_seconds": 15,
            },
            "source": {
                "selected_video_ids": [spec["video_id"] for spec in _VIDEO_SPECS],
            },
            "chunks": chunks,
        }

        channel_dir = storage.get_channel_dir(channel_id)
        storage.write_json(channel_dir / "chunk_index.json", chunk_index)

        profile = _build_profile(channel_id)
        storage.write_json(channel_dir / "profile.json", profile)

        summaries_dir = channel_dir / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        for spec in _VIDEO_SPECS:
            storage.write_json(
                summaries_dir / f"{spec['video_id']}.json",
                _build_summary(spec),
            )

        yield SyntheticChunkIndex(
            channel_id=channel_id,
            data_dir=Path(tmpdir),
            chunk_index=chunk_index,
            profile=profile,
            storage=storage,
            retrieve=retrieve,
        )
