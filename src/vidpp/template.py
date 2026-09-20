from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re
import yaml

from .errors import VidPPError

_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _mapping(raw: Any, name: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise VidPPError(f"template.{name} must be a mapping")
    return raw


def _positive(value: Any, name: str, default: int | float) -> int | float:
    value = default if value is None else value
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise VidPPError(f"template.{name} must be positive")
    return value


def _asset(value: Any, template_path: Path, name: str) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise VidPPError(f"template.{name} must be a file path")
    candidate = (template_path.parent / value).resolve()
    if not candidate.is_file():
        raise VidPPError(f"template asset does not exist: {value}")
    return candidate


@dataclass(frozen=True)
class Template:
    width: int = 1080
    height: int = 1920
    fps: str | float = "source"
    video_x: int = 0
    video_y: int = 0
    video_width: int = 1080
    video_height: int = 1920
    video_fit: str = "contain"
    background: Path | None = None
    subtitles_enabled: bool = True
    subtitle_font: str = "Noto Sans"
    subtitle_font_size: int = 44
    subtitle_color: str = "#FFFFFF"
    subtitle_outline_color: str = "#000000"
    subtitle_outline_width: int = 3
    subtitle_position: str = "bottom"
    subtitle_bottom_margin: int = 180
    subtitle_max_lines: int = 2
    hook_enabled: bool = False
    hook_text: str = ""
    hook_image: Path | None = None
    hook_duration: float = 4.0
    hook_position: str = "top"
    normalize_audio: bool = True
    long_pause_threshold: float = 1.5
    target_pause: float = 0.4


def load_template(path: Path | None, hook_override: str | None = None) -> Template:
    if path is None:
        data: dict[str, Any] = {}
        template_path = Path.cwd() / "default.yaml"
    else:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise VidPPError(f"invalid template {path}: {exc}") from exc
        if not isinstance(data, dict) or data.get("version", 1) != 1:
            raise VidPPError("template must be a version: 1 mapping")
        template_path = path.resolve()
    output, video, subtitles = _mapping(data.get("output"), "output"), _mapping(data.get("video"), "video"), _mapping(data.get("subtitles"), "subtitles")
    hook, audio, editing = _mapping(data.get("hook"), "hook"), _mapping(data.get("audio"), "audio"), _mapping(data.get("editing"), "editing")
    width, height = int(_positive(output.get("width"), "output.width", 1080)), int(_positive(output.get("height"), "output.height", 1920))
    # Defaults scale with output width; explicit font sizes remain output pixels.
    subtitles.setdefault("font_size", max(12, round(width * 44 / 1080)))
    subtitles.setdefault("bottom_margin", max(8, round(height * 180 / 1920)))
    fps = output.get("fps", "source")
    if fps != "source": _positive(fps, "output.fps", 30)
    fit = video.get("fit", "contain")
    if fit not in {"contain", "cover"}: raise VidPPError("template.video.fit must be contain or cover")
    video_x, video_y = int(video.get("x", 0)), int(video.get("y", 0))
    video_width, video_height = int(_positive(video.get("width"), "video.width", width)), int(_positive(video.get("height"), "video.height", height))
    if video_x < 0 or video_y < 0 or video_x + video_width > width or video_y + video_height > height:
        raise VidPPError("template.video rectangle must fit inside output dimensions")
    def color(section: dict[str, Any], key: str, default: str) -> str:
        result = section.get(key, default)
        if not isinstance(result, str) or not _COLOR.fullmatch(result): raise VidPPError(f"template.subtitles.{key} must be #RRGGBB")
        return result
    position = subtitles.get("position", "bottom")
    hook_position = hook.get("position", "top")
    if position not in {"top", "bottom"} or hook_position not in {"top", "bottom"}: raise VidPPError("subtitle and hook positions must be top or bottom")
    hook_text = hook_override if hook_override is not None else hook.get("text", "")
    if not isinstance(hook_text, str): raise VidPPError("template.hook.text must be a string")
    enabled = hook.get("enabled", bool(hook_text))
    if not isinstance(enabled, bool): raise VidPPError("template.hook.enabled must be boolean")
    return Template(width, height, fps, video_x, video_y, video_width, video_height, fit, _asset(video.get("background"), template_path, "video.background"), bool(subtitles.get("enabled", True)), str(subtitles.get("font", "Noto Sans")), int(_positive(subtitles.get("font_size"), "subtitles.font_size", 54)), color(subtitles, "color", "#FFFFFF"), color(subtitles, "outline_color", "#000000"), int(_positive(subtitles.get("outline_width"), "subtitles.outline_width", 3)), position, int(_positive(subtitles.get("bottom_margin"), "subtitles.bottom_margin", 180)), int(_positive(subtitles.get("max_lines"), "subtitles.max_lines", 2)), enabled, hook_text, _asset(hook.get("image"), template_path, "hook.image"), float(_positive(hook.get("duration"), "hook.duration", 4.0)), hook_position, bool(audio.get("normalize", True)), float(_positive(editing.get("long_pause_threshold"), "editing.long_pause_threshold", 1.5)), float(_positive(editing.get("target_pause"), "editing.target_pause", 0.4)))
