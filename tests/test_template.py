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
    path.write_text("version: 1\nsubtitles: {max_words: 8, linger: 0.5, pause_threshold: 0.3, max_duration: 2.5}\n")
    value = load_template(path)
    assert (value.subtitle_max_words, value.subtitle_linger, value.subtitle_pause_threshold, value.subtitle_max_duration) == (8, .5, .3, 2.5)
