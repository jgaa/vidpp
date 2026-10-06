import io
import json
import shutil
import subprocess

from PIL import Image
import pytest

from vidpp.errors import VidPPError
from vidpp.models import EditOperation, TranscriptSegment
from vidpp.render import build_filter, log_edit_summary, remap_transcript, render, render_hook_bubble, render_target, timeline_ranges, write_ass
from vidpp.core import create_project
from vidpp.template import Template
from vidpp.config import SubtitleConfig, SubtitleArea, read_project_config, write_project_config
from vidpp.captions import caption_font


def test_shorten_pause_generates_short_retained_range(tmp_path):
    ops = [EditOperation("pause", "shorten_pause", 2, 5, target_duration=.4)]
    assert timeline_ranges(ops, 7) == [(0.0, 2), (2, 2.4), (5, 7)]
    graph = build_filter(7, ops, Template(), tmp_path / "captions.ass")
    assert "concat=n=3" in graph
    assert "pad=1280:720" in graph


def test_hook_overlay_is_duration_bounded_and_does_not_truncate_video(tmp_path):
    template = Template(hook_duration=3.5)
    graph = build_filter(7, [], template, tmp_path / "captions.ass", tmp_path / "hook.png")
    assert "movie='" in graph
    assert ":loop=1" not in graph
    assert "eof_action=repeat:repeatlast=1" in graph
    assert "enable='between(t,0,3.500)'" in graph
    assert "shortest=1:enable" not in graph


def test_custom_render_target_is_created_without_overwriting_source(tmp_path):
    source = tmp_path / "source.mp4"
    source.touch()
    project = tmp_path / "project.vidpp"
    target = tmp_path / "archive/social/post.mp4"
    data = {"source_path": str(source)}
    assert render_target(project, data, preview=False, output_file=target) == target
    assert target.parent.is_dir()
    with pytest.raises(VidPPError, match="must not overwrite source"):
        render_target(project, data, preview=False, output_file=source)


def test_render_target_requires_mp4(tmp_path):
    source = tmp_path / "source.mp4"
    source.touch()
    with pytest.raises(VidPPError, match=".mp4 extension"):
        render_target(tmp_path / "project.vidpp", {"source_path": str(source)}, preview=False, output_file=tmp_path / "video.mov")


def test_caption_timestamps_follow_cut_timeline():
    transcript = [TranscriptSegment(0, 1, "before"), TranscriptSegment(3, 4, "after")]
    mapped = remap_transcript(transcript, [(0, 1), (3, 5)])
    assert [(item.start, item.end) for item in mapped] == [(0, 1), (1, 2)]


def test_disabled_proposals_warn_that_full_timeline_is_rendered(caplog):
    operations = [EditOperation("editor-001", "remove", 2, 5, enabled=False)]
    ranges = timeline_ranges(operations, 7)
    log_edit_summary(operations, 7, ranges)
    assert ranges == [(0.0, 7)]
    assert "none are enabled; rendering the full source timeline" in caplog.text


def test_enabled_edit_logs_removed_duration(caplog):
    caplog.set_level("INFO")
    operations = [EditOperation("editor-001", "remove", 2, 5, enabled=True)]
    ranges = timeline_ranges(operations, 7)
    log_edit_summary(operations, 7, ranges)
    assert "Applying 1 enabled edits; output timeline is shortened by 3.000 seconds" in caplog.text


def test_hook_bubble_is_text_sized_rounded_and_semi_opaque(tmp_path):
    path = tmp_path / "hook.png"
    template = Template(
        width=720,
        height=1280,
        hook_enabled=True,
        hook_text="Experiments? When?",
        hook_font="DejaVu Sans",
        hook_font_size=72,
    )
    render_hook_bubble(path, template)
    with Image.open(path) as image:
        assert image.mode == "RGBA"
        assert image.width < template.width
        assert image.height < template.height // 4
        assert image.getpixel((0, 0))[3] == 0
        assert image.getpixel((image.width // 2, image.height // 2))[3] >= 217


def test_ass_uses_independent_weighted_subtitle_style(tmp_path):
    path = tmp_path / "captions.ass"
    template = Template(
        width=720,
        height=1280,
        subtitle_font="DejaVu Sans",
        subtitle_weight=600,
        hook_enabled=True,
        hook_text="Hook",
        hook_font="DejaVu Sans",
        hook_font_size=72,
        hook_weight=700,
    )
    write_ass(path, [], template, include_hook=False)
    contents = path.read_text()
    assert "Style: Caption,DejaVu Sans,54,&H00F8F8F8" in contents
    assert ",&H00101010,&HFF000000,-1," in contents
    assert "Style: Hook,DejaVu Sans,72" in contents
    assert "Dialogue: 0,0:00:00.00" not in contents


@pytest.mark.parametrize("position,y", [("bottom", 720 - 180 - 72), ("top", 180 - 72)])
def test_relative_subtitle_offset_preserves_style(tmp_path, position, y):
    path = tmp_path / "captions.ass"
    template = Template(subtitle_font="DejaVu Sans", subtitle_position=position)
    transcript = [TranscriptSegment(0, 1, "A caption")]
    write_ass(path, transcript, template)
    original = path.read_text()
    write_ass(path, transcript, template, placement=SubtitleConfig(relative_y=-.1))
    shifted = path.read_text()
    assert shifted == original.replace("A caption", f"{{\\pos(640,{y})}}A caption")
    write_ass(path, transcript, template, placement=SubtitleConfig())
    assert path.read_text() == original


def test_absolute_area_scales_font_and_wraps_inside_rectangle(tmp_path):
    path = tmp_path / "captions.ass"
    template = Template(subtitle_font="DejaVu Sans", hook_font_size=72)
    area = SubtitleArea(top=100, left=100, right=500, bottom=180)
    transcript = [TranscriptSegment(0, 2, "Wideword followed by several more words to wrap.")]
    write_ass(path, transcript, template, placement=SubtitleConfig(area=area))
    contents = path.read_text()
    style = next(line.split(",") for line in contents.splitlines() if line.startswith("Style: Caption,"))
    size, outline = int(style[2]), int(style[17])
    assert size < template.subtitle_font_size
    font = caption_font(template.subtitle_font, size, template.subtitle_weight)
    assert sum(font.getmetrics()) * template.subtitle_max_lines + 2 * (outline + 1) <= 80
    assert "Style: Hook,Noto Sans,72," in contents
    captions = [line for line in contents.splitlines() if line.startswith("Dialogue:")]
    assert captions
    for line in captions:
        assert f"{{\\an2\\pos(300,{180 - outline - 1})\\clip(100,100,500,180)}}" in line
        text = line.split("}", 1)[1]
        assert all(font.getlength(part) <= 400 - 2 * (outline + 1) for part in text.split(r"\N"))


@pytest.mark.parametrize("placement,error", [
    (SubtitleConfig(relative_y=1), "outside"),
    (SubtitleConfig(area=SubtitleArea(0, 0, 1281, 100)), "inside"),
    (SubtitleConfig(area=SubtitleArea(0, 0, 100, 721)), "inside"),
    (SubtitleConfig(area=SubtitleArea(0, 0, 1, 1)), "too small"),
])
def test_subtitle_placement_must_fit_output(tmp_path, placement, error):
    with pytest.raises(VidPPError, match=error):
        write_ass(tmp_path / "captions.ass", [], Template(subtitle_font="DejaVu Sans"), placement=placement)


@pytest.mark.parametrize("scope", ["global", "project"])
def test_rendered_subtitle_pixels_follow_settings(tmp_path, monkeypatch, scope):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg unavailable")
    global_path = tmp_path / "global.yaml"
    global_path.write_text("version: 1\n")
    monkeypatch.setenv("VIDPP_CONFIG", str(global_path))
    source = tmp_path / "source.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:size=320x240:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx264", "-c:a", "aac", str(source),
    ], check=True)
    original_source = source.read_bytes()
    project = tmp_path / "project"
    create_project(source, project)
    (project / "transcript.json").write_text(json.dumps({"segments": [{
        "start": 0, "end": 1, "text": "Wide subtitle text",
        "words": [{"word": word, "start": i * .3, "end": (i + 1) * .3}
                  for i, word in enumerate(["Wide", "subtitle", "text"])],
    }]}))
    template = Template(width=320, height=240, video_width=320, video_height=240,
                        subtitle_font="DejaVu Sans", subtitle_font_size=28,
                        subtitle_bottom_margin=30)

    def rendered_bounds():
        target = render(project, template, preview=True)
        result = subprocess.run([
            "ffmpeg", "-v", "error", "-ss", "0.2", "-i", str(target),
            "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-",
        ], check=True, capture_output=True)
        with Image.open(io.BytesIO(result.stdout)) as image:
            bounds = image.convert("L").point(lambda value: 255 if value > 100 else 0).getbbox()
        assert bounds is not None
        return bounds

    baseline = rendered_bounds()
    settings_path = global_path if scope == "global" else project / "config.yaml"
    settings = {} if scope == "global" else read_project_config(project)
    settings["subtitles"] = {"relative_y": -.2}
    if scope == "global":
        settings_path.write_text("subtitles:\n  relative_y: -0.2\n")
    else:
        write_project_config(project, settings)
    moved = rendered_bounds()
    assert moved[0] == baseline[0] and moved[2] == baseline[2]
    assert moved[1] == pytest.approx(baseline[1] - 48, abs=1)
    assert moved[3] == pytest.approx(baseline[3] - 48, abs=1)
    if scope == "global":
        settings_path.write_text("subtitles:\n  area: {top: 40, left: 30, right: 190, bottom: 100}\n")
    else:
        settings["subtitles"] = {"area": {"top": 40, "left": 30, "right": 190, "bottom": 100}}
        write_project_config(project, settings)
    absolute = rendered_bounds()
    assert 30 <= absolute[0] < absolute[2] <= 190
    assert 40 <= absolute[1] < absolute[3] <= 100
    assert (absolute[0] + absolute[2]) / 2 == pytest.approx(110, abs=3)
    assert source.read_bytes() == original_source
