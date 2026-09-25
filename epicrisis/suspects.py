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

from epicrisis.rules.subjects import Archive, Found
from epicrisis.values import only_results

# How much each signal says, how many readings it takes before a test has habits, and how far a
# number has to be before it looks like a misplaced decimal point, are all settings of the rules
# now: see epicrisis/rules/shipped/. What stays here is the one decision about combining them.
CAP = 3  # times one signal can count in one document


@dataclass
class Suspect:
    file_id: str
    first_page: int
    date: str | None
    codes: Counter = field(default_factory=Counter)
    lines: list[str] = field(default_factory=list)
    weights: dict = field(default_factory=dict)  # what each rule that found this one says it weighs

    @property
    def weight(self) -> int:
        return sum(self.weights.get(code, 1) * min(times, CAP) for code, times in self.codes.items())


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


def unit_missing_where_others_have_one(archive, settings: dict) -> list[Found]:
    """A value with no unit, on a test whose other forms print one."""
    found = []
    for row in archive.rows:
        counts = archive.habits.get(row["indicator_id"] or "", Counter())
        if not (row["unit"] or "").strip() and row["number"] is not None and sum(counts.values()) >= settings["least_history"]:
            found.append(Found(row["file_sha256"], row["first_page"], row.get("date"),
                               f'{row["name"]}: {row["value"]} with no unit (others print {counts.most_common(1)[0][0]})'))  # fmt: skip
    return found


def number_far_from_the_others(archive, settings: dict) -> list[Found]:
    """A number many times away from the middle of the same test, in the same unit and specimen."""
    found = []
    for row in archive.rows:
        series = archive.numbers.get(_series_key(row), [])
        if not row["number"] or len(series) < settings["least_history"]:
            continue
        middle = median(series)
        if middle > 0 and (row["number"] / middle >= settings["times_away"] or middle / row["number"] >= settings["times_away"]):
            found.append(Found(row["file_sha256"], row["first_page"], row.get("date"),
                               f'{row["name"]}: {row["value"]} {(row["unit"] or "").strip()} (others around {middle:g})'))  # fmt: skip
    return found


def institution_looks_like_a_name(archive, settings: dict) -> list[Found]:
    """The doctor under the stamp read as the laboratory."""
    return [
        Found(document["file_sha256"], document["first_page"], document.get("date"),
              f'institution as printed: {document["provider"]}')  # fmt: skip
        for document in archive.documents
        if provider_looks_like_a_person(document["provider"])
    ]


def lab_form_without_a_title(archive, settings: dict) -> list[Found]:
    return [
        Found(document["file_sha256"], document["first_page"], document.get("date"),
              "no title read on a laboratory form")  # fmt: skip
        for document in archive.documents
        if document["doc_type"] == "lab_panel" and not document["title"] and document["transcribed"]
    ]


def find(rows: list[dict], documents: list[dict], found_by) -> list[Suspect]:
    """Rows are values with their indicator, unit, number and document; documents carry the header.

    The rules are handed in, already chosen, the way the charts are handed theirs: this module
    gathers what they find into one document at a time and weighs it. Which rules exist, and
    which of them this archive runs, is not its business.
    """
    archive = Archive(rows=rows, documents=documents,
                      habits=unit_habits(rows), numbers=numbers_by_indicator(rows))  # fmt: skip
    suspects: dict[tuple, Suspect] = {}
    weights: dict[str, int] = {}
    for rule in found_by:
        weights[rule.id] = rule.settings.get("weight", 1)
        for item in rule.check.run(archive, rule.settings):
            key = (item.file_sha256, item.first_page)
            suspect = suspects.setdefault(key, Suspect(item.file_sha256[:8], item.first_page, item.date))
            suspect.codes[rule.id] += 1
            suspect.lines.append(item.line)
            suspect.weights = weights
    return sorted(suspects.values(), key=lambda item: (-item.weight, item.file_id))


def rows_from_index(connection) -> tuple[list[dict], list[dict]]:
    values = [
        dict(row)
        for row in connection.execute(
            f"""SELECT o.name, o.value, o.unit, o.value_numeric AS number, o.indicator_id, o.material, d.file_sha256, d.first_page, d.date
               FROM observations o JOIN documents d ON d.id = o.document_id
               WHERE {only_results()} AND o.derived = 0"""
        )
    ]
    documents = [
        dict(row)
        for row in connection.execute(
            "SELECT file_sha256, first_page, date, doc_type, title, provider, transcribed FROM documents"
        )
    ]
    return values, documents
