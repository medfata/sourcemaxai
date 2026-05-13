"""Tests for Phase 6 per-video summarization behavior."""

import json

import pytest
from backend.pipeline.schema_versions import SUMMARY_MODEL, SUMMARY_SCHEMA_VERSION
from backend.pipeline.summarize import (
    _summarize_one,
    _summary_evidence_metrics,
    _verify_claims,
)


class _TextBlock:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class _Response:
    def __init__(self, payload: dict):
        self.content = [_TextBlock(json.dumps(payload))]


class _Messages:
    def __init__(self, payloads: list[dict]):
        self.payloads = list(payloads)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Response(self.payloads.pop(0))


class _Client:
    def __init__(self, payloads: list[dict]):
        self.messages = _Messages(payloads)


def _summary_payload(**overrides) -> dict:
    payload = {
        "core_topic": "Testing retrieval summaries",
        "key_claims": [
            {
                "text": "Testing improves retrieval evidence.",
                "evidence": [{"start_seconds": 10, "quote": "testing retrieval evidence"}],
            }
        ],
        "recurring_themes": ["testing"],
        "tone_markers": ["direct"],
        "notable_opinions": [
            {
                "text": "Careful evidence makes summaries durable.",
                "evidence": [{"start_seconds": 10, "quote": "durable systems"}],
            }
        ],
        "people_or_things_referenced": [],
        "questions_answered": ["How should summaries support retrieval?"],
        "concepts": ["retrieval evidence", "summary schema"],
        "tactics": ["verify quote spans"],
        "story_events": [],
        "audience": "developers improving retrieval",
        "summary_confidence": 0.99,
    }
    payload.update(overrides)
    return payload


def test_verify_claims_preserves_unsupported_claims_without_bad_evidence():
    segments = [
        {
            "start": 10,
            "text": "Build durable systems by testing retrieval evidence carefully.",
        }
    ]
    claims = [
        {
            "text": "Supported",
            "evidence": [{"start_seconds": 10, "quote": "testing retrieval evidence"}],
        },
        {
            "text": "Unsupported",
            "evidence": [{"start_seconds": 99, "quote": "not in transcript"}],
        },
    ]

    verified = _verify_claims(claims, segments)

    assert verified[0]["evidence"] == [
        {"start_seconds": 10, "quote": "testing retrieval evidence"}
    ]
    assert verified[1] == {"text": "Unsupported", "evidence": []}


@pytest.mark.asyncio
async def test_summarize_one_writes_v3_schema_and_counts_only_verified_evidence():
    client = _Client(
        [
            _summary_payload(
                key_claims=[
                    {
                        "text": "Testing improves retrieval evidence.",
                        "evidence": [
                            {"start_seconds": 10, "quote": "testing retrieval evidence"}
                        ],
                    },
                    {
                        "text": "Unsupported inference remains searchable.",
                        "evidence": [{"start_seconds": 99, "quote": "not in transcript"}],
                    },
                ],
            )
        ]
    )
    segments = [
        {
            "start": 10,
            "text": "Build durable systems by testing retrieval evidence carefully.",
        },
        {"start": 20, "text": "A second timestamped line appears here."},
    ]

    summary = await _summarize_one(
        client,
        "vid_1",
        "Summary Video",
        "20240101",
        "fallback transcript",
        segments,
    )

    assert summary["schema_version"] == SUMMARY_SCHEMA_VERSION
    assert summary["summary_schema_version"] == SUMMARY_SCHEMA_VERSION
    assert summary["model"] == SUMMARY_MODEL
    assert summary["key_claims"][0]["evidence"]
    assert summary["key_claims"][1]["evidence"] == []
    assert summary["notable_opinions"][0]["evidence"]
    assert summary["questions_answered"] == ["How should summaries support retrieval?"]
    assert summary["concepts"] == ["retrieval evidence", "summary schema"]
    assert summary["tactics"] == ["verify quote spans"]
    assert summary["audience"] == "developers improving retrieval"
    assert summary["summary_confidence"] == 0.784

    metrics = _summary_evidence_metrics(summary)
    assert metrics == {
        "claim_count": 3,
        "supported_claim_count": 2,
        "unsupported_claim_count": 1,
        "summary_evidence_rate": 0.667,
    }
    assert client.messages.calls[0]["model"] == SUMMARY_MODEL
