import json
from pathlib import Path
import shutil
import subprocess

import pytest

from vidpp import cli
from vidpp.cli import _list_projects, _output_file, _prepare_project_destination, _resolve_project, parser
from vidpp.config import AppConfig
from vidpp.core import _validate_matching_sources, create_project, project_data, project_hook, save_project_hook
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


def test_project_and_output_paths_use_app_config(tmp_path):
    projects = tmp_path / "projects"
    config = AppConfig(projects, tmp_path / "exports")
    assert _resolve_project(Path("demo.vidpp"), projects, existing=False) == (projects / "demo.vidpp").resolve()
    absolute = tmp_path / "elsewhere/demo.vidpp"
    assert _resolve_project(absolute, projects, existing=False) == absolute.resolve()
    assert _output_file(projects / "demo.vidpp", None, config) == tmp_path / "exports/demo.mp4"
    assert _output_file(projects / "demo.vidpp", tmp_path / "archive/post.mp4", config) == (tmp_path / "archive/post.mp4").resolve()


def test_list_projects_returns_only_valid_sorted_projects(tmp_path):
    projects = tmp_path / "projects"
    for name in ("Zulu.vidpp", "alpha.vidpp"):
        item = projects / name
        item.mkdir(parents=True)
        (item / "project.json").write_text("{}")
    (projects / "not-a-project").mkdir()
    assert [item.name for item in _list_projects(projects)] == ["alpha.vidpp", "Zulu.vidpp"]


def test_list_command_uses_configured_projects_dir(tmp_path, monkeypatch, capsys):
    projects = tmp_path / "projects"
    project = projects / "demo.vidpp"
    project.mkdir(parents=True)
    (project / "project.json").write_text("{}")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"version: 1\nprojects_dir: {projects}\n")
    monkeypatch.setenv("VIDPP_CONFIG", str(config_path))
    assert cli.main(["list"]) == 0
    assert capsys.readouterr().out == "demo.vidpp\n"


def test_cli_project_name_adds_suffix_and_accepts_replace():
    args = parser().parse_args(["process", "source.mp4", "--project-name", "demo", "--replace-project", "--no-edit"])
    assert args.project_name == Path("demo.vidpp")
    assert args.project is None
    assert args.replace_project is True
    assert args.no_edit is True
    imported = parser().parse_args(["import", "source.mp4", "demo.vidpp", "--replace-project"])
    assert imported.project == Path("demo.vidpp")
    assert imported.replace_project is True


def test_cli_rejects_project_name_paths():
    with pytest.raises(SystemExit):
        parser().parse_args(["process", "source.mp4", "--project-name", "nested/demo"])


def test_render_cli_accepts_no_edit():
    args = parser().parse_args(["render", "demo.vidpp", "--no-edit", "--open", "--output-file", "/archive/post.mp4"])
    assert args.no_edit is True
    assert args.open is True
    assert args.output_file == Path("/archive/post.mp4")
    process = parser().parse_args(["process", "source.mp4", "--open", "--output-file", "/archive/post.mp4"])
    assert process.open is True
    assert process.output_file == Path("/archive/post.mp4")


def test_open_video_uses_default_desktop_launcher(tmp_path, monkeypatch):
    video = tmp_path / "final.mp4"
    video.touch()
    launched = []
    monkeypatch.setattr(cli.sys, "platform", "linux")
    monkeypatch.setattr(cli.subprocess, "Popen", lambda command, **options: launched.append((command, options)))

    cli.open_video(video)

    command, options = launched[0]
    assert command == ["xdg-open", str(video.resolve())]
    assert options["start_new_session"] is True
    assert options["stdin"] is cli.subprocess.DEVNULL


def test_project_hook_roundtrip(tmp_path):
    source = tmp_path / "source.mp4"
    source.touch()
    project = tmp_path / "demo.vidpp"
    project.mkdir()
    (project / "project.json").write_text(json.dumps({"version": 1, "source_path": str(source), "source": {}}))

    assert project_hook(project) is None
    save_project_hook(project, "Saved hook")
    assert project_hook(project) == "Saved hook"
    assert json.loads((project / "project.json").read_text())["hook"] == "Saved hook"


def test_project_rejects_non_string_hook(tmp_path):
    source = tmp_path / "source.mp4"
    source.touch()
    project = tmp_path / "demo.vidpp"
    project.mkdir()
    (project / "project.json").write_text(json.dumps({
        "version": 1,
        "source_path": str(source),
        "source": {},
        "hook": ["not", "text"],
    }))
    with pytest.raises(VidPPError, match="hook must be a string"):
        project_data(project)


def test_render_uses_and_updates_saved_project_hook(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.touch()
    project = tmp_path / "demo.vidpp"
    project.mkdir()
    (project / "project.json").write_text(json.dumps({
        "version": 1,
        "source_path": str(source),
        "source": {"width": 1080, "height": 1920},
        "hook": "Saved hook",
    }))
    rendered = []
    render_options = []
    opened = []
    monkeypatch.setattr(cli, "refresh_source_metadata", lambda unused: {"width": 1080, "height": 1920})
    def fake_render(unused_project, template, **options):
        rendered.append(template)
        render_options.append(options)
        return options.get("output_file") or project / "output/final.mp4"
    monkeypatch.setattr(cli, "render", fake_render)
    monkeypatch.setattr(cli, "open_video", opened.append)

    archive = tmp_path / "archive/post.mp4"
    assert cli.main(["render", str(project), "--open", "--output-file", str(archive)]) == 0
    assert rendered[-1].hook_text == "Saved hook"
    assert render_options[-1]["output_file"] == archive.resolve()
    assert opened == [archive.resolve()]

    assert cli.main(["render", str(project), "--hook", "Replacement hook"]) == 0
    assert rendered[-1].hook_text == "Replacement hook"
    assert project_hook(project) == "Replacement hook"

    assert cli.main(["render", str(project), "--hook", ""]) == 0
    assert rendered[-1].hook_text == ""
    assert project_hook(project) == ""


def test_process_saves_hook_in_new_project(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.touch()
    project = tmp_path / "demo.vidpp"
    rendered = []
    opened = []

    def fake_create(unused_sources, destination):
        destination.mkdir()
        for name in ("assets", "cache", "previews", "output"):
            (destination / name).mkdir()
        metadata = {
            "version": 1,
            "source_path": str(source),
            "source": {"width": 1080, "height": 1920, "duration": 1.0},
        }
        (destination / "project.json").write_text(json.dumps(metadata))
        return metadata

    monkeypatch.setattr(cli, "create_project", fake_create)
    monkeypatch.setattr(cli, "transcribe", lambda unused: None)
    monkeypatch.setattr(cli, "analyze", lambda unused_project, unused_template: None)
    monkeypatch.setattr(cli, "plan", lambda unused_project, unused_template: [])
    monkeypatch.setattr(cli, "render", lambda unused_project, template, **unused: rendered.append(template) or project / "output/final.mp4")
    monkeypatch.setattr(cli, "open_video", opened.append)

    assert cli.main(["process", str(source), "--project", str(project), "--hook", "Persistent hook", "--open"]) == 0
    assert rendered[-1].hook_text == "Persistent hook"
    assert project_hook(project) == "Persistent hook"
    assert opened == [project / "output/final.mp4"]

    template = tmp_path / "template.yaml"
    template.write_text("version: 1\nhook: {text: Template hook}\n")
    template_project = tmp_path / "from-template.vidpp"
    assert cli.main(["process", str(source), "--project", str(template_project), "--template", str(template)]) == 0
    assert rendered[-1].hook_text == "Template hook"
    assert project_hook(template_project) == "Template hook"


def test_root_help_lists_command_options():
    help_text = parser().format_help()
    for option in ("--no-edit", "--open", "--output-file", "--project-name", "--replace-project", "--transcript", "--template", "--format"):
        assert option in help_text
    assert "command options:" in help_text
    assert "list projects" in help_text


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
