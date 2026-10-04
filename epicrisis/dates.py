"""Dates as printed on documents, read into calendar dates for sorting and grouping.

The printed text is always kept next to the result. Numeric dates are read day first, as in
every language of the archive; when day and month could be swapped and the document is in
English, the date is marked ambiguous rather than guessed silently. Nothing here looks at the
file name or folder.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import NamedTuple

from epicrisis.printed_values import fold, fold_with_offsets, with_the_one_letter_slips
from datetime import date

# Month names by stem: genitive and nominative forms in ru, uk, en, es, el share these starts.
_MONTH_STEMS = {
    1: ("январ", "янв", "січ", "january", "jan", "enero", "ene", "ιαν"),
    2: ("феврал", "фев", "лют", "february", "feb", "febrero", "φεβ", "φλεβ"),
    3: ("март", "мар", "берез", "march", "mar", "marzo", "μαρ", "μάρ"),
    4: ("апрел", "апр", "квіт", "april", "apr", "abril", "abr", "απρ", "απρ"),
    # μαϊ, with the dialytika and no accent, is how May comes out of capitals: ΜΑΪΟΥ. Greek prints
    # that mark in capitals precisely because ΜΑΙΟΥ would read as the diphthong αι, so a form
    # headed in capitals — as laboratory forms are — carried the one spelling this list did not
    # hold, and every document dated in May lost its day and its month and went to the first of
    # January. May is the only month of the twelve this happens to.
    5: ("мая", "май", "трав", "may", "mayo", "μαΐ", "μαϊ", "μαι", "μάι"),
    6: ("июн", "черв", "june", "jun", "junio", "ιουν", "ιούν"),
    7: ("июл", "лип", "july", "jul", "julio", "ιουλ", "ιούλ"),
    8: ("август", "авг", "серп", "august", "aug", "agosto", "ago", "αυγ", "αύγ"),
    9: ("сентябр", "сен", "верес", "september", "sep", "septiembre", "sept", "set", "σεπ"),
    10: ("октябр", "окт", "жовт", "october", "oct", "octubre", "οκτ"),
    11: ("ноябр", "ноя", "листоп", "november", "nov", "noviembre", "νοε", "νοέ"),
    12: ("декабр", "дек", "груд", "december", "dec", "diciembre", "dic", "δεκ"),
}
# And every stem with one of its letters out of the other alphabet, because that is how a model
# transcribing a Ukrainian form writes two of the twelve month stems: "січ" and "квіт" carry an і,
# and "і" and "i" are the same mark on paper. Read with that і Latin, "15 квiтня 2019" named no
# month at all, so the day and the month were both lost and the document stood on the first of
# January — three and a half months from where it was printed — with the page showing a bare
# "2019" and no flag beside it, because a date read to the year is a date that was read.
# _BIRTH_LABELS below went through the fold with the words "this list was the one left behind";
# this was the next list behind it. What makes these spellings safe to generate rather than
# patch one at a time is that only one letter moves: see
# printed_values.one_letter_in_the_other_alphabet, where the English word "map" says why.
MONTH_STEMS = with_the_one_letter_slips(_MONTH_STEMS)
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
# A hyphen between the day, the month and the year is what a laboratory system prints:
# "10-NOV-2021", "9-ago-2011". Allowed only between the parts, never as the separator a number
# begins with, so "3,89-5,84" is still two numbers and not a date. Without it the day and the
# month were both lost and the document went quietly to the first of January.
_APART = r"[-–/.\s\u00a0]"
DAY_MONTH_WORD = re.compile(r"(?<!\d)(\d{1,2})\s*[º°]?\s*" + _APART + r"?\s*(?:de\s+)?(" + _WORD
                            + r")\s*,?\s*" + _APART + r"?\s*(?:de\s+)?(\d{4}|\d{2})(?!\d)")  # fmt: skip
MONTH_WORD_DAY = re.compile(r"(" + _WORD + r")\s+(\d{1,2})\s*,?\s+(\d{4})(?!\d)")
MONTH_WORD_YEAR = re.compile(r"(" + _WORD + r")\s*(?:" + _APART + r"|\s*de\s+)\s*(\d{4}|\d{2})(?!\d)")
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


def searchable(printed: str) -> tuple[str, str]:
    """The form of a text that a date is looked for in, and the same with Cyrillic І, Х, У Latin.

    Put back together before the words are looked for. casefold turns Greek ΐ into a letter and
    two combining marks, and a pattern of letters stops at the first mark it cannot take — so
    "8 Μαΐου 2019" lost both the day and the month and became the first of January. The same
    month in capitals was said here to read perfectly, and did not: ΜΑΪΟΥ folds to μαϊου, a
    third spelling that was in no list, and it is the spelling a laboratory form actually
    prints. The sentence stood over the code for two versions; the shape now stands in
    tests/printed-shapes.json, where it can be run instead of believed.

    Every replacement is one character for one, so an offset into either string is an offset into
    the other — which is what lets a caller read a match out of one and ask about the other.
    """
    text = unicodedata.normalize("NFC", re.sub(r"[«»\"„“”']", " ", printed.casefold()))
    return text, text.replace("і", "i").replace("х", "x").replace("у", "v")


def _every_match(pattern: re.Pattern[str], text: str, read) -> list[tuple[re.Match[str], date]]:
    """Every date the pattern finds, including the ones a failed match used to hide behind it.

    re.finditer carries on from the end of whatever matched, and these patterns match any word at
    all where a month's name belongs. So in "ТТГ 4.12 від 19 січня 2019" the day-month-year shape
    matched "12 від 19" first, named no month, and took the rest of the sentence with it: the date
    printed in words two characters later was never looked at. The day was lost in every one of
    the five languages — "19 de enero de 2019" went the same way on "12 de 19", and
    "19 Ιανουαρίου 2019" on "12 στις 19" — and what the reader fell back on was the month alone,
    so the value stood on the first of the month instead of the day the form printed.

    A match that names no month now gives up one character instead of the rest of the line.
    """
    at, found = 0, []
    while True:
        match = pattern.search(text, at)
        if not match:
            return found
        when = read(match)
        if when:
            found.append((match, when))
        at = match.end() if when else match.start() + 1


def _roman_month(match: re.Match[str], today: date) -> date | None:
    if match.group(2) not in ROMAN_MONTHS:
        return None
    read = _day(_full_year(match.group(3), today), ROMAN_MONTHS[match.group(2)], int(match.group(1)))
    return read[0] if read else None


def _word_month(match: re.Match[str], places: tuple[int, int, int], today: date) -> date | None:
    month = _month(match.group(places[0]))
    read = _day(_full_year(match.group(places[1]), today), month, int(match.group(places[2]))) if month else None
    return read[0] if read else None


class NamedMonthDate(NamedTuple):
    """A date whose month was printed as a name, and enough of how it was printed to judge it."""

    start: int        #: where it begins in `searchable(printed)[0]`
    printed: str      #: exactly the characters it was read from, out of that same string
    value: date
    precision: str    #: "day" where the day was printed too, else "month"
    roman: bool       #: the month was a Roman numeral rather than a word


def named_month_dates(printed: str, today: date | None = None) -> list[NamedMonthDate]:
    """Every date in a text whose month is printed as a name, in the order they are to be tried.

    The program's one reader of month names: the five languages of these archives, the case each
    of them declines the month into, the abbreviations a laboratory system prints ("10-NOV-2021",
    "9-ago-2011"), and the Roman numerals an old form uses — typed with Cyrillic І and Х as often
    as with Latin ones. quotations.py asks the same question of a value's own line, and two
    readers of month names in two places would part company on the first month either of them
    learnt; this one has already had to learn that ΜΑΪΟΥ folds to a spelling no list held.

    Those that name a day come first and those that name only a month and a year come last,
    because that is the order of the evidence and it is the order both callers want.
    """
    today = today or date.today()
    text, latin_digits = searchable(printed)
    found = []
    for match, when in _every_match(ROMAN, latin_digits, lambda item: _roman_month(item, today)):
        found.append(NamedMonthDate(match.start(), text[match.start():match.end()], when, "day", True))
    for pattern, places in ((DAY_MONTH_WORD, (2, 3, 1)), (MONTH_WORD_DAY, (1, 3, 2))):
        reader = (lambda item, places=places: _word_month(item, places, today))
        for match, when in _every_match(pattern, text, reader):
            found.append(NamedMonthDate(match.start(), match.group(0), when, "day", False))
    for match in MONTH_WORD_YEAR.finditer(text):
        month = _month(match.group(1))
        if month:
            whole = date(_full_year(match.group(2), today), month, 1)
            found.append(NamedMonthDate(match.start(), match.group(0), whole, "month", False))
    return found


def read_printed_date(printed: str | None, language: str | None = None, today: date | None = None) -> PrintedDate:
    """The first date in the printed text; a range such as "from ... to ..." gives its start."""
    if not printed or not printed.strip():
        return PrintedDate(printed)
    today = today or date.today()
    text, _ = searchable(printed)
    named = named_month_dates(printed, today)

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
    candidates += [(item.start, (item.value, "day", False)) for item in named if item.precision == "day"]
    found = [(start, parsed) for start, parsed in candidates if parsed]
    if found:
        return PrintedDate(printed, *min(found, key=lambda item: item[0])[1])

    for item in named:
        if item.precision == "month":
            return PrintedDate(printed, item.value, "month")
    for match in MONTH_YEAR.finditer(text):
        month, year_text = int(match.group(1)), match.group(2)
        # "08.89" is a month and year only when the second number cannot be a month.
        if 1 <= month <= 12 and (len(year_text) == 4 or int(year_text) > 12):
            return PrintedDate(printed, date(_full_year(year_text, today), month, 1), "month")
    year = YEAR.search(text)
    if year:
        return PrintedDate(printed, date(int(year.group(1)), 1, 1), "year")
    return PrintedDate(printed)


#: Which way round a form writes a numeric date, where the numbers themselves say so.
DAY_FIRST, MONTH_FIRST = "day first", "month first"


def day_or_month_first(printed: str | None) -> str | None:
    """Which way round the numeric date printed here can only be read, or None for either way.

    None also where no numeric date is printed at all, and the two are one answer on purpose: a
    text this program does not read as a date says nothing about how a form writes its dates.

    This is about the printed text and not about the date that came out of it, which is why it is
    a function of its own and not a field of PrintedDate. document_dates.py asks it of a
    document: a form that prints 19.05.2020 has said plainly that it puts the day first, and that
    settles the reading of its other dates — and of every date of the same institution.

    Read with NUMERIC, the one pattern read_printed_date reads a numeric date with, and that is
    the whole of the point. document_dates.py wrote the pattern out again, twice in one file,
    with the back-reference that makes the two separators match left out and with no spaced form
    at all, and so answered wrongly in both directions. "19 05 2020" is read here as a date to
    the day, and that copy saw nothing in it, so another date of the same document kept "Day and
    month may be swapped" although the document had said how it writes dates. "19.05-2020" is
    not read here as a date at all — only its year is — and that copy answered day first for it:
    a string this program never read as a date settled the reading of dates it did read, and the
    habit carried from there to every document of the same institution, taking an honest "not
    known" off each of them.
    """
    if not printed:
        return None
    found = NUMERIC.search(searchable(printed)[0])
    if not found:
        return None
    # Either the punctuated shape or the spaced one matched; read_printed_date reads the same two
    # groups in the same two places.
    first, second = (found.group(1, 3) if found.group(1) else found.group(5, 6))
    if int(first) > 12:
        return DAY_FIRST
    if int(second) > 12:
        return MONTH_FIRST
    return None


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
#
# Written here as a person writes them, and compiled through the same fold as the text they are
# looked for in. Matched against a merely lower-cased text they could not work in Greek at all: a
# casefold turns the final ς into σ, so the literal "γέννησης" could never meet itself, and a form
# that prints the label in capitals loses its accents on top of that. The date of birth then passed
# for the date of the document, in silence, on every Greek form. The same answer — fold both sides —
# is what reference.py and index/build.py already do; this list was the one left behind.
_BIRTH_LABELS = (
    r"дата\s+рожд\w*", r"год\s+рожд\w*", r"дата\s+народж\w*", r"рік\s+народж\w*",
    r"fecha\s+de\s+nacimiento", r"date\s+of\s+birth", r"birth\s*date", r"d\.\s*o\.\s*b\.?", r"\bdob\b",
    r"ημερομηνία\s+γέννησης", r"ημ\.?\s*γέννησης", r"έτος\s+γέννησης",
)  # fmt: skip
BIRTH_LABEL = re.compile(fold("(" + "|".join(_BIRTH_LABELS) + r")[^\d\n]{0,40}"))


#: A date whose last digit is the last character before a label: "06/12/1975ΗΜ.ΓΕΝΝΗΣΗΣ:". Two
#: columns of a form, flattened into one line of text, put the value in front of its own label.
#: \Z and not $: in Python $ also matches in front of a trailing newline, and with it the value of
#: the field *above* the label — "ДАТА: Aug 11, 2011\nГод рождения:" — read as touching it.
DATE_ENDING_HERE = re.compile(r"(\d{1,4}[./-]\d{1,2}[./-]\d{2,4}|\d{4})\Z")


def birth_dates(text: str | None, language: str | None = None, today: date | None = None) -> list[PrintedDate]:
    """Dates printed beside a date-of-birth label — after it, or in front of it.

    After it is how a form reads. In front of it is how a form *flattened* reads: a page laid out
    in two columns comes out of a PDF as "06/12/1975ΗΜ.ΓΕΝΝΗΣΗΣ:", value first and label second,
    and taking what follows the label then reaches past it into the next line — on the archive this
    was found in, past it to the date a study was completed, three years out and on the wrong side
    of a whole life. Only a date touching the label counts as one: with so much as a space between
    them it could as easily be the date of the last field, and then what follows the label is the
    better guess.
    """
    found = []
    # Searched in the folded text and read from the original one, through the offsets the fold
    # keeps: a fold can change a string's length (ß becomes ss), and every offset after it would
    # then point a letter or two off — at the tail of the date rather than at the date.
    whole = text or ""
    folded, offsets = fold_with_offsets(whole)
    for match in BIRTH_LABEL.finditer(folded):
        touching = DATE_ENDING_HERE.search(whole[: offsets[match.start()]][-24:])
        parsed = read_printed_date(touching.group(0), language, today) if touching else None
        if parsed is None or not parsed.value:
            start = offsets[match.end()] if match.end() < len(offsets) else len(whole)
            # Up to the next colon: a colon is another field beginning, and a form that prints the
            # birth field empty — "Дата народження: Вік:" — otherwise hands over the date of the
            # field below it. The date itself may hold one ("06.12.1975 10:30"), which is why what
            # is cut is what comes *before* the date rather than the date itself.
            after = whole[start : start + 30].split(":")[0]
            parsed = read_printed_date(after, language, today)
        if parsed.value:
            found.append(parsed)
    return found


def same_date(one: PrintedDate, other: PrintedDate) -> bool:
    if not one.value or not other.value:
        return False
    if "year" in (one.precision, other.precision):
        return one.value.year == other.value.year
    return one.value == other.value
