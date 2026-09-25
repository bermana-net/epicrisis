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
