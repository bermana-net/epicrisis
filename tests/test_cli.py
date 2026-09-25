from pathlib import Path

import pytest
from typer.testing import CliRunner

from epicrisis import __version__
from epicrisis.cli import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == __version__


def _every_command() -> list[str]:
    """Every command this program registers, asked of the program rather than written by hand.

    Fourteen of the twenty-one were listed here; the seven that were not — the vocabulary
    commands, read-materials, the demo — could have had a broken signature for months without a
    test noticing, which is the whole thing this test exists to catch.
    """
    from epicrisis.cli import app as registered

    return sorted(command.name or command.callback.__name__.replace("_", "-")
                  for command in registered.registered_commands)  # fmt: skip


COMMANDS = _every_command()


@pytest.mark.parametrize("command", COMMANDS)
def test_every_command_can_be_asked_what_it_does(command):
    """A command whose options do not line up with its body dies on its first line.

    That happened: an option was written into the wrong signature, the server read a name that
    did not exist, and the only thing that noticed was a person watching the log.
    """
    result = CliRunner().invoke(app, [command, "--help"])

    assert result.exit_code == 0, result.output
    assert result.exit_code == 0
    # Typer prints the command's own first line of docstring; a command whose help is empty is a
    # command nobody can find out about from the terminal.
    assert "Usage:" in result.output and command in result.output


@pytest.mark.parametrize("command", ("index", "validate", "suspects", "indicators"))
def test_commands_that_read_say_so_on_an_empty_instance(command, tmp_path):
    """Nothing that only reads should raise on a folder with nothing in it."""
    result = CliRunner().invoke(app, [command, "--data-dir", str(tmp_path)])

    assert result.exit_code in (0, 2), result.output
    assert "Traceback" not in result.output


def test_the_lock_command_answers_before_a_secret_exists(tmp_path, monkeypatch):
    from epicrisis import mcp_lock

    monkeypatch.setattr(mcp_lock, "SECRET_FILE", tmp_path / "totp")
    monkeypatch.setattr(mcp_lock, "read_secret", lambda *args: None)

    status = CliRunner().invoke(app, ["mcp-lock", "status", "--data-dir", str(tmp_path)])
    turning_on = CliRunner().invoke(app, ["mcp-lock", "on", "--data-dir", str(tmp_path)])
    nonsense = CliRunner().invoke(app, ["mcp-lock", "sideways", "--data-dir", str(tmp_path)])

    assert status.exit_code == 0 and "Lock: off" in status.output
    assert turning_on.exit_code == 2 and "mcp-lock init" in turning_on.output
    assert nonsense.exit_code == 2 and "status, init, on, off" in nonsense.output


def test_the_whole_run_without_a_model_goes_through_the_command_line(tmp_path):
    """Inventory, validate, index, suspects and indicators: every step that needs no model.

    The commands were only ever asked for their help before, and a command's body can be broken
    in ways --help never reaches: a name that does not exist, an option read from the wrong
    place. This walks one synthetic archive through all of them and reads what they printed.
    """
    from test_extract import setup_archive

    data_dir, source, _output = setup_archive(tmp_path)
    data = ["--data-dir", str(data_dir)]

    listed = CliRunner().invoke(app, ["inventory", str(source.path), "--out", str(tmp_path / "out.jsonl")])
    assert listed.exit_code == 0, listed.output
    assert "Inventory written to" in listed.output and (tmp_path / "out.jsonl").exists()

    checked = CliRunner().invoke(app, ["validate", *data])
    assert checked.exit_code == 0, checked.output

    built = CliRunner().invoke(app, ["index", *data])
    assert built.exit_code == 0, built.output
    assert "documents" in built.output and "written to" in built.output

    for command in ("suspects", "indicators"):
        answer = CliRunner().invoke(app, [command, *data])
        assert answer.exit_code == 0, answer.output
        assert "Traceback" not in answer.output


def test_an_archive_read_again_from_nothing_keeps_its_folder_and_its_corrections(tmp_path):
    from epicrisis.corrections import set_document_date
    from epicrisis.sources import source_output_dir
    from test_extract import setup_archive

    data_dir, source, output = setup_archive(tmp_path)
    data = ["--data-dir", str(data_dir)]
    assert CliRunner().invoke(app, ["index", *data]).exit_code == 0
    set_document_date(output, "0" * 64, [1], None)

    refused = CliRunner().invoke(app, ["forget", "no-such-archive", *data])
    assert refused.exit_code == 2 and "No archive with the id" in refused.output

    done = CliRunner().invoke(app, ["forget", source.id, "--yes", *data])
    assert done.exit_code == 0, done.output
    assert "Moved aside to" in done.output and "epicrisis update" in done.output

    output = source_output_dir(data_dir, source.id)
    assert not (output / "classify.jsonl").exists() and not (output / "inventory.jsonl").exists()
    assert (output / "corrections.jsonl").exists()  # a person's own words are not a reading
    assert Path(source.path).is_dir() and any(Path(source.path).rglob("*.pdf"))
    assert next(output.glob("forgotten-*/classify.jsonl"), None) is not None

    # Nothing is left to forget, and saying so is not an error.
    again = CliRunner().invoke(app, ["forget", source.id, "--yes", *data])
    assert again.exit_code == 0 and "Nothing had been read" in again.output


def test_the_lock_is_set_up_turned_on_and_off_from_the_command_line(tmp_path, monkeypatch):
    """The whole lifecycle, on a secret file of its own. No secret ever reaches the output."""
    from epicrisis import mcp_lock

    secret_file = tmp_path / "totp"
    monkeypatch.setattr(mcp_lock, "SECRET_FILE", secret_file)
    data = ["--data-dir", str(tmp_path)]

    started = CliRunner().invoke(app, ["mcp-lock", "init", *data])
    assert started.exit_code == 0, started.output
    secret = secret_file.read_text(encoding="utf-8").strip()
    assert len(secret) >= 16
    # The line for the authenticator holds the secret and is printed once, here, on the owner's
    # own terminal. That is the only place it is ever shown, and the file keeps it afterwards.
    assert f"otpauth://totp/Epicrisis:archive?secret={secret}" in started.output
    assert str(secret_file) in started.output

    again = CliRunner().invoke(app, ["mcp-lock", "init", *data])
    assert again.exit_code == 2 and "--force" in again.output  # never replaced by accident

    assert CliRunner().invoke(app, ["mcp-lock", "on", *data]).exit_code == 0
    assert "Lock: on" in CliRunner().invoke(app, ["mcp-lock", "status", *data]).output

    scope = CliRunner().invoke(app, ["mcp-lock", "scope", "server", *data])
    assert scope.exit_code == 0 and "server" in scope.output
    window = CliRunner().invoke(app, ["mcp-lock", "window", "60", *data])
    assert window.exit_code == 0 and "60" in window.output
    wrong = CliRunner().invoke(app, ["mcp-lock", "scope", "sideways", *data])
    assert wrong.exit_code == 2 and "conversation" in wrong.output
    no_minutes = CliRunner().invoke(app, ["mcp-lock", "window", "soon", *data])
    assert no_minutes.exit_code == 2 and "minutes" in no_minutes.output

    assert CliRunner().invoke(app, ["mcp-lock", "clear", *data]).exit_code == 0
    assert CliRunner().invoke(app, ["mcp-lock", "off", *data]).exit_code == 0
    assert "Lock: off" in CliRunner().invoke(app, ["mcp-lock", "status", *data]).output
