"""A second look for dates on documents that have none after transcription.

Every page goes as an image with close-ups, text-layer PDFs included: dates hide in stamps,
signatures, handwriting and device screens that transcription passes over. The model only
copies dates and says what each one is; nothing else is read or kept.

Output: data/sources/<id>/date_search.jsonl, one line per document per run; the latest wins.
"""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from epicrisis import layout
from epicrisis import records
from epicrisis.classify.backend import STRONG_MODEL, BackendError, UsageLimitReached
from epicrisis.classify.pages import PageRef, PageUnreadable, _clean_image, _close_ups, _file_bytes, _page_image, page_refs
from epicrisis.records import read_records
from epicrisis.runs import belongs_to_the_folder
from epicrisis.parallel import DEFAULT_WORKERS, STATE_LOCK, run_parallel
from epicrisis.sources import Source, source_output_dir

FILE_NAME = layout.DATE_SEARCH
LOCK_NAME = "date_search.lock"
MAX_PAGES_PER_CALL = 3
KINDS = ["study", "report", "issue", "signature", "stamp", "birth", "validity", "device", "other"]

SYSTEM_PROMPT = """You look for dates on the pages of one document from a person's own medical archive. Each page comes as a whole image and four overlapping close-ups of the same page. Find every date that appears anywhere: printed, typed, stamped, handwritten, in a signature block, in a header or footer, or on a device screen captured in the image.

For each date:
- as_printed: the date exactly as written, the same characters. Never complete missing parts and never guess unclear digits.
- page: the page number.
- kind: what the date is, from its label or its place: study (examination, test, sample, visit), report (conclusion, result, validation), issue (document issued or written), signature, stamp, birth (date of birth), validity (valid until, next visit), device (date shown by a machine), other.
- label_as_printed: the label printed next to it, or null.
- legible: false when any digit is unclear.

Report dates only. Do not read, transcribe or comment on anything else on the pages."""

SCHEMA = {
    "type": "object",
    "properties": {
        "dates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "as_printed": {"type": "string"},
                    "page": {"type": "integer", "minimum": 1},
                    "kind": {"type": "string", "enum": KINDS},
                    "label_as_printed": {"type": ["string", "null"]},
                    "legible": {"type": "boolean"},
                },
                "required": ["as_printed", "page", "kind", "label_as_printed", "legible"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["dates"],
    "additionalProperties": False,
}

REQUEST_LINE = "Page {number}: {name} in the current directory, close-ups {close_ups}."
PROMPT_VERSION = hashlib.sha256("\n".join([SYSTEM_PROMPT, json.dumps(SCHEMA, sort_keys=True), REQUEST_LINE]).encode()).hexdigest()[:12]


@dataclass
class SearchStats:
    total: int = 0
    searched: int = 0
    with_dates: int = 0
    unreadable: int = 0
    failed: int = 0
    stopped: str | None = None


class ClaudeCodeDateSearch:
    name = "claude-code-subscription"

    def __init__(self, model: str = STRONG_MODEL, executable: str = "claude", timeout_seconds: int = 600,
                 call=None):  # fmt: skip
        self.model, self.executable, self.timeout_seconds = model, executable, timeout_seconds
        self._call = call
        if call is not None:
            self.name = call.backend_name  # the instance says where its pages actually went

    @property
    def call(self):
        if getattr(self, "_call", None) is None:
            from epicrisis.engines import ClaudeCodeCall

            self._call = ClaudeCodeCall(model=self.model, executable=self.executable,
                                        timeout_seconds=self.timeout_seconds, read_files=True)  # fmt: skip
        return self._call

    def search(self, images: list[tuple[Path, list[Path]]], workdir: Path) -> tuple[list[dict], str]:
        request = "Find the dates on these pages.\n\n" + "\n".join(
            REQUEST_LINE.format(number=number, name=page.name, close_ups=", ".join(path.name for path in close_ups))
            for number, (page, close_ups) in enumerate(images, 1)
        )
        pages = tuple(path for page, close_ups in images for path in (page, *close_ups))
        fields, model = self.call.ask(SYSTEM_PROMPT, SCHEMA, request, workdir, pages)
        if not isinstance(fields.get("dates"), list):
            raise BackendError("no valid structured output")
        return fields["dates"], model


def load_search_results(output: Path) -> dict[tuple, dict]:
    path = output / FILE_NAME
    latest: dict[tuple, dict] = {}
    if path.exists():
        for line in read_records(path):
            latest[(line["file_sha256"], tuple(line["pages"]))] = line
    return latest


def search_source(data_dir: Path, source: Source, backend, targets: list[tuple[dict, tuple[int, ...]]], workers: int = DEFAULT_WORKERS) -> SearchStats:
    """Search the given documents (inventory record, pages) not yet searched with this model and prompt."""
    output = source_output_dir(data_dir, source.id)
    done = {
        key for key, line in load_search_results(output).items()
        if line.get("model") == backend.model and line.get("prompt_version") == PROMPT_VERSION and line.get("status") == "done"
    }  # fmt: skip
    due = [(record, pages) for record, pages in targets if (record["sha256"], pages) not in done]
    stats = SearchStats(total=len(due))
    lock = output / LOCK_NAME
    lock.write_text(json.dumps({"pid": os.getpid(), "started_at": records.now()}), encoding="utf-8")
    try:
        run_parallel(due, lambda item: _search_document(*item, output, source, backend, stats), workers)
    finally:
        lock.unlink(missing_ok=True)
    return stats


def _search_document(record: dict, pages: tuple[int, ...], output: Path, source: Source, backend, stats: SearchStats) -> bool:
    by_page = {ref.page: ref for ref in page_refs(record)}
    refs = [by_page[page] for page in pages if page in by_page and by_page[page].part != "office_text"]
    found, models = [], set()
    try:
        if not refs:
            raise PageUnreadable("no page images")
        for start in range(0, len(refs), MAX_PAGES_PER_CALL):
            chunk = refs[start : start + MAX_PAGES_PER_CALL]
            with tempfile.TemporaryDirectory(prefix="epicrisis-dates-", ignore_cleanup_errors=True) as folder:
                workdir = Path(folder)
                images = _images(chunk, Path(source.path), workdir)
                dates, model = backend.search(images, workdir)
                models.add(model)
                for item in dates:
                    position = item["page"] - 1
                    if 0 <= position < len(chunk):
                        found.append({**item, "page": chunk[position].page})
    except UsageLimitReached:
        with STATE_LOCK:
            stats.stopped = "usage_limit"
        return False
    except (PageUnreadable, BackendError) as exc:
        status = "unreadable" if isinstance(exc, PageUnreadable) else "failed"
        _write(output, record, pages, backend, status, [], None, str(exc))
        with STATE_LOCK:
            setattr(stats, status, getattr(stats, status) + 1)
        return True
    _write(output, record, pages, backend, "done", found, ", ".join(sorted(models)))
    with STATE_LOCK:
        stats.searched += 1
        stats.with_dates += bool(found)
    return True


def _images(refs: list[PageRef], archive_root: Path, workdir: Path) -> list[tuple[Path, list[Path]]]:
    data = _file_bytes(refs[0].record, archive_root)
    images = []
    try:
        for position, ref in enumerate(refs, 1):
            stem = f"{ref.file_sha256[:16]}-{position:02d}"
            image = _page_image(data, ref, zoom=True)
            page = workdir / f"{stem}.png"
            _clean_image(image).save(page, "PNG")
            close_ups = []
            for part, close_up in zip("abcd", _close_ups(image), strict=False):
                close_ups.append(workdir / f"{stem}{part}.png")
                _clean_image(close_up).save(close_ups[-1], "PNG")
            images.append((page, close_ups))
    except PageUnreadable:
        raise
    except Exception as exc:
        raise PageUnreadable(type(exc).__name__) from exc
    return images


def _write(output: Path, record: dict, pages: tuple[int, ...], backend, status: str, found: list, model: str | None, reason: str | None = None) -> None:
    line = {
        "file_sha256": record["sha256"],
        "pages": list(pages),
        "status": status,
        "found": found,
        "model": backend.model,
        "answering_model": model,
        "prompt_version": PROMPT_VERSION,
        "at": records.now(),
    }
    if reason:
        line["reason"] = reason
    with STATE_LOCK, (output / FILE_NAME).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    belongs_to_the_folder(output / FILE_NAME)

