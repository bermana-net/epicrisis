"""One run at a time, and files that stay the archive owner's own."""

import json
import os
from pathlib import Path

import pytest

from epicrisis.records import append_line
from epicrisis.runs import Busy, belongs_to_the_folder, holder, one_at_a_time, put_in_place, temporary_name

as_somebody_else = pytest.mark.skipif(
    os.geteuid() != 0, reason="handing a file back to another user is only possible as root"
)


def test_one_run_of_a_step_at_a_time(tmp_path: Path):
    lock = tmp_path / "step.lock"
    with one_at_a_time(lock, "an index"):
        assert holder(lock) == os.getpid()
        with pytest.raises(Busy, match=f"pid {os.getpid()}"):
            with one_at_a_time(lock, "an index"):
                pass
    assert not lock.exists() and holder(lock) is None

    # A lock left behind by a process that is gone is not a lock.
    lock.write_text(json.dumps({"pid": 999_999_999}), encoding="utf-8")
    with one_at_a_time(lock, "an index"):
        assert holder(lock) == os.getpid()


def test_two_writers_never_share_one_temporary_name(tmp_path: Path):
    path = tmp_path / "index.sqlite"
    assert temporary_name(path).name.endswith(f".{os.getpid()}.tmp")
    assert temporary_name(path).parent == path.parent


@as_somebody_else
def test_a_file_written_by_root_is_handed_back_to_the_archive_s_owner(tmp_path: Path):
    """The live failure: root rebuilt an index in somebody's data directory and the server that
    reads it, running as that person, could not open the file it had been given."""
    theirs = tmp_path / "data"
    theirs.mkdir()
    os.chown(theirs, 1000, 1000)

    written = theirs / "sources" / "abc" / "ledger.jsonl"
    written.parent.mkdir(parents=True)
    temporary = temporary_name(written)
    temporary.write_text("{}\n", encoding="utf-8")
    put_in_place(temporary, written)

    assert written.stat().st_uid == 1000
    # The folders root made on the way are handed over too, or nobody could reach the file.
    assert written.parent.stat().st_uid == 1000 and written.parent.parent.stat().st_uid == 1000

    # A line appended to a ledger of its own is the owner's as well.
    append_line(theirs / "sources" / "abc" / "mcp-access.jsonl", {"at": "now"})
    assert (theirs / "sources" / "abc" / "mcp-access.jsonl").stat().st_uid == 1000


@as_somebody_else
def test_root_s_own_folders_are_left_alone(tmp_path: Path):
    """Nothing is handed to anybody when the whole tree is root's: a server run by root keeps
    writing root's files, as it always did."""
    mine = tmp_path / "data"
    mine.mkdir()
    written = mine / "settings.json"
    written.write_text("{}", encoding="utf-8")
    belongs_to_the_folder(written)
    assert written.stat().st_uid == os.geteuid()


def test_two_runs_starting_together_never_both_hold_the_lock(tmp_path: Path, monkeypatch):
    """Reproduced by running it, which is how the finding was made rather than read off the code.

    The lock was created and then filled: os.open with O_EXCL put an empty file there and the pid
    went in as a second act. A reader arriving between the two found no pid, judged the lock held
    by nobody, deleted it and took it over — so two runs held one lock, and since every writer
    under it is read-modify-write, the loser's whole file went away without a word. On two threads
    started at the same instant it came out about half the time. The same hole sat under
    people.json and under all seven writers of indicators.json, because this lock is the only
    thing standing between them.

    The window is widened here rather than faked: the stamp that goes into the lock is made to
    take a quarter of a second. Before the fix that quarter second is spent with the lock file
    already created and still empty, and the second thread walks in; after it the stamp is made
    before anything is created, the file is written whole under a name of its own and linked into
    place, so there is no instant in which the lock exists and says nothing.

    What is asserted is not that both runs got through — the lock refuses rather than queues — but
    that the two were never inside at once, and that whoever did not get in was told so.
    """
    import threading
    import time

    from epicrisis import runs

    stamped = runs.now

    def slowly() -> str:
        made = stamped()
        time.sleep(0.25)
        return made

    monkeypatch.setattr(runs, "now", slowly)
    lock = tmp_path / "step.lock"
    inside: list[str] = []
    together, held, told = [], [], []

    def taking(which: str) -> None:
        try:
            with one_at_a_time(lock, "an index"):
                inside.append(which)
                if len(inside) > 1:
                    together.append(sorted(inside))
                time.sleep(0.2)
                inside.remove(which)
                held.append(which)
        except Busy:
            told.append(which)

    threads = [threading.Thread(target=taking, args=(which,), name=which) for which in ("first", "second")]
    threads[0].start()
    time.sleep(0.05)  # long enough for the first to be inside the window, far short of leaving it
    threads[1].start()
    for thread in threads:
        thread.join()

    assert not together, together  # the two were never in there at the same time
    assert len(held) + len(told) == 2, (held, told)  # and neither failed in some other way
    assert len(held) == 1 and len(told) == 1, (held, told)
    assert not lock.exists()  # taken off after, and nothing of the claim left beside it
    assert sorted(path.name for path in tmp_path.iterdir()) == []
