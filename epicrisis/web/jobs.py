"""Background inventory runs, at most one per source.

Status lives on disk next to the results, so the dashboard survives a server restart.
"""

import json
import threading
import time
from pathlib import Path

from epicrisis import layout
from epicrisis import records
from epicrisis.inventory.run import write_inventory
from epicrisis.sources import OUTPUT_DIR_NAME, Source, source_output_dir
from epicrisis.runs import write_whole
from epicrisis.invocation import CLI

PROGRESS_INTERVAL_SECONDS = 0.5



# What can be said out loud about a failure of a scan, by the kind of failure. Only this program's
# own refusals are here, and only in words written in this file: nothing in these sentences comes
# from the file system, so no path and no file name of anybody's archive can reach a page through
# them. Anything not on this list keeps to the type alone, as before.
CAN_BE_SAID = {
    "NothingWhereTheArchiveWas":
        "The folder of this archive held no files this time, and the last look through it did, so "
        "nothing was changed. Check whether the disk it is on is mounted. If the folder has moved, "
        f"point this archive at the new place with '{CLI} sources set-path' — everything already "
        "read from it, and every correction, is kept.",
    "OutputInsideArchive":
        "What this program writes would land inside the archive folder itself, which it only ever "
        "reads. Keep the data folder of this instance outside the folder of documents.",
    "PermissionError":
        "This server is not allowed to read something in that folder. Nothing was changed.",
    "NotADirectoryError":
        "The path of this archive is not a folder. Nothing was changed.",
    "FileNotFoundError":
        "The folder of this archive is not there. Nothing was changed: everything already read from "
        "it is kept here, beside this instance.",
}


# And the same for the record of a scan that is there and will not parse, which is not a failure of
# a scan at all: the file was cut off by a hand, a half-finished copy of data/ carried to another
# machine, or a file system that lost a write. Named here beside the others so that the one page
# that carries the way out of every other trouble does not fall over this one.
STATUS_UNREADABLE = (
    f"The record of the last look through this folder is there and cannot be read "
    f"({layout.INVENTORY_STATUS}, beside what was read from this archive). Nothing read from the "
    "archive is lost and the folder itself was not touched: this file holds how far the last scan "
    "got and nothing else. Rescan to write it again — that is the whole of the mending — or delete "
    "that one file."
)


def sayable(exc: BaseException) -> str:
    """The sentence for this kind of failure, or nothing where there is none to show."""
    return CAN_BE_SAID.get(type(exc).__name__, "")


class InventoryJobs:
    def __init__(self, data_dir: Path, background: bool = True):
        self.data_dir = data_dir
        self.background = background
        self._lock = threading.Lock()
        self._running: set[str] = set()
        self._mark_interrupted()

    def records_path(self, source_id: str) -> Path:
        return source_output_dir(self.data_dir, source_id) / layout.INVENTORY

    def status(self, source_id: str) -> dict | None:
        """How far the last look through this folder got, or nothing where none has been recorded.

        A file that is there and will not parse is a third thing, and it was the one reading of a
        file of state in this program with no answer for it: the status page — the page holding the
        names of the archives, the folder paths, Rescan, Start again, Take off the list, Add an
        archive and the panel of the lock — answered with the words Internal Server Error, over a
        file that says how far a scan got and nothing else. Every other reader of a JSON file here
        has had its second except for years. The way out was to delete one file, and nothing named
        it: not the page, not the terminal, not the README. `update` does not mend it either.

        Said as a scan that failed, because that is the shape the row of this archive already
        draws in words, with the sentence beside it — and because the alternative was to answer
        "no scan has ever run", which is what a page believes about a folder nobody has looked at
        yet. Nothing here is lost: this file is made again by code, in the time one scan takes.
        """
        try:
            return json.loads(self._status_path(source_id).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (ValueError, OSError):
            return {"state": "failed", "error": "StatusUnreadable", "said": STATUS_UNREADABLE,
                    "started_at": None, "finished_at": None}  # fmt: skip

    def start(self, source: Source) -> bool:
        """Start an inventory unless one is already running for this source."""
        with self._lock:
            if source.id in self._running:
                return False
            self._running.add(source.id)
        started_at = records.now()
        self._write_status(source.id, {"state": "running", "scanned": 0, "total": None, "started_at": started_at})
        if self.background:
            threading.Thread(
                target=self._run, args=(source, started_at), name=f"inventory-{source.id}", daemon=True
            ).start()
        else:
            self._run(source, started_at)
        return True

    def _run(self, source: Source, started_at: str) -> None:
        last_write = 0.0

        def progress(scanned: int, total: int) -> None:
            nonlocal last_write
            now = time.monotonic()
            if scanned == total or now - last_write >= PROGRESS_INTERVAL_SECONDS:
                last_write = now
                self._write_status(
                    source.id,
                    {"state": "running", "scanned": scanned, "total": total, "started_at": started_at},
                )

        try:
            summary = write_inventory(Path(source.path), self.records_path(source.id), progress=progress)
        except Exception as exc:  # reported on the dashboard instead of killing the server
            # The kind of failure only. This walks the person's own files, so the message of almost
            # any error here — a permission, a broken PDF — carries the full path of the file, and
            # a file name in an archive like this carries a surname and often the reason for the
            # visit. It was written to the dashboard and kept in inventory.status.json for good.
            # Everywhere else that prints an exception in this program keeps the type alone.
            #
            # And beside it, where there is one, a sentence written here in this file rather than
            # come from the machine: this program's own refusals already explain themselves in
            # words, and the rule against showing their messages took those words away too. The
            # commonest of them — a folder that has stopped being there — reached the page as "The
            # folder could not be read through: NothingWhereTheArchiveWas", under a button whose
            # only advice was to try again, which would fail the same way for ever. The command
            # line had been printing the sentence all along.
            self._write_status(
                source.id,
                {"state": "failed", "error": type(exc).__name__, "said": sayable(exc),
                 "started_at": started_at, "finished_at": records.now()},
            )  # fmt: skip
        else:
            self._write_status(
                source.id,
                {"state": "done", "scanned": summary.files + summary.skipped, "started_at": started_at, "finished_at": records.now()},
            )
        finally:
            with self._lock:
                self._running.discard(source.id)

    def _mark_interrupted(self) -> None:
        # A fresh process has no threads, so any "running" status is left over from a crash or restart.
        for status_path in (self.data_dir / OUTPUT_DIR_NAME).glob("*/inventory.status.json"):
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # A status file torn by the crash it is evidence of. It says nothing; the
                # dashboard starting is worth more than the line it would have said.
                continue
            if status.get("state") == "running":
                self._write_status(status_path.parent.name, {**status, "state": "interrupted"})

    def _status_path(self, source_id: str) -> Path:
        return source_output_dir(self.data_dir, source_id) / layout.INVENTORY_STATUS

    def _write_status(self, source_id: str, status: dict) -> None:
        path = self._status_path(source_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_whole(path, json.dumps(status))
