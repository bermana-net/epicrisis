"""Every failure this program already answers in words now also leaves a line behind.

The pages were written years ago and each of them says which file, what is safe and what puts it
right. What none of them did was remember: a refusal drew its page and vanished, so a fault
reported an hour later could only be looked into by asking the person to make it happen again.

Each test here breaks something a real machine breaks by itself, and asserts that the journal
holds the event, the type, the line it came from and the code — and that the sentence the
exception carried is not in it.

Every invented string is nonsense on purpose, and `test_journal_shows_nothing.py` is the sweep
that proves none of them reach a line.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from epicrisis import journal, layout, records
from epicrisis.sources import SourceRegistry, source_output_dir
from epicrisis.web.app import create_app
from test_the_wall_between_people import THEIRS


def an_instance(tmp_path: Path, folder: Path | None = None) -> tuple[Path, str]:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    archive = folder or (tmp_path / "zhabbor-qwyzzlon")
    archive.mkdir(parents=True, exist_ok=True)
    registry = SourceRegistry(data_dir)
    source = registry.add(str(archive), owner=THEIRS["one"]["whose"])
    registry.set_active(source.id)
    return data_dir, source.id


def dashboard(data_dir: Path) -> TestClient:
    return TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050",
                      raise_server_exceptions=False)  # fmt: skip


def only(data_dir: Path, event: str) -> dict:
    """The one line of that event, asserting that there is exactly one."""
    found = [one for one in journal.entries(data_dir) if one["event"] == event]
    assert len(found) == 1, [one["event"] for one in journal.entries(data_dir)]
    return found[0]


def test_a_torn_file_of_state_is_written_down_with_the_file_and_the_code(tmp_path: Path):
    """The page names the file; nothing remembered that it had ever been named.

    sources.json is asked for by every page, so a torn one is the case where the dashboard has
    nowhere to send a person — and the case where nobody will be looking at a terminal either.
    """
    data_dir, _ = an_instance(tmp_path)
    (data_dir / layout.SOURCES).write_text('[{"id": "aa11bb22", "name": "x", "pa', encoding="utf-8")

    assert dashboard(data_dir).get("/").status_code == 503

    line = only(data_dir, "a file of this instance would not read")
    assert line["kind"] == "Unreadable" and line["code"] == 503
    assert line["file"] == layout.SOURCES
    # Where in this project the refusal came from, which is what the page cannot say and what
    # tells one of the nine raise sites that share a sentence from the others.
    assert line["at_line"].startswith("epicrisis/sources.py:")
    # And what it was raised from: a torn json and bad bytes are two faults with one sentence.
    assert line["because"] == "JSONDecodeError"


def test_a_file_of_state_inside_an_archive_is_written_down_relatively_and_no_further_up(tmp_path: Path):
    """The files of a person's own work moved inside the archive they are about.

    `Unreadable` carries its file through state.where(), which cuts the path at the archives
    folder, so what reaches the journal is sources/<random id>/extracted/<hash>.json. The id is
    random for exactly this reason: the folder names of archives are not — they carry a surname
    and often what was wrong with the person.
    """
    from epicrisis import state
    from epicrisis.extract.run import extracted_path

    data_dir, source_id = an_instance(tmp_path)
    torn = extracted_path(data_dir / layout.ARCHIVES / source_id / layout.EXTRACTED, "b" * 64)
    client = dashboard(data_dir)

    @client.app.get("/a-page-over-a-torn-transcription")
    def _torn() -> None:
        raise state.Unreadable(state.where(torn), "Every other document is whole.",
                               "Delete that one file and read that one document again.")  # fmt: skip

    assert client.get("/a-page-over-a-torn-transcription").status_code == 503

    line = only(data_dir, "a file of this instance would not read")
    assert line["file"] == f"{layout.ARCHIVES}/{source_id}/{layout.EXTRACTED}/{torn.name}"
    assert str(tmp_path) not in json.dumps(line) and "zhabbor" not in json.dumps(line)
    # The sentences the exception carries are not written down. They name no value and no person —
    # every raise site passes a fixed phrase — but the page is where a person reads them, and a
    # field the journal does not need is a field it does not keep.
    assert "Every other document is whole" not in json.dumps(line)


def test_a_full_disk_is_written_down_with_the_code_it_answers_with(tmp_path: Path):
    data_dir, _ = an_instance(tmp_path)
    client = dashboard(data_dir)

    @client.app.get("/a-write-that-meets-a-full-disk")
    def _write() -> None:
        raise OSError(28, "No space left on device", "/zhabbor-qwyzzlon/2019/pselofaza.pdf")

    assert client.get("/a-write-that-meets-a-full-disk").status_code == 507

    line = only(data_dir, "there was no space left on the disk")
    assert line["kind"] == "OSError" and line["code"] == 507
    # OSError carries the name of the file it failed on, and here that name is somebody's.
    assert "pselofaza" not in json.dumps(line) and "No space" not in json.dumps(line)


def test_a_step_already_running_is_written_down_with_the_step_and_the_lock(tmp_path: Path):
    data_dir, _ = an_instance(tmp_path)
    (data_dir / "indicators.lock").write_text(
        json.dumps({"pid": 1, "started_at": records.now()}), encoding="utf-8")

    refused = dashboard(data_dir).post("/indicators",
                                       data={"action": "save", "label": "Zhabborin", "names": "Zhb"})  # fmt: skip

    assert refused.status_code == 409
    line = only(data_dir, "a step was already running")
    assert line["kind"] == "Busy" and line["code"] == 409 and line["file"] == "indicators.lock"
    assert line["step"]  # which step holds it, in this program's own words
    # The lock is named inside the data directory and no further up, as the page names it: a path
    # outside it could be an archive folder, and those are named after people.
    assert str(tmp_path) not in json.dumps(line)
    # And nothing of what was being saved when it was refused.
    assert "Zhabborin" not in json.dumps(line) and "Zhb" not in json.dumps(line)


def test_a_fault_with_no_page_to_answer_it_is_written_down_at_all(tmp_path: Path):
    """There is no handler for Exception here on purpose, so until now this was the whole of it:
    a traceback to whatever started the server, and nothing on disk."""
    data_dir, _ = an_instance(tmp_path)
    client = dashboard(data_dir)

    @client.app.get("/a-fault-nobody-foresaw")
    def _fault() -> None:
        raise KeyError("Pselofaza 3,33 zyu/dl, the words of a rule, which may quote a page")

    assert client.get("/a-fault-nobody-foresaw").status_code == 500

    line = only(data_dir, "a request failed with no page to answer it")
    assert line["kind"] == "KeyError" and line["method"] == "GET"
    assert "Pselofaza" not in json.dumps(line) and "zyu/dl" not in json.dumps(line)
    # Which page was asked for is left out: a path here carries whatever a person typed into a
    # search, and the method and the type of the fault are what somebody looking into it needs.
    assert "a-fault-nobody-foresaw" not in json.dumps(line)


def on_the_command_line(*arguments: str) -> tuple[int, str]:
    """Run a command the way a person does: through the entry point, in a process of its own.

    run() is where a refusal becomes one sentence and a status, and it is the only place that can
    write the line — a test going in through CliRunner would skip exactly the door being tested.
    """
    import subprocess
    import sys

    done = subprocess.run([sys.executable, "-m", "epicrisis", *arguments],
                          capture_output=True, text=True, cwd=Path(__file__).parent.parent)  # fmt: skip
    return done.returncode, done.stdout + done.stderr


def test_a_command_that_refuses_is_written_down_with_its_code_and_its_name(tmp_path: Path):
    """The thirty places in the commands that say no and leave with 2.

    Each of them prints a sentence a person can act on, and then the terminal is closed and that
    is the end of it. Click turns every one of them into a SystemExit on its way out of app(), so
    they are all caught in the one place.
    """
    data_dir, _ = an_instance(tmp_path)

    code, said = on_the_command_line("suspects", "--data-dir", str(data_dir))

    assert code == 2 and "Nothing is indexed yet" in said
    line = only(data_dir, "a command refused and stopped")
    assert line["code"] == 2 and line["command"] == "suspects"
    # No exception reached run(): the command answered for itself and asked to stop.
    assert "kind" not in line


def test_a_torn_file_of_state_on_the_command_line_is_written_down_too(tmp_path: Path):
    """The sentence and status 2 were already right. Nothing remembered them."""
    data_dir, _ = an_instance(tmp_path)
    (data_dir / layout.SETTINGS).write_text("{not json", encoding="utf-8")

    code, said = on_the_command_line("ask", "--on", "--data-dir", str(data_dir))

    assert code == 2 and "cannot be read" in said
    line = only(data_dir, "a file of this instance would not read")
    assert line["kind"] == "Unreadable" and line["code"] == 2 and line["command"] == "ask"
    assert line["file"] == layout.SETTINGS


def test_nothing_but_the_name_of_the_command_is_read_off_the_line(tmp_path: Path):
    """An argument here is a path to somebody's archive, or a search, or the name of a model.

    The folder names of archives carry surnames and often what was wrong with the person, so the
    one word taken off the line is the command's own name, and only where it is one this program
    has.
    """
    from epicrisis import cli

    assert cli._which_command(["epicrisis", "classify", "--data-dir", "/zhabbor-qwyzzlon"]) == {"command": "classify"}
    assert cli._which_command(["epicrisis", "--version"]) == {}
    assert cli._which_command(["epicrisis", "/zhabbor-qwyzzlon/2019"]) == {}
    assert cli._which_command(["epicrisis"]) == {}
    # The option that decides which instance the line goes into, both ways round.
    assert cli._the_instance_in(["epicrisis", "ask", "--data-dir", "/tmp/qq"]) == Path("/tmp/qq")
    assert cli._the_instance_in(["epicrisis", "ask", "--data-dir=/tmp/qq"]) == Path("/tmp/qq")
    assert cli._the_instance_in(["epicrisis", "ask"]) == cli.DEFAULT_DATA_DIR


def test_a_page_the_pipeline_could_not_read_is_written_down_once(tmp_path: Path):
    """And once only, per place it is raised from, per archive, per step.

    Nine hundred pages of one archive fail at the same line for the same reason, and nine hundred
    identical lines would push every other failure out of a journal that keeps five thousand.
    """
    from test_inventory import make_scan_pdf

    from epicrisis.classify.run import classify_source
    from epicrisis.inventory.run import write_inventory

    archive = tmp_path / "zhabbor-qwyzzlon"
    archive.mkdir(parents=True)
    make_scan_pdf(archive / "zhabborin-7731.pdf", pages=2)
    make_scan_pdf(archive / "pselofaza-3313.pdf", pages=2)
    data_dir, source_id = an_instance(tmp_path, folder=archive)
    source = SourceRegistry(data_dir).get(source_id)
    output = source_output_dir(data_dir, source_id)
    write_inventory(archive, output / layout.INVENTORY)
    # The disk that was carried elsewhere and came back changed: every page of both files now
    # hashes to something the inventory never saw, which is a PageUnreadable before any model.
    for scan in sorted(archive.glob("*.pdf")):
        scan.write_bytes(b"not a pdf any more")

    journal.say_everything_again()

    class NeverCalled:
        name, model = "fake", "fake-model-1"

        def classify(self, payload, workdir):  # pragma: no cover - every page fails before this
            raise AssertionError("no page should have reached a model")

    stats = classify_source(data_dir, source, NeverCalled())

    assert stats.unreadable == 4 and stats.classified == 0
    line = only(data_dir, "a page could not be read")
    assert line["kind"] == "PageUnreadable" and line["archive"] == source_id
    assert line["step"] == "classify" and line["said_once"] is True
    assert line["at_line"].startswith("epicrisis/classify/pages.py:")
    # Four pages failed and one line was written. What each page was stays in the ledger, which
    # holds the file, its hash and its number against the document — the three things that would
    # tie a line of this journal back to one person's scan.
    written = journal.path(data_dir).read_text(encoding="utf-8")
    for name in ("zhabbor", "zhabborin", "pselofaza", "7731", "3313"):
        assert name not in written, name
