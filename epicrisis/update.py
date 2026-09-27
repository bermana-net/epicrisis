"""All steps for all sources in one go, for new or changed files: `epicrisis update`.

Inventory, then classify and extract (Haiku first, Opus when a check fails), the date search
for undated documents, validation, and the index. Everything already done is skipped by the
ledgers, so a run over an unchanged archive makes no model calls. Model steps run only for
sources whose model processing is confirmed.
"""

import json
import os
import shutil
import subprocess
import tempfile
import sys
from pathlib import Path

from epicrisis import layout
from epicrisis.models import model_for
from epicrisis.classify.run import classify_source
from epicrisis import engines
from epicrisis.consent import has_consent
from epicrisis.datesearch import search_source
from epicrisis.extract.run import extract_source
from epicrisis.index.build import build_index
from epicrisis.inventory.run import NothingWhereTheArchiveWas, write_inventory
from epicrisis.records import now, read_records
from epicrisis.runs import belongs_to_the_folder, holder, one_at_a_time
from epicrisis.sources import SourceRegistry, source_output_dir
from epicrisis.validate import validate_source
from epicrisis.invocation import CLI

LOCK_NAME = "update.lock"
MAX_NEW_NAMES = 120  # new spellings offered to indicators in one update
LOG_NAME = "update.log"


def run_update(data_dir: Path, say=print) -> dict:
    registry = SourceRegistry(data_dir)
    totals = {}
    with one_at_a_time(registry.data_dir / LOCK_NAME, "An update"):
        for source in registry.list():
            output = source_output_dir(registry.data_dir, source.id)
            try:
                summary = write_inventory(Path(source.path), output / layout.INVENTORY)
            except NothingWhereTheArchiveWas as gone:
                # One archive whose folder is not where it was does not stop the others being
                # brought up to date, and the refusal is said rather than raised: it names no
                # path, and it is the whole of what a person needs to know.
                say(f"Source {source.id}: {gone}")
                continue
            say(f"Source {source.id}: {summary.files} files")
            backend = engines.classifier(registry.data_dir)
            if not has_consent(registry.data_dir, backend.name):
                # Not a line in a progress log. This is the difference between an archive that has
                # been read and one that has not, and the run goes on to finish with a zero exit —
                # so a person following the README sees no failure, and then a dashboard with
                # nothing read in it, and no idea that one press on one page is all that is
                # missing. The same sentence the other commands give, and where to go.
                say(f"Source {source.id}: nothing was read, and nothing was sent.")
                say("  Model processing is not confirmed for this engine. Confirm it once, on the")
                say(f"  page that says exactly what would go and where: {CLI} serve, then /consent.")
            else:
                classified = classify_source(registry.data_dir, source, backend)
                say(f"  classify: {classified.classified} new pages, {classified.failed} failed")
                extracted = extract_source(registry.data_dir, source, engines.extractor(registry.data_dir))
                say(f"  extract: {extracted.extracted} new documents, {extracted.escalated} by Opus after a check, {extracted.failed} failed")
                if "usage_limit" in (classified.stopped, extracted.stopped):
                    say("  stopped at the subscription usage limit; run update again later")
                else:
                    targets = _undated(source, output)
                    searched = search_source(registry.data_dir, source, engines.date_search(registry.data_dir), targets)
                    say(f"  date search: {searched.searched} documents searched, dates found in {searched.with_dates}")
                    read = _read_materials(registry.data_dir, output)
                    say(f"  materials: {read['decided']} tables settled, {read['values']} values, "
                        f"{read['waiting']} unsure, {read['unclear']} could not be told")  # fmt: skip
            result = validate_source(output, Path(source.path))
            say(f"  validate: {len(result['documents'])} of {result['documents_checked']} documents to check")
        totals: dict = {}
        for source in registry.list():
            built = build_index(registry.data_dir, [source])
            totals = {name: totals.get(name, 0) + value for name, value in built.items() if isinstance(value, int)}
            say(f"Index for {source.whose}: {built['documents']} documents, {built['observations']} values")
            # This asks a model too, and so stands behind the same consent as every other step
            # that does. It stood outside it: the steps above were skipped, the person was told
            # so, and this one went to the provider anyway — which is the whole of what a consent
            # screen is for. What it sends is narrow (printed names and units, no values and no
            # dates), but that is an argument about the harm, not about the permission.
            if has_consent(registry.data_dir, engines.classifier(registry.data_dir).name):
                if _propose_new_names(registry.data_dir, say, source.id):
                    build_index(registry.data_dir, [source])
    return totals


def _read_materials(data_dir: Path, output: Path) -> dict:
    """What each table was measured in, where the form printed nothing. Headings only; no values."""
    from epicrisis.extract.run import load_extracted
    from epicrisis.material_reading import MaterialBackend, read_materials

    documents = []
    for record in read_records(output / layout.INVENTORY):
        if "sha256" not in record:
            continue
        extracted = load_extracted(output / layout.EXTRACTED, record["sha256"])
        for document in (extracted or {"documents": []})["documents"]:
            documents.append({**document, "file_sha256": record["sha256"]})
    return read_materials(output, documents, MaterialBackend(model=model_for(data_dir, "first"), data_dir=data_dir), output)


def start_in_background(data_dir: Path) -> None:
    """Run `epicrisis update` detached from the web server, logging to data/update.log.

    Appended to, not written over: the log of the run before this one is often the only record of
    why it stopped. The web server's own copy of the file is closed as soon as the child has it.
    """
    executable = Path(sys.executable).with_name("epicrisis")
    if not executable.exists():  # installed somewhere else than beside the interpreter
        executable = Path(shutil.which("epicrisis") or executable)
    with (data_dir / LOG_NAME).open("a", encoding="utf-8") as log:
        log.write(f"\n--- update started {now()} ---\n")
        log.flush()
        belongs_to_the_folder(data_dir / LOG_NAME)
        subprocess.Popen(
            [str(executable), "update", "--data-dir", str(data_dir)],
            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
        )  # fmt: skip


def update_running(data_dir: Path) -> bool:
    """Through runs.holder, the one reader of a lock file. See classify.run.is_running."""
    return holder(data_dir / LOCK_NAME) is not None


def _propose_new_names(data_dir: Path, say, source_id: str | None = None) -> int:
    """New spellings of results are offered to the indicators that already exist, never applied."""
    from epicrisis import indicators
    from epicrisis.indicator_proposals import ProposalBackend, propose_indicators, unassigned
    from epicrisis.query import open_index

    if not indicators.load(data_dir):
        return 0
    connection = open_index(data_dir, source_id)
    try:
        printed = indicators.printed_names(connection)
    finally:
        connection.close()
    waiting = unassigned(data_dir, printed)
    if not waiting:
        return 0
    with tempfile.TemporaryDirectory(prefix="epicrisis-indicators-") as workdir:
        counts = propose_indicators(data_dir, printed[: MAX_NEW_NAMES], ProposalBackend(model=model_for(data_dir, "strong"), data_dir=data_dir), Path(workdir))
    say(
        f"  indicators: {len(waiting)} new spellings, proposed {counts['added_to_existing']} for existing indicators "
        f"and {counts['new_indicators']} new groups, waiting for you on the Indicators page"
    )
    return counts["added_to_existing"] + counts["new_indicators"]


def _undated(source, output: Path) -> list:
    from epicrisis.web.documents import source_documents

    records = {record["sha256"]: record for record in read_records(output / layout.INVENTORY) if "sha256" in record}
    view = source_documents(source, output) or {"years": []}
    return [
        (records[row["file"]["sha256"]], tuple(row["pages"]))
        for group in view["years"]
        for row in group["documents"]
        if row["date"]["value"] is None and not row.get("unreadable") and row["doc_type"] != "Blank page"
    ]

