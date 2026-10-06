"""Application settings, distinct from visual templates."""
from dataclasses import dataclass
from pathlib import Path
import os
import logging
import math
import unicodedata

import yaml

from .errors import VidPPError

LOG = logging.getLogger(__name__)
GLOBAL_KEYS = {"version", "transcription", "projects_dir", "output_file_dir", "subtitles"}
PROJECT_KEYS = {"version", "transcription", "subtitles"}


@dataclass(frozen=True)
class SubtitleArea:
    top: int
    left: int
    right: int
    bottom: int


@dataclass(frozen=True)
class SubtitleConfig:
    relative_y: float | None = None
    area: SubtitleArea | None = None


def _subtitle_settings(section: object, path: Path) -> SubtitleConfig:
    if not isinstance(section, dict) or set(section) - {"relative_y", "area"}:
        raise VidPPError(f"invalid subtitle settings in {path}")
    if "relative_y" in section and "area" in section:
        raise VidPPError(f"subtitles must choose relative_y or area, not both, in {path}")
    if "relative_y" in section:
        value = section["relative_y"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not -1 <= value <= 1 or not math.isfinite(value):
            raise VidPPError("subtitles.relative_y must be a finite number between -1 and 1")
        return SubtitleConfig(relative_y=float(value))
    if "area" in section:
        area = section["area"]
        if not isinstance(area, dict) or set(area) != {"top", "left", "right", "bottom"}:
            raise VidPPError("subtitles.area requires exactly top, left, right and bottom")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in area.values()):
            raise VidPPError("subtitles.area coordinates must be non-negative integer pixels")
        if area["right"] <= area["left"] or area["bottom"] <= area["top"]:
            raise VidPPError("subtitles.area requires left < right and top < bottom")
        return SubtitleConfig(area=SubtitleArea(**area))
    return SubtitleConfig()


def subtitle_config(project: Path) -> SubtitleConfig:
    """Project placement replaces global placement as a whole, including its mode."""
    global_path, explicit = _global_config_path()
    result = SubtitleConfig()
    for index, path in enumerate((global_path, project / "config.yaml")):
        if not path.exists():
            if index == 0 and explicit:
                raise VidPPError(f"configuration does not exist: {path}")
            continue
        raw = _read_config(path)
        if set(raw) - (GLOBAL_KEYS if index == 0 else PROJECT_KEYS):
            raise VidPPError(f"invalid configuration keys/version in {path}")
        if "subtitles" in raw:
            result = _subtitle_settings(raw["subtitles"], path)
            LOG.debug("Subtitle placement from %s: %s", path, result)
    return result


@dataclass(frozen=True)
class TranscriptionConfig:
    engine: str = "whisper"
    model: str = "turbo"
    recovery_model: str = "turbo"
    crisper_backend: str = "auto"
    language: str = "en"
    phrases: tuple[str, ...] = ()


@dataclass(frozen=True)
class AppConfig:
    projects_dir: Path
    output_file_dir: Path | None = None


def _global_config_path() -> tuple[Path, bool]:
    default = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "vidpp/config.yaml"
    explicit = os.environ.get("VIDPP_CONFIG")
    return (Path(explicit).expanduser() if explicit else default), explicit is not None


def _read_config(path: Path) -> dict:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise VidPPError(f"invalid configuration {path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("version", 1) != 1:
        raise VidPPError(f"invalid configuration keys/version in {path}")
    return raw


def _configured_directory(raw: dict, key: str, default: Path | None, config_path: Path) -> Path | None:
    value = raw.get(key)
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise VidPPError(f"{key} must be a non-empty directory path")
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def app_config() -> AppConfig:
    path, explicit = _global_config_path()
    if path.exists():
        raw = _read_config(path)
        if set(raw) - GLOBAL_KEYS:
            raise VidPPError(f"invalid configuration keys/version in {path}")
    elif explicit:
        raise VidPPError(f"configuration does not exist: {path}")
    else:
        raw = {}
    if "subtitles" in raw:
        _subtitle_settings(raw["subtitles"], path)
    projects = _configured_directory(raw, "projects_dir", Path.home() / ".local/vidpp/projects", path)
    output = _configured_directory(raw, "output_file_dir", None, path)
    assert projects is not None
    for key, directory in (("projects_dir", projects), ("output_file_dir", output)):
        if directory is not None and directory.exists() and not directory.is_dir():
            raise VidPPError(f"{key} is not a directory: {directory}")
    return AppConfig(projects, output)


def transcription_config(project: Path) -> TranscriptionConfig:
    global_path, explicit = _global_config_path()
    paths = [global_path, project / "config.yaml"]
    values = {"engine": "whisper", "model": "turbo", "crisper_backend": "auto", "language": "en"}
    recovery_model: str | None = None
    phrases, seen = [], set()
    for index, path in enumerate(paths):
        if not path.exists():
            if explicit and index == 0:
                raise VidPPError(f"configuration does not exist: {path}")
            continue
        raw = _read_config(path)
        allowed = GLOBAL_KEYS if index == 0 else PROJECT_KEYS
        if set(raw) - allowed:
            raise VidPPError(f"invalid configuration keys/version in {path}")
        if "subtitles" in raw:
            _subtitle_settings(raw["subtitles"], path)
        section = raw.get("transcription", {})
        if not isinstance(section, dict) or set(section) - {"engine", "model", "recovery_model", "crisper_backend", "language", "phrases"}:
            raise VidPPError(f"invalid transcription settings in {path}")
        for key in values:
            if key in section:
                value = section[key]
                if not isinstance(value, str) or not value.strip():
                    raise VidPPError(f"transcription.{key} must be a non-empty string")
                values[key] = value.strip()
        if "recovery_model" in section:
            value = section["recovery_model"]
            if not isinstance(value, str) or not value.strip():
                raise VidPPError("transcription.recovery_model must be a non-empty string")
            recovery_model = value.strip()
        items = section.get("phrases", [])
        if not isinstance(items, list):
            raise VidPPError("transcription.phrases must be a list of strings")
        for phrase in items:
            if not isinstance(phrase, str) or not phrase.strip():
                raise VidPPError("transcription phrases must be non-empty strings")
            phrase = " ".join(unicodedata.normalize("NFKC", phrase).split())
            if phrase.casefold() not in seen:
                seen.add(phrase.casefold())
                phrases.append(phrase)
    model = os.environ.get("VIDPP_TRANSCRIBE_MODEL") or os.environ.get("VIDPP_WHISPER_MODEL") or values["model"]
    recovery = os.environ.get("VIDPP_WHISPER_RECOVERY_MODEL") or recovery_model or model
    engine = os.environ.get("VIDPP_TRANSCRIBE_ENGINE") or values["engine"]
    crisper_backend = os.environ.get("VIDPP_CRISPER_BACKEND") or values["crisper_backend"]
    if engine not in {"whisper", "crisperwhisper"}:
        raise VidPPError("transcription.engine must be whisper or crisperwhisper")
    if crisper_backend not in {"auto", "ct2", "transformers"}:
        raise VidPPError("transcription.crisper_backend must be auto, ct2, or transformers")
    return TranscriptionConfig(engine, model, recovery, crisper_backend,
                               os.environ.get("VIDPP_WHISPER_LANGUAGE") or values["language"], tuple(phrases))
