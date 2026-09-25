"""Indicators: printed names that mean the same test, grouped under one label.

One lab prints "Креатинін", another "Creatinina", a third "CREATININE". An indicator says these
are one thing, so a history can be asked for once instead of guessing every spelling. The
printed name, unit and reference range are never changed: an indicator is a label on top.

Stored in data/indicators.json and edited on the Indicators page. A group proposed by a model
applies to nothing until a person approves it. Names are kept in their folded form (case,
accents, Ukrainian and Russian letters), so one spelling belongs to one indicator at a time.
"""

import functools
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from epicrisis import records
from epicrisis.printed_values import fold
from epicrisis.runs import one_at_a_time, put_in_place

FILE_NAME = "indicators.json"
STATUSES = ("approved", "proposed", "rejected")


@dataclass
class Indicator:
    id: str
    label: str
    status: str = "proposed"
    names: list[str] = field(default_factory=list)  # printed names, folded, in use
    proposed_names: list[str] = field(default_factory=list)  # spellings waiting for a person
    note: str = ""
    reviewed: bool = True  # False while nobody has looked at what a model put here
    source: str = "person"
    updated_at: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id, "label": self.label, "status": self.status, "names": sorted(self.names),
            "proposed_names": sorted(self.proposed_names), "note": self.note, "reviewed": self.reviewed,
            "source": self.source, "updated_at": self.updated_at,
        }  # fmt: skip


def path(data_dir: Path) -> Path:
    return Path(data_dir) / FILE_NAME


def load(data_dir: Path) -> list[Indicator]:
    try:
        stored = json.loads(path(data_dir).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    return [Indicator(**item) for item in stored.get("indicators", [])]


def while_editing(change):
    """Hold the vocabulary's lock for the whole of a change, not only for the write at the end."""

    @functools.wraps(change)
    def guarded(data_dir: Path, *args, **kwargs):
        with editing(data_dir):
            return change(data_dir, *args, **kwargs)

    return guarded


@contextmanager
def editing(data_dir: Path):
    """The vocabulary is one file for the whole server, and every change to it is read-modify-write.

    Two writers without this — the Indicators page and a command, or two commands — each read the
    file, each change their own copy, and the second rename silently undoes the first.
    """
    with one_at_a_time(Path(data_dir) / "indicators.lock", "Editing the indicators"):
        yield


def save(data_dir: Path, indicators: list[Indicator]) -> None:
    file = path(data_dir)
    temporary = file.with_name(file.name + ".tmp")
    payload = {"version": 1, "indicators": [indicator.as_dict() for indicator in sorted(indicators, key=lambda item: item.label.casefold())]}
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    put_in_place(temporary, file)


def approved_names(data_dir: Path) -> dict[str, str]:
    """Folded printed name to indicator id, for approved indicators only."""
    return {name: indicator.id for indicator in load(data_dir) if indicator.status == "approved" for name in indicator.names}


# Letters of the alphabets this archive is written in, as an address can carry them. A label in
# Cyrillic or Greek used to leave nothing behind after the Latin letters were kept, so every such
# indicator was called "indicator", "indicator-2", "indicator-3" — opaque in a URL, and unmatched
# by every table in this program that is keyed by what a test is.
TRANSLITERATED = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ie", "ж": "zh",
    "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "iu", "я": "ia",
    "α": "a", "β": "b", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i", "θ": "th", "ι": "i",
    "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x", "ο": "o", "π": "p", "ρ": "r", "σ": "s",
    "ς": "s", "τ": "t", "υ": "y", "φ": "f", "χ": "ch", "ψ": "ps", "ω": "o",
}


def slug(label: str, taken: set[str]) -> str:
    latin = "".join(TRANSLITERATED.get(letter, letter) for letter in fold(label))
    base = re.sub(r"[^a-z0-9]+", "-", latin).strip("-")[:40] or "indicator"
    candidate, number = base, 2
    while candidate in taken:
        candidate, number = f"{base}-{number}", number + 1
    return candidate


@while_editing
def upsert(data_dir: Path, indicator_id: str | None, label: str, names: list[str], status: str,
           note: str | None = None, source: str = "person", reviewed: bool = True) -> Indicator:  # fmt: skip
    """Add or change one indicator; a name moves here from any other indicator holding it.

    A note left out keeps the one the indicator already has. It used to be cleared by every
    caller that did not think to pass it, which is how a note nobody wrote survived being
    unwritten: nothing wrote one.
    """
    if status not in STATUSES:
        raise ValueError("unknown status")
    indicators = load(data_dir)
    folded = [fold(name).strip() for name in names if name.strip()]
    folded = list(dict.fromkeys(folded))
    if not label.strip() and not folded:
        raise ValueError("an indicator needs a label or at least one spelling")
    by_id = {indicator.id: indicator for indicator in indicators}
    if indicator_id and indicator_id in by_id:
        indicator = by_id[indicator_id]
        indicator.label, indicator.status, indicator.names = label.strip() or indicator.label, status, folded
        if note is not None:
            indicator.note = note
        indicator.proposed_names = [name for name in indicator.proposed_names if name not in folded]
        indicator.reviewed = reviewed
    else:
        indicator = Indicator(id=slug(label, set(by_id)), label=label.strip() or "Indicator", status=status,
                              names=folded, note=note or "", source=source, reviewed=reviewed)  # fmt: skip
        indicators.append(indicator)
    indicator.updated_at = records.now()
    for other in indicators:
        if other.id != indicator.id:
            other.names = [name for name in other.names if name not in folded]
    save(data_dir, [item for item in indicators if item.names or item.id == indicator.id])
    return indicator


@while_editing
def add_names(data_dir: Path, indicator_id: str, names: list[str], reviewed: bool = False) -> None:
    """Put spellings straight into an indicator; they leave any other indicator holding them."""
    folded = {fold(name) for name in names if name.strip()}
    indicators = load(data_dir)
    for indicator in indicators:
        if indicator.id == indicator_id:
            indicator.names = sorted(set(indicator.names) | folded)
            indicator.proposed_names = [name for name in indicator.proposed_names if name not in folded]
            indicator.reviewed = indicator.reviewed and reviewed
            indicator.updated_at = records.now()
        else:
            indicator.names = [name for name in indicator.names if name not in folded]
    save(data_dir, indicators)


@while_editing
def drop_name(data_dir: Path, indicator_id: str, name: str) -> None:
    """Take one spelling out of an indicator; it goes back to the names with no indicator."""
    folded = fold(name)
    indicators = load(data_dir)
    for indicator in indicators:
        if indicator.id == indicator_id:
            indicator.names = [item for item in indicator.names if item != folded]
            indicator.proposed_names = [item for item in indicator.proposed_names if item != folded]
            indicator.updated_at = records.now()
    save(data_dir, indicators)


@while_editing
def mark_reviewed(data_dir: Path, indicator_id: str) -> None:
    indicators = load(data_dir)
    for indicator in indicators:
        if indicator.id == indicator_id:
            indicator.reviewed, indicator.updated_at = True, records.now()
    save(data_dir, indicators)


@while_editing
def propose_names(data_dir: Path, indicator_id: str, names: list[str]) -> None:
    """Offer spellings for an existing indicator; they count for nothing until approved."""
    indicators = load(data_dir)
    known = {name for indicator in indicators for name in indicator.names + indicator.proposed_names}
    for indicator in indicators:
        if indicator.id == indicator_id:
            indicator.proposed_names = sorted(set(indicator.proposed_names) | {fold(name) for name in names if fold(name) not in known})
            indicator.updated_at = records.now()
    save(data_dir, indicators)


@while_editing
def decide_names(data_dir: Path, indicator_id: str, names: list[str], accept: bool) -> None:
    """Take proposed spellings into the indicator, or drop them."""
    folded = {fold(name) for name in names}
    indicators = load(data_dir)
    for indicator in indicators:
        if indicator.id == indicator_id:
            indicator.proposed_names = [name for name in indicator.proposed_names if name not in folded]
            if accept:
                indicator.names = sorted(set(indicator.names) | folded)
            indicator.updated_at = records.now()
        else:
            if accept:
                indicator.names = [name for name in indicator.names if name not in folded]
    save(data_dir, indicators)


def assigned_names(data_dir: Path) -> dict[str, str]:
    """Every folded name already placed or offered, to an indicator id."""
    return {
        name: indicator.id
        for indicator in load(data_dir)
        for name in indicator.names + indicator.proposed_names
    }


@while_editing
def remove(data_dir: Path, indicator_id: str) -> None:
    save(data_dir, [indicator for indicator in load(data_dir) if indicator.id != indicator_id])


MIN_STEM = 5  # letters of a word that make it worth comparing two names


def stems(name: str) -> set[str]:
    """Word beginnings of a folded name, long enough to mean something."""
    return {word[:MIN_STEM] for word in re.findall(r"[^\W\d_]+", fold(name)) if len(word) >= MIN_STEM}


def coverage(data_dir: Path, printed: list[dict]) -> dict[str, list[dict]]:
    """For every indicator, the names elsewhere in the archive that share a word with it.

    A model groups the names; this looks at the archive itself, so a spelling cannot go missing
    quietly. Spellings in other languages share no word at all, so only the other direction is
    checked. It suggests, it never moves anything.
    """
    indicators = load(data_dir)
    assigned = assigned_names(data_dir)
    by_stem: dict[str, list[dict]] = {}
    for item in printed:
        for stem in stems(item["folded"]):
            by_stem.setdefault(stem, []).append(item)
    report: dict[str, list[dict]] = {}
    for indicator in indicators:
        own = {stem for name in indicator.names for stem in stems(name)}
        here = set(indicator.names) | set(indicator.proposed_names)
        missing = {
            item["folded"]: {**item, "indicator": assigned.get(item["folded"])}
            for stem in own
            for item in by_stem.get(stem, ())
            if item["folded"] not in here
        }
        report[indicator.id] = sorted(missing.values(), key=lambda item: (item["indicator"] is not None, -item["times"]))
    return report


def printed_names(connection, include_derived: bool = False) -> list[dict]:
    """Every printed name of a result in the index, with how often it appears and over which years.

    Copies are left out, as they are wherever a value is counted or drawn: the same blood draw
    filed in three files counted three times here and once on the page of that test, and the two
    numbers stood side by side in the interface disagreeing with each other.
    """
    rows = connection.execute(
        f"""SELECT o.name, count(*) AS times, count(DISTINCT o.unit) AS units, min(d.date) AS first_date, max(d.date) AS last_date,
                   group_concat(DISTINCT o.unit) AS unit_list, o.kind
            FROM observations o JOIN documents d ON d.id = o.document_id
            WHERE o.value_role = 'result' AND d.primary_copy = 1 {"" if include_derived else "AND o.derived = 0"}
            GROUP BY fold(o.name) ORDER BY times DESC, o.name""",
    ).fetchall()
    return [{**dict(row), "folded": fold(row["name"]), "units": [unit for unit in (row["unit_list"] or "").split(",") if unit]} for row in rows]

