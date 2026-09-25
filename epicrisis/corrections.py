"""What a person set by hand, kept apart from model output and never overwriting it.

data/sources/<id>/corrections.jsonl, one line per change; the latest line for a document and
field wins, and an empty value removes the correction.

A value is corrected by what was printed for it, not by its place in a list: the page, the name
and the value as the model read them. So a correction follows its line through a new
transcription, and stops applying if that line is read differently next time.
"""

import re
from datetime import date
from pathlib import Path

from epicrisis import layout
from epicrisis import records
from epicrisis.records import read_records
from epicrisis.printed_values import fold

FILE_NAME = layout.CORRECTIONS


# The fields of a printed value a person may put right, and the only ones the index takes from a
# correction. What was measured is not here on purpose: material has its own order of precedence
# — a person first, then the form, then a model — and index/build._material applies it.
CORRECTABLE = ("name_as_printed", "value_as_printed", "unit_as_printed", "reference_as_printed", "flag_as_printed")


def load_corrections(output: Path) -> dict[tuple, dict]:
    path = output / FILE_NAME
    latest: dict[tuple, dict] = {}
    if path.exists():
        for line in read_records(path):
            latest[(line["file_sha256"], tuple(line["pages"]), line["field"])] = line
    return {key: line for key, line in latest.items() if line.get("value")}


def value_key(page: int, name: str, value: str) -> str:
    return "|".join((str(page), fold(name), re.sub(r"\s+", "", (value or "")).casefold()))


def load_value_corrections(output: Path) -> dict[tuple, dict]:
    """(file, pages, value key) to what a person changed: fields, or removed."""
    path = output / FILE_NAME
    latest: dict[tuple, dict] = {}
    if path.exists():
        for line in read_records(path):
            if line.get("field") == "value":
                latest[(line["file_sha256"], tuple(line["pages"]), line["key"])] = line
    return {key: line for key, line in latest.items() if line.get("changes") or line.get("removed")}


def unmatched_values(output: Path) -> list[dict]:
    """Corrections that no longer find the line they were made on.

    A correction follows a printed line, not a position in a list, so a document read again by a
    model keeps every correction whose line it read the same way. Where it read the line
    differently, the correction quietly applies to nothing — and a person's own reading of their
    own page disappearing in silence is the worst failure this project has. So it is counted.
    """
    from epicrisis.extract.run import load_extracted

    lost = []
    for (file_sha256, pages, key), line in load_value_corrections(output).items():
        extracted = load_extracted(output / layout.EXTRACTED, file_sha256)
        document = next(
            (item for item in (extracted or {"documents": []})["documents"] if tuple(item["pages"]) == pages), None
        )  # fmt: skip
        keys = {
            value_key(item["provenance"]["page"], item["name_as_printed"], item["value_as_printed"])
            for item in (document or {}).get("observations", [])
        }
        if key not in keys:
            lost.append({"file_sha256": file_sha256, "pages": list(pages), "key": key,
                         "changes": line.get("changes"), "removed": bool(line.get("removed")),
                         "at": line.get("at"), "document_found": document is not None})  # fmt: skip
    return lost


def set_value(output: Path, file_sha256: str, pages: list[int], key: str, changes: dict | None, removed: bool = False) -> None:
    """Change the fields of one value, mark it as not a value at all, or take the change back.

    The file is named by its whole hash. A correction written against a shortened one matches
    nothing and is silently ignored, which is the worst way for a person's work to disappear.
    """
    if len(file_sha256) != 64:
        raise ValueError("a correction names the file by its whole sha256")
    line = {
        "file_sha256": file_sha256,
        "pages": pages,
        "field": "value",
        "key": key,
        "changes": {name: text for name, text in (changes or {}).items() if text not in (None, "")},
        "removed": removed,
        "by": "person",
        "at": records.now(),
    }
    _append(output, line)


def set_document_date(output: Path, file_sha256: str, pages: list[int], value: date | None) -> None:
    line = {
        "file_sha256": file_sha256,
        "pages": pages,
        "field": "document_date",
        "value": value.isoformat() if value else None,
        "by": "person",
        "at": records.now(),
    }
    _append(output, line)


def set_primary_copy(output: Path, file_sha256: str, pages: list[int], chosen: bool) -> None:
    """Which of several copies of one document stands for the group.

    The index picks one by itself — a lab report before a letter quoting it, a page read by the
    stronger model, fewer unreadable parts, more values. A person looking at the two scans knows
    things the rule cannot, so their choice is kept here, beside their other corrections, and
    wins over the rule at the next indexing as well as now.
    """
    _append(output, {
        "file_sha256": file_sha256, "pages": pages, "field": "primary_copy",
        "value": "chosen" if chosen else None, "by": "person", "at": records.now(),
    })  # fmt: skip


def load_primary_copies(output: Path) -> set[tuple[str, tuple[int, ...]]]:
    """The documents a person chose to stand for their group of copies."""
    return {
        (file_sha256, pages)
        for (file_sha256, pages, field) in load_corrections(output)
        if field == "primary_copy"
    }


def _append(output: Path, line: dict) -> None:
    records.append_line(output / FILE_NAME, line)

