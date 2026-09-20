"""Application settings, distinct from visual templates."""
from dataclasses import dataclass
from pathlib import Path
import os
import unicodedata

import yaml

from .errors import VidPPError


@dataclass(frozen=True)
class TranscriptionConfig:
    engine: str = "whisper"
    model: str = "turbo"
    recovery_model: str = "turbo"
    crisper_backend: str = "auto"
    language: str = "en"
    phrases: tuple[str, ...] = ()


def transcription_config(project: Path) -> TranscriptionConfig:
    default = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "vidpp/config.yaml"
    explicit = os.environ.get("VIDPP_CONFIG")
    paths = [Path(explicit).expanduser() if explicit else default, project / "config.yaml"]
    values = {"engine": "whisper", "model": "turbo", "crisper_backend": "auto", "language": "en"}
    recovery_model: str | None = None
    phrases, seen = [], set()
    for path in paths:
        if not path.exists():
            if explicit and path == paths[0]:
                raise VidPPError(f"configuration does not exist: {path}")
            continue
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise VidPPError(f"invalid configuration {path}: {exc}") from exc
        if not isinstance(raw, dict) or raw.get("version", 1) != 1 or set(raw) - {"version", "transcription"}:
            raise VidPPError(f"invalid configuration keys/version in {path}")
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
