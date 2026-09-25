"""The date a document is sorted and grouped by, from what is printed or set by hand.

Folder names play no part. A date set by a person wins; then the study date, the report date and
dates on the pages; then a date the date search found. A date of birth is never taken.
"""

import re
from datetime import date
from pathlib import Path

from epicrisis.dates import birth_dates, read_printed_date, same_date
from epicrisis.extract.run import load_extracted

DATE_FLAGS = {
    "not_read": "Date printed but not read",
    "ambiguous": "Day and month may be swapped",
    "future": "Date in the future",
    "early": "Date before 1950",
    "apart": "The report is dated before the study",
    "birth_date": "A date of birth was given as the document date",
    "second_look": "Found on a second look for dates",
    "second_look_unclear": "Found on a second look, some digits unclear",
}

# Kinds from the date search, in the order they are taken as the document's date.
SEARCH_KINDS = ("study", "report", "issue", "signature", "stamp", "other", "device")


def document_date(
    extracted: dict | None,
    pages: list[dict],
    today: date | None = None,
    correction: dict | None = None,
    search: dict | None = None,
    day_first: bool = False,
) -> dict:
    """The date a document is sorted by: a date set by hand, else study date, else report date,
    else a date printed on its pages, else one the date search found."""
    today = today or date.today()
    if correction:
        value = date.fromisoformat(correction["value"])
        printed = next((item for item in ((extracted or {}).get("date_of_study_as_printed"), (extracted or {}).get("date_of_report_as_printed"), *(page.get("date_on_page") for page in pages)) if item), None)
        return {"value": value, "year": value.year, "label": value.strftime("%d.%m.%Y"), "printed": printed, "flags": [], "by_hand": True}
    language = (extracted or {}).get("language") or pages[0].get("language")
    study = read_printed_date((extracted or {}).get("date_of_study_as_printed"), language, today)
    report = read_printed_date((extracted or {}).get("date_of_report_as_printed"), language, today)
    on_pages = [read_printed_date(page.get("date_on_page"), language, today) for page in pages if page.get("date_on_page")]
    text = "\n".join(item["text"] for item in (extracted or {}).get("page_texts", []))
    births = birth_dates(text, language, today)

    def is_birth(item) -> bool:
        return any(same_date(item, birth) for birth in births)

    chosen = next((item for item in (study, report, *on_pages) if item.value and not is_birth(item)), None)
    printed = next((item.printed for item in (study, report, *on_pages) if item.printed and item.printed.strip()), None)

    flags = []
    if chosen is None and search:
        # Legible dates first, then unclear ones, each by kind; an unclear date is shown to be checked.
        found = sorted(
            (item for item in search["found"] if item["kind"] in SEARCH_KINDS),
            key=lambda item: (not item["legible"], SEARCH_KINDS.index(item["kind"])),
        )
        for item in found:
            candidate = read_printed_date(item["as_printed"], language, today)
            if candidate.value and not is_birth(candidate):
                chosen = candidate
                flags.append("second_look" if item["legible"] else "second_look_unclear")
                break
    if any(item.value and is_birth(item) for item in (study, report)):
        flags.append("birth_date")
    if printed and chosen is None:
        flags.append("not_read")
    # Day and month cannot be swapped when another date of the same document can be read only
    # one way round. Evidence of either kind settles it; only a document that says nothing about
    # its own habit is left ambiguous.
    others = [item for item in (study, report, *on_pages) if item.value and item is not chosen]
    settled = day_first or any(_day_first_only(item) or _month_first_only(item) for item in others)
    if chosen and chosen.ambiguous and not settled:
        flags.append("ambiguous")
    if chosen and chosen.value > today:
        flags.append("future")
    if chosen and chosen.value.year < 1950:
        flags.append("early")
    # Reports printed long after the study are common (records printed from a portal); a report
    # dated before its study is not.
    if (
        study.precision == "day" and report.precision == "day" and not is_birth(study) and not is_birth(report)
        and (study.value - report.value).days > 1
    ):  # fmt: skip
        flags.append("apart")
    return {
        "value": chosen.value if chosen else None,
        "year": chosen.year if chosen else None,
        "label": _date_label(chosen),
        "printed": (chosen.printed if chosen else printed),
        "flags": [{"code": code, "label": DATE_FLAGS[code]} for code in flags],
        "by_hand": False,
    }


def _date_label(printed_date) -> str | None:
    if printed_date is None:
        return None
    value = printed_date.value
    return {"day": value.strftime("%d.%m.%Y"), "month": value.strftime("%m.%Y")}.get(printed_date.precision, str(value.year))


def _day_first_only(item) -> bool:
    """A numeric date whose first number is above 12, so it can only be day first."""
    match = re.search(r"(?<!\d)(\d{1,2})\s*[./\-]\s*(\d{1,2})\s*[./\-]\s*\d{2,4}", item.printed or "")
    return bool(match) and int(match.group(1)) > 12


def _month_first_only(item) -> bool:
    """A numeric date whose second number is above 12, so it can only be month first.

    The mirror of the rule above, and it was missing: a form printing 02/28/2020 said plainly
    how it writes dates, and the document's other date was still read the other way round,
    flagged as ambiguous, and then reported as a report dated before its own study.
    """
    match = re.search(r"(?<!\d)(\d{1,2})\s*[./\-]\s*(\d{1,2})\s*[./\-]\s*\d{2,4}", item.printed or "")
    return bool(match) and int(match.group(1)) <= 12 < int(match.group(2))


def provider_key(extracted: dict | None, pages: list[dict]) -> str | None:
    name = (extracted or {}).get("provider_as_printed") or next((page.get("provider_on_page") for page in pages if page.get("provider_on_page")), None)
    key = re.sub(r"[^\w]+", "", (name or "").casefold())[:24]
    return key or None


def prints_day_first(extracted: dict | None, pages: list[dict]) -> bool:
    """Whether a document prints a numeric date that can only be read day first."""
    printed = [(extracted or {}).get("date_of_study_as_printed"), (extracted or {}).get("date_of_report_as_printed")]
    printed += [page.get("date_on_page") for page in pages]
    return any(_day_first_only(read_printed_date(text)) for text in printed if text)


def day_first_evidence(documents) -> tuple[set[str], set[str]]:
    """Documents and institutions that print day first: (file_sha256, extracted, pages) items.

    The key is the document rather than the file it sits in. A scan holding a dozen forms is one
    file, and one day-first date anywhere in it used to settle the reading of every other form in
    the same scan, including forms from another laboratory printing dates the other way round.
    An institution's habit does carry: the same laboratory writes its dates the same way.
    """
    documents_seen, providers = set(), set()
    for file_sha256, extracted, pages in documents:
        if prints_day_first(extracted, pages):
            documents_seen.add((file_sha256, tuple(page["page"] for page in pages)))
            if key := provider_key(extracted, pages):
                providers.add(key)
    return documents_seen, providers


def source_day_first(output: Path, documents: list[list[dict]]) -> tuple[set[str], set[str]]:
    """Files and institutions of this source that print dates day first somewhere."""
    items = []
    for pages in documents:
        extracted = load_extracted(output / "extracted", pages[0]["file_sha256"])
        numbers = [page["page"] for page in pages]
        items.append((pages[0]["file_sha256"], next((d for d in (extracted or {"documents": []})["documents"] if d["pages"] == numbers), None), pages))
    return day_first_evidence(items)
