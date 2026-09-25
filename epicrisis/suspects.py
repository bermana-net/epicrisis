"""Lines that look misread, found in the index itself, without a model.

Nothing here judges health. Every check asks one question only: does this line look like the
page was read wrong? A unit nobody else on this indicator uses, a number ten times larger than
every other reading of the same test in the same unit, a laboratory recorded as somebody's
initials, a lab form with no title. These are candidates for a second reading, not findings.

The suspicion is about the transcription. Whether a value is high or low, and what that means,
is never asked and never stored.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from statistics import median

MIN_HISTORY = 4  # readings of one indicator before its habits mean anything
# How much each signal says. A number far from every other reading of the same test speaks
# loudest; a missing unit is common on old forms, so many of them say little more than a few.
WEIGHT = {
    "number_far_from_the_others": 3,
    "institution_looks_like_a_name": 3,
    "unit_missing_where_others_have_one": 1,
    "lab_form_without_a_title": 1,
}
CAP = 3  # times one signal can count in one document
MAGNITUDE = 10  # times away from the median before a number looks like a misplaced decimal point


@dataclass
class Suspect:
    file_id: str
    first_page: int
    date: str | None
    codes: Counter = field(default_factory=Counter)
    lines: list[str] = field(default_factory=list)

    @property
    def weight(self) -> int:
        return sum(WEIGHT.get(code, 1) * min(times, CAP) for code, times in self.codes.items())


TITLES = ("проф", "профессор", "професор", "доц", "д-р", "др", "dr", "dra", "prof", "лікар", "врач", "уролог", "mudr", "md")
# Words an institution writes about itself. Matched whole, so "клінічний" is not a clinic.
ORGANISATION = (
    "клиника", "клиники", "клініка", "клініки", "klinika", "clinic", "clinica", "clínica", "clinics",
    "lab", "laboratory", "laboratories", "laboratorios", "лаб", "лабораторія", "лаборатория",
    "центр", "центру", "centre", "center", "centro", "hospital", "лікарня", "больница", "поліклініка",
    "поликлиника", "institute", "instituto", "інститут", "институт", "gmbh", "ltd", "s.a.u.", "s.l.",
    "медцентр", "diagnostics", "діагностика", "диагностика", "health", "ооо", "тов", "зао", "дз", "дну", "дус",
    "мл", "мтм", "мтп", "гдкб", "кокл", "нпц",
)


def _has(text: str, words) -> bool:
    """A word of the list standing on its own, not a piece of another one.

    "ЗДРАВООХРАНЕНИЯ" holds "др" and "КЛІНІЧНИЙ" holds "клін"; neither means a doctor or a clinic.
    """
    parts = re.findall(r"[^\W\d_]+", text.casefold())
    # A long word may be glued to the front, as in "полідіагностика"; a short one may not.
    return any(part == word or (len(word) >= 5 and part.endswith(word)) for part in parts for word in words)


def provider_looks_like_a_person(provider: str | None, title: str | None = None) -> bool:
    """A laboratory recorded as "Гриценко С.А." or "проф. Дорошенко Д.Г." is a signature read as the lab.

    Three signs, and each avoids the way institutions really write themselves. A title before the
    name ("проф.", "Dr."). A surname with initials beside it ("Кедров В. П.", "Савчук L. B.").
    Initials alone, comma separated ("TRW, KLN"). A field that names a kind of institution —
    "ТОВ", "клініка", "Ltd" — is never a person, whatever else it holds; and an abbreviation
    a hospital writes on its forms ("МКЛ N7", "ОКЛ N3") is left alone.

    With the title given, one more sign: the institution's own words stand in the title while the
    institution field holds none of them — the two were swapped.
    """
    if not provider:
        return False
    text = provider.strip()
    if _has(text, ORGANISATION):
        return False
    if _has(text, TITLES):
        return True
    if title and _has(title, ORGANISATION):
        return True
    words = text.replace(",", " ").split()
    if len(words) > 4:
        return False
    initials = [word for word in words if _looks_like_initials(word)]
    surnames = [word for word in words if len(word.strip(".")) >= 4 and word[:1].isupper() and not word.strip(".").isupper()]
    if initials and surnames:
        return True
    return len(initials) >= 2 and len(initials) == len(words) and "," in text


def _looks_like_initials(word: str) -> bool:
    """Short and in capitals: "С.А.", "А.", "TRW" — a signature, not a laboratory's name."""
    bare = word.strip(".")
    return bool(bare) and len(bare) <= 4 and bare == bare.upper() and any(letter.isalpha() for letter in bare)


def unit_habits(rows: list[dict]) -> dict[str, Counter]:
    habits: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        if row["indicator_id"] and row["unit"]:
            habits[row["indicator_id"]][row["unit"].strip()] += 1
    return habits


def numbers_by_indicator(rows: list[dict]) -> dict[tuple, list[float]]:
    """What one test usually reads, per unit and per specimen.

    The specimen belongs in the key for the same reason it belongs on a chart: protein in urine
    and protein in serum are printed under one name in one unit and differ by a factor of ten,
    so a median over both makes each of them look far from the others.
    """
    numbers: dict[tuple, list[float]] = defaultdict(list)
    for row in rows:
        if row["indicator_id"] and row["number"] is not None and row["number"] > 0:
            numbers[_series_key(row)].append(row["number"])
    return numbers


def _series_key(row: dict) -> tuple:
    return (row["indicator_id"] or "", (row["unit"] or "").strip(), (row.get("material") or "").strip())


def find(rows: list[dict], documents: list[dict]) -> list[Suspect]:
    """Rows are values with their indicator, unit, number and document; documents carry the header."""
    habits, numbers = unit_habits(rows), numbers_by_indicator(rows)
    suspects: dict[tuple, Suspect] = {}

    def suspect(row) -> Suspect:
        key = (row["file_sha256"], row["first_page"])
        return suspects.setdefault(key, Suspect(row["file_sha256"][:8], row["first_page"], row.get("date")))

    for row in rows:
        unit = (row["unit"] or "").strip()
        counts = habits.get(row["indicator_id"] or "", Counter())
        if not unit and row["number"] is not None and sum(counts.values()) >= MIN_HISTORY:
            item = suspect(row)
            item.codes["unit_missing_where_others_have_one"] += 1
            item.lines.append(f'{row["name"]}: {row["value"]} with no unit (others print {counts.most_common(1)[0][0]})')
        series = numbers.get(_series_key(row), [])
        if row["number"] and len(series) >= MIN_HISTORY:
            middle = median(series)
            if middle > 0 and (row["number"] / middle >= MAGNITUDE or middle / row["number"] >= MAGNITUDE):
                item = suspect(row)
                item.codes["number_far_from_the_others"] += 1
                item.lines.append(f'{row["name"]}: {row["value"]} {unit} (others around {middle:g})')

    for document in documents:
        if provider_looks_like_a_person(document["provider"]):
            key = (document["file_sha256"], document["first_page"])
            item = suspects.setdefault(key, Suspect(document["file_sha256"][:8], document["first_page"], document.get("date")))
            item.codes["institution_looks_like_a_name"] += 1
            item.lines.append(f'institution as printed: {document["provider"]}')
        if document["doc_type"] == "lab_panel" and not document["title"] and document["transcribed"]:
            key = (document["file_sha256"], document["first_page"])
            item = suspects.setdefault(key, Suspect(document["file_sha256"][:8], document["first_page"], document.get("date")))
            item.codes["lab_form_without_a_title"] += 1
            item.lines.append("no title read on a laboratory form")

    return sorted(suspects.values(), key=lambda item: (-item.weight, item.file_id))


def rows_from_index(connection) -> tuple[list[dict], list[dict]]:
    values = [
        dict(row)
        for row in connection.execute(
            """SELECT o.name, o.value, o.unit, o.value_numeric AS number, o.indicator_id, o.material, d.file_sha256, d.first_page, d.date
               FROM observations o JOIN documents d ON d.id = o.document_id
               WHERE o.value_role = 'result' AND o.derived = 0"""
        )
    ]
    documents = [
        dict(row)
        for row in connection.execute(
            "SELECT file_sha256, first_page, date, doc_type, title, provider, transcribed FROM documents"
        )
    ]
    return values, documents
