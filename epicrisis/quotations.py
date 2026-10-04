"""A value a document quotes from another study, and the date that value really has.

A consultation retells what was measured before it: "ТТГ 4.12 від 19.01.16", "ПСА-4,35 (12.2024)",
"05.11.2020 Глікозильований гемоглобін 4.9". The number is read correctly and stored correctly, and
then it is dated by the document that quoted it — so a measurement from January stands on a chart
in March, and one from 2019 stands in 2021. Measured on a real archive: twenty-seven such values,
the middle of them quoted 308 days from the document carrying them, the furthest 1 526.

What makes a quotation is the date printed in the value's own line. A laboratory form prints its
date once, at the top; a doctor writing a note has to say when the thing he is retelling was done,
because otherwise his own sentence means nothing.

**The one thing this must never do is mistake a printed reference range for a date.** A range is
two numbers with a dash between them and dots inside them, and to a careless reader "4.11-5.89"
is the eleventh of April and "0.57-1.52" is January 1952. On one archive a careless reader found
eight such "quotations", every one of them a real laboratory value it would then have moved years
away from where it was measured, or hidden. So a date here is one of two shapes and nothing else:

- **Three parts separated by one and the same character**, and where the year is shortened to two
  digits the other two are written in two digits as well. The one separator is what tells
  "11.02.15" from "4.11-5.89", whose separator changes from a dot to a dash. The padding is what
  tells a date from the other things that are three small numbers over one separator — a course of
  treatment, a list of doses, a line of visual acuities, a numbered heading, a device's version —
  and those were read as dates for as long as this paragraph claimed a triple could be nothing
  else. Read day first, as all five of these languages write it; a triple that can only be read
  month first needs the word below, because month first is the habit of none of them.
- **A month and a year that somebody introduced** with a word or set apart in brackets of its own,
  printed with a dot or a slash and never a dash. A dash is how a range is printed, and no other
  mark separates the two: "(норма 4-2000)" has brackets of its own, "4-2000 нг/мл феритин 23"
  opens its line, and "IgE от 5-2015 МЕ/мл" has a word in front of it that introduces dates
  everywhere else.

A month printed as a name takes the same two shapes, and is read by `dates.named_month_dates` —
the program's one reader of month names, in all five languages, in the case each declines the
month into, in the abbreviations a laboratory system prints and in the Roman numerals an old form
types with Cyrillic letters. What does not come with it is that reader's courage: it answers "this
text is a date, which one?" about a field somebody has already decided is a date, and asked the
same of a sentence it reads "Глюкоза 8.88 7.77-9.99" as August 1988. So its answers are put
through the two gates above, and a month in Roman numerals is read only where the date is printed
tight, because "х" is also the multiplication sign of every blood count on every one of these
forms.

Nothing here decides what a chart does with a quotation; it says which values are quotations and
when they were measured. What is drawn is decided by the rule that reads this.
"""

import re
from datetime import date

from epicrisis.dates import named_month_dates, searchable
from epicrisis.printed_values import fold, with_the_one_letter_slips

#: Nothing of a date is glued to a letter. A form puts a space between a word and a date, so a
#: number a letter runs straight into is a code of some kind — a version, a catalogue number —
#: and "аналізатор версія v5.2.19" is not the fifth of February.
_NOT_AFTER = r"(?<![\d/.\-])(?<![^\W\d_])"
#: Three parts with one and the same separator between them: "19.01.16", "16/04/2025". Written as
#: a back-reference on purpose — it is what tells a date from a printed range.
#:
#: The pattern is not the whole of the rule, and a sentence here saying it was is what let a
#: course of treatment and a list of doses onto a chart: what this finds still has to get past
#: `_whole_date`, which is where the rest of it is written down and why.
A_WHOLE_DATE = re.compile(_NOT_AFTER + r"(\d{1,2})([./-])(\d{1,2})\2(\d{2,4})(?![\d/.-])")
#: A month and a year, which is all a note often gives: "(12.2024)", "від 10.2015".
#:
#: A dot or a slash, and never a dash. A dash between two numbers is how every form on every one
#: of these archives prints a reference range, and "Феритин 23 нг/мл (норма 4-2000)" is the range
#: the laboratory printed beside the test and not April 2000 — the same shape read as a date put
#: that ferritin twenty-one years from where it was measured. Neither of the other two doors helps
#: here: the range sits in brackets of its own in "(норма 4-2000)", it opens the line in
#: "4-2000 нг/мл феритин 23", and in "IgE от 5-2015 МЕ/мл" a word that really does introduce dates
#: stands in front of it. Only the separator tells the two apart, so only the separator is asked.
A_MONTH = re.compile(_NOT_AFTER + r"(\d{1,2})([./])(\d{4})(?![\d/.-])")
#: Words a form uses to say "this was done then", in the five languages these archives are in.
#: Russian "с" stands beside Ukrainian "з" because it is the same word and the same single letter;
#: the Ukrainian one has been in this list since it was written and has produced no false reading
#: on any archive, which is the measurement the Russian one is admitted on.
_INTRODUCED_BY = ("від", "от", "с", "з", "from", "del", "de", "στις", "дата")
#: Compiled through the same fold as the text they are looked for in. Matched against a merely
#: case-dropped word they could not work in Greek at all: casefold turns the final ς into σ, so the
#: literal "στις" could never meet itself, and Greek was the one language of the five with no word
#: that introduces a month. printed_values._comparator_words and dates._BIRTH_LABELS were both put
#: right the same way — fold both sides; this list was the one left behind.
#: And every one of them with one letter out of the other alphabet, which is how "вiд" came to
#: stand in the list above by hand: a Latin i where the Ukrainian і belongs, on a form a model had
#: transcribed, and the word that introduces a month in Ukrainian introduced nothing. Each word is
#: its own meaning here, so a slip two of them could both be is read as neither — the same rule the
#: tables of units and of month names are built with.
INTRODUCED_BY = tuple(fold(spelling) for spellings in
                      with_the_one_letter_slips({word: (word,) for word in _INTRODUCED_BY}).values()
                      for spelling in spellings)  # fmt: skip
#: Brackets holding the date and nothing else but, sometimes, who did it: "(12.2024: Діла)".
ALONE_IN_BRACKETS = re.compile(r"\(([^()]*)\)")
#: How far a date must stand from the document's own before the value is somebody else's study and
#: not this one. A form printed on the fifth and signed on the twelfth is one visit, not two.
A_MONTH_APART = 31
#: No archive holds a measurement from before this, and nothing printed on a form is dated after
#: the document that carries it by more than a few days. Both ends are here because a range read
#: as a date lands outside them far more often than inside: "1.78-5.38" is 1938.
EARLIEST = 1900
DAYS_AHEAD = 3


def _as_date(day: str, month: str, year: str) -> date | None:
    try:
        number = int(year)
        whole = number + 2000 if number < 100 else number
        return date(whole, int(month), int(day))
    except ValueError:
        return None


def _introduced(line: str, at: int) -> bool:
    """Whether somebody put this month there on purpose, rather than it falling out of a number.

    Asked only of a month and a year, never of a whole date: three parts with one separator cannot
    be anything else, and requiring a word in front of them as well lost a real quotation —
    "Холестерин заг 29.03.19р.-5.1", where the date stands between the name of the test and the
    number, introduced by nothing but the writer's hurry. A bare "1.2024" is another matter: it is
    the shape of a measurement as much as of a month, so that one is read only where somebody put
    it there — a word in front of it, the start of the line, or brackets of its own.
    """
    before = line[:at].rstrip("  ([")
    if not before:
        return True
    # The words of the text, not the pieces a split leaves: splitting "Дата:" on non-word
    # characters ends in an empty piece, and the word that was actually there was never compared
    # with anything. Every label a form prints ends in a colon, so that was the whole list missing
    # its commonest shape of all.
    words = re.findall(r"\w+", fold(before))
    if words and words[-1] in INTRODUCED_BY:
        return True
    return any(found.start() <= at <= found.end()
               and re.fullmatch(r"[^\d]*[\d./-]+[^\d]*(:.*)?", found.group(1) or "")
               for found in ALONE_IN_BRACKETS.finditer(line))  # fmt: skip


def _whole_date(found: re.Match[str], line: str) -> date | None:
    """The day a triple of numbers over one separator names, where it can only be naming a day.

    Two things are asked of it that the pattern cannot ask for itself.

    Where the year is written in two digits, the day and the month have to be written in two
    digits as well. At that length the shape stops belonging to dates alone: a course of treatment
    ("по 1 таблетці 3 рази на день 5-7-10 днів"), a list of doses ("Еналаприл 5/10/20 мг"), a
    count in a field of view ("Епітелій 2-3-19"), a line of visual acuities ("Vis 6/9/18") and a
    numbered heading ("2.1.19 Загальні показники") are every one of them three small numbers over
    one separator, and every one of them was read as a date and carried a value years off. A form
    that shortens the year to two digits is printing a date in a field of fixed width and pads the
    other two parts; every quotation measured on these archives is printed that way. Where the
    year is written in full the triple is unmistakable and nothing is asked of the other two.

    And the reading is day first, as every language of these archives writes it — dates.py settles
    that for the whole program and this module is downstream of it. A triple whose second number
    is above twelve can only be read month first, which is the habit of none of these five
    languages; so it is the weaker evidence of the two, and it takes the same word in front of it
    that a bare month and year takes. Without that, "Еналаприл 10/20/19 мг" is a day in 2019.
    """
    first, second, year = found.group(1), found.group(3), found.group(4)
    if len(year) == 2 and not len(first) == len(second) == 2:
        return None
    if int(second) > 12 >= int(first):
        return _as_date(second, first, year) if _introduced(line, found.start()) else None
    return _as_date(first, second, year)


def _by_a_month_s_name(line: str, document_date: date) -> date | None:
    """A date whose month is printed as a name, read by the program's one reader of month names.

    Reused rather than written again. dates.py already holds the five languages, the case each
    declines the month into, the abbreviations a laboratory system prints and the Roman numerals
    an old form types with Cyrillic letters, and that list has been corrected several times — the
    last time because ΜΑΪΟΥ folds to a spelling no list held, which cost every Greek form dated in
    May its day and its month. A second reader here would need every one of those corrections
    again, separately, and would not get them.

    What is not reused is that reader's courage. read_printed_date answers "this text is a date,
    which one?" about a field somebody has already decided is a date, and asked that about a whole
    sentence it reads "Глюкоза 8.88 7.77-9.99" as August 1988. This module asks whether there is a
    date in a sentence at all, so what comes back goes through the two gates this file already
    keeps: a day with its month and year is three parts and stands on its own, while a month and a
    year alone wants the word or the brackets that a numeric month and year wants.
    """
    text, _ = searchable(line)
    for found in named_month_dates(line):
        # A Roman month is one or two letters, and "х" is the multiplication sign of every blood
        # count printed in this archive: "Лейкоцити 5 х 10 9/л" is five times ten to the ninth,
        # and read as a date it is the fifth of October 2010. A form that writes a month in Roman
        # numerals writes the date tight — "19.ІХ.2019" — so a space inside the shape says it is
        # a formula. A month written as a word cannot collide with a formula this way, and the
        # laboratory shape "10-NOV-21" is real, so nothing of the sort is asked of those.
        if found.roman and re.search(r"\s", found.printed):
            continue
        if found.precision != "day" and not _introduced(text, found.start):
            continue
        if _far_enough(found.value, document_date):
            return found.value
    return None


def quoted_date(line: str | None, document_date: date | None) -> date | None:
    """When the study this line retells was done, where the line says so and the document does not.

    None where the line names no date of its own, where the date it names is the document's own
    day, or where what looked like a date cannot be one.
    """
    if not line or not document_date:
        return None
    for found in A_WHOLE_DATE.finditer(line):
        when = _whole_date(found, line)
        if when and _far_enough(when, document_date):
            return when
    for found in A_MONTH.finditer(line):
        when = _as_date("1", found.group(1), found.group(3))
        if when and _far_enough(when, document_date) and _introduced(line, found.start()):
            return when
    # Last, so that no line any of the patterns above already reads can have its answer changed
    # by this one. The order between the two is arbitrary either way — a line naming two studies
    # gives up one of them whichever is asked first — and keeping the numbers in front is the
    # choice that moved none of the readings measured on the live archives.
    return _by_a_month_s_name(line, document_date)


def _far_enough(when: date, document_date: date) -> bool:
    """A plausible day, and far enough from the document's own to be another study."""
    if not EARLIEST <= when.year <= document_date.year + 1:
        return False
    if (when - document_date).days > DAYS_AHEAD:
        return False  # a form cannot quote a study done after it was printed
    return abs((document_date - when).days) > A_MONTH_APART
