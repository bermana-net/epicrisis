"""The page of one scan asked directly: what it shows around the image, and why it sometimes cannot.

This page was the image alone, opened in a tab of its own — no page number, no name of the file it
came from, no way to the next page of the same form and no way back. Checking a four-page form
against its card meant four tabs and no captions. And where a page is text rather than a picture
it drew an <img> at an address that answered 409: a broken image in the middle of the one page
this program promises is always one click away from a value.

What it gathers is in `epicrisis/web/documents.py` now, beside the card it offers a way back to.
"""

import ast
import inspect
from pathlib import Path

from test_extract import FakeExtractBackend, setup  # noqa: F401

from epicrisis import layout
from epicrisis.inventory.run import write_inventory
from epicrisis.records import read_records
from epicrisis.web import documents as the_pages
from epicrisis.web.documents import nothing_read_yet, one_scanned_page, record_path, the_scan_at


def test_the_page_of_one_scan_gathers_what_stands_around_the_image(setup):  # noqa: F811
    """The page number, the name of the file, the way on and the way back."""
    data_dir, source, output, records = setup
    labs = records["labs.pdf"]

    first = one_scanned_page(source, output, labs["sha256"], 1)
    assert first is not None, "the first page of a file this archive holds was not found"
    assert first["current"] == "documents"
    assert first["source_id"] == source.id and first["sha256"] == labs["sha256"]
    assert first["page"] == 1
    assert first["path"] == "labs.pdf", "the name of the file the page came from"
    assert first["previous"] is None, "there is nothing before the first page"
    assert first["pages"] == sorted(first["pages"]) and 1 in first["pages"]
    if len(first["pages"]) > 1:
        assert first["next"] == first["pages"][1]
        last = one_scanned_page(source, output, labs["sha256"], first["pages"][-1])
        assert last["next"] is None and last["previous"] == first["pages"][-2]
    assert set(first) >= {"cannot_be_shown", "as_text", "document"}


def test_a_page_the_reading_does_not_hold_is_nothing_rather_than_a_half_drawn_page(setup):  # noqa: F811
    data_dir, source, output, records = setup
    labs = records["labs.pdf"]["sha256"]

    assert one_scanned_page(source, output, labs, 9999) is None
    assert one_scanned_page(source, output, "0" * 64, 1) is None
    assert the_scan_at(source, output, labs, 9999) is None
    assert the_scan_at(source, output, "0" * 64, 1) is None


def test_an_archive_nothing_has_been_read_from_is_its_own_answer(setup, tmp_path):  # noqa: F811
    """Two dead ends and not one, because they are different sentences: an archive whose folder
    has not been walked yet is answered as the archive having been switched, which is what it is
    from the reader's side, and a page the walk does not hold is answered as the address."""
    data_dir, source, output, records = setup
    assert nothing_read_yet(output) is False
    assert nothing_read_yet(tmp_path / "a folder nothing was read from") is True


def test_the_image_and_the_page_around_it_agree_about_which_page_that_is(setup):  # noqa: F811
    """The image is an address of its own — the page above links to it in so many words — so the
    two ask the same question of the same reading, and a page the one finds the other finds."""
    data_dir, source, output, records = setup
    labs = records["labs.pdf"]["sha256"]
    for page in one_scanned_page(source, output, labs, 1)["pages"]:
        assert the_scan_at(source, output, labs, page) is not None, page
        assert one_scanned_page(source, output, labs, page) is not None, page


def test_the_name_of_the_file_is_the_name_and_not_the_folder_it_sits_in(setup):  # noqa: F811
    """The folder a person keeps their scans in is a path with a surname in it often enough."""
    data_dir, source, output, records = setup
    labs = records["labs.pdf"]["sha256"]
    said = record_path(source, output, labs)
    assert said.endswith("labs.pdf")
    assert one_scanned_page(source, output, labs, 1)["path"] == "labs.pdf"


def test_a_page_that_is_text_and_not_a_picture_is_shown_as_its_text(setup):  # noqa: F811
    """There is no picture of a sheet of a workbook or of a text file anywhere, and this page drew
    an <img> at an address that answered 409: a broken image in the middle of the one page this
    program promises is always one click away from a value.

    The shape is invented here, because the archive this fixture builds is three PDFs and has
    none of it — §6 of the constitution, and the defect it was written for. A plain text file is
    the simplest page that has no picture anywhere.
    """
    data_dir, source, output, records = setup
    typed = Path(source.path) / "2019" / "a note of this test.txt"
    typed.write_text("a line of this test, printed nowhere\n", encoding="utf-8")
    write_inventory(Path(source.path), output / layout.INVENTORY)
    again = {record["name"]: record for record in read_records(output / layout.INVENTORY)}
    assert typed.name in again, "the walk did not find the page this test invented"

    shown = one_scanned_page(source, output, again[typed.name]["sha256"], 1)

    assert shown is not None, "a page that is text is still a page of this archive"
    assert shown["as_text"] is not None or shown["cannot_be_shown"], (
        "a page with no picture offers neither its text nor a reason")
    if shown["as_text"] is not None:
        assert "printed nowhere" in shown["as_text"]
        assert shown["cannot_be_shown"] == "", "the text is shown and a refusal is said as well"

    # And every PDF page beside it still answers as a picture, or says why it cannot.
    for name in (one for one in records if one.endswith(".pdf")):
        beside = one_scanned_page(source, output, records[name]["sha256"], 1)
        assert beside is not None and beside["as_text"] is None, name


def test_which_archive_comes_in_as_an_argument_with_no_default(setup):  # noqa: F811
    for door in (one_scanned_page, the_scan_at, record_path):
        asked = inspect.signature(door).parameters
        assert asked["source"].default is inspect.Parameter.empty, door.__name__
        assert asked["output"].default is inspect.Parameter.empty, door.__name__


def test_nothing_in_this_module_knows_about_the_web():
    """The routes are the shells, read off the imports rather than the text."""
    reached = set()
    for node in ast.walk(ast.parse(inspect.getsource(the_pages))):
        if isinstance(node, ast.Import):
            reached |= {one.name for one in node.names}
        elif isinstance(node, ast.ImportFrom):
            reached.add(node.module or "")
    assert reached
    for name in sorted(reached):
        assert name.split(".")[0] in ("epicrisis", "collections", "datetime", "pathlib", "re",
                                      "markupsafe"), name  # fmt: skip
