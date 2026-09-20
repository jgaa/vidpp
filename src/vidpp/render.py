from __future__ import annotations

from pathlib import Path
import logging
import re

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


def write_ass(path: Path, transcript: list[TranscriptSegment], template: Template) -> None:
    color = "&H00" + template.subtitle_color[5:7] + template.subtitle_color[3:5] + template.subtitle_color[1:3]
    outline = "&H00" + template.subtitle_outline_color[5:7] + template.subtitle_outline_color[3:5] + template.subtitle_outline_color[1:3]
    alignment = 2 if template.subtitle_position == "bottom" else 8
    margin_v = template.subtitle_bottom_margin
    lines = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: %d" % template.width, "PlayResY: %d" % template.height, "", "[V4+ Styles]", "Format: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BorderStyle,Outline,Alignment,MarginL,MarginR,MarginV,Encoding", f"Style: Caption,{template.subtitle_font},{template.subtitle_font_size},{color},{outline},1,{template.subtitle_outline_width},{alignment},80,80,{margin_v},1", "Style: Hook,%s,%d,%s,%s,1,2,%d,80,80,100,1" % (template.subtitle_font, template.subtitle_font_size, color, outline, 8 if template.hook_position == "top" else 2), "", "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"]
    if template.hook_enabled and template.hook_text:
        lines.append(f"Dialogue: 0,0:00:00.00,{_ass_time(template.hook_duration)},Hook,,0,0,0,,{_ass_text(template.hook_text)}")
    if template.subtitles_enabled:
        font = caption_font(template.subtitle_font, template.subtitle_font_size)
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


def build_filter(source_duration: float, operations: list[EditOperation], template: Template, ass_path: Path) -> str:
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
    if template.hook_image:
        y = 40 if template.hook_position == "top" else template.height - 300
        parts.append(f"movie='{_filter_path(template.hook_image)}':loop=1,setpts=N/FRAME_RATE/TB[hookbg]")
        parts.append(f"[composed][hookbg]overlay=(W-w)/2:{y}:shortest=1:enable='between(t,0,{template.hook_duration:.3f})'[withhook]")
        parts.append(f"[withhook]ass='{_filter_path(ass_path)}'[outv]")
    else: parts.append(f"[composed]ass='{_filter_path(ass_path)}'[outv]")
    return ";".join(parts)


def render(project: Path, template: Template, *, preview: bool = False) -> Path:
    data = project_data(project)
    transcript = load_transcript(project / "transcript.json")
    operations = load_edit_plan(project / "edit.json", float(data["source"]["duration"])) if (project / "edit.json").exists() else []
    ass_path = project / "cache" / "captions.ass"
    target = project / ("previews/preview.mp4" if preview else "output/final.mp4")
    ranges = timeline_ranges(operations, float(data["source"]["duration"]))
    log_edit_summary(operations, float(data["source"]["duration"]), ranges)
    write_ass(ass_path, remap_transcript(transcript, ranges), template)
    filter_graph = build_filter(float(data["source"]["duration"]), operations, template, ass_path)
    command = ["ffmpeg", "-y", "-i", data["source_path"], "-filter_complex", filter_graph, "-map", "[outv]", "-map", "[outa]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"]
    if template.fps != "source": command.extend(["-r", str(template.fps)])
    if preview: command.extend(["-preset", "ultrafast", "-crf", "30"])
    else: command.extend(["-preset", "medium", "-crf", "20", "-movflags", "+faststart"])
    command.append(str(target))
    run(command)
    return target
