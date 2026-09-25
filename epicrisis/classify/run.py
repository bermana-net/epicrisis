"""Classify the pages of one source, resumable through the ledger.

Each page gets its own temporary directory outside data/, removed right after the page, so a
crash leaves at most one rendered page on disk.
"""

import json
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from epicrisis.classify.backend import PROMPT_VERSION, BackendError, UsageLimitReached
from epicrisis.classify.pages import PageRef, PageUnreadable, materialize, page_refs
from epicrisis.classify.report import latest_pages
from epicrisis.records import append_line, now, read_records
from epicrisis.parallel import DEFAULT_WORKERS, STATE_LOCK, run_parallel
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
    records = list(read_records(output / "inventory.jsonl"))
    if sample:
        refs = sample_refs(records)
    elif years is not None:
        refs = refs_for_years(records, years)
    else:
        refs = all_refs(records)
    done = _done_keys(output / "ledger.jsonl", output / "classify.jsonl")
    accepts = getattr(backend, "accepts", None)
    if accepts:
        done |= {
            (line["file_sha256"], line["page"], line.get("route"), backend.model, line["provenance"]["prompt_version"])
            for line in latest_pages(output / "classify.jsonl")
            if "error" not in line and accepts(line)
        }
    stats = RunStats(total=len(refs))

    lock = output / LOCK_NAME
    lock.write_text(json.dumps({"pid": os.getpid(), "started_at": now()}), encoding="utf-8")
    try:
        _classify_refs(refs, done, stats, output, source, backend, limit, progress, workers)
    finally:
        lock.unlink(missing_ok=True)
    return stats


def is_running(output: Path, lock_name: str = LOCK_NAME) -> bool:
    """True while a run holds the lock (classify by default) for this source's output directory."""
    try:
        pid = json.loads((output / lock_name).read_text(encoding="utf-8"))["pid"]
    except (FileNotFoundError, ValueError, KeyError):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # alive, owned by another user
        return True
    return True


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
    workdir = Path(tempfile.mkdtemp(prefix="epicrisis-page-"))
    try:
        try:
            payload = materialize(ref, Path(source.path), workdir)
        except PageUnreadable as exc:
            with STATE_LOCK:
                append_line(output / "classify.jsonl", _page_line(ref, backend, model=None, error=str(exc)))
                append_line(output / "ledger.jsonl", _ledger_line(ref, backend, "unreadable"))
                stats.unreadable += 1
            return True
        try:
            result = backend.classify(payload, workdir)
        except UsageLimitReached:
            with STATE_LOCK:
                stats.stopped = "usage_limit"
            return False
        except BackendError as exc:
            with STATE_LOCK:
                append_line(output / "ledger.jsonl", _ledger_line(ref, backend, "failed", reason=str(exc)))
                stats.failed += 1
            return True
        line = _page_line(ref, backend, model=result.model, fields=result.fields)
        if result.escalation:
            line["provenance"]["escalation"] = result.escalation
        with STATE_LOCK:
            append_line(output / "classify.jsonl", line)
            append_line(output / "ledger.jsonl", _ledger_line(ref, backend, "done"))
            stats.classified += 1
        return True
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


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
    line = {"file_sha256": ref.file_sha256, "page": ref.page, "route": ref.route}
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

