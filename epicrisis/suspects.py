"""Lines that look misread, found in the index itself, without a model.

Nothing here judges health. Every check asks one question only: does this line look like the
page was read wrong? A unit nobody else on this indicator uses, a number ten times larger than
every other reading of the same test in the same unit, a laboratory recorded as somebody's
initials, a lab form with no title. These are candidates for a second reading, not findings.

The suspicion is about the transcription. Whether a value is high or low, and what that means,
is never asked and never stored.
"""

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from statistics import median

from epicrisis.printed_values import fold
from epicrisis.rules.subjects import Archive, Found
from epicrisis.units import unit_key
from epicrisis.values import only_results

# How much each signal says, how many readings it takes before a test has habits, and how far a
# number has to be before it looks like a misplaced decimal point, are all settings of the rules
# now: see epicrisis/rules/shipped/. What stays here is the one decision about combining them.
CAP = 3  # times one signal can count in one document


@dataclass
class Suspect:
    # The whole hash, not the eight characters a person reads: a page that shows these has to be
    # able to link to the document, and the address of a document is its full hash. Held short,
    # this was the one thing standing between the command line and a page — every caller had the
    # eight characters a person recognises and nothing a link could be made of.
    file_sha256: str
    first_page: int
    date: str | None
    codes: Counter = field(default_factory=Counter)
    lines: list[str] = field(default_factory=list)
    weights: dict = field(default_factory=dict)  # what each rule that found this one says it weighs

    @property
    def file_id(self) -> str:
        """The eight characters every page and every command of this program names a file by."""
        return self.file_sha256[:8]

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

    **Two callers, and both give the title.** `index/build.institution_and_doctor`, which acts on
    the answer, and the extract step's own check, which decides whether a document is read again by
    a stronger model. The rule of this name was the third and asked without a title, so the program
    held two different answers to one question about a person's name; it now reads what the index
    recorded instead of asking again. Measured before they were brought together: the title adds 0
    findings on the three archives here either way — 15, 4 and 255 documents with it and without —
    so the one that reads the page more fully is the one kept, and it cost nothing.
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
    """The doctor under the stamp read as the laboratory, as the index recorded it.

    It asked the provider column and `provider_looks_like_a_person` itself, and so it could never
    find one: `index/build.institution_and_doctor` moves every such name out of that column and
    into the doctor's before this ever sees it. 0 documents on all three archives here, which read
    on the settings page as "nothing wrong" and meant "looking in the wrong place". The same fact
    was found by the extract step's own check on 274 documents and counted into
    `checks_still_failing` — a line with no name, no explanation and no switch of its own.

    So the question is not asked a second time here. The index writes down the string the form
    printed in the institution's place whenever it read it as a person's, and this reads that:
    one predicate, asked where the decision is taken, and a count beside the switch that is the
    number of documents the decision was taken on.
    """
    return [
        Found(document["file_sha256"], document["first_page"], document.get("date"),
              f'institution as printed: {document["person_printed_as_the_institution"]}'
              + ("" if document["provider"] else " — read here as the doctor of this document"))  # fmt: skip
        for document in archive.documents
        if document.get("person_printed_as_the_institution")
    ]


def lab_form_without_a_title(archive, settings: dict) -> list[Found]:
    return [
        Found(document["file_sha256"], document["first_page"], document.get("date"),
              "no title read on a laboratory form")  # fmt: skip
        for document in archive.documents
        if document["doc_type"] == "lab_panel" and not document["title"] and document["transcribed"]
    ]


def unit_alone_in_a_series(archive, settings: dict) -> list[Found]:
    """One unit standing alone in a test whose other forms all print another.

    Knows nothing about the names of tests, so it does not go stale on the next form: it asks
    only whether this line's unit is the one nobody else on this test uses.
    """
    # By the unit's key and not its spelling: «ммоль/л» and "mmol/L" are one unit written in two
    # alphabets, and counting them apart would mark every Ukrainian form in a Greek archive.
    counted: dict[tuple, Counter] = defaultdict(Counter)
    printed: dict[tuple, str] = {}
    for row in archive.rows:
        key = unit_key(row["unit"])
        counted[(row["indicator_id"] or "", (row.get("material") or "").strip())][key] += 1
        printed.setdefault(key, (row["unit"] or "").strip())
    found = []
    for row in archive.rows:
        units = counted[(row["indicator_id"] or "", (row.get("material") or "").strip())]
        key = unit_key(row["unit"])
        # Only against units somebody actually printed. A test whose other forms printed no unit
        # at all says nothing about this one: that is a form with no unit column, not a stray.
        others = sum(count for other, count in units.items() if other and other != key)
        usual = max((other for other in units if other and other != key), key=lambda other: units[other], default="")
        if row["indicator_id"] and key and units[key] <= settings["alone_at_most"] and others >= settings["others_at_least"]:
            found.append(Found(row["file_sha256"], row["first_page"], row.get("date"),
                               f'{row["name"]}: {row["value"]} in {(row["unit"] or "").strip()}, where the others print {printed.get(usual, usual)}'))  # fmt: skip
    return found


def _spellings_at_least(spellings: dict[str, str], shortest: int):
    """One expression over every spelling long enough to mean something. Compiled once.

    Compiled once and not once per value: a regular expression per spelling per row is a
    thousand times the work and turns a check that should take a second into a minute.
    """
    wanted = sorted((spelling for spelling in spellings if len(spelling) >= shortest), key=len, reverse=True)
    if not wanted:
        return None
    return re.compile(r"(?<![^\W_])(" + "|".join(re.escape(spelling) for spelling in wanted) + r")(?![^\W_])")


def value_names_another_test(archive, settings: dict) -> list[Found]:
    """The text of a value names a different test than the row it stands in.

    A table of targets prints one test's name in the row and another's inside the cell, and the
    grouping into indicators only ever reads the row. Matched on whole words and never on short
    ones: an indicator whose spelling is an ordinary word matches everything otherwise.
    """
    spellings = archive.spellings or {}
    named = _spellings_at_least(spellings, settings["shortest_spelling"])
    if named is None:
        return []
    found = []
    for row in archive.rows:
        text = fold(row.get("value") or "")
        if not row["indicator_id"] or not text:
            continue
        others = {spellings[match] for match in named.findall(text)} - {row["indicator_id"]}
        if others:
            found.append(Found(row["file_sha256"], row["first_page"], row.get("date"),
                               f'{row["name"]}: the value text names another test'))  # fmt: skip
    return found


def find(rows: list[dict], documents: list[dict], spellings: dict, found_by) -> list[Suspect]:
    """Rows are values with their indicator, unit, number and document; documents carry the header.

    The rules are handed in, already chosen, the way the charts are handed theirs: this module
    gathers what they find into one document at a time and weighs it. Which rules exist, and
    which of them this archive runs, is not its business.
    """
    archive = Archive(rows=rows, documents=documents, habits=unit_habits(rows),
                      numbers=numbers_by_indicator(rows), spellings=spellings)  # fmt: skip
    suspects: dict[tuple, Suspect] = {}
    weights: dict[str, int] = {}
    for rule in found_by:
        weights[rule.id] = rule.settings.get("weight", 1)
        for item in rule.check.run(archive, rule.settings):
            key = (item.file_sha256, item.first_page)
            suspect = suspects.setdefault(key, Suspect(item.file_sha256, item.first_page, item.date))
            suspect.codes[rule.id] += 1
            suspect.lines.append(item.line)
            suspect.weights = weights
    return sorted(suspects.values(), key=lambda item: (-item.weight, item.file_id))


def spellings_from_index(connection) -> dict[str, str]:
    """Every approved spelling of every test, folded, and the indicator it belongs to."""
    found: dict[str, str] = {}
    for row in connection.execute("SELECT id, names FROM indicators WHERE status = 'approved'"):
        for name in json.loads(row[1] or "[]"):
            found[fold(name)] = row[0]
    return found


def rows_from_index(connection) -> tuple[list[dict], list[dict], dict[str, str]]:
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
            "SELECT file_sha256, first_page, date, doc_type, title, provider, person_printed_as_the_institution,"
            " transcribed FROM documents"
        )
    ]
    return values, documents, spellings_from_index(connection)
