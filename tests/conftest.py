"""What the tests share, in one place.

Fixtures used to be imported from one test module into another — `test_extract` was the de facto
conftest and `test_inventory` the helper library — so a file could not be renamed without
breaking three others, and two different fixtures called `setup` returned four-tuples in
different orders. Everything here is what more than one file needs; anything only one file needs
stays in that file.
"""

import json
from pathlib import Path

import pytest

from epicrisis.records import now


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
