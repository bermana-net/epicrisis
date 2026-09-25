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


def append_line(path: Path, line: dict) -> None:
    """Add one record to a file of them, making the folder if it is not there yet."""
    from epicrisis.runs import belongs_to_the_folder  # runs stamps its locks with now(), above

    path.parent.mkdir(parents=True, exist_ok=True)
    with STATE_LOCK, path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    belongs_to_the_folder(path)


def read_records(path: Path) -> Iterator[dict]:
    """Every record in one of these files, in the order they were written."""
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)
