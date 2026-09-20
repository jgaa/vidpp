"""Application settings, distinct from visual templates."""
from dataclasses import dataclass
from pathlib import Path
import os
import unicodedata

import yaml

from .errors import VidPPError


@dataclass(frozen=True)
class TranscriptionConfig:
    model: str = "turbo"
    language: str | None = None
    phrases: tuple[str, ...] = ()


def transcription_config(project: Path) -> TranscriptionConfig:
    default = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "vidpp/config.yaml"
    explicit = os.environ.get("VIDPP_CONFIG")
    paths = [Path(explicit).expanduser() if explicit else default, project / "config.yaml"]
    values = {"model": "turbo", "language": None}
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
        if not isinstance(section, dict) or set(section) - {"model", "language", "phrases"}:
            raise VidPPError(f"invalid transcription settings in {path}")
        for key in values:
            if key in section:
                value = section[key]
                if not isinstance(value, str) or not value.strip():
                    raise VidPPError(f"transcription.{key} must be a non-empty string")
                values[key] = value.strip()
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
    return TranscriptionConfig(os.environ.get("VIDPP_WHISPER_MODEL") or values["model"],
                               os.environ.get("VIDPP_WHISPER_LANGUAGE") or values["language"], tuple(phrases))
