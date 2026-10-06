import pytest

from vidpp import cli


@pytest.fixture(autouse=True)
def help_must_not_access_projects_or_settings(monkeypatch):
    def fail():
        pytest.fail("Help must exit before loading configuration or executing commands")

    monkeypatch.setattr(cli, "app_config", fail)


@pytest.mark.parametrize("arguments", [[], ["help"], ["-h"], ["--help"]])
def test_default_and_explicit_overviews(arguments, capsys):
    with pytest.raises(SystemExit) as result:
        cli.main(arguments)
    assert result.value.code == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert "commands:" in output.out
    assert 'vidpp process input.mp4 --hook "Why privacy matters"' in output.out
    assert "--output-file" not in output.out


@pytest.mark.parametrize("command,options,unrelated", [
    ("list", [], "--template"),
    ("import", ["sources", "project", "--project-config", "--replace-project"], "--transcript"),
    ("transcribe", ["project", "--hook", "--transcript"], "--no-edit"),
    ("analyze", ["project", "--template", "--hook"], "--output-file"),
    ("plan", ["project", "--template", "--hook"], "--open"),
    ("preview", ["project", "--template", "--hook", "--format", "--orientation", "--no-edit"], "--output-file"),
    ("render", ["project", "--template", "--hook", "--format", "--orientation", "--no-edit", "--open", "--output-file"], "--project-config"),
    ("process", ["sources", "--template", "--hook", "--transcript", "--project-config", "--project", "--project-name",
                 "--replace-project", "--no-edit", "--open", "--output-file", "--format", "--orientation"], "lower-quality preview"),
])
def test_command_help_aliases_show_only_relevant_details(command, options, unrelated, capsys):
    outputs = []
    for alias in ("help", "-h", "--help"):
        with pytest.raises(SystemExit) as result:
            cli.main([command, alias])
        assert result.value.code == 0
        output = capsys.readouterr()
        assert output.err == ""
        assert f"usage: vidpp {command}" in output.out
        assert "--verbose" in output.out
        for option in options:
            assert option in output.out
        assert unrelated not in output.out
        outputs.append(output.out)
    assert outputs[0] == outputs[1] == outputs[2]


def test_command_help_with_global_verbose_flag(capsys):
    with pytest.raises(SystemExit) as result:
        cli.main(["-v", "render", "help"])
    assert result.value.code == 0
    assert "--output-file" in capsys.readouterr().out


def test_help_from_process_arguments_when_called_without_argv(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "argv", ["vidpp", "render", "help"])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 0
    assert "usage: vidpp render" in capsys.readouterr().out
