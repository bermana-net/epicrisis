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

from epicrisis.classify.pages import PageUnreadable, document_payloads, page_refs
from epicrisis.classify.report import goes_to_extract, group_documents, latest_pages
from epicrisis.corrections import load_corrections
from epicrisis.datesearch import load_search_results
from epicrisis.document_dates import document_date, provider_key, source_day_first
from epicrisis.extract.run import load_extracted, transcription_problems
from epicrisis.records import read_records
from epicrisis.printed_values import SIGNS, comparator_printed, fold, squeezed, number_matches, number_tokens
from epicrisis.runs import one_at_a_time, put_in_place, temporary_name

FILE_NAME = "validation.json"

CHECKS = {
    "transcription_incomplete": ("document", "Parts of the document were not transcribed"),
    "number_differs": ("value", "The number stored differs from the value as printed"),
    "comparator_missing": ("value", "A < or > sign is printed but not stored, or the other way round"),
    "quantitative_without_number": ("value", "A value marked as a number has no number"),
    "value_not_on_the_page": ("value", "A value that is nowhere in the text of its page"),
    "reference_reversed": ("value", "The reference range has its lower bound above the upper bound"),
    "row_without_result": ("value", "A row has other values but no result"),
    "repeated_value": ("value", "The same value is stored twice for the same row"),
    "lab_without_values": ("document", "Lab results with no values transcribed"),
    "checks_still_failing": ("document", "Automatic checks still fail after the strong model"),
    "unreadable_parts": ("document", "Parts could not be read"),
    "date_to_check": ("document", "The document date needs a look"),
    "possible_copy": ("document", "Possibly the same document as one in another file"),
}

# What the person is being asked to do about a finding. A list of findings without this is a
# wall: the page says a check failed and leaves the reader to work out whether it is their
# problem and what would settle it. Each line says who decides and what settles it.
ASKS = {
    "transcription_incomplete": "Open the document beside the original. If pages or tables are missing, this file needs reading again.",
    "number_differs": "The number stored is not the one printed. Open the line and set it to what the form says.",
    "comparator_missing": "A < or > is printed and not stored, or stored and not printed. Correct the line on the card.",
    "quantitative_without_number": "A value counted as a number has none. Read the line on the form and correct it, or mark it as not a value.",
    "value_not_on_the_page": "The page's own text does not contain this value. Open the page beside the card: either the layout was misread, or the page asked for something other than what it prints.",
    "reference_reversed": "The range reads backwards. Often the form prints it that way; look, and correct it only if the form does not.",
    "row_without_result": "A row has a unit or a range but no result. The result may sit in a column that was not read. Open it and see.",
    "repeated_value": "One line stored twice. Remove the second one on the card.",
    "lab_without_values": "Lab results with nothing transcribed. It may be a covering letter, or it may need reading again.",
    "checks_still_failing": "The stronger model read this and the checks still do not pass. These need your eyes.",
    "date_to_check": "The date could not be settled from the document. Set it by hand on the card, or leave it as it was read.",
    "possible_copy": "Choose which file answers for the group.",
    "unreadable_parts": "Mostly nothing to do: a signature, a stamp, a handwritten margin. Read what could not be read, and open only what touches a value.",
}

# Numbers as labs print them, including a leading decimal separator such as ",5".
# The order a person works through findings: errors in values first, unreadable parts last.
PRIORITY = [
    "transcription_incomplete", "number_differs", "value_not_on_the_page", "comparator_missing", "quantitative_without_number", "reference_reversed", "row_without_result",
    "repeated_value", "lab_without_values", "checks_still_failing", "date_to_check", "possible_copy", "unreadable_parts",
]  # fmt: skip

NUMBER = re.compile(r"[-+]?(?:\d+(?:[.,]\d+)?|[.,]\d+)")
# Codes from the extract checks that other checks here already cover or that do not point at an error.
COVERED_CHECK_PROBLEMS = {"unreadable_on_images", "no_column_headings", "no_column_headings_in_multi_value_rows"}
# Checks that mean a transcription is incomplete: listed on their own, ahead of the rest.
INCOMPLETE_CHECK_PROBLEMS = {"page_text_missing", "page_text_short", "page_numbers_missing", "table_page_without_values"}
# Checks from the extract pass that stand on their own here, with their own line and their own
# ask, rather than being counted together as "the checks still fail".
OWN_FINDING_PROBLEMS = {"value_not_on_the_page"}
RANGE = re.compile(r"^\s*([-+]?\d+(?:[.,]\d+)?)\s*[-–—]\s*([-+]?\d+(?:[.,]\d+)?)\s*$")
COPY_MIN_SHARED = 0.8
COPY_MIN_VALUES = 5
COPY_MIN_SIZE_RATIO = 0.6  # a short form sharing a date with a long one is not its copy
COPY_MIN_CONTAINED = 3  # a shorter document whose named results all appear in a longer one


def value_findings(document: dict) -> Counter:
    found: Counter = Counter()
    seen = Counter()
    rows: dict[tuple, list[dict]] = defaultdict(list)
    for item in document["observations"]:
        printed = item["value_as_printed"] or ""
        rows[(item["provenance"]["page"], squeezed(item["name_as_printed"]))].append(item)
        # The same line transcribed twice; the same value printed in two places is fine.
        seen[(item["provenance"]["page"], squeezed(item["name_as_printed"]), squeezed(printed), item.get("column_as_printed"), squeezed(item["provenance"]["snippet"]))] += 1
        numbers = number_tokens(printed)
        if item.get("value_numeric") is not None:
            if not number_matches(printed, item["value_numeric"]):
                found["number_differs"] += 1
            # A comparator in words ("up to 5") counts as printed; a sign that is lost or invented does not.
            if printed.lstrip().startswith(SIGNS) and not item.get("comparator"):
                found["comparator_missing"] += 1
            if item.get("comparator") and not comparator_printed(printed):
                found["comparator_missing"] += 1
        if item.get("value_kind") == "quantitative" and not numbers:
            found["quantitative_without_number"] += 1
        reference = RANGE.match(item.get("reference_as_printed") or "")
        if reference and _number(reference.group(1)) > _number(reference.group(2)):
            found["reference_reversed"] += 1
    for items in rows.values():
        if any(item.get("value_role") == "other" for item in items) and not any(item.get("value_role") == "result" for item in items):
            found["row_without_result"] += 1
    found["repeated_value"] += sum(count - 1 for count in seen.values() if count > 1)
    return +found


def validate_source(output: Path, archive_root: Path | None = None) -> dict:
    """Run every check over one archive. One run at a time: it writes that archive's findings."""
    with one_at_a_time(output / "validate.lock", "Checking this archive"):
        return _validate_source(output, archive_root)


def _validate_source(output: Path, archive_root: Path | None = None) -> dict:
    records = {record["sha256"]: record for record in read_records(output / "inventory.jsonl") if "sha256" in record}
    pages = latest_pages(output / "classify.jsonl")
    corrections = load_corrections(output)
    searches = load_search_results(output)

    groups = group_documents(pages)
    day_first_documents, day_first_providers = source_day_first(output, groups)
    documents = []
    for group in groups:
        sha256, numbers = group[0]["file_sha256"], tuple(page["page"] for page in group)
        if sha256 not in records:
            continue
        extracted = load_extracted(output / "extracted", sha256)
        item = next((doc for doc in (extracted or {"documents": []})["documents"] if tuple(doc["pages"]) == numbers), None)
        if not goes_to_extract(group[0]):
            item = None
        date = document_date(
            item, group, correction=corrections.get((sha256, numbers, "document_date")), search=searches.get((sha256, numbers)),
            day_first=(sha256, numbers) in day_first_documents or provider_key(item, group) in day_first_providers,
        )
        findings = Counter()
        if item:
            findings += value_findings(item)
            if item["doc_type"] == "lab_panel" and not item["observations"] and goes_to_extract(group[0]):
                findings["lab_without_values"] += 1
            # Checks run again with today's rules: the page text for text pages, the transcription otherwise.
            tabular = tuple(page["page"] for page in group if page.get("has_tabular_results"))
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
            if item["unreadable"]:
                findings["unreadable_parts"] += len(item["unreadable"])
        if date["flags"]:
            findings["date_to_check"] += 1
        documents.append({"file_sha256": sha256, "pages": list(numbers), "date": date["value"], "item": item, "findings": findings})

    _mark_possible_copies(documents)
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
    temporary = temporary_name(path)
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    put_in_place(temporary, path)
    return result


def coverage(output: Path) -> dict:
    """Whether every file, page and due document went through the pipeline. Counts, and file ids for gaps."""
    records = list(read_records(output / "inventory.jsonl"))
    pages = latest_pages(output / "classify.jsonl")
    classified = {(page["file_sha256"], page["page"]) for page in pages}
    by_sha = {record["sha256"]: record for record in records if "sha256" in record}
    skipped = [record for record in records if not page_refs(record) and "sha256" in record]
    unclassified = [(sha256, ref.page) for sha256, record in by_sha.items() for ref in page_refs(record) if (sha256, ref.page) not in classified]
    due = [group for group in group_documents(pages) if goes_to_extract(group[0]) and group[0]["file_sha256"] in by_sha]
    untranscribed = []
    for group in due:
        extracted = load_extracted(output / "extracted", group[0]["file_sha256"])
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
    }


def validation_state(output: Path) -> dict:
    """Whether validation ran after the latest change to what it reads."""
    result = load_validation(output)
    if result is None:
        return {"state": "not_started", "label": "", "title": "Validate: not run yet"}
    inputs = [output / "classify.jsonl", output / "corrections.jsonl", output / "date_search.jsonl", output / "extracted"]
    changed = max((path.stat().st_mtime for path in inputs if path.exists()), default=0)
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
    path = output / FILE_NAME
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _mark_possible_copies(documents: list[dict]) -> None:
    """Documents in different files with the same date that print the same results.

    Either the same named values (any size, one file an excerpt or export of the other), or
    for longer documents of similar size mostly the same values.
    """
    by_date = defaultdict(list)
    for doc in documents:
        if doc["item"] and doc["date"] and doc["item"]["observations"]:
            by_date[doc["date"]].append(doc)
    for group in by_date.values():
        for position, one in enumerate(group):
            for other in group[position + 1 :]:
                if one["file_sha256"] == other["file_sha256"]:
                    continue
                if not (_same_named_values(one["item"], other["item"]) or _mostly_same_values(one["item"], other["item"])):
                    continue
                for doc, twin in ((one, other), (other, one)):
                    # One finding per document, however many twins it has: a group of three used
                    # to report six findings over three documents, which reads as twice the work.
                    doc["findings"]["possible_copy"] = 1
                    doc.setdefault("copies", []).append({"file_sha256": twin["file_sha256"], "pages": twin["pages"]})


def _named_values(item: dict) -> set[tuple[str, str]]:
    """What a document says, as (name, value) pairs — the decimal separator taken out of it.

    One export writes 5,2 where another writes 5.2 for the same result, and two files of one
    blood draw were not seen as copies of each other because of the comma.
    """
    return {
        (fold(observation["name_as_printed"]).strip(" :"), squeezed(observation["value_as_printed"]).replace(",", "."))
        for observation in item["observations"]
        if observation.get("value_role", "result") == "result"
    }


def _same_named_values(one: dict, other: dict) -> bool:
    """Identical named results, or all results of one document found in the other (at least three)."""
    a, b = _named_values(one), _named_values(other)
    if not a or not b:
        return False
    small, large = sorted((a, b), key=len)
    return small == large or (len(small) >= COPY_MIN_CONTAINED and small <= large)


def _mostly_same_values(one: dict, other: dict) -> bool:
    """Mostly the same results, named. Numbers alone made copies of two different forms.

    A urinalysis and a coprogram from one day print the same handful of small numbers — 0, 1,
    1-2, 2-3 — and were filed as one document, after which one of them answered nothing at all,
    because only one document of a group of copies is shown.
    """
    a, b = _named_values(one), _named_values(other)
    if min(len(one["observations"]), len(other["observations"])) < COPY_MIN_VALUES or not a or not b:
        return False
    if min(len(a), len(b)) < COPY_MIN_SIZE_RATIO * max(len(a), len(b)):
        return False
    return len(a & b) >= COPY_MIN_SHARED * min(len(a), len(b))


def _number(text: str) -> float:
    text = text.replace(",", ".")
    return float("0" + text if text.startswith(".") else text.replace("+.", "+0.").replace("-.", "-0."))

