"""Classify the pages of one source, resumable through the ledger.

Each page gets its own temporary directory outside data/, removed right after the page, so a
crash leaves at most one rendered page on disk.
"""

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from epicrisis import journal, layout
from epicrisis.classify.backend import PROMPT_VERSION, BackendError, UsageLimitReached
from epicrisis.classify.pages import PageRef, PageUnreadable, materialize, page_refs
from epicrisis.classify.report import latest_pages
from epicrisis.records import append_line, now, read_records
from epicrisis.parallel import DEFAULT_WORKERS, STATE_LOCK, run_parallel
from epicrisis.runs import holder, one_at_a_time
from epicrisis.sources import Source, source_output_dir

LOCK_NAME = "classify.lock"
SAMPLE_BEFORE_YEAR = 2014
SAMPLE_FROM_YEAR = 2015


@dataclass
class RunStats:
    total: int = 0
    already_done: int = 0
    classified: int = 0
    unreadable: int = 0
    failed: int = 0
    stopped: str | None = None

    @property
    def attempted(self) -> int:
        return self.classified + self.unreadable + self.failed


def all_refs(records: list[dict]) -> list[PageRef]:
    return [ref for record in records for ref in page_refs(record)]


def sample_refs(records: list[dict]) -> list[PageRef]:
    """First pages of distinct files: 2 scans before 2014, 2 digital pages from 2015, 1 photo.

    The folder year is used only here, on our side, and never reaches the model.
    """

    def pick(matches: Callable[[dict, PageRef], bool], count: int) -> list[PageRef]:
        picked = []
        for record in sorted(records, key=lambda record: record.get("sha256", "")):
            refs = page_refs(record)
            if refs and matches(record, refs[0]):
                picked.append(refs[0])
                if len(picked) == count:
                    break
        return picked

    def year(record: dict) -> int:
        return record.get("folder_year_hint") or 0

    return (
        pick(lambda r, ref: r["category"] == "pdf" and ref.route == "vision" and 0 < year(r) < SAMPLE_BEFORE_YEAR, 2)
        + pick(lambda r, ref: r["category"] == "pdf" and ref.route == "text" and year(r) >= SAMPLE_FROM_YEAR, 2)
        + pick(lambda r, ref: r["category"] == "image", 1)
    )


def parse_years(spec: str) -> set[int]:
    """"1992-2003,2025" -> {1992, ..., 2003, 2025}."""
    years: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        start, _, end = part.partition("-")
        try:
            first, last = int(start), int(end or start)
        except ValueError as exc:
            raise ValueError(f"not a year or a year range: {part}") from exc
        if first > last:
            raise ValueError(f"year range goes backwards: {part}")
        years.update(range(first, last + 1))
    if not years:
        raise ValueError("no years given")
    return years


def refs_for_years(records: list[dict], years: set[int]) -> list[PageRef]:
    """Pages of files whose folder year is in years. The folder year stays on our side."""
    return [ref for record in records if record.get("folder_year_hint") in years for ref in page_refs(record)]


def classify_source(
    data_dir: Path,
    source: Source,
    backend,
    sample: bool = False,
    limit: int | None = None,
    progress: Callable[[RunStats], None] | None = None,
    years: set[int] | None = None,
    workers: int = DEFAULT_WORKERS,
) -> RunStats:
    output = source_output_dir(data_dir, source.id)
    records = list(read_records(output / layout.INVENTORY))
    if sample:
        refs = sample_refs(records)
    elif years is not None:
        refs = refs_for_years(records, years)
    else:
        refs = all_refs(records)
    done = _done_keys(output / layout.LEDGER, output / layout.CLASSIFY)
    accepts = getattr(backend, "accepts", None)
    if accepts:
        done |= {
            (line["file_sha256"], line["page"], line.get("route"), backend.model, line["provenance"]["prompt_version"])
            for line in latest_pages(output / layout.CLASSIFY)
            if "error" not in line and accepts(line)
        }
    stats = RunStats(total=len(refs))

    with one_at_a_time(output / LOCK_NAME, "Reading what each page is"):
        _classify_refs(refs, done, stats, output, source, backend, limit, progress, workers)
    return stats


def is_running(output: Path, lock_name: str = LOCK_NAME) -> bool:
    """True while a run holds the lock (classify by default) for this source's output directory.

    Through runs.holder, which is the one reader of a lock file. This had a copy of that reading
    and the copy had already drifted: a lock whose pid was null raised TypeError here and came
    back as None there, so a stray lock file took down every page that asks whether a run is
    going — the documents, the status, a document's own card.
    """
    return holder(output / lock_name) is not None


def _classify_refs(refs, done, stats, output, source, backend, limit, progress, workers=DEFAULT_WORKERS) -> None:
    models = getattr(backend, "accepted_models", {backend.model})
    due = []
    for ref in refs:
        if any((ref.file_sha256, ref.page, ref.route, model, PROMPT_VERSION) in done for model in models):
            stats.already_done += 1
        elif limit is None or len(due) < limit:
            due.append(ref)

    def work(ref) -> bool:
        try:
            return _classify_page(ref, stats, output, source, backend)
        finally:
            if progress:
                with STATE_LOCK:
                    progress(stats)

    run_parallel(due, work, workers)


def _classify_page(ref, stats, output, source, backend) -> bool:
    """Classify one page. Returns False when the run has to stop."""
    with tempfile.TemporaryDirectory(prefix="epicrisis-page-", ignore_cleanup_errors=True) as folder:
        workdir = Path(folder)
        try:
            payload = materialize(ref, Path(source.path), workdir)
        except PageUnreadable as exc:
            with STATE_LOCK:
                append_line(output / layout.CLASSIFY, _page_line(ref, backend, model=None, error=str(exc)))
                append_line(output / layout.LEDGER, _ledger_line(ref, backend, "unreadable"))
                stats.unreadable += 1
            # The ledger says this page could not be read; the journal says which line of this
            # project decided so, which is the thing a person debugging it has no other way to
            # learn. Outside the lock: the journal takes its own.
            journal.a_page_would_not_read(output, source.id, exc, "classify")
            return True
        try:
            result = backend.classify(payload, workdir)
        except UsageLimitReached:
            with STATE_LOCK:
                stats.stopped = "usage_limit"
            return False
        except BackendError as exc:
            with STATE_LOCK:
                append_line(output / layout.LEDGER, _ledger_line(ref, backend, "failed", reason=str(exc)))
                stats.failed += 1
            return True
        line = _page_line(ref, backend, model=result.model, fields=result.fields)
        # Why the stronger model was asked, in the codes `classification_problems` returned, and
        # only on the lines where it was asked. A line with no `escalation` says the small model
        # answered this page on its own and there was nothing to escalate — it does not say the
        # reasons are unknown, and nothing may read the absence as "no reasons were recorded".
        # One of the codes is `small_model_failed`, which is the small model not answering at all:
        # a fault and not a doubt, and the two must never be counted together.
        if result.escalation:
            line["provenance"]["escalation"] = result.escalation
        with STATE_LOCK:
            append_line(output / layout.CLASSIFY, line)
            append_line(output / layout.LEDGER, _ledger_line(ref, backend, "done"))
            stats.classified += 1
        return True


def _done_keys(ledger: Path, results: Path) -> set[tuple]:
    """Pages classified by this model and prompt, on the route the page takes now.

    A page whose route changed since (a text layer later found garbled) is classified again.
    """
    if not ledger.exists():
        return set()
    routes = {(page["file_sha256"], page["page"]): page.get("route") for page in latest_pages(results)}
    return {
        (entry["file_sha256"], entry["page"], routes.get((entry["file_sha256"], entry["page"])), entry["model"], entry["prompt_version"])
        for entry in read_records(ledger)
        if entry.get("step") == "classify" and entry.get("status") in ("done", "unreadable")
    }



def _page_line(ref: PageRef, backend, model: str | None, fields: dict | None = None, error: str | None = None) -> dict:
    # What kind of page this is, beside how it was read: a page of a text file has no page break
    # of its own — this program cut it — and what follows from that is decided on the stored
    # classification alone, by everything that groups pages into documents.
    line = {"file_sha256": ref.file_sha256, "page": ref.page, "route": ref.route, "part": ref.part}
    if ref.document is not None:
        # Which document of the file this page is a piece of, settled before anything read it.
        # Where this is known the grouping follows it and asks the reader nothing about it.
        line["of_document"] = ref.document
    if error is not None:
        line["error"] = error
    else:
        line.update(fields or {})
    line["provenance"] = {
        "backend": backend.name,
        "model": model,
        "requested_model": backend.model,
        "prompt_version": PROMPT_VERSION,
        "classified_at": now(),
    }
    return line


def _ledger_line(ref: PageRef, backend, status: str, reason: str | None = None) -> dict:
    line = {
        "step": "classify",
        "file_sha256": ref.file_sha256,
        "page": ref.page,
        "model": backend.model,
        "prompt_version": PROMPT_VERSION,
        "status": status,
        "at": now(),
    }
    if reason:
        line["reason"] = reason
    return line

