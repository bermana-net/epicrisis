"""Documents view: what classify found in each file, as printed, with links to the original pages.

It lists and shows. It never rates, flags or summarises anything about health.
"""

import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from markupsafe import Markup

from epicrisis import layout
from epicrisis.classify.pages import (PageUnreadable, cannot_be_read, has_no_image,
                                      original_text, page_refs)  # fmt: skip
from epicrisis.classify.report import goes_to_extract, group_documents, latest_pages
from epicrisis.classify.run import is_running
from epicrisis.corrections import line_key, load_corrections, load_value_corrections
from epicrisis.datesearch import load_search_results
from epicrisis.document_dates import document_date, provider_key, source_day_first
from epicrisis.extract.run import earlier_readings, load_extracted
from epicrisis.indicators import approved_names
from epicrisis.index.build import institution_and_doctor
from epicrisis.printed_values import fold
from epicrisis.records import read_records
from epicrisis.validate import load_validation, validation_state, vocabulary
from epicrisis import judgements
from epicrisis.sources import data_dir_of, Source
from epicrisis.values import is_result

FILE_ID_LENGTH = 8

# ISO 639-1 codes the model returns, shown by name so "uk" is not read as a country.
LANGUAGE_NAMES = {
    "uk": "Ukrainian",
    "ru": "Russian",
    "en": "English",
    "el": "Greek",
    "he": "Hebrew",
    "es": "Spanish",
    "de": "German",
    "fr": "French",
    "it": "Italian",
    "pl": "Polish",
    "pt": "Portuguese",
    "tr": "Turkish",
    "ar": "Arabic",
    "be": "Belarusian",
    "bg": "Bulgarian",
    "cs": "Czech",
    "ro": "Romanian",
    "ka": "Georgian",
    "hy": "Armenian",
    "lv": "Latvian",
    "lt": "Lithuanian",
    "et": "Estonian",
    "nl": "Dutch",
}


def file_id(sha256: str) -> str:
    """Short name for a file, taken from its content: it survives renames and moves."""
    return sha256[:FILE_ID_LENGTH]


# The word a person reads for each printed field they may put right. The card says what the model
# had read in the fields they changed, and it says it on the row: "1,35" on its own would not say
# which of five fields that number had stood in. The order here is the order of the table columns.
PRINTED_FIELD_WORDS = {
    "name_as_printed": "name",
    "value_as_printed": "value",
    "unit_as_printed": "unit",
    "reference_as_printed": "range",
    "flag_as_printed": "flag",
}


def _corrected(document: dict, output: Path, file_sha256: str, pages: list[int], data_dir: Path | None = None) -> list[dict]:
    """The document's values as they stand after a person's corrections, each marked.

    A value whose printed name belongs to an indicator also carries it, so a line on the card can
    lead to that test's whole history without the card having to know the index.
    """
    corrections = load_value_corrections(output)
    known = approved_names(data_dir) if data_dir else {}
    shown = []
    for observation in document["observations"]:
        key = line_key(observation)
        correction = corrections.get((file_sha256, tuple(pages), key))
        item = {**observation, "key": key, "correction": None,
                "indicator_id": known.get(fold(observation["name_as_printed"]))}  # fmt: skip
        if correction and correction.get("removed"):
            item["correction"] = {"removed": True}
        elif correction:
            # "was" is what the row says out loud, and it is narrower than "printed" twice over.
            # The form posts all five printed fields whichever one a person retyped, so "printed"
            # holds every one of them; saying "as the model read it" over four fields nobody
            # touched is the noise this line would be rejected for. And the form carries the
            # material a person set, which is nothing a model ever read at all.
            item = {**item, **correction["changes"], "correction": {
                "changes": correction["changes"],
                "printed": {field: observation.get(field) for field in correction["changes"]},
                "was": [{"field": word, "text": observation.get(field)}
                        for field, word in PRINTED_FIELD_WORDS.items()
                        if field in correction["changes"]
                        and (observation.get(field) or "") != (correction["changes"][field] or "")],
            }}  # fmt: skip
        shown.append(item)
    return shown


def observation_tables(observations: list[dict]) -> list[dict]:
    """The document's results laid out as the printed tables: same blocks, same column headings.

    A row is the value in the result column, with the values the lab printed in further columns
    of the same row. Headings are taken as printed; what each column holds comes from extraction.
    """
    tables: list[dict] = []
    for item in observations:
        page, heading = item["provenance"]["page"], item.get("table_as_printed")
        if not tables or (tables[-1]["page"], tables[-1]["heading"]) != (page, heading):
            tables.append({"page": page, "heading": heading, "rows": []})
        rows = tables[-1]["rows"]
        same_row = rows and rows[-1]["main"]["name_as_printed"] == item["name_as_printed"]
        if same_row and not is_result(item):
            rows[-1]["others"].append(item)
        elif same_row and not is_result(rows[-1]["main"]):
            rows[-1]["others"].insert(0, rows[-1]["main"])
            rows[-1]["main"] = item
        else:
            rows.append({"main": item, "others": []})

    for table in tables:
        mains = [row["main"] for row in table["rows"]]
        table["result_heading"] = next((item["column_as_printed"] for item in mains if item.get("column_as_printed")), None)
        table["reference_heading"] = next(
            (item["reference_column_as_printed"] for item in mains if item.get("reference_column_as_printed")), None
        )
        headings: list[str | None] = []
        for row in table["rows"]:
            for other in row["others"]:
                if other.get("column_as_printed") not in headings:
                    headings.append(other.get("column_as_printed"))
            row["by_column"] = {heading: [o for o in row["others"] if o.get("column_as_printed") == heading] for heading in headings}
        table["other_headings"] = headings
    return tables


def file_reading(extracted: dict | None, rows: list[dict], error_pages: list[int]) -> dict:
    """How much of a file's text was read, for the colour of its file ID.

    Nobody knows how many characters an unreadable part had, so each page counts transcribed
    lines against lines plus unreadable parts, and the file takes the mean over its pages.
    Pages classify could not open count as nothing read. This rates the transcription, not health.
    """
    shares = {page: 0.0 for page in error_pages}
    parts_total = 0
    documents = extracted["documents"] if extracted else []
    for document in documents:
        lines = {item["page"]: sum(1 for line in item["text"].splitlines() if line.strip()) for item in document["page_texts"]}
        parts = Counter(item["page"] for item in document["unreadable"])
        parts_total += len(document["unreadable"])
        for page in document["pages"]:
            if lines.get(page, 0) + parts[page]:
                shares[page] = lines.get(page, 0) / (lines.get(page, 0) + parts[page])

    due = [row for row in rows if row["goes_to_extract"]]
    done = {document["pages"][0] for document in documents}
    waiting = sum(1 for row in due if row["pages"][0] not in done)
    if not shares:
        title = "Not transcribed yet" if due else "Nothing in this file is transcribed"
        return {"percent": None, "background": "var(--line)", "color": "var(--ink)", "title": title}

    share = sum(shares.values()) / len(shares)
    percent = 100 if share == 1 else min(int(share * 100), 99)
    pages = len(shares)
    title = f"Text read: {percent}% over {pages} {'page' if pages == 1 else 'pages'}"
    if parts_total:
        title += f", {parts_total} {'part' if parts_total == 1 else 'parts'} could not be read"
    if error_pages:
        title += f", {len(error_pages)} {'page' if len(error_pages) == 1 else 'pages'} could not be opened"
    if waiting:
        title += f"; {len(due) - waiting} of {len(due)} documents transcribed so far"
    return {"percent": percent, **reading_colour(share), "title": title}


def reading_colour(share: float) -> dict:
    """Ruby at nothing read, through red, orange and yellow, to green only when all is read.

    The hue grows with the square of the share, so the high end, where most files are, stays apart.
    """
    if share >= 1:
        return {"background": "hsl(130, 62%, 34%)", "color": "#fff"}
    hue = round(-12 + 124 * share**2) % 360
    if 30 <= hue <= 100:  # orange to yellow-green: light background, dark text
        return {"background": f"hsl({hue}, 90%, 52%)", "color": "#141414"}
    return {"background": f"hsl({hue}, 78%, 40%)", "color": "#fff"}


def language_name(code: str | None) -> str | None:
    if not code:
        return None
    return LANGUAGE_NAMES.get(code, code)


# Two lowercase letters, which is what classify's schema asks a model for and all a lang= needs.
A_LANGUAGE_CODE = re.compile(r"[a-z]{2}")


def said_in(code: str | None) -> Markup:
    """` lang="uk"` for an element that carries printed text, or nothing where nobody knows.

    The shell of every page is lang="en" and stays so: the words around the content — the
    headings, the labels, the sentences this program writes — are English. The content is not.
    Most of this archive is Russian, Ukrainian and Greek, and a browser reads lang to choose a
    fallback face for a character the page's own font has not got, and to decide how to read a
    line aloud. One document is one language, which is why this goes on the elements holding that
    document's printed text rather than on the page.

    Nothing is invented. The code is the one classify read off the page, and anything that is not
    exactly two lowercase letters renders no attribute at all: a wrong lang is worse than none,
    because a browser acts on it.
    """
    if not isinstance(code, str) or not A_LANGUAGE_CODE.fullmatch(code):
        return Markup("")
    return Markup(f' lang="{code}"')


# (kind, folder) -> (when its inputs last changed, view). By folder, not by archive id: two data
# folders on one machine can hold the same id, and one would then answer for the other.
_VIEWS: dict[tuple, tuple[float, dict]] = {}


def _last_change(output: Path) -> float:
    """When anything this view is built from last changed, so a built view can be kept."""
    # Everything a view here is built from. The verdicts belong on this list: the findings page
    # shows what a person said about each one, and without it a verdict just pressed came back to
    # a page rebuilt from the cache — the click looked as though it had done nothing.
    inputs = (layout.INVENTORY, layout.CLASSIFY, layout.CORRECTIONS, layout.DATE_SEARCH,
              layout.VALIDATION, layout.EXTRACTED, layout.JUDGEMENTS)  # fmt: skip
    return max(((output / name).stat().st_mtime for name in inputs if (output / name).exists()), default=0.0)


def _kept(kind: str, source: Source, output: Path) -> dict | None:
    """A view built from files that have not changed since. Reading 170 files takes a second."""
    when, view = _VIEWS.get((kind, str(output)), (None, None))
    return view if when == _last_change(output) else None


def _keep(kind: str, source: Source, output: Path, view: dict | None) -> dict | None:
    if view is not None:
        _VIEWS[(kind, str(output))] = (_last_change(output), view)
    return view


def source_documents(source: Source, output: Path) -> dict | None:
    inventory = output / layout.INVENTORY
    if not inventory.exists():
        return None
    kept = _kept("documents", source, output)
    if kept is not None:
        return kept
    records = {record["sha256"]: record for record in read_records(inventory) if "sha256" in record}
    total_pages = sum(len(page_refs(record)) for record in records.values())
    pages = latest_pages(output / layout.CLASSIFY)
    documents = group_documents(pages)

    by_file: dict[str, list[list[dict]]] = defaultdict(list)
    for document in documents:
        by_file[document[0]["file_sha256"]].append(document)
    unreadable_pages: dict[str, list[int]] = defaultdict(list)
    for page in pages:
        if "error" in page:
            unreadable_pages[page["file_sha256"]].append(page["page"])

    corrections = load_corrections(output)
    searches = load_search_results(output)
    day_first_documents, day_first_providers = source_day_first(output, documents)
    years: dict[int | None, list[dict]] = defaultdict(list)
    for sha256 in by_file.keys() | unreadable_pages.keys():
        record = records.get(sha256)
        if record is None:  # the file left the archive after classify
            continue
        extracted = load_extracted(output / layout.EXTRACTED, sha256)
        transcribed = {tuple(item["pages"]): item for item in extracted["documents"]} if extracted else {}
        rows = [_document_row(document) for document in by_file.get(sha256, [])]
        file = {
            "sha256": sha256,
            "file_id": file_id(sha256),
            "path": record["path"],
            "page_count": len(page_refs(record)),
            "reading": file_reading(extracted, rows, unreadable_pages.get(sha256, [])),
        }
        for row, document in zip(rows, by_file.get(sha256, []), strict=True):
            # A transcription of a document classified since as not for extraction no longer applies.
            item = transcribed.get(tuple(row["pages"])) if row["goes_to_extract"] else None
            correction = corrections.get((sha256, tuple(row["pages"]), "document_date"))
            search = searches.get((sha256, tuple(row["pages"])))
            settled = (sha256, tuple(page["page"] for page in document)) in day_first_documents or provider_key(item, document) in day_first_providers
            row.update(file=file, extracted=item is not None, date=document_date(item, document, correction=correction, search=search, day_first=settled))
            years[row["date"]["year"]].append(row)
        if unreadable_pages.get(sha256):
            numbers = unreadable_pages[sha256]
            row = {
                "doc_type": "Could not be read", "pages": numbers, "page_label": ", ".join(map(str, numbers)),
                "provider": None, "language": None, "goes_to_extract": False, "illegible": True, "unreadable": True,
                layout.EXTRACTED: False, "file": file, "date": {"value": None, "year": None, "label": None, "precision": None, "printed": None, "flags": [], "by_hand": False},
            }  # fmt: skip
            years[None].append(row)

    def order(row: dict) -> tuple:
        return (row["date"]["value"] or date.min, row["file"]["path"], row["pages"][0])

    return _keep("documents", source, output, {
        "id": source.id,
        "name": source.name,
        "whose": source.whose,
        "classified_pages": len(pages),
        "total_pages": total_pages,
        "document_count": len(documents),
        "dates_to_check": sum(1 for rows in years.values() for row in rows if row["date"]["flags"]),
        "running": is_running(output),
        "years": [
            {
                "year": year,
                "documents": sorted(rows, key=order, reverse=True),
                "document_count": sum(1 for row in rows if not row.get("unreadable")),
                "transcribed_count": sum(1 for row in rows if row[layout.EXTRACTED]),
                "dates_to_check": sum(1 for row in rows if row["date"]["flags"]),
            }
            for year, rows in sorted(years.items(), key=lambda item: (item[0] is None, -(item[0] or 0)))
        ],
    })


def how_many_documents_to_check(view: dict) -> int:
    """The N of "N of M documents to check": the documents this page in fact puts work on.

    It was `len(result["documents"])` — every document any finding hangs on, whether or not this
    page then draws it, and it drops findings in two places. One is `and row` below: a finding
    whose document the classification no longer groups the same way has no row to draw, and the
    file of findings is older than the grouping every time the checks have not been run since.
    The other is `possible_copy`, which `app.py` takes out of the blocks once the index has
    grouped the copies, because a group is one decision and not three documents to read — it is
    drawn as its own block instead, and the documents in that block are work on this page too.

    So it is counted off what is drawn, like every other count beside a list here: nine documents
    of the archive read on 4 October 2026 carry no finding but `possible_copy`, and the header's
    372 was right about them only by the accident of the copies block holding exactly those nine.
    Asked again by whoever changes what the page draws, which is the whole point of its taking
    the view rather than the findings.
    """
    drawn = {(entry["sha256"], entry["pages"]) for check in view["checks"] for entry in check["entries"]}
    # Said the way an entry says it, because a group's members carry their pages as a list.
    drawn |= {(item["file_sha256"], ",".join(str(page) for page in item["pages"]))
              for group in view.get("copy_groups") or () for item in group["members"]}  # fmt: skip
    return len(drawn)


def review_view(source: Source, output: Path) -> dict | None:
    """Findings of the last validation, by check in the order to work through them."""
    from epicrisis.corrections import unmatched_documents, unmatched_values

    kept = _kept("review", source, output)
    if kept is not None:
        return kept
    result = load_validation(output)
    view = source_documents(source, output)
    if result is None or view is None:
        return {"id": source.id, "name": source.name, "validated_at": None, "checks": [], "documents_checked": 0} if view else None
    rows = {(row["file"]["sha256"], tuple(row["pages"])): row for group in view["years"] for row in group["documents"]}
    checks = []
    said = vocabulary(data_dir_of(output))
    # What a person has already said about each finding, so the page shows it back to them and
    # a second opinion is one click rather than a guess at what they clicked last time.
    judged = judgements.latest(output)
    # Every code the findings hold, in the order of the rules, and then the ones no rule explains
    # any more. A rule deleted or renamed leaves its findings in the file until the checks are run
    # again; iterating the rules alone dropped them from this page while the count above it and
    # the tools over the network went on reporting them — a list that says "34 of 400 documents
    # to check" over a page that shows thirty.
    orphans = sorted({code for finding in result["documents"] for code in finding["findings"]} - set(said))
    for code in [*said, *orphans]:
        entries = []
        for finding in result["documents"]:
            row = rows.get((finding["file_sha256"], tuple(finding["pages"])))
            if code in finding["findings"] and row:
                copies = [rows[key] for key in ((copy["file_sha256"], tuple(copy["pages"])) for copy in finding["copies"]) if key in rows]
                entries.append({"row": row, "count": finding["findings"][code],
                                "said": judged.get((code, finding["file_sha256"], tuple(finding["pages"])), ""),
                                "pages": ",".join(str(page) for page in finding["pages"]),
                                "sha256": finding["file_sha256"],
                                "copies": copies if code == "possible_copy" else []})  # fmt: skip
        if entries:
            entries.sort(key=lambda entry: (entry["row"]["date"]["value"] or date.min), reverse=True)
            explains = said.get(code, {})
            checks.append({"code": code, "kind": explains.get("kind", "document"),
                           "label": explains.get("label", code),
                           "ask": explains.get("ask") or "No rule of this instance explains this any more: "
                                  "it was found by a rule that has since been removed or renamed, and it "
                                  "goes when the checks are run again.",
                           "entries": entries})  # fmt: skip
    lost = [
        {**item, "row": rows.get((item["file_sha256"], tuple(item["pages"])))} for item in unmatched_values(output)
    ]  # fmt: skip
    return _keep("review", source, output, {
        "lost_corrections": lost,
        # The same loss, for the corrections made on a whole document rather than on one line.
        "lost_document_corrections": unmatched_documents(output),
        # And for a person's verdict on a finding, which is kept against the same key and was the
        # one of the three that went uncounted — while still counting towards the two numbers that
        # decide whether a rule is kept at all.
        "lost_judgements": judgements.unmatched(output),
        "id": source.id,
        "name": source.name,
        "whose": source.whose,
        "validated_at": result["validated_at"],
        "documents_checked": result["documents_checked"],
        # Of the blocks above, not of the file of findings: see how_many_documents_to_check, and
        # `_from_the_index` in app.py, which asks it again once it has changed what is drawn.
        "documents_with_findings": how_many_documents_to_check({"checks": checks}),
        "outdated": validation_state(output)["state"] == "partial",
        "checks": checks,
    })


def document_findings(output: Path, file_sha256: str, pages: list[int]) -> list[dict]:
    result = load_validation(output)
    finding = next((item for item in (result or {"documents": []})["documents"] if item["file_sha256"] == file_sha256 and item["pages"] == pages), None)
    if finding is None:
        return []
    said = vocabulary(data_dir_of(output))
    return [
        {"label": said[code]["label"], "count": finding["findings"][code],
         "copies": finding["copies"] if code == "possible_copy" else []}  # fmt: skip
        for code in said
        if code in finding["findings"]
    ]


def document_card(source: Source, output: Path, file_sha256: str, first_page: int) -> dict | None:
    """One document: what classify found, and what extract transcribed if it has run."""
    inventory = output / layout.INVENTORY
    if not inventory.exists():
        return None
    record = next((r for r in read_records(inventory) if r.get("sha256") == file_sha256), None)
    if record is None:
        return None
    pages = [page for page in latest_pages(output / layout.CLASSIFY) if page["file_sha256"] == file_sha256]
    classified = next((doc for doc in group_documents(pages) if doc[0]["page"] == first_page), None)
    if classified is None:
        return None
    extracted = load_extracted(output / layout.EXTRACTED, file_sha256)
    document = next((d for d in extracted["documents"] if d["pages"][0] == first_page), None) if extracted else None
    if document and (document["pages"] != [page["page"] for page in classified] or not goes_to_extract(classified[0])):
        document = None
    # How this archive writes its dates, read once for the card rather than inside the argument
    # that needed it: the call below used to rebuild it, walking every document of the archive
    # and reading every transcription from disk, twice, to render one card.
    on_pages = tuple(page["page"] for page in classified)
    corrections = load_corrections(output)
    searches = load_search_results(output)
    day_first_documents, day_first_providers = source_day_first(output, group_documents(latest_pages(output / layout.CLASSIFY)))
    writes_day_first = ((file_sha256, on_pages) in day_first_documents
                        or provider_key(document, classified) in day_first_providers)  # fmt: skip
    # What the index did with a name the form printed where the institution goes — asked of the
    # index's own decision rather than taken again here. This card prints the two fields as the
    # model read them, so on such a document it showed a person under "Institution as printed" and
    # a dash under "Doctor as printed", while every page drawn from the index named that person the
    # doctor of this document and no institution at all. The seventh entry of the constitution: two
    # answers to one question on one screen is a defect, not a detail.
    institution, _doctor, printed_as_a_person = institution_and_doctor(document, classified)
    printed_as_the_institution = (
        {"name": printed_as_a_person, "read_as_the_doctor": not institution} if printed_as_a_person else None
    )  # fmt: skip
    return {
        "source_id": source.id,
        "sha256": file_sha256,
        "file_id": file_id(file_sha256),
        "reading": file_reading(
            extracted, [_document_row(doc) for doc in group_documents(pages)], [page["page"] for page in pages if "error" in page]
        ),
        "path": record["path"],
        "year": record.get("folder_year_hint"),
        "summary": _document_row(classified),
        "date": document_date(
            document, classified,
            correction=corrections.get((file_sha256, on_pages, "document_date")),
            search=searches.get((file_sha256, on_pages)),
            day_first=writes_day_first,
        ),  # fmt: skip
        "document": document,
        "printed_as_the_institution": printed_as_the_institution,
        "observation_tables": observation_tables(_corrected(document, output, file_sha256, [page["page"] for page in classified], output.parent.parent)) if document else [],
        "findings": document_findings(output, file_sha256, [page["page"] for page in classified]),
        "language": language_name(document["language"]) if document else None,
        # The code as well as the name: the name is for a person to read, the code is what goes
        # on the elements carrying this document's printed text, as a lang= a browser acts on.
        "language_code": (document or {}).get("language"),
        # Readings of this file that a later reading displaced, kept beside the archive because
        # they were somebody's. Written from the day the folder existed, and shown nowhere until
        # now: a person who changed the model, had the archive read again and finds the new reading
        # worse was not told that the old one was still there. This says how many and when, and
        # where the file is; it does not draw the old values beside the new ones, which would put
        # two readings of one page on one screen with nothing to say which is which.
        "earlier_readings": _earlier_readings_here(output, file_sha256, on_pages),
    }


def _earlier_readings_here(output: Path, file_sha256: str, on_pages: tuple) -> dict:
    """How many earlier readings of these pages are kept, when the last one was, and by whom.

    By pages that overlap, not by a list that matches. A regrouping is the commonest reason anything
    is in replaced/ at all — extract/run.py says so where it puts it there: a new reading of pages
    1-2 takes out every document whose pages it touches. In exactly that case the pages of the old
    document and of the new one differ by definition, so the one card that mentions this folder said
    nothing about it, with the file sitting right there; and no other page, command or line of the
    README names the folder, so a silent card leaves nowhere at all to learn of it.
    """
    kept, regrouped = [], []
    for item in earlier_readings(output, file_sha256):
        pages = tuple((item.get("document") or {}).get("pages") or ())
        if not set(pages) & set(on_pages):
            continue
        kept.append(item)
        if pages != tuple(on_pages):
            regrouped.append(pages)
    if not kept:
        return {}
    newest = kept[0]
    return {
        "count": len(kept),
        "when": (newest.get("replaced_at") or "")[:10],
        "by": ((newest.get("by") or {}).get("model") or ""),
        # Where the file is, in the words the rest of this program uses for the same place: inside
        # the data folder of this instance. The card used to say "inside this archive's folder",
        # which in the language of this program is the folder of scans — the one the status page
        # calls "Source (read only). Nothing is copied, moved or renamed." A person sent there finds
        # nothing, because nothing of this program's is ever written there.
        "file": f"sources/{output.name}/{layout.REPLACED}/{file_sha256}.jsonl",
        # And that one of them read these pages as part of a differently grouped document, which is
        # what usually put it in that folder.
        "regrouped": [_page_label(pages) for pages in regrouped],
    }


def _page_label(pages: tuple) -> str:
    return str(pages[0]) if len(pages) == 1 else f"{pages[0]}\u2013{pages[-1]}"


def _document_row(pages: list[dict]) -> dict:
    first = pages[0]
    numbers = [page["page"] for page in pages]
    return {
        # The machine name, which is what every other reader of this row compares against; the
        # pages print it through the `in_words` filter. It was the words that were stored here,
        # and two steps then tested a document for being a blank page by comparing it with the
        # string "Blank page" -- so rewording a tab would have quietly sent every blank page of
        # the archive to the model that looks for a printed date.
        "doc_type": first["doc_type"],
        "pages": numbers,
        "page_label": str(numbers[0]) if len(numbers) == 1 else f"{numbers[0]}–{numbers[-1]}",
        "date": next((page["date_on_page"] for page in pages if page.get("date_on_page")), None),
        "provider": next((page["provider_on_page"] for page in pages if page.get("provider_on_page")), None),
        "language": language_name(first.get("language")),
        "language_code": first.get("language"),
        "confidence": min(page["confidence"] for page in pages),
        "goes_to_extract": goes_to_extract(first),
        "illegible": any(not page.get("legible", True) for page in pages),
    }


def nothing_read_yet(output: Path) -> bool:
    """Whether anything at all has been read out of this archive's folder.

    Its own answer, apart from "no page of this archive is at that address", because the two are
    different sentences and were before the page of one scan moved here: an archive whose folder
    has not been walked yet is answered as the archive having been switched, which is what it is
    from the reader's side, and a file or a page the walk does not hold is answered as the
    address. The route picks between the two; which case it is, is decided here.
    """
    return not (output / layout.INVENTORY).exists()


def the_scan_at(source: Source, output: Path, sha256: str, page: int):
    """The one page of the one file this address names, or nothing where the reading holds none.

    Which archive comes in as a `Source` with no default of its own, as every door into an
    archive does, and here it has already been through the one in `web/app.py`: a scan is
    content, and an address under another archive answers as though it does not exist.
    """
    inventory = output / layout.INVENTORY
    if not inventory.exists():
        return None
    record = next((one for one in read_records(inventory) if one.get("sha256") == sha256), None)
    return next((ref for ref in (page_refs(record) if record else []) if ref.page == page), None)


def record_path(source: Source, output: Path, sha256: str) -> str:
    """The name of the file a page came from. The folder it sits in is not shown anywhere."""
    record = next((one for one in read_records(output / layout.INVENTORY)
                   if one.get("sha256") == sha256), None)  # fmt: skip
    return (record or {}).get("path", "")


def one_scanned_page(source: Source, output: Path, sha256: str, page: int) -> dict | None:
    """The scan of one page, with enough around it to know what one is looking at.

    This was the image alone, opened in a tab of its own: no page number, no name of the file
    it came from, no way to the next page of the same form and no way back. Checking a
    four-page form against its card meant four tabs and no captions. The image itself is
    still one address of its own, which is what this page draws.

    Which archive comes in as a `Source` with no default of its own, as every door into an
    archive does, and here it has already been through the one in `web/app.py`.
    """
    inventory = output / layout.INVENTORY
    if not inventory.exists():
        return None
    record = next((one for one in read_records(inventory) if one.get("sha256") == sha256), None)
    refs = page_refs(record) if record else []
    ref = next((one for one in refs if one.page == page), None)
    if ref is None:
        return None
    numbers = sorted(one.page for one in refs)
    at = numbers.index(page)
    # Which document this page belongs to, so there is a way back to the card it was opened
    # from. A page can belong to none, in a file whose pages were never grouped.
    view = source_documents(source, output)
    belongs = next((row for group in (view or {}).get("years", []) for row in group["documents"]
                    if row["file"]["sha256"] == sha256 and page in row["pages"]), None)  # fmt: skip
    return {
        "current": "documents", "source_id": source.id, "sha256": sha256, "page": page,
        "path": Path(record_path(source, output, sha256) or "").name,
        "pages": numbers,
        "previous": numbers[at - 1] if at else None,
        "next": numbers[at + 1] if at + 1 < len(numbers) else None,
        "document": belongs,
        # Why this scan cannot be shown, where it cannot, in words on the page. It used to ask
        # one question — is the folder there — and say a sentence for that and nothing at all
        # for the likelier trouble: one file changed under the archive, rescanned or resaved or
        # damaged, where the page stayed whole with a broken image in the middle of it. Over the
        # one promise this program makes about every value it shows: that the page it was read
        # from is one click away.
        **_what_this_page_shows(ref, source),
    }  # fmt: skip


def _what_this_page_shows(ref, source: Source) -> dict:
    """The scan, or the text where the page is text, or why neither can be shown.

    A text file, a sheet of a workbook, the text of a Word document: there is no picture of
    such a page anywhere, and this page drew an <img> at an address that answered 409 — a
    broken image in the middle of the one page this program promises is always one click away
    from a value. What there is instead is the text the values were read from.
    """
    cannot = cannot_be_read(ref, Path(source.path))
    if cannot or not has_no_image(ref):
        return {"cannot_be_shown": cannot, "as_text": None}
    try:
        return {"cannot_be_shown": "", "as_text": original_text(ref, Path(source.path))}
    except PageUnreadable as why:
        return {"cannot_be_shown": str(why), "as_text": None}
