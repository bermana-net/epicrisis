"""Documents view: what classify found in each file, as printed, with links to the original pages.

It lists and shows. It never rates, flags or summarises anything about health.
"""

from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from epicrisis import layout
from epicrisis.classify.pages import page_refs
from epicrisis.classify.report import goes_to_extract, group_documents, latest_pages
from epicrisis.classify.run import is_running
from epicrisis.corrections import load_corrections, load_value_corrections, value_key
from epicrisis.datesearch import load_search_results
from epicrisis.document_dates import document_date, provider_key, source_day_first
from epicrisis.extract.run import load_extracted
from epicrisis.indicators import approved_names
from epicrisis.printed_values import fold
from epicrisis.records import read_records
from epicrisis.validate import ASKS, CHECKS, PRIORITY, load_validation, validation_state
from epicrisis.sources import Source
from epicrisis.values import is_result

DOC_TYPE_LABELS = {
    "lab_panel": "Lab results",
    "imaging_report": "Imaging report",
    "consultation": "Consultation",
    "discharge": "Discharge summary",
    "prescription": "Prescription",
    "referral": "Referral",
    "admin": "Administrative",
    "insurance": "Insurance, billing",
    "id_document": "ID document",
    "blank": "Blank page",
    "other": "Other",
}


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


def _corrected(document: dict, output: Path, file_sha256: str, pages: list[int], data_dir: Path | None = None) -> list[dict]:
    """The document's values as they stand after a person's corrections, each marked.

    A value whose printed name belongs to an indicator also carries it, so a line on the card can
    lead to that test's whole history without the card having to know the index.
    """
    corrections = load_value_corrections(output)
    known = approved_names(data_dir) if data_dir else {}
    shown = []
    for observation in document["observations"]:
        key = value_key(observation["provenance"]["page"], observation["name_as_printed"], observation["value_as_printed"])
        correction = corrections.get((file_sha256, tuple(pages), key))
        item = {**observation, "key": key, "correction": None,
                "indicator_id": known.get(fold(observation["name_as_printed"]))}  # fmt: skip
        if correction and correction.get("removed"):
            item["correction"] = {"removed": True}
        elif correction:
            item = {**item, **correction["changes"], "correction": {"changes": correction["changes"], "printed": {field: observation.get(field) for field in correction["changes"]}}}
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


# (kind, folder) -> (when its inputs last changed, view). By folder, not by archive id: two data
# folders on one machine can hold the same id, and one would then answer for the other.
_VIEWS: dict[tuple, tuple[float, dict]] = {}


def _last_change(output: Path) -> float:
    """When anything this view is built from last changed, so a built view can be kept."""
    inputs = (layout.INVENTORY, layout.CLASSIFY, layout.CORRECTIONS, layout.DATE_SEARCH,
              layout.VALIDATION, layout.EXTRACTED)  # fmt: skip
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
                layout.EXTRACTED: False, "file": file, "date": {"value": None, "year": None, "label": None, "printed": None, "flags": [], "by_hand": False},
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


def review_view(source: Source, output: Path) -> dict | None:
    """Findings of the last validation, by check in the order to work through them."""
    from epicrisis.corrections import unmatched_values

    kept = _kept("review", source, output)
    if kept is not None:
        return kept
    result = load_validation(output)
    view = source_documents(source, output)
    if result is None or view is None:
        return {"id": source.id, "name": source.name, "validated_at": None, "checks": [], "documents_checked": 0} if view else None
    rows = {(row["file"]["sha256"], tuple(row["pages"])): row for group in view["years"] for row in group["documents"]}
    checks = []
    for code in PRIORITY:
        entries = []
        for finding in result["documents"]:
            row = rows.get((finding["file_sha256"], tuple(finding["pages"])))
            if code in finding["findings"] and row:
                copies = [rows[key] for key in ((copy["file_sha256"], tuple(copy["pages"])) for copy in finding["copies"]) if key in rows]
                entries.append({"row": row, "count": finding["findings"][code], "copies": copies if code == "possible_copy" else []})
        if entries:
            entries.sort(key=lambda entry: (entry["row"]["date"]["value"] or date.min), reverse=True)
            checks.append({"code": code, "kind": CHECKS[code][0], "label": CHECKS[code][1],
                           "ask": ASKS.get(code, ""), "entries": entries})  # fmt: skip
    lost = [
        {**item, "row": rows.get((item["file_sha256"], tuple(item["pages"])))} for item in unmatched_values(output)
    ]  # fmt: skip
    return _keep("review", source, output, {
        "lost_corrections": lost,
        "id": source.id,
        "name": source.name,
        "whose": source.whose,
        "validated_at": result["validated_at"],
        "documents_checked": result["documents_checked"],
        "documents_with_findings": len(result["documents"]),
        "outdated": validation_state(output)["state"] == "partial",
        "checks": checks,
    })


def document_findings(output: Path, file_sha256: str, pages: list[int]) -> list[dict]:
    result = load_validation(output)
    finding = next((item for item in (result or {"documents": []})["documents"] if item["file_sha256"] == file_sha256 and item["pages"] == pages), None)
    if finding is None:
        return []
    return [
        {"label": CHECKS[code][1], "count": finding["findings"][code], "copies": finding["copies"] if code == "possible_copy" else []}
        for code in PRIORITY
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
        "observation_tables": observation_tables(_corrected(document, output, file_sha256, [page["page"] for page in classified], output.parent.parent)) if document else [],
        "findings": document_findings(output, file_sha256, [page["page"] for page in classified]),
        "language": language_name(document["language"]) if document else None,
    }


def _document_row(pages: list[dict]) -> dict:
    first = pages[0]
    numbers = [page["page"] for page in pages]
    return {
        "doc_type": DOC_TYPE_LABELS.get(first["doc_type"], first["doc_type"]),
        "pages": numbers,
        "page_label": str(numbers[0]) if len(numbers) == 1 else f"{numbers[0]}–{numbers[-1]}",
        "date": next((page["date_on_page"] for page in pages if page.get("date_on_page")), None),
        "provider": next((page["provider_on_page"] for page in pages if page.get("provider_on_page")), None),
        "language": language_name(first.get("language")),
        "confidence": min(page["confidence"] for page in pages),
        "goes_to_extract": goes_to_extract(first),
        "illegible": any(not page.get("legible", True) for page in pages),
    }
