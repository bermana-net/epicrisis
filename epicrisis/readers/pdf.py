"""A PDF: the kind of file an archive is mostly made of.

Its pages are real pages, printed by whoever made it, and each of them is one of two things: a
page with a text layer, which goes to a model as text, or a page that is a photograph of paper,
which goes as a picture. One file holds both kinds. See epicrisis/readers/__init__.py for what
every reader of a kind of file answers.

**Two libraries, and which question each answers.** The text layer of a page is read by pdfium,
through pypdfium2 — the same library that already renders a page as a picture. What a file *is*
is still read by pypdf: whether it is encrypted and whether the empty password opens it, and
whether a page has a picture pasted inside it, which is a walk of the page's own resource
dictionary that pdfium does not expose. Neither library answers a question the other one also
answers, so the two can never disagree about one fact.

The reader of the text layer is not an implementation detail, and it is named here because the
owner of an archive was shown what changing it does and decided it. The two libraries read the
same page differently: the characters are the same characters, and the spaces between them fall
elsewhere. Where a form prints a row as a label, a result and a printed range in three columns,
pypdf can give back the range, then the result with no space after it, then the label — one
printed number ending up joined to the next, and the label of the row at the end of it; pdfium
gives the three in the order the row is printed in. On the 236 pages of one live archive that go
to a model as words, 0 came out identical character for character, 104 differed in whitespace
alone, and 54 of them changed what `printed_values.number_tokens` reads out of the page. No page
changed route: 630 pages of 169 files, and every one has a text layer where it had one and none
where it had none.

**The one thing pdfium reads as less than the page prints.** Where a word is broken across a
line by a hyphen the font draws as a soft hyphen, pdfium answers U+FFFE — the code Unicode sets
aside for "this is not a character" — and pypdf answered the hyphen. Sixteen characters of one
live archive, on 14 pages of 5 files, every one of them inside a word and none of them inside a
number or a printed range. It is left as it comes, because what the form prints there is a hyphen
and what this program has is a library saying it does not know: putting the hyphen back would be
this program deciding what was printed, which is the second entry of the constitution, and taking
the character out would lose a character the page has. It is counted as garbled by
`probes.text_looks_garbled`, which is the right answer and is nowhere near the share that would
send a page as a picture — one or two characters in a page of a thousand.

What it costs is one finding: on the archive measured, one stored value whose printed form holds
such a hyphen can no longer be found in the text of its own page, so the check that looks for it
says "look at this" where it used to say nothing. The value itself is untouched, as is every
other stored value, and no chart moved.
"""

import hashlib
import io
import logging
import threading
from contextlib import contextmanager
from pathlib import Path

import pypdfium2
from PIL import Image
from pypdf import PasswordType, PdfReader

from epicrisis.inventory.probes import (
    MAX_TEXT_CHARS,
    MIN_TEXT_CHARS_PER_PAGE,
    Source,
    _visible_chars,
    text_looks_garbled,
)

logging.getLogger("pypdf").setLevel(logging.ERROR)

PDFIUM_LOCK = threading.Lock()
MAX_IMAGE_EDGE = 1600
MAX_RENDER_DPI = 200
# Second pass for small print: the page is rendered larger and cut into four overlapping
# quarters, each sent at MAX_IMAGE_EDGE, which gives the model about twice the detail.
ZOOM_RENDER_EDGE = 3200
ZOOM_RENDER_DPI = 300

# How much of an archive's text layer one pass may hold at once, counted in characters. A live
# archive of 148 PDF files and 580 pages comes to 339,194 characters, about 0.6 MB of Python
# strings, so this is a hundred archives of that size and a sixtieth of the memory of the machine
# this was measured on. Past it the pass stops remembering and reads as it did before: slower,
# never wrong.
MAX_REMEMBERED_CHARS = 32_000_000

_REMEMBERED_LOCK = threading.Lock()
_REMEMBERED: dict[tuple[str, int], str] = {}
_REMEMBERED_CHARS = 0
_PASSES = 0


@contextmanager
def remembering_page_text():
    """For as long as this is held, the text layer of a PDF page is read once and then reused.

    Four steps read the same page of the same file in one pass over an archive: the inventory, to
    see whether the page has a text layer at all; classify; extract; and the checks. On a live
    archive of 439 documents the inventory read 580 pages in 11.8 s and the checks read 200 of
    those same pages again in 15.8 s, of which 12.9 s was pypdf taking a page apart — more than
    80% of the step. The four readings cannot differ: same bytes, same page, same library. So the
    first one is kept and the rest are given it.

    The library underneath is pdfium now rather than pypdf. The same two steps on the same live
    archive went from 12.1 s to 3.3 s and from 15.9 s to 5.9 s, and this is still here for the
    reason it was built: a reading that costs a hundredth of a second is still a reading, four of
    them are still four, and what makes them one is this and not the speed of either library.

    It is held for a pass and not for the life of the process on purpose, and the reason is the
    first entry of the constitution. What this holds is text printed on somebody's documents, and
    such a thing belongs inside the archive it came from; a dictionary beside the instance, living
    as long as `serve` does and filling with every page anybody clicks on, is the shape that rule
    was written about. A pass over one archive enters this and leaves it, and nothing printed
    survives the leaving.

    Nothing outside a pass is wrong without it, only slower: every reader of a page text asks
    through here, and with no pass open the question goes straight to the library as it always did.
    """
    global _REMEMBERED, _REMEMBERED_CHARS, _PASSES
    with _REMEMBERED_LOCK:
        _PASSES += 1
    try:
        yield
    finally:
        with _REMEMBERED_LOCK:
            _PASSES -= 1
            if not _PASSES:
                _REMEMBERED = {}
                _REMEMBERED_CHARS = 0


def _remembered(key: tuple[str, int]) -> str | None:
    with _REMEMBERED_LOCK:
        return _REMEMBERED.get(key) if _PASSES else None


def _remember(key: tuple[str, int], text: str) -> None:
    global _REMEMBERED_CHARS
    with _REMEMBERED_LOCK:
        if not _PASSES or key in _REMEMBERED or _REMEMBERED_CHARS + len(text) > MAX_REMEMBERED_CHARS:
            return
        _REMEMBERED[key] = text
        _REMEMBERED_CHARS += len(text)


def _taken_apart(data: bytes, index: int) -> str:
    """One page's text layer as pdfium gives it, every character and not one character more.

    Every character: the text of the whole page and not of the page box, because the box leaves
    out what is printed past its edge. Asked the other way round, on one live archive, five pages
    of four files came back 2 to 30 characters shorter than the page has — and a number printed in
    a margin is a number printed. A page turned by its own /Rotate loses most of itself that way,
    which is a shape no archive here holds yet and tests/test_the_reader_of_the_text_layer.py
    invents.

    PDFium is not thread-safe, so the file is opened, read and closed inside the one lock the
    rendering of a page already takes. Opening the file and taking one page out of it together
    cost a thirteenth of what taking one page apart used to cost — 236 pages of that archive in
    1.3 s against 17.5 s — so a page is opened for and closed after, and nothing is held open
    between two of them.
    """
    with PDFIUM_LOCK:
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


def _page_text(data: bytes, digest: str, index: int) -> str:
    """One page's text layer, whole and untouched, read once per pass over the archive.

    Keyed by what the bytes hash to rather than by which file they came from: the same page of the
    same content is the same text, and a file that changed under the archive hashes differently
    and so is read again. Every page text of a PDF in this program comes from here.

    The file is opened only where the page has to be read, so a page already read in this pass
    costs the hash of the bytes and nothing else.
    """
    key = (digest, index)
    kept = _remembered(key)
    if kept is not None:
        return kept
    text = _taken_apart(data, index)
    _remember(key, text)
    return text


def _bytes_of(source: Source) -> bytes:
    """The whole file, which is what pypdf makes of a path anyway, and what the hash needs."""
    if isinstance(source, Path):
        return source.read_bytes()
    source.seek(0)
    return source.read()


def probe(source: Source, mime: str) -> dict:
    """What is true of this file. pypdf answers what the file is; pdfium reads the text layer.

    The lock on the file comes first and is pypdf's answer, because it is the one library here
    that can say whether the empty password opens an encrypted file or whether nobody can read it
    without one; pdfium refuses the second kind and cannot tell it from a damaged file. A file
    nobody can open returns here and pdfium is never asked about it.
    """
    data = _bytes_of(source)
    digest = hashlib.sha256(data).hexdigest()
    reader = PdfReader(io.BytesIO(data))
    encrypted = reader.is_encrypted
    if encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
        return {"encrypted": True}

    chars_per_page = []
    garbled_pages = []
    has_images = False
    # pypdf's pages, for two reasons. The picture pasted into a page is read out of that page's
    # own resource dictionary, which pdfium does not hand over. And this count is what numbers the
    # pages of every document in the archive — the number a person follows from a value back to
    # the page it was printed on — so moving it would move page numbers already written down,
    # which is the one thing a change of reader may not do. The two libraries agree on it anyway:
    # 630 pages of 169 files of this archive, every file the same count either way. A file where
    # they did not agree comes apart here, at the index, and is recorded as damaged rather than
    # quietly read short.
    for number, page in enumerate(reader.pages, 1):
        text = _page_text(data, digest, number - 1)
        chars_per_page.append(_visible_chars(text))
        if chars_per_page[-1] >= MIN_TEXT_CHARS_PER_PAGE and text_looks_garbled(text):
            garbled_pages.append(number)
        has_images = has_images or _has_images(page.get("/Resources"))

    pages = len(chars_per_page)
    pages_with_text = sum(1 for chars in chars_per_page if chars >= MIN_TEXT_CHARS_PER_PAGE) - len(garbled_pages)
    if pages and pages_with_text == pages:
        text_layer = "full"
    elif pages_with_text:
        text_layer = "partial"
    else:
        text_layer = "none"

    return {
        "encrypted": encrypted,
        "pages": pages,
        "pages_with_text": pages_with_text,
        "text_layer": text_layer,
        "text_chars_per_page": chars_per_page,
        "garbled_text_pages": garbled_pages,
        "has_images": has_images,
    }

def _has_images(resources, depth: int = 0) -> bool:
    # Images sit in the page's XObject resources, possibly nested inside Form XObjects.
    if resources is None or depth > 5:
        return False
    xobjects = resources.get_object().get("/XObject")
    if xobjects is None:
        return False
    for ref in xobjects.get_object().values():
        xobject = ref.get_object()
        subtype = xobject.get("/Subtype")
        if subtype == "/Image":
            return True
        if subtype == "/Form" and _has_images(xobject.get("/Resources"), depth + 1):
            return True
    return False

def _pdf_text(data: bytes, index: int) -> str:
    # Cut here and not where the page is remembered: the inventory counts the characters of the
    # whole page and the pages that go to a model carry at most MAX_TEXT_CHARS of it, so one text
    # answers both and each gets the part of it that was always its own.
    return _page_text(data, hashlib.sha256(data).hexdigest(), index)[:MAX_TEXT_CHARS]

def _render_pdf_page(data: bytes, index: int, max_edge: int = MAX_IMAGE_EDGE, max_dpi: int = MAX_RENDER_DPI) -> Image.Image:
    # PDFium is not thread-safe: parallel runs and the dashboard render one page at a time.
    with PDFIUM_LOCK:
        return _render_pdf_page_unlocked(data, index, max_edge, max_dpi)

def _render_pdf_page_unlocked(data: bytes, index: int, max_edge: int, max_dpi: int) -> Image.Image:
    document = pypdfium2.PdfDocument(data)
    try:
        page = document[index]
        try:
            width, height = page.get_size()
            scale = min(max_edge / max(width, height), max_dpi / 72)
            return page.render(scale=scale).to_pil().copy()
        finally:
            page.close()
    finally:
        document.close()


def pages(record: dict) -> list[tuple[str, str, int | None]]:
    """A page with enough text of its own goes as text; one without goes as a picture.

    A text layer can look fine on screen and extract as garbage, and such a page is counted here
    as having none: the inventory says which those are.
    """
    garbled = set(record["pdf"].get("garbled_text_pages", []))
    out = []
    for number, chars in enumerate(record["pdf"].get("text_chars_per_page", []), 1):
        readable = chars >= MIN_TEXT_CHARS_PER_PAGE and number not in garbled
        out.append(("text" if readable else "vision", "pdf", None))
    return out


def text_of(data: bytes, ref) -> str:
    return _pdf_text(data, ref.index)


def image_of(data: bytes, ref, zoom: bool = False) -> Image.Image:
    if zoom:
        return _render_pdf_page(data, ref.index, ZOOM_RENDER_EDGE, ZOOM_RENDER_DPI)
    return _render_pdf_page(data, ref.index)
