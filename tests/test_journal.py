"""The journal itself: one line per event, no message of any exception, and never in the way.

Every string invented here is nonsense on purpose. The journal exists to be read by whoever is
looking into a fault, which means it exists to be shown to somebody — so a test of it that used a
plausible surname would be teaching the wrong lesson in the one file where the lesson is the point.
"""

import errno
import json
import stat
from pathlib import Path

from epicrisis import journal, layout


def test_one_event_is_one_line_with_the_time_on_it(tmp_path):
    journal.record(tmp_path, {"event": "a thing happened", "archive": "qqzz1234"})
    journal.record(tmp_path, {"event": "another thing happened", "count": 3})

    lines = [json.loads(line) for line in journal.path(tmp_path).read_text(encoding="utf-8").splitlines()]
    assert [one["event"] for one in lines] == ["a thing happened", "another thing happened"]
    assert lines[0]["archive"] == "qqzz1234" and lines[1]["count"] == 3
    # The time comes first, because every line of it is read by eye and sorted by nobody.
    assert list(lines[0])[0] == "at" and lines[0]["at"].endswith("+00:00")


def test_the_journal_is_private_to_whoever_owns_the_instance(tmp_path):
    """The same mode as the access log. What went wrong in somebody's archive is theirs."""
    journal.record(tmp_path, {"event": "a thing happened"})

    assert stat.S_IMODE(journal.path(tmp_path).stat().st_mode) == 0o640


def test_a_journal_that_cannot_be_written_stops_nothing(tmp_path):
    """It is called from inside the handler that answers a full disk. Raising there would put the
    words Internal Server Error back over the page that names the trouble."""
    missing = tmp_path / "not-a-directory"

    journal.record(missing, {"event": "a thing happened"})  # recorded nowhere, raises nothing

    assert journal.last(missing) is None
    assert journal.counts(missing) == {"lines": 0, "troubles": 0}


def test_an_entry_json_cannot_write_is_not_a_reason_to_crash(tmp_path):
    journal.record(tmp_path, {"event": "a thing happened", "what": object()})

    assert journal.counts(tmp_path)["lines"] == 0
    # And it leaves no file behind. It used to leave an empty one — created by the open, never
    # written to, and so never given its mode, because the next line to arrive found a file that
    # already existed and left the mode alone. One bad entry handed the journal to the machine.
    assert not journal.path(tmp_path).exists()
    journal.record(tmp_path, {"event": "a thing happened"})
    assert stat.S_IMODE(journal.path(tmp_path).stat().st_mode) == 0o640


def test_the_file_is_trimmed_to_the_lines_it_keeps(tmp_path):
    for number in range(journal.KEEP_LINES + 12):
        journal.record(tmp_path, {"event": "a thing happened", "number": number})

    lines = journal.entries(tmp_path)
    assert len(lines) == journal.KEEP_LINES
    # The newest are the ones kept: a journal trimmed from the wrong end answers about last month.
    assert lines[-1]["number"] == journal.KEEP_LINES + 11
    # And it is still private after a trim, which rewrites the file whole.
    assert stat.S_IMODE(journal.path(tmp_path).stat().st_mode) == 0o640


def test_a_torn_last_line_is_skipped_rather_than_raised(tmp_path):
    journal.record(tmp_path, {"event": "a thing happened"})
    with journal.path(tmp_path).open("a", encoding="utf-8") as lines:
        lines.write('{"event": "cut off half')

    assert [one["event"] for one in journal.entries(tmp_path)] == ["a thing happened"]
    assert journal.last(tmp_path)["event"] == "a thing happened"


def test_a_failure_is_kept_by_its_type_and_its_line_and_never_by_its_message(tmp_path):
    """The one rule this module is for. A message can quote a document; a line number cannot."""
    try:
        # The disk that filled, named after the file it filled on: OSError carries that name, and
        # in this archive a file name carries a surname and often the reason for the visit.
        raise OSError(errno.ENOSPC, "No space left on device", "/archives/Qwyzzlon/zhabbor-7731.pdf")
    except OSError as trouble:
        journal.went_wrong(tmp_path, "trouble with a file", trouble, code=507)

    written = journal.path(tmp_path).read_text(encoding="utf-8")
    assert "Qwyzzlon" not in written and "zhabbor" not in written and "No space left" not in written

    line = journal.last(tmp_path)
    assert line["event"] == "trouble with a file" and line["kind"] == "OSError" and line["code"] == 507
    # Where it came from, named from the project down and not from the root of the disk. The
    # number is not asserted: it is this test's own raise line, and a sentence added above it is
    # not a defect.
    where, _, number = line["at_line"].rpartition(":")
    assert where == "tests/test_journal.py" and number.isdigit()


def test_what_a_failure_was_raised_from_is_kept_as_a_type(tmp_path):
    """An Unreadable raised from a torn json and one raised from bad bytes are two faults."""
    try:
        try:
            json.loads("{")
        except ValueError as broken:
            raise RuntimeError("never written down") from broken
    except RuntimeError as trouble:
        journal.went_wrong(tmp_path, "a file of state would not read", trouble)

    line = journal.last(tmp_path)
    assert line["kind"] == "RuntimeError" and line["because"] == "JSONDecodeError"
    assert "never written down" not in journal.path(tmp_path).read_text(encoding="utf-8")


def test_the_place_a_failure_came_from_is_named_from_the_package_down():
    """And the folder holding the clone never comes along, however that folder is named.

    Both of the ways of reading it out of the path are wrong, and each was written first. Looking
    for the first "epicrisis" gives "epicrisis/epicrisis/people.py", because a clone lives in a
    folder of that name too. Looking for the last gives
    "epicrisis/.claude/worktrees/agent-…/tests/test_journal.py" when the clone sits inside another
    folder of the name — which is how this test is being run. The folder above the clone is
    somebody's home directory on the machine this runs on, so either answer publishes a name.
    """
    inside = journal._PACKAGE_DIR / "web" / "app.py"
    beside = journal._PROJECT_ROOT / "tests" / "test_journal.py"

    assert journal._module(str(inside)) == "epicrisis/web/app.py"
    assert journal._module(str(beside)) == "tests/test_journal.py"
    # Nothing of the path survives for a file outside this project, wherever it sits.
    assert journal._module("/home/zhabbor/.venv/lib/python3.13/json/decoder.py") == "decoder.py"
    assert journal._module("/home/zhabbor/epicrisis/epicrisis/people.py") == "people.py"


def test_a_failure_with_no_traceback_is_still_one_line(tmp_path):
    journal.went_wrong(tmp_path, "a thing happened", RuntimeError("never written down"))

    line = journal.last(tmp_path)
    assert line["kind"] == "RuntimeError" and "at_line" not in line


def test_counts_tells_a_failure_from_an_act(tmp_path):
    journal.record(tmp_path, {"event": "the archive shown was switched", "archive": "qqzz1234"})
    journal.went_wrong(tmp_path, "a thing happened", RuntimeError("x"))

    assert journal.counts(tmp_path) == {"lines": 2, "troubles": 1}


def test_the_journal_is_nobodys_work_and_a_backup_leaves_it_behind():
    """`backup` copies THEIR_OWN_WORK off the machine. The journal must never be in that list.

    Nobody typed a line of it, and the one thing it is for is this machine: which failure happened
    here, in which line of which module. Carried away it is a file about somebody's instance
    sitting somewhere nobody meant it to be.
    """
    assert layout.JOURNAL in layout.MADE_AGAIN_BY_CODE
    assert layout.JOURNAL not in layout.THEIR_OWN_WORK
    assert layout.JOURNAL not in layout.THEIR_CHOICES
    assert layout.JOURNAL not in layout.MADE_AGAIN_BY_A_MODEL
    assert layout.JOURNAL == journal.FILE_NAME


def test_the_status_page_says_the_journal_is_there_and_says_what_is_not_in_it(tmp_path):
    """The program says out loud everything it does, and a new file in the data directory is a
    thing it does. What is *not* in a log beside a medical archive matters more than what is."""
    from fastapi.testclient import TestClient

    from epicrisis.sources import SourceRegistry
    from epicrisis.web.app import create_app

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (tmp_path / "scans").mkdir()
    registry = SourceRegistry(data_dir)
    registry.set_active(registry.add(str(tmp_path / "scans"), owner="Somebody").id)
    journal.record(data_dir, {"event": "a thing happened"})

    page = TestClient(create_app(data_dir, background_jobs=False),
                      base_url="http://localhost:8050").get("/status").text  # fmt: skip

    assert journal.FILE_NAME in page and "a thing happened" in page
    assert "no message of any exception" in page
    assert "paste the whole of it into a bug report" in page.lower()


def test_the_readme_says_the_journal_holds_no_content(tmp_path):
    said = " ".join((Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8").split())

    assert journal.FILE_NAME in said
    assert "no message of any exception" in said
    assert "paste the whole file into a bug report and you have given nothing away" in said


def test_the_journal_sits_in_the_data_directory_and_not_inside_an_archive():
    """One journal for the instance, as the access log is. It holds no printed string of anybody's
    — only the random id of the archive an event was about — and that is what makes it safe to
    keep beside the instance rather than inside one archive's own folder."""
    assert journal.path(Path("/somewhere/data")) == Path("/somewhere/data/journal.jsonl")
