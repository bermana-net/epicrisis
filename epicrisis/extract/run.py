"""Extract whole documents found by classify, resumable through the ledger.

Output: data/sources/<id>/extracted/<sha256[:16]>.json, one file per archive file holding its
documents. A document is rewritten whole, so re-extraction leaves no orphans. Temporary page
images live in a directory per call outside data/, removed right after the call.

A document that went as images and came back with unreadable parts gets one more pass with
close-ups of every page. The result with fewer unreadable parts is kept, and the pass is noted
in the document's provenance so it runs only once.
"""

import json
import re
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from epicrisis.invocation import CLI
from epicrisis import journal, layout
from epicrisis.classify.backend import BackendError, UsageLimitReached
from epicrisis.classify.pages import PageRef, PageUnreadable, document_payloads, page_refs
from epicrisis.classify.report import goes_to_extract, group_documents, latest_pages
from epicrisis.extract.backend import PROMPT_VERSION
from epicrisis.readers.text import TEXT_PAGE_CHARS
from epicrisis.dates import birth_dates, read_printed_date, same_date
from epicrisis.records import append_line, now, read_records
from epicrisis.printed_values import comparator_printed, number_tokens, squeezed, numbers_in_text, typewriter_digits, unexplained_letters
from epicrisis.parallel import DEFAULT_WORKERS, STATE_LOCK, run_parallel
from epicrisis.sources import Source, source_output_dir
from epicrisis.suspects import provider_looks_like_a_person
from epicrisis.runs import one_at_a_time, write_whole
from epicrisis.state import NoSpace, Unreadable, no_space, where

LOCK_NAME = "extract.lock"
MAX_PAGES_PER_CALL = 8
MAX_CLOSE_UP_PAGES_PER_CALL = 3  # five images per page
# Eight pages to a call was settled when a page meant a photograph of a form, which carries a few
# thousand characters. A page of a text file carries as many as it is cut to, so the same eight
# can be five times that, and a call that is too long is not a slow call but a failed one. This is
# how much text goes in one call; it is about what a document of two pages of this archive carried,
# which reads in six or seven minutes against a ceiling of fifteen.
TEXT_CHARS_PER_CALL = 20_000
SAMPLE_SIZE = 5
HEADER_FIELDS = (
    "title_as_printed",
    "date_of_study_as_printed",
    "date_of_report_as_printed",
    "provider_as_printed",
    "department_as_printed",
    "doctor_as_printed",
)


@dataclass
class ExtractStats:
    total: int = 0
    already_done: int = 0
    extracted: int = 0
    unreadable: int = 0
    failed: int = 0
    close_up_only: int = 0  # documents done earlier that got only the close-up pass in this run
    close_up_passes: int = 0
    close_up_better: int = 0
    escalated: int = 0  # documents the stronger model transcribed again after a failed check
    stopped: str | None = None

    @property
    def attempted(self) -> int:
        return self.extracted + self.unreadable + self.failed + self.close_up_only


@dataclass(frozen=True)
class DocumentRef:
    file_sha256: str
    pages: tuple[int, ...]
    doc_type: str
    language: str | None
    record: dict = field(compare=False, hash=False, repr=False)
    tabular_pages: tuple[int, ...] = field(default=(), compare=False, hash=False, repr=False)


def document_refs(records: dict[str, dict], classify_pages: list[dict]) -> list[DocumentRef]:
    """Documents from classify that go to extract, in file and page order.

    Only files with every page classified count: while classify still runs, the last document
    of a file could otherwise be cut short.
    """
    classified: dict[str, set[int]] = {}
    for page in classify_pages:
        classified.setdefault(page["file_sha256"], set()).add(page["page"])
    documents = []
    for pages in group_documents(classify_pages):
        first = pages[0]
        record = records.get(first["file_sha256"])
        if record is None or not goes_to_extract(first):
            continue
        if classified[first["file_sha256"]] != {ref.page for ref in page_refs(record)}:
            continue
        documents.append(
            DocumentRef(
                first["file_sha256"], tuple(page["page"] for page in pages), first["doc_type"], first.get("language"), record,
                tuple(page["page"] for page in pages if page.get("has_tabular_results")),
            )  # fmt: skip
        )
    return documents


def sample_documents(documents: list[DocumentRef], count: int = SAMPLE_SIZE) -> list[DocumentRef]:
    """A few documents of different types and languages, from different files where possible."""
    picked: list[DocumentRef] = []
    rules = [
        lambda doc: (doc.doc_type, doc.language) not in {(p.doc_type, p.language) for p in picked}
        and doc.file_sha256 not in {p.file_sha256 for p in picked},
        lambda doc: doc.doc_type not in {p.doc_type for p in picked},
        lambda doc: True,
    ]
    for rule in rules:
        for document in documents:
            if len(picked) == count:
                return picked
            if document not in picked and rule(document):
                picked.append(document)
    return picked


def pages_per_call(refs: list[PageRef]) -> int:
    """How many pages of this document go in one call.

    Eight, as for every document made of pages — unless the pages are a text file's, which are
    cut to a size of this program's own choosing and can each be as long as several printed ones.
    Then it is as many as fit the text a call carries, and never fewer than two: a call of one
    page would repeat that page as its own context, for ever.
    """
    if not any(ref.part == "text" for ref in refs):
        return MAX_PAGES_PER_CALL
    return max(2, min(MAX_PAGES_PER_CALL, TEXT_CHARS_PER_CALL // TEXT_PAGE_CHARS))


def call_chunks(refs: list[PageRef], size: int = MAX_PAGES_PER_CALL) -> list[list[PageRef]]:
    """Documents over the page limit are cut into calls that each repeat the first page."""
    if len(refs) <= size:
        return [refs]
    first, rest = refs[0], refs[1:]
    step = size - 1
    return [[first, *rest[start : start + step]] for start in range(0, len(rest), step)]


def extract_source(
    data_dir: Path,
    source: Source,
    backend,
    years: set[int] | None = None,
    sample: bool = False,
    limit: int | None = None,
    files: set[str] | None = None,
    done_by: str | None = None,
    redo: bool = False,
    close_ups: bool = False,
    progress: Callable[[ExtractStats], None] | None = None,
    workers: int = DEFAULT_WORKERS,
) -> ExtractStats:
    output = source_output_dir(data_dir, source.id)
    records = {record["sha256"]: record for record in read_records(output / layout.INVENTORY) if "sha256" in record}
    documents = document_refs(records, latest_pages(output / layout.CLASSIFY))
    if years is not None:
        documents = [document for document in documents if document.record.get("folder_year_hint") in years]
    if files:
        documents = [document for document in documents if any(document.file_sha256.startswith(start) for start in files)]
    if done_by:
        # Everything one model read, to be read again by another: the name of the model as stored.
        documents = [document for document in documents if done_by in ((_stored(output, document) or {}).get("provenance", {}).get("model") or "")]
    if sample:
        documents = sample_documents(documents)
    done = done_keys(output / layout.LEDGER, latest_pages(output / layout.CLASSIFY))
    stats = ExtractStats(total=len(documents))

    with one_at_a_time(output / LOCK_NAME, "Reading the documents"):
        models = getattr(backend, "accepted_models", {backend.model})
        due = []
        for document in documents:
            # A line in the ledger is a claim; the transcription on disk is the thing itself. They
            # can part: a document written while two of these runs were going at once, or a file
            # cut short by a machine losing power, leaves the claim and not the reading. Trusting
            # the claim alone meant the document was never read again by anything — not by another
            # update, not by extract run a second time — and it sat in the archive as "not
            # transcribed" with nothing able to say why. So the file is asked as well.
            stored = _stored(output, document)
            is_done = not redo and stored is not None and any(
                (document.file_sha256, document.pages, model, PROMPT_VERSION) in done for model in models)  # fmt: skip
            wants_close_ups = is_done and needs_close_ups(document, stored, force=close_ups)
            if is_done and not wants_close_ups:
                stats.already_done += 1
            elif limit is None or len(due) < limit:
                due.append((document, wants_close_ups))

        def work(item) -> bool:
            document, close_ups_only = item
            if close_ups_only:
                with STATE_LOCK:
                    stats.close_up_only += 1
                carry_on = _close_up_pass(document, output, source, getattr(backend, "stages", (backend,))[-1], stats)
            else:
                carry_on = _extract_document(document, output, source, backend, stats, force_close_ups=close_ups)
            if progress:
                with STATE_LOCK:
                    progress(stats)
            return carry_on

        run_parallel(due, work, workers)
    return stats


def needs_close_ups(document: DocumentRef, stored: dict | None, force: bool = False) -> bool:
    """Unreadable parts in a document read from images, and no close-up pass so far.

    force asks for the pass whatever the route and however many passes there have been: a person
    saying read this one again, not the run deciding for itself.
    """
    if stored is None or not stored["unreadable"]:
        return False
    if force:
        return True
    if "close_up_pass" in stored["provenance"]:
        return False
    try:
        return any(ref.route == "vision" for ref in _document_page_refs(document))
    except PageUnreadable:
        return False


def _document_page_refs(document: DocumentRef) -> list[PageRef]:
    by_page = {ref.page: ref for ref in page_refs(document.record)}
    refs = [by_page[page] for page in document.pages if page in by_page]
    if len(refs) != len(document.pages):
        raise PageUnreadable("pages missing from inventory")
    return refs


def _stored(output: Path, document: DocumentRef) -> dict | None:
    extracted = load_extracted(output / layout.EXTRACTED, document.file_sha256)
    documents = extracted["documents"] if extracted else []
    return next((item for item in documents if item["pages"] == list(document.pages)), None)


def _call_backend(document: DocumentRef, source: Source, backend, close_ups: bool = False) -> tuple[list, dict[int, str]]:
    """Calls for one document, and the page texts that went as text, by page of the file."""
    size = MAX_CLOSE_UP_PAGES_PER_CALL if close_ups else pages_per_call(_document_page_refs(document))
    parts, sent_texts = [], {}
    for chunk in call_chunks(_document_page_refs(document), size):
        with tempfile.TemporaryDirectory(prefix="epicrisis-document-", ignore_cleanup_errors=True) as folder:
            workdir = Path(folder)
            payloads = document_payloads(chunk, Path(source.path), workdir, zoom=close_ups, always_images=close_ups)
            sent_texts.update({ref.page: payload.text for ref, payload in zip(chunk, payloads, strict=True) if payload.text is not None})
            parts.append((chunk, backend.extract(payloads, workdir)))
    return parts, sent_texts


def read_again(document: DocumentRef, source: Source, backend, close_ups: bool = False) -> dict:
    """One more reading of a document, returned instead of stored: for checking a transcription."""
    parts, sent_texts = _call_backend(document, source, backend, close_ups=close_ups)
    return merge_document(document, parts, backend, sent_texts)



CYRILLIC = re.compile(r"[\u0400-\u04FF]")
LATIN = re.compile(r"[A-Za-z]")


def mixed_script_words(text: str | None) -> list[str]:
    """Words holding both alphabets at once, as in "Кліnіка": a letter read from the wrong one.

    A name may hold words of each alphabet ("Клініка VITAMED"); one word holding both is a slip.
    """
    return [word for word in re.findall(r"[^\W\d_]+", text or "") if CYRILLIC.search(word) and LATIN.search(word)]


MIN_PAGE_TEXT_CHARS = 20
MIN_TEXT_SHARE = 0.5  # words transcribed against words sent, for pages that went as text
MIN_NUMBER_SHARE = 0.9  # numbers of a text page found again in its transcription


def transcription_problems(document: dict, sent_texts: dict[int, str], tabular_pages: tuple[int, ...] = ()) -> dict[str, int]:
    """Checks a transcription can fail without a model. Counts by reason, never content.

    Pages that went as text are compared with that text: a value or reference the page does not
    contain was not copied as printed. Pages that went as images are compared with the model's
    own transcription of the page. Codes only; the counts are kept in provenance.
    """
    problems: dict[str, int] = {}

    def add(reason: str) -> None:
        problems[reason] = problems.get(reason, 0) + 1

    # The signing doctor is not the institution. A small model takes the name under the stamp and
    # writes it as the laboratory; a second reading with the strong model gets the letterhead.
    if provider_looks_like_a_person(document.get("provider_as_printed"), document.get("title_as_printed")):
        add("institution_looks_like_a_name")
    for printed in ("provider_as_printed", "title_as_printed"):
        if mixed_script_words(document.get(printed)):
            add("word_in_two_alphabets")

    own_texts = {item["page"]: squeezed(item["text"]) for item in document["page_texts"]}
    # Completeness: a model can stop early and still write correct fields for what it did.
    transcribed = {item["page"]: item["text"] for item in document["page_texts"]}
    for page in document["pages"]:
        text = transcribed.get(page) or ""
        if len(text.strip()) < MIN_PAGE_TEXT_CHARS:
            add("page_text_missing")
        elif page in sent_texts and len(sent_texts[page].split()) > 40 and len(text.split()) < MIN_TEXT_SHARE * len(sent_texts[page].split()):
            add("page_text_short")
        elif page in sent_texts:
            numbers = number_tokens(sent_texts[page])
            if len(numbers) >= 10:
                as_read = squeezed(typewriter_digits(text))
                found = sum(1 for number in numbers if squeezed(number) in as_read)
                if found < MIN_NUMBER_SHARE * len(numbers):
                    add("page_numbers_missing")
    # A value that is nowhere in the text of the page it claims to come from. The text of a
    # text-layer page is the page itself, not a reading of it, so a number that is not in it was
    # not printed there — whether a model misread the layout or a page told it what to write.
    # Only whole pages of real text are judged: a scan's text is the model's own transcription,
    # and a page with little text says nothing either way.
    for item in document["observations"]:
        page = item["provenance"]["page"]
        text = sent_texts.get(page)
        printed = (item.get("value_as_printed") or "").strip()
        if not text or len(text.split()) < 40 or not printed or item.get("value_kind") == "qualitative":
            continue
        if squeezed(typewriter_digits(printed)) not in squeezed(typewriter_digits(text)):
            add("value_not_on_the_page")

    pages_with_values = {item["provenance"]["page"] for item in document["observations"]}
    # Reports, letters and prescriptions often print a table inside their text; only lab results
    # must have values wherever classify saw a table.
    for page in tabular_pages if document["doc_type"] == "lab_panel" else ():
        if page not in pages_with_values:
            add("table_page_without_values")
    for item in document["observations"]:
        page = item["provenance"]["page"]
        source, label = (squeezed(sent_texts[page]), "page_text") if page in sent_texts else (own_texts.get(page, ""), "own_page_text")
        page_text = sent_texts[page] if page in sent_texts else "\n".join(text["text"] for text in document["page_texts"] if text["page"] == page)
        if squeezed(typewriter_digits(item["value_as_printed"])) not in squeezed(typewriter_digits(page_text)):
            add(f"value_not_in_{label}")
        # A reference may be printed over several lines or columns (norms for men and women, ages):
        # every number of it must be on the page, not the joined text as one piece.
        if item.get("reference_as_printed") and not numbers_in_text(item["reference_as_printed"], page_text):
            add(f"reference_not_in_{label}")
        # On text pages the comparison above is exact; letters there are printed, such as "Normal".
        if page not in sent_texts and item.get("value_numeric") is not None and unexplained_letters(item["value_as_printed"]):
            add("letters_in_numeric_value_on_image")
        # A comparator is a sign or word printed with the value, never a comparison with the range.
        if item.get("comparator") and not comparator_printed(item["value_as_printed"]):
            add("comparator_not_printed")
    # Headings matter where a row prints several values: they tell the result from the rest.
    # Many forms print one value per row and no headings at all; that is not a problem.
    #
    # A row, not a page. This counted a name twice anywhere on the page, which is not a row with
    # several values in it — it is a measurement printed in two places, which any long report
    # does. On the archive read on 2 October it fired on four documents where no name repeated
    # inside any row at all, and each of those was read a second time by the costliest model to
    # answer a complaint about a table that was not there. What tells one row from another is the
    # piece of the original line kept beside every value.
    rows = Counter((item["provenance"]["page"], squeezed(item["provenance"].get("snippet")),
                    squeezed(item["name_as_printed"])) for item in document["observations"])  # fmt: skip
    if any(count > 1 for count in rows.values()) and not any(item.get("column_as_printed") for item in document["observations"]):
        add("no_column_headings_in_multi_value_rows")
    language = document.get("language")
    births = [birth for text in [*sent_texts.values(), *(item["text"] for item in document["page_texts"])] for birth in birth_dates(text, language)]
    for printed_date in ("date_of_study_as_printed", "date_of_report_as_printed"):
        printed = read_printed_date(document.get(printed_date), language)
        if any(same_date(printed, birth) for birth in births):
            add("document_date_is_birth_date")
    if document["unreadable"] and len(sent_texts) < len(document["pages"]):
        add("unreadable_on_images")
    return problems


def _extract_document(document: DocumentRef, output: Path, source: Source, backend, stats: ExtractStats, force_close_ups: bool = False) -> bool:
    """Extract one document, moving to the next model when a check fails. Returns False when the run has to stop."""
    stages = getattr(backend, "stages", (backend,))
    escalations = []
    try:
        for number, stage in enumerate(stages, 1):
            try:
                parts, sent_texts = _call_backend(document, source, stage)
            except BackendError as exc:
                if isinstance(exc, UsageLimitReached) or number == len(stages):
                    raise
                escalations.append({"model": stage.model, "problems": {"call_failed": 1}})
                continue
            merged = merge_document(document, parts, stage, sent_texts)
            problems = transcription_problems(merged, sent_texts, document.tabular_pages)
            if not problems or number == len(stages):
                break
            escalations.append({"model": stage.model, "problems": problems})
    except PageUnreadable as exc:
        with STATE_LOCK:
            append_line(output / layout.LEDGER, _ledger_line(document, backend, "unreadable", str(exc)))
            stats.unreadable += 1
        # Which line of this project decided the page could not be read. The ledger holds the
        # document and the count; this holds the cause, said once per place it comes from.
        journal.a_page_would_not_read(output, source.id, exc, "extract")
        return True
    except UsageLimitReached:
        with STATE_LOCK:
            stats.stopped = "usage_limit"
        return False
    except BackendError as exc:
        with STATE_LOCK:
            append_line(output / layout.LEDGER, _ledger_line(document, backend, "failed", str(exc)))
            stats.failed += 1
        return True

    if escalations:
        merged["provenance"]["escalations"] = escalations
    if problems:
        merged["provenance"]["check_problems"] = problems
    with STATE_LOCK:
        write_document(output / layout.EXTRACTED, document.file_sha256, merged)
        append_line(output / layout.LEDGER, _ledger_line(document, backend, "done"))
        stats.extracted += 1
        stats.escalated += bool(escalations)
    if needs_close_ups(document, _stored(output, document), force=force_close_ups):
        return _close_up_pass(document, output, source, stages[-1], stats)
    return True


def _close_up_pass(document: DocumentRef, output: Path, source: Source, backend, stats: ExtractStats) -> bool:
    """Read the document again from close-ups and keep whichever result has fewer unreadable parts."""
    current = _stored(output, document)
    before = len(current["unreadable"])
    try:
        parts, sent_texts = _call_backend(document, source, backend, close_ups=True)
    except UsageLimitReached:
        with STATE_LOCK:
            stats.stopped = "usage_limit"
        return False
    except (PageUnreadable, BackendError) as exc:
        current["provenance"]["close_up_pass"] = {"status": "failed", "reason": str(exc), "at": now()}
        write_document(output / layout.EXTRACTED, document.file_sha256, current, first_reading=False)
        return True

    second = merge_document(document, parts, backend, sent_texts)
    after = len(second["unreadable"])
    kept = second if after < before else current
    kept["provenance"]["close_up_pass"] = {
        "status": "kept" if kept is second else "not_better",
        "unreadable_before": before,
        "unreadable_after": after,
        "at": now(),
    }
    with STATE_LOCK:
        write_document(output / layout.EXTRACTED, document.file_sha256, kept, first_reading=False)
        stats.close_up_passes += 1
        stats.close_up_better += kept is second
    return True


def _read_here(page: int | None, repeated: int | None) -> bool:
    """Whether a page belongs to this chunk and was not already read in the chunk before it."""
    return page is not None and page != repeated


def merge_document(document: DocumentRef, parts: list, backend, sent_texts: dict[int, str] | None = None) -> dict:
    """Join the calls of one document, mapping page numbers back to pages of the file.

    A page that went as text came from a file this program holds, so its text here is that file's
    own, not a copy written out by a model. The model is told not to write those pages back at
    all; where an older reading did, this is what decides between the two.
    """
    merged = {name: None for name in HEADER_FIELDS}
    observations, sections, unreadable = [], [], []
    page_texts: dict[int, str] = {}
    diagnoses: list[str] = []
    medications: list[str] = []

    for index, (chunk, extraction) in enumerate(parts):
        fields = extraction.fields
        to_file_page = {position: ref.page for position, ref in enumerate(chunk, 1)}
        # Each chunk after the first repeats the page the one before it ended on, for context.
        # That page has already been read, so everything found on it again is dropped here.
        repeated = chunk[0].page if index > 0 else None
        keep = partial(_read_here, repeated=repeated)

        for name in HEADER_FIELDS:
            merged[name] = merged[name] or fields.get(name)
        for item in fields["observations"]:
            page = to_file_page.get(item["page"])
            if keep(page):
                values = {key: value for key, value in item.items() if key not in ("page", "snippet")}
                observations.append({**values, "provenance": {"page": page, "snippet": item["snippet"]}})
        for item in fields["sections"]:
            page = to_file_page.get(item["page"])
            if keep(page):
                sections.append({**item, "page": page})
        for item in fields["page_texts"]:
            page = to_file_page.get(item["page"])
            if keep(page):
                page_texts.setdefault(page, item["text"])
        for position, ref in to_file_page.items():
            if keep(ref) and (sent_texts or {}).get(ref) is not None:
                page_texts[ref] = sent_texts[ref]
        for item in fields["unreadable"]:
            page = to_file_page.get(item["page"])
            if keep(page):
                unreadable.append({**item, "page": page})
        diagnoses += [value for value in fields["diagnoses_as_printed"] if value not in diagnoses]
        medications += [value for value in fields["medications_as_printed"] if value not in medications]

    first = parts[0][1]
    return {
        "doc_type": document.doc_type,
        **merged,
        "language": first.fields.get("language") or document.language,
        "pages": list(document.pages),
        "observations": observations,
        "sections": sections,
        "full_text": "\n\n".join(page_texts[page] for page in sorted(page_texts)),
        "page_texts": [{"page": page, "text": page_texts[page]} for page in sorted(page_texts)],
        "medications_as_printed": medications,
        "diagnoses_as_printed": diagnoses,
        "unreadable": unreadable,
        "provenance": {
            "backend": backend.name,
            "model": first.model,
            "requested_model": backend.model,
            "prompt_version": PROMPT_VERSION,
            "extracted_at": now(),
            "calls": len(parts),
        },
    }


def extracted_path(extracted_dir: Path, file_sha256: str) -> Path:
    return extracted_dir / f"{file_sha256[:16]}.json"


def load_extracted(extracted_dir: Path, file_sha256: str) -> dict | None:
    """One document's transcription, or None where it was never read.

    A file that is there and will not parse is the third thing, and it was the one state nothing
    answered: a card of that document said Internal Server Error, and `epicrisis index` and
    `epicrisis validate` each ended in a hundred and twenty lines of traceback that never once named
    the file — while every other file of state in this instance had been given a sentence. These are
    the most expensive files here; they are what a model was paid to produce.

    put_in_place says in its own words that a rename can reach the journal before the contents do,
    so a machine that loses power can leave an empty file exactly where a whole one was. The way out
    is cheap once the file is named: delete that one file and read that one document again.
    """
    path = extracted_path(extracted_dir, file_sha256)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as broken:
        if no_space(broken):
            raise NoSpace() from broken
        raise Unreadable(
            where(path),
            "Every other document is whole, and so is everything a person typed themselves: this is "
            "one document's transcription and nothing else reads it.",
            f"Delete that one file and run '{CLI} extract' — it reads that one document again "
            f"and leaves the rest alone. A reading of it may also be in {layout.REPLACED}/.",
        ) from broken


def write_document(extracted_dir: Path, file_sha256: str, document: dict, first_reading: bool = True) -> None:
    """Replace the document and any document overlapping its pages, then write atomically.

    first_reading is False where this run is saving a document it has already saved in this same
    run — the close-up pass writes its result over its own first result. Without that, the reading
    being displaced was the same reading, and a full copy of it went into replaced/ on every
    document with an unreadable part: the largest layer of the archive doubled, and the folder
    that should mean "somebody's earlier reading is in here" filled with noise.
    """
    with STATE_LOCK:
        _write_document(extracted_dir, file_sha256, document, first_reading)


def _write_document(extracted_dir: Path, file_sha256: str, document: dict, first_reading: bool = True) -> None:
    extracted_dir.mkdir(parents=True, exist_ok=True)
    data = load_extracted(extracted_dir, file_sha256) or {"file_sha256": file_sha256, "documents": []}
    pages = set(document["pages"])
    kept = [existing for existing in data["documents"] if not pages & set(existing["pages"])]
    if first_reading:
        _keep_what_is_displaced(extracted_dir, file_sha256, document,
                                [existing for existing in data["documents"] if pages & set(existing["pages"])])  # fmt: skip
    data["documents"] = sorted([*kept, document], key=lambda item: item["pages"][0])
    path = extracted_path(extracted_dir, file_sha256)
    write_whole(path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def _keep_what_is_displaced(extracted_dir: Path, file_sha256: str, writing: dict, displaced: list[dict]) -> None:
    """Put a reading that a later reading pushes out beside the archive rather than over it.

    This layer is described everywhere as written once and never rewritten, and it very nearly is:
    a document already read is skipped. But the skip is a key — the file, the pages, the model and
    the version of the prompt — and the key stops matching whenever a person picks another model
    on the settings page, whenever the prompt is raised, whenever `--redo` is given, and whenever
    a page is classified again and the document is regrouped. Then the document is read afresh and
    what was there is gone, with nothing to compare against; and a regrouping takes out every
    document whose pages the new one touches, so one new reading of pages 1-2 removed two.

    A model reads worse as well as better. The reading a person has already looked at, and may
    have made corrections against, is theirs. This is what `forget` does with an archive and what
    `recheck` does with a second opinion: keep it, next to the thing, and say when.
    """
    if not displaced:
        return
    aside = extracted_dir.parent / layout.REPLACED
    aside.mkdir(parents=True, exist_ok=True)
    for older in displaced:
        append_line(aside / f"{file_sha256}.jsonl", {
            "replaced_at": now(), "file_sha256": file_sha256,
            "by": {"pages": writing["pages"], "model": (writing.get("provenance") or {}).get("model")},
            "document": older,
        })  # fmt: skip


def earlier_readings(output: Path, file_sha256: str) -> list[dict]:
    """Readings of this file that a later reading pushed aside, newest first.

    Written since the day the folder existed and read by nothing at all: no page, no command, no
    line in the documentation. The scenario it was written for is a person who changed the model on
    the settings page, had the archive read again, and finds the new reading worse — and the whole
    point of keeping the old one is that they can see it. They could not.
    """
    kept = output / layout.REPLACED / f"{file_sha256}.jsonl"
    if not kept.exists():
        return []
    return sorted(read_records(kept), key=lambda item: item.get("replaced_at", ""), reverse=True)


def done_keys(ledger: Path, classify_pages: list[dict], statuses: tuple[str, ...] = ("done", "unreadable")) -> set[tuple]:
    """(file, pages, model, prompt version) of documents extracted since their pages were last classified.

    A page classified again after extraction (its route changed) makes the document due again.

    `statuses` narrows it to one kind of ending. Two questions are asked of this list and they are
    not the same: "what will a run skip" counts a document the reading itself declared unreadable,
    since reading it again gives the same answer; "what has a transcription on the disk" must not,
    because no transcription is written for one — and counting it there made the status page report
    a document as lost values for ever, on an archive where nothing was lost at all.
    """
    if not ledger.exists():
        return set()
    classified_at = {(page["file_sha256"], page["page"]): page.get("provenance", {}).get("classified_at", "") for page in classify_pages}
    keys = set()
    for entry in read_records(ledger):
        if entry.get("step") != "extract" or entry.get("status") not in statuses:
            continue
        if entry.get("at") and any(classified_at.get((entry["file_sha256"], page), "") > entry["at"] for page in entry["pages"]):
            continue
        keys.add((entry["file_sha256"], tuple(entry["pages"]), entry["model"], entry["prompt_version"]))
        # The ledger names the reader that read it, and where that was a ladder of two models it
        # names both, joined: "small>expert". A document read by such a ladder has been read by
        # its last model — the one this program now reads with on its own — so the line counts
        # under that name too. Without this, dropping the quick first pass would have made every
        # document already in the archive look unread, and the next run would have read four
        # hundred of them again, with the costliest model, for nothing.
        keys.add((entry["file_sha256"], tuple(entry["pages"]), entry["model"].split(">")[-1], entry["prompt_version"]))
    return keys



def _ledger_line(document: DocumentRef, backend, status: str, reason: str | None = None) -> dict:
    line = {
        "step": "extract",
        "file_sha256": document.file_sha256,
        "pages": list(document.pages),
        "model": backend.model,
        "prompt_version": PROMPT_VERSION,
        "status": status,
        "at": now(),
    }
    if reason:
        line["reason"] = reason
    return line

