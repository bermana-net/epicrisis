"""A file that is nothing but text: a history poured into one file, visit after visit.

It is the one kind of file with no pages of its own. A scan has them because somebody printed it;
this program cuts a text file into them — at the lines its own export draws between documents
where there are such lines, and at line ends inside anything longer than a page. See
epicrisis/boundaries.py for the cutting and epicrisis/readers/__init__.py for what every reader
of a kind of file answers.
"""

import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path

from epicrisis.inventory.probes import (
    MARKUP_MIMES,
    Source,
    UnsupportedFormat,
    _garbled_char,
    _read_all,
    _visible_chars,
)

# A plain text file has no pages of its own, so it is cut into pages of this many characters, at
# line ends. A printed page holds a few thousand characters, and everything downstream was built
# for pages of that size: a reading carries up to eight of them in one call, which was set when a
# page meant a photograph of a form.
#
# It was twenty thousand to begin with, and the first text archive read here showed what that
# costs. A document of four such pages is eighty thousand characters in one request; two documents
# of that archive never finished inside the fifteen minutes a call is given. And the cut is where
# the reader is told one document ends and the next begins: a visit of 2019 and a visit of 2016
# fell inside one twenty-thousand-character page, so the page could only be called a continuation
# of the first, and the two were stored as one document.
TEXT_PAGE_CHARS = 5_000

# A text file carries no declaration of how its bytes stand for letters. The ones that come up in
# an archive like this: anything written in the last fifteen years, and the Windows codings of the
# decade before that, one per alphabet. They are tried in this order and the one that reads as
# letters rather than as symbols wins; see _reads_as_text.
TEXT_CODINGS = ("utf-8", "cp1251", "cp1253", "cp1252", "koi8-r")
BOMS = (("utf-8-sig", b"\xef\xbb\xbf"), ("utf-16", b"\xff\xfe"), ("utf-16", b"\xfe\xff"))
ORDINARY_MARKS = set(" \t\r\n.,:;!?()[]{}<>-–—/\\|\"'«»„“”‘’+=*&#№%°±~@$€£_^`")

def read_text(data: bytes) -> tuple[str, str]:
    """A text file as letters, and the name of the coding it was read with.

    A byte order mark settles it. Otherwise the codings are tried in turn and scored by how much
    of what comes out is letters rather than symbols: Cyrillic read as Western European is not an
    error any decoder reports — it is "Ð¡Ð¾" where the file says a word — so nothing but reading
    the result tells the two apart.
    """
    for coding, mark in BOMS:
        if data.startswith(mark):
            return data.decode(coding, errors="replace"), coding
    best: tuple[float, str, str] | None = None
    for coding in TEXT_CODINGS:
        try:
            text = data.decode(coding)
        except (UnicodeDecodeError, LookupError):
            continue
        score = _reads_as_text(text)
        if best is None or score > best[0]:
            best = (score, text, coding)
    if best is None:  # no coding read these bytes at all
        return data.decode("utf-8", errors="replace"), "utf-8"
    return best[1], best[2]

def _reads_as_text(text: str, sample: int = 20_000) -> float:
    """How much this reads like writing rather than like a wrong coding, as one number.

    sample is how much of the file is looked at to answer that, and is not the ceiling on how
    much of a page goes to a model — probes.MAX_TEXT_CHARS, which happens to be the same number
    today. A different question: this one is about telling one coding from another, and the
    shares below are shares, so enough of the file to be sure is all it needs.

    Shares, not counts, so the length of the file does not decide. Four things are asked of the
    text, and only the high bytes can answer differently from one coding to another — the plain
    ASCII of a file reads the same under all of them, so whatever it does weighs on all alike:

    - letters, digits and ordinary marks rather than control characters and replacements;
    - letters mostly of one alphabet, which is what writing is;
    - no alphabet changing inside a word: "anblisis" with a Cyrillic letter in the middle is
      Spanish read with the Russian coding;
    - no capital in the middle of a word: Greek vowels that carry an accent come out of the
      Russian coding as capitals, so this is what tells those two apart.
    """
    head = text[:sample]
    if not head:
        return 0.0
    good = sum(1 for ch in head if ch.isalnum() or ch in ORDINARY_MARKS)
    odd = sum(1 for ch in head if _garbled_char(ch))
    plain = (good - 10 * odd) / len(head)

    letters = [ch for ch in head if ch.isalpha()]
    if not letters:
        return plain
    alphabets = Counter(_alphabet(ch) for ch in letters)
    one_alphabet = alphabets.most_common(1)[0][1] / len(letters)
    inside = [(before, ch) for before, ch in zip(head, head[1:], strict=False) if before.isalpha() and ch.isalpha()]
    switches = sum(1 for before, ch in inside if _alphabet(before) != _alphabet(ch))
    capitals = sum(1 for before, ch in inside if before.islower() and ch.isupper())
    return plain + one_alphabet - 5 * (switches + capitals) / len(letters)

@lru_cache(maxsize=4096)
def _alphabet(ch: str) -> str:
    """LATIN, CYRILLIC, GREEK and so on, from the character's own name."""
    return unicodedata.name(ch, "UNNAMED").split()[0]

def text_pages(text: str) -> list[str]:
    """The text cut into pages at line ends. Empty for a file with nothing visible in it.

    This is the cut of a file nobody has read yet: so many characters, wherever that falls. Once
    the documents in it have been marked out, the pages follow the marks instead — see
    epicrisis/boundaries.py, which cuts at a document and then uses this for what is left over.
    """
    if not _visible_chars(text):
        return []
    pages, page = [], ""
    for line in text.splitlines(keepends=True):
        if page and len(page) + len(line) > TEXT_PAGE_CHARS:
            pages.append(page)
            page = ""
        while len(line) > TEXT_PAGE_CHARS:  # one line longer than a page, cut where it must be
            pages.append(line[:TEXT_PAGE_CHARS])
            line = line[TEXT_PAGE_CHARS:]
        page += line
    if page:
        pages.append(page)
    return pages

def probe(source: Source, mime: str) -> dict:
    """A plain text file: how it is to be read, and into how many pages it falls."""
    if mime in MARKUP_MIMES:
        raise UnsupportedFormat("a markup or web page file, not a document of this archive")
    data = source.read_bytes() if isinstance(source, Path) else _read_all(source)
    text, coding = read_text(data)
    return {"coding": coding, "text_chars": _visible_chars(text), "pages": len(text_pages(text))}


def pages(record: dict) -> list[tuple[str, str, int | None]]:
    """The pages of a text file: route, part, and which document of the file each belongs to.

    An inventory written before text files were read at all names the category and says nothing
    more, and such a file waits for the next walk of the folder rather than taking the dashboard
    down with it.
    """
    facts = record.get("text", {})
    belongs = facts.get("of_document") or []
    return [("text", "text", belongs[number] if number < len(belongs) else None)
            for number in range(facts.get("pages", 0))]  # fmt: skip


def text_of(data: bytes, ref) -> str:
    """One page, read with the coding the inventory settled on and cut where the inventory cut.

    The coding is read back rather than worked out again, so the same file reads the same way
    here, in the inventory and on the page this dashboard draws of it.
    """
    from epicrisis.boundaries import pages_of

    facts = ref.record.get("text", {})
    coding = facts.get("coding")
    whole = data.decode(coding, errors="replace") if coding else read_text(data)[0]
    cuts = facts.get("cuts")
    pieces = [piece for piece, _ in pages_of(whole, cuts)] if cuts else text_pages(whole)
    if ref.index >= len(pieces):
        from epicrisis.classify.pages import PageUnreadable

        raise PageUnreadable("file changed since inventory")
    return pieces[ref.index]
