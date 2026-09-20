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
                {"start": 1, "end": 1, "reason": "Removing this question would weaken the message."}]})}}]}).encode()
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

    assert core._llm_operations(tmp_path, {"source": {"lots": "of duplicated metadata"}, "silences": [
        {"start": 1.2, "end": 2.5, "duration": 1.3},
    ]}) == []
    user_payload = json.loads(captured["body"]["messages"][1]["content"])
    assert user_payload == {"owned_blocks": [1, 2], "blocks": [
        [1, "Hello there.", 2.0], [2, "Again."],
    ]}
    assert captured["timeout"] == 345
    assert (tmp_path / "cache/editorial-request.json").is_file()
    assert (tmp_path / "cache/editorial-response.json").is_file()


def test_editorial_request_includes_word_timestamp_pauses(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.touch()
    (tmp_path / "project.json").write_text(json.dumps({"version": 1, "source_path": str(source), "source": {"duration": 9}}))
    (tmp_path / "transcript.json").write_text(json.dumps({"segments": [
        {"start": 0, "end": 1, "text": "So I...", "words": [
            {"word": "So", "start": 0, "end": .2}, {"word": "I...", "start": .4, "end": 1}]},
        {"start": 3, "end": 4, "text": "So...", "words": [
            {"word": "So...", "start": 3, "end": 4}]},
        {"start": 7, "end": 9, "text": "So I finished.", "words": [
            {"word": "So", "start": 7, "end": 7.2}, {"word": "I", "start": 7.3, "end": 7.5},
            {"word": "finished.", "start": 7.6, "end": 9}]},
    ]}))
    monkeypatch.setenv("VIDPP_LLM_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("VIDPP_LLM_MODEL", "test")
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"choices":[{"message":{"content":"{\\"operations\\":[]}"}}]}'

    def open_request(request, **kwargs):
        captured["body"] = json.loads(request.data)
        return Response()

    monkeypatch.setattr(core.urllib.request, "urlopen", open_request)
    core._llm_operations(tmp_path, {})

    payload = json.loads(captured["body"]["messages"][1]["content"])
    assert payload == {"owned_blocks": [1, 3], "blocks": [
        [1, "So I...", 2.0], [2, "So...", 3.0], [3, "So I finished."],
    ]}
    system_prompt = captured["body"]["messages"][0]["content"]
    assert "local window, not the whole video" in system_prompt
    assert "gap_after_seconds" in system_prompt
    assert captured["body"]["max_tokens"] == 8192
    assert "chat_template_kwargs" not in captured["body"]
    assert captured["body"]["reasoning_effort"] == "low"
    schema = captured["body"]["response_format"]
    assert schema["type"] == "json_object"
    operation_schema = schema["schema"]["properties"]["operations"]["items"]
    assert operation_schema["additionalProperties"] is False
    assert set(operation_schema["properties"]) == {"start", "end", "reason"}


def test_editorial_output_limit_has_specific_error(tmp_path, monkeypatch):
    import pytest
    from vidpp.errors import VidPPError

    source = tmp_path / "source.mp4"
    source.touch()
    (tmp_path / "project.json").write_text(json.dumps({"version": 1, "source_path": str(source), "source": {"duration": 2}}))
    (tmp_path / "transcript.json").write_text(json.dumps({"segments": [
        {"start": 0, "end": 2, "text": "So I...", "words": [
            {"word": "So", "start": 0, "end": .2}, {"word": "I...", "start": .4, "end": 2}]},
    ]}))
    monkeypatch.setenv("VIDPP_LLM_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("VIDPP_LLM_MODEL", "test")

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            return json.dumps({"choices": [{"finish_reason": "length", "message": {"content": "{\"operations\":["}}]}).encode()

    monkeypatch.setattr(core.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(VidPPError, match="output-token limit"):
        core._llm_operations(tmp_path, {})


def test_llm_max_tokens_validation(monkeypatch):
    import pytest
    from vidpp.errors import VidPPError

    monkeypatch.setenv("VIDPP_LLM_MAX_TOKENS", "8192")
    assert core._llm_max_tokens() == 8192
    monkeypatch.setenv("VIDPP_LLM_MAX_TOKENS", "lots")
    with pytest.raises(VidPPError, match="must be an integer"):
        core._llm_max_tokens()


def test_editorial_cut_must_use_known_block_ids(tmp_path, monkeypatch):
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
            content = json.dumps({"operations": [{"start": 999, "end": 1, "reason": "invented boundary"}]})
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode()
    monkeypatch.setattr(core.urllib.request, "urlopen", lambda *args, **kwargs: Response())

    import pytest
    from vidpp.errors import VidPPError
    with pytest.raises(VidPPError, match="supplied speech blocks"):
        core._llm_operations(tmp_path, {})


def test_editorial_silence_overlapping_speech_is_not_sent(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.touch()
    (tmp_path / "project.json").write_text(json.dumps({"version": 1, "source_path": str(source), "source": {"duration": 2}}))
    (tmp_path / "transcript.json").write_text(json.dumps({"segments": [{"start": 0, "end": 2, "text": "Quiet speech.", "words": [
        {"word": "Quiet", "start": 0, "end": 1}, {"word": "speech.", "start": 1, "end": 2}]}]}))
    monkeypatch.setenv("VIDPP_LLM_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("VIDPP_LLM_MODEL", "test")
    captured = {}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"choices":[{"message":{"content":"{\\"operations\\":[]}"}}]}'
    def open_request(request, **kwargs):
        captured["body"] = json.loads(request.data)
        return Response()
    monkeypatch.setattr(core.urllib.request, "urlopen", open_request)

    core._llm_operations(tmp_path, {"silences": [{"start": .5, "end": 1.5, "duration": 1}]})
    payload = json.loads(captured["body"]["messages"][1]["content"])
    assert payload == {"owned_blocks": [1, 1], "blocks": [[1, "Quiet speech."]]}


def test_editorial_windows_have_exclusive_owners_and_overlapping_context():
    assert core._editorial_windows(51) == [
        {"stage": "opening", "window_start": 1, "window_end": 12, "owner_start": 1, "owner_end": 8},
        {"stage": "middle-001", "window_start": 5, "window_end": 24, "owner_start": 9, "owner_end": 20},
        {"stage": "middle-002", "window_start": 17, "window_end": 36, "owner_start": 21, "owner_end": 32},
        {"stage": "middle-003", "window_start": 29, "window_end": 47, "owner_start": 33, "owner_end": 43},
        {"stage": "ending", "window_start": 40, "window_end": 51, "owner_start": 44, "owner_end": 51},
    ]


def test_editorial_context_proposals_are_ignored_and_each_window_is_cached(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.touch()
    (tmp_path / "project.json").write_text(json.dumps({
        "version": 1, "source_path": str(source), "source": {"duration": 40},
    }))
    segments = [{
        "start": index * 2, "end": index * 2 + 1, "text": f"Block {index + 1}.",
        "words": [{"word": f"Block-{index + 1}.", "start": index * 2, "end": index * 2 + 1}],
    } for index in range(20)]
    (tmp_path / "transcript.json").write_text(json.dumps({"segments": segments}))
    monkeypatch.setenv("VIDPP_LLM_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("VIDPP_LLM_MODEL", "test")

    class Response:
        def __init__(self, content): self.content = content
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps({"choices": [{"message": {"content": self.content}}]}).encode()

    def open_request(request, **kwargs):
        body = json.loads(request.data)
        payload = json.loads(body["messages"][1]["content"])
        first_context_id = payload["blocks"][0][0]
        content = json.dumps({"operations": [{
            "start": first_context_id, "end": first_context_id, "reason": "test candidate",
        }]})
        return Response(content)

    monkeypatch.setattr(core.urllib.request, "urlopen", open_request)
    operations = core._llm_operations(tmp_path, {})

    assert [(item.source_start, item.source_end) for item in operations] == [(0, 1)]
    assert len(list((tmp_path / "cache").glob("editorial-request-[0-9][0-9][0-9].json"))) == 3
    assert len(list((tmp_path / "cache").glob("editorial-response-[0-9][0-9][0-9].json"))) == 3


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
