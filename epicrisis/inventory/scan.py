"""Walk an archive and build one inventory record per file.

The archive is only ever read: files are opened in binary read mode and nothing is
written, renamed or moved.
"""

import io
import hashlib
import os
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from epicrisis.inventory import legacy, probes

OS_METADATA_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
YEAR_RE = re.compile(r"(?<!\d)(19\d\d|20\d\d)(?!\d)")

PROBES = {
    "pdf": probes.probe_pdf,
    "image": probes.probe_image,
    "excel": probes.probe_excel,
    "word": probes.probe_word,
}


def scan(root: Path) -> Iterator[dict]:
    for path in iter_files(root):
        yield inventory_record(root, path)


def iter_files(root: Path) -> Iterator[Path]:
    """Regular files under root in a stable order. Symlinks are not followed."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_file() and not path.is_symlink():
                yield path


def inventory_record(root: Path, path: Path) -> dict:
    relative = path.relative_to(root)
    stat = path.stat()
    record = {
        "path": relative.as_posix(),
        "name": path.name,
        "size": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="seconds"),
        "folder_year_hint": folder_year_hint(relative),
    }
    if is_os_metadata(path.name):
        record["skipped"] = "os_metadata"
        return record

    try:
        record["sha256"] = sha256_file(path)
        source = path
        wrapped = probes.http_payload(path)
        if wrapped is not None:
            offset, source = wrapped
            record["wrapper"] = {"kind": "http_response", "payload_offset": offset}
        record["mime"] = probes.detect_mime(source)
    except OSError as exc:
        record["error"] = f"{type(exc).__name__}: {exc.strerror}"
        return record
    except probes.UnsupportedFormat as exc:
        record["unsupported"] = str(exc)
        return record

    kind = record["category"] = probes.category(record["mime"])
    if kind == "legacy_office":
        # Old Excel workbooks are read like new ones; other legacy Office files stay unsupported.
        try:
            record["excel"] = probes.probe_legacy_excel(source, record["mime"])
            kind = record["category"] = "excel"
            return record
        except probes.UnsupportedFormat:
            pass
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            return record
        # Old Word documents are read from a .docx copy made by LibreOffice.
        try:
            converted = legacy.doc_to_docx(source.read_bytes() if isinstance(source, Path) else source.getvalue())
            record["word"] = {**probes.probe_word(io.BytesIO(converted), record["mime"]), "format": "doc"}
            kind = record["category"] = "word"
        except legacy.ConversionUnavailable as exc:
            record["unsupported"] = str(exc)
        except Exception as exc:
            record["unsupported"] = f"legacy Office file not read: {type(exc).__name__}"
        return record
    probe = PROBES.get(kind)
    if probe is not None:
        try:
            record[kind] = probe(source, record["mime"])
        except probes.UnsupportedFormat as exc:
            record["unsupported"] = str(exc)
        except Exception as exc:  # any parser failure means the file is damaged
            record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def is_os_metadata(name: str) -> bool:
    return name in OS_METADATA_NAMES or name.startswith("._")


def folder_year_hint(relative: Path) -> int | None:
    """Year from the nearest enclosing folder name. A hint only; dates come from content."""
    this_year = datetime.now(UTC).year
    for part in reversed(relative.parent.parts):
        for match in YEAR_RE.findall(part):
            year = int(match)
            if year <= this_year:
                return year
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()
