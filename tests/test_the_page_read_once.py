"""The text layer of a PDF page, read once in a pass over an archive and not four times.

Four steps ask for the same page of the same file in one pass — the inventory, to see whether the
page has a text layer at all; classify; extract; the checks — and taking a page apart in pure
Python is where more than 80% of the checks' time went on a live archive. The four readings cannot
differ, so the first one is kept.

Every test here counts readings rather than seconds. A test on time is a test that fails on
somebody else's machine, and these have to say what changed, not how fast this computer is.
"""

import hashlib
import io
import tempfile
from pathlib import Path

import pypdfium2
import pytest

from epicrisis.classify.pages import document_payloads, materialize, page_refs
from epicrisis.inventory import probes
from epicrisis.readers import pdf
from tests.test_inventory import SYNTHETIC_TEXT, make_text_pdf

PAGES_OF_THE_FORM = 3


@pytest.fixture
def readings(monkeypatch):
    """How many times the library was asked for the text of a page.

    The library and not `pdf._taken_apart`: a count of this program's own function would still
    read one if that function were the thing that stopped asking, and what these tests are about
    is how often the page is taken apart underneath. pdfium is the reader of the text layer; the
    one before it was pypdf and this fixture counted `extract_text` the same way.
    """
    counted = []
    original = pypdfium2.PdfTextPage.get_text_range

    def counting(self, *args, **kwargs):
        counted.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pypdfium2.PdfTextPage, "get_text_range", counting)
    return counted


@pytest.fixture
def form(tmp_path) -> Path:
    """A printed form of several pages, each with a text layer. Invented, like every file here."""
    path = tmp_path / "archive" / "form.pdf"
    path.parent.mkdir()
    make_text_pdf(path, [SYNTHETIC_TEXT] * PAGES_OF_THE_FORM)
    return path


def test_one_page_asked_for_twice_in_a_pass_is_taken_apart_once(form, readings):
    data = form.read_bytes()
    with pdf.remembering_page_text():
        first = pdf._pdf_text(data, 0)
        del readings[:]
        again = pdf._pdf_text(data, 0)

    assert not readings, "the page was taken apart a second time inside one pass"
    assert again == first


def test_what_a_pass_remembers_is_character_for_character_what_the_library_gives(form):
    """The whole permission for remembering: the text does not change, so nothing below it does."""
    data = form.read_bytes()
    straight = [pdf._pdf_text(data, index) for index in range(PAGES_OF_THE_FORM)]
    with pdf.remembering_page_text():
        [pdf._pdf_text(data, index) for index in range(PAGES_OF_THE_FORM)]
        remembered = [pdf._pdf_text(data, index) for index in range(PAGES_OF_THE_FORM)]

    assert remembered == straight
    for one, other in zip(straight, remembered, strict=True):
        assert list(one) == list(other)


def test_outside_a_pass_nothing_is_remembered_and_nothing_is_kept(form, readings):
    """A page viewed on the dashboard is read as it always was, and leaves nothing behind.

    The constitution's first entry is why: what this holds is text printed on somebody's
    documents, and a dictionary beside the instance that fills up with every page anybody clicks
    on for as long as the server runs is the shape that rule was written about.
    """
    data = form.read_bytes()
    with pdf.remembering_page_text():
        pdf._pdf_text(data, 0)
    assert not pdf._REMEMBERED, "a pass left somebody's page text behind it"

    del readings[:]
    pdf._pdf_text(data, 0)
    pdf._pdf_text(data, 0)
    assert len(readings) == 2
    assert not pdf._REMEMBERED


def test_the_inventory_and_the_page_sent_to_a_model_share_one_reading(form, readings):
    """probe reads every page to see whether it has a text layer; the steps then read them again."""
    data = form.read_bytes()
    with pdf.remembering_page_text():
        probed = pdf.probe(io.BytesIO(data), "application/pdf")
        after_the_inventory = len(readings)
        texts = [pdf._pdf_text(data, index) for index in range(PAGES_OF_THE_FORM)]

    assert after_the_inventory == PAGES_OF_THE_FORM
    assert len(readings) == PAGES_OF_THE_FORM, "the pages were taken apart twice over"
    assert probed["pages_with_text"] == PAGES_OF_THE_FORM
    assert all(text.strip() for text in texts)


def _four_steps(record: dict, root: Path) -> list:
    """The inventory, classify, extract and the checks, in the order one pass runs them."""
    refs = page_refs(record)
    with tempfile.TemporaryDirectory() as workdir:
        for ref in refs:  # classify asks for one page at a time
            materialize(ref, root, Path(workdir))
        document_payloads(refs, root, Path(workdir))  # extract
        document_payloads(refs, root, Path(workdir))  # the checks
    return refs


def test_four_steps_over_one_document_take_each_page_apart_once(tmp_path, form, readings):
    """The count this was written for: four readings of a page in one pass before, one after."""
    root = tmp_path / "archive"
    data = form.read_bytes()

    def a_pass() -> tuple[int, list]:
        del readings[:]
        record = {"sha256": hashlib.sha256(data).hexdigest(), "path": form.name, "category": "pdf",
                  "pdf": pdf.probe(io.BytesIO(data), "application/pdf")}  # the inventory
        refs = _four_steps(record, root)
        return len(readings), refs

    in_a_pass, refs = None, None
    with pdf.remembering_page_text():
        in_a_pass, refs = a_pass()
    without_a_pass, _ = a_pass()

    assert [ref.route for ref in refs] == ["text"] * PAGES_OF_THE_FORM
    assert without_a_pass == 4 * PAGES_OF_THE_FORM
    assert in_a_pass == PAGES_OF_THE_FORM


def test_a_file_that_changed_is_read_again_rather_than_answered_from_the_old_one(tmp_path, readings):
    """Remembered by what the bytes hash to, so a rescanned file cannot be answered by its past."""
    rescanned = tmp_path / "rescanned.pdf"
    make_text_pdf(rescanned, [SYNTHETIC_TEXT])
    was = rescanned.read_bytes()
    make_text_pdf(rescanned, [SYNTHETIC_TEXT + " repeat sample"])
    now = rescanned.read_bytes()

    with pdf.remembering_page_text():
        before = pdf._pdf_text(was, 0)
        del readings[:]
        after = pdf._pdf_text(now, 0)

    assert len(readings) == 1
    assert after != before and "repeat sample" in after


def test_a_page_longer_than_what_goes_to_a_model_is_cut_where_it_always_was(form):
    """One text serves both: the inventory counts the whole page, a model is sent the first part."""
    long_enough = "a" * (probes.MAX_TEXT_CHARS + 500)
    path = form.with_name("long.pdf")
    make_text_pdf(path, [long_enough])
    data = path.read_bytes()

    with pdf.remembering_page_text():
        probed = pdf.probe(io.BytesIO(data), "application/pdf")
        assert len(pdf._pdf_text(data, 0)) == probes.MAX_TEXT_CHARS
    assert probed["text_chars_per_page"][0] > probes.MAX_TEXT_CHARS
