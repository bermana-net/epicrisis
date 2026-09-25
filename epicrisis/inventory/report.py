"""Console summary of an inventory.

The summary prints counts only. File paths can carry personal data, so they are listed
only when explicitly requested.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from epicrisis.inventory.probes import MIN_TEXT_CHARS_PER_PAGE

# Buckets for the visible-characters-per-page histogram, used to tune the text layer threshold.
CHAR_BUCKETS = [(0, 0, "0"), (1, 19, "1-19"), (20, 99, "20-99"), (100, 499, "100-499"), (500, 1999, "500-1999"), (2000, None, "2000+")]


def _char_bucket(chars: int) -> str:
    return next(label for low, high, label in CHAR_BUCKETS if chars >= low and (high is None or chars <= high))


@dataclass
class Summary:
    files: int = 0
    total_bytes: int = 0
    skipped: int = 0
    categories: Counter = field(default_factory=Counter)
    text_layers: Counter = field(default_factory=Counter)
    pdf_pages: int = 0
    pdf_pages_without_text: int = 0
    image_frames: int = 0
    office_images: int = 0
    http_wrapped: int = 0
    vision_pages: int = 0
    chars_histogram: Counter = field(default_factory=Counter)
    years: Counter = field(default_factory=Counter)
    paths_by_hash: defaultdict = field(default_factory=lambda: defaultdict(list))
    damaged: list = field(default_factory=list)
    unsupported: list = field(default_factory=list)

    def add(self, record: dict) -> None:
        if record.get("skipped"):
            self.skipped += 1
            return
        self.files += 1
        self.total_bytes += record["size"]
        self.years[record["folder_year_hint"]] += 1
        kind = record.get("category", "unknown")
        self.categories[kind] += 1

        if "error" in record or kind == "empty":
            self.damaged.append(record["path"])
        if kind == "pdf" and "error" in record:
            self.text_layers["damaged"] += 1

        sha = record.get("sha256")
        first_copy = sha is None or not self.paths_by_hash[sha]
        if sha is not None:
            self.paths_by_hash[sha].append(record["path"])

        if "unsupported" in record:
            self.unsupported.append(record["path"])
            # An unreadable image format still needs a vision pass; assume one page.
            if kind == "image" and first_copy:
                self.vision_pages += 1

        pdf = record.get("pdf")
        if pdf is not None:
            if "pages" not in pdf:
                self.text_layers["encrypted"] += 1
            else:
                self.text_layers[pdf["text_layer"]] += 1
                self.pdf_pages += pdf["pages"]
                without_text = pdf["pages"] - pdf["pages_with_text"]
                self.pdf_pages_without_text += without_text
                if first_copy:
                    self.vision_pages += without_text
                    self.chars_histogram.update(_char_bucket(chars) for chars in pdf["text_chars_per_page"])

        image = record.get("image")
        if image is not None:
            self.image_frames += image["frames"]
            if first_copy:
                self.vision_pages += image["frames"]

        office = record.get("word") or record.get("excel")
        if office is not None:
            # Inventories written before image counting lack the field.
            images = office.get("embedded_images", 0)
            self.office_images += images
            if first_copy:
                self.vision_pages += images

        if "wrapper" in record:
            self.http_wrapped += 1

    @property
    def duplicate_groups(self) -> list[list[str]]:
        return [paths for paths in self.paths_by_hash.values() if len(paths) > 1]

    @property
    def extra_copies(self) -> int:
        return sum(len(paths) - 1 for paths in self.duplicate_groups)


def render(summary: Summary, usd_per_page: float | None = None, details: bool = False) -> str:
    lines = [f"Files: {summary.files} ({_human_size(summary.total_bytes)})"]
    if summary.skipped:
        lines.append(f"Skipped OS metadata files: {summary.skipped}")

    lines.append("By type:")
    for kind, count in summary.categories.most_common():
        lines.append(f"  {kind:<14} {count:>6}")

    layers = summary.text_layers
    lines.append(
        "PDF text layer: "
        + ", ".join(
            f"{name} {layers[name]}" for name in ("full", "partial", "none", "encrypted", "damaged")
        )
    )
    lines.append(
        f"Pages: PDF {summary.pdf_pages} ({summary.pdf_pages_without_text} without text), "
        f"image frames {summary.image_frames}, images inside Office files {summary.office_images}"
    )
    if summary.http_wrapped:
        lines.append(f"Files saved as raw HTTP responses (read past the headers): {summary.http_wrapped}")
    if summary.chars_histogram:
        lines.append(
            f"PDF pages by visible characters (text layer from {MIN_TEXT_CHARS_PER_PAGE}, duplicates counted once):"
        )
        for _, _, label in CHAR_BUCKETS:
            lines.append(f"  {label:<14} {summary.chars_histogram[label]:>6}")

    lines.append("By folder year (hint):")
    for year in sorted(year for year in summary.years if year is not None):
        lines.append(f"  {year:<14} {summary.years[year]:>6}")
    if summary.years[None]:
        lines.append(f"  {'no hint':<14} {summary.years[None]:>6}")

    groups = summary.duplicate_groups
    lines.append(f"Duplicates: {len(groups)} groups, {summary.extra_copies} extra copies")
    lines.append(f"Damaged files: {len(summary.damaged)}")
    lines.append(f"Unsupported formats: {len(summary.unsupported)}")

    lines.append(
        f"Vision pass: {summary.vision_pages} pages "
        "(PDF pages without text + image frames + images inside Office files, duplicates counted once)"
    )
    if usd_per_page is None:
        lines.append("  Cost estimate: pass --usd-per-page to calculate")
    else:
        lines.append(
            f"  Cost estimate: {summary.vision_pages} x ${usd_per_page:g} "
            f"= ${summary.vision_pages * usd_per_page:,.2f}"
        )

    if details:
        for index, paths in enumerate(groups, 1):
            lines.append(f"Duplicate group {index}:")
            lines.extend(f"  {path}" for path in paths)
        if summary.damaged:
            lines.append("Damaged:")
            lines.extend(f"  {path}" for path in summary.damaged)
        if summary.unsupported:
            lines.append("Unsupported:")
            lines.extend(f"  {path}" for path in summary.unsupported)

    return "\n".join(lines)


def _human_size(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
