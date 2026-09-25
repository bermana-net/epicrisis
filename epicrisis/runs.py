"""One run of a step at a time, per folder, and a way to tell whether one is going.

Every step that writes into a source's output directory — or into the one file of state the
whole server shares — takes the lock for it first. Two runs of the same step were not stopped
by anything before: they raced over the same ledgers, and over temporary files whose names were
fixed, so two `epicrisis index` runs wrote the same `index-<id>.sqlite.tmp` and each renamed
whatever the other had half-written into place.

The lock is a file holding the pid that holds it, created with O_EXCL so that the check and the
claim are one act rather than two. A lock left behind by a process that is gone is not a lock:
it is taken over, because a crash must not make a step unusable until somebody deletes a file.
"""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from epicrisis.records import now


class Busy(RuntimeError):
    """Another run of this step holds the lock. It says which pid, so a person can look."""


def holder(lock: Path) -> int | None:
    """The pid of the live process holding this lock, or None: no file, junk, or a dead pid."""
    try:
        pid = json.loads(Path(lock).read_text(encoding="utf-8"))["pid"]
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return None
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, TypeError, ValueError):
        return None
    except PermissionError:  # alive, owned by another user
        return int(pid)
    return int(pid)


@contextmanager
def one_at_a_time(lock: Path, what: str) -> Iterator[None]:
    """Hold the lock for the length of a run, or refuse with Busy and touch nothing."""
    lock = Path(lock)
    lock.parent.mkdir(parents=True, exist_ok=True)
    for attempt in (1, 2):
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            running = holder(lock)
            if running is not None:
                raise Busy(f"{what} is already running here (pid {running}).") from None
            # The process that wrote it is gone; its lock is not one. Taken over, once.
            if attempt == 2:
                raise Busy(f"{what} could not take its lock: it is being taken by somebody else.") from None
            lock.unlink(missing_ok=True)
            continue
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump({"pid": os.getpid(), "started_at": now()}, file)
        break
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def belongs_to_the_folder(path: Path) -> None:
    """Give a written file — and any folder made for it — the owner of the archive it sits in.

    A step run as root in somebody else's data directory (a rebuild of the index from a terminal,
    a line in a crontab) wrote files owned by root, with the private mode this program keeps. The
    server that reads them runs as the person whose archive it is, and the archive then answered
    "unable to open database file" to every question asked of it.

    Whose the files are is read from the directory tree itself: the first folder above them that
    root did not make. Nothing is done when this process is not root, or when the whole tree is
    root's own.
    """
    if os.geteuid() != 0:
        return
    path = Path(path)
    folder = path.parent
    while folder != folder.parent:
        try:
            above = folder.stat()
        except OSError:
            return
        if above.st_uid != 0:
            break
        folder = folder.parent
    else:
        return  # every folder up to the root is root's; there is nobody to hand these back to
    here = path
    while here != folder:
        try:
            if here.stat().st_uid == 0:
                os.chown(here, above.st_uid, above.st_gid)
        except OSError:
            pass  # a file we cannot hand over is still a file we have written
        here = here.parent


def put_in_place(temporary: Path, path: Path) -> None:
    """Rename a finished file over the one it replaces, and leave it owned by its archive."""
    os.replace(temporary, path)
    belongs_to_the_folder(path)


def temporary_name(path: Path) -> Path:
    """The name to write under before a rename: one per process, so two writers never share one.

    os.replace is atomic; two writers of one temporary file are not, and the loser's half-written
    bytes are what the winner renames into place.
    """
    path = Path(path)
    return path.with_name(f"{path.name}.{os.getpid()}.tmp")
