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
from epicrisis.datesearch import documents_without_a_date, search_source
from epicrisis.extract.run import extract_source
from epicrisis.index.build import build_index
from epicrisis.inventory.run import NothingWhereTheArchiveWas, write_inventory
from epicrisis.readers.pdf import remembering_page_text
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
            # One pass over one archive, and the text layer of a page read once inside it.
            # It is left behind at the end of this archive and before the next one begins:
            # what it holds is printed on somebody's documents, and the first entry of the
            # constitution says such a thing stays with the archive it came from.
            with remembering_page_text():
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
                    # Before anything is read: where the documents of a text file begin. A scan has
                    # pages because somebody printed it; a text file has none, and a cut by a number
                    # of characters falls in the middle of a visit. Files of every other kind pass
                    # through this in no time at all, having their own pages already.
                    from epicrisis.boundaries import read_boundaries

                    marked = read_boundaries(registry.data_dir, source,
                                             engines.boundary_reader(registry.data_dir), say=say)  # fmt: skip
                    if marked:
                        say(f"  boundaries: {marked} text file(s) marked into documents")
                    classified = classify_source(registry.data_dir, source, backend)
                    say(f"  classify: {classified.classified} new pages, {classified.failed} failed")
                    extracted = extract_source(registry.data_dir, source, engines.extractor(registry.data_dir))
                    say(f"  extract: {extracted.extracted} new documents, {extracted.escalated} by Opus after a check, {extracted.failed} failed")
                    if "usage_limit" in (classified.stopped, extracted.stopped):
                        say("  stopped at the subscription usage limit; run update again later")
                    else:
                        targets = documents_without_a_date(source, output)
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
                # The same narrow question about the names of doctors and places. No index is
                # built after it, because nothing it writes changes what the archive answers:
                # a proposal about a person's identity is applied by a person and by nobody else.
                _propose_people(registry.data_dir, say, source.id)
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


def _propose_people(data_dir: Path, say, source_id: str) -> int:
    """Which printed names are one doctor, or one place — asked of a model, applied by nobody."""
    from epicrisis import people
    from epicrisis.people_proposals import ProposalBackend, names_to_ask_about, propose_people
    from epicrisis.query import open_index

    groups = people.load(data_dir, source_id)
    connection = open_index(data_dir, source_id)
    try:
        from epicrisis.query import who_made_them

        makers = who_made_them(connection, groups)
    finally:
        connection.close()
    if not any(len(names_to_ask_about(makers, kind, groups)) >= 2 for kind in people.KINDS):
        return 0
    with tempfile.TemporaryDirectory(prefix="epicrisis-people-") as workdir:
        counts = propose_people(data_dir, source_id, makers, ProposalBackend(model=model_for(data_dir, "strong"), data_dir=data_dir), Path(workdir))
    if counts["proposed"]:
        say(f"  who made them: {counts['proposed']} group(s) of names look like one and the same, "
            f"waiting for you on the Doctors and clinics page")  # fmt: skip
    return counts["proposed"]
