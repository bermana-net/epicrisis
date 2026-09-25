"""Reading documents again with another model, to see whether a transcription holds.

Nothing here touches the archive's own transcription. The second reading is kept beside it, in
data/sources/<id>/rechecked/<model>/, and compared line by line: a value counts as agreed when
the name, the number, the unit and the reference range are printed the same way after folding.

Two models reading the same page do not prove it right — they can be wrong together — but where
they disagree, the page is worth opening. That is what this is for.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from epicrisis import layout
from epicrisis.classify.backend import UsageLimitReached
from epicrisis.classify.report import latest_pages
from epicrisis.extract.run import document_refs, load_extracted, read_again
from epicrisis.records import read_records
from epicrisis.runs import one_at_a_time
from epicrisis.parallel import DEFAULT_WORKERS, STATE_LOCK, run_parallel
from epicrisis.printed_values import fold
from epicrisis.sources import Source, source_output_dir

HEADER_FIELDS = ("title_as_printed", "date_of_study_as_printed", "provider_as_printed")
COMPARED = ("value_as_printed", "unit_as_printed", "reference_as_printed", "flag_as_printed")


@dataclass
class Disagreement:
    file_id: str
    page: int
    name: str
    field: str
    ours: str | None
    theirs: str | None


@dataclass
class RecheckStats:
    documents: int = 0
    failed: int = 0
    values_ours: int = 0
    values_theirs: int = 0
    agreed: int = 0
    only_ours: list[tuple[str, int, str]] = field(default_factory=list)
    only_theirs: list[tuple[str, int, str]] = field(default_factory=list)
    differing: list[Disagreement] = field(default_factory=list)
    header: list[Disagreement] = field(default_factory=list)
    text_chars: tuple[int, int] = (0, 0)
    stopped: str = ""  # "usage_limit" when the subscription ran out and the rest was not read


def line_key(observation: dict) -> tuple:
    return (observation["provenance"]["page"], fold(observation.get("name_as_printed") or ""))


def _same(first: str | None, second: str | None) -> bool:
    return re.sub(r"\s+", "", (first or "")).casefold() == re.sub(r"\s+", "", (second or "")).casefold()


def compare(ours: dict, theirs: dict, file_id: str, stats: RecheckStats) -> None:
    """Count what the two readings agree on and collect every line where they do not."""
    mine = {line_key(item): item for item in ours["observations"]}
    other = {line_key(item): item for item in theirs["observations"]}
    stats.values_ours += len(mine)
    stats.values_theirs += len(other)
    for key in mine.keys() - other.keys():
        stats.only_ours.append((file_id, key[0], mine[key]["name_as_printed"]))
    for key in other.keys() - mine.keys():
        stats.only_theirs.append((file_id, key[0], other[key]["name_as_printed"]))
    for key in mine.keys() & other.keys():
        differences = [name for name in COMPARED if not _same(mine[key].get(name), other[key].get(name))]
        if not differences:
            stats.agreed += 1
        for name in differences:
            stats.differing.append(
                Disagreement(file_id, key[0], mine[key]["name_as_printed"], name.removesuffix("_as_printed"),
                             mine[key].get(name), other[key].get(name))
            )  # fmt: skip
    for name in HEADER_FIELDS:
        if not _same(ours.get(name), theirs.get(name)):
            stats.header.append(Disagreement(file_id, ours["pages"][0], "—", name.removesuffix("_as_printed"), ours.get(name), theirs.get(name)))
    chars = lambda document: sum(len(page["text"]) for page in document["page_texts"])  # noqa: E731
    stats.text_chars = (stats.text_chars[0] + chars(ours), stats.text_chars[1] + chars(theirs))


def recheck_source(*args, **kwargs):
    """One second reading of an archive at a time: two would write the same files twice over."""
    output = source_output_dir(args[0] if args else kwargs["data_dir"],
                               (args[1] if len(args) > 1 else kwargs["source"]).id)  # fmt: skip
    with one_at_a_time(output / "recheck.lock", "Reading this archive again"):
        return _recheck_source(*args, **kwargs)


def _recheck_source(
    data_dir: Path,
    source: Source,
    backend,
    files: set[str] | None = None,
    done_by: str | None = None,
    limit: int | None = None,
    close_ups: bool = False,
    workers: int = DEFAULT_WORKERS,
    say=lambda text: None,
) -> RecheckStats:
    output = source_output_dir(data_dir, source.id)
    records = {record["sha256"]: record for record in read_records(output / layout.INVENTORY) if "sha256" in record}
    documents = document_refs(records, latest_pages(output / layout.CLASSIFY))
    if files:
        documents = [item for item in documents if any(item.file_sha256.startswith(start) for start in files)]
    stored = {}
    due = []
    for document in documents:
        extracted = load_extracted(output / layout.EXTRACTED, document.file_sha256)
        found = next((item for item in (extracted["documents"] if extracted else []) if item["pages"] == list(document.pages)), None)
        if found is not None and done_by and done_by not in (found["provenance"].get("model") or ""):
            continue
        if found is not None and (limit is None or len(due) < limit):
            stored[(document.file_sha256, document.pages)] = found
            due.append(document)

    stats = RecheckStats()
    folder = output / layout.RECHECKED / re.sub(r"[^a-z0-9.-]+", "-", backend.model.casefold())
    folder.mkdir(parents=True, exist_ok=True)

    def work(document) -> bool:
        try:
            fresh = read_again(document, source, backend, close_ups=close_ups)
        except UsageLimitReached:
            # The subscription is spent: every further call would fail the same way, so the run
            # stops here and says so, as every other model step does.
            with STATE_LOCK:
                stats.stopped = "usage_limit"
                say("  the subscription usage limit was reached; nothing more was read")
            return False
        except Exception as exc:  # the type only: messages can quote a document
            with STATE_LOCK:
                stats.failed += 1
                say(f"  {document.file_sha256[:8]} p{document.pages[0]}: {type(exc).__name__}")
            return True
        with STATE_LOCK:
            path = folder / f"{document.file_sha256[:16]}-{document.pages[0]}.json"
            path.write_text(json.dumps(fresh, ensure_ascii=False, indent=1), encoding="utf-8")
            stats.documents += 1
            compare(stored[(document.file_sha256, document.pages)], fresh, document.file_sha256[:8], stats)
            say(f"  {document.file_sha256[:8]} p{document.pages[0]}: read again")
        return True

    run_parallel(due, work, workers)
    return stats
