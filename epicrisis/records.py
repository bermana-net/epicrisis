"""The files this project writes beside an archive: one JSON record per line, appended.

A run records what it did while it is doing it — a ledger line per document, a correction a
person made, a call the MCP server served — so that a run stopped halfway leaves behind
everything it had finished. Every one of those writes goes through the same lock and stamps
itself with the same kind of time, which is why both live here instead of once per module.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from epicrisis.parallel import STATE_LOCK


def now() -> str:
    """This moment to the second, in UTC: how every record in this project stamps itself."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def today() -> str:
    """This day in UTC, as `YYYY-MM-DD`: how anything counted in whole days is compared.

    Cut from `now()` rather than asked of the clock a second time, so that a day and a moment in
    this program can never disagree about which day it is.
    """
    return now()[:10]


def append_line(path: Path, line: dict) -> None:
    """Add one record to a file of them, making the folder if it is not there yet."""
    from epicrisis.runs import belongs_to_the_folder  # runs stamps its locks with now(), above

    path.parent.mkdir(parents=True, exist_ok=True)
    with STATE_LOCK, path.open("a+", encoding="utf-8") as fh:
        # A record begins on a line of its own, whatever the last write left behind. These files
        # are appended to a line at a time, so a disk that filled or a process killed mid-write
        # leaves a last line with no newline on it — and the next record written was glued to that
        # stump, which made one unreadable line out of two records: the torn one, which was already
        # lost, and this one, which a person had just typed and was told nothing about. The count of
        # torn lines did not move either, there being no new line to count.
        if fh.tell():
            fh.seek(fh.tell() - 1)
            if fh.read(1) != "\n":
                fh.write("\n")
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    belongs_to_the_folder(path)


def read_records(path: Path) -> Iterator[dict]:
    """Every record in one of these files, in the order they were written.

    A line that will not parse is skipped and counted rather than raised. These files are the
    archive itself — what each page is, what was read, what a person corrected — and they are
    appended to a line at a time, so a disk that fills up or a process killed mid-write leaves
    one torn line at the end. Raising there took every page of the interface down at once, with
    nothing to say which file or which line, and no way back from inside the program. One
    unreadable line is one record lost; the rest of the archive is still the archive.

    Nothing is hidden by this: torn_lines() says how many were skipped, and the pages that count
    what an archive holds say so.
    """
    found: set[int] = set()
    read_to_the_end = False
    try:
        with path.open(encoding="utf-8") as fh:
            for number, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    found.add(number)
                    continue
                yield record
        read_to_the_end = True
    finally:
        # A whole file read through is the last word on it: what it holds now is what it holds,
        # and a file that has been repaired says so by having nothing torn in it. A reader that
        # stopped early saw only part of the file and may not add up to the truth, so it can add
        # what it found and take nothing away.
        if read_to_the_end:
            if found:
                _torn[str(path)] = found
            else:
                _torn.pop(str(path), None)
        elif found:
            _torn.setdefault(str(path), set()).update(found)


# Which lines could not be read, by file, since this process started: the line numbers and not a
# count of them. Read by whatever wants to say so. A file is forgotten only by being read through
# and found whole; nothing else clears it, because a number that goes back to nothing on its own
# says the trouble went away when nobody has looked.
#
# The numbers are the point. Counting instead gave a number that grew while a person looked at
# it: a page reads these files more than once to draw itself, and every pass added the same torn
# line again, so one torn line was reported as six, then eight, then ten — over an archive whose
# pages are a person's medical records, with "a record lost" beside each. The set says the same
# thing of a second reading of the same trouble, and a file read through after being repaired
# takes its own alarm down — which the count never did, not even after the file was whole again.
_torn: dict[str, set[int]] = {}


def torn_under(folder: Path) -> dict[str, int]:
    """Lines lost from files under one folder, named relative to it.

    Asked by whatever reports on one archive. The count is kept per process and by whole path, and
    an instance holds several archives, so a caller that wants to say "this archive lost a line"
    has to know which lines were this archive's.
    """
    folder = Path(folder).resolve()
    out = {}
    for path, count in torn_lines().items():
        try:
            out[str(Path(path).resolve().relative_to(folder))] = count
        except ValueError:
            continue
    return out


def torn_lines() -> dict[str, int]:
    """Files that held a line this process could not read, and how many such lines."""
    return {path: len(numbers) for path, numbers in _torn.items() if numbers}
