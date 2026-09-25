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


def group_documents(pages: list[dict]) -> list[list[dict]]:
    """Consecutive pages of a file form a document; "first" starts a new one. No model involved."""
    documents: list[list[dict]] = []
    previous_file = None
    for page in sorted(pages, key=lambda page: (page["file_sha256"], page["page"])):
        if "error" in page:
            continue
        if page["file_sha256"] != previous_file or page.get("page_role") == "first":
            documents.append([])
        documents[-1].append(page)
        previous_file = page["file_sha256"]
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
