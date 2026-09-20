from vidpp.models import EditOperation, TranscriptSegment
from vidpp.render import build_filter, remap_transcript, timeline_ranges
from vidpp.template import Template


def test_shorten_pause_generates_short_retained_range(tmp_path):
    ops = [EditOperation("pause", "shorten_pause", 2, 5, target_duration=.4)]
    assert timeline_ranges(ops, 7) == [(0.0, 2), (2, 2.4), (5, 7)]
    graph = build_filter(7, ops, Template(), tmp_path / "captions.ass")
    assert "concat=n=3" in graph
    assert "pad=1280:720" in graph


def test_caption_timestamps_follow_cut_timeline():
    transcript = [TranscriptSegment(0, 1, "before"), TranscriptSegment(3, 4, "after")]
    mapped = remap_transcript(transcript, [(0, 1), (3, 5)])
    assert [(item.start, item.end) for item in mapped] == [(0, 1), (1, 2)]
