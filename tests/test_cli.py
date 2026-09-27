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


def test_an_archive_can_be_added_the_way_the_readme_says(tmp_path):
    """The command the README, the site and this program's own messages all named did not exist.

    A person who had installed everything and liked the demo typed it, got "No such command", and
    was told the same command again by the program itself when they tried update.
    """
    from typer.testing import CliRunner

    from epicrisis.cli import app
    from epicrisis.sources import SourceRegistry

    folder = tmp_path / "scans"
    folder.mkdir()
    (folder / "a-form.txt").write_text("a page", encoding="utf-8")
    data = tmp_path / "data"
    runner = CliRunner()

    # Whose records these are is asked for, because every page carries the name.
    refused = runner.invoke(app, ["sources", "add", str(folder), "--data-dir", str(data)])
    assert refused.exit_code == 2 and "whose records" in refused.output

    added = runner.invoke(app, ["sources", "add", str(folder), "--owner", "A Person", "--data-dir", str(data)])
    assert added.exit_code == 0 and "A Person" in added.output
    assert "Nothing has been read yet" in added.output

    registry = SourceRegistry(data)
    assert [source.owner for source in registry.list()] == ["A Person"]
    assert registry.active() is not None, "the first archive added is the one that is open"

    listed = runner.invoke(app, ["sources", "list", "--data-dir", str(data)])
    assert listed.exit_code == 0 and "A Person" in listed.output and "(open)" in listed.output


def test_the_secret_that_stands_in_the_served_path_can_be_made(tmp_path):
    """mcp --http refuses to start without one, and there was no way to make it.

    The README described the lock and named no command, so a person had to work out that a file
    of at least thirty-two characters was wanted, and invent it themselves.
    """
    from typer.testing import CliRunner

    from epicrisis.cli import app
    from epicrisis.mcp_server import MIN_SECRET

    out = tmp_path / "etc" / "mcp-token"
    runner = CliRunner()
    made = runner.invoke(app, ["mcp-secret", str(out)])
    assert made.exit_code == 0
    assert len(out.read_text(encoding="utf-8").strip()) >= MIN_SECRET
    assert out.read_text(encoding="utf-8").strip() not in made.output, "the secret is not printed"

    again = runner.invoke(app, ["mcp-secret", str(out)])
    assert again.exit_code == 2 and "already there" in again.output


def test_the_command_a_page_prints_can_be_typed_from_another_folder():
    """`uv run epicrisis …` finds the project by walking up, so it worked in one folder only.

    Every page and every message of this program prints a command for somebody to copy. From
    anywhere but the checkout itself — a home directory, the disk the scans are on, wherever a
    person happened to open a terminal — the answer was `error: Failed to spawn: epicrisis`. The
    folder picker's refusal is the worst of them: it names the typed command as the one way to add
    a disk the picker will not offer, to somebody who has nowhere else to go.
    """
    import shutil
    import subprocess
    import sys

    from epicrisis import __version__, invocation

    printed = invocation.run("--version")
    project = Path(sys.prefix).resolve().parent
    assert f"--project {project}" in printed, printed

    if shutil.which("uv") is None:  # pragma: no cover - a machine without uv cannot be asked
        pytest.skip("uv is not on the path of this run")
    # The proof is the shell's, not the assertion's: the words as printed, typed somewhere else.
    typed = subprocess.run(printed, shell=True, cwd="/tmp", capture_output=True, text=True, timeout=300)
    assert typed.returncode == 0, typed.stdout + typed.stderr
    assert __version__ in typed.stdout


def test_a_page_never_prints_a_command_without_the_instance_it_acts_on():
    """--data-dir defaults to "data" beside whoever is standing there, and the pages said nothing.

    A person who had followed the demo (--data-dir /tmp/demo/data) and stood in the program's own
    folder copied a line off a page and turned Ask on, or built an index, in another instance — or
    in one this made on the spot — and was told it had worked. The lock's own advice on the
    settings page was given the folder for exactly this reason; the rest of the pages were not.
    """
    import re

    commands = re.compile(r"\{\{ cli \}\}([^<]*)")
    templates = Path(__file__).parent.parent / "epicrisis" / "web" / "templates"
    for page in sorted(templates.glob("*.html")):
        for printed in commands.findall(page.read_text(encoding="utf-8")):
            assert "--data-dir" in printed, f"{page.name} prints '{printed.strip()}' for no instance"


def test_the_advice_a_command_prints_names_the_folder_it_acted_on(tmp_path):
    """The same defect on the command line: advice printed by one instance about another."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    folder = tmp_path / "scans"
    folder.mkdir()
    data = ["--data-dir", str(data_dir)]

    empty = CliRunner().invoke(app, ["index", *data])
    assert empty.exit_code == 2
    assert f"--data-dir {data_dir}" in empty.output, empty.output

    added = CliRunner().invoke(app, ["sources", "add", str(folder), "--owner", "A Person", *data])
    assert added.exit_code == 0, added.output
    assert f"serve --data-dir {data_dir}" in added.output, added.output


@pytest.mark.parametrize("command", (["index"], ["update"], ["validate"], ["sources", "list"],
                                     ["forget", "whatever"]))  # fmt: skip
def test_a_command_in_the_wrong_folder_says_so_instead_of_offering_a_second_archive(command, tmp_path):
    """Run from anywhere but the instance's folder, every one of them said "No archive here yet".

    Which is an invitation to add the archive a second time, under a new id, leaving every hour of
    reading under the old one. The folder being somewhere else is the whole of what happened, and
    it is what the answer has to say. The guard existed and was on two commands out of seven.
    """
    missing = tmp_path / "not-an-instance"

    answer = CliRunner().invoke(app, [*command, "--data-dir", str(missing)])

    assert answer.exit_code == 2, answer.output
    assert "no data folder" in answer.output and str(missing) in answer.output
    assert "Traceback" not in answer.output
    assert not missing.exists(), "a folder that is not an instance is not made into one"
