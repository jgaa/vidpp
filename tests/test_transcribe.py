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
    assert calls[0][calls[0].index("--word_timestamps") + 1] == "True"
    assert calls[0][calls[0].index("--language") + 1] == "en"
    assert (tmp_path / "transcript.json").is_file()


def test_deduplicated_phrases_are_passed_as_one_argument(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.delenv("VIDPP_TRANSCRIBE_COMMAND", raising=False)
    path = tmp_path / "global.yaml"
    path.write_text('transcription:\n  phrases: [VidPP, vidpp, "private messages"]\n')
    monkeypatch.setenv("VIDPP_CONFIG", str(path))
    monkeypatch.setattr(core.shutil, "which", lambda _: "/venv/bin/whisper")
    def fake_run(command, **kwargs):
        assert command[command.index("--initial_prompt") + 1] == "VidPP, private messages"
        (tmp_path / "cache/source.json").write_text('{"segments":[]}')
    monkeypatch.setattr(core, "run", fake_run)
    core.transcribe(tmp_path)


def test_failed_whisper_is_actionable(monkeypatch):
    import subprocess
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["whisper"])
    monkeypatch.setattr(core.subprocess, "run", fail)
    with pytest.raises(VidPPError, match="command failed"):
        core.run(["whisper"], capture=False)


def test_recovery_pass_replaces_stretched_opening_words(tmp_path, monkeypatch):
    source = _project(tmp_path)
    (tmp_path / "project.json").write_text(json.dumps({"version": 1, "source_path": str(source), "source": {"duration": 12}}))
    monkeypatch.delenv("VIDPP_TRANSCRIBE_COMMAND", raising=False)
    monkeypatch.setattr(core.shutil, "which", lambda _: "/venv/bin/whisper")
    calls = []
    primary = {"language": "en", "segments": [{"start": 3, "end": 10, "text": "So I begin", "words": [
        {"word": "So", "start": 3, "end": 3.5}, {"word": "I", "start": 3.5, "end": 7},
        {"word": "begin", "start": 7, "end": 10}]}]}
    recovery = {"language": "en", "segments": [{"start": 1, "end": 10, "text": "So I'm So I'm I begin", "words": [
        {"word": "So", "start": 1, "end": 1.3}, {"word": "I'm", "start": 1.3, "end": 1.8},
        {"word": "So", "start": 2.2, "end": 2.5}, {"word": "I'm", "start": 2.5, "end": 3},
        {"word": "I", "start": 6, "end": 6.4}, {"word": "begin", "start": 7, "end": 8}]}]}
    def fake_run(command, **kwargs):
        calls.append(command)
        output_dir = Path(command[command.index("--output_dir") + 1])
        output_dir.mkdir(exist_ok=True)
        output_dir.joinpath("source.json").write_text(json.dumps(recovery if "--clip_timestamps" in command else primary))
    from pathlib import Path
    monkeypatch.setattr(core, "run", fake_run)

    core.transcribe(tmp_path)
    transcript = json.loads((tmp_path / "transcript.json").read_text())
    assert len(calls) == 2
    assert calls[1][calls[1].index("--condition_on_previous_text") + 1] == "False"
    assert "So I'm So I'm" in transcript["text"]
    assert (tmp_path / "cache/transcription-recovery.json").is_file()


def test_optional_crisperwhisper_backend(tmp_path, monkeypatch):
    source = _project(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "transcription:\n  engine: crisperwhisper\n  model: medium\n  crisper_backend: transformers\n"
    )
    monkeypatch.delenv("VIDPP_TRANSCRIBE_COMMAND", raising=False)
    monkeypatch.setattr(core.importlib.util, "find_spec", lambda _: object())
    calls, crisper_calls = [], []
    def fake_run(command, **kwargs):
        calls.append(command)
    def fake_crisper(audio, target, settings, language):
        crisper_calls.append((audio, settings, language))
        target.write_text('{"segments":[{"start":0,"end":1,"text":"um hello","words":[{"word":"um","start":0,"end":0.3},{"word":"hello","start":0.4,"end":1}]}]}')
    monkeypatch.setattr(core, "run", fake_run)
    monkeypatch.setattr(core, "_run_crisper", fake_crisper)

    core.transcribe(tmp_path)
    assert calls[0][0] == "ffmpeg"
    assert len(calls) == 1
    assert crisper_calls[0][1].crisper_backend == "transformers"
    assert crisper_calls[0][1].model == "medium"


def test_missing_crisperwhisper_is_actionable(tmp_path, monkeypatch):
    _project(tmp_path)
    (tmp_path / "config.yaml").write_text("transcription:\n  engine: crisperwhisper\n")
    monkeypatch.delenv("VIDPP_TRANSCRIBE_COMMAND", raising=False)
    monkeypatch.setattr(core.importlib.util, "find_spec", lambda _: None)
    with pytest.raises(VidPPError, match=r"crisperwhisper\[transformers\]"):
        core.transcribe(tmp_path)


def test_crisper_result_becomes_word_timestamp_transcript():
    from types import SimpleNamespace
    from vidpp.models import TranscriptSegment
    result = SimpleNamespace(language="en", words=[
        SimpleNamespace(word="So,", start=0.1, end=0.4),
        SimpleNamespace(word="I'm...", start=0.5, end=1.0),
        SimpleNamespace(word="again.", start=2.0, end=2.5),
    ])
    payload = core._crisper_payload(result)
    segments = [TranscriptSegment.from_dict(item) for item in payload["segments"]]
    assert payload["engine"] == "crisperwhisper"
    assert [segment.text for segment in segments] == ["So, I'm...", "again."]
