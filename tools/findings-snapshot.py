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
from epicrisis.index.build import build_index, index_path  # noqa: E402
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
    # The extract step's own checks by name, which is what this ruler was blind to. Eleven of them
    # arrive at `validate` and leave as three summaries, so a check that moved by one moved a
    # summary by one and the diff said only that a number somewhere had changed. These are the
    # lines that say which check it was. Codes and counts, nothing out of anybody's records.
    #
    # Taken from every document and not only from the ones that ended with a finding: four of
    # these codes are covered by rules elsewhere and make no finding of their own, and those are
    # exactly the ones a move into the registry is most likely to drop in silence.
    found = {f"{document['file_sha256']}:{'.'.join(str(page) for page in document['pages'])}": document
             for document in result["documents"]}  # fmt: skip
    for key, checks in sorted(result.get("checks", {}).items()):
        sha256, numbers = key.split(":")
        where = f"{sha256[:16]} p{numbers}"
        for code, count in sorted(checks.items()):
            lines.append(f"check    {source.id} {where} {code} {count}")
        lines += _the_summaries_add_up(source.id, where, checks, found.get(key, {}).get("findings", {}))
    return lines


def _the_summaries_add_up(source_id: str, where: str, checks: dict, findings: dict) -> list[str]:
    """The ruler checking itself: the codes it just printed, folded the way `validate` folds them,
    against the summaries `validate` actually wrote.

    Without this the new lines are a second opinion rather than a measurement — they would be
    taken from the same run and could drift from the summaries beside them without either looking
    wrong. The folding is reproduced here **from the sets validate declares**, not from a copy of
    them, so a code moved between those sets is not quietly reproduced on both sides.

    It raises rather than printing a note. A ruler that says "these do not add up" in a file
    somebody diffs later is a ruler whose own disagreement travels as data.
    """
    from epicrisis.validate import COVERED_CHECK_PROBLEMS, INCOMPLETE_CHECK_PROBLEMS, OWN_FINDING_PROBLEMS

    folded = {
        "transcription_incomplete": sum(count for code, count in checks.items() if code in INCOMPLETE_CHECK_PROBLEMS),
        "checks_still_failing": sum(count for code, count in checks.items() if code not in
                                    COVERED_CHECK_PROBLEMS | INCOMPLETE_CHECK_PROBLEMS | OWN_FINDING_PROBLEMS),  # fmt: skip
        **{code: checks.get(code, 0) for code in OWN_FINDING_PROBLEMS},
    }
    for code, counted in folded.items():
        # A rule of the registry may add to one of these names as well, so the summary is allowed
        # to stand higher than the checks alone — never lower, which would mean a check was
        # counted into a summary that nothing here can see.
        if findings.get(code, 0) < counted:
            raise SystemExit(f"{source_id} {where}: {code} is {findings.get(code, 0)} and the checks "
                             f"under it add up to {counted}. The snapshot cannot be trusted.")  # fmt: skip
    return [f"folded   {source_id} {where} {code} {count}" for code, count in sorted(folded.items()) if count]


def suspect_lines(data_dir: Path, source) -> list[str]:
    """What the search for rows that look like a misreading finds, per row, by signal."""
    path = index_path(data_dir, source.id)
    if not path.exists():
        return [f"suspects {source.id} - no-index -"]
    lines = []
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        rows, documents, spellings = suspects.rows_from_index(connection)
        # Every rule that could find one of these, whatever this instance has turned on: the
        # ruler measures the checks, not the switches.
        for found in suspects.find(rows, documents, spellings, rules.load(data_dir).at(kinds.SUSPECTS)):
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
        # In the order the program itself runs them: the checks write validation.json, the index is
        # built from that and from the transcriptions, and the search for rows that look misread is
        # read out of the index. Half of this snapshot came from an index somebody had built at some
        # earlier time — twice it was one from before the very change being measured, and the
        # snapshot then said "identical to the byte" about a comparison of two old readings. The
        # numbers happened to be right both times, and the sentence was stronger than the
        # measurement, which is the failure this file exists to prevent in the code it measures.
        lines += validation_lines(data_dir, source)
        build_index(data_dir, [source])
        lines += suspect_lines(data_dir, source)
    # Sorted, because neither the order documents are read in nor the order a Counter hands its
    # keys back is part of what the checks decide, and a diff should not say it is.
    out.write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")
    print(f"{len(lines)} findings from {len(SourceRegistry(data_dir).list())} archives -> {out}")


if __name__ == "__main__":
    main()
