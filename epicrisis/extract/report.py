"""Numbers-only summary of extracted documents. No names, values or text."""

import json
from collections import Counter
from pathlib import Path


def load_documents(extracted_dir: Path) -> list[tuple[str, dict]]:
    if not extracted_dir.exists():
        return []
    documents = []
    for path in sorted(extracted_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        documents += [(data["file_sha256"], document) for document in data["documents"]]
    return documents


def render_summary(documents: list[tuple[str, dict]], total_documents: int, years: dict[str, int | None]) -> str:
    observations = [item for _, document in documents for item in document["observations"]]
    panel_values = [len(document["observations"]) for _, document in documents if document["doc_type"] == "lab_panel"]
    by_year = Counter(years.get(sha) for sha, _ in documents)
    return "\n".join(
        [
            f"Documents extracted: {len(documents)} of {total_documents}",
            "By document type: " + ", ".join(f"{kind} {n}" for kind, n in Counter(d["doc_type"] for _, d in documents).most_common()),
            f"Values extracted: {len(observations)}",
            "By value kind: " + ", ".join(f"{kind} {n}" for kind, n in Counter(o["value_kind"] for o in observations).most_common()),
            f"Values without unit: {sum(1 for o in observations if not o['unit_as_printed'])}",
            f"Values without reference: {sum(1 for o in observations if not o['reference_as_printed'])}",
            f"Values with a printed flag: {sum(1 for o in observations if o['flag_as_printed'])}",
            f"Values per lab panel: {sum(panel_values) / len(panel_values):.1f}" if panel_values else "Values per lab panel: -",
            f"Sections: {sum(len(d['sections']) for _, d in documents)}",
            f"Unreadable entries: {sum(len(d['unreadable']) for _, d in documents)}",
            f"Full text characters: {sum(len(d['full_text']) for _, d in documents)}",
            f"Documents with printed diagnoses: {sum(1 for _, d in documents if d['diagnoses_as_printed'])}",
            "By folder year: " + ", ".join(f"{year or 'none'} {n}" for year, n in sorted(by_year.items(), key=lambda item: item[0] or 0)),
        ]
    )
