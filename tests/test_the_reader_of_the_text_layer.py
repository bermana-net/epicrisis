"""Which library reads the text layer of a PDF, and what every refusal of that reader still is.

The reader was pypdf and is pdfium, through pypdfium2 — the library that already renders a page
as a picture. The owner of a live archive was shown what the change does to the text of his own
pages and chose it; these tests are the other half of that, the part that is not about his
archive at all. They are the shapes a reader of a PDF has to go on refusing, invented here, in
one place, because the live archive holds none of them and a measurement on it is blind to every
shape it does not happen to contain.

Nothing here is about speed. A test on seconds is a test that fails on somebody else's machine.
"""

import io
import re

import pypdfium2
import pytest
from pypdf import PasswordType, PdfReader, PdfWriter

from epicrisis.classify.pages import page_refs
from epicrisis.inventory import probes
from epicrisis.printed_values import number_tokens, numbers_in_text
from epicrisis.readers import pdf
from tests.test_inventory import SYNTHETIC_TEXT, make_text_pdf

# A row of a form as a form prints one: the name of the test, the result, the printed range, in
# three columns, with a second row under it. Which is the whole question a reader of a text layer
# answers — a page of one line in one place has no order for a reader to get wrong.
A_ROW_OF_A_FORM = [
    [(72, 700, "Analyte"), (300, 700, "6,8"), (420, 700, "4,0 - 9,0"),
     (72, 680, "Second analyte"), (300, 680, "707"), (420, 680, "404 - 909")],
]


def written(tmp_path, name: str, pages, rotate: int | None = None) -> bytes:
    path = tmp_path / name
    make_text_pdf(path, pages, rotate=rotate)
    return path.read_bytes()


def pdfium_itself(data: bytes, index: int = 0) -> str:
    document = pypdfium2.PdfDocument(data, password="")
    try:
        page = document[index]
        textpage = page.get_textpage()
        try:
            return textpage.get_text_range()
        finally:
            textpage.close()
            page.close()
    finally:
        document.close()


def pypdf_itself(data: bytes, index: int = 0) -> str:
    return PdfReader(io.BytesIO(data)).pages[index].extract_text() or ""


def test_the_text_layer_comes_from_pdfium_and_not_from_pypdf(tmp_path):
    """The whole of the change, as one assertion, on a shape where the two do not agree.

    They agree on the characters and not on the spaces between them: pypdf ends a line of a page
    with "\\n" and pdfium with "\\r\\n". That is the smallest difference the two have on a page
    simple enough to invent, and it is enough to say which of them answered.
    """
    data = written(tmp_path, "form.pdf", A_ROW_OF_A_FORM)
    read = pdf.text_of(data, page_refs({"sha256": "a" * 64, "category": "pdf",
                                        "pdf": pdf.probe(io.BytesIO(data), "application/pdf")})[0])

    assert read == pdfium_itself(data)
    assert read != pypdf_itself(data)
    # And the characters themselves are the same characters: this is a reading of one page, not
    # another page. Whitespace aside, nothing of the form was gained or lost — which is why the
    # check that asks whether a printed value is on the page it claims to come from sees exactly
    # what it saw: it squeezes the whitespace out of both sides before it looks.
    assert re.sub(r"\s+", "", read) == re.sub(r"\s+", "", pypdf_itself(data))
    for printed in ("6,8", "4,0 - 9,0", "707", "404 - 909"):
        assert numbers_in_text(printed, read), printed
    # What does move is the cutting of the page into numbers, because one space between two
    # columns is the space a form groups thousands with. tests/printed-shapes.json holds the
    # row this happens to and what each reader makes of it; ten pages of one live archive moved
    # that way, and nothing places a value by it.
    assert "707 404" in number_tokens(read)


def test_a_form_fed_in_sideways_reads_the_same_way_round_as_one_that_was_not(tmp_path):
    """A turned page is a page, and /Rotate is not an excuse to read the row backwards.

    The live archive holds no PDF turned by its /Rotate, so nothing measured on it says what a
    new reader does with one. Both libraries read a turned page the right way round; what this
    pins is that the reader this program uses does.
    """
    upright = written(tmp_path, "upright.pdf", A_ROW_OF_A_FORM)
    sideways = written(tmp_path, "sideways.pdf", A_ROW_OF_A_FORM, rotate=90)

    assert pdf._pdf_text(sideways, 0) == pdf._pdf_text(upright, 0)
    assert "Analyte 6,8 4,0 - 9,0" in pdf._pdf_text(sideways, 0)
    assert pdf.probe(io.BytesIO(sideways), "application/pdf")["pages"] == 1


def test_a_file_only_a_password_opens_is_refused_before_the_text_reader_is_asked(tmp_path):
    """pypdf is kept for this one question, because pdfium cannot tell it from a damaged file.

    Asked for such a file, pdfium raises the same error it raises for a file of rubbish. The
    inventory has to say "encrypted" and not "damaged", because the two have different answers:
    one needs the password and the other needs the file again.
    """
    plain = tmp_path / "plain.pdf"
    make_text_pdf(plain, [SYNTHETIC_TEXT])
    writer = PdfWriter(clone_from=plain)
    writer.encrypt(user_password="a-password-nobody-here-has", owner_password="synthetic-owner", algorithm="AES-256")
    locked = tmp_path / "locked.pdf"
    writer.write(locked)
    data = locked.read_bytes()

    facts = pdf.probe(locked, "application/pdf")

    assert facts == {"encrypted": True}
    assert page_refs({"sha256": "b" * 64, "category": "pdf", "pdf": facts}) == []
    reader = PdfReader(io.BytesIO(data))
    assert reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED
    with pytest.raises(pypdfium2.PdfiumError):
        pypdfium2.PdfDocument(data, password="")


def test_an_encrypted_file_the_empty_password_opens_is_read_whole(tmp_path):
    """The other half of the one above: locked on paper, open to anybody, and read as text."""
    plain = tmp_path / "plain.pdf"
    make_text_pdf(plain, [SYNTHETIC_TEXT])
    writer = PdfWriter(clone_from=plain)
    writer.encrypt(user_password="", owner_password="synthetic-owner", algorithm="AES-256")
    locked = tmp_path / "open-to-anybody.pdf"
    writer.write(locked)

    facts = pdf.probe(locked, "application/pdf")

    assert (facts["encrypted"], facts["pages"], facts["text_layer"]) == (True, 1, "full")
    assert "hemoglobin" in pdf._pdf_text(locked.read_bytes(), 0)


@pytest.mark.parametrize(
    ("name", "data"),
    [("rubbish", b"%PDF-1.4\nthis is not a pdf body\n"), ("nothing at all", b"")],
    ids=["a-body-that-is-not-one", "no-bytes-at-all"],
)
def test_a_damaged_file_raises_rather_than_reading_as_a_page_with_no_text(name, data):
    """The eighth entry of the constitution, at the one door a damaged file comes in by.

    A reader that answers "empty" about a file it could not read is how an archive loses what was
    on it: the inventory would write down a page with no text layer, the page would go to a model
    as a picture of nothing, and nothing anywhere would say the file had never been opened.
    """
    with pytest.raises(Exception) as refused:  # noqa: B017 - which exception is the library's own
        pdf.probe(io.BytesIO(data), "application/pdf")
    assert not isinstance(refused.value, AssertionError)

    with pytest.raises(pypdfium2.PdfiumError):
        pdf._pdf_text(data, 0)


def test_a_page_the_file_does_not_have_is_refused_and_not_answered(tmp_path):
    """Both libraries count the pages of a file, and probe numbers them with pypdf's count.

    The number of a page is an address a person follows from a value back to the page it was
    printed on, so it may not move when the reader of the text layer changes. It does not: the
    count comes from the same library it came from before, and the text of page n is asked of
    pdfium by that same n. A file the two counted differently would raise here, at the index,
    rather than quietly reporting the pages they agree about.
    """
    data = written(tmp_path, "three.pdf", [SYNTHETIC_TEXT] * 3)

    assert pdf.probe(io.BytesIO(data), "application/pdf")["pages"] == 3
    assert len(PdfReader(io.BytesIO(data)).pages) == len(pypdfium2.PdfDocument(data, password=""))
    with pytest.raises(Exception) as refused:  # noqa: B017 - the library's own, not ours
        pdf._pdf_text(data, 3)
    assert not isinstance(refused.value, AssertionError)


def test_a_page_of_a_stamp_a_page_of_nothing_and_a_page_only_just_a_text_layer(tmp_path):
    """The counting that decides whether a page goes to a model as words or as a picture.

    The third of the three is the one that can move: a page a few characters over the threshold
    goes as text, and a reader that lost a few characters of it would send it as a picture
    instead — the pass would pay for a vision call, and a model would read a photograph of a page
    whose words were there to be had. Its line is printed wider than the paper, because a reader
    asked for the text of the page *box* rather than of the page is how those characters go
    missing, and that is the mistake this is here to catch.
    """
    stamped = written(tmp_path, "stamped.pdf", ["01", "PAGE 02 OF 02"])
    facts = pdf.probe(io.BytesIO(stamped), "application/pdf")

    assert facts["text_layer"] == "none" and facts["pages_with_text"] == 0
    assert all(0 < chars < probes.MIN_TEXT_CHARS_PER_PAGE for chars in facts["text_chars_per_page"])
    assert [route for route, _part, _document in pdf.pages({"pdf": facts})] == ["vision", "vision"]

    empty = written(tmp_path, "empty-page.pdf", [" "])
    bare = pdf.probe(io.BytesIO(empty), "application/pdf")
    assert bare["text_chars_per_page"] == [0] and bare["text_layer"] == "none"

    only_just = written(tmp_path, "only-just.pdf", ["a" * (probes.MIN_TEXT_CHARS_PER_PAGE + 10)])
    barely = pdf.probe(io.BytesIO(only_just), "application/pdf")
    assert barely["text_chars_per_page"] == [probes.MIN_TEXT_CHARS_PER_PAGE + 10]
    assert barely["text_layer"] == "full"
    assert [route for route, _part, _document in pdf.pages({"pdf": barely})] == ["text"]


def test_a_page_longer_than_what_goes_to_a_model_is_still_cut_at_that_one_number(tmp_path):
    long_enough = "a" * (probes.MAX_TEXT_CHARS + 500)
    data = written(tmp_path, "long.pdf", [long_enough])

    assert len(pdf._pdf_text(data, 0)) == probes.MAX_TEXT_CHARS
    assert pdf.probe(io.BytesIO(data), "application/pdf")["text_chars_per_page"][0] > probes.MAX_TEXT_CHARS


