from PIL import Image
import pytest

from vidpp.errors import VidPPError
from vidpp.models import EditOperation, TranscriptSegment
from vidpp.render import build_filter, log_edit_summary, remap_transcript, render_hook_bubble, render_target, timeline_ranges, write_ass
from vidpp.template import Template


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
