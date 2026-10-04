"""Numbers-only summary of classify results. No dates, providers or other page content."""

from collections import Counter
from pathlib import Path

from epicrisis.records import read_records

NOT_FOR_EXTRACT = {"admin", "insurance", "id_document", "blank"}
CONFIDENCE_BUCKETS = [(0.0, 0.5, "<0.5"), (0.5, 0.7, "0.5-0.7"), (0.7, 0.9, "0.7-0.9"), (0.9, 1.01, ">=0.9")]


def latest_pages(path: Path) -> list[dict]:
    """The most recent result per page; re-classified pages override older lines."""
    if not path.exists():
        return []
    pages = {}
    for line in read_records(path):
        pages[(line["file_sha256"], line["page"])] = line
    return [pages[key] for key in sorted(pages)]


def document_keys(output: Path) -> set[tuple]:
    """Which documents this archive holds now, as (file, pages) — the key everything hangs on.

    A date put in by hand, the choice of which copy answers, and a person's verdict on a finding are
    all kept against the pages the classification grouped. A page read again can be grouped
    differently, and then such a key matches nothing. Each of the three needs the same answer to
    "does that document still exist", and it was written out twice and missing for the third.
    """
    from epicrisis import layout

    return {
        (group[0]["file_sha256"], tuple(page["page"] for page in group))
        for group in group_documents(latest_pages(Path(output) / layout.CLASSIFY))
    }  # fmt: skip


def group_documents(pages: list[dict]) -> list[list[dict]]:
    """Consecutive pages of a file form a document; "first" starts a new one. No model involved.

    In a text file there are no page breaks: this program cut the text into pages itself, so a
    document ends somewhere in the middle of one and the next begins there. Asked of such a page
    on its own — the only way a page is ever asked — "is this the first page of a document" has
    no good answer, and the answer given is "continuation". On the first text archive read here
    that put fifteen consecutive pages into one document spanning five years, each of those pages
    carrying its own date and its own kind, named with a confidence of 0.95.

    So for the pages of a text file the date decides as well: a page dated otherwise than the page
    before it begins a document. The date is the one the reader gave for the page's own document,
    and nothing else about the grouping changes — least of all for a scan or a PDF, where a page
    break is a real one and a date printed again on page two is the same form, not a new one.
    """
    documents: list[list[dict]] = []
    previous_file = None
    previous_date = None
    previous_document = None
    for page in sorted(pages, key=lambda page: (page["file_sha256"], page["page"])):
        if "error" in page:
            continue
        if page["file_sha256"] != previous_file:
            previous_date = previous_document = None
        date = page.get("date_on_page")
        # Where the documents of a file were marked out before it was cut into pages, the marks
        # decide and nothing else is asked: no page_role, no date. That is a text file whose
        # boundaries were read; see epicrisis/boundaries.py.
        marked = page.get("of_document")
        # A page with no date of its own carries on with the last one seen: it is the middle of
        # something, which is exactly where a text file gives no date.
        cut_in_the_text = (marked is None and page.get("part") == "text" and date is not None
                           and previous_date is not None and date != previous_date)  # fmt: skip
        begins = marked != previous_document if marked is not None else page.get("page_role") == "first"
        if page["file_sha256"] != previous_file or begins or cut_in_the_text:
            documents.append([])
        documents[-1].append(page)
        previous_file = page["file_sha256"]
        previous_date = date if date is not None else previous_date
        previous_document = marked
    return documents


def goes_to_extract(page: dict) -> bool:
    return "error" not in page and page.get("legible", True) and page.get("doc_type") not in NOT_FOR_EXTRACT


def render_summary(pages: list[dict], total_pages: int) -> str:
    classified = [page for page in pages if "error" not in page]
    documents = group_documents(pages)
    documents_per_file = Counter(document[0]["file_sha256"] for document in documents)
    confidence = Counter(
        next(label for low, high, label in CONFIDENCE_BUCKETS if low <= page["confidence"] < high) for page in classified
    )

    lines = [
        f"Pages classified: {len(classified)} of {total_pages}, unreadable: {len(pages) - len(classified)}",
        "By route: " + ", ".join(f"{route} {count}" for route, count in sorted(Counter(p["route"] for p in classified).items())),
        "By document type:",
    ]
    lines += [f"  {doc_type:<16} {count:>5}" for doc_type, count in Counter(p["doc_type"] for p in classified).most_common()]
    lines.append("By language: " + ", ".join(f"{language} {count}" for language, count in Counter(p["language"] for p in classified).most_common()))
    lines.append(f"Illegible pages: {sum(1 for p in classified if not p['legible'])}")
    lines.append(f"Pages going to extract: {sum(1 for p in classified if goes_to_extract(p))}, filtered out: {sum(1 for p in classified if not goes_to_extract(p))}")
    lines.append(f"Documents: {len(documents)}, files split into 2+ documents: {sum(1 for count in documents_per_file.values() if count > 1)}")
    lines.append(f"Pages with tabular results: {sum(1 for p in classified if p['has_tabular_results'])}")
    lines.append(f"Pages without a printed date: {sum(1 for p in classified if not p['date_on_page'])}")
    lines.append("Confidence: " + ", ".join(f"{label} {confidence[label]}" for _, _, label in CONFIDENCE_BUCKETS))
    return "\n".join(lines)
