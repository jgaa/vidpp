import pytest

from vidpp.config import transcription_config
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


def test_english_is_default(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDPP_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "missing"))
    monkeypatch.delenv("VIDPP_WHISPER_LANGUAGE", raising=False)
    assert transcription_config(tmp_path).language == "en"


@pytest.mark.parametrize("value", ['"VidPP"', '[42]', '[""]', 'null'])
def test_rejects_bad_phrases(tmp_path, monkeypatch, value):
    path = tmp_path / "global.yaml"
    path.write_text(f"transcription:\n  phrases: {value}\n")
    monkeypatch.setenv("VIDPP_CONFIG", str(path))
    with pytest.raises(VidPPError):
        transcription_config(tmp_path)
