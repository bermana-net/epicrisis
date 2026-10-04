"""The journal must be safe to paste into a stranger's chat whole. This is the test of that.

One archive is built whose every printed string is a known nonsense word — the words are taken
from `test_the_wall_between_people.py`, which is where they were invented and where they were
looked for in the archives first, so no plausible name is being added to this repository by this
file. Its folder on disk is named after the person and their diagnosis, because that is how an
archive of this kind is named, and its files after the doctor and the test, because that is how
scans are named.

Then every kind of trouble this journal records is caused in turn, and every act it records is
performed, and the file is read whole and swept for all of it: the person, the doctor, the
laboratory, the test, the value, the unit, the diagnosis, the medication, the printed line, a
search, the folder, the absolute paths and the names of the files. Not one of them may be there.

The sweep is written so that it can fail, and the test below it proves that it does: it writes one
line holding one of those words and asserts that the same sweep catches it. A guard that cannot
fail guards nothing, and this one guards the sentence the module's own docstring is written to.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from epicrisis import journal, layout, people, records, state
from epicrisis.sources import SourceRegistry, source_output_dir
from epicrisis.web.app import create_app
from test_the_wall_between_people import THEIRS

MINE = THEIRS["one"]
#: Everything an archive of this kind prints or is named after, and not one of it may be in a line.
NOTHING_OF_THEIRS = tuple(MINE[key] for key in
                          ("whose", "doctor", "provider", "test", "value", "unit",
                           "diagnosis", "medication", "line"))  # fmt: skip


def an_archive_of_recognisable_strings(tmp_path: Path) -> tuple[Path, str, Path]:
    """A data directory holding one archive, named the way these archives are named.

    The folder carries the person and what was wrong with them, and the files inside it carry the
    doctor and the test. Both are true of a real archive of scans and both are the reason a
    refusal here may not quote a path.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    archive = tmp_path / f"{MINE['whose']} {MINE['diagnosis']}"
    archive.mkdir(parents=True)
    (archive / f"{MINE['test']} {MINE['doctor']}.pdf").write_bytes(b"%PDF-1.4 not really a pdf")
    registry = SourceRegistry(data_dir)
    source = registry.add(str(archive), owner=MINE["whose"])
    registry.set_active(source.id)
    return data_dir, source.id, archive


def dashboard(data_dir: Path) -> TestClient:
    return TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050",
                      raise_server_exceptions=False)  # fmt: skip


def whatever_leaked(data_dir: Path, archive: Path, tmp_path: Path) -> dict[str, list[str]]:
    """Every forbidden word found in the journal, by the line it was found in.

    The whole file as text, not field by field: a word in a key, in a nested value or in a field
    somebody adds next month is the same leak, and a sweep that only looked at the fields it knew
    about would pass over it.
    """
    forbidden = [*NOTHING_OF_THEIRS, archive.name, str(archive), str(tmp_path),
                 f"{MINE['test']} {MINE['doctor']}.pdf"]  # fmt: skip
    found = {}
    for line in journal.path(data_dir).read_text(encoding="utf-8").splitlines():
        caught = [word for word in forbidden if word in line]
        if caught:
            found[line] = caught
    return found


def every_kind_of_trouble(tmp_path: Path) -> tuple[Path, str, Path, list[str]]:
    """Cause each thing the journal records, and perform each act it records, in one instance."""
    from test_inventory import make_scan_pdf

    from epicrisis.classify.run import classify_source
    from epicrisis.inventory.run import write_inventory

    data_dir, source_id, archive = an_archive_of_recognisable_strings(tmp_path)
    journal.say_everything_again()
    client = dashboard(data_dir)

    # A page that meets a disk with no room left, named after the file it failed on.
    @client.app.get("/a-write-that-meets-a-full-disk")
    def _full() -> None:
        raise OSError(28, "No space left on device", str(archive / f"{MINE['test']}.pdf"))

    # A fault nobody foresaw, carrying a printed line in its message, as a rule's words can.
    @client.app.get("/a-fault-nobody-foresaw")
    def _fault() -> None:
        raise KeyError(MINE["line"])

    # And one of this program's own files of state, there and not parsing, named inside the archive.
    @client.app.get("/a-page-over-a-torn-file-of-state")
    def _torn() -> None:
        raise state.Unreadable(state.where(data_dir / layout.ARCHIVES / source_id / layout.PEOPLE),
                               f"Every {MINE['test']} ever printed is still in that file.",
                               f"Copy back {layout.PEOPLE}.previous beside it.")  # fmt: skip

    client.get("/a-write-that-meets-a-full-disk")
    client.get("/a-fault-nobody-foresaw")
    client.get("/a-page-over-a-torn-file-of-state")

    # A step already running, refused while a group of spellings was being saved.
    (data_dir / "indicators.lock").write_text(
        json.dumps({"pid": 1, "started_at": records.now()}), encoding="utf-8")
    client.post("/indicators", data={"action": "save", "label": MINE["test"],
                                     "names": MINE["test"], "status": "approved"})  # fmt: skip
    (data_dir / "indicators.lock").unlink()

    # A group of spellings settled by hand, and a search, which is the question itself.
    client.post("/indicators", data={"action": "save", "label": MINE["test"],
                                     "names": f"{MINE['test']}\n{MINE['test']} total",
                                     "status": "approved"})  # fmt: skip
    client.get("/search", params={"q": MINE["line"]})

    # The archive shown, switched to another person's and back.
    (tmp_path / "second").mkdir()
    other = SourceRegistry(data_dir).add(str(tmp_path / "second"), owner=THEIRS["two"]["whose"])
    client.post("/owner", data={"source": other.id, "back": "/"}, follow_redirects=True)
    client.post("/owner", data={"source": source_id, "back": "/"}, follow_redirects=True)

    # Decisions about who is who, made by hand: joined, undone, said no to, and that taken back.
    both = [MINE["doctor"], f"{MINE['doctor']} ({MINE['provider']})"]
    people.join(data_dir, source_id, "doctor", both, both[1])
    people.split(data_dir, source_id, "doctor", both[1])
    places = [MINE["provider"], MINE["provider"] + " East"]
    people.propose(data_dir, source_id, "institution", places)
    people.decline(data_dir, source_id, "institution", places)
    people.reconsider(data_dir, source_id, "institution", places)

    # Pages of the archive that cannot be turned into text or a picture, from a step of the
    # pipeline: the bytes on disk are no longer the ones the inventory hashed.
    output = source_output_dir(data_dir, source_id)
    make_scan_pdf(archive / f"{MINE['doctor']} {MINE['value']}.pdf", pages=2)
    write_inventory(archive, output / layout.INVENTORY)
    (archive / f"{MINE['doctor']} {MINE['value']}.pdf").write_bytes(b"not a pdf any more")

    class NeverCalled:
        name, model = "fake", "fake-model-1"

        def classify(self, payload, workdir):  # pragma: no cover - no page reaches a model here
            raise AssertionError("no page should have reached a model")

    classify_source(data_dir, SourceRegistry(data_dir).get(source_id), NeverCalled())

    # Settings changed: a rule switched off, its thresholds moved, the answer mode, the window of
    # the lock, and the two places where a string somebody typed could reach this file — a model
    # named by hand, and a threshold of a shape no rule ships today but the writer would take.
    from dataclasses import replace

    from epicrisis import rules, settings

    a_rule = next(one for one in rules.load(data_dir) if one.settings and one.on_by_default)
    with settings.editing(data_dir):  # one press of Save, as the settings page makes it
        settings.set_rule_on(data_dir, a_rule.id, False)
        settings.set_rule_settings(data_dir, a_rule, {name: 7 for name in a_rule.settings})
        settings.set_answer_mode(data_dir, "direct")
        settings.set_mcp_lock_minutes(data_dir, 11)
        settings.set_rule_settings(data_dir, replace(a_rule, settings={"spelling": "whatever"}),
                                   {"spelling": MINE["test"]})  # fmt: skip
        settings.set_chosen_models(data_dir, {"strong": MINE["line"][:80]})

    # And a command refusing on the command line, its arguments naming the archive folder.
    import subprocess
    import sys

    # Two archives are on this list, so a step that reads pages refuses to guess which, and says
    # so with ids alone — the names are folder names. The journal line goes beside them.
    refused = subprocess.run(
        [sys.executable, "-m", "epicrisis", "classify", "--data-dir", str(data_dir)],
        capture_output=True, text=True, cwd=Path(__file__).parent.parent)  # fmt: skip
    assert refused.returncode == 2, refused.stdout + refused.stderr

    return data_dir, source_id, archive, [one["event"] for one in journal.entries(data_dir)]


def test_not_one_word_of_an_archive_reaches_the_journal(tmp_path: Path):
    """The sweep. Every kind of trouble, every act, every printed string, both ways round."""
    data_dir, source_id, archive, events = every_kind_of_trouble(tmp_path)

    leaked = whatever_leaked(data_dir, archive, tmp_path)
    assert leaked == {}, f"the journal holds what an archive printed: {leaked}"

    # And the journal did record all of it, or the sweep above proves nothing: an empty file
    # would pass it. This is the half of the wall test that was once missing from a fixture.
    assert set(events) >= {
        "there was no space left on the disk",
        "a request failed with no page to answer it",
        "a file of this instance would not read",
        "a step was already running",
        "a group of spellings was settled by hand",
        "the archive shown was switched",
        "names were joined into one",
        "a join of names was undone",
        "names were said not to be one",
        "a refusal about names was taken back",
        "a page could not be read",
        "a command refused and stopped",
        "a rule was switched off",
        "a rule's thresholds were changed",
        "a setting was changed",
        "a model was chosen for a pass",
    }, sorted(set(events))

    # The random id of the archive is the one thing of the archive's that is written down, and it
    # is written down because it is random: the folder name is what carries the surname.
    written = journal.path(data_dir).read_text(encoding="utf-8")
    assert source_id in written
    assert len(source_id) == 8 and source_id not in archive.name


def test_the_sweep_can_fail(tmp_path: Path):
    """A guard that cannot fail guards nothing.

    One line is written holding the name of the laboratory, by exactly the call every hook in this
    program uses, and the sweep above is asked about it. If this passes while the test above is
    unable to fail, the two disagree and somebody has to look.
    """
    data_dir, _, archive = an_archive_of_recognisable_strings(tmp_path)

    journal.record(data_dir, {"event": "a thing happened", "provider": MINE["provider"]})

    leaked = whatever_leaked(data_dir, archive, tmp_path)
    assert len(leaked) == 1 and MINE["provider"] in next(iter(leaked.values()))


@pytest.mark.parametrize("word", NOTHING_OF_THEIRS, ids=lambda word: word[:24])
def test_the_sweep_looks_for_each_printed_string_on_its_own(tmp_path: Path, word: str):
    """Each of them, one at a time: a sweep that only caught some of them would pass the test
    above as long as the leak happened to be one of the others."""
    data_dir, _, archive = an_archive_of_recognisable_strings(tmp_path)

    journal.record(data_dir, {"event": "a thing happened", "whatever": word})

    assert whatever_leaked(data_dir, archive, tmp_path), word
