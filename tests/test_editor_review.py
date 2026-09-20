import json

from vidpp import core


def test_contradictory_editorial_cut_requires_explicit_acceptance(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.touch()
    (tmp_path / "project.json").write_text(json.dumps({"version": 1, "source_path": str(source), "source": {"duration": 18}}))
    (tmp_path / "transcript.json").write_text(json.dumps({"segments": [{"start": 14, "end": 16, "text": "A false start.", "words": [
        {"word": "A", "start": 14, "end": 14.2}, {"word": "false", "start": 14.2, "end": 15},
        {"word": "start.", "start": 15, "end": 16}]}]}))
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


def test_editorial_request_is_compact_and_uses_configured_timeout(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.touch()
    (tmp_path / "project.json").write_text(json.dumps({"version": 1, "source_path": str(source), "source": {"duration": 4}}))
    (tmp_path / "transcript.json").write_text(json.dumps({"segments": [{"start": 0, "end": 4, "text": "Hello there. Again.", "words": [
        {"word": "Hello", "start": 0, "end": .5}, {"word": "there.", "start": .5, "end": 1},
        {"word": "Again.", "start": 3, "end": 4}]}]}))
    monkeypatch.setenv("VIDPP_LLM_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("VIDPP_LLM_MODEL", "test")
    monkeypatch.setenv("VIDPP_LLM_TIMEOUT", "345")
    captured = {}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"choices":[{"message":{"content":"{\\"operations\\":[]}"}}]}'
    def open_request(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()
    monkeypatch.setattr(core.urllib.request, "urlopen", open_request)

    assert core._llm_operations(tmp_path, {"source": {"lots": "of duplicated metadata"}, "silences": []}) == []
    user_payload = json.loads(captured["body"]["messages"][1]["content"])
    assert user_payload == {"transcript_blocks": [[0.0, 1.0, "Hello there."], [3.0, 4.0, "Again."]], "silences": []}
    assert captured["timeout"] == 345


def test_editorial_cut_must_use_supplied_block_boundaries(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.touch()
    (tmp_path / "project.json").write_text(json.dumps({"version": 1, "source_path": str(source), "source": {"duration": 2}}))
    (tmp_path / "transcript.json").write_text(json.dumps({"segments": [{"start": 0, "end": 2, "text": "Keep this.", "words": [
        {"word": "Keep", "start": 0, "end": 1}, {"word": "this.", "start": 1, "end": 2}]}]}))
    monkeypatch.setenv("VIDPP_LLM_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("VIDPP_LLM_MODEL", "test")
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            content = json.dumps({"operations": [{"id": "bad", "type": "remove", "source_start": .5, "source_end": 2, "reason": "invented boundary"}]})
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode()
    monkeypatch.setattr(core.urllib.request, "urlopen", lambda *args, **kwargs: Response())

    import pytest
    from vidpp.errors import VidPPError
    with pytest.raises(VidPPError, match="block boundaries"):
        core._llm_operations(tmp_path, {})


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
