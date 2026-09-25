"""Dates as printed on documents, read into calendar dates for sorting and grouping.

The printed text is always kept next to the result. Numeric dates are read day first, as in
every language of the archive; when day and month could be swapped and the document is in
English, the date is marked ambiguous rather than guessed silently. Nothing here looks at the
file name or folder.
"""

import re
from dataclasses import dataclass
from datetime import date

# Month names by stem: genitive and nominative forms in ru, uk, en, es, el share these starts.
MONTH_STEMS = {
    1: ("январ", "янв", "січ", "january", "jan", "enero", "ene", "ιαν"),
    2: ("феврал", "фев", "лют", "february", "feb", "febrero", "φεβ", "φλεβ"),
    3: ("март", "мар", "берез", "march", "mar", "marzo", "μαρ", "μάρ"),
    4: ("апрел", "апр", "квіт", "april", "apr", "abril", "abr", "απρ", "απρ"),
    5: ("мая", "май", "трав", "may", "mayo", "μαΐ", "μαι", "μάι"),
    6: ("июн", "черв", "june", "jun", "junio", "ιουν", "ιούν"),
    7: ("июл", "лип", "july", "jul", "julio", "ιουλ", "ιούλ"),
    8: ("август", "авг", "серп", "august", "aug", "agosto", "ago", "αυγ", "αύγ"),
    9: ("сентябр", "сен", "верес", "september", "sep", "septiembre", "sept", "set", "σεπ"),
    10: ("октябр", "окт", "жовт", "october", "oct", "octubre", "οκτ"),
    11: ("ноябр", "ноя", "листоп", "november", "nov", "noviembre", "νοε", "νοέ"),
    12: ("декабр", "дек", "груд", "december", "dec", "diciembre", "dic", "δεκ"),
}
_STEMS = sorted(((stem, month) for month, stems in MONTH_STEMS.items() for stem in stems), key=lambda item: -len(item[0]))
_WORD = r"[^\W\d_]+\.?"

# A lookahead, so a time printed right before the date cannot swallow its first number — and the
# two separators have to match, for the same reason. "08:30 12.05.2020" read with a free-for-all
# separator begins at "30 12.05" and files the form under 30 December 2005; so does a page
# number printed in front of the date. A date written with spaces is allowed, but then it is
# spaces throughout and the year is written in full.
NUMERIC = re.compile(
    r"(?=(?<![\d:])(\d{1,2})\s*([./\-])\s*(\d{1,2})\s*\2\s*(\d{4}|\d{2})(?![\d:]))"
    r"|(?=(?<![\d:])(\d{1,2})\s+(\d{1,2})\s+(\d{4})(?![\d:]))"
)
ROMAN_MONTHS = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10, "xi": 11, "xii": 12}
# Old forms print the month in Roman numerals, sometimes typed with Cyrillic І, Х and У for V.
ROMAN = re.compile(r"(?<!\d)(\d{1,2})\s*[./\-\s]\s*([ivx]{1,4})\s*[./\-\s]\s*(\d{4}|\d{2})(?!\d)")
# The year first, with any of the separators a form may print it with.
ISO = re.compile(r"(?<!\d)(\d{4})\s*([.\-/])\s*(\d{1,2})\s*\2\s*(\d{1,2})(?!\d)")
DAY_MONTH_WORD = re.compile(r"(?<!\d)(\d{1,2})\s*\.?\s*(?:de\s+)?(" + _WORD + r")\s*,?\s*(?:de\s+)?(\d{4}|\d{2})(?!\d)")
MONTH_WORD_DAY = re.compile(r"(" + _WORD + r")\s+(\d{1,2})\s*,?\s+(\d{4})(?!\d)")
MONTH_WORD_YEAR = re.compile(r"(" + _WORD + r")\s*[/\s]\s*(\d{4}|\d{2})(?!\d)")
MONTH_YEAR = re.compile(r"(?<!\d)(\d{1,2})\s*[./]\s*(\d{4}|\d{2})(?!\d)")
YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")


@dataclass(frozen=True)
class PrintedDate:
    printed: str | None
    value: date | None = None
    precision: str | None = None  # "day", "month" or "year"
    ambiguous: bool = False

    @property
    def year(self) -> int | None:
        return self.value.year if self.value else None


def read_printed_date(printed: str | None, language: str | None = None, today: date | None = None) -> PrintedDate:
    """The first date in the printed text; a range such as "from ... to ..." gives its start."""
    if not printed or not printed.strip():
        return PrintedDate(printed)
    today = today or date.today()
    text = re.sub(r"[«»\"„“”']", " ", printed.casefold())
    latin_digits = text.replace("і", "i").replace("х", "x").replace("у", "v")

    candidates = []
    for match in ISO.finditer(text):
        candidates.append((match.start(), _day(int(match.group(1)), int(match.group(3)), int(match.group(4)))))
    for match in NUMERIC.finditer(text):
        # Either the punctuated shape or the spaced one matched; the groups are the same three.
        numbers = match.group(1, 3, 4) if match.group(1) else match.group(5, 6, 7)
        first, second, year = int(numbers[0]), int(numbers[1]), _full_year(numbers[2], today)
        if first <= 12 and second > 12:  # month first, the only reading possible
            candidates.append((match.start(), _day(year, first, second)))
            continue
        ambiguous = first <= 12 and second <= 12 and first != second and language == "en"
        candidates.append((match.start(), _day(year, second, first, ambiguous)))
    for match in ROMAN.finditer(latin_digits):
        if match.group(2) in ROMAN_MONTHS:
            year = _full_year(match.group(3), today)
            candidates.append((match.start(), _day(year, ROMAN_MONTHS[match.group(2)], int(match.group(1)))))
    for match in DAY_MONTH_WORD.finditer(text):
        month = _month(match.group(2))
        if month:
            candidates.append((match.start(), _day(_full_year(match.group(3), today), month, int(match.group(1)))))
    for match in MONTH_WORD_DAY.finditer(text):
        month = _month(match.group(1))
        if month:
            candidates.append((match.start(), _day(int(match.group(3)), month, int(match.group(2)))))
    found = [(start, parsed) for start, parsed in candidates if parsed]
    if found:
        return PrintedDate(printed, *min(found, key=lambda item: item[0])[1])

    for match in MONTH_WORD_YEAR.finditer(text):
        month = _month(match.group(1))
        if month:
            return PrintedDate(printed, date(_full_year(match.group(2), today), month, 1), "month")
    for match in MONTH_YEAR.finditer(text):
        month, year_text = int(match.group(1)), match.group(2)
        # "08.89" is a month and year only when the second number cannot be a month.
        if 1 <= month <= 12 and (len(year_text) == 4 or int(year_text) > 12):
            return PrintedDate(printed, date(_full_year(year_text, today), month, 1), "month")
    year = YEAR.search(text)
    if year:
        return PrintedDate(printed, date(int(year.group(1)), 1, 1), "year")
    return PrintedDate(printed)


def _day(year: int, month: int, day: int, ambiguous: bool = False) -> tuple | None:
    try:
        return date(year, month, day), "day", ambiguous
    except ValueError:
        return None


def _month(word: str) -> int | None:
    word = word.rstrip(".")
    if len(word) < 3:
        return None
    return next((month for stem, month in _STEMS if word.startswith(stem)), None)


def _full_year(text: str, today: date) -> int:
    if len(text) == 4:
        return int(text)
    short = int(text)
    return 2000 + short if short <= today.year % 100 else 1900 + short


# Labels printed before a date of birth. Such a date is never the date of a document.
BIRTH_LABEL = re.compile(
    r"(дата\s+рожд\w*|год\s+рожд\w*|дата\s+народж\w*|рік\s+народж\w*|fecha\s+de\s+nacimiento|date\s+of\s+birth|"
    r"birth\s*date|d\.\s*o\.\s*b\.?|\bdob\b|ημερομηνία\s+γέννησης|ημ\.?\s*γέννησης|έτος\s+γέννησης)[^\d\n]{0,40}"
)


def birth_dates(text: str | None, language: str | None = None, today: date | None = None) -> list[PrintedDate]:
    """Dates printed right after a date-of-birth label."""
    found = []
    # Searched in the lower-cased text and read from the same text, not from the original: a
    # casefold can change a string's length (ß becomes ss), and every offset after it would then
    # point a letter or two off — at the tail of the date rather than at the date.
    lowered = (text or "").casefold()
    for match in BIRTH_LABEL.finditer(lowered):
        parsed = read_printed_date(lowered[match.end() : match.end() + 30], language, today)
        if parsed.value:
            found.append(parsed)
    return found


def same_date(one: PrintedDate, other: PrintedDate) -> bool:
    if not one.value or not other.value:
        return False
    if "year" in (one.precision, other.precision):
        return one.value.year == other.value.year
    return one.value == other.value
