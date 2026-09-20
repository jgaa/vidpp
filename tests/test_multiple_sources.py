import json
from pathlib import Path
import shutil
import subprocess

import pytest

from vidpp.cli import _prepare_project_destination, parser
from vidpp.core import _validate_matching_sources, create_project, project_data
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


def test_cli_project_name_adds_suffix_and_accepts_replace():
    args = parser().parse_args(["process", "source.mp4", "--project-name", "demo", "--replace-project"])
    assert args.project_name == Path("demo.vidpp")
    assert args.project is None
    assert args.replace_project is True
    imported = parser().parse_args(["import", "source.mp4", "demo.vidpp", "--replace-project"])
    assert imported.project == Path("demo.vidpp")
    assert imported.replace_project is True


def test_cli_rejects_project_name_paths():
    with pytest.raises(SystemExit):
        parser().parse_args(["process", "source.mp4", "--project-name", "nested/demo"])


def test_replace_project_removes_only_exact_destination(tmp_path):
    source = tmp_path / "source.mp4"
    source.touch()
    project = tmp_path / "demo.vidpp"
    project.mkdir()
    (project / "old-file").write_text("old")

    _prepare_project_destination(project, [source], True)

    assert not project.exists()
    assert source.is_file()


def test_replace_project_refuses_to_delete_contained_source(tmp_path):
    project = tmp_path / "demo.vidpp"
    project.mkdir()
    source = project / "source.mp4"
    source.touch()

    with pytest.raises(VidPPError, match="contains source media"):
        _prepare_project_destination(project, [source], True)

    assert source.is_file()


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


def test_phone_variable_frame_rate_fractions_are_compatible():
    first = (Path("first.mp4"), {"width": 1080, "height": 1920, "fps": "41970000/1401983"})
    second = (Path("second.mp4"), {"width": 1080, "height": 1920, "fps": "815625/27137"})
    _validate_matching_sources([first, second])


def test_genuinely_different_frame_rates_are_rejected():
    first = (Path("first.mp4"), {"width": 1080, "height": 1920, "fps": "30/1"})
    second = (Path("second.mp4"), {"width": 1080, "height": 1920, "fps": "24/1"})
    with pytest.raises(VidPPError, match="source format differs"):
        _validate_matching_sources([first, second])
