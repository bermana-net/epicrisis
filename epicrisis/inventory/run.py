"""Run an inventory into a JSONL file. Shared by the CLI and the web app."""

import json
from collections.abc import Callable
from pathlib import Path

from epicrisis import layout
from epicrisis.inventory.report import Summary
from epicrisis.inventory.scan import iter_files, scan
from epicrisis.records import now
from epicrisis.runs import put_in_place, temporary_name, write_whole


class OutputInsideArchive(ValueError):
    pass


class NothingWhereTheArchiveWas(RuntimeError):
    """The folder walked empty where it used to hold files. Refused rather than written."""


def _found_something_last_time(out: Path) -> bool:
    """Whether the scan already on disk holds a record. A file of blank lines holds none."""
    with out.open(encoding="utf-8") as written:
        return any(line.strip() for line in written)


def write_inventory(
    archive: Path, out: Path, progress: Callable[[int, int], None] | None = None
) -> Summary:
    """Scan archive into out. The file appears only once the scan has finished."""
    archive = archive.resolve()
    out = out.resolve()
    if out.is_relative_to(archive):
        raise OutputInsideArchive("the output would be written inside the archive, which is read-only")
    out.parent.mkdir(parents=True, exist_ok=True)

    started_at = now()
    total = sum(1 for _ in iter_files(archive)) if progress else 0
    summary = Summary()
    partial = temporary_name(out).with_suffix(".partial")
    try:
        with partial.open("w", encoding="utf-8") as fh:
            for count, record in enumerate(scan(archive), 1):
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                summary.add(record)
                if progress:
                    progress(count, total)
        # A folder that has stopped being there walks as a folder with nothing in it: os.walk over
        # a path that does not exist yields nothing and raises nothing. Put in place, that empty
        # scan became the archive — every page saying nought documents, the index rebuilt from it
        # — for the ordinary reason that a disk did not mount or a folder was renamed. The
        # transcriptions survive it, but a person looking at an empty medical archive does not
        # know that. So an empty scan never replaces a scan that found something.
        if not summary.files and out.exists() and _found_something_last_time(out):
            raise NothingWhereTheArchiveWas(
                "the folder held no files this time, and the last scan of it did; "
                "nothing was changed. Check that the archive is where it was."
            )  # fmt: skip
        put_in_place(partial, out)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    # How far the walk got, beside what it found. The dashboard writes this while its own scan
    # runs, and read it to draw the first step of an archive; a walk from anywhere else — the
    # reading's own first step, the command line — left no such line, so an archive read from end
    # to end by `epicrisis update` showed "Queued" on that step for ever. It was seen on an
    # archive of 257 documents, every one of them read, with the first step saying it had not
    # begun. Written by the walk itself now, whoever asked for it.
    _write_status(out, {"state": "done", "scanned": summary.files + summary.skipped,
                        "started_at": started_at, "finished_at": now()})  # fmt: skip
    return summary


def _write_status(inventory: Path, status: dict) -> None:
    beside = inventory.parent / layout.INVENTORY_STATUS
    beside.parent.mkdir(parents=True, exist_ok=True)
    write_whole(beside, json.dumps(status))

