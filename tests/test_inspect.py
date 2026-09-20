import json
import subprocess

import pytest

from vidpp import core
from vidpp.template import load_template


def _probe_result(rotation=None, *, tag=False):
    video = {"codec_type": "video", "width": 1920, "height": 1080, "avg_frame_rate": "30/1"}
    if rotation is not None:
        if tag:
            video["tags"] = {"rotate": str(rotation)}
        else:
            video["side_data_list"] = [{"side_data_type": "Display Matrix", "rotation": rotation}]
    return subprocess.CompletedProcess([], 0, json.dumps({"streams": [video], "format": {"duration": "17.8"}}), "")


@pytest.mark.parametrize("rotation", [90, -90, 270])
def test_inspect_swaps_display_dimensions_for_quarter_turn(tmp_path, monkeypatch, rotation):
    source = tmp_path / "source.mp4"
    source.touch()
    monkeypatch.setattr(core, "run", lambda command: _probe_result(rotation))
    metadata = core.inspect(source)
    assert (metadata["width"], metadata["height"]) == (1080, 1920)
    assert (metadata["coded_width"], metadata["coded_height"]) == (1920, 1080)
    assert (load_template(None, source_width=metadata["width"], source_height=metadata["height"]).width,
            load_template(None, source_width=metadata["width"], source_height=metadata["height"]).height) == (720, 1280)


def test_inspect_supports_legacy_rotate_tag(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.touch()
    monkeypatch.setattr(core, "run", lambda command: _probe_result(90, tag=True))
    metadata = core.inspect(source)
    assert (metadata["width"], metadata["height"], metadata["rotation"]) == (1080, 1920, 90)


def test_inspect_keeps_unrotated_dimensions(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.touch()
    monkeypatch.setattr(core, "run", lambda command: _probe_result())
    metadata = core.inspect(source)
    assert (metadata["width"], metadata["height"], metadata["rotation"]) == (1920, 1080, 0)
