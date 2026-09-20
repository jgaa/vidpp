from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re
import yaml

from .errors import VidPPError

_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_RGBA_COLOR = re.compile(r"^#[0-9A-Fa-f]{8}$")
_OUTPUT_FORMAT = re.compile(r"^p([1-9][0-9]{2,3})$")


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


def _nonnegative(value: Any, name: str, default: int | float) -> int | float:
    value = default if value is None else value
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise VidPPError(f"template.{name} must be non-negative")
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


def _color(section: dict[str, Any], key: str, default: str, section_name: str) -> str:
    result = section.get(key, default)
    if not isinstance(result, str) or not _COLOR.fullmatch(result):
        raise VidPPError(f"template.{section_name}.{key} must be #RRGGBB")
    return result.upper()


def _rgba_color(section: dict[str, Any], key: str, default: str, section_name: str) -> str:
    result = section.get(key, default)
    if not isinstance(result, str) or not (_COLOR.fullmatch(result) or _RGBA_COLOR.fullmatch(result)):
        raise VidPPError(f"template.{section_name}.{key} must be #RRGGBB or #AARRGGBB")
    return result.upper()


def _weight(value: Any, name: str, default: int) -> int:
    value = default if value is None else value
    if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 900 or value % 100:
        raise VidPPError(f"template.{name} must be a multiple of 100 from 100 through 900")
    return value


def _subtitle_background(value: Any) -> str | None:
    if value is None or (isinstance(value, str) and value.casefold() == "none"):
        return None
    if not isinstance(value, str) or not (_COLOR.fullmatch(value) or _RGBA_COLOR.fullmatch(value)):
        raise VidPPError("template.subtitles.background must be none, #RRGGBB, or #AARRGGBB")
    return value.upper()


def output_dimensions(
    output: dict[str, Any],
    *,
    source_width: int | None,
    source_height: int | None,
    format_override: str | None,
    orientation_override: str | None,
) -> tuple[int, int]:
    has_width, has_height = "width" in output, "height" in output
    if has_width != has_height:
        raise VidPPError("template.output.width and height must be specified together")
    if "format" in output and has_width:
        raise VidPPError("template.output must use either format or width/height")
    if has_width and format_override is None and orientation_override is None:
        return int(_positive(output["width"], "output.width", 1280)), int(_positive(output["height"], "output.height", 720))

    output_format = format_override or output.get("format", "p720")
    if not isinstance(output_format, str) or not (match := _OUTPUT_FORMAT.fullmatch(output_format.casefold())):
        raise VidPPError("output format must look like p720 or p1080")
    short_edge = int(match.group(1))
    if not 240 <= short_edge <= 4320:
        raise VidPPError("output format must be between p240 and p4320")
    long_edge = round(short_edge * 16 / 9)
    long_edge += long_edge % 2

    orientation = orientation_override or output.get("orientation", "auto")
    if orientation not in {"auto", "portrait", "landscape"}:
        raise VidPPError("output orientation must be auto, portrait, or landscape")
    if orientation == "auto":
        orientation = "portrait" if source_width is not None and source_height is not None and source_height > source_width else "landscape"
    return (short_edge, long_edge) if orientation == "portrait" else (long_edge, short_edge)


@dataclass(frozen=True)
class Template:
    width: int = 1280
    height: int = 720
    fps: str | float = "source"
    video_x: int = 0
    video_y: int = 0
    video_width: int = 1280
    video_height: int = 720
    video_fit: str = "contain"
    background: Path | None = None
    subtitles_enabled: bool = True
    subtitle_font: str = "Noto Sans"
    subtitle_font_size: int = 54
    subtitle_weight: int = 600
    subtitle_color: str = "#F8F8F8"
    subtitle_outline_color: str = "#101010"
    subtitle_outline_width: int = 3
    subtitle_background: str | None = None
    subtitle_position: str = "bottom"
    subtitle_bottom_margin: int = 180
    subtitle_max_lines: int = 2
    hook_enabled: bool = False
    hook_text: str = ""
    hook_image: Path | None = None
    hook_duration: float = 4.0
    hook_position: str = "top"
    hook_font: str = "Noto Sans"
    hook_font_size: int = 72
    hook_weight: int = 700
    hook_color: str = "#FFFFFF"
    hook_background_color: str = "#D90F0F0F"
    hook_corner_radius: int = 16
    hook_padding_x: int = 21
    hook_padding_y: int = 12
    normalize_audio: bool = True
    long_pause_threshold: float = 1.5
    target_pause: float = 0.4
    subtitle_max_words: int = 8
    subtitle_linger: float = 1.0
    subtitle_pause_threshold: float = 0.45
    subtitle_max_duration: float = 3.5
    subtitle_max_characters: int = 48


def load_template(
    path: Path | None,
    hook_override: str | None = None,
    *,
    source_width: int | None = None,
    source_height: int | None = None,
    output_format: str | None = None,
    orientation: str | None = None,
) -> Template:
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
    width, height = output_dimensions(output, source_width=source_width, source_height=source_height, format_override=output_format, orientation_override=orientation)
    # Visual defaults use a 1080x1920 reference frame. Explicit dimensions are pixels.
    subtitles.setdefault("font_size", max(12, round(min(width, height) * 54 / 720)))
    subtitles.setdefault("bottom_margin", max(8, round(height * 180 / 1920)))
    subtitles.setdefault("outline_width", max(3, round(min(width, height) * 3 / 1080)))
    hook.setdefault("font_size", max(16, round(min(width, height) * 108 / 1080)))
    hook.setdefault("corner_radius", max(1, round(min(width, height) * 24 / 1080)))
    hook.setdefault("padding_x", max(1, round(min(width, height) * 32 / 1080)))
    hook.setdefault("padding_y", max(1, round(min(width, height) * 18 / 1080)))
    fps = output.get("fps", "source")
    if fps != "source": _positive(fps, "output.fps", 30)
    fit = video.get("fit", "contain")
    if fit not in {"contain", "cover"}: raise VidPPError("template.video.fit must be contain or cover")
    video_x, video_y = int(video.get("x", 0)), int(video.get("y", 0))
    video_width, video_height = int(_positive(video.get("width"), "video.width", width)), int(_positive(video.get("height"), "video.height", height))
    if video_x < 0 or video_y < 0 or video_x + video_width > width or video_y + video_height > height:
        raise VidPPError("template.video rectangle must fit inside output dimensions")
    position = subtitles.get("position", "bottom")
    hook_position = hook.get("position", "top")
    if position not in {"top", "bottom"} or hook_position not in {"top", "bottom"}: raise VidPPError("subtitle and hook positions must be top or bottom")
    hook_text = hook_override if hook_override is not None else hook.get("text", "")
    if not isinstance(hook_text, str): raise VidPPError("template.hook.text must be a string")
    enabled = hook.get("enabled", bool(hook_text))
    if not isinstance(enabled, bool): raise VidPPError("template.hook.enabled must be boolean")
    return Template(
        width=width,
        height=height,
        fps=fps,
        video_x=video_x,
        video_y=video_y,
        video_width=video_width,
        video_height=video_height,
        video_fit=fit,
        background=_asset(video.get("background"), template_path, "video.background"),
        subtitles_enabled=bool(subtitles.get("enabled", True)),
        subtitle_font=str(subtitles.get("font", "Noto Sans")),
        subtitle_font_size=int(_positive(subtitles.get("font_size"), "subtitles.font_size", 54)),
        subtitle_weight=_weight(subtitles.get("weight"), "subtitles.weight", 600),
        subtitle_color=_color(subtitles, "color", "#F8F8F8", "subtitles"),
        subtitle_outline_color=_color(subtitles, "outline_color", "#101010", "subtitles"),
        subtitle_outline_width=int(_positive(subtitles.get("outline_width"), "subtitles.outline_width", 3)),
        subtitle_background=_subtitle_background(subtitles.get("background")),
        subtitle_position=position,
        subtitle_bottom_margin=int(_positive(subtitles.get("bottom_margin"), "subtitles.bottom_margin", 180)),
        subtitle_max_lines=int(_positive(subtitles.get("max_lines"), "subtitles.max_lines", 2)),
        hook_enabled=enabled,
        hook_text=hook_text,
        hook_image=_asset(hook.get("image"), template_path, "hook.image"),
        hook_duration=float(_positive(hook.get("duration"), "hook.duration", 4.0)),
        hook_position=hook_position,
        hook_font=str(hook.get("font", "Noto Sans")),
        hook_font_size=int(_positive(hook.get("font_size"), "hook.font_size", 72)),
        hook_weight=_weight(hook.get("weight"), "hook.weight", 700),
        hook_color=_color(hook, "color", "#FFFFFF", "hook"),
        hook_background_color=_rgba_color(hook, "background_color", "#D90F0F0F", "hook"),
        hook_corner_radius=int(_nonnegative(hook.get("corner_radius"), "hook.corner_radius", 16)),
        hook_padding_x=int(_nonnegative(hook.get("padding_x"), "hook.padding_x", 21)),
        hook_padding_y=int(_nonnegative(hook.get("padding_y"), "hook.padding_y", 12)),
        normalize_audio=bool(audio.get("normalize", True)),
        long_pause_threshold=float(_positive(editing.get("long_pause_threshold"), "editing.long_pause_threshold", 1.5)),
        target_pause=float(_positive(editing.get("target_pause"), "editing.target_pause", 0.4)),
        subtitle_max_words=int(_positive(subtitles.get("max_words"), "subtitles.max_words", 8)),
        subtitle_linger=float(_nonnegative(subtitles.get("linger"), "subtitles.linger", 1.0)),
        subtitle_pause_threshold=float(_positive(subtitles.get("pause_threshold"), "subtitles.pause_threshold", 0.45)),
        subtitle_max_duration=float(_positive(subtitles.get("max_duration"), "subtitles.max_duration", 3.5)),
        subtitle_max_characters=int(_positive(subtitles.get("max_characters"), "subtitles.max_characters", 48)),
    )
