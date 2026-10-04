"""What the tests share, in one place.

Fixtures used to be imported from one test module into another — `test_extract` was the de facto
conftest and `test_inventory` the helper library — so a file could not be renamed without
breaking three others, and two different fixtures called `setup` returned four-tuples in
different orders. Everything here is what more than one file needs; anything only one file needs
stays in that file.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from epicrisis.records import now

# The day an illustration in these tests is dated, and the only place it is written down.
#
# It was 8 July 2019 until this was written, and that is the hour a sample was taken on a
# Ukrainian laboratory form in the archive this program was built for. It had reached nine files
# by then, which is the whole reason it is here: the fifth entry of the constitution says an
# invented name is looked for in the archives before it is written down, and nobody looks in nine
# places. 9 July 2011 was looked for in every live index — as a document's date, as a printed
# date, in every page's text and in every value's snippet, in both number orders and in the month
# names of all five languages — and is in none of them.
#
# How far that goes is worth knowing, because it is not far. The tests write down 154 distinct
# days and the archives hold 736 documents over thirty-seven years, so 56 of those days already
# coincide with a date printed somewhere, by chance and not by carelessness. A bare day with no
# name, no institution and no value beside it names nobody, which is why those are left alone; a
# check for dates in tools/nothing-of-yours.py would be 56 refusals nobody can clear. What is
# worth keeping deliberate is this one — the day the example values of the archive are dated,
# where a reader would take the coincidence for a copy of a real form.
A_DAY_FOR_AN_ILLUSTRATION = date(2011, 7, 9)

# The same day as the forms here print one: day first, with full stops.
AS_A_FORM_PRINTS_IT = A_DAY_FOR_AN_ILLUSTRATION.strftime("%d.%m.%Y")

# And the day a form prints as somebody's date of birth, which is never the date of a document.
# Kept apart because an illustration of one is no use as an illustration of the other, and looked
# for in the same way: 14 March 1961 is in no live index either.
A_DAY_OF_BIRTH_FOR_AN_ILLUSTRATION = date(1961, 3, 14)


@pytest.fixture
def archive_folder(tmp_path: Path) -> Path:
    """An empty folder standing in for somebody's box of scans."""
    folder = tmp_path / "archive"
    folder.mkdir()
    return folder


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Where this instance keeps what it derives. Never inside the archive."""
    folder = tmp_path / "data"
    folder.mkdir()
    return folder


def classify_line(file_sha256: str, page: int = 1, **changes) -> dict:
    """One line of classify.jsonl, in the shape the pipeline actually writes.

    Seven tests wrote this by hand with four different sets of keys; a field added to the real
    line would have been missing from all seven and noticed by none.
    """
    line = {
        "file_sha256": file_sha256,
        "page": page,
        "route": "vision",
        "doc_type": "lab_panel",
        "page_role": "first",
        "language": "en",
        "date_on_page": None,
        "provider_on_page": None,
        "has_tabular_results": True,
        "legible": True,
        "confidence": 0.95,
        "model": "test",
        "prompt_version": "test",
        "at": now(),
    }
    return {**line, **changes}


def write_lines(path: Path, lines: list[dict]) -> Path:
    """A .jsonl file written whole, for a test that needs one to exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines), encoding="utf-8")
    return path
