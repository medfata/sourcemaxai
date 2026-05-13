"""Repeatable evaluation harness for source-grounded chat responses.

The default dry-run mode evaluates mocked source-registry/delta frames from the
case file, so it never needs API keys or network access. Context and live modes
can be used against local channel data when needed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CASE_FILE = Path(__file__).with_name("chat_quality_cases.json")
CITATION_RE = re.compile(r"(?<!\w)\[(S\d+)\](?!\w)", re.IGNORECASE)
REFUSAL_PATTERNS = (
    re.compile(r"\bnot enough(?: caption)? evidence\b", re.IGNORECASE),
    re.compile(r"\binsufficient(?: caption)? evidence\b", re.IGNORECASE),
    re.compile(r"\bno relevant caption sources\b", re.IGNORECASE),
    re.compile(r"\bsource pack does not contain\b", re.IGNORECASE),
    re.compile(r"\bcannot determine\b", re.IGNORECASE),
    re.compile(r"\bcan't determine\b", re.IGNORECASE),
    re.compile(r"\bnot covered\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class EvalCase:
    """A single chat quality evaluation case."""

    id: str
    channel_id: str
    question: str
    expected_video_ids: list[str] = field(default_factory=list)
    expected_terms: list[str] = field(default_factory=list)
    requires_citation: bool = False
    expect_refusal: bool | None = None
    scope: dict[str, Any] | None = None
    notes: str = ""
    mock_answer: str | None = None
    mock_sources: list[dict[str, Any]] = field(default_factory=list)
    mock_frames: list[Any] = field(default_factory=list)


def _string_list(value: Any, *, field_name: str, case_id: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{case_id}: {field_name} must be a list of strings")
    return value


def _bool_or_none(value: Any, *, field_name: str, case_id: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{case_id}: {field_name} must be true, false, or null")
    return value


def _case_from_dict(raw: dict[str, Any], index: int) -> EvalCase:
    case_id = raw.get("id") or f"case_{index + 1}"
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError(f"case at index {index}: id must be a non-empty string")
    case_id = case_id.strip()

    channel_id = raw.get("channel_id")
    question = raw.get("question")
    if not isinstance(channel_id, str) or not channel_id.strip():
        raise ValueError(f"{case_id}: channel_id must be a non-empty string")
    if not isinstance(question, str) or not question.strip():
        raise ValueError(f"{case_id}: question must be a non-empty string")

    scope = raw.get("scope")
    if scope is not None and not isinstance(scope, dict):
        raise ValueError(f"{case_id}: scope must be an object when provided")

    mock_answer = raw.get("mock_answer")
    if mock_answer is not None and not isinstance(mock_answer, str):
        raise ValueError(f"{case_id}: mock_answer must be a string when provided")

    mock_sources = raw.get("mock_sources") or raw.get("source_registry") or []
    if not isinstance(mock_sources, list):
        raise ValueError(f"{case_id}: mock_sources must be a list when provided")
    if not all(isinstance(item, dict) for item in mock_sources):
        raise ValueError(f"{case_id}: mock_sources entries must be objects")

    mock_frames = raw.get("mock_frames") or []
    if not isinstance(mock_frames, list):
        raise ValueError(f"{case_id}: mock_frames must be a list when provided")

    return EvalCase(
        id=case_id,
        channel_id=channel_id.strip(),
        question=question.strip(),
        expected_video_ids=_string_list(
            raw.get("expected_video_ids"), field_name="expected_video_ids", case_id=case_id
        ),
        expected_terms=_string_list(
            raw.get("expected_terms"), field_name="expected_terms", case_id=case_id
        ),
        requires_citation=bool(raw.get("requires_citation", False)),
        expect_refusal=_bool_or_none(
            raw.get("expect_refusal", raw.get("expected_refusal")),
            field_name="expect_refusal",
            case_id=case_id,
        ),
        scope=scope,
        notes=str(raw.get("notes") or ""),
        mock_answer=mock_answer,
        mock_sources=mock_sources,
        mock_frames=mock_frames,
    )


def load_cases(path: Path = DEFAULT_CASE_FILE, case_ids: set[str] | None = None) -> list[EvalCase]:
    """Load and validate eval cases from a JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        raw_cases = data.get("cases")
    elif isinstance(data, list):
        raw_cases = data
    else:
        raise ValueError("case file must be either a list or an object with a cases list")

    if not isinstance(raw_cases, list):
        raise ValueError("case file must contain a cases list")

    cases = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            raise ValueError(f"case at index {index} must be an object")
        case = _case_from_dict(raw, index)
        if case.id in seen_ids:
            raise ValueError(f"duplicate eval case id: {case.id}")
        seen_ids.add(case.id)
        if case_ids is None or case.id in case_ids:
            cases.append(case)

    if case_ids:
        missing = sorted(case_ids - {case.id for case in cases})
        if missing:
            raise ValueError(f"unknown case id(s): {', '.join(missing)}")
    return cases


def normalize_source_id(value: Any, fallback_index: int | None = None) -> str:
    """Normalize source IDs to upper-case S-number labels."""
    if value is None and fallback_index is not None:
        return f"S{fallback_index}"
    text = str(value or "").strip()
    if not text and fallback_index is not None:
        return f"S{fallback_index}"
    if text.isdigit():
        return f"S{text}"
    return text.upper()


def extract_citation_ids(answer: str) -> list[str]:
    """Return unique [S1]-style citation IDs in answer order."""
    seen: set[str] = set()
    citations: list[str] = []
    for match in CITATION_RE.finditer(answer or ""):
        source_id = normalize_source_id(match.group(1))
        if source_id in seen:
            continue
        seen.add(source_id)
        citations.append(source_id)
    return citations


def parse_frames(value: Any) -> list[dict[str, Any]]:
    """Parse dict/list/raw JSON/SSE data into backend response frames."""
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        frames: list[dict[str, Any]] = []
        for item in value:
            frames.extend(parse_frames(item))
        return frames
    if not isinstance(value, str):
        return []

    text = value.strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if parsed is not None:
        return parse_frames(parsed)

    payloads: list[str] = []
    current_event: list[str] = []
    saw_sse_data = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if current_event:
                payloads.append("\n".join(current_event))
                current_event = []
            continue
        if stripped.startswith("data:"):
            saw_sse_data = True
            current_event.append(stripped.removeprefix("data:").strip())
        elif not saw_sse_data:
            payloads.append(stripped)
    if current_event:
        payloads.append("\n".join(current_event))

    frames = []
    for payload in payloads:
        if not payload:
            continue
        if payload == "[DONE]":
            frames.append({"type": "done"})
            continue
        try:
            parsed_payload = json.loads(payload)
        except json.JSONDecodeError:
            frames.append({"type": "delta", "text": payload})
        else:
            frames.extend(parse_frames(parsed_payload))
    return frames


def collect_answer_text(frames: list[dict[str, Any]]) -> str:
    """Collect assistant answer text from streamed delta-like frames."""
    parts: list[str] = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        frame_type = frame.get("type")
        if frame_type in {"delta", "text_delta"}:
            text = frame.get("text")
            if isinstance(text, str):
                parts.append(text)
            delta = frame.get("delta")
            if isinstance(delta, dict) and isinstance(delta.get("text"), str):
                parts.append(delta["text"])
        elif frame_type in {"answer", "message", "completion"}:
            text = frame.get("text") or frame.get("content") or frame.get("answer")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()


def _source_list_from_frame(frame: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("sources", "source_registry"):
        value = frame.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict) and isinstance(value.get("sources"), list):
            return [item for item in value["sources"] if isinstance(item, dict)]

    data = frame.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return _source_list_from_frame(data)
    return []


def source_registry_from_frames(frames: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build a source registry from backend sources/source_registry frames."""
    registry: dict[str, dict[str, Any]] = {}
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        for index, source in enumerate(_source_list_from_frame(frame), start=1):
            source_id = normalize_source_id(source.get("source_id"), index)
            if not source_id:
                continue
            normalized = dict(source)
            normalized["source_id"] = source_id
            registry[source_id] = normalized
    return registry


def normalize_text(value: Any) -> str:
    """Case-fold text and collapse whitespace for deterministic comparisons."""
    return " ".join(str(value or "").casefold().split())


def rough_token_count(text: str) -> int:
    """Estimate tokens from text length without tokenizer dependencies."""
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, math.ceil(len(stripped) / 4))


def is_refusal_answer(answer: str) -> bool:
    """Detect the expected caption-evidence refusal shape."""
    return any(pattern.search(answer or "") for pattern in REFUSAL_PATTERNS)


def _source_quote(source: dict[str, Any]) -> str:
    for key in ("quote", "excerpt", "snippet"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _source_candidate_text(source: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("text", "chunk_text", "caption", "segment_text", "transcript_text"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)

    for nested_key in ("chunk", "segment"):
        nested = source.get(nested_key)
        if isinstance(nested, dict):
            value = nested.get("text")
            if isinstance(value, str) and value.strip():
                values.append(value)
    return "\n".join(values)


def _quote_is_grounded(source: dict[str, Any]) -> bool | None:
    quote = _source_quote(source)
    candidate_text = _source_candidate_text(source)
    if not quote or not candidate_text:
        return None

    haystack = normalize_text(candidate_text)
    quote_norm = normalize_text(quote.replace("...", " ").replace("…", " "))
    if quote_norm and quote_norm in haystack:
        return True

    parts = [
        normalize_text(part)
        for part in re.split(r"\.{3,}|…", quote)
        if len(normalize_text(part)) >= 16
    ]
    if parts:
        return all(part in haystack for part in parts)
    return False


def evaluate_response(
    case: EvalCase,
    frames: list[dict[str, Any]],
    *,
    elapsed_seconds: float = 0.0,
    first_delta_seconds: float | None = None,
    mode: str = "dry-run",
) -> dict[str, Any]:
    """Evaluate a response against deterministic citation and content metrics."""
    answer = collect_answer_text(frames)
    citations = extract_citation_ids(answer)
    registry = source_registry_from_frames(frames)

    valid_citations = [source_id for source_id in citations if source_id in registry]
    invalid_citations = [source_id for source_id in citations if source_id not in registry]
    if citations:
        citation_validity = len(valid_citations) / len(citations)
    else:
        citation_validity = 0.0 if case.requires_citation else 1.0
    citation_required_met = (not case.requires_citation) or bool(citations)

    grounding_statuses: dict[str, bool | None] = {}
    for source_id in valid_citations:
        grounding_statuses[source_id] = _quote_is_grounded(registry[source_id])
    ungrounded_citations = [
        source_id for source_id, grounded in grounding_statuses.items() if grounded is False
    ]
    unknown_grounding = [
        source_id for source_id, grounded in grounding_statuses.items() if grounded is None
    ]
    known_grounding = [
        grounded for grounded in grounding_statuses.values() if grounded is not None
    ]
    citation_grounding = (
        sum(1 for grounded in known_grounding if grounded) / len(known_grounding)
        if known_grounding
        else None
    )

    normalized_answer = normalize_text(answer)
    missing_terms = [
        term for term in case.expected_terms if normalize_text(term) not in normalized_answer
    ]
    expected_terms_score = (
        (len(case.expected_terms) - len(missing_terms)) / len(case.expected_terms)
        if case.expected_terms
        else 1.0
    )

    cited_video_ids = [
        str(registry[source_id].get("video_id"))
        for source_id in valid_citations
        if registry[source_id].get("video_id") is not None
    ]
    expected_video_ids = set(case.expected_video_ids)
    recalled_video_ids = sorted(expected_video_ids.intersection(cited_video_ids))
    source_recall = (
        len(recalled_video_ids) / len(expected_video_ids) if expected_video_ids else 1.0
    )
    source_recall_pass = bool(recalled_video_ids) if expected_video_ids else True

    refusal_detected = is_refusal_answer(answer)
    if case.expect_refusal is None:
        refusal_correct = True
    elif case.expect_refusal:
        refusal_correct = refusal_detected
    else:
        refusal_correct = not refusal_detected

    metrics = {
        "citation_validity": round(citation_validity, 4),
        "citation_validity_pass": not invalid_citations and citation_required_met,
        "citation_required_met": citation_required_met,
        "invalid_citations": invalid_citations,
        "cited_source_ids": citations,
        "citation_grounding": (
            round(citation_grounding, 4) if citation_grounding is not None else None
        ),
        "citation_grounding_pass": not ungrounded_citations,
        "ungrounded_citations": ungrounded_citations,
        "unknown_grounding": unknown_grounding,
        "source_recall": round(source_recall, 4),
        "source_recall_pass": source_recall_pass,
        "recalled_video_ids": recalled_video_ids,
        "expected_terms": round(expected_terms_score, 4),
        "expected_terms_pass": not missing_terms,
        "missing_terms": missing_terms,
        "refusal_detected": refusal_detected,
        "refusal_correct": refusal_correct,
        "latency_seconds": round(elapsed_seconds, 4),
        "first_delta_seconds": (
            round(first_delta_seconds, 4) if first_delta_seconds is not None else None
        ),
        "rough_answer_tokens": rough_token_count(answer),
        "source_count": len(registry),
    }
    passed = all(
        [
            metrics["citation_validity_pass"],
            metrics["citation_grounding_pass"],
            metrics["source_recall_pass"],
            metrics["expected_terms_pass"],
            metrics["refusal_correct"],
        ]
    )

    return {
        "case_id": case.id,
        "channel_id": case.channel_id,
        "question": case.question,
        "mode": mode,
        "passed": passed,
        "answer": answer,
        "metrics": metrics,
        "notes": case.notes,
    }


def _frames_from_mock_case(case: EvalCase) -> list[dict[str, Any]]:
    if case.mock_frames:
        return parse_frames(case.mock_frames)

    frames: list[dict[str, Any]] = []
    if case.mock_sources:
        frames.append({"type": "sources", "sources": case.mock_sources})

    if case.mock_answer is not None:
        answer = case.mock_answer
    elif case.expect_refusal:
        answer = "There is not enough caption evidence in the source pack to answer."
    else:
        terms = ", ".join(case.expected_terms) if case.expected_terms else "mock answer"
        citation = " [S1]" if case.mock_sources else ""
        answer = f"{terms}.{citation}"

    frames.append({"type": "delta", "text": answer})
    frames.append({"type": "done"})
    return frames


def _scope_from_case(case: EvalCase) -> Any:
    if not case.scope:
        return None
    from backend.models import ChatScope

    return ChatScope.model_validate(case.scope)


def _synthesize_context_answer(case: EvalCase, sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "There is not enough caption evidence in the source pack to answer."

    terms = " ".join(case.expected_terms[:3])
    source = sources[0]
    quote = _source_quote(source) or _source_candidate_text(source)
    quote = " ".join(quote.split())[:220]
    prefix = f"{terms}. " if terms else ""
    return f"{prefix}{quote} [{source.get('source_id', 'S1')}]".strip()


async def _run_context_case(
    case: EvalCase,
) -> tuple[list[dict[str, Any]], float, float | None]:
    from backend.pipeline.chat_context import build_chat_context

    start = time.perf_counter()
    context = build_chat_context(
        case.channel_id,
        [{"role": "user", "content": case.question}],
        _scope_from_case(case),
    )
    elapsed = time.perf_counter() - start
    if context.error:
        return [{"type": "error", "message": context.error}], elapsed, None

    answer = _synthesize_context_answer(case, context.sources)
    frames = [
        {"type": "sources", "sources": context.sources},
        {"type": "delta", "text": answer},
        {"type": "done"},
    ]
    return frames, elapsed, elapsed


async def _run_live_case(case: EvalCase) -> tuple[list[dict[str, Any]], float, float | None]:
    from backend.pipeline.ask import chat_stream
    from backend.pipeline.chat_context import build_chat_context

    messages = [{"role": "user", "content": case.question}]
    scope = _scope_from_case(case)
    frames: list[dict[str, Any]] = []
    first_delta_seconds: float | None = None
    start = time.perf_counter()

    context = build_chat_context(case.channel_id, messages, scope)
    if context.error:
        return [{"type": "error", "message": context.error}], time.perf_counter() - start, None
    frames.append({"type": "sources", "sources": context.sources})

    async for raw_frame in chat_stream(case.channel_id, messages, scope):
        parsed_frames = parse_frames(raw_frame)
        if first_delta_seconds is None:
            if any(frame.get("type") == "delta" and frame.get("text") for frame in parsed_frames):
                first_delta_seconds = time.perf_counter() - start
        frames.extend(parsed_frames)

    return frames, time.perf_counter() - start, first_delta_seconds


async def run_case(case: EvalCase, *, mode: str) -> dict[str, Any]:
    """Run one eval case in dry-run, context, or live mode."""
    start = time.perf_counter()
    if mode == "dry-run":
        frames = _frames_from_mock_case(case)
        elapsed = time.perf_counter() - start
        first_delta_seconds = elapsed if collect_answer_text(frames) else None
    elif mode == "context":
        frames, elapsed, first_delta_seconds = await _run_context_case(case)
    elif mode == "live":
        frames, elapsed, first_delta_seconds = await _run_live_case(case)
    else:
        raise ValueError(f"unsupported mode: {mode}")

    return evaluate_response(
        case,
        frames,
        elapsed_seconds=elapsed,
        first_delta_seconds=first_delta_seconds,
        mode=mode,
    )


async def run_cases(cases: list[EvalCase], *, mode: str) -> list[dict[str, Any]]:
    """Run all eval cases in file order."""
    results = []
    for case in cases:
        results.append(await run_case(case, mode=mode))
    return results


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Create a compact aggregate report."""
    total = len(results)
    passed = sum(1 for result in results if result["passed"])
    failed = total - passed

    def average_metric(name: str) -> float | None:
        values = [
            result["metrics"][name]
            for result in results
            if isinstance(result["metrics"].get(name), int | float)
        ]
        if not values:
            return None
        return round(sum(values) / len(values), 4)

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "averages": {
            "citation_validity": average_metric("citation_validity"),
            "citation_grounding": average_metric("citation_grounding"),
            "source_recall": average_metric("source_recall"),
            "expected_terms": average_metric("expected_terms"),
            "latency_seconds": average_metric("latency_seconds"),
            "rough_answer_tokens": average_metric("rough_answer_tokens"),
        },
    }


def print_text_report(report: dict[str, Any], results: list[dict[str, Any]]) -> None:
    """Print a deterministic human-readable eval report."""
    summary = report["summary"]
    print(
        f"Chat eval mode={report['mode']} cases={summary['total']} "
        f"passed={summary['passed']} failed={summary['failed']}"
    )
    for result in results:
        status = "PASS" if result["passed"] else "FAIL"
        metrics = result["metrics"]
        print(
            f"[{status}] {result['case_id']} "
            f"citation_validity={metrics['citation_validity']} "
            f"source_recall={metrics['source_recall']} "
            f"expected_terms={metrics['expected_terms']} "
            f"refusal_correct={metrics['refusal_correct']} "
            f"tokens={metrics['rough_answer_tokens']} "
            f"latency={metrics['latency_seconds']}s"
        )
        problems = []
        if metrics["invalid_citations"]:
            problems.append(f"invalid_citations={','.join(metrics['invalid_citations'])}")
        if metrics["ungrounded_citations"]:
            problems.append(f"ungrounded={','.join(metrics['ungrounded_citations'])}")
        if metrics["missing_terms"]:
            problems.append(f"missing_terms={','.join(metrics['missing_terms'])}")
        if problems:
            print(f"  {'; '.join(problems)}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run chat response quality evals.")
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASE_FILE,
        help="Path to chat eval case JSON.",
    )
    parser.add_argument(
        "--mode",
        choices=("dry-run", "context", "live"),
        default="dry-run",
        help=(
            "dry-run uses mocked frames, context uses local retrieval only, "
            "live calls chat_stream."
        ),
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Run only the specified case id. Can be passed more than once.",
    )
    parser.add_argument("--output", type=Path, help="Optional path for JSON report.")
    parser.add_argument("--json", action="store_true", help="Print the full JSON report to stdout.")
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Exit with 0 even when one or more eval cases fail.",
    )
    return parser


async def async_main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    case_filter = set(args.case_id) if args.case_id else None
    cases = load_cases(args.cases, case_filter)
    results = await run_cases(cases, mode=args.mode)
    report = {
        "schema_version": 1,
        "mode": args.mode,
        "case_file": str(args.cases),
        "summary": summarize_results(results),
        "results": results,
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_text_report(report, results)

    if report["summary"]["failed"] and not args.no_fail:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
