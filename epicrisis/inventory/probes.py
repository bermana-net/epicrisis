"""What kind of file this is, and the few things every reader of one needs.

Telling a kind of file from its first bytes, reading past the headers of a file saved as a raw
HTTP response, and the small measures of text that more than one format asks of itself. What is
true of a file *of a kind* — how many pages, how much text, what is pasted inside it — belongs to
that kind's own reader, in epicrisis/readers/.

UnsupportedFormat means a file this program does not read, by design; anything else raised while
reading one means the file is damaged.
"""

import re
import unicodedata
import zipfile
from io import BytesIO
from pathlib import Path
from typing import BinaryIO


# A page with fewer visible characters than this is treated as having no text layer.
# Scans carry stamps and page numbers as text: the real archive showed scanned pages with
# 1-19 characters, real text pages with 500 or more, and nothing in between.
MIN_TEXT_CHARS_PER_PAGE = 100

# A text layer can look fine on screen and still extract as garbage: fonts with a private
# encoding come out as control characters and Latin Extended-B. Such pages go as images.
# In the real archive broken pages had 45-63% of these characters, readable ones 1.1% at most.
MAX_GARBLED_SHARE = 0.1

# How much of one page's text a reader hands over, whatever kind of file the page came out of.
#
# A ceiling and not a size. A printed page carries a few thousand characters, so no page of a
# scan or a PDF comes near this. What it is here for is the page that is not a printed page: a
# Word document is one page however long it is, because a document is not paginated until it is
# printed, and a sheet of a workbook has as many rows as somebody typed. Without a ceiling such
# a file goes to a model whole, in one call, and a call that is too long is not a slow call but a
# failed one — the measurement for that is written beside extract/run.TEXT_CHARS_PER_CALL, which
# is the ceiling on a whole call of up to eight pages. This is the ceiling on one page of one;
# the two are separate numbers that happen to be equal today.
#
# One name in one place because it was three: readers/word.py and readers/pdf.py each had a
# MAX_TEXT_CHARS of their own and readers/excel.py cut by the bare literal. Raised for a document
# and a scan, every sheet of every workbook would have stayed cut where it was, and no page says
# that part of a table never reached the model.
MAX_TEXT_CHARS = 20_000

HEAD_BYTES = 64 * 1024
HEADER_LINE = re.compile(rb"^[ \t]*[A-Za-z0-9-]+:[^\n]*$")


# Text files this program does not read: markup is a file about a page, not a page.
MARKUP_MIMES = {"text/html", "text/xml", "text/css", "text/javascript", "text/x-script"}

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
LEGACY_OFFICE_MIMES = {
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-office",
    "application/x-ole-storage",
    "application/CDFV2",
}


Source = Path | BinaryIO


class UnsupportedFormat(Exception):
    pass


def http_payload(path: Path) -> tuple[int, BytesIO] | None:
    """Offset and body of a file saved as a raw HTTP response, or None for ordinary files.

    Browsers and download tools sometimes store the status line and headers in front of a PDF.
    Header lines may be indented and the blank line before the body may be missing, so the
    header block ends at the first line that is blank or does not look like a header.
    """
    with path.open("rb") as fh:
        head = fh.read(HEAD_BYTES)
    if not head.startswith(b"HTTP/1."):
        return None

    headers = []
    offset = head.find(b"\n") + 1
    while True:
        end = head.find(b"\n", offset)
        if offset == 0 or end == -1:
            raise UnsupportedFormat("saved HTTP response without a complete header")
        line = head[offset:end]
        if not line.strip():
            offset = end + 1
            break
        if not HEADER_LINE.match(line):
            break
        headers.append(line.decode("latin-1").strip().lower())
        offset = end + 1
    while offset < len(head) and head[offset] in b" \t\r\n":
        offset += 1

    if any(header.startswith(("transfer-encoding: chunked", "content-encoding:")) for header in headers):
        raise UnsupportedFormat("saved HTTP response with an encoded body")
    return offset, BytesIO(path.read_bytes()[offset:])


# python-magic is a few lines of ctypes over a system library, and the wheel does not carry it.
# Ubuntu has libmagic; macOS and Windows do not, and the README sends a person on macOS to install
# nothing but Python. The import stood at the top of this module, which the command line imports on
# startup, so on such a machine *everything* answered with a traceback — `epicrisis demo`,
# `epicrisis serve`, and `epicrisis --help` itself, before this program had said one word of its
# own. It is asked for where it is used now, and what is missing is said in a sentence naming the
# one thing to install.
def _reading_the_signature():
    try:
        import magic
    except ImportError as missing:  # pragma: no cover - depends on the machine, not on the code
        raise UnsupportedFormat(
            "this needs libmagic, the system library that tells a file's kind from its first bytes. "
            "python-magic is only a wrapper over it. Install it: 'brew install libmagic' on macOS, "
            "'apt install libmagic1' on Debian or Ubuntu; on Windows use 'pip install python-magic-bin'."
        ) from missing
    return magic


def detect_mime(source: Source) -> str:
    """MIME type from the content signature, never from the extension."""
    magic = _reading_the_signature()
    if isinstance(source, Path):
        mime = magic.from_file(str(source), mime=True)
    else:
        source.seek(0)
        mime = magic.from_buffer(source.read(HEAD_BYTES), mime=True)
        source.seek(0)
    if mime in ("application/zip", "application/octet-stream"):
        mime = _sniff_ooxml(source) or mime
    return mime


def _sniff_ooxml(source: Source) -> str | None:
    # Some libmagic builds report .docx/.xlsx as a plain zip archive.
    try:
        names = _zip_names(source)
    except (zipfile.BadZipFile, OSError):
        return None
    if "word/document.xml" in names:
        return DOCX_MIME
    if "xl/workbook.xml" in names:
        return XLSX_MIME
    return None


def _zip_names(source: Source) -> list[str]:
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
    if not isinstance(source, Path):
        source.seek(0)
    return names


def category(mime: str) -> str:
    if mime == "application/pdf":
        return "pdf"
    if mime.startswith("image/"):
        return "image"
    if mime == DOCX_MIME:
        return "word"
    if mime == XLSX_MIME:
        return "excel"
    if mime in LEGACY_OFFICE_MIMES:
        return "legacy_office"
    if mime == "inode/x-empty":
        return "empty"
    if mime.startswith("text/"):
        return "text"
    return "other"


def _visible_chars(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def _garbled_char(ch: str) -> bool:
    code = ord(ch)
    # Latin Extended-B, except the Romanian comma-below letters that real text uses.
    if 0x0180 <= code <= 0x024F and not 0x0218 <= code <= 0x021B:
        return True
    return code == 0xFFFD or unicodedata.category(ch) in ("Cc", "Co", "Cn", "Cs")


def text_looks_garbled(text: str) -> bool:
    visible = [ch for ch in text if not ch.isspace()]
    return bool(visible) and sum(map(_garbled_char, visible)) / len(visible) > MAX_GARBLED_SHARE


def _read_all(source: BinaryIO) -> bytes:
    source.seek(0)
    data = source.read()
    source.seek(0)
    return data


