"""Tests for the Phase 7 chat quality evaluation harness."""

import asyncio
import json

import pytest
from backend.evals import run_chat_eval


def _source(source_id: str = "S1", *, video_id: str = "vid_expected") -> dict:
    return {
        "source_id": source_id,
        "kind": "chunk",
        "chunk_id": f"{video_id}:0001",
        "video_id": video_id,
        "title": "Expected Video",
        "upload_date": "20240101",
        "start_seconds": 12,
        "end_seconds": 55,
        "quote": "Brand trust comes from a promise repeated through values.",
        "text": (
            "Brand trust comes from a promise repeated through values. "
            "The behavior has to stay consistent."
        ),
    }


def test_parse_sse_frames_and_source_registry_shape():
    raw = (
        'data: {"type":"sources","sources":[{"source_id":"S1","video_id":"vid_a",'
        '"quote":"alpha beta","text":"alpha beta gamma"}]}\n\n'
        'data: {"type":"delta","text":"Answer with alpha [S1]"}\n\n'
        'data: {"type":"done"}\n\n'
    )

    frames = run_chat_eval.parse_frames(raw)

    assert [frame["type"] for frame in frames] == ["sources", "delta", "done"]
    assert run_chat_eval.collect_answer_text(frames) == "Answer with alpha [S1]"
    registry = run_chat_eval.source_registry_from_frames(frames)
    assert registry["S1"]["video_id"] == "vid_a"


def test_evaluate_response_scores_valid_citations_terms_recall_and_grounding():
    case = run_chat_eval.EvalCase(
        id="supported",
        channel_id="UC_eval",
        question="What does he say about brand trust?",
        expected_video_ids=["vid_expected"],
        expected_terms=["brand", "promise", "values"],
        requires_citation=True,
        expect_refusal=False,
    )
    frames = [
        {"type": "sources", "sources": [_source()]},
        {
            "type": "delta",
            "text": "Brand trust depends on a promise repeated through values [S1].",
        },
        {"type": "done"},
    ]

    result = run_chat_eval.evaluate_response(case, frames, elapsed_seconds=0.25)

    assert result["passed"] is True
    assert result["metrics"]["citation_validity"] == 1.0
    assert result["metrics"]["citation_grounding"] == 1.0
    assert result["metrics"]["source_recall"] == 1.0
    assert result["metrics"]["expected_terms"] == 1.0
    assert result["metrics"]["rough_answer_tokens"] > 0


def test_evaluate_response_reports_invalid_citations_and_missing_terms():
    case = run_chat_eval.EvalCase(
        id="invalid",
        channel_id="UC_eval",
        question="What does he say about brand trust?",
        expected_video_ids=["vid_expected"],
        expected_terms=["brand", "promise", "values", "consistency"],
        requires_citation=True,
        expect_refusal=False,
    )
    frames = [
        {"type": "sources", "sources": [_source()]},
        {"type": "delta", "text": "Brand trust depends on a promise [S1] [S99]."},
    ]

    result = run_chat_eval.evaluate_response(case, frames)

    assert result["passed"] is False
    assert result["metrics"]["invalid_citations"] == ["S99"]
    assert result["metrics"]["missing_terms"] == ["values", "consistency"]
    assert result["metrics"]["source_recall_pass"] is True


def test_evaluate_response_accepts_expected_refusal_without_citation():
    case = run_chat_eval.EvalCase(
        id="refusal",
        channel_id="UC_eval",
        question="What does he say about a topic with no support?",
        expected_terms=["not enough caption evidence"],
        requires_citation=False,
        expect_refusal=True,
    )
    frames = [
        {"type": "sources", "sources": []},
        {
            "type": "delta",
            "text": "There is not enough caption evidence in the source pack to answer.",
        },
    ]

    result = run_chat_eval.evaluate_response(case, frames)

    assert result["passed"] is True
    assert result["metrics"]["refusal_detected"] is True
    assert result["metrics"]["citation_validity"] == 1.0


def test_load_cases_validates_filters_and_rejects_unknown_case_id(tmp_path):
    case_file = tmp_path / "cases.json"
    case_file.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "one",
                        "channel_id": "UC_one",
                        "question": "Question?",
                        "expected_terms": ["answer"],
                    },
                    {
                        "id": "two",
                        "channel_id": "UC_two",
                        "question": "Question?",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    cases = run_chat_eval.load_cases(case_file, {"one"})

    assert [case.id for case in cases] == ["one"]
    with pytest.raises(ValueError, match="unknown case id"):
        run_chat_eval.load_cases(case_file, {"missing"})


def test_default_dry_run_cases_pass_without_live_api_calls():
    cases = run_chat_eval.load_cases(run_chat_eval.DEFAULT_CASE_FILE)

    results = asyncio.run(run_chat_eval.run_cases(cases, mode="dry-run"))
    summary = run_chat_eval.summarize_results(results)

    assert len(cases) >= 4
    assert summary["failed"] == 0
    assert all(result["metrics"]["latency_seconds"] >= 0 for result in results)
