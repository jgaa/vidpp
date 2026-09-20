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
