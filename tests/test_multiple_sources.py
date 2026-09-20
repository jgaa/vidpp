import json
from pathlib import Path
import shutil
import subprocess

import pytest

from vidpp.cli import parser
from vidpp.core import create_project, project_data
from vidpp.errors import VidPPError


def _video(path: Path, *, size: str = "160x90", frequency: int = 440) -> None:
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=10",
        "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000", "-t", "0.5",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
    ], check=True)


def test_cli_accepts_ordered_sources():
    args = parser().parse_args(["process", "first.mp4", "second.mp4", "--project", "combined.vidpp"])
    assert args.sources == [Path("first.mp4"), Path("second.mp4")]


def test_multiple_sources_create_rebuildable_master(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg unavailable")
    first, second = tmp_path / "first.mp4", tmp_path / "second.mp4"
    _video(first, frequency=440)
    _video(second, frequency=880)
    project = tmp_path / "combined.vidpp"
    metadata = create_project([first, second], project)
    master = project / "cache/master.mp4"
    assert Path(metadata["source_path"]) == master.resolve()
    assert master.is_file()
    assert [item["path"] for item in metadata["sources"]] == [str(first.resolve()), str(second.resolve())]
    assert metadata["sources"][1]["timeline_start"] == pytest.approx(.5, abs=.05)
    assert metadata["source"]["duration"] == pytest.approx(1.0, abs=.15)

    master.unlink()
    project_data(project)
    assert master.is_file()


def test_different_source_dimensions_are_rejected(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg unavailable")
    first, second = tmp_path / "first.mp4", tmp_path / "second.mp4"
    _video(first, size="160x90")
    _video(second, size="320x180")
    with pytest.raises(VidPPError, match="source format differs"):
        create_project([first, second], tmp_path / "project")
