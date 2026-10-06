"""Application settings, distinct from visual templates."""
from dataclasses import dataclass
from pathlib import Path
import os
import json
import logging
import math
import tempfile
import unicodedata

import yaml

from .errors import VidPPError

LOG = logging.getLogger(__name__)
GLOBAL_KEYS = {"version", "transcription", "projects_dir", "output_file_dir", "subtitles"}
PROJECT_OVERRIDE_KEYS = {"version", "transcription", "subtitles", "hook"}
PROJECT_KEYS = PROJECT_OVERRIDE_KEYS | {"source_path", "source", "sources"}


def _merge_project_values(stored: dict, overrides: dict) -> dict:
    result = dict(stored)
    for key, value in overrides.items():
        if key != "subtitles" and isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _merge_project_values(result[key], value)
        else:
            result[key] = value
    return result


def write_project_config(project: Path, values: dict) -> None:
    """Atomically persist stored values only; never materialize defaults."""
    path = project / "config.yaml"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=project, prefix=".config-", suffix=".yaml", delete=False) as stream:
            temporary = Path(stream.name)
            yaml.safe_dump(values, stream, sort_keys=False, allow_unicode=True)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            temporary.chmod(path.stat().st_mode & 0o777)
        temporary.replace(path)
    except (OSError, yaml.YAMLError) as exc:
        raise VidPPError(f"cannot write project configuration {path}: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def migrate_project_config(project: Path) -> None:
    """Consolidate legacy metadata and explicit YAML overrides without defaults."""
    legacy = project / "project.json"
    if not legacy.is_file():
        return
    path = project / "config.yaml"
    try:
        values = json.loads(legacy.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VidPPError(f"invalid legacy project {legacy}: {exc}") from exc
    if not isinstance(values, dict) or values.get("version", 1) != 1:
        raise VidPPError(f"invalid legacy project {legacy}: expected a version 1 mapping")
    overrides = _read_config(path) if path.exists() else {}
    # Explicit subtitle placement replaces its legacy counterpart, so
    # placement modes never accidentally merge and empty overrides stay empty.
    merged = _merge_project_values(values, overrides)
    LOG.debug("Migrating project configuration: legacy=%s, overrides=%s, merged=%s", values, overrides, merged)
    write_project_config(project, merged)
    backup = project / "project.json.bak"
    index = 1
    while backup.exists():
        backup = project / f"project.json.bak.{index}"
        index += 1
    try:
        legacy.rename(backup)
    except OSError as exc:
        raise VidPPError(f"configuration migrated to {path}, but cannot archive {legacy}: {exc}") from exc
    LOG.info("Migrated project settings to %s; original saved as %s", path, backup)


def read_project_config(project: Path) -> dict:
    migrate_project_config(project)
    path = project / "config.yaml"
    values = _read_config(path) if path.exists() else {}
    if set(values) - PROJECT_KEYS:
        raise VidPPError(f"invalid configuration keys/version in {path}")
    return values


def apply_project_config(project: Path, path: Path) -> None:
    """Merge supplied overrides with required project data rather than replacing it."""
    overrides = _read_config(path)
    if set(overrides) - PROJECT_OVERRIDE_KEYS:
        raise VidPPError(f"project overrides may contain only version, hook, transcription and subtitles in {path}")
    values = read_project_config(project)
    write_project_config(project, _merge_project_values(values, overrides))
    LOG.debug("Applied project overrides from %s: %s", path, overrides)


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
    project_values = read_project_config(project)
    for index, path in enumerate((global_path, project / "config.yaml")):
        if not path.exists():
            if index == 0 and explicit:
                raise VidPPError(f"configuration does not exist: {path}")
            continue
        raw = _read_config(path) if index == 0 else project_values
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
    project_values = read_project_config(project)
    values = {"engine": "whisper", "model": "turbo", "crisper_backend": "auto", "language": "en"}
    recovery_model: str | None = None
    phrases, seen = [], set()
    for index, path in enumerate(paths):
        if not path.exists():
            if explicit and index == 0:
                raise VidPPError(f"configuration does not exist: {path}")
            continue
        raw = _read_config(path) if index == 0 else project_values
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
