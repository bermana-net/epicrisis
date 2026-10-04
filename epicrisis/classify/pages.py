"""Pages to classify, derived from inventory records, and the payload sent for each page.

A payload is either the page text or a PNG rendered for that page alone. It never carries a
file name, folder name, path, folder year or page number, and images are re-encoded without
metadata (phone photos keep GPS coordinates and device names in EXIF).
"""

import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps

from epicrisis.inventory import legacy
from epicrisis.readers import reader_for

MAX_IMAGE_EDGE = 1600
CLOSE_UP_SHARE = 0.55


@dataclass(frozen=True)
class PageRef:
    file_sha256: str
    page: int  # 1-based position among all pages of the file
    route: str  # "text" or "vision"
    part: str  # "pdf", "image", "text", "office_text" or "office_image"
    index: int  # 0-based position within its part
    record: dict = field(compare=False, hash=False, repr=False)
    # Which document of the file this page belongs to, where that is known before anything reads
    # it: a text file has no page breaks, so its documents are marked out first and the pages cut
    # at the marks. Nothing else has this, and for everything else it is None.
    document: int | None = None


@dataclass
class Payload:
    text: str | None = None
    image_path: Path | None = None
    close_ups: list[Path] = field(default_factory=list)


class PageUnreadable(Exception):
    """The page cannot be turned into text or an image. Recorded without calling a model."""


def page_refs(record: dict) -> list[PageRef]:
    """The pages of one file, in order, as the reader of that kind of file counts them.

    What a page *is* differs by kind — a printed page of a PDF, a frame of a photograph, a sheet
    of a workbook, a piece of a text file this program cut itself — so the counting belongs to the
    reader and the numbering belongs here: page 1 is the first page of the file whatever it holds,
    and that number is an address a person follows from a value to the page it was read from.
    """
    if record.get("skipped") or "error" in record or "unsupported" in record or "sha256" not in record:
        return []
    reader = reader_for(record.get("category"))
    if reader is None:
        return []
    refs: list[PageRef] = []
    counts: dict[str, int] = {}
    for route, part, document in reader.pages(record):
        refs.append(PageRef(record["sha256"], len(refs) + 1, route, part, counts.get(part, 0), record, document))
        counts[part] = counts.get(part, 0) + 1
    return refs


def materialize(ref: PageRef, archive_root: Path, workdir: Path) -> Payload:
    """One page, as the thing that goes to a model: words, or a picture written to the workdir.

    Which of the two it is was settled when the pages were counted, and the reader of that kind
    of file is the one that can produce it.
    """
    data = _file_bytes(ref.record, archive_root)
    reader = reader_for(ref.record.get("category"))
    try:
        if ref.route == "text":
            return Payload(text=reader.text_of(data, ref))
        return _png(reader.image_of(data, ref), ref, workdir)
    except Exception as exc:
        # Only the exception type is kept: messages can quote document content.
        raise PageUnreadable(type(exc).__name__) from exc


def _file_bytes(record: dict, archive_root: Path) -> bytes:
    try:
        data = (archive_root / record["path"]).read_bytes()
    except FileNotFoundError as gone:
        # Not a damaged document: the archive folder is not where it was. A disk that did not
        # mount, a folder carried elsewhere. Raised bare, this reached the dashboard as the words
        # Internal Server Error inside the <img> of a page a person had clicked through to see
        # their own scan — the one thing this program promises is always one click away. The name
        # of the file is left out on purpose: in an archive like this it carries a surname and
        # often the reason for the visit, and the page already says which document it is.
        raise PageUnreadable(
            "the archive folder is not where it was, so this page cannot be read from disk; "
            "check whether the disk it is on is mounted"
        ) from gone
    if hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise PageUnreadable("file changed since inventory")
    wrapper = record.get("wrapper")
    data = data[wrapper["payload_offset"] :] if wrapper else data
    if record.get("word", {}).get("format") == "doc":
        # Word 97-2003 is read from a .docx copy, so text and pictures come out as for .docx.
        data = legacy.doc_to_docx(data)
    return data


def _png(image: Image.Image, ref: PageRef, workdir: Path) -> Payload:
    path = workdir / f"{ref.file_sha256[:16]}.png"
    _clean_image(image).save(path, "PNG")
    return Payload(image_path=path)


def _clean_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    # A fresh image carries pixels only: no EXIF, ICC profile or text chunks.
    clean = Image.new(image.mode, image.size)
    clean.paste(image)
    return clean


def cannot_be_read(ref: PageRef, archive_root: Path) -> str:
    """Why this page cannot be read from disk, in this program's own words, or nothing where it can.

    The page of a scan is one request and its image is another, so the first has to be able to say
    what the second is going to fail at. It asked one question only — is the folder there — and
    answered a sentence for that and a broken image for everything else. The likelier trouble is one
    file changing under the archive: rescanned, resaved by a photo application, damaged. Then the
    page drew an <img> at an address that answers 409, and the reason, which this program knew
    exactly, went only into a header nobody reads.

    The file is read and hashed, as reading it for the image would, and the image is not drawn: a
    page that cannot be drawn at all is rarer, and the request for the image says that itself.
    """
    try:
        _file_bytes(ref.record, archive_root)
    except PageUnreadable as why:
        return str(why)
    return ""


#: Parts of a file that are text and have no picture of a page behind them. A PDF page is not
#: among them: it has a text layer and an image both, and the image is what a person wants to see.
TEXT_ONLY_PARTS = ("text", "office_text")


def has_no_image(ref: PageRef) -> bool:
    return ref.part in TEXT_ONLY_PARTS


def original_text(ref: PageRef, archive_root: Path) -> str:
    """A page that is text and nothing else, as it stands in the file.

    The dashboard draws the page every value was read from. For a scan that is a picture; for a
    text file, a page of a spreadsheet or of a Word document there is no picture, and this is
    what there is instead. Nothing leaves the machine.
    """
    data = _file_bytes(ref.record, archive_root)
    try:
        return reader_for(ref.record.get("category")).text_of(data, ref)
    except PageUnreadable:
        raise
    except Exception as exc:
        raise PageUnreadable(type(exc).__name__) from exc


def original_png(ref: PageRef, archive_root: Path) -> bytes:
    """The page as a PNG for viewing on this server. Nothing here leaves the machine."""
    data = _file_bytes(ref.record, archive_root)
    try:
        buffer = io.BytesIO()
        _clean_image(_page_image(data, ref)).save(buffer, "PNG")
    except PageUnreadable:
        raise
    except Exception as exc:
        raise PageUnreadable(type(exc).__name__) from exc
    return buffer.getvalue()


def document_payloads(refs: list[PageRef], archive_root: Path, workdir: Path, zoom: bool = False, always_images: bool = False) -> list[Payload]:
    """Payloads for the pages of one document, in order.

    If any page is a scan, PDF pages all go as images, so the model reads the document one way.
    Text files, and Word and Excel text pages, have no image and always go as text. Image
    files are named by the file hash and the position in this document, never by the page
    number in the file.
    With zoom, every image page also gets four overlapping close-ups. always_images renders the
    PDF pages even where a text layer exists: a text layer holds no axis labels, no stamp and no
    small print outside the text flow, so a second reading of such a page has to look at it.
    """
    data = _file_bytes(refs[0].record, archive_root)
    reader = reader_for(refs[0].record.get("category"))
    as_images = always_images or any(ref.route == "vision" for ref in refs)
    payloads = []
    try:
        for position, ref in enumerate(refs, 1):
            if ref.part in TEXT_ONLY_PARTS or (ref.route == "text" and not as_images):
                payloads.append(Payload(text=reader.text_of(data, ref)))
            else:
                stem = f"{ref.file_sha256[:16]}-{position:02d}"
                image = _page_image(data, ref, zoom)
                path = workdir / f"{stem}.png"
                _clean_image(image).save(path, "PNG")
                close_ups = []
                if zoom:
                    for part, close_up in zip("abcd", _close_ups(image), strict=False):
                        close_ups.append(workdir / f"{stem}{part}.png")
                        _clean_image(close_up).save(close_ups[-1], "PNG")
                payloads.append(Payload(image_path=path, close_ups=close_ups))
    except PageUnreadable:
        raise
    except Exception as exc:
        raise PageUnreadable(type(exc).__name__) from exc
    return payloads


def _close_ups(image: Image.Image) -> list[Image.Image]:
    """Four overlapping quarters of the upright page, row by row."""
    image = ImageOps.exif_transpose(image)
    width, height = image.size
    cut_x, cut_y = int(width * CLOSE_UP_SHARE), int(height * CLOSE_UP_SHARE)
    return [
        image.crop((left, top, left + cut_x, top + cut_y))
        for top in (0, height - cut_y)
        for left in (0, width - cut_x)
    ]


def _page_image(data: bytes, ref: PageRef, zoom: bool = False) -> Image.Image:
    """The picture of a page, from the reader of that kind of file. A page that is text has none."""
    if has_no_image(ref):
        raise PageUnreadable("text page without an image")
    return reader_for(ref.record.get("category")).image_of(data, ref, zoom)


