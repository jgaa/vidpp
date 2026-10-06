from pathlib import Path

import pytest

from vidpp.config import SubtitleArea, SubtitleConfig, app_config, subtitle_config, transcription_config
from vidpp.errors import VidPPError


def test_merges_deduplicates_and_overrides(tmp_path, monkeypatch):
    global_config = tmp_path / "global.yaml"
    global_config.write_text('transcription:\n  model: small\n  phrases: [VidPP, "end to end"]\n')
    project = tmp_path / "project"
    project.mkdir()
    (project / "config.yaml").write_text('transcription:\n  model: turbo\n  phrases: [vidpp, "end   to end", OneRSS]\n')
    monkeypatch.setenv("VIDPP_CONFIG", str(global_config))
    monkeypatch.delenv("VIDPP_WHISPER_MODEL", raising=False)
    config = transcription_config(project)
    assert config.engine == "whisper"
    assert config.model == "turbo"
    assert config.recovery_model == "turbo"
    assert config.phrases == ("VidPP", "end to end", "OneRSS")
    monkeypatch.setenv("VIDPP_WHISPER_MODEL", "large-v3")
    assert transcription_config(project).model == "large-v3"


def test_recovery_model_can_be_configured(tmp_path, monkeypatch):
    path = tmp_path / "global.yaml"
    path.write_text('transcription:\n  model: turbo\n  recovery_model: large-v3\n')
    monkeypatch.setenv("VIDPP_CONFIG", str(path))
    monkeypatch.delenv("VIDPP_WHISPER_MODEL", raising=False)
    monkeypatch.delenv("VIDPP_WHISPER_RECOVERY_MODEL", raising=False)
    assert transcription_config(tmp_path).recovery_model == "large-v3"


def test_crisperwhisper_engine_and_backend(tmp_path, monkeypatch):
    path = tmp_path / "global.yaml"
    path.write_text('transcription:\n  engine: crisperwhisper\n  model: medium\n  crisper_backend: transformers\n')
    monkeypatch.setenv("VIDPP_CONFIG", str(path))
    config = transcription_config(tmp_path)
    assert config.engine == "crisperwhisper"
    assert config.model == "medium"
    assert config.crisper_backend == "transformers"


def test_english_is_default(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDPP_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "missing"))
    monkeypatch.delenv("VIDPP_WHISPER_LANGUAGE", raising=False)
    assert transcription_config(tmp_path).language == "en"


def test_app_paths_have_safe_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDPP_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "missing"))
    config = app_config()
    assert config.projects_dir == Path.home() / ".local/vidpp/projects"
    assert config.output_file_dir is None


def test_app_paths_can_be_configured_relative_to_config(tmp_path, monkeypatch):
    config_dir = tmp_path / "settings"
    config_dir.mkdir()
    path = config_dir / "config.yaml"
    path.write_text("version: 1\nprojects_dir: projects\noutput_file_dir: exports\n")
    monkeypatch.setenv("VIDPP_CONFIG", str(path))
    config = app_config()
    assert config.projects_dir == (config_dir / "projects").resolve()
    assert config.output_file_dir == (config_dir / "exports").resolve()


def test_project_config_cannot_redirect_application_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDPP_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "missing"))
    project = tmp_path / "project"
    project.mkdir()
    (project / "config.yaml").write_text("projects_dir: elsewhere\n")
    with pytest.raises(VidPPError, match="invalid configuration keys"):
        transcription_config(project)


@pytest.mark.parametrize("value", ['"VidPP"', '[42]', '[""]', 'null'])
def test_rejects_bad_phrases(tmp_path, monkeypatch, value):
    path = tmp_path / "global.yaml"
    path.write_text(f"transcription:\n  phrases: {value}\n")
    monkeypatch.setenv("VIDPP_CONFIG", str(path))
    with pytest.raises(VidPPError):
        transcription_config(tmp_path)


def test_subtitle_settings_inherit_replace_and_reset(tmp_path, monkeypatch):
    path = tmp_path / "global.yaml"
    path.write_text("subtitles:\n  relative_y: -0.1\n")
    monkeypatch.setenv("VIDPP_CONFIG", str(path))
    project = tmp_path / "project"
    project.mkdir()
    assert subtitle_config(project) == SubtitleConfig(relative_y=-0.1)
    app_config()
    transcription_config(project)
    local = project / "config.yaml"
    local.write_text("subtitles:\n  area: {top: 100, left: 20, right: 500, bottom: 300}\n")
    assert subtitle_config(project) == SubtitleConfig(area=SubtitleArea(100, 20, 500, 300))
    transcription_config(project)
    path.write_text("subtitles:\n  area: {top: 100, left: 20, right: 500, bottom: 300}\n")
    local.write_text("subtitles:\n  relative_y: 0\n")
    assert subtitle_config(project) == SubtitleConfig(relative_y=0)
    local.write_text("subtitles: {}\n")
    assert subtitle_config(project) == SubtitleConfig()
    path.write_text("version: 1\n")
    local.unlink()
    assert subtitle_config(project) == SubtitleConfig()


@pytest.mark.parametrize("section", [
    "{relative_y: -0.1, area: {top: 0, left: 0, right: 100, bottom: 100}}",
    "{relative_y: true}", "{relative_y: .nan}", "{relative_y: .inf}",
    "{relative_y: 1.1}", "{relative_y: -1.1}", "{relative_y: null}",
    "{area: {top: 0, left: 0, right: 100}}",
    "{area: {top: 0, left: 10, right: 10, bottom: 100}}",
    "{area: {top: 100, left: 0, right: 10, bottom: 99}}",
    "{area: {top: -1, left: 0, right: 10, bottom: 100}}",
    "{area: {top: true, left: 0, right: 10, bottom: 100}}",
    "{area: {top: 0.5, left: 0, right: 10, bottom: 100}}",
    "{area: {top: 0, left: 0, right: 10, bottom: 100, extra: 1}}",
    "{y: 0.5}", "null",
])
@pytest.mark.parametrize("scope", ["global", "project"])
def test_invalid_subtitle_settings(tmp_path, monkeypatch, section, scope):
    global_path = tmp_path / "global.yaml"
    global_path.write_text("version: 1\n")
    monkeypatch.setenv("VIDPP_CONFIG", str(global_path))
    project = tmp_path / "project"
    project.mkdir()
    path = global_path if scope == "global" else project / "config.yaml"
    path.write_text(f"subtitles: {section}\n")
    with pytest.raises(VidPPError):
        subtitle_config(project)
    with pytest.raises(VidPPError):
        transcription_config(project)
    if scope == "global":
        with pytest.raises(VidPPError):
            app_config()
