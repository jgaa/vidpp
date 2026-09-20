import pytest

from vidpp.errors import VidPPError
from vidpp.template import load_template


def test_template_rejects_missing_asset(tmp_path):
    path = tmp_path / "template.yaml"
    path.write_text("version: 1\nvideo:\n  background: missing.png\n")
    with pytest.raises(VidPPError, match="does not exist"):
        load_template(path)


def test_template_reads_video_rectangle(tmp_path):
    path = tmp_path / "template.yaml"
    path.write_text("version: 1\noutput: {width: 720, height: 1280}\nvideo: {x: 20, y: 10, width: 680, height: 700, fit: cover}\n")
    value = load_template(path)
    assert (value.width, value.video_x, value.video_fit) == (720, 20, "cover")


def test_template_reads_caption_flow_controls(tmp_path):
    path = tmp_path / "template.yaml"
    path.write_text("version: 1\nsubtitles: {max_words: 7, max_characters: 40, linger: 0.5, pause_threshold: 0.3, max_duration: 2.5}\n")
    value = load_template(path)
    assert (value.subtitle_max_words, value.subtitle_max_characters, value.subtitle_linger, value.subtitle_pause_threshold, value.subtitle_max_duration) == (7, 40, .5, .3, 2.5)


def test_default_captions_are_short_and_large():
    value = load_template(None)
    assert (value.subtitle_font_size, value.subtitle_max_words, value.subtitle_max_characters) == (54, 8, 48)
    assert (value.subtitle_font, value.subtitle_weight, value.subtitle_color) == ("Noto Sans", 600, "#F8F8F8")
    assert (value.subtitle_outline_color, value.subtitle_outline_width, value.subtitle_background) == ("#101010", 3, None)
    assert (value.hook_font, value.hook_weight, value.hook_color, value.hook_background_color) == (
        "Noto Sans", 700, "#FFFFFF", "#D90F0F0F"
    )


def test_visual_defaults_scale_from_1080x1920_reference():
    value = load_template(None, source_width=1080, source_height=1920, output_format="p1080")
    assert (value.width, value.height) == (1080, 1920)
    assert (value.subtitle_font_size, value.subtitle_outline_width, value.subtitle_bottom_margin) == (81, 3, 180)
    assert (value.hook_font_size, value.hook_corner_radius, value.hook_padding_x, value.hook_padding_y) == (108, 24, 32, 18)


def test_template_can_override_text_styles(tmp_path):
    path = tmp_path / "template.yaml"
    path.write_text(
        """version: 1
subtitles:
  font: DejaVu Sans
  font_size: 50
  weight: 500
  color: '#EEEEEE'
  outline_color: '#111111'
  outline_width: 4
  background: '#CC202020'
hook:
  text: Styled hook
  font: DejaVu Sans
  font_size: 90
  weight: 800
  color: '#FAFAFA'
  background_color: '#C0000000'
  corner_radius: 30
  padding_x: 40
  padding_y: 20
"""
    )
    value = load_template(path)
    assert (value.subtitle_font, value.subtitle_font_size, value.subtitle_weight) == ("DejaVu Sans", 50, 500)
    assert (value.subtitle_color, value.subtitle_outline_color, value.subtitle_outline_width) == ("#EEEEEE", "#111111", 4)
    assert value.subtitle_background == "#CC202020"
    assert (value.hook_font, value.hook_font_size, value.hook_weight) == ("DejaVu Sans", 90, 800)
    assert (value.hook_color, value.hook_background_color) == ("#FAFAFA", "#C0000000")
    assert (value.hook_corner_radius, value.hook_padding_x, value.hook_padding_y) == (30, 40, 20)


@pytest.mark.parametrize("weight", [0, 550, 1000, True])
def test_template_rejects_invalid_font_weight(tmp_path, weight):
    path = tmp_path / "template.yaml"
    path.write_text(f"version: 1\nsubtitles: {{weight: {str(weight).lower()}}}\n")
    with pytest.raises(VidPPError, match="subtitles.weight"):
        load_template(path)


@pytest.mark.parametrize(
    ("source", "expected"),
    [((1920, 1080), (1280, 720)), ((1080, 1920), (720, 1280)), ((1000, 1000), (1280, 720))],
)
def test_p720_default_follows_source_orientation(source, expected):
    value = load_template(None, source_width=source[0], source_height=source[1])
    assert (value.width, value.height, value.video_width, value.video_height) == (*expected, *expected)


def test_p_format_and_orientation_can_be_overridden():
    value = load_template(None, source_width=1920, source_height=1080, output_format="p1080", orientation="portrait")
    assert (value.width, value.height) == (1080, 1920)


def test_template_can_select_p_format(tmp_path):
    path = tmp_path / "template.yaml"
    path.write_text("version: 1\noutput: {format: p480, orientation: portrait}\n")
    value = load_template(path, source_width=1920, source_height=1080)
    assert (value.width, value.height) == (480, 854)


@pytest.mark.parametrize("value", ["720p", "p100", "p9000", "pfoo"])
def test_invalid_p_format_is_rejected(value):
    with pytest.raises(VidPPError, match="output format"):
        load_template(None, output_format=value)


def test_explicit_template_dimensions_take_precedence(tmp_path):
    path = tmp_path / "template.yaml"
    path.write_text("version: 1\noutput: {width: 1000, height: 1000}\n")
    value = load_template(path, source_width=1920, source_height=1080)
    assert (value.width, value.height) == (1000, 1000)
