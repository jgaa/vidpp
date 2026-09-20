from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import json
import math

from .errors import VidPPError


def _number(value: Any, name: str, *, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise VidPPError(f"{name} must be a finite number >= {minimum}")
    return float(value)


@dataclass(frozen=True)
class TranscriptWord:
    start: float
    end: float
    word: str
    probability: float | None = None

    @classmethod
    def from_dict(cls, raw: Any) -> "TranscriptWord":
        if not isinstance(raw, dict):
            raise VidPPError("word must be an object")
        start, end = _number(raw.get("start"), "word.start"), _number(raw.get("end"), "word.end")
        word = raw.get("word")
        if end < start or not isinstance(word, str) or not word.strip():
            raise VidPPError("invalid word text or timestamp range")
        probability = raw.get("probability")
        if probability is not None and _number(probability, "word.probability") > 1:
            raise VidPPError("word probability must be <= 1")
        return cls(start, end, word, probability)


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str
    words: tuple[TranscriptWord, ...] = ()

    @classmethod
    def from_dict(cls, raw: Any) -> "TranscriptSegment":
        if not isinstance(raw, dict):
            raise VidPPError("each transcript segment must be an object")
        start = _number(raw.get("start"), "segment.start")
        end = _number(raw.get("end"), "segment.end")
        text = raw.get("text")
        if end <= start:
            raise VidPPError("segment.end must be after segment.start")
        if not isinstance(text, str) or not text.strip():
            raise VidPPError("segment.text must be a non-empty string")
        raw_words = raw.get("words", [])
        if not isinstance(raw_words, list):
            raise VidPPError("segment.words must be an array")
        words = tuple(TranscriptWord.from_dict(item) for item in raw_words)
        if any(b.start < a.start for a, b in zip(words, words[1:])):
            raise VidPPError("words must be sorted by start time")
        if any(w.start < start - .02 or w.end > end + .02 for w in words):
            raise VidPPError("word timestamps must lie inside their segment")
        return cls(start, end, text.strip(), words)


@dataclass(frozen=True)
class EditOperation:
    id: str
    type: str
    source_start: float
    source_end: float
    enabled: bool = True
    target_duration: float | None = None
    reason: str = ""

    @classmethod
    def from_dict(cls, raw: Any, duration: float | None = None) -> "EditOperation":
        if not isinstance(raw, dict):
            raise VidPPError("each edit operation must be an object")
        operation_id = raw.get("id")
        kind = raw.get("type")
        if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 80:
            raise VidPPError("operation.id must be a short non-empty string")
        if kind not in {"remove", "shorten_pause", "review"}:
            raise VidPPError(f"unsupported operation type: {kind!r}")
        start = _number(raw.get("source_start", raw.get("start")), "operation.source_start")
        end = _number(raw.get("source_end", raw.get("end")), "operation.source_end")
        if end <= start:
            raise VidPPError("operation.source_end must be after operation.source_start")
        if duration is not None and end > duration + 0.01:
            raise VidPPError("operation exceeds source duration")
        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise VidPPError("operation.enabled must be boolean")
        target = raw.get("target_duration")
        if kind == "shorten_pause":
            target = _number(target, "operation.target_duration")
            if target >= end - start:
                raise VidPPError("shortened pause must be shorter than original pause")
        elif target is not None:
            raise VidPPError("target_duration is only valid for shorten_pause")
        reason = raw.get("reason", "")
        if not isinstance(reason, str) or len(reason) > 1000:
            raise VidPPError("operation.reason must be a short string")
        return cls(operation_id, kind, start, end, enabled, target, reason)


def load_transcript(path: Path) -> list[TranscriptSegment]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VidPPError(f"invalid transcript {path}: {exc}") from exc
    segments_raw = raw.get("segments") if isinstance(raw, dict) else None
    if not isinstance(segments_raw, list):
        raise VidPPError("transcript must be an object with a segments array")
    segments = [TranscriptSegment.from_dict(item) for item in segments_raw]
    if any(right.start < left.start for left, right in zip(segments, segments[1:])):
        raise VidPPError("transcript segments must be sorted by start time")
    return segments


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_edit_plan(path: Path, duration: float | None = None) -> list[EditOperation]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VidPPError(f"invalid edit plan {path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("operations"), list):
        raise VidPPError("edit plan must contain version 1 and an operations array")
    operations = [EditOperation.from_dict(item, duration) for item in raw["operations"]]
    ids = [item.id for item in operations]
    if len(ids) != len(set(ids)):
        raise VidPPError("edit operation IDs must be unique")
    active = sorted((item for item in operations if item.enabled and item.type != "review"), key=lambda item: item.source_start)
    if any(right.source_start < left.source_end - 0.001 for left, right in zip(active, active[1:])):
        raise VidPPError("enabled edit operations must not overlap")
    return operations


def edit_plan_json(operations: list[EditOperation]) -> dict[str, Any]:
    return {"version": 1, "operations": [asdict(operation) for operation in operations]}
