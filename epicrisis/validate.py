"""Step 04: checks over transcriptions that need no model. It lists, it never changes data.

Every finding names a document (file and pages), a check code and counts; values and text stay
in the transcription. The result is written whole to data/sources/<id>/validation.json.
"""

import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from epicrisis import layout
from epicrisis.classify.pages import PageUnreadable, document_payloads, page_refs
from epicrisis.classify.report import goes_to_extract, group_documents, latest_pages
from epicrisis.corrections import as_a_person_left_it, load_corrections, load_value_corrections
from epicrisis.datesearch import load_search_results
from epicrisis.document_dates import document_date, provider_key, source_day_first
from epicrisis.extract.run import load_extracted, transcription_problems
from epicrisis.state import Unreadable
from epicrisis.records import read_records, torn_under
from epicrisis.printed_values import SIGNS, comparator_printed, fold, squeezed, number_matches, number_tokens
from epicrisis import reference
from epicrisis.rules import load as load_rules
from epicrisis.rules.kinds import VALIDATE
from epicrisis.rules.subjects import ONE_DOCUMENT, THE_ARCHIVE, Archive, Document, Found
from epicrisis.settings import rules_on
from epicrisis.sources import data_dir_of
from epicrisis.runs import one_at_a_time, write_whole
from epicrisis.values import is_result
from epicrisis.invocation import run

FILE_NAME = layout.VALIDATION

# The three findings that are not rules, and are not going to be. Each says what it is, where a
# finding of it hangs, what would settle it, and where it stands in the queue a person works
# through — the same four things every rule says in its own file.
#
# What is left here after possible_copy moved out is not a backlog. These three are not judgements
# about a person's data: they are this program reporting on its own reading. "Parts of the document
# were not transcribed" and "the checks still fail after the strong model" come from what the
# extract step recorded about itself; "a value that is nowhere in the text of its page" is one of
# that step's own checks, surfaced. There is nothing in them to tune and nothing to call noise, and
# a switch on them would be a switch that hides a hole in somebody's archive — which is how a
# transcription that had gone missing from disk came to be drawn as a finished step (see the note
# in web/app.py:_extract_step). They fire when something really is missing, and they stay on.
LEFTOVER = {
    "transcription_incomplete": ("document", "Parts of the document were not transcribed", 0,
        "Open the document beside the original. If pages or tables are missing, this file needs reading again."),
    "value_not_on_the_page": ("value", "A value that is nowhere in the text of its page", 2,
        "The page's own text does not contain this value. Open the page beside the card: either the layout was misread, or the page asked for something other than what it prints."),
    "checks_still_failing": ("document", "Automatic checks still fail after the strong model", 9,
        "The stronger model read this and the checks still do not pass. These need your eyes."),
}


def vocabulary(data_dir: Path | None = None) -> dict[str, dict]:
    """Every finding a person can be shown: what it is, where it hangs, what settles it, in order.

    One home for each of those, which is the rule's own file wherever the check has become a
    rule. What is left here is the handful that have not moved yet.
    """
    from epicrisis.rules import load as load_rules

    said = {code: {"kind": kind, "label": label, "order": order, "ask": ask}
            for code, (kind, label, order, ask) in LEFTOVER.items()}  # fmt: skip
    for rule in load_rules(data_dir):
        if rule.attaches:
            said[rule.id] = {"kind": rule.attaches, "label": rule.name, "order": rule.order, "ask": rule.settles}
    return dict(sorted(said.items(), key=lambda item: item[1]["order"]))


NUMBER = re.compile(r"[-+]?(?:\d+(?:[.,]\d+)?|[.,]\d+)")
# Codes from the extract checks that other checks here already cover or that do not point at an error.
COVERED_CHECK_PROBLEMS = {"unreadable_on_images", "no_column_headings", "no_column_headings_in_multi_value_rows"}
# Checks that mean a transcription is incomplete: listed on their own, ahead of the rest.
INCOMPLETE_CHECK_PROBLEMS = {"page_text_missing", "page_text_short", "page_numbers_missing", "table_page_without_values"}
# Checks from the extract pass that stand on their own here, with their own line and their own
# ask, rather than being counted together as "the checks still fail".
OWN_FINDING_PROBLEMS = {"value_not_on_the_page"}
RANGE = re.compile(r"^\s*([-+]?\d+(?:[.,]\d+)?)\s*[-–—]\s*([-+]?\d+(?:[.,]\d+)?)\s*$")


def _rows(item: dict) -> dict[tuple, list[dict]]:
    rows: dict[tuple, list[dict]] = defaultdict(list)
    for value in item["observations"]:
        rows[(value["provenance"]["page"], squeezed(value["name_as_printed"]))].append(value)
    return rows


def _found(document, value, line: str = "") -> Found:
    return Found(document.file_sha256, value["provenance"]["page"], None, line)


def number_differs(document, settings: dict) -> list[Found]:
    """The number stored is not the number printed."""
    return [_found(document, value) for value in document.item["observations"]
            if value.get("value_numeric") is not None
            and not number_matches(value["value_as_printed"] or "", value["value_numeric"])]  # fmt: skip


def comparator_missing(document, settings: dict) -> list[Found]:
    """A < or > printed and not stored, or stored and not printed.

    A comparator in words ("up to 5") counts as printed; a sign that is lost or invented does not.
    """
    found = []
    for value in document.item["observations"]:
        printed = value["value_as_printed"] or ""
        if value.get("value_numeric") is None:
            continue
        if printed.lstrip().startswith(SIGNS) and not value.get("comparator"):
            found.append(_found(document, value))
        if value.get("comparator") and not comparator_printed(printed):
            found.append(_found(document, value))
    return found


def quantitative_without_number(document, settings: dict) -> list[Found]:
    """A value counted as a number that holds none."""
    return [_found(document, value) for value in document.item["observations"]
            if value.get("value_kind") == "quantitative" and not number_tokens(value["value_as_printed"] or "")]  # fmt: skip


def reference_reversed(document, settings: dict) -> list[Found]:
    """A printed range whose lower bound is above its upper one."""
    found = []
    for value in document.item["observations"]:
        reference = RANGE.match(value.get("reference_as_printed") or "")
        if reference and _number(reference.group(1)) > _number(reference.group(2)):
            found.append(_found(document, value))
    return found


def range_read_two_ways(document, settings: dict) -> list[Found]:
    """The two readings of one printed range disagree: the model's numbers and this program's.

    Everything after the reading is done without a model, and the printed range is read by a parser
    in reference.py — a hand-written thing that has to know a decimal comma from a separator of
    thousands, a unit carrying a power, a word of direction in five languages, a label before the
    range, and a ratio that only looks like a range. It has been wrong, and when it is wrong nothing
    disagrees with it: the band is missing, or it is the wrong band, and no page says so. This asks
    the one reader that had the page in front of it for the same two numbers, and reports where the
    two answers differ.

    It reports and decides nothing. Which reading draws the band is one decision in one place —
    reference.parse, as before — and a disagreement is a thing for a person to look at, beside the
    scan of the page, exactly like every other finding here.

    Silent where the model was never asked: a document transcribed before those two fields existed
    carries neither, and the absence of an answer is not a disagreement with one.
    """
    apart_by = settings["apart_by"]

    def far_apart(ours: float | None, theirs: float | None) -> bool:
        if ours is None or theirs is None:
            return ours is not theirs  # one read a bound where the other read none
        widest = max(abs(ours), abs(theirs))
        return abs(ours - theirs) > apart_by * widest

    found = []
    for value in document.item["observations"]:
        printed = value.get("reference_as_printed")
        if not printed or ("reference_low" not in value and "reference_high" not in value):
            continue
        theirs = (value.get("reference_low"), value.get("reference_high"))
        ours = reference.parse(printed) or (None, None)
        if theirs == (None, None) and ours == (None, None):
            continue  # both say this is not one range for this person, which is an answer they share
        if any(far_apart(mine, theirs[side]) for side, mine in enumerate(ours)):
            found.append(_found(document, value))
    return found


def row_without_result(document, settings: dict) -> list[Found]:
    """A row with a unit or a range but nothing that is the result of it."""
    return [_found(document, values[0]) for values in _rows(document.item).values()
            if values and not any(is_result(value) for value in values)]  # fmt: skip


def repeated_value(document, settings: dict) -> list[Found]:
    """One line transcribed twice. The same value printed in two places is not that."""
    seen: Counter = Counter()
    where: dict[tuple, dict] = {}
    for value in document.item["observations"]:
        key = (value["provenance"]["page"], squeezed(value["name_as_printed"]),
               squeezed(value["value_as_printed"] or ""), value.get("column_as_printed"),
               squeezed(value["provenance"]["snippet"]))  # fmt: skip
        seen[key] += 1
        where.setdefault(key, value)
    return [_found(document, where[key]) for key, count in seen.items() for _ in range(count - 1) if count > 1]


def lab_without_values(document, settings: dict) -> list[Found]:
    """A laboratory panel that was transcribed and came back holding nothing."""
    if not (document.item["doc_type"] == "lab_panel" and not document.item["observations"] and document.goes_to_extract):
        return []
    return [Found(document.file_sha256, document.pages[0] if document.pages else 0, None, "")]


def unreadable_parts(document, settings: dict) -> list[Found]:
    """Parts of the page the reading itself said it could not make out."""
    return [Found(document.file_sha256, document.pages[0] if document.pages else 0, None, "")
            for _ in document.item["unreadable"]]  # fmt: skip


def date_to_check(document, settings: dict) -> list[Found]:
    """A document whose date could not be settled. What could not be settled is decided in
    document_dates.py; this only says that it is worth a person's eye."""
    if not document.date_flags:
        return []
    return [Found(document.file_sha256, document.pages[0] if document.pages else 0, None, "")]


def _the_document_of(documents: list[dict], hit: Found):
    """The one document a finding is about: its file, and the document holding the page it names.

    The hash alone is the file, and a file can hold several documents — a four-page scan that is
    two forms. Hanging a finding by hash put it on every document of the file, which turned
    forty-seven copies into a hundred and seven.

    The page it names, and not the page a document starts on. A rule is free to point at the page
    where the thing it found actually stands, which for a four-page form is usually not the first;
    matched against first pages only, such a finding belonged to no document at all and was thrown
    away in silence — a rule that runs, finds something, and is heard by nobody.
    """
    for doc in documents:
        if doc["file_sha256"] != hit.file_sha256:
            continue
        pages = doc["pages"] or [0]
        if hit.first_page in pages or hit.first_page == pages[0]:
            yield doc


def findings_for(document: Document, checked_by) -> Counter:
    """What the rules find in one document, counted by the id of the rule that found it.

    Only the rules that are handed one document. A rule of this step that looks at the archive as
    a whole is run once for all of them, after every document has been read, and would otherwise
    be handed a document and asked a question it cannot answer from one.
    """
    found: Counter = Counter()
    for rule in checked_by:
        if rule.check.looks_at != ONE_DOCUMENT:
            continue
        hits = rule.check.run(document, rule.settings)
        if hits:
            found[rule.id] += len(hits)
    return found


def validate_source(output: Path, archive_root: Path | None = None) -> dict:
    """Run every check over one archive. One run at a time: it writes that archive's findings."""
    with one_at_a_time(output / "validate.lock", "Checking this archive"):
        return _validate_source(output, archive_root)


def _validate_source(output: Path, archive_root: Path | None = None) -> dict:
    # Which of the checks this instance runs is its own answer, kept per rule; the way from an
    # archive's folder back to the instance it belongs to is written once, in sources.py.
    checked_by = rules_on(data_dir_of(output), load_rules(data_dir_of(output)), VALIDATE)
    records = {record["sha256"]: record for record in read_records(output / layout.INVENTORY) if "sha256" in record}
    pages = latest_pages(output / layout.CLASSIFY)
    corrections = load_corrections(output)
    # What a person put right themselves. The checks used to read only what the model wrote, so a
    # value somebody had corrected went on being reported as wrong for ever, and a row they had
    # marked as not a value went on producing findings. The only way to clear either was to call
    # the check noise — that is, to say of one's own correction that the check had been mistaken.
    # A list of work that does not shrink as the work is done is not a list of work.
    value_corrections = load_value_corrections(output)
    searches = load_search_results(output)

    groups = group_documents(pages)
    day_first_documents, day_first_providers = source_day_first(output, groups)
    documents = []
    for group in groups:
        sha256, numbers = group[0]["file_sha256"], tuple(page["page"] for page in group)
        if sha256 not in records:
            continue
        extracted = load_extracted(output / layout.EXTRACTED, sha256)
        item = next((doc for doc in (extracted or {"documents": []})["documents"] if tuple(doc["pages"]) == numbers), None)
        if not goes_to_extract(group[0]):
            item = None
        # Two readings of one document, on purpose, and each check gets the one it is asking about.
        # The value checks ask what the archive now holds, which is the transcription with this
        # archive's corrections on it. The transcription check asks whether the model wrote down
        # what was on the page, and judging that by a correction a person made afterwards is
        # answering a different question: the person's reading would be reported as the model's
        # mistake, and correcting a value would add a finding instead of taking one away.
        as_left = item
        if item is not None and value_corrections:
            as_left = {**item, "observations": as_a_person_left_it(
                item["observations"], sha256, numbers, value_corrections)}  # fmt: skip
        date = document_date(
            item, group, correction=corrections.get((sha256, numbers, "document_date")), search=searches.get((sha256, numbers)),
            day_first=(sha256, numbers) in day_first_documents or provider_key(item, group) in day_first_providers,
        )
        tabular = tuple(page["page"] for page in group if page.get("has_tabular_results"))
        subject = Document(file_sha256=sha256, pages=numbers, item=as_left, tabular_pages=tabular,
                           goes_to_extract=goes_to_extract(group[0]), date_flags=tuple(date["flags"]))  # fmt: skip
        findings = findings_for(subject, checked_by)
        if item:
            # Checks run again with today's rules: the page text for text pages, the transcription otherwise.
            problems = transcription_problems(item, _sent_texts(records[sha256], numbers, archive_root), tabular)
            incomplete = {code: count for code, count in problems.items() if code in INCOMPLETE_CHECK_PROBLEMS}
            if incomplete:
                findings["transcription_incomplete"] += sum(incomplete.values())
            for code in OWN_FINDING_PROBLEMS & problems.keys():
                findings[code] += problems[code]
            still = {code: count for code, count in problems.items()
                     if code not in COVERED_CHECK_PROBLEMS | INCOMPLETE_CHECK_PROBLEMS | OWN_FINDING_PROBLEMS}  # fmt: skip
            if still:
                findings["checks_still_failing"] += sum(still.values())
        # as_left, the same reading every line-by-line check is given: the transcription with what
        # a person corrected on top of it. The raw one went to the rules of the whole archive, so
        # the check for copies compared documents by what a model wrote and not by what the person
        # left — and a list of work that does not shrink as the work is done is not a list of work,
        # which is written twenty lines above this and was true of every check but that one.
        documents.append({"file_sha256": sha256, "pages": list(numbers), "date": date["value"],
                          "item": as_left, "findings": findings})  # fmt: skip

    # The rules of this step that look at the archive as a whole, rather than at one document:
    # they run once, after every document has been read, and hang their findings on the documents
    # they are about. A rule that is switched off does not run and finds nothing, here as anywhere.
    for rule in checked_by:
        if rule.check.looks_at == THE_ARCHIVE:
            # The archive as this step can give it: every document with its transcription, and no
            # rows. The same subject at the suspects step is built whole, out of the index, with
            # the habits and numbers of every test in it — so a rule written against those finds
            # nothing here rather than failing, and the halves are named here instead of guessed
            # at. kinds.SERVED says which steps hand out this subject at all.
            for hit in rule.check.run(Archive(rows=[], documents=documents), rule.settings):
                for doc in _the_document_of(documents, hit):
                    # Counted, not set. A rule of the whole archive may have several things to say
                    # about one document, and the line-by-line path beside this one counts them;
                    # this one wrote 1 whatever it was handed, so one rule was counted two ways
                    # depending only on which subject it happens to take.
                    doc["findings"][rule.id] += 1
    result = {
        "validated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "documents": [
            {"file_sha256": doc["file_sha256"], "pages": doc["pages"], "findings": dict(doc["findings"]), "copies": doc.get("copies", [])}
            for doc in documents
            if doc["findings"]
        ],
        "totals": dict(sum((doc["findings"] for doc in documents), Counter())),
        "coverage": coverage(output),
        "documents_checked": len(documents),
    }
    path = output / FILE_NAME
    write_whole(path, json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    return result


def coverage(output: Path) -> dict:
    """Whether every file, page and due document went through the pipeline. Counts, and file ids for gaps."""
    records = list(read_records(output / layout.INVENTORY))
    pages = latest_pages(output / layout.CLASSIFY)
    classified = {(page["file_sha256"], page["page"]) for page in pages}
    by_sha = {record["sha256"]: record for record in records if "sha256" in record}
    skipped = [record for record in records if not page_refs(record) and "sha256" in record]
    unclassified = [(sha256, ref.page) for sha256, record in by_sha.items() for ref in page_refs(record) if (sha256, ref.page) not in classified]
    due = [group for group in group_documents(pages) if goes_to_extract(group[0]) and group[0]["file_sha256"] in by_sha]
    untranscribed = []
    for group in due:
        extracted = load_extracted(output / layout.EXTRACTED, group[0]["file_sha256"])
        numbers = [page["page"] for page in group]
        if not any(doc["pages"] == numbers for doc in (extracted or {"documents": []})["documents"]):
            untranscribed.append((group[0]["file_sha256"], numbers))
    return {
        "files": len(by_sha),
        "files_not_read": [{"file_id": record["sha256"][:8], "reason": record.get("unsupported") or record.get("error") or record.get("category")} for record in skipped],
        "pages": sum(len(page_refs(record)) for record in by_sha.values()),
        "pages_not_classified": len(unclassified),
        "documents_due": len(due),
        "documents_not_transcribed": [{"file_id": sha256[:8], "pages": numbers} for sha256, numbers in untranscribed],
        # Lines this run could not read, from this archive's own files. read_records skips a torn
        # line and counts it, which is right — one lost record must not take the rest of an archive
        # down — but the count was asked for in exactly one place, a page of the dashboard, in
        # another process. From a terminal the archive simply got smaller and every number agreed
        # with every other: forty-three files became forty-two, and nothing said a word.
        "lines_not_read": torn_under(output),
    }


def validation_state(output: Path) -> dict:
    """Whether validation ran after the latest change to what it reads."""
    result = load_validation(output)
    if result is None:
        return {"state": "not_started", "label": "", "title": "Validate: not run yet"}
    changed = layout.changed_since(output, data_dir_of(output), "validate")
    ran = (output / FILE_NAME).stat().st_mtime
    documents = len(result["documents"])
    if ran < changed:
        return {"state": "partial", "label": "Outdated", "title": f"Validate: {documents} documents to check, data changed since"}
    return {"state": "done", "label": str(documents), "title": f"Validate: {documents} of {result['documents_checked']} documents to check"}


def _sent_texts(record: dict, pages: tuple[int, ...], archive_root: Path | None) -> dict[int, str]:
    """The text a text-layer document was sent as; empty for documents that went as images."""
    if archive_root is None:
        return {}
    by_page = {ref.page: ref for ref in page_refs(record)}
    refs = [by_page[page] for page in pages if page in by_page]
    if len(refs) != len(pages) or any(ref.route == "vision" for ref in refs):
        return {}
    with tempfile.TemporaryDirectory(prefix="epicrisis-validate-") as workdir:
        try:
            payloads = document_payloads(refs, archive_root, Path(workdir))
        except PageUnreadable:
            return {}
    return {ref.page: payload.text for ref, payload in zip(refs, payloads, strict=True) if payload.text is not None}


def load_validation(output: Path) -> dict | None:
    """The findings of the last run of the checks, or nothing where they have not been run.

    A file that is there and will not parse is neither, and it used to be raised from here into
    whatever was drawing the page: the status page and the page of things to check both answered
    with the words Internal Server Error, while the five pages that live on the index went on
    working — so the archive was half open and nothing said why. The way out is the cheapest in
    this program, and nothing named it: these findings are made by code, in seconds, with no model
    and nothing sent anywhere.
    """
    path = output / FILE_NAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as broken:
        raise Unreadable(
            FILE_NAME,
            "Nothing that was read is lost. These are the findings of the checks that need no "
            "model: they are made from what is already on this machine, in seconds.",
            # The command, with the archive and the instance in it, and nothing about a button.
            # This same file draws the status page and the page of things to check, so both are
            # down while it is torn — and "press Check again on the status page" sent a person who
            # lives on the dashboard to the one page that could not answer them, over the half of
            # the advice addressed to them. A way out that is not there is worse than one way out.
            f"Run them again: {run(f'validate --source {output.name}', data_dir_of(output))}. They "
            f"need no model and send nothing anywhere. The Check again button cannot be used for "
            f"this one: the status page it stands on is drawn from this same file and is down with "
            f"it until the checks have been run.",
        ) from broken


def possible_copies(documents: list[dict], settings: dict) -> list[Found]:
    """Documents in different files with the same date that print the same results.

    Either the same named values (any size, one file an excerpt or export of the other), or
    for longer documents of similar size mostly the same values.

    A rule of the registry rather than a check written into this file: the four numbers below
    decide what counts as a copy, they were constants nobody could see or move, and "is this a
    copy" is exactly the kind of judgement a person may want tuned, measured, or turned off —
    which is what the registry is for. It writes the list of twins onto each document as it
    goes, because the page that asks a person to choose which file answers for a group needs to
    know what the group is.
    """
    by_date = defaultdict(list)
    for doc in documents:
        if doc["item"] and doc["date"] and doc["item"]["observations"]:
            by_date[doc["date"]].append(doc)
    found: list[Found] = []
    already: set[int] = set()
    for group in by_date.values():
        for position, one in enumerate(group):
            for other in group[position + 1 :]:
                if one["file_sha256"] == other["file_sha256"]:
                    continue
                if not (_same_named_values(one["item"], other["item"], settings)
                        or _mostly_same_values(one["item"], other["item"], settings)):  # fmt: skip
                    continue
                for doc, twin in ((one, other), (other, one)):
                    # One finding per document, however many twins it has: a group of three used
                    # to report six findings over three documents, which reads as twice the work.
                    if id(doc) not in already:
                        already.add(id(doc))
                        found.append(Found(doc["file_sha256"], doc["pages"][0] if doc["pages"] else 0,
                                           doc["date"], ""))  # fmt: skip
                    doc.setdefault("copies", []).append({"file_sha256": twin["file_sha256"], "pages": twin["pages"]})
    return found


def _named_values(item: dict) -> set[tuple[str, str]]:
    """What a document says, as (name, value) pairs — the decimal separator taken out of it.

    One export writes 5,2 where another writes 5.2 for the same result, and two files of one
    blood draw were not seen as copies of each other because of the comma.
    """
    return {
        (fold(observation["name_as_printed"]).strip(" :"), squeezed(observation["value_as_printed"]).replace(",", "."))
        for observation in item["observations"]
        if is_result(observation)
    }


def _same_named_values(one: dict, other: dict, settings: dict) -> bool:
    """Identical named results, or all results of one document found in the other."""
    a, b = _named_values(one), _named_values(other)
    if not a or not b:
        return False
    small, large = sorted((a, b), key=len)
    return small == large or (len(small) >= settings["results_in_common"] and small <= large)


def _mostly_same_values(one: dict, other: dict, settings: dict) -> bool:
    """Mostly the same results, named. Numbers alone made copies of two different forms.

    A urinalysis and a coprogram from one day print the same handful of small numbers — 0, 1,
    1-2, 2-3 — and were filed as one document, after which one of them answered nothing at all,
    because only one document of a group of copies is shown.
    """
    a, b = _named_values(one), _named_values(other)
    if min(len(one["observations"]), len(other["observations"])) < settings["results_at_least"] or not a or not b:
        return False
    if min(len(a), len(b)) < settings["similar_in_size"] * max(len(a), len(b)):
        return False
    return len(a & b) >= settings["results_shared"] * min(len(a), len(b))


def _number(text: str) -> float:
    text = text.replace(",", ".")
    return float("0" + text if text.startswith(".") else text.replace("+.", "+0.").replace("-.", "-0."))

