"""Pictures pasted inside an Office file, which are usually scans somebody put in a document."""

import io
import zipfile

from PIL import Image

OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def pictures_among(names, kind: str) -> list[str]:
    """Which entries of an Office file's zip are its pictures, in the order they are numbered.

    One place, because it was three: this, and the inventory probe of each of the two kinds of
    file. A zip may hold a directory as an entry of its own — "word/media/" itself, with no name
    after it — and python's zipfile writes one, LibreOffice writes one, and a .doc is read here
    through a .docx LibreOffice converted. The probes counted that entry as a picture and this
    did not, so such a file was given one page more than it has pictures: the page that is not
    there went to classify and extract and failed with a bare IndexError naming neither the file
    nor the page, and the ledger recorded a refusal against a page that does not exist.
    """
    prefix = "word/media/" if kind == "word" else "xl/media/"
    return sorted(name for name in names if name.startswith(prefix) and not name.endswith("/"))


def media_names(data: bytes, kind: str) -> list[str]:
    if data.startswith(OLE_SIGNATURE):
        return []  # Excel 97-2003: pictures are not counted in inventory either
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return pictures_among(archive.namelist(), kind)


def image_of(data: bytes, ref, zoom: bool = False) -> Image.Image:
    """A picture pasted into a document or a workbook, as it was pasted."""
    name = media_names(data, ref.record["category"])[ref.index]
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        with Image.open(io.BytesIO(archive.read(name))) as source:
            return source.copy()
