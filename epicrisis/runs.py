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
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from contextlib import contextmanager
from pathlib import Path

from epicrisis.records import now


class Busy(RuntimeError):
    """Another run of this step holds the lock. It names the lock file, so a person can act.

    The lock file and the name of the step are carried as well as said, because the two readers of
    this need them written differently: a command prints the path in full, and a page may only name
    it relative to the data directory — a path outside it could be an archive folder, and those are
    named after people and after what was wrong with them.
    """

    def __init__(self, said: str, lock=None, what: str = ""):
        self.lock = str(lock) if lock else ""
        self.what = what
        super().__init__(said)


# After how long a lock is no longer believed, whatever its pid says. A pid is a weak witness: the
# numbers are reused, and a machine that has rebooted — or a container, where they start again at
# one — hands the number in a lock left by a dead run to some live daemon. The step was then busy
# for ever: the command answered with a traceback saying "already running (pid 1)", the dashboard
# drew the step as running at 100% with no end, and the one button that starts an archive over
# refused politely and suggested waiting. Nothing named the file, and no command took it off.
#
# A day is far longer than any step here takes over the whole of a real archive, so a lock older
# than that is evidence of a run that is not coming back rather than of one still working.
ABANDONED_AFTER_HOURS = 24


def holder(lock: Path) -> int | None:
    """The pid of the live process holding this lock, or None: no file, junk, a dead pid, or stale.

    Stale means the lock was written long enough ago that it is not believed any more. started_at
    has been written into every one of these files from the beginning and read by nothing.
    """
    try:
        written = json.loads(Path(lock).read_text(encoding="utf-8"))
        pid = written["pid"]
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return None
    if _older_than_believing(written.get("started_at")):
        return None
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, TypeError, ValueError):
        return None
    except PermissionError:  # alive, owned by another user
        return int(pid)
    return int(pid)


def _older_than_believing(started_at) -> bool:
    """Whether a lock was taken so long ago that no run of this program could still be in it."""
    if not isinstance(started_at, str):
        return False  # a lock from before this was written down is judged by its pid alone
    try:
        taken = datetime.fromisoformat(started_at)
    except ValueError:
        return False
    if taken.tzinfo is None:
        taken = taken.replace(tzinfo=UTC)
    return datetime.now(UTC) - taken > timedelta(hours=ABANDONED_AFTER_HOURS)


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
                raise Busy(
                    f"{what} is already running here (pid {running}). If nothing is running — the "
                    f"machine was restarted, or that number belongs to something else now — the "
                    f"lock is the file {lock}, and deleting it lets this step run again. A lock "
                    f"older than {ABANDONED_AFTER_HOURS} hours is ignored by itself.",
                    lock=lock, what=what,
                ) from None  # fmt: skip
            # The process that wrote it is gone; its lock is not one. Taken over, once.
            if attempt == 2:
                raise Busy(f"{what} could not take its lock ({lock}): it is being taken by somebody else.",
                           lock=lock, what=what) from None  # fmt: skip
            lock.unlink(missing_ok=True)
            continue
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                json.dump({"pid": os.getpid(), "started_at": now()}, file)
        except OSError:
            # The file is made first and written second, so a disk with no room left in it left an
            # empty lock file behind — one per press of a button on the dashboard — from before the
            # try/finally that takes the lock off. An empty file is read as held by nobody, so this
            # healed itself; it still littered a full disk with locks while a person was trying to
            # clear one.
            lock.unlink(missing_ok=True)
            raise
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


def write_whole(path: Path, text: str) -> None:
    """Write a file of state whole: under a temporary name, then renamed over the old one.

    Nine places wrote these same three lines, and all nine left the temporary file behind when the
    write failed. On a disk with no room left that was one dead file per press of a button —
    settings.json.1120419.tmp, sources.json.1120419.tmp, consent.json.1120419.tmp — each of them
    empty, none of them ever removed, on the very disk a person was trying to make room on. The
    files themselves were never damaged, which is what this way of writing is for; the litter was
    working against the only way out of the trouble.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = temporary_name(path)
    try:
        temporary.write_text(text, encoding="utf-8")
        put_in_place(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def copy_whole(source: Path, target: Path) -> None:
    """Copy a file so that the one already at the target is never half replaced.

    shutil.copy2 opens the target for writing, which empties it, and only then writes. A disk that
    fills in the middle of that leaves a truncated file where a whole one was — and the two places
    this program copies files are the copy kept beside a person's own work and the backup of it.
    Both destroyed the last good copy exactly when the trouble arrived that makes a copy worth
    having: a backup onto a stick with no room left came away with half of one file and none of
    the version that had been there since the last time.

    So the bytes go to a temporary name beside the target and are renamed over it, the way every
    file of state here is written. A failure leaves the old copy untouched and nothing behind.
    """
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = temporary_name(target)
    try:
        shutil.copyfile(source, temporary)
        shutil.copystat(source, temporary)
        put_in_place(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def put_in_place(temporary: Path, path: Path) -> None:
    """Rename a finished file over the one it replaces, and leave it owned by its archive.

    The bytes reach the disk before the rename does. Writing a file and renaming it is atomic in
    the sense that nobody ever sees half a name — but the rename can reach the journal before the
    contents do, and a machine that loses power in between puts an empty file where the old one
    was, atomically. For a transcription that is hours of a model's work and the only copy there
    is; for corrections it is a person's own reading of their own page.
    """
    try:
        with temporary.open("rb+") as written:
            os.fsync(written.fileno())
    except OSError:
        pass  # a file we cannot sync is still a file we have written
    os.replace(temporary, path)
    _sync_the_folder(path.parent)
    belongs_to_the_folder(path)


def _sync_the_folder(folder: Path) -> None:
    """So that the rename itself survives, and not only what it renamed."""
    try:
        opened = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(opened)
    except OSError:
        pass
    finally:
        os.close(opened)


def temporary_name(path: Path) -> Path:
    """The name to write under before a rename: one per process, so two writers never share one.

    os.replace is atomic; two writers of one temporary file are not, and the loser's half-written
    bytes are what the winner renames into place.
    """
    path = Path(path)
    return path.with_name(f"{path.name}.{os.getpid()}.tmp")
