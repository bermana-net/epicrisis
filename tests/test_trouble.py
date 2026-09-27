"""What a person meets when something has already gone wrong, and whether they are told.

Every test here starts from a state a real machine arrives at by itself: a disk that filled up
mid-write, a process killed between two writes, a folder whose disk did not mount, a file edited
by hand, a clock that drifted, a lock left by a run that died. What is being checked is not that
the program survives — most of that it already did — but that what the person sees names the file,
says what has *not* been lost, and gives the one act that puts it right. The words "Internal
Server Error", a Python traceback and the name of an exception class are none of those things.
"""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from epicrisis import consent, indicators, layout, records, settings, state
from epicrisis.cli import app
from epicrisis.index.build import SCHEMA_VERSION, index_path
from epicrisis.query import IndexMissing, open_index
from epicrisis.sources import SourceRegistry
from epicrisis.web.app import create_app


def on_the_command_line(*arguments: str) -> tuple[int, str]:
    """Run a command the way a person does: through the entry point, in a process of its own.

    CliRunner calls the typer app directly, which is exactly the door that these answers are not
    behind: run() is where a file of state that will not parse becomes one sentence and status 2,
    and a test that skipped it would have passed over the traceback it is here to prevent.
    """
    done = subprocess.run([sys.executable, "-m", "epicrisis", *arguments],
                          capture_output=True, text=True, cwd=Path(__file__).parent.parent)  # fmt: skip
    return done.returncode, done.stdout + done.stderr


def dashboard(data_dir: Path) -> TestClient:
    return TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050",
                      raise_server_exceptions=False)  # fmt: skip


def _ago(seconds: float) -> str:
    """A moment that many seconds in the past, written as this program writes moments."""
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def an_instance(tmp_path: Path, folder: Path | None = None) -> tuple[Path, str]:
    """A data directory with one archive on the list, as a person's own instance has."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    archive = folder or (tmp_path / "archive")
    archive.mkdir(parents=True, exist_ok=True)
    registry = SourceRegistry(data_dir)
    source = registry.add(str(archive), owner="Somebody")
    registry.set_active(source.id)
    return data_dir, source.id


def test_a_torn_list_of_archives_is_a_page_and_not_internal_server_error(tmp_path: Path):
    """sources.json is asked for by every page and every command, so it took all of them down."""
    data_dir, _ = an_instance(tmp_path)
    (data_dir / layout.SOURCES).write_text('[{"id": "aa11bb22", "name": "x", "pa', encoding="utf-8")

    client = dashboard(data_dir)
    for page in ("/", "/status", "/documents", "/settings", "/indicators", "/review"):
        answer = client.get(page)
        assert answer.status_code == 503, page
        assert "sources.json" in answer.text, page
        # What has not been lost, and what to do. A person meeting this has no other information.
        assert "No archive has been touched" in answer.text
        assert "sources.json.previous" in answer.text

    # And the command line says the sentence and leaves with 2, rather than a traceback and 1.
    code, said = on_the_command_line("sources", "list", "--data-dir", str(data_dir))
    assert code == 2 and "sources.json is there and cannot be read" in said
    assert "Traceback" not in said


def test_the_list_of_archives_keeps_the_version_before_the_last_change(tmp_path: Path):
    """It is the only thing tying a person's folders to everything read from them."""
    data_dir, first = an_instance(tmp_path)
    second = tmp_path / "second"
    second.mkdir()
    SourceRegistry(data_dir).add(str(second), owner="Somebody Else")

    kept = json.loads((data_dir / (layout.SOURCES + ".previous")).read_text(encoding="utf-8"))
    assert [entry["id"] for entry in kept] == [first]


def test_a_moved_archive_is_pointed_at_its_new_place_and_keeps_what_was_read(tmp_path: Path):
    """The whole of what moving an archive costs: one field. Before this there was no way at all."""
    data_dir, source_id = an_instance(tmp_path)
    read_from_it = data_dir / "sources" / source_id / layout.CORRECTIONS
    read_from_it.parent.mkdir(parents=True, exist_ok=True)
    read_from_it.write_text('{"field": "value_as_printed"}\n', encoding="utf-8")
    moved_to = tmp_path / "on-another-disk"
    moved_to.mkdir()

    code, _said = on_the_command_line("sources", "set-path", source_id, str(moved_to), "--data-dir", str(data_dir))

    assert code == 0
    listed = SourceRegistry(data_dir).list()
    assert [source.path for source in listed] == [str(moved_to)]
    # One archive, the same id, and everything read from it still where it was.
    assert len(listed) == 1 and listed[0].id == source_id
    assert read_from_it.exists()


def test_pointing_an_archive_at_a_folder_that_is_not_there_changes_nothing(tmp_path: Path):
    data_dir, source_id = an_instance(tmp_path)
    before = SourceRegistry(data_dir).get(source_id).path

    code, said = on_the_command_line("sources", "set-path", source_id, str(tmp_path / "nowhere"),
                                     "--data-dir", str(data_dir))  # fmt: skip

    assert code == 2 and "No such folder" in said
    assert SourceRegistry(data_dir).get(source_id).path == before


def test_the_status_page_says_a_folder_is_not_where_it_was(tmp_path: Path):
    """It used to draw the counts of the last scan beside a path to nothing, and say nothing."""
    gone = tmp_path / "on-a-disk-that-did-not-mount"
    data_dir, source_id = an_instance(tmp_path, folder=gone)
    gone.rmdir()

    page = dashboard(data_dir).get("/status")

    assert page.status_code == 200
    assert "is not where it was" in page.text
    assert "sources set-path" in page.text  # the way out, named, with the id in it
    assert source_id in page.text


def test_a_torn_settings_file_is_said_on_the_page_that_shows_the_settings(tmp_path: Path):
    """Every switch on it is drawn at its default over such a file, and the lock draws as on."""
    data_dir, _ = an_instance(tmp_path)
    settings.set_answer_mode(data_dir, "with_meaning")
    whole = (data_dir / layout.SETTINGS).read_text(encoding="utf-8")
    (data_dir / layout.SETTINGS).write_text(whole[: len(whole) // 2], encoding="utf-8")

    client = dashboard(data_dir)
    for page in ("/settings", "/status"):
        answer = client.get(page)
        assert answer.status_code == 200, page
        assert "settings.json" in answer.text and "cannot be read" in answer.text, page
    # The lock showing as on is right — it fails closed — and now it says why it is showing that.
    assert "closed rather than open" in client.get("/status").text


def test_the_command_line_answers_a_torn_settings_file_in_one_sentence(tmp_path: Path):
    """The sentence was there; a traceback of thirty-five lines and exit 1 came after it."""
    data_dir, _ = an_instance(tmp_path)
    (data_dir / layout.SETTINGS).write_text("{not json", encoding="utf-8")

    code, said = on_the_command_line("ask", "--on", "--data-dir", str(data_dir))

    assert code == 2  # and not 1, which is what an unhandled typer.Exit left behind
    assert "settings.json is there and cannot be read" in said
    assert "Traceback" not in said and "typer.exceptions.Exit" not in said


def test_a_torn_consent_file_does_not_shut_the_door_for_ever(tmp_path: Path):
    """Behind that button is every reading this program does, and it answered 500 for ever."""
    data_dir, _ = an_instance(tmp_path)
    (data_dir / "consent.json").write_text('{"claude-code": {"ver', encoding="utf-8")

    consent.record_consent(data_dir, "claude-code")

    assert consent.has_consent(data_dir, "claude-code")


def test_a_torn_vocabulary_is_never_written_over(tmp_path: Path):
    """Five hundred groups approved one at a time, replaced by one, with a 303 for "saved"."""
    from epicrisis.index.build import build_index

    data_dir, source_id = an_instance(tmp_path)
    indicators.upsert(data_dir, None, "Haemoglobin", ["гемоглобін"], "approved")
    indicators.upsert(data_dir, None, "Creatinine", ["креатинін"], "approved")
    # An index, so that the page gets as far as reading the vocabulary at all rather than stopping
    # at "nothing is indexed yet" — which is the state this used to be indistinguishable from.
    build_index(data_dir, [SourceRegistry(data_dir).get(source_id)])
    whole = (data_dir / layout.INDICATORS).read_text(encoding="utf-8")
    (data_dir / layout.INDICATORS).write_text(whole[: len(whole) // 2], encoding="utf-8")

    # Reading it is not "there is no vocabulary yet", which is what let the emptiness be written.
    with pytest.raises(state.Unreadable, match="indicators.json"):
        indicators.load(data_dir)
    with pytest.raises(state.Unreadable):
        indicators.save(data_dir, [])
    # And the copy from before the last change is there to put back: this is the one file under
    # data/ whose contents no code and no model can make again.
    kept = json.loads((data_dir / (layout.INDICATORS + ".previous")).read_text(encoding="utf-8"))
    assert [item["label"] for item in kept["indicators"]] == ["Haemoglobin"]

    page = dashboard(data_dir).get("/indicators")
    assert page.status_code == 503 and "indicators.json" in page.text
    assert "Every spelling a person approved is still in that file" in page.text
    assert "0 indicators" not in page.text  # what it used to say: "the work has not been done yet"


def test_an_index_that_is_there_and_will_not_open_is_answered_in_words(tmp_path: Path):
    """Including on the status page and the settings page: where a person goes when something is wrong."""
    data_dir, source_id = an_instance(tmp_path)
    broken = index_path(data_dir, source_id)
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_bytes(b"\x00" * 4096)

    with pytest.raises(state.Unreadable, match="index"):
        open_index(data_dir, source_id)

    client = dashboard(data_dir)
    # Which pages cannot work without the index and which stand on their own, named, and each
    # asserted with no condition in front of it. This was one loop whose assertions stood inside
    # "if this page answered 503" — the behaviour under test was the condition for testing it, so
    # six of the seven pages were held to nothing but the absence of two words. Had the guard
    # stopped working and those pages answered 200 over an archive that looked empty — the
    # confusion between "damaged" and "not done yet" that this whole thing exists to stop — the
    # test would have stayed green.
    cannot_work_without_it = ("/", "/?view=indicators", "/?view=types", "/indicators", "/search")
    stands_on_its_own = ("/documents", "/settings", "/review", "/ask", "/consent")
    for page in cannot_work_without_it:
        answer = client.get(page)
        assert answer.status_code == 503, page
        assert "cannot be read" in answer.text and "epicrisis index" in answer.text, page
        assert "Nothing that was read is lost" in answer.text, page
    for page in stands_on_its_own:
        answer = client.get(page)
        # These read the archive's own files rather than the index, and a damaged index is not a
        # reason to refuse them. What they must never do is answer with the two words.
        assert answer.status_code == 200, page
        assert "Internal Server Error" not in answer.text, page

    # The status page is the one that must stay on its feet whatever is wrong, because it is where
    # a person goes when something is: it says which step is broken rather than refusing as a whole.
    status = client.get("/status")
    assert status.status_code == 200
    assert "cannot be read" in status.text and "epicrisis index" in status.text


def test_an_index_cut_off_at_nothing_reads_as_one_that_was_never_built(tmp_path: Path):
    """A file of no bytes is an empty database to sqlite: it would answer "nothing" for everything."""
    data_dir, source_id = an_instance(tmp_path)
    empty = index_path(data_dir, source_id)
    empty.parent.mkdir(parents=True, exist_ok=True)
    empty.write_bytes(b"")

    with pytest.raises(IndexMissing):
        open_index(data_dir, source_id)


def test_an_index_built_by_another_version_is_refused_rather_than_read(tmp_path: Path):
    """The version was written into every index for six versions and read by nothing at all."""
    data_dir, source_id = an_instance(tmp_path)
    foreign = index_path(data_dir, source_id)
    foreign.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(foreign) as connection:
        connection.execute("CREATE TABLE meta (key TEXT, value TEXT)")
        connection.execute("CREATE TABLE documents (id TEXT)")
        connection.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION - 1),))

    with pytest.raises(state.Unreadable, match="another version"):
        open_index(data_dir, source_id)


def test_a_torn_file_of_checks_says_which_command_makes_it_again(tmp_path: Path):
    """Two pages of seven were dead and the cheapest command in the program was not named."""
    from epicrisis.validate import load_validation

    data_dir, source_id = an_instance(tmp_path)
    output = data_dir / "sources" / source_id
    output.mkdir(parents=True, exist_ok=True)
    (output / layout.VALIDATION).write_text('{"documents": [{"sha', encoding="utf-8")

    with pytest.raises(state.Unreadable, match="validation.json"):
        load_validation(output)

    answer = dashboard(data_dir).get("/status")
    assert answer.status_code == 503 and "epicrisis validate" in answer.text


def test_one_torn_line_is_counted_once_however_often_the_page_is_drawn(tmp_path: Path):
    """It was counted per pass over the file, so one lost record was reported as six, then eight."""
    path = tmp_path / layout.CLASSIFY
    path.write_text('{"page": 1}\n{"page": 2}\n{"page": ', encoding="utf-8")

    for _ in range(3):
        list(records.read_records(path))
    assert records.torn_lines()[str(path)] == 1

    # And the alarm goes out when the file is whole again, which it never did: only a restart did.
    path.write_text('{"page": 1}\n{"page": 2}\n', encoding="utf-8")
    list(records.read_records(path))
    assert str(path) not in records.torn_lines()


def test_a_lock_left_by_a_run_that_died_stops_holding_after_a_day(tmp_path: Path):
    """A pid is reused. After a reboot the number in an old lock belongs to some live daemon."""
    from epicrisis.runs import ABANDONED_AFTER_HOURS, Busy, holder, one_at_a_time

    lock = tmp_path / "index.lock"
    lock.write_text(json.dumps({"pid": 1, "started_at": "2020-01-01T00:00:00+00:00"}), encoding="utf-8")
    assert holder(lock) is None
    with one_at_a_time(lock, "Building this index"):
        pass

    # A lock taken a moment ago by something alive is still a lock, and it now names the file.
    lock.write_text(json.dumps({"pid": 1, "started_at": records.now()}), encoding="utf-8")
    assert holder(lock) == 1
    with pytest.raises(Busy, match="lock"):
        with one_at_a_time(lock, "Building this index"):
            pass

    # And the line between the two is a length of time, so it is asserted as behaviour rather than
    # as the number itself: a lock one hour short of it still holds, and one hour past it does not.
    an_hour = 3600
    lock.write_text(json.dumps({"pid": 1, "started_at": _ago(ABANDONED_AFTER_HOURS * an_hour - an_hour)}), encoding="utf-8")
    assert holder(lock) == 1
    lock.write_text(json.dumps({"pid": 1, "started_at": _ago(ABANDONED_AFTER_HOURS * an_hour + an_hour)}), encoding="utf-8")
    assert holder(lock) is None


def test_a_transcription_missing_from_disk_is_not_a_finished_step(tmp_path: Path):
    """The ledger said done, so the step drew green and 'update' would never read it again."""
    from epicrisis.web.app import _extract_step

    output = tmp_path / "output"
    (output / layout.EXTRACTED).mkdir(parents=True)
    inventory = [{"sha256": "a" * 64, "name": "labs.pdf", "path": "labs.pdf", "category": "pdf",
                  "pdf": {"text_chars_per_page": [3000]}}]  # fmt: skip
    (output / layout.CLASSIFY).write_text(json.dumps(
        {"file_sha256": "a" * 64, "page": 1, "route": "text", "doc_type": "lab_panel",
         "page_role": "first", "language": "uk", "legible": True, "confidence": 0.9}) + "\n", encoding="utf-8")  # fmt: skip
    (output / layout.LEDGER).write_text(json.dumps(
        {"step": "extract", "file_sha256": "a" * 64, "pages": [1], "model": "m",
         "prompt_version": "0", "status": "done", "at": records.now()}) + "\n", encoding="utf-8")  # fmt: skip

    step = _extract_step(inventory, output)

    assert step["state"] == "partial"
    assert "on disk" in step["title"]
    assert "--redo" in step["note"]  # the way out: one document, one call of a model


def test_a_refused_code_says_when_the_clock_is_what_is_wrong(tmp_path: Path):
    """It looked exactly like guessing, and five honest tries put the owner in a wait."""
    import time

    from epicrisis.mcp_lock import Lock, Locked, code_at, new_secret

    secret = new_secret()
    lock = Lock(secret=secret)
    now = time.time()

    with pytest.raises(Locked, match="clock"):
        lock.unlock(code_at(secret, now + 300), now=now)
    # Nothing is opened by saying so, and a code that is nobody's is still answered as before.
    lock.wrong = []
    with pytest.raises(Locked, match="does not fit"):
        lock.unlock("000000", now=now)


def test_the_lock_commands_refuse_to_invent_a_data_folder(tmp_path: Path):
    """"The lock is off." was printed over a ./data made beside whoever ran it, while it stayed on."""
    code, said = on_the_command_line("mcp-lock", "off", "--data-dir", str(tmp_path / "not-an-instance"))

    assert code == 2 and "no data folder" in said
    assert not (tmp_path / "not-an-instance").exists()


def test_the_lock_commands_say_which_folder_they_acted_on(tmp_path: Path):
    data_dir, _ = an_instance(tmp_path)

    code, said = on_the_command_line("mcp-lock", "off", "--data-dir", str(data_dir))

    assert code == 0 and str(data_dir) in said


def test_a_backup_takes_what_nothing_can_make_again_and_leaves_the_rest(tmp_path: Path):
    """There was no backup command, and the README said the whole of data/ could be rebuilt."""
    from epicrisis.backup import back_up

    data_dir, source_id = an_instance(tmp_path)
    output = data_dir / "sources" / source_id
    output.mkdir(parents=True, exist_ok=True)
    (output / layout.CORRECTIONS).write_text('{"field": "value_as_printed"}\n', encoding="utf-8")
    (output / layout.JUDGEMENTS).write_text('{"verdict": "noise"}\n', encoding="utf-8")
    indicators.upsert(data_dir, None, "Haemoglobin", ["гемоглобін"], "approved")
    index_path(data_dir, source_id).write_bytes(b"an index, which rebuilds in seconds")

    copied = back_up(data_dir, tmp_path / "kept")

    took = {Path(name).name for name in copied.took}
    assert {layout.CORRECTIONS, layout.JUDGEMENTS, layout.INDICATORS} <= took
    assert not any(name.startswith("index-") for name in took)
    assert (tmp_path / "kept" / "sources" / source_id / layout.CORRECTIONS).exists()


def test_a_backup_refuses_to_write_inside_what_it_is_copying(tmp_path: Path):
    from epicrisis.backup import back_up

    data_dir, _ = an_instance(tmp_path)
    with pytest.raises(ValueError, match="inside"):
        back_up(data_dir, data_dir / "kept")


def test_no_temporary_file_is_left_behind_when_a_write_fails(tmp_path: Path, monkeypatch):
    """One dead .tmp per press of a button, on the very disk somebody was making room on."""
    from epicrisis import runs

    def the_disk_is_full(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(runs, "put_in_place", the_disk_is_full)
    path = tmp_path / "settings.json"
    with pytest.raises(OSError):
        runs.write_whole(path, "{}\n")

    assert list(tmp_path.glob("*.tmp")) == []
    assert not path.exists()  # and the file it would have replaced is untouched


def test_a_full_disk_is_a_page_and_not_internal_server_error(tmp_path: Path):
    """Six buttons answered with those two words while every page looked perfectly healthy."""
    data_dir, _ = an_instance(tmp_path)
    client = dashboard(data_dir)

    app_under_test = client.app

    @app_under_test.get("/a-write-that-meets-a-full-disk")
    def _write() -> None:
        raise OSError(28, "No space left on device")

    answer = client.get("/a-write-that-meets-a-full-disk")

    assert answer.status_code == 507
    assert "no space left" in answer.text.lower()
    assert "Nothing was changed" in answer.text
    assert "Internal Server Error" not in answer.text


def test_no_space_is_told_from_any_other_trouble_with_a_file():
    import errno

    assert state.no_space(OSError(errno.ENOSPC, "No space left on device"))
    assert not state.no_space(OSError(errno.EACCES, "Permission denied"))


def test_a_copy_is_never_half_written_over_the_one_already_there(tmp_path: Path, monkeypatch):
    """shutil.copy2 empties the target first, and a full disk then leaves half a file where a whole
    one was. The two places this program copies are the version kept beside a person's own work and
    the backup of it — both destroyed the last good copy exactly when trouble arrived."""
    from epicrisis import runs

    whole = tmp_path / "corrections.jsonl"
    whole.write_text("one\ntwo\nthree\n", encoding="utf-8")
    already_there = tmp_path / "kept" / "corrections.jsonl"
    already_there.parent.mkdir()
    already_there.write_text("what was there before\n", encoding="utf-8")

    def the_disk_is_full(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(runs.shutil, "copyfile", the_disk_is_full)
    with pytest.raises(OSError):
        runs.copy_whole(whole, already_there)

    assert already_there.read_text(encoding="utf-8") == "what was there before\n"
    assert list(already_there.parent.glob("*.tmp")) == []


def test_a_backup_can_be_put_back(tmp_path: Path):
    """The folder each archive's work sits in is named by four random bytes, written down in one file.

    Without that file the copy is unusable: a person who has lost their data directory adds the
    archive again, is given a new id, and their corrections sit in a folder nothing reads. Of the
    five kinds of their own work, one came back.
    """
    from epicrisis.backup import back_up

    data_dir, source_id = an_instance(tmp_path)
    output = data_dir / "sources" / source_id
    output.mkdir(parents=True, exist_ok=True)
    (output / layout.CORRECTIONS).write_text('{"field": "value_as_printed"}\n', encoding="utf-8")

    back_up(data_dir, tmp_path / "kept")

    kept = json.loads((tmp_path / "kept" / layout.SOURCES).read_text(encoding="utf-8"))
    assert [entry["id"] for entry in kept] == [source_id], "the copy says which folder is whose"
    assert (tmp_path / "kept" / "sources" / source_id / layout.CORRECTIONS).exists()


def test_a_backup_refuses_to_write_inside_a_folder_of_documents(tmp_path: Path):
    """Those folders are only ever read, which everything else in this program already refuses to
    break. One mistyped path here would put one person's corrections and conversations inside
    another person's folder of documents, where the next walk of it would find them."""
    from epicrisis.backup import back_up

    archive = tmp_path / "archive"
    data_dir, _ = an_instance(tmp_path, folder=archive)

    with pytest.raises(ValueError, match="only ever read"):
        back_up(data_dir, archive)
    with pytest.raises(ValueError, match="only ever read"):
        back_up(data_dir, archive / "somewhere" / "inside")
    assert not (archive / "somewhere").exists()


def test_the_lock_keeps_counting_when_its_file_cannot_be_written(tmp_path: Path):
    """The file is the truth and is read back on every attempt, so a file that can be read and not
    written empties the wait: each wrong code is written nowhere and read back as nothing."""
    import time

    from epicrisis.mcp_lock import Lock, Locked, new_secret

    kept = tmp_path / "wrong.json"
    kept.write_text("[]", encoding="utf-8")
    kept.parent.chmod(0o555)
    try:
        lock = Lock(secret=new_secret(), remembers=kept)
        now = time.time()
        waited = 0
        for attempt in range(8):
            try:
                lock.unlock("000000", now=now + attempt)
            except Locked as refused:
                waited += "Too many" in str(refused)
        assert waited, "guessing is not slowed down at all while the file cannot be written"
    finally:
        kept.parent.chmod(0o755)


def test_a_step_says_what_it_found_beside_the_scan_and_not_instead_of_it(tmp_path: Path):
    """"1 document counted as read has no transcription on disk" was displaced by "3 duplicates".

    The neutral note won because it was written first, so on every archive holding a duplicate —
    which is nearly all of them — the sentence about values that are gone never appeared.
    """
    from epicrisis.inventory.report import Summary
    from epicrisis.sources import Source
    from epicrisis.web.app import _source_row

    scan_found_duplicates = Summary()
    scan_found_duplicates.paths_by_hash["same"] = ["one.pdf", "two.pdf", "three.pdf"]
    a_step_with_something_to_say = {"state": "partial", "label": "", "title": "",
                                    "note": "1 document counted as read has no transcription on disk",
                                    "alert": True}  # fmt: skip
    plain = {"state": "done", "label": "", "title": ""}

    row = _source_row(Source(id="a1", name="x", path="/tmp", added_at="", owner="Somebody"),
                      scan_found_duplicates, {"state": "done"}, plain,
                      a_step_with_something_to_say, plain, plain)  # fmt: skip

    assert "duplicates" in row["note"], "the scan's own note still stands"
    assert "no transcription on disk" in row["note"], "and so does the step's"
    assert row["alert"] is True


def test_a_finding_of_the_whole_archive_reaches_the_document_holding_its_page(tmp_path: Path):
    """A rule may point at the page where the thing it found stands, which is rarely the first."""
    from collections import Counter

    from epicrisis.rules.subjects import Found
    from epicrisis.validate import _the_document_of

    two_forms_in_one_scan = [
        {"file_sha256": "a" * 64, "pages": [1, 2], "findings": Counter()},
        {"file_sha256": "a" * 64, "pages": [3, 4], "findings": Counter()},
    ]

    assert [doc["pages"] for doc in _the_document_of(two_forms_in_one_scan, Found("a" * 64, 2, None, ""))] == [[1, 2]]
    assert [doc["pages"] for doc in _the_document_of(two_forms_in_one_scan, Found("a" * 64, 3, None, ""))] == [[3, 4]]


def test_what_could_not_be_read_is_said_by_whoever_reports_the_numbers(tmp_path: Path):
    """The count was asked for in one place, a page of the dashboard, in another process.

    From a terminal an archive simply became smaller — forty-three files, then forty-two — and
    every number agreed with every other, which is what a silent loss looks like.
    """
    from epicrisis import records
    from epicrisis.records import torn_under

    output = tmp_path / "sources" / "abc123"
    output.mkdir(parents=True)
    (output / layout.INVENTORY).write_text('{"sha256": "aa"}\n{"sha256": "b\n', encoding="utf-8")
    list(records.read_records(output / layout.INVENTORY))

    assert torn_under(output) == {layout.INVENTORY: 1}
    assert torn_under(tmp_path / "somewhere-else") == {}


def test_one_archive_index_does_not_carry_another_archive_printed_words(tmp_path: Path):
    """Values never crossed between archives; the words a laboratory printed did.

    The vocabulary is one file for the whole instance, which is right — a person keeping three
    people's records approves "Cystatin C" once. Copied whole into every index, it let whoever
    holds one person's archive read the printed wording of another person's forms.
    """
    import sqlite3

    from epicrisis import indicators
    from epicrisis.index.build import build_index, index_path

    data_dir, mine = an_instance(tmp_path)
    (tmp_path / "theirs").mkdir(exist_ok=True)
    theirs = SourceRegistry(data_dir).add(str(tmp_path / "theirs"), owner="Somebody Else").id
    indicators.upsert(data_dir, None, "Ferritin", ["ферритин", "ferritina"], "approved")

    for source in SourceRegistry(data_dir).list():
        build_index(data_dir, [source])

    for source_id in (mine, theirs):
        with sqlite3.connect(f"file:{index_path(data_dir, source_id)}?mode=ro", uri=True) as db:
            rows = db.execute("SELECT label, names FROM indicators").fetchall()
            assert [label for label, _ in rows] == ["Ferritin"], "the label stays: a page must answer for it"
            assert json.loads(rows[0][1]) == [], "no spelling this archive has never printed"


def test_a_locked_server_over_the_network_does_not_name_whose_archive_it_is(tmp_path: Path):
    """The instructions are handed over in the answer to `initialize`, which needs no code at all.

    So on a locked server this sentence told whoever held the address the one fact the lock exists
    to keep — while every refusal a few lines away carefully did not.
    """
    from epicrisis.mcp_server import build_server
    from epicrisis.settings import set_mcp_lock

    data_dir, _ = an_instance(tmp_path)
    SourceRegistry(data_dir).set_owner(SourceRegistry(data_dir).list()[0].id, "Ирина Петровна")

    set_mcp_lock(data_dir, True)
    assert "Ирина" not in (build_server(data_dir, over_the_network=True).instructions or "")
    # Over stdio the lock does not apply and whoever started it already has the files.
    assert "Ирина" in (build_server(data_dir, over_the_network=False).instructions or "")
    set_mcp_lock(data_dir, False)
    assert "Ирина" in (build_server(data_dir, over_the_network=True).instructions or "")


def test_a_code_refused_because_the_clock_drifted_does_not_spend_a_try(tmp_path: Path):
    """Counted, five honest attempts ran out and the sixth said "Too many wrong codes" with no word
    about the clock — the very state the clock message exists to get somebody out of."""
    import time

    from epicrisis.mcp_lock import Lock, Locked, code_at, new_secret

    secret = new_secret()
    lock = Lock(secret=secret)
    now = time.time()

    said = []
    for attempt in range(8):
        try:
            lock.unlock(code_at(secret, now + 300 + attempt * 31), now=now + attempt)
        except Locked as refused:
            said.append(str(refused))

    assert all("out of step with this server's clock" in one for one in said)
    assert not any("Too many" in one for one in said)
    # A code that is nobody's still counts, and still ends in a wait.
    for attempt in range(6):
        with pytest.raises(Locked):
            lock.unlock("000000", now=now + 100 + attempt)
    assert lock.wrong, "a guess is still a guess"


def test_a_path_that_is_not_ascii_is_a_wrong_path_and_not_a_fault():
    """compare_digest raises on anything but ASCII, which happened before the request was written
    down: one accented letter in the address and a scanner got 500 and a hint that something is
    there, with no record kept of having been asked."""
    import hmac

    secret_path = "/mcp/" + "a" * 43
    asked_for = "/mcp/ä"

    assert not asked_for.isascii()
    with pytest.raises(TypeError):
        hmac.compare_digest(asked_for, secret_path)


def test_a_typed_address_while_the_list_of_archives_is_torn_answers_about_the_file(tmp_path: Path):
    """The page that says "not here" was the one page the 503 did not reach.

    Its header asks two questions of the registry, and only one of them was guarded, so a typed
    address or an old bookmark — at the very moment the file was torn — answered with the two words
    this whole thing exists to remove. /favicon.ico among them, which a browser asks for by itself
    on every page, filling the log with tracebacks exactly when somebody is reading it.
    """
    data_dir, _ = an_instance(tmp_path)
    (data_dir / layout.SOURCES).write_text('[{"id": "aa11bb22", "name": "x", "pa', encoding="utf-8")

    client = dashboard(data_dir)
    for page in ("/statuz", "/no-such-page", "/favicon.ico", "/review/nosuch", "/tests/nothing"):
        answer = client.get(page)
        # The trouble matters more than the address: "no page is at that address" is the smaller of
        # two true things, and the one that helps nobody.
        assert answer.status_code == 503, page
        assert layout.SOURCES in answer.text and "Internal Server Error" not in answer.text, page


def test_the_page_about_a_torn_list_of_archives_offers_no_way_back_to_itself(tmp_path: Path):
    """Its one button led to the status page, which in this state is this same page.

    And the way out it described was a description rather than an act: "repair that file, or move it
    aside and add the folders again" — the second of which is the costliest step in the program,
    offered beside the cheapest as though they were alternatives.
    """
    data_dir, _ = an_instance(tmp_path)
    (data_dir / layout.SOURCES).write_text("{ not json", encoding="utf-8")

    page = dashboard(data_dir).get("/").text

    assert f"mv {layout.SOURCES}.previous {layout.SOURCES}" in page
    assert "is the last resort" in page and "read by a model from nothing" in page
    assert "nowhere in this interface to go" in page
    assert 'class="btn"' not in page  # not a button that leads back to this same page


def test_a_transcription_that_will_not_parse_is_named_and_the_rest_is_whole(tmp_path: Path):
    """The most expensive files in the instance were the ones nothing answered for.

    A rename can reach the journal before the contents do, so a machine that loses power leaves an
    empty file where a whole one was. The card of that document answered with the two words, and
    'epicrisis index' and 'epicrisis validate' each ended in a hundred and twenty lines of traceback
    that never named the file.
    """
    from epicrisis.extract.run import extracted_path, load_extracted

    data_dir, source_id = an_instance(tmp_path)
    extracted = data_dir / "sources" / source_id / layout.EXTRACTED
    extracted.mkdir(parents=True, exist_ok=True)
    sha = "b" * 64
    extracted_path(extracted, sha).write_bytes(b"")

    with pytest.raises(state.Unreadable) as broken:
        load_extracted(extracted, sha)

    # Named as a person would look for it, and never above the data directory.
    assert broken.value.file.startswith(layout.EXTRACTED + "/") and str(tmp_path) not in str(broken.value)
    assert "Every other document is whole" in broken.value.safe
    assert "epicrisis extract" in broken.value.mend and layout.REPLACED in broken.value.mend
    # A document nobody ever read is not this, and still answers with nothing.
    assert load_extracted(extracted, "c" * 64) is None


def test_a_step_already_running_is_a_page_and_names_no_path(tmp_path: Path):
    """Every step here takes a lock, and the commands this dashboard recommends take the same ones.

    Editing the indicators is six buttons on a page and four commands in a terminal, all through
    indicators.lock. Pressing a button while one of those commands held it answered with the words
    Internal Server Error, and the sentence naming the step and the lock went into the server's log
    instead — with the full path of the lock file in it.
    """
    data_dir, _ = an_instance(tmp_path)
    (data_dir / "indicators.lock").write_text(
        json.dumps({"pid": 1, "started_at": records.now()}), encoding="utf-8")

    refused = dashboard(data_dir).post("/indicators", data={"action": "save", "label": "Haemoglobin",
                                                            "names": "Hb"})  # fmt: skip

    assert refused.status_code == 409
    assert "already running" in refused.text and "Internal Server Error" not in refused.text
    # The lock is named as a person would look for it, inside the data directory, and no further up.
    assert "indicators.lock" in refused.text and str(tmp_path) not in refused.text


def test_a_full_disk_says_the_same_thing_on_the_button_that_runs_the_checks(tmp_path: Path, monkeypatch):
    """Seven buttons answered with the page about the disk and the eighth did not.

    Its own guard stood in front of the handler for it: a broad except, there because a rule's
    message can quote a document, caught the full disk too and answered "That is not in this archive"
    and the word OSError — a heading that was a lie, to somebody whose archive was open in front of
    them, about a disk that was never mentioned.
    """
    from epicrisis.web import app as web

    data_dir, source_id = an_instance(tmp_path)
    output = data_dir / "sources" / source_id
    output.mkdir(parents=True, exist_ok=True)
    (output / layout.CLASSIFY).write_text("", encoding="utf-8")

    def a_full_disk(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(web, "validate_source", a_full_disk)
    answer = dashboard(data_dir).post(f"/sources/{source_id}/validate")

    assert answer.status_code == 507
    assert "no space left" in answer.text.lower() and "Nothing was changed" in answer.text
    assert "That is not in this archive" not in answer.text
    assert "OSError" not in answer.text and "Internal Server Error" not in answer.text

    # Anything else that stops the checks still says so on a page, with its own heading and the
    # kind of failure — the type only, because a rule's own words can quote a document.
    def something_else(*_args, **_kwargs):
        raise KeyError("a rule's own words, which may quote a page")

    monkeypatch.setattr(web, "validate_source", something_else)
    other = dashboard(data_dir).post(f"/sources/{source_id}/validate")

    assert other.status_code == 500 and "The checks could not be run" in other.text
    assert "KeyError" in other.text and "quote a page" not in other.text


def test_an_earlier_reading_of_pages_grouped_differently_is_still_named(tmp_path: Path):
    """A regrouping is the commonest reason anything is in replaced/ at all, and it was the one case
    the card could not see: it compared the list of pages for equality, and a regrouping changes that
    list by definition. No other page, command or line of the README names that folder, so a card
    that stays silent leaves nowhere to learn the file is there."""
    from epicrisis.web.documents import _earlier_readings_here

    data_dir, source_id = an_instance(tmp_path)
    output = data_dir / "sources" / source_id
    (output / layout.REPLACED).mkdir(parents=True, exist_ok=True)
    sha = "d" * 64
    (output / layout.REPLACED / f"{sha}.jsonl").write_text("".join(json.dumps(line) + "\n" for line in [
        {"document": {"pages": [1, 2]}, "replaced_at": "2026-09-01T10:00:00+00:00", "by": {"model": "a-newer-model"}},
        {"document": {"pages": [7]}, "replaced_at": "2026-08-01T10:00:00+00:00", "by": {"model": "a-newer-model"}},
    ]), encoding="utf-8")  # fmt: skip

    said = _earlier_readings_here(output, sha, (1,))

    # The reading of pages 1-2 touches page 1, so it belongs to this card; the one of page 7 does not.
    assert said["count"] == 1 and said["regrouped"] == ["1–2"]
    assert said["when"] == "2026-09-01" and said["by"] == "a-newer-model"
    # And where the file is, in the words this program uses for that place. It used to say "inside
    # this archive's folder", which in the language of this program is the folder of scans — the one
    # nothing of this program is ever written into.
    assert said["file"] == f"sources/{source_id}/{layout.REPLACED}/{sha}.jsonl"
    # A reading of pages nothing of this document touches is not this document's.
    assert _earlier_readings_here(output, sha, (9,)) == {}


def test_reaching_past_the_provider_is_its_own_agreement(tmp_path: Path):
    """The one place in this program that goes anywhere but Anthropic had the provider's own name.

    settle-names and look-up-names send printed test names to a search engine and to whatever sites
    it returns — no values, no dates, but a set of rare test names says what somebody is ill with.
    Consent is checked by the name of the destination, and that backend carried the same name as the
    reading of documents, so an agreement whose page says "To Anthropic, through Claude Code" also
    let names out to the web. The sibling backend on an API key has always had a name of its own.
    """
    from epicrisis import consent
    from epicrisis.classify.backend import ClaudeCodeBackend
    from epicrisis.datesearch import ClaudeCodeDateSearch
    from epicrisis.indicator_web_check import ApiWebCheckBackend, WebCheckBackend

    data_dir, _ = an_instance(tmp_path)
    consent.record_consent(data_dir, ClaudeCodeBackend.name)

    # Reading documents is agreed to; reaching the web is not, on either engine.
    assert consent.has_consent(data_dir, ClaudeCodeBackend.name)
    assert not consent.has_consent(data_dir, WebCheckBackend.name)
    assert not consent.has_consent(data_dir, ApiWebCheckBackend.name)
    # And a date read out of a document goes to the provider, so it shares that destination.
    assert ClaudeCodeDateSearch.name == ClaudeCodeBackend.name
    assert WebCheckBackend.name != ClaudeCodeBackend.name


def test_a_missing_system_library_is_a_sentence_and_not_the_whole_program(monkeypatch):
    """python-magic is a wrapper over libmagic, and the wheel does not carry the library.

    Ubuntu has it; macOS and Windows do not, and the README sends a person on macOS to install
    nothing but Python. The import stood at the top of a module the command line loads on startup,
    so on such a machine everything answered with a traceback before this program said a word of
    its own — `epicrisis demo`, `epicrisis serve`, and `epicrisis --help` itself.
    """
    import builtins

    from epicrisis.inventory import probes

    real = builtins.__import__

    def without_libmagic(name, *rest):
        if name == "magic":
            raise ImportError("failed to find libmagic.  Check your installation")
        return real(name, *rest)

    monkeypatch.setattr(builtins, "__import__", without_libmagic)
    with pytest.raises(probes.UnsupportedFormat) as said:
        probes.detect_mime(Path("README.md"))

    # Named, with the one thing to install on each of the three kinds of machine.
    assert "libmagic" in str(said.value)
    assert "brew install libmagic" in str(said.value) and "apt install libmagic1" in str(said.value)
    assert "python-magic-bin" in str(said.value)


def test_a_backup_counts_what_it_carried_and_names_nothing_else(tmp_path: Path):
    """"Copied 2 files", and three names under it.

    chats/ exists as soon as this instance is asked anything and holds nothing before that. An empty
    folder was listed among what had gone into the copy while the count above it was one lower, and
    on the one command whose whole job is to say whether what cannot be rebuilt has left this
    machine, a count that does not add up to the list costs more than it looks. An empty one belongs
    in the line that says what this instance does not hold yet.
    """
    from epicrisis.backup import back_up

    data_dir, source_id = an_instance(tmp_path)
    output = data_dir / "sources" / source_id
    output.mkdir(parents=True, exist_ok=True)
    (output / layout.CORRECTIONS).write_text('{"field": "value_as_printed"}\n', encoding="utf-8")
    (data_dir / layout.CHATS).mkdir(parents=True, exist_ok=True)  # asked nothing yet

    copied = back_up(data_dir, tmp_path / "kept")

    assert copied.files == len(copied.took), f"{copied.files} files, {len(copied.took)} names"
    assert layout.CHATS not in {Path(name).name for name in copied.took}
    assert layout.CHATS in copied.missing

    # And with a conversation in it, it is carried and named like everything else.
    (data_dir / layout.CHATS / "one.json").write_text("{}", encoding="utf-8")
    again = back_up(data_dir, tmp_path / "kept-again")
    assert layout.CHATS in {Path(name).name for name in again.took} and again.files == len(again.took)


def _a_document_with_two_lines_alike(tmp_path: Path) -> tuple[Path, str, tuple, list[dict]]:
    """One page printing the same name and the same value twice, in different units.

    A panel giving a count and a percentage, a range printed in two units, a summary repeating a
    line of the table above: on the live archive 46 groups of lines shared the key a correction was
    filed under, and eleven of those groups differed by the printed unit or the printed range.
    """
    data_dir, source_id = an_instance(tmp_path)
    output = data_dir / "sources" / source_id
    output.mkdir(parents=True, exist_ok=True)
    line = lambda unit, reference: {  # noqa: E731
        "name_as_printed": "Neutrophils", "value_as_printed": "2,5", "unit_as_printed": unit,
        "reference_as_printed": reference, "value_kind": "quantitative",
        "provenance": {"page": 1, "snippet": ""},
    }  # fmt: skip
    return output, "a" * 64, (1,), [line("10^9/l", "2,0-7,0"), line("%", "45-70")]


def test_one_correction_does_not_land_on_two_printed_lines(tmp_path: Path):
    """The key was the page, the name and the value, and a page prints all three twice.

    A person opens the line in percent and puts its unit right; the line in absolute numbers is
    rewritten with it and marked corrected by a person, on a page they never opened. Worse the
    other way round: marking one line "not a value" took its twin out of the archive too, which is
    a value gone from every chart and every answer with nothing said.
    """
    from epicrisis.corrections import as_a_person_left_it, line_key, load_value_corrections, set_value

    output, sha256, pages, lines = _a_document_with_two_lines_alike(tmp_path)
    set_value(output, sha256, list(pages), line_key(lines[1]), {"unit_as_printed": "per cent"})

    left = as_a_person_left_it(lines, sha256, pages, load_value_corrections(output))
    assert [item["unit_as_printed"] for item in left] == ["10^9/l", "per cent"]
    assert "corrected_by_a_person" not in left[0], "a line nobody opened was marked as corrected"

    # And the same for a line marked as not a value at all: one goes, the other stays.
    set_value(output, sha256, list(pages), line_key(lines[0]), None, removed=True)
    left = as_a_person_left_it(lines, sha256, pages, load_value_corrections(output))
    assert [item["unit_as_printed"] for item in left] == ["per cent"]


def test_a_correction_written_before_the_key_was_widened_still_finds_its_line(tmp_path: Path):
    """Corrections are a person's own work and outlive the shape of the key they were filed under.

    Where the old short key names one line, it still applies. Where it names two, it applies to
    neither and is counted among the corrections that no longer match a line — which is a sentence
    on the page, and better than two lines quietly rewritten from one decision.
    """
    from epicrisis.corrections import as_a_person_left_it, load_value_corrections, set_value, value_key

    output, sha256, pages, lines = _a_document_with_two_lines_alike(tmp_path)
    alone = {"name_as_printed": "Sodium", "value_as_printed": "140", "unit_as_printed": "mmol/l",
             "reference_as_printed": "136-145", "value_kind": "quantitative",
             "provenance": {"page": 1, "snippet": ""}}  # fmt: skip

    set_value(output, sha256, list(pages), value_key(1, "Sodium", "140"), {"unit_as_printed": "mmol/L"})
    set_value(output, sha256, list(pages), value_key(1, "Neutrophils", "2,5"), {"unit_as_printed": "no"})

    left = as_a_person_left_it([*lines, alone], sha256, pages, load_value_corrections(output))
    assert left[-1]["unit_as_printed"] == "mmol/L", "an old correction naming one line still applies"
    assert [item["unit_as_printed"] for item in left[:2]] == ["10^9/l", "%"], "and one naming two applies to neither"


def test_a_person_can_take_off_a_unit_the_form_never_printed(tmp_path: Path):
    """A model invents a unit, a person clears the field, and the field comes back.

    Empty fields were dropped from a correction as though nothing had been said, so the one way to
    take a wrong unit or a wrong range off a line did nothing — and the line still wore the badge
    saying a person had corrected it, over the model's own word.
    """
    from epicrisis.corrections import as_a_person_left_it, line_key, load_value_corrections, set_value

    output, sha256, pages, lines = _a_document_with_two_lines_alike(tmp_path)
    set_value(output, sha256, list(pages), line_key(lines[0]), {"unit_as_printed": "", "reference_as_printed": ""})

    left = as_a_person_left_it(lines, sha256, pages, load_value_corrections(output))
    assert left[0]["unit_as_printed"] == "" and left[0]["reference_as_printed"] == ""
    assert left[0]["corrected_by_a_person"], "and it is their correction, not the model's word"

def test_a_key_in_a_env_beside_the_data_directory_is_read_where_the_page_says_it_is(tmp_path: Path, monkeypatch):
    """The settings page said ".env beside the data directory", and that was the one place unread.

    It was read inside the data directory, or beside the program. On a checkout the two are the
    same folder, so nobody noticed. An organisation keeps the data somewhere of its own — a mounted
    volume, /srv/epicrisis/data — and there the file a person put exactly where the page told them
    to was read by nothing: the engine stayed "not ready", naming the key and not the file.
    """
    from epicrisis import engines

    monkeypatch.delenv(engines.KEY_NAME, raising=False)
    monkeypatch.setattr(engines, "PROJECT_ROOT", tmp_path / "no-checkout-here")
    data_dir = tmp_path / "somewhere-of-its-own" / "data"
    data_dir.mkdir(parents=True)
    (data_dir.parent / ".env").write_text(f"{engines.KEY_NAME}=sk-beside-the-archive\n", encoding="utf-8")

    assert engines.key_for(data_dir) == "sk-beside-the-archive"
    assert engines.what_it_needs("anthropic-api", data_dir) is None

    # And the words say both places, because now both are read.
    (data_dir.parent / ".env").unlink()
    said = engines.what_it_needs("anthropic-api", data_dir)
    assert "in the data directory or beside it" in said, said
    # Inside it is read as it always was: nobody's key moves because this was fixed.
    (data_dir / ".env").write_text(f"{engines.KEY_NAME}=sk-inside\n", encoding="utf-8")
    assert engines.key_for(data_dir) == "sk-inside"


def test_a_page_that_prints_a_command_names_the_instance_it_belongs_to(tmp_path: Path):
    """A line copied off a page acted on whatever "data" meant beside the person's own shell.

    Which, for anybody who had run the demo and then stood in the program's folder, was another
    instance — or none, and then one was made and the page's advice reported as done. The lock's
    own commands on the settings page were given the folder for this reason; the rest were not.
    """
    gone = tmp_path / "on-a-disk-that-did-not-mount"
    data_dir, source_id = an_instance(tmp_path, folder=gone)
    gone.rmdir()
    client = dashboard(data_dir)

    page = client.get("/status")
    assert page.status_code == 200
    # The one way to keep every reading of an archive whose folder moved, and it is typed in a
    # terminal: without the folder it moves the archive of whatever instance the person stands in.
    assert f"sources set-path {source_id} /the/new/folder --data-dir {data_dir}" in page.text

    # The folder picker's refusal names the typed command as the one way to add a disk it will not
    # offer. Run in the wrong folder, that command adds the archive where nothing reads it.
    refused = client.get("/browse", params={"path": "/proc"})
    assert refused.status_code == 403
    assert f"--data-dir {data_dir}" in refused.json()["error"], refused.json()


def test_a_record_written_after_a_torn_line_is_not_glued_to_it(tmp_path: Path):
    """A write cut off by a full disk leaves a line with no newline, and the next one joined it.

    Two records became one unreadable line: the torn one, which was already lost, and the one a
    person had just typed — and the count of torn lines did not move either, there being no new
    line to count. They pressed Save, got the card back with the old value on it, and were told
    nothing at all.
    """
    from epicrisis import records

    path = tmp_path / "corrections.jsonl"
    records.append_line(path, {"first": "a value a person corrected"})
    records.append_line(path, {"second": "another one"})
    whole = path.read_text(encoding="utf-8")
    path.write_text(whole[: len(whole) - 8], encoding="utf-8")  # the second write, cut off
    assert not path.read_text(encoding="utf-8").endswith("\n")

    records.append_line(path, {"third": "typed after the trouble"})

    read = list(records.read_records(path))
    assert read == [{"first": "a value a person corrected"}, {"third": "typed after the trouble"}]
    assert records.torn_lines().get(str(path)) == 1, "the torn line is still counted, and only it"


def test_a_backup_does_not_put_an_unreadable_file_over_the_whole_copy_of_it(tmp_path: Path):
    """The one way back from a file that has gone wrong, destroyed by the command that keeps it.

    A backup copies what is there without reading it. A file of the instance that stopped parsing —
    a write cut off by a full disk — was copied over the last whole copy of itself, and the command
    printed "Copied 5 files" with that name among them. Without a second copy kept by hand, the
    thing the command exists for was gone, in silence, at the moment it was needed.
    """
    from epicrisis.backup import UNREADABLE_SUFFIX, back_up

    data_dir, source_id = an_instance(tmp_path)
    output = data_dir / "sources" / source_id
    output.mkdir(parents=True, exist_ok=True)
    (output / layout.CORRECTIONS).write_text('{"field": "value_as_printed"}\n', encoding="utf-8")
    indicators.upsert(data_dir, None, "Haemoglobin", ["гемоглобін"], "approved")

    kept = tmp_path / "kept"
    back_up(data_dir, kept)
    whole = (kept / layout.INDICATORS).read_text(encoding="utf-8")
    assert json.loads(whole), "the first copy is a copy of a readable file"

    # Now the instance's own file goes wrong, and the copy is taken again into the same folder.
    torn = (data_dir / layout.INDICATORS).read_text(encoding="utf-8")
    (data_dir / layout.INDICATORS).write_text(torn[: len(torn) // 2], encoding="utf-8")
    again = back_up(data_dir, kept)

    assert (kept / layout.INDICATORS).read_text(encoding="utf-8") == whole, "the whole copy was kept"
    assert (kept / (layout.INDICATORS + UNREADABLE_SUFFIX)).exists(), "and the broken one is beside it"
    assert layout.INDICATORS in " ".join(again.unreadable), "and the command says which file"
    assert layout.INDICATORS not in " ".join(again.took), "and does not count it among what it carried"


def test_a_torn_record_of_a_scan_does_not_take_down_the_page_that_says_what_to_do(tmp_path: Path):
    """The one reading of a JSON file here that caught only a missing file.

    inventory.status.json says how far the last look through a folder got. Cut off by a hand, by an
    interrupted copy of data/ carried to another machine, or by a file system that lost a write, it
    answered json.loads with a JSONDecodeError that nothing caught — and the status page, which
    holds the names of the archives, the folder paths, Rescan, Start again, Take off the list, Add
    an archive and the panel of the lock, came back as the words Internal Server Error. The way out
    was to delete that one file, and no page, no message and no README said so.
    """
    data_dir, source_id = an_instance(tmp_path)
    output = data_dir / "sources" / source_id
    output.mkdir(parents=True, exist_ok=True)
    (output / layout.INVENTORY_STATUS).write_text('{"state": "run', encoding="utf-8")  # cut off

    client = dashboard(data_dir)
    answer = client.get("/status")

    assert answer.status_code == 200 and "Internal Server Error" not in answer.text
    # Which file, what is not lost, and the act that puts it right — the same three things the page
    # about any other file of this instance carries.
    assert layout.INVENTORY_STATUS in answer.text
    assert "Nothing read from the archive is lost" in answer.text
    assert "Rescan to write it again" in answer.text
    # And the folder is not reported as being looked through right now, which is what a status of
    # "no scan has ever run" would have said on every other page.
    assert client.get("/").status_code == 200

    # Pressing Rescan is the mending, and it leaves the file readable again.
    assert client.post(f"/sources/{source_id}/inventory", follow_redirects=False).status_code == 303
    assert json.loads((output / layout.INVENTORY_STATUS).read_text(encoding="utf-8"))["state"] == "done"


def test_a_torn_file_of_checks_does_not_send_a_person_to_a_page_that_is_down_with_it(tmp_path: Path):
    """The advice named two ways out and one of them was the page that cannot be drawn.

    The findings of the checks draw the status page and the page of things to check, so a torn
    validation.json takes both down. "Run them again, or press Check again on the status page" gave
    a person who lives on the dashboard and not in a terminal the half of the advice that is not
    there: the button is on the page that answers 503 for the same reason.
    """
    from epicrisis.validate import load_validation

    data_dir, source_id = an_instance(tmp_path)
    output = data_dir / "sources" / source_id
    output.mkdir(parents=True, exist_ok=True)
    (output / layout.VALIDATION).write_text('{"documents": [{"sha', encoding="utf-8")

    with pytest.raises(state.Unreadable) as broken:
        load_validation(output)

    mend = broken.value.mend
    assert "press Check again on the status page" not in mend
    # The one way out that works, ready to be typed: this archive, and this instance.
    assert f"validate --source {source_id}" in mend and str(data_dir) in mend
    # And it says why the button is not among the ways out, rather than leaving it to be found.
    assert "Check again button cannot be used" in mend

    client = dashboard(data_dir)
    for page in ("/status", "/review"):
        answer = client.get(page)
        assert answer.status_code == 503, page
        assert f"validate --source {source_id}" in answer.text, page
        assert "press Check again" not in answer.text, page


def test_a_forgotten_update_lock_is_named_in_the_terminal_and_on_the_page(tmp_path: Path):
    """The commonest lock of all, and the only one whose sentence about itself reached nobody.

    A machine restarted in the middle of an update leaves update.lock behind with a number in it
    that now belongs to some live daemon — the very case ABANDONED_AFTER_HOURS and the words of Busy
    were written for. The terminal answered "An update is already running." and stopped: no pid, no
    file name, no way out, because the check stood in front of the lock and Busy was never raised.
    The status page went on promising that the documents were being read.
    """
    import os

    data_dir, source_id = an_instance(tmp_path)
    output = data_dir / "sources" / source_id
    output.mkdir(parents=True, exist_ok=True)
    # The folder was looked through, and then the reading was interrupted by the machine itself.
    (output / layout.INVENTORY_STATUS).write_text(
        json.dumps({"state": "done", "scanned": 0, "started_at": _ago(600), "finished_at": _ago(590)}),
        encoding="utf-8")  # fmt: skip
    (data_dir / "update.lock").write_text(
        json.dumps({"pid": os.getpid(), "started_at": records.now()}), encoding="utf-8")

    code, said = on_the_command_line("update", "--data-dir", str(data_dir))

    assert code == 3, said  # Busy, and not the bare 2 of a check that said five words
    assert "update.lock" in said and str(os.getpid()) in said
    assert "deleting it lets this step run again" in said
    assert "24 hours is ignored by itself" in said
    assert "Traceback" not in said

    # And the page that promises the documents are being read now names the file that says so.
    page = dashboard(data_dir).get("/status")
    assert page.status_code == 200 and "The documents are being read" in page.text
    assert "update.lock" in page.text and "deleting it lets the reading be started again" in page.text


def test_putting_back_the_list_of_archives_says_which_version_it_is(tmp_path: Path):
    """"Everything is there again" over a copy that is one change behind.

    sources.json.previous is the version before the last change. Somebody who had just added an
    archive — or pointed one at the folder it had moved to — and then met a torn list was told that
    putting the copy back gives them every archive, everything read from it and every correction on
    it. It gives them the list as it was before that last change: the new archive is off it, its
    folder of work sits under an id nothing names any more, and `backup` stops carrying it.
    """
    data_dir, first = an_instance(tmp_path)
    registry = SourceRegistry(data_dir)
    later = tmp_path / "later"
    later.mkdir()
    added = registry.add(str(later), owner="Somebody Else")
    output = data_dir / "sources" / added.id
    output.mkdir(parents=True, exist_ok=True)
    (output / layout.CORRECTIONS).write_text('{"field": "as the person typed it"}\n', encoding="utf-8")

    (data_dir / layout.SOURCES).write_text('[{"id": "', encoding="utf-8")  # cut off mid-write
    with pytest.raises(state.Unreadable) as broken:
        registry.list()

    mend = broken.value.mend
    assert "version before the last change" in mend
    assert "not on it" in mend, "and what the copy does not hold is said, not left to be found"
    assert f"{layout.SOURCES}.previous" in mend  # the act itself is still the first thing
    assert "sources list" in mend and str(data_dir) in mend

    # And that command is the one that answers it: the folder of work is named, with the id it is
    # under, where nothing named it before.
    (data_dir / layout.SOURCES).replace(data_dir / (layout.SOURCES + ".torn"))
    (data_dir / (layout.SOURCES + ".previous")).replace(data_dir / layout.SOURCES)
    code, said = on_the_command_line("sources", "list", "--data-dir", str(data_dir))

    assert code == 0, said
    assert added.id in said and first in said
    assert "this list does not name" in said
    assert "Add that folder again" in said


def test_the_settings_of_an_instance_keep_the_version_before_the_last_change(tmp_path: Path):
    """Three files hold what somebody chose here, and only two of them could be put back.

    sources.json and indicators.json each keep a copy beside them and name it in their own message
    about trouble. settings.json kept none, and its way out was not an act but a description:
    "repair that file, or move it aside to start from the defaults" — nineteen switches, the engine,
    three models, the answer mode, every rule's threshold, the lock and its window, to be answered
    again by hand. Nothing about how it is written made it safer: a hand editing it, a folder half
    restored from a copy, a file system that lost a write reach all three the same way.
    """
    data_dir, _ = an_instance(tmp_path)
    settings.set_answer_mode(data_dir, "with_meaning")
    first = (data_dir / layout.SETTINGS).read_text(encoding="utf-8")
    settings.set_answer_mode(data_dir, "direct")

    kept = data_dir / (layout.SETTINGS + ".previous")
    assert kept.exists(), "the version before the last change is beside it, as for the other two"
    assert kept.read_text(encoding="utf-8") == first
    assert json.loads((data_dir / layout.SETTINGS).read_text(encoding="utf-8"))["answer_mode"] == "direct"

    # And the file is the one thing that has to be readable for the copy to be worth having: a torn
    # one is refused, with the copy named as the act that puts it right.
    whole = (data_dir / layout.SETTINGS).read_text(encoding="utf-8")
    (data_dir / layout.SETTINGS).write_text(whole[: len(whole) // 2], encoding="utf-8")
    with pytest.raises(state.Unreadable) as broken:
        settings.set_answer_mode(data_dir, "as_printed")
    assert f"{layout.SETTINGS}.previous" in broken.value.mend
    assert "the version before the last change" in broken.value.mend
    # Putting it back by hand is the whole of the mending, and the answer stored in it comes back.
    kept.replace(data_dir / layout.SETTINGS)
    assert not settings.unreadable(data_dir)
    assert settings.answer_mode(data_dir) == "with_meaning"

    # The page that says this file cannot be read names the copy too, for whoever is not in a shell.
    (data_dir / layout.SETTINGS).write_text("{not json", encoding="utf-8")
    page = dashboard(data_dir).get("/status")
    assert page.status_code == 200 and f"{layout.SETTINGS}.previous" in page.text


def test_a_folder_picker_with_nothing_it_may_show_shows_nothing(tmp_path: Path, monkeypatch):
    """An empty list of roots turned the boundary off instead of closing it.

    `if roots and not any(...)`: with no roots at all the condition is false and the folder was
    listed. The list goes empty on an ordinary installation — a server run as root, with the data
    folder under /var/lib, /opt or /srv, which is what an organisation does — because the home of
    that account and both folders above the data folder are then all three the server's own and
    roots() drops them. What went out of the door was the directory tree of the machine: folder
    names and the number of files in each, and a folder name in this program is a surname and
    sometimes a diagnosis. The docstring of the module promised the opposite of what it did.
    """
    from epicrisis.sources import SourceError, SourceRegistry
    from epicrisis.web.browse import BrowseError, list_folder

    monkeypatch.delenv("EPICRISIS_ARCHIVE_ROOT", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/root")))  # the server runs as root
    registry = SourceRegistry(Path("/var/lib/epicrisis/data"))  # where a service keeps its data
    assert registry.roots() == [], "every place this instance would offer is the server's own"

    for folder in ("/etc", "/usr/share", "/var"):
        with pytest.raises(BrowseError) as refused:
            list_folder(folder, added_paths=set(), roots=registry.roots(), data_dir=registry.data_dir)
        assert refused.value.status_code == 403, folder

    # And the refusal says which way out there is, without offering the folder it is standing in:
    # every one of these could never be an archive, so a line saying to add it would be a lie.
    said = str(refused.value)
    assert "no folder it can show" in said
    assert "sources add" in said and '"/var"' not in said
    assert "EPICRISIS_ARCHIVE_ROOT" in said and str(registry.data_dir) in said

    # The page behind the picker refuses in the same state, and says the same thing rather than
    # "Archives are added from ." with the place missing out of it.
    with pytest.raises(SourceError) as from_the_page:
        registry.validate(str(tmp_path))
    assert "No folder of this server can be added from a page" in str(from_the_page.value)
    assert "Archives are added from ." not in str(from_the_page.value)
    # Typed out, it is still the person's own decision to make, and still every other rule.
    with pytest.raises(SourceError, match="system folder"):
        registry.validate("/etc", typed=True)


def test_the_picker_never_offers_a_folder_of_the_server_as_an_archive_to_type(tmp_path: Path, monkeypatch):
    """Opened where the server chose and refused there, it advised adding that very folder.

    The dialog opens on no path, and the server answers with the home folder of the account it runs
    as. Run as root that is /root, which is the server's own and refused however it is offered — so
    the red line under an empty window said `sources add "/root"`: add, as somebody's medical
    archive, a folder the person never chose and nothing would accept.
    """
    from epicrisis.web.browse import BrowseError, list_folder
    from epicrisis.sources import SourceRegistry

    monkeypatch.delenv("EPICRISIS_ARCHIVE_ROOT", raising=False)
    home = tmp_path / "home"
    (home / "scans").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    registry = SourceRegistry(home / "instance" / "data")
    assert registry.roots(), "this instance has places of its own to offer"

    with pytest.raises(BrowseError) as refused:
        list_folder("/etc", added_paths=set(), roots=registry.roots(), data_dir=registry.data_dir)

    said = str(refused.value)
    assert 'sources add "/etc"' not in said, "a folder that can never be an archive is never offered"
    assert "<the folder of documents>" in said, "and the shape of the line is still there to copy"
    assert str(home) in said, "with the places this picker does show"
    # A folder that could be added is still named in full, which is what makes that line usable.
    disk = tmp_path / "mnt" / "scans"
    disk.mkdir(parents=True)
    with pytest.raises(BrowseError) as elsewhere:
        list_folder(str(disk), added_paths=set(), roots=registry.roots(), data_dir=registry.data_dir)
    assert f'sources add "{disk}"' in str(elsewhere.value)


def test_the_button_that_starts_a_reading_says_when_a_lock_is_in_the_way(tmp_path: Path):
    """Pressed over a forgotten lock, it did nothing and said nothing, for a day.

    A machine that dies in the middle of a reading leaves update.lock behind with the number of a
    process that is gone. The page then says the documents are being read, and the button offered
    for every other case quietly returns to that same page — so a person presses it, nothing
    happens, and the one thing in the way has a name and a file that nobody ever showed them.
    """
    import os

    from fastapi.testclient import TestClient

    from epicrisis.runs import one_at_a_time
    from epicrisis.update import LOCK_NAME
    from epicrisis.web.app import create_app

    data_dir, _source_id = an_instance(tmp_path)
    client = TestClient(create_app(data_dir, background_jobs=True), base_url="http://localhost:8050")

    with one_at_a_time(data_dir / LOCK_NAME, "an update"):
        refused = client.post("/update", follow_redirects=False)
        assert refused.status_code == 409, refused.status_code
        assert "update.lock" in refused.text
        assert "deleting that one file" in refused.text

    # And with nothing holding it, the button is a button again.
    assert client.post("/update", follow_redirects=False).status_code == 303
    assert os.path.exists(data_dir)
