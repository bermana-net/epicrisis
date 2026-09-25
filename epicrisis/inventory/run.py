"""Run an inventory into a JSONL file. Shared by the CLI and the web app."""

import json
from collections.abc import Callable
from pathlib import Path

from epicrisis.inventory.report import Summary
from epicrisis.inventory.scan import iter_files, scan
from epicrisis.runs import put_in_place, temporary_name


class OutputInsideArchive(ValueError):
    pass


def write_inventory(
    archive: Path, out: Path, progress: Callable[[int, int], None] | None = None
) -> Summary:
    """Scan archive into out. The file appears only once the scan has finished."""
    archive = archive.resolve()
    out = out.resolve()
    if out.is_relative_to(archive):
        raise OutputInsideArchive("the output would be written inside the archive, which is read-only")
    out.parent.mkdir(parents=True, exist_ok=True)

    total = sum(1 for _ in iter_files(archive)) if progress else 0
    summary = Summary()
    partial = temporary_name(out).with_suffix(".partial")
    try:
        with partial.open("w", encoding="utf-8") as fh:
            for count, record in enumerate(scan(archive), 1):
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                summary.add(record)
                if progress:
                    progress(count, total)
        put_in_place(partial, out)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return summary

