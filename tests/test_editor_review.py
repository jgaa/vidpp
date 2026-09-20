import json

from vidpp import core


def test_contradictory_editorial_cut_requires_explicit_acceptance(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.touch()
    (tmp_path / "project.json").write_text(json.dumps({"version": 1, "source_path": str(source), "source": {"duration": 18}}))
    (tmp_path / "transcript.json").write_text('{"segments":[]}')
    monkeypatch.setenv("VIDPP_LLM_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("VIDPP_LLM_MODEL", "test")
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            return json.dumps({"choices": [{"message": {"content": json.dumps({"operations": [
                {"id": "editor-001", "type": "remove", "source_start": 14, "source_end": 16,
                 "enabled": True, "reason": "Removing this question would weaken the message."}]})}}]}).encode()
    monkeypatch.setattr(core.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    operations = core._llm_operations(tmp_path, {})
    assert len(operations) == 1
    assert operations[0].enabled is False


def test_silence_detector_cannot_remove_transcribed_speech(tmp_path, monkeypatch):
    from vidpp.template import Template
    source = tmp_path / "source.mp4"
    source.touch()
    (tmp_path / "project.json").write_text(json.dumps({"version": 1, "source_path": str(source), "source": {"duration": 5}}))
    (tmp_path / "transcript.json").write_text(json.dumps({"segments": [{"start": 0, "end": 4, "text": "quiet speech", "words": [
        {"word": "quiet", "start": 0, "end": 1}, {"word": "speech", "start": 3, "end": 4}]}]}))
    (tmp_path / "analysis.json").write_text(json.dumps({"silences": [{"start": 1, "end": 4, "duration": 3}]}))
    monkeypatch.delenv("VIDPP_LLM_BASE_URL", raising=False)
    assert core.plan(tmp_path, Template()) == []
