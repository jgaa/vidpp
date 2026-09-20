from __future__ import annotations

from pathlib import Path
import logging
import math

try:
    from PIL import Image, ImageDraw
except ModuleNotFoundError:  # Existing editable installs may predate this dependency.
    Image = ImageDraw = None

from .core import project_data, run
from .errors import VidPPError
from .models import EditOperation, TranscriptSegment, load_edit_plan, load_transcript
from .template import Template
from .captions import caption_chunks, caption_font, remap_transcript

LOG = logging.getLogger(__name__)


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, centiseconds = divmod(centiseconds, 360000)
    minutes, centiseconds = divmod(centiseconds, 6000)
    return f"{hours}:{minutes:02}:{centiseconds // 100:02}.{centiseconds % 100:02}"


def _ass_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def _ass_color(value: str) -> str:
    """Convert #RRGGBB or opacity-first #AARRGGBB to ASS inverted alpha + BGR."""
    opacity, rgb = (255, value[1:]) if len(value) == 7 else (int(value[1:3], 16), value[3:])
    return f"&H{255 - opacity:02X}{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}"


def write_ass(path: Path, transcript: list[TranscriptSegment], template: Template, *, include_hook: bool = True) -> None:
    color = _ass_color(template.subtitle_color)
    outline = _ass_color(template.subtitle_outline_color)
    background = _ass_color(template.subtitle_background) if template.subtitle_background else "&HFF000000"
    alignment = 2 if template.subtitle_position == "bottom" else 8
    margin_v = template.subtitle_bottom_margin
    border_style = 3 if template.subtitle_background else 1
    caption_outline = background if template.subtitle_background else outline
    hook_margin = max(24, round(template.height * 140 / 1920))
    style_format = "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding"
    caption_style = (
        f"Style: Caption,{template.subtitle_font},{template.subtitle_font_size},{color},{color},"
        f"{caption_outline},{background},{-1 if template.subtitle_weight >= 600 else 0},0,0,0,100,100,0,0,"
        f"{border_style},{template.subtitle_outline_width},1,{alignment},80,80,{margin_v},1"
    )
    hook_style = (
        f"Style: Hook,{template.hook_font},{template.hook_font_size},{_ass_color(template.hook_color)},"
        f"{_ass_color(template.hook_color)},{outline},&HFF000000,{-1 if template.hook_weight >= 600 else 0},"
        f"0,0,0,100,100,0,0,1,2,1,{8 if template.hook_position == 'top' else 2},80,80,{hook_margin},1"
    )
    lines = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: %d" % template.width, "PlayResY: %d" % template.height, "", "[V4+ Styles]", style_format, caption_style, hook_style, "", "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"]
    if include_hook and template.hook_enabled and template.hook_text:
        lines.append(f"Dialogue: 0,0:00:00.00,{_ass_time(template.hook_duration)},Hook,,0,0,0,,{_ass_text(template.hook_text)}")
    if template.subtitles_enabled:
        font = caption_font(template.subtitle_font, template.subtitle_font_size, template.subtitle_weight)
        margin = max(8, round(template.width * 80 / 1080))
        # Disable automatic wrapping; line breaks below are measured against the font.
        lines.insert(2, "WrapStyle: 2")
        lines = [line.replace(",80,80,", f",{margin},{margin},") if line.startswith("Style:") else line for line in lines]
        available = template.width - 2 * margin - 2 * template.subtitle_outline_width
        for item in caption_chunks(
            transcript,
            template.subtitle_max_lines,
            font=font,
            width=available,
            max_words=template.subtitle_max_words,
            max_characters=template.subtitle_max_characters,
            pause_threshold=template.subtitle_pause_threshold,
            max_duration=template.subtitle_max_duration,
            linger=template.subtitle_linger,
        ):
            lines.append(f"Dialogue: 0,{_ass_time(item.start)},{_ass_time(item.end)},Caption,,0,0,0,,{_ass_text(item.text)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _rgba(value: str) -> tuple[int, int, int, int]:
    opacity, rgb = (255, value[1:]) if len(value) == 7 else (int(value[1:3], 16), value[3:])
    return int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16), opacity


def _wrap_hook(text: str, font, max_width: int) -> str:
    wrapped: list[str] = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if line and font.getlength(candidate) > max_width:
                wrapped.append(line)
                line = word
            else:
                line = candidate
            if font.getlength(word) > max_width:
                raise VidPPError(f"Hook word {word!r} does not fit; reduce hook.font_size or hook.padding_x")
        wrapped.append(line)
    return "\n".join(wrapped)


def render_hook_bubble(path: Path, template: Template) -> Path:
    if Image is None or ImageDraw is None:
        raise VidPPError(
            "Pillow is required for hook rendering. Update the active virtual environment with "
            "'python -m pip install -e .', then retry."
        )
    font = caption_font(template.hook_font, template.hook_font_size, template.hook_weight)
    max_text_width = max(1, round(template.width * .88) - 2 * template.hook_padding_x)
    text = _wrap_hook(template.hook_text, font, max_text_width)
    spacing = max(1, round(template.hook_font_size * .18))
    probe = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(probe)
    left, top, right, bottom = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align="center")
    width = math.ceil(right - left + 2 * template.hook_padding_x)
    height = math.ceil(bottom - top + 2 * template.hook_padding_y)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=template.hook_corner_radius, fill=_rgba(template.hook_background_color))
    draw.multiline_text(
        (width / 2, template.hook_padding_y - top),
        text,
        font=font,
        fill=_rgba(template.hook_color),
        spacing=spacing,
        align="center",
        anchor="ma",
    )
    image.save(path)
    LOG.debug(
        "Rendered hook bubble %s: %dx%d, font=%r size=%d weight=%d, radius=%d, padding=%dx%d, text=%r",
        path,
        width,
        height,
        template.hook_font,
        template.hook_font_size,
        template.hook_weight,
        template.hook_corner_radius,
        template.hook_padding_x,
        template.hook_padding_y,
        text,
    )
    return path


def timeline_ranges(operations: list[EditOperation], duration: float) -> list[tuple[float, float]]:
    cursor, ranges = 0.0, []
    for op in sorted((item for item in operations if item.enabled and item.type != "review"), key=lambda item: item.source_start):
        if cursor < op.source_start: ranges.append((cursor, op.source_start))
        if op.type == "shorten_pause": ranges.append((op.source_start, op.source_start + (op.target_duration or 0)))
        cursor = op.source_end
    if cursor < duration: ranges.append((cursor, duration))
    return [(start, end) for start, end in ranges if end - start > .01]


def log_edit_summary(operations: list[EditOperation], duration: float, ranges: list[tuple[float, float]]) -> None:
    enabled = [item for item in operations if item.enabled and item.type != "review"]
    removed = max(0.0, duration - sum(end - start for start, end in ranges))
    if operations and not enabled:
        LOG.warning(
            "%d proposed edits exist but none are enabled; rendering the full source timeline. "
            "Review edit.json and enable only justified cuts.",
            len(operations),
        )
    elif enabled:
        LOG.info("Applying %d enabled edits; output timeline is shortened by %.3f seconds.", len(enabled), removed)
    else:
        LOG.info("No edit operations exist; rendering the full source timeline.")


def _filter_path(path: Path) -> str:
    # This is generated from a private cache filename, not model/template input.
    return str(path).replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")


def build_filter(source_duration: float, operations: list[EditOperation], template: Template, ass_path: Path, hook_overlay: Path | None = None) -> str:
    ranges = timeline_ranges(operations, source_duration)
    if not ranges: raise VidPPError("enabled edits remove the entire source")
    parts: list[str] = []
    labels: list[str] = []
    for index, (start, end) in enumerate(ranges):
        parts.extend([f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{index}]", f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{index}]"])
        labels.append(f"[v{index}][a{index}]")
    parts.append("".join(labels) + f"concat=n={len(ranges)}:v=1:a=1[cutv][cuta]")
    if template.normalize_audio:
        parts.append("[cuta]loudnorm=I=-16:TP=-1.5:LRA=11[outa]")
    else:
        parts.append("[cuta]anull[outa]")
    if template.video_fit == "contain":
        parts.append(f"[cutv]scale={template.video_width}:{template.video_height}:force_original_aspect_ratio=decrease,pad={template.video_width}:{template.video_height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[video]")
    else:
        parts.append(f"[cutv]scale={template.video_width}:{template.video_height}:force_original_aspect_ratio=increase,crop={template.video_width}:{template.video_height},setsar=1[video]")
    if template.background:
        parts.append(f"movie='{_filter_path(template.background)}',scale={template.width}:{template.height}[bg]")
    else:
        parts.append(f"color=c=black:s={template.width}x{template.height}[bg]")
    parts.append(f"[bg][video]overlay={template.video_x}:{template.video_y}:shortest=1[composed]")
    hook_overlay = hook_overlay or (template.hook_image if template.hook_enabled else None)
    if hook_overlay:
        margin = max(24, round(template.height * 140 / 1920))
        y = str(margin) if template.hook_position == "top" else f"H-h-{margin}"
        parts.append(
            f"movie='{_filter_path(hook_overlay)}':loop=1,"
            f"trim=duration={template.hook_duration:.3f},setpts=PTS-STARTPTS[hookbg]"
        )
        parts.append(
            f"[composed][hookbg]overlay=(W-w)/2:{y}:eof_action=pass:repeatlast=0:"
            f"enable='between(t,0,{template.hook_duration:.3f})'[withhook]"
        )
        parts.append(f"[withhook]ass='{_filter_path(ass_path)}'[outv]")
    else: parts.append(f"[composed]ass='{_filter_path(ass_path)}'[outv]")
    return ";".join(parts)


def render(project: Path, template: Template, *, preview: bool = False, apply_edits: bool = True) -> Path:
    data = project_data(project)
    transcript = load_transcript(project / "transcript.json")
    stored_operations = load_edit_plan(project / "edit.json", float(data["source"]["duration"])) if (project / "edit.json").exists() else []
    operations = stored_operations if apply_edits else []
    if not apply_edits:
        LOG.info("Editing disabled; ignoring %d stored edit operations and keeping the complete timeline.", len(stored_operations))
    ass_path = project / "cache" / "captions.ass"
    target = project / ("previews/preview.mp4" if preview else "output/final.mp4")
    ranges = timeline_ranges(operations, float(data["source"]["duration"]))
    log_edit_summary(operations, float(data["source"]["duration"]), ranges)
    generated_hook = None
    if template.hook_enabled and template.hook_text and template.hook_image is None:
        generated_hook = render_hook_bubble(project / "cache" / "hook.png", template)
    write_ass(ass_path, remap_transcript(transcript, ranges), template, include_hook=generated_hook is None)
    filter_graph = build_filter(float(data["source"]["duration"]), operations, template, ass_path, generated_hook)
    command = ["ffmpeg", "-y", "-i", data["source_path"], "-filter_complex", filter_graph, "-map", "[outv]", "-map", "[outa]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"]
    if template.fps != "source": command.extend(["-r", str(template.fps)])
    if preview: command.extend(["-preset", "ultrafast", "-crf", "30"])
    else: command.extend(["-preset", "medium", "-crf", "20", "-movflags", "+faststart"])
    command.append(str(target))
    run(command)
    return target
