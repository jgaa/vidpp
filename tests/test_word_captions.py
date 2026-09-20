import json
import shutil
import subprocess

import pytest

from vidpp.captions import caption_chunks, caption_font, remap_transcript
from vidpp.errors import VidPPError
from vidpp.models import TranscriptSegment, TranscriptWord, load_transcript
from vidpp.render import render
from vidpp.core import create_project, save_transcript
from vidpp.template import Template


def segment():
    return TranscriptSegment(0, 7, "Many words make", (
        TranscriptWord(0, .3, "Many"), TranscriptWord(.3, 1, "words"), TranscriptWord(6.8, 7, "make")))


def test_caption_uses_actual_word_times_and_preserves_pause():
    captions = caption_chunks([segment()])
    assert [(c.start, c.end, c.text) for c in captions] == [(0, 1, "Many words"), (6.8, 7, "make")]


def test_caption_prefers_commas_and_sentence_boundaries():
    texts = ["First", "natural,", "then", "the", "next", "sentence.", "Finally"]
    words = tuple(TranscriptWord(i * .3, (i + 1) * .3, text) for i, text in enumerate(texts))
    captions = caption_chunks([TranscriptSegment(0, 2.1, " ".join(texts), words)], max_words=12)
    assert [caption.text for caption in captions] == ["First natural,", "then the next sentence.", "Finally"]


def test_caption_limits_words_and_leaves_long_pause_blank():
    words = tuple(TranscriptWord(i * .2, (i + 1) * .2, f"w{i}") for i in range(8)) + (
        TranscriptWord(4.0, 4.1, "after"),
    )
    captions = caption_chunks([TranscriptSegment(0, 5, "words", words)], max_words=4, linger=1.0)
    assert all(len(caption.words) <= 4 for caption in captions)
    assert captions[-2].end <= 2.6
    assert captions[-1].start == 4.0


def test_cut_removes_only_its_words():
    result = remap_transcript([segment()], [(0, .3), (6.8, 7)])
    assert [c.text for c in result] == ["Many", "make"]
    assert result[-1].start == pytest.approx(.3)
    assert result[-1].end == pytest.approx(.5)


def test_cut_through_word_requires_review():
    with pytest.raises(VidPPError, match="through spoken word"):
        remap_transcript([segment()], [(0, .5)])


def test_font_measured_wrapping():
    font = caption_font("DejaVu Sans", 22)
    words = tuple(TranscriptWord(i * .1, (i + 1) * .1, "wideword") for i in range(20))
    captions = caption_chunks([TranscriptSegment(0, 2, " ".join(w.word for w in words), words)], font=font, width=200)
    assert sum(len(c.words) for c in captions) == 20
    for caption in captions:
        assert len(caption.text.splitlines()) <= 2
        assert all(font.getlength(line) <= 200 for line in caption.text.splitlines())


def test_word_metadata_roundtrip(tmp_path):
    from dataclasses import asdict
    source = tmp_path / "original.json"
    source.write_text(json.dumps({"segments": [asdict(segment())]}))
    save_transcript(tmp_path, source)
    assert load_transcript(tmp_path / "transcript.json") == [segment()]


@pytest.mark.parametrize("start,end,probability", [(2, 3, .9), (0, float("nan"), .9), (0, 1, 2), (1, 0, .9)])
def test_invalid_word_timestamps_are_rejected(start, end, probability):
    with pytest.raises(VidPPError):
        TranscriptSegment.from_dict({"start": 0, "end": 1, "text": "test", "words": [
            {"word": "test", "start": start, "end": end, "probability": probability}]})


def test_ffmpeg_word_cut_render(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg unavailable")
    source = tmp_path / "source.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25", "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx264", "-c:a", "aac", str(source)], check=True)
    project = tmp_path / "project"
    create_project(source, project)
    (project / "transcript.json").write_text(json.dumps({"segments": [{"start": 0, "end": 2, "text": "Keep remove kept", "words": [
        {"word": "Keep", "start": 0, "end": .5}, {"word": "remove", "start": .5, "end": 1}, {"word": "kept", "start": 1, "end": 2}]}]}))
    (project / "edit.json").write_text(json.dumps({"version": 1, "operations": [{"id": "test", "type": "remove", "source_start": .5, "source_end": 1, "enabled": True}]}))
    target = render(project, Template(width=320, height=480, video_width=320, video_height=480, subtitle_font="DejaVu Sans", subtitle_font_size=22, subtitle_bottom_margin=30), preview=True)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(target)], capture_output=True, text=True, check=True)
    assert float(json.loads(probe.stdout)["format"]["duration"]) == pytest.approx(1.5, abs=.15)
    assert "remove" not in (project / "cache/captions.ass").read_text()
