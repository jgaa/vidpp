import json

import pytest

from vidpp import core
from vidpp.errors import VidPPError


def _project(tmp_path):
    source = tmp_path / "source.mp4"
    source.touch()
    (tmp_path / "cache").mkdir()
    (tmp_path / "project.json").write_text(json.dumps({"version": 1, "source_path": str(source), "source": {"duration": 1}}))
    return source


def test_missing_whisper_explains_local_install(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.delenv("VIDPP_TRANSCRIBE_COMMAND", raising=False)
    monkeypatch.setattr(core.shutil, "which", lambda _: None)
    with pytest.raises(VidPPError, match="openai-whisper"):
        core.transcribe(tmp_path)


def test_whisper_fallback_saves_its_json(tmp_path, monkeypatch):
    source = _project(tmp_path)
    monkeypatch.delenv("VIDPP_TRANSCRIBE_COMMAND", raising=False)
    monkeypatch.setattr(core.shutil, "which", lambda _: "/venv/bin/whisper")
    calls = []
    def fake_run(command, *, capture=True):
        calls.append(command)
        (tmp_path / "cache" / "source.json").write_text('{"segments":[{"start":0,"end":1,"text":"hello"}]}')
    monkeypatch.setattr(core, "run", fake_run)
    core.transcribe(tmp_path)
    assert calls[0][:3] == ["whisper", str(source), "--model"]
    assert (tmp_path / "transcript.json").is_file()
