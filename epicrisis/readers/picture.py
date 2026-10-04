"""A photograph or a scan: a file that is a picture, and nothing else.

A page of it is a frame — one for an ordinary photograph, several for a multi-page TIFF — and
there is no text in it at all, so every page goes to a model as an image. See
epicrisis/readers/__init__.py for what every reader of a kind of file answers.
"""

import io

from PIL import Image, UnidentifiedImageError

from epicrisis.inventory.probes import Source, UnsupportedFormat

def probe(source: Source, mime: str) -> dict:
    try:
        with Image.open(source) as image:
            dpi = image.info.get("dpi")
            facts = {
                "format": image.format,
                "width": image.width,
                "height": image.height,
                "dpi": [round(float(value)) for value in dpi] if dpi else None,
                "frames": getattr(image, "n_frames", 1),
            }
            # Decoding the pixels is the only reliable way to catch truncated files.
            image.load()
    except UnidentifiedImageError as exc:
        # Pillow knows the format but cannot read this file: damaged. Otherwise: unsupported.
        Image.init()
        if mime in Image.MIME.values():
            raise
        raise UnsupportedFormat("image format not supported by Pillow") from exc
    return facts


def pages(record: dict) -> list[tuple[str, str, int | None]]:
    """One page per frame. A photograph has one; a scan saved as a multi-page TIFF has several."""
    return [("vision", "image", None) for _ in range(record["image"]["frames"])]


def image_of(data: bytes, ref, zoom: bool = False) -> Image.Image:
    """The frame itself. Nothing is resized or stripped here: that is the payload's business."""
    with Image.open(io.BytesIO(data)) as source:
        source.seek(ref.index)
        return source.copy()
