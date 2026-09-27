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
from epicrisis.printed_values import number_as_printed
from epicrisis import records
from epicrisis.records import read_records
from epicrisis.printed_values import fold

FILE_NAME = layout.CORRECTIONS


# The fields of a printed value a person may put right, and the only ones the index takes from a
# correction. What was measured is not here on purpose: material has its own order of precedence
# — a person first, then the form, then a model — and index/build._material applies it.
CORRECTABLE = ("name_as_printed", "value_as_printed", "unit_as_printed", "reference_as_printed", "flag_as_printed")
# The key a corrected row carries its own correction under, for readers that need more than the
# changed fields: whether there was a correction at all, and the material a person set by hand.
BY_A_PERSON = "corrected_by_a_person"


def load_corrections(output: Path) -> dict[tuple, dict]:
    path = output / FILE_NAME
    latest: dict[tuple, dict] = {}
    if path.exists():
        for line in read_records(path):
            latest[(line["file_sha256"], tuple(line["pages"]), line["field"])] = line
    return {key: line for key, line in latest.items() if line.get("value")}


def value_key(page: int, name: str, value: str) -> str:
    """The short key, as corrections were written until now. Read, never written."""
    return "|".join((str(page), fold(name), re.sub(r"\s+", "", (value or "")).casefold()))


def line_key(observation: dict) -> str:
    """What tells one printed line of a page from another: its name, value, unit and range.

    The key was the page, the name and the value, and a form prints the same name and the same
    value twice on one page more often than it looks: a panel giving a count and a percentage, a
    range printed in two units, a summary repeating a line of the table above. On this archive 46
    groups of lines shared a key, and in eleven of them the lines differed by the printed unit or
    the printed range. A correction made on one of them was applied to both — the unit a person put
    right appeared on a line they had never opened, and a line they marked as not a value took its
    twin with it, both marked as corrected by a person.
    """
    printed = lambda text: re.sub(r"\s+", "", (text or "")).casefold()  # noqa: E731
    return "|".join((
        value_key(observation["provenance"]["page"], observation["name_as_printed"], observation["value_as_printed"]),
        printed(observation.get("unit_as_printed")),
        printed(observation.get("reference_as_printed")),
    ))  # fmt: skip


def load_value_corrections(output: Path) -> dict[tuple, dict]:
    """(file, pages, value key) to what a person changed: fields, or removed."""
    path = output / FILE_NAME
    latest: dict[tuple, dict] = {}
    if path.exists():
        # Where in the file each one stood. The clock keeps whole seconds and two corrections of
        # one line are easily written inside one, so the order they were appended in is what says
        # which came last — and that matters where a line carries a correction under the short key
        # and another under the long one.
        for place, line in enumerate(read_records(path)):
            if line.get("field") == "value":
                latest[(line["file_sha256"], tuple(line["pages"]), line["key"])] = {**line, "_place": place}
    return {key: line for key, line in latest.items() if line.get("changes") or line.get("removed")}


def as_a_person_left_it(observations: list[dict], file_sha256: str, pages: tuple,
                        value_corrections: dict) -> list[dict]:  # fmt: skip
    """The rows of a document with this archive's corrections on them, and the removed ones gone.

    One home for it, because there were two readings of the same document and they disagreed: the
    index was built from the corrected rows and the checks were run on the model's, so a value a
    person had put right went on being reported as wrong for ever, and a row they had marked as
    not a value went on producing findings. The list of work did not shrink as the work was done.
    """
    left = []
    # A key written before the unit and the range joined it still finds its line — but only where
    # it finds one line. Where the short key stands for two printed lines, applying the correction
    # to both is the very fault this key was widened to stop, so it is applied to neither and
    # counted as unmatched, which is what a person is shown.
    short_keys = [value_key(item["provenance"]["page"], item["name_as_printed"], item["value_as_printed"])
                  for item in observations]  # fmt: skip
    for observation in observations:
        short = value_key(observation["provenance"]["page"], observation["name_as_printed"], observation["value_as_printed"])
        # Both keys of one line, and the last word wins — which is the rule inside one key already.
        # A line corrected before the key was widened and again after it carries a correction under
        # each, and preferring either key over the other would make one of a person's two decisions
        # the older one, whichever they made last.
        candidates = [value_corrections.get((file_sha256, pages, line_key(observation)))]
        if short_keys.count(short) == 1:
            candidates.append(value_corrections.get((file_sha256, pages, short)))
        said = [one for one in candidates if one]
        correction = max(said, key=lambda one: one.get("_place", 0)) if said else None
        if correction and correction.get("removed"):
            continue  # a person said this line is not a value
        if not correction:
            left.append(observation)
            continue
        # The line a person wrote travels with the row under a name of its own. What they changed
        # is already on the row; what the row's reader still needs from the line is that there was
        # one at all, and the material, which is a person's word rather than a printed field.
        changed = {**observation, **{name: text for name, text in correction["changes"].items() if name in CORRECTABLE},
                   BY_A_PERSON: correction}  # fmt: skip
        # The number follows the value a person wrote. Without this the table showed 13,5 with a
        # "corrected" badge and the chart drew the model's 1,35, and the same stale number
        # answered "outside the printed range" over the network.
        if "value_as_printed" in correction["changes"]:
            changed["value_numeric"] = number_as_printed(changed)
        left.append(changed)
    return left


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
        lines = (document or {}).get("observations", [])
        short_keys = [value_key(item["provenance"]["page"], item["name_as_printed"], item["value_as_printed"])
                      for item in lines]  # fmt: skip
        keys = {line_key(item) for item in lines} | {one for one in short_keys if short_keys.count(one) == 1}
        if key not in keys:
            lost.append({"file_sha256": file_sha256, "pages": list(pages), "key": key,
                         "changes": line.get("changes"), "removed": bool(line.get("removed")),
                         "at": line.get("at"), "document_found": document is not None})  # fmt: skip
    return lost


def unmatched_documents(output: Path) -> list[dict]:
    """Corrections made on a whole document that no longer find a document.

    A date put in by hand, and the choice of which of several copies answers, are both kept
    against (the file, its pages). The pages are how the classification grouped them, and a page
    read again can be grouped differently — a two-page form becoming two documents, or two
    becoming one. Then the key matches nothing, the date a person typed silently stops applying,
    the document goes back to having no date and slides out of its year, and nothing counts it.

    Only the corrections on values were ever counted. These are the same kind of loss and they
    are quieter, because a value that loses its correction still shows a value.
    """
    from epicrisis.classify.report import document_keys

    groups = document_keys(output)
    lost = []
    for (file_sha256, pages, field), line in load_corrections(output).items():
        if field == "value" or (file_sha256, pages) in groups:
            continue
        lost.append({"file_sha256": file_sha256, "pages": list(pages), "field": field,
                     "value": line.get("value"), "at": line.get("at")})  # fmt: skip
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
        # An empty string is a person saying "the form printed nothing here", which is a correction
        # like any other: a unit or a range the model invented has to be removable. Only a field
        # that was not sent at all is dropped. Written as "not None and not empty", the one way to
        # take a wrong unit off a line did nothing and said nothing.
        "changes": {name: text for name, text in (changes or {}).items() if text is not None},
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

