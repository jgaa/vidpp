from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import urllib.request

from .errors import VidPPError
from .models import EditOperation, edit_plan_json, load_edit_plan, load_transcript, write_json
from .template import Template

LOG = logging.getLogger(__name__)


def run(command: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    LOG.debug("Executing command: %s", shlex.join(command))
    try:
        return subprocess.run(command, check=True, text=True, capture_output=capture)
    except FileNotFoundError as exc:
        raise VidPPError(f"required program not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        LOG.debug("Command stderr: %s", exc.stderr)
        raise VidPPError(f"command failed: {command[0]}: {exc.stderr.strip()[-1000:]}") from exc


def inspect(source: Path) -> dict[str, Any]:
    if not source.is_file(): raise VidPPError(f"source video does not exist: {source}")
    result = run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,avg_frame_rate", "-of", "json", str(source)])
    try:
        payload = json.loads(result.stdout)
        duration = float(payload["format"]["duration"])
        video = next(item for item in payload["streams"] if item["codec_type"] == "video")
    except (KeyError, StopIteration, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise VidPPError("could not obtain a valid video stream and duration from source") from exc
    fps = video.get("avg_frame_rate", "0/1")
    return {"duration": duration, "width": video["width"], "height": video["height"], "fps": fps}


def create_project(source: Path, project: Path) -> dict[str, Any]:
    source = source.resolve()
    if project.exists() and any(project.iterdir()): raise VidPPError(f"project directory is not empty: {project}")
    project.mkdir(parents=True, exist_ok=True)
    for name in ("assets", "cache", "previews", "output"):
        (project / name).mkdir(exist_ok=True)
    metadata = {"version": 1, "source_path": str(source), "source": inspect(source)}
    write_json(project / "project.json", metadata)
    return metadata


def project_data(project: Path) -> dict[str, Any]:
    try: raw = json.loads((project / "project.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise VidPPError(f"invalid project: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("source_path"), str): raise VidPPError("invalid project.json")
    if not Path(raw["source_path"]).is_file(): raise VidPPError("project source video no longer exists")
    return raw


def save_transcript(project: Path, transcript: Path) -> None:
    segments = load_transcript(transcript)
    write_json(project / "transcript.json", {"segments": [asdict(item) for item in segments]})


def transcribe(project: Path) -> None:
    """Use an explicit local adapter, otherwise local Whisper, to produce a transcript."""
    command_text = os.environ.get("VIDPP_TRANSCRIBE_COMMAND")
    source = project_data(project)["source_path"]
    target = project / "transcript.json"
    if command_text:
        command = shlex.split(command_text)
        if not command: raise VidPPError("VIDPP_TRANSCRIBE_COMMAND is empty")
        result = run([*command, source])
        target.write_text(result.stdout, encoding="utf-8")
    else:
        if not shutil.which("whisper"):
            raise VidPPError(
                "Whisper is not installed. Install it in the active virtual environment with "
                "'python -m pip install openai-whisper', then retry. Alternatively pass "
                "'--transcript transcript.json' or set VIDPP_TRANSCRIBE_COMMAND to a local "
                "transcriber that writes transcript JSON to stdout."
            )
        cache = project / "cache"
        command = ["whisper", source, "--model", os.environ.get("VIDPP_WHISPER_MODEL", "base"), "--output_dir", str(cache), "--output_format", "json", "--fp16", "False"]
        language = os.environ.get("VIDPP_WHISPER_LANGUAGE")
        if language: command.extend(["--language", language])
        run(command, capture=False)
        whisper_json = cache / (Path(source).stem + ".json")
        if not whisper_json.is_file():
            raise VidPPError("Whisper completed without producing its expected JSON transcript")
        target.write_text(whisper_json.read_text(encoding="utf-8"), encoding="utf-8")
    load_transcript(target)


_SILENCE_START = re.compile(r"silence_start: ([0-9.]+)")
_SILENCE_END = re.compile(r"silence_end: ([0-9.]+)")


def analyze(project: Path, template: Template) -> dict[str, Any]:
    meta = project_data(project)
    result = run(["ffmpeg", "-hide_banner", "-i", meta["source_path"], "-af", f"silencedetect=noise=-35dB:d={template.long_pause_threshold}", "-f", "null", "-"])
    ranges: list[dict[str, float]] = []
    starts: list[float] = []
    for line in result.stderr.splitlines():
        if match := _SILENCE_START.search(line): starts.append(float(match.group(1)))
        elif match := _SILENCE_END.search(line):
            end = float(match.group(1))
            if starts:
                start = starts.pop(0)
                ranges.append({"start": start, "end": end, "duration": end - start})
    for item in ranges: item["duration"] = item["end"] - item["start"]
    payload = {"version": 1, "source": meta["source"], "silences": ranges}
    write_json(project / "analysis.json", payload)
    LOG.debug("Silence ranges: %s", ranges)
    return payload


def _llm_operations(project: Path, analysis_data: dict[str, Any]) -> list[EditOperation]:
    base_url, model = os.environ.get("VIDPP_LLM_BASE_URL"), os.environ.get("VIDPP_LLM_MODEL")
    if not base_url or not model: return []
    transcript = json.loads((project / "transcript.json").read_text(encoding="utf-8"))
    prompt = ("You are a conservative video editor. Never change meaning. Prefer no edit when uncertain. "
              "Return JSON only: {\"operations\":[{\"id\":\"editor-001\",\"type\":\"remove\",\"source_start\":number,\"source_end\":number,\"reason\":string}]} . "
              "Only propose obvious abandoned false starts or superseded repetitions. Do not edit pauses.")
    body = {"model": model, "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps({"transcript": transcript, "analysis": analysis_data})}], "temperature": 0}
    request = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + os.environ["VIDPP_LLM_API_KEY"]} if os.environ.get("VIDPP_LLM_API_KEY") else {})})
    try:
        with urllib.request.urlopen(request, timeout=120) as response: answer = json.loads(response.read())
        content = answer["choices"][0]["message"]["content"]
        raw = json.loads(content)
    except Exception as exc: raise VidPPError(f"local LLM response was unusable: {exc}") from exc
    duration = project_data(project)["source"]["duration"]
    return [EditOperation.from_dict(item, duration) for item in raw.get("operations", [])]


def plan(project: Path, template: Template) -> list[EditOperation]:
    try: analysis_data = json.loads((project / "analysis.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise VidPPError("run analyze before plan") from exc
    transcript = load_transcript(project / "transcript.json")
    LOG.debug("Transcript blocks for editorial planning: %s", [asdict(item) for item in transcript])
    operations = [EditOperation(f"pause-{index:04d}", "shorten_pause", item["start"], item["end"], True, template.target_pause, "long unplanned pause") for index, item in enumerate(analysis_data.get("silences", []), 1) if item["duration"] > template.target_pause]
    operations.extend(_llm_operations(project, analysis_data))
    duration = project_data(project)["source"]["duration"]
    # LLM overlap is rejected rather than silently changing its proposed meaning.
    operations = load_valid_operations(operations, duration)
    write_json(project / "edit.json", edit_plan_json(operations))
    return operations


def load_valid_operations(operations: list[EditOperation], duration: float) -> list[EditOperation]:
    active = sorted((item for item in operations if item.enabled and item.type != "review"), key=lambda item: item.source_start)
    if len({item.id for item in operations}) != len(operations): raise VidPPError("generated edit operation IDs conflict")
    if any(right.source_start < left.source_end - .001 for left, right in zip(active, active[1:])): raise VidPPError("LLM operations overlap deterministic pause operations")
    for item in operations:
        EditOperation.from_dict(asdict(item), duration)
    return sorted(operations, key=lambda item: item.id)
