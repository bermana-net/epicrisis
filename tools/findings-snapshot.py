#!/usr/bin/env python
"""Every finding every check makes, on every archive here, as one sorted list.

This is the ruler against which the checks are moved into the rule registry. A refactor that
keeps its promise produces a file identical to the one it started from, line for line, on the
real archives — which is a stronger statement than a green test suite, because it covers the
cases nobody thought to write a test for.

It holds codes, counts and document ids, and no medical content whatsoever: no names, no
values, no institutions. Even so it is about one person's archive, so it is written where it is
asked for and never into the repository.

    tools/findings-snapshot.py before.txt
    ... a step of the refactor ...
    tools/findings-snapshot.py after.txt && diff before.txt after.txt

The checks are re-run, not read from what was stored: reading the stored findings would compare
a file with itself and prove nothing. Re-running needs no model and touches no document.
"""

import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from epicrisis import rules  # noqa: E402
from epicrisis import suspects  # noqa: E402
from epicrisis.rules import kinds  # noqa: E402
from epicrisis.index.build import index_path  # noqa: E402
from epicrisis.sources import SourceRegistry, source_output_dir  # noqa: E402
from epicrisis.validate import validate_source  # noqa: E402


def validation_lines(data_dir: Path, source) -> list[str]:
    """What the checks over the transcriptions find, per document, by code."""
    output = source_output_dir(data_dir, source.id)
    result = validate_source(output, Path(source.path))
    lines = []
    for document in result["documents"]:
        where = f"{document['file_sha256'][:16]} p{'.'.join(str(page) for page in document['pages'])}"
        for code, count in document["findings"].items():
            lines.append(f"validate {source.id} {where} {code} {count}")
        for copy in document.get("copies", []):
            lines.append(f"validate {source.id} {where} copy_of {copy['file_sha256'][:16]}")
    for code, count in result["totals"].items():
        lines.append(f"total    {source.id} - {code} {count}")
    return lines


def suspect_lines(data_dir: Path, source) -> list[str]:
    """What the search for rows that look like a misreading finds, per row, by signal."""
    path = index_path(data_dir, source.id)
    if not path.exists():
        return [f"suspects {source.id} - no-index -"]
    lines = []
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        rows, documents = suspects.rows_from_index(connection)
        # Every rule that could find one of these, whatever this instance has turned on: the
        # ruler measures the checks, not the switches.
        for found in suspects.find(rows, documents, rules.load(data_dir).at(kinds.SUSPECTS)):
            where = f"{found.file_id[:16]} p{found.first_page}"
            for code, times in sorted(found.codes.items()):
                lines.append(f"suspects {source.id} {where} {code} {times}")
            lines.append(f"suspects {source.id} {where} weight {found.weight}")
    return lines


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: findings-snapshot.py <file to write> [--data-dir DIR]")
    out = Path(sys.argv[1])
    data_dir = Path(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[2] == "--data-dir" else Path("data")

    lines: list[str] = []
    for source in SourceRegistry(data_dir).list():
        lines += validation_lines(data_dir, source)
        lines += suspect_lines(data_dir, source)
    # Sorted, because neither the order documents are read in nor the order a Counter hands its
    # keys back is part of what the checks decide, and a diff should not say it is.
    out.write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")
    print(f"{len(lines)} findings from {len(SourceRegistry(data_dir).list())} archives -> {out}")


if __name__ == "__main__":
    main()
