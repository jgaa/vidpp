import json

import pytest
import yaml

from vidpp import cli, core
from vidpp.config import apply_project_config, read_project_config, subtitle_config, transcription_config, write_project_config
from vidpp.errors import VidPPError


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDPP_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "missing-global"))


def legacy_project(project, **overrides):
    source = project / "source.mp4"
    source.touch()
    values = {"version": 1, "source_path": str(source), "source": {"duration": 1}, **overrides}
    (project / "project.json").write_text(json.dumps(values))
    return values


def test_project_access_migrates_exact_values_without_defaults(tmp_path, isolated_config):
    stored = legacy_project(tmp_path, hook="", subtitles={"relative_y": -.1})
    assert core.project_data(tmp_path) == stored
    assert yaml.safe_load((tmp_path / "config.yaml").read_text()) == stored
    assert json.loads((tmp_path / "project.json.bak").read_text()) == stored
    assert not (tmp_path / "project.json").exists()
    assert "transcription" not in stored
    before = (tmp_path / "config.yaml").read_bytes()
    transcription_config(tmp_path)
    assert subtitle_config(tmp_path).relative_y == -.1
    core.project_data(tmp_path)
    assert (tmp_path / "config.yaml").read_bytes() == before
    assert len(list(tmp_path.glob("project.json.bak*"))) == 1


def test_migration_merges_explicit_overrides_preserving_other_values(tmp_path, isolated_config):
    stored = legacy_project(tmp_path, hook="Original", transcription={"model": "small", "language": "en"},
                            subtitles={"relative_y": -.1})
    overrides = {"hook": "Replacement", "transcription": {"language": "bg"},
                 "subtitles": {"area": {"top": 10, "left": 0, "right": 100, "bottom": 200}}}
    write_project_config(tmp_path, overrides)
    expected = {**stored, **overrides, "transcription": {"model": "small", "language": "bg"}}
    assert core.project_data(tmp_path) == expected
    assert subtitle_config(tmp_path).area.top == 10
    core.save_project_hook(tmp_path, "Updated")
    expected["hook"] = "Updated"
    assert read_project_config(tmp_path) == expected


def test_transcription_access_migrates_before_loading_settings(tmp_path, isolated_config):
    stored = legacy_project(tmp_path, transcription={"model": "small"})
    assert transcription_config(tmp_path).model == "small"
    assert read_project_config(tmp_path) == stored
    assert not (tmp_path / "project.json").exists()


def test_invalid_stored_subtitles_are_preserved_and_reported(tmp_path, isolated_config):
    stored = legacy_project(tmp_path, subtitles={"relative_y": -100.0})
    assert read_project_config(tmp_path) == stored
    with pytest.raises(VidPPError, match="relative_y"):
        subtitle_config(tmp_path)
    assert read_project_config(tmp_path) == stored


@pytest.mark.parametrize("contents", ["{", "[]", '{"version": 2}'])
def test_bad_json_does_not_create_yaml_or_archive(tmp_path, contents):
    legacy = tmp_path / "project.json"
    legacy.write_text(contents)
    with pytest.raises(VidPPError):
        read_project_config(tmp_path)
    assert legacy.read_text() == contents
    assert not (tmp_path / "config.yaml").exists()
    assert not (tmp_path / "project.json.bak").exists()


def test_bad_yaml_does_not_change_legacy(tmp_path):
    stored = legacy_project(tmp_path)
    (tmp_path / "config.yaml").write_text("[invalid")
    with pytest.raises(VidPPError):
        read_project_config(tmp_path)
    assert json.loads((tmp_path / "project.json").read_text()) == stored
    assert (tmp_path / "config.yaml").read_text() == "[invalid"


def test_write_failure_preserves_original_files(tmp_path, monkeypatch):
    stored = legacy_project(tmp_path)
    existing = "transcription: {language: bg}\n"
    (tmp_path / "config.yaml").write_text(existing)

    def fail_replace(path, target):
        raise OSError("simulated write failure")

    monkeypatch.setattr(type(tmp_path), "replace", fail_replace)
    with pytest.raises(VidPPError, match="cannot write"):
        read_project_config(tmp_path)
    assert json.loads((tmp_path / "project.json").read_text()) == stored
    assert (tmp_path / "config.yaml").read_text() == existing
    assert not list(tmp_path.glob(".config-*"))


def test_previous_backup_is_preserved(tmp_path):
    stored = legacy_project(tmp_path)
    (tmp_path / "project.json.bak").write_text("old backup")
    assert read_project_config(tmp_path) == stored
    assert (tmp_path / "project.json.bak").read_text() == "old backup"
    assert json.loads((tmp_path / "project.json.bak.1").read_text()) == stored


def test_supplied_settings_merge_without_losing_source_or_dumping_defaults(tmp_path):
    source = tmp_path / "source.mp4"
    source.touch()
    values = {"version": 1, "source_path": str(source), "source": {"duration": 1}, "hook": "Existing"}
    write_project_config(tmp_path, values)
    overrides = tmp_path / "overrides.yaml"
    overrides.write_text("transcription: {model: small}\nsubtitles: {relative_y: -0.1}\n")
    apply_project_config(tmp_path, overrides)
    expected = {**values, "transcription": {"model": "small"}, "subtitles": {"relative_y": -.1}}
    assert core.project_data(tmp_path) == expected
    assert not (tmp_path / "project.json").exists()


def test_import_creates_only_yaml_with_required_data_and_explicit_settings(tmp_path, monkeypatch, isolated_config):
    source = tmp_path / "source.mp4"
    source.touch()
    inspected = {"width": 320, "height": 240, "duration": 1, "fps": "25/1"}
    monkeypatch.setattr(core, "inspect", lambda unused: inspected)
    project = tmp_path / "new.vidpp"
    supplied = tmp_path / "overrides.yaml"
    supplied.write_text("subtitles: {relative_y: -0.1}\ntranscription: {model: small}\n")
    assert cli.main(["import", str(source), str(project), "--project-config", str(supplied)]) == 0
    expected = {"version", "source_path", "source", "sources", "subtitles", "transcription"}
    values = core.project_data(project)
    assert set(values) == expected
    assert values["transcription"] == {"model": "small"}
    assert values["subtitles"] == {"relative_y": -.1}
    assert not (project / "project.json").exists()
    assert not list(project.glob("project.json.bak*"))


def test_list_recognizes_yaml_and_migrates_json_without_media_access(tmp_path):
    for name in ("legacy", "modern"):
        project = tmp_path / name
        project.mkdir()
        values = {"version": 1, "source_path": "/unavailable/source.mp4"}
        if name == "legacy":
            (project / "project.json").write_text(json.dumps(values))
        else:
            write_project_config(project, values)
    settings_only = tmp_path / "settings-only"
    settings_only.mkdir()
    write_project_config(settings_only, {"subtitles": {}})
    assert [project.name for project in cli._list_projects(tmp_path)] == ["legacy", "modern"]
    assert not (tmp_path / "legacy/project.json").exists()


def test_settings_yaml_alone_does_not_authorize_replacing_a_directory(tmp_path):
    directory = tmp_path / "settings"
    directory.mkdir()
    write_project_config(directory, {"transcription": {"model": "small"}})
    with pytest.raises(VidPPError, match="not recognizably"):
        cli._prepare_project_destination(directory, [tmp_path / "source.mp4"], True)
    assert directory.is_dir()
