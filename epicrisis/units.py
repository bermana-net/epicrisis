"""What this program knows about units: which spellings are one unit, and what converts to what.

One place to add a unit. Whether two spellings are the same measure lived with the charts, the
table of what converts into what lived here, and a unit named inside a printed reference range
lived here too — so adding one unit meant remembering all three.

The first half is reading: a spelling folded to a key, two keys that are the same measure, the
unit a printed range names. The second half is converting, which happens only when a person asks
for it.

Bringing values of one test to one scale, when a person asks for it:

Off by default, and off in the repository: the archive shows what the form printed. Turned on,
a chart of one test puts every value on the scale European forms print most often — creatinine
in µmol/L, urea and glucose in mmol/L, haemoglobin in g/L — so that a history written by four
laboratories in three unit systems can be read as one line.

What keeps this honest:

- Only the pairs in the table below are ever converted. An analyte or a unit that is not here
  keeps its own chart, untouched. Nothing is guessed from the size of a number.
- The printed value, its unit and its reference range stay exactly as they were, beside the
  chart. A converted point says what it was converted from and by what factor.
- Nothing converted is stored. The archive and the index hold the printed value alone; the
  conversion happens when the chart is drawn, and switching the setting off undoes it entirely.
- The factors are molar masses, and a wrong one moves a value by a factor of ten or twenty. So
  each factor is written once, here, with the analyte it belongs to, and each has a test.
"""

import math
import re
from collections import Counter

from epicrisis.printed_values import fold, with_the_one_letter_slips


# One unit written several ways is one unit: "мкмоль/л", "мкМоль/л" and "umol/L" are the same
# measure in three alphabets. Two units of different size are not: mg/dL and мкмоль/л stay apart,
# because putting them on one axis would mean converting, and nothing here converts anything.
#
# Spellings are joined only where the joining is certain from the writing itself: the same power
# of ten written in five ways (10¹²/л, 10*12/л, 10E12/L, х10¹²/л, 1012/L), the same words in two
# alphabets, a cubic millimetre and a microlitre, which are the same volume by definition. "Т/л"
# and "Г/л" carry their prefix in a capital letter, and that is read before anything is folded,
# because "г/л" in small letters is grams and not giga. Everything else keeps its own chart:
# per litre and per microlitre are not joined, and a spelling that looks like a misreading
# ("10¹²/1") is left alone rather than guessed at.
# Each pair was written in when somebody met it, and its twin was left for later: the Cyrillic
# giga was here and the Latin one was not, so "G/L" on an English form became grams per litre and
# the same count of cells drew a second chart of its own, a thousand million away from the first.
# Then the two alphabets were here and the mixed spellings were not — a Cyrillic letter for the
# measure and a Latin one for the litre, which `eyes.py` says in its own paragraph is a shape this
# archive really prints — so "Г/L" and "G/л" became grams in exactly the same way, and "Г/Л" in
# capitals with them. So the letters are written as a choice of alphabet and the litre as a choice
# of alphabet and case, and no pair of the sixteen is left for later.
#
# One table and not two: the unit named inside a printed range is read from this same table, by
# `unit_from_reference` below. Two tables of the same knowledge disagreed, and the disagreement
# was silent — a range printed "Г/Л" was a count of cells to one reader and grams to the other.
CAPITALS = ((r"[ТT]\s*/\s*[лЛlL]", "10^12/l"), (r"[ГG]\s*/\s*[лЛlL]", "10^9/l"))
# Read only where the capital is the whole unit, never the tail of a longer one: looked for as a
# substring, "Г/Л" is inside "МГ/Л" and "МКГ/Л" and "MG/L", and a range printed in milligrams was
# read as a count of cells — the mistake the capital was added to prevent, in the other direction
# and over more values than it ever fixed.
CAPITAL_IS_THE_UNIT = tuple((re.compile(rf"(?<![^\W\d_]){pattern}(?![^\W\d_])"), plain)
                            for pattern, plain in CAPITALS)  # fmt: skip
# A backslash where the slash of a unit belongs. On a Cyrillic keyboard the two share a key, and a
# form printed "нг\\мл" where it meant "нг/мл". A backslash is never part of a unit — there is
# nothing it could mean there — so every run of them is the slash it was meant to be. Both readers
# collapse it, and both collapse it first: see unit_key.
BACKSLASH = re.compile(r"\\+")
SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
LETTERS = str.maketrans({" ": "", "·": "", "*": "", "х": "x"})
# The micro sign and the Greek mu mean "millionth" before a unit — and are the first letter of an
# ordinary Greek word before Greek letters. Translated wherever they stood, "μονάδες/L" came out as
# "uονάδεσ/l": a key of its own, a chart of its own, for a test already held under other spellings.
MICRO = re.compile(r"[µμ](?![\u0370-\u03ff\u1f00-\u1fff])")
# Every word a unit is written with in this archive's languages, longest first so that "мкмоль"
# is read before "моль". A word left out does not fail loudly: it stays in the key, half
# translated, and the key comes out in two alphabets at once — "нmol/l" beside "nmol/l" — so one
# test printed on a Ukrainian form, a Russian one and an English one drew two or three separate
# charts. On this archive 50 keys of 152 were mixed that way, carrying 15% of every value that
# had a unit at all.
# Replaced in order, so the list is kept longest first: "мкмоль" has to be read before "моль",
# and "год" before "од", or an hour comes out as a unit. Sorted here rather than trusted to the
# eye, because the one time it was trusted "мм/год" folded to "мм/gu".
_WORDS = (
    [("мкмоль", "umol"), ("ммоль", "mmol"), ("нмоль", "nmol"), ("пмоль", "pmol"), ("моль", "mol"),
     # A prefix in front of a word of units, which the overlap ate. "мкМЕ/мл" is how thyrotropin
     # and insulin are printed on Russian and Ukrainian forms, and it came out as "umolе/ml":
     # "мкм" stands in this list in its own right and was taken out of the middle of "мкМЕ", so
     # one test printed "мкМЕ/мл" here and "µIU/mL" there drew two charts in the same unit. "мМЕ/л"
     # went the same way through "мм". Longest first is no cure where one word begins another, so
     # the prefixed spellings stand here themselves. They are written as the international unit
     # and the plain one, each with its own prefix, and INTERNATIONAL below then folds the two
     # together: the words are read here, and what is the same measure is decided in one place.
     ("мкмод", "uiu"), ("мкме", "uiu"), ("мкмо", "uiu"), ("мкед", "uu"), ("мкод", "uu"),
     ("ммод", "miu"), ("мме", "miu"), ("ммо", "miu"), ("мед", "mu"), ("мод", "mu"),
     # The kilogramme, which was in no list at all, so "мг/кг" came out "mg/кg" and a weight in
     # "кг" and one in "kg" were two keys of one measure.
     ("кг", "kg"),
     ("мкг", "ug"), ("мг", "mg"), ("нг", "ng"), ("пг", "pg"), ("мл", "ml"), ("дл", "dl"),
     ("мкл", "ul"), ("мкм", "umol"), ("мм", "mm"), ("ед", "u"), ("од", "u"), ("ме", "iu"),
     # The minute written out, which only the short forms were here for. A pulse is printed "в 1
     # минуту" and "в 1 хвилину" on these forms, and "мин" and "хв" were taken out of the middle
     # of those words — so the key came out "в1minуту" and "в1minиlину", half translated, in two
     # alphabets at once, drawing a chart of its own beside the one the same measurement already
     # had. This is the failure the paragraph above this table describes, and it is the same cure:
     # the whole word stands here in its own right, longest first.
     ("хвилину", "min"), ("хвилини", "min"), ("хвилин", "min"),
     ("минуту", "min"), ("минуты", "min"), ("минут", "min"),
     ("мо", "iu"), ("мин", "min"), ("хв", "min"), ("час", "h"), ("год", "h"), ("ч", "h"), ("hours", "h"), ("hour", "h"), ("hrs", "h"), ("hr", "h"),
     ("сек", "s"), ("сек.", "s"), ("см", "cm"), ("г", "g"), ("л", "l"),
     # Spanish. One of the five languages these forms are printed in, and it stood in this table
     # only where a word happens to be spelt the same way in Latin letters — so the forms that
     # write the word out were half translated, exactly as the Russian and Ukrainian minute was
     # above. Measured on the archives here: "seg" drew the clotting times of one laboratory on a
     # key of their own beside every other form's "сек", "mm/hora" did the same to a sedimentation
     # rate, and "gramos" to the mass of a ventricle.
     #
     # The prefixed spellings are written out rather than taken apart into a prefix and a word.
     # A table entry is replaced wherever it stands, so "mili" standing for the prefix would read
     # "milimetros" as "mmetros" and "decibelios" as "dbelios" — the mixed key this paragraph
     # exists to prevent, made by the cure for it. The same choice, for the same reason, as
     # "мкМЕ" and "мМЕ" above.
     ("miligramos", "mg"), ("miligramo", "mg"), ("microgramos", "ug"), ("microgramo", "ug"),
     ("nanogramos", "ng"), ("nanogramo", "ng"), ("picogramos", "pg"), ("picogramo", "pg"),
     ("kilogramos", "kg"), ("kilogramo", "kg"), ("gramos", "g"), ("gramo", "g"),
     ("milisegundos", "ms"), ("milisegundo", "ms"), ("microsegundos", "us"), ("microsegundo", "us"),
     ("segundos", "s"), ("segundo", "s"), ("seg", "s"), ("minutos", "min"), ("minuto", "min"),
     ("horas", "h"), ("hora", "h"),
     # The microgramme's twin among the units of activity: "microUI" is "мкМЕ" in Spanish, and it
     # lands on the same two letters so that INTERNATIONAL below folds it with "µU/mL" and
     # "мкМЕ/мл" rather than this table deciding that question a second time.
     ("microui", "uiu"),
     # Unidades formadoras de colonias, which is what cfu stands for in English. Three forms of
     # this archive print it three ways — "UFC/mL", "ufc/mL", "cfu/ml" — and they are one unit.
     ("ufc", "cfu"),
     # Both spellings of the final sigma: this list runs after a casefold, which turns ς into σ,
     # so the word as a form prints it would never meet itself here.
     ("μονάδες", "u"), ("μονάδεσ", "u"), ("μοναδες", "u"), ("μοναδεσ", "u"), ("μον.", "u"), ("λίτρο", "l"), ("λιτρο", "l"),
     ("ώρα", "h"), ("ωρα", "h"), ("λεπτά", "min"), ("λεπτα", "min")]
)  # fmt: skip


def _and_the_one_letter_slips(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The table above, plus every spelling of it with one letter out of the other alphabet.

    The commonest thing a model does to a word of units is type one of its letters in the alphabet
    the mark is drawn in rather than the one the word is written in: "мкмoль/л" with a Latin o came
    out of `unit_key` as "umololь/l", a key nobody recognises, carrying a soft sign in the middle of
    it, drawing a second chart for a test the archive already holds. One such spelling — "xв", with
    a Latin x — was in this list by hand; it is generated now, with the other hundred and thirty.

    Longest first as before, and the slips sorted *after* the spellings of their own length: a
    stable sort keeps the hand-written order of the table, which equal-length entries depend on,
    because replacing "мм" first and "мо" second is not the same reading as the other way round.
    """
    by_key: dict[str, list[str]] = {}
    for spelling, key in pairs:
        by_key.setdefault(key, []).append(spelling)
    whole = with_the_one_letter_slips(by_key)
    slips = [(spelling, key) for key, spellings in whole.items()
             for spelling in spellings if (spelling, key) not in pairs]  # fmt: skip
    return sorted(pairs + slips, key=lambda pair: -len(pair[0]))


WORDS = _and_the_one_letter_slips(_WORDS)
# "кл." with its full stop was here and "кл" without one was not, so the commonest abbreviation of
# all left a Cyrillic letter in the key and drew its own chart beside the one it belongs to.
CELL_WORDS = ("клітин", "клеток", "клетки", "cells", "cell", "ery", "кл.", "кл", "лейко", "эритро",
              "еритро", "wbc", "rbc", "κύτταρα", "κυττάρα", "κύτταρο", "ερυθρά", "λευκά")  # fmt: skip
# Taken out where the word begins, and not in the middle of another: "кл" is inside "мкл", the
# microlitre, so taking it wherever it stood turned every count of cells per microlitre into a
# count per "м". Longest first, so "кл." goes before "кл" and "клітин" before both.
CELLS = re.compile(r"(?<![^\W\d_])(?:" + "|".join(re.escape(word) for word in
                   sorted(CELL_WORDS, key=len, reverse=True)) + r")")  # fmt: skip
# Counting under a microscope is written a dozen ways in four languages and means one thing:
# what one field of view holds. The words differ, the measure does not.
FIELD = ("вполізору", "вполезрения", "вполязрения", "вп/зр", "вп./зр", "вп/з", "п/з", "п/зр", "полезрения", "полізору",
         "οπτικόπεδίο", "οπτικοπεδιο", "κ.ο.π.", "κ.ο.π", "κοπ")  # fmt: skip
EXPONENT = re.compile(r"10\^?e?(3|6|9|12)(?![0-9])", re.IGNORECASE)

# A micro sign standing where a unit belongs, with a litre on the other side of the slash: "μ/L".
# "Micro" is a prefix and there is nothing to measure in it, so this is not a unit at all — and
# the micro sign becomes a plain `u` three lines into `unit_key`, so the key came out "u/l",
# which is units per litre and is what an enzyme is printed in. One leucocyte count on the
# archive this was measured on printed it, where every other form of the same test printed
# "лейко/мкл": the test drew two charts, and one of them stood a count of cells on an enzyme's
# scale. The microlitre is the same two marks with the slash on the other side, and it is the one
# measure this can be.
A_MISPLACED_MICROLITRE = re.compile(r"^[µμ]\s*/\s*[lLлЛ]$")

# The international unit and the plain one are one unit. A laboratory prints an enzyme in "U/L"
# and the one beside it prints the same enzyme in "IU/L"; for an activity measured by one method
# those are the same number, and the reader of printed ranges in this very file has said so since
# it was written — "iu/l" stands among the spellings it reads as "u/l". So the two halves of this
# file disagreed, which the paragraph above the table says must never happen: a value whose form
# printed no unit column took "u/l" out of its printed range, while the value beside it, whose
# column said "IU/L", took "iu/l" out of the column. One test, two charts, in what the forms call
# one unit. Written over the whole prefix rather than over "iu/l" alone, because "µIU/mL" against
# "µU/mL" and "mIU/L" against "mU/L" are the same question, and one answer is the only way the
# three cannot drift apart again.
# "UI" among them, which is how Spanish forms print it — unidades internacionales, the same two
# letters the other way round. It was a key of its own: on the archive these were measured on,
# "UI/L" carried 22 values over six enzymes, each of which already had a chart in "U/L", "IU/L",
# "Од/л", "од/л" or "Е/л", and the one printed in Spanish stood beside it in what the forms call
# the same unit.
INTERNATIONAL = re.compile(r"(?<![^\W\d_])([um]?)(?:iu|ui)(?![^\W\d_])")

# What is counted per minute is not the unit; the minute is. A pulse is printed "bpm", "lpm",
# "уд/мин", "уд/хв", "уд.хв.", "уд в 1 хв", "р./хв.", "/хв", "за 1 хв" and "в 1 минуту" on the
# forms of this archive — ten spellings of one measure, which came out as nine keys, five of them
# carrying Cyrillic letters the table had never been taught. The word that says what is counted is
# dropped the way the words for cells are, and "в 1", "за 1" and the Spanish "por" are the slash
# written out.
#
# "lpm" was the one left behind when the other nine were folded — latidos por minuto, the Spanish
# for beats per minute, which was simply not on the list. It stood as a chart of its own over
# three values beside the seven under "в 1 минуту", on the archive whose forms are the Spanish
# ones: half a translation of the same kind as the keys above, and the same cure.
#
# Anchored on the whole key, and never on the minute alone: "мин" by itself is a length of time —
# a clotting time, the hour a sedimentation is read at — and not a rate at all, so it keeps its
# own key. That is why each of the three branches below requires something besides the minute:
# the word for what is counted, a slash, or "per one".
COUNTED_PER_MINUTE = ("ударов", "ударів", "удари", "удар", "уд", "вдохов", "вдихів", "вдох", "вд",
                      "дых", "раз", "р", "beats", "latidos", "lat")  # fmt: skip
# Written here as a form prints them and put through LETTERS before they are matched, because by
# the time this is read the key has been through LETTERS already: it turns the Cyrillic х into a
# Latin x, so "вдохов" meets this as "вдоxов" and a word spelt the way the form spells it would
# match nothing. Written out by hand with the Latin letter, the two spellings would be one more
# pair somebody has to remember, which is what the table of words above says never works.
#
# Longest first, and sorted here rather than trusted to the eye, for the same reason that table
# is: a regular expression takes the first branch that matches, so "удар" written before "ударов"
# would leave "ов" standing and the key would come out half read.
#
# "por" with no number after it, where the other two languages write "в 1" and "за 1": Spanish
# prints "latidos por minuto" and "por minuto", and nothing is counted in the word itself.
PER_ONE = r"(?:(?:в|за)1|por)"
PER_MINUTE = re.compile(
    r"^(?:bpm|lpm"
    r"|(?:" + "|".join(sorted((word.translate(LETTERS) for word in COUNTED_PER_MINUTE),
                              key=len, reverse=True)) + r")[./]?" + PER_ONE + r"?[./]?min"
    r"|[./]" + PER_ONE + r"?[./]?min"
    r"|" + PER_ONE + r"[./]?min)$"
)  # fmt: skip


def unit_key(unit: str | None) -> str:
    """What two spellings of one unit have in common. Nothing about size or kind."""
    text = (unit or "").strip()
    # The backslash first, and before the capitals below, because they are the only pass that reads
    # a capital letter — and because getting that order wrong was worse than the split it replaced:
    # with the fold running second, "Г\\л" missed "Г/л" and came out as plain grams per litre, so a
    # count of cells and a protein stood on one axis a thousand million times apart. A key nobody
    # recognises draws a second chart and the eye catches it; a key that is quietly another unit
    # does not. The reader of printed ranges collapses the backslash in the same order, and for the
    # same reason.
    text = BACKSLASH.sub("/", text)
    for pattern, plain in CAPITAL_IS_THE_UNIT:
        text = pattern.sub(plain, text)
    # Before the micro sign becomes a plain u, because afterwards there is nothing left to tell a
    # misplaced microlitre from an enzyme's units per litre. See A_MISPLACED_MICROLITRE.
    if A_MISPLACED_MICROLITRE.match(text.strip()):
        return "/ul"
    text = MICRO.sub("u", text.translate(SUPERSCRIPT).casefold()).translate(LETTERS)
    text = CELLS.sub("", text)
    text = text.replace("гр", "г")
    if "hpf" in text or text.strip("/.") in FIELD:
        return "hpf"
    for cyrillic, latin in WORDS:
        text = text.replace(cyrillic, latin)
    # After the words, so that "МЕ/л" and "мкМЕ/мл" have already become "iu/l" and "uiu/ml" and
    # the plain and the international unit meet here as one question. See INTERNATIONAL.
    text = INTERNATIONAL.sub(r"\1u", text)
    # What is left after the words: the square metre of a filtration rate written with a Cyrillic
    # м, and the decimal comma inside "1,73". Done here rather than in LETTERS, which runs before
    # the words and would turn "мкмоль" into "mкmоль".
    # A lone Cyrillic "е" standing for units, and only where a unit stands: before the slash and
    # after the words, so that "МЕ/л" has already become "iu/l" and is not touched. As a letter in
    # the table it would have eaten the е of every other word.
    text = re.sub(r"(?<![^\W\d_])е(?=\s*/)", "u", text)
    # A lone 1 where a letter for litre belongs. A model reading a form sets "л" and "l" as the
    # digit often enough to matter: "10⁹/1" beside "10⁹/л", "g/1" beside "g/l" — one measurement in
    # two keys, drawn as two charts of one test, and neither of them the whole history. The digit is
    # only ever taken where it stands alone beside the slash, so "mg/24 h" and "10^9" keep theirs.
    text = re.sub(r"(?<=/)1(?![\d⁰¹²³⁴⁵⁶⁷⁸⁹])", "l", text)
    text = re.sub(r"(?<![\d^⁰¹²³⁴⁵⁶⁷⁸⁹])1(?=/)", "l", text)
    text = text.replace("м2", "m2").replace("м²", "m2").replace(",", ".")
    text = text.replace("mm3", "ul").replace("mm³", "ul").replace("gr/", "g/").strip("().,;[]")
    # A full stop inside a word of a unit is a form's own punctuation, not part of the word: "уд./мин"
    # and "уд/мин" are the same pulse, and "pg/" with nothing after it is "pg".
    text = re.sub(r"\.(?=/)", "", text).rstrip("/")
    # Two Cyrillic letters that stand for a unit only where they stand alone: the second after a
    # slash ("см/с"), the degree sign's own ("°С"). As table entries they would eat the с of every
    # other word, which is why they are matched here and only in these two places.
    text = re.sub(r"(?<=/)с$", "s", text)
    text = re.sub(r"(?<=°)с", "c", text)
    if text in ("мм/l", "mm/l"):
        return "mmol/l"  # millimolar written as mM is millimoles per litre
    # Last, so that the dots, the spaces and the alphabets have all been read already and what is
    # left is the key itself. See PER_MINUTE.
    if PER_MINUTE.match(text):
        return "/min"
    text = EXPONENT.sub(lambda found: f"10^{found.group(1)}", text)
    return text.lstrip("x")


# A litre holds a million microlitres, so "10⁶/µL" and "10¹²/л" are one measure written two ways,
# with the same numbers on the page. Such a pair is joined only when the archive's own numbers
# agree: both sides have at least two values and their middles are within a factor of two. That
# keeps cells per microlitre in urine, which are counted from zero, away from cells per litre in
# blood, which are counted in millions, even when a spelling is ambiguous.
PER_LITRE = re.compile(r"^(?:10\^(\d+))?/(l|ul)$")
AGREEMENT = 2.0
MIN_TO_JOIN = 2


def same_measure(key: str) -> int | None:
    """The power of ten this spelling counts in, per litre, or None when it does not say."""
    found = PER_LITRE.match(key)
    if not found:
        return None
    exponent = int(found.group(1) or 0)
    return exponent + 6 if found.group(2) == "ul" else exponent


def says_its_power(key: str) -> bool:
    """Whether the spelling writes its power of ten out, which makes the measure exact.

    "10³/mm³" and "10⁹/L" are one measure by arithmetic alone — a litre holds a million cubic
    millimetres — and no reading of the numbers is needed to know it. A bare "/µL" beside a bare
    "/L" is a different matter: neither says a power, and only the archive's own numbers can say
    whether one lab meant what the other did.
    """
    found = PER_LITRE.match(key)
    return bool(found and found.group(1))


# analyte -> the scale it is brought to, and what one unit of another kind is worth in it.
# Factors are the usual molar conversions; where a unit differs only by a prefix, the factor is
# exact. Cell counts are not here: 10⁹/L and 10³/µL are the same measure written two ways, and
# same_measure above joins those without arithmetic.
SCALES: dict[str, dict] = {
    "creatinine": {"unit": "мкмоль/л", "key": "umol/l", "from": {"mg/dl": 88.4, "mmol/l": 1000.0, "umol/l": 1.0}},
    "urea": {"unit": "ммоль/л", "key": "mmol/l", "from": {"mg/dl": 0.1665, "mmol/l": 1.0, "umol/l": 0.001}},
    "glucose": {"unit": "ммоль/л", "key": "mmol/l", "from": {"mg/dl": 0.0555, "mmol/l": 1.0}},
    "uric acid": {"unit": "мкмоль/л", "key": "umol/l", "from": {"mg/dl": 59.48, "mmol/l": 1000.0, "umol/l": 1.0}},
    "bilirubin": {"unit": "мкмоль/л", "key": "umol/l", "from": {"mg/dl": 17.1, "mmol/l": 1000.0, "umol/l": 1.0}},
    "cholesterol": {"unit": "ммоль/л", "key": "mmol/l", "from": {"mg/dl": 0.02586, "mmol/l": 1.0}},
    "triglyceride": {"unit": "ммоль/л", "key": "mmol/l", "from": {"mg/dl": 0.01129, "mmol/l": 1.0}},
    "calcium": {"unit": "ммоль/л", "key": "mmol/l", "from": {"mg/dl": 0.2495, "mmol/l": 1.0}},
    "phosphate": {"unit": "ммоль/л", "key": "mmol/l", "from": {"mg/dl": 0.3229, "mmol/l": 1.0}},
    "magnesium": {"unit": "ммоль/л", "key": "mmol/l", "from": {"mg/dl": 0.4114, "mmol/l": 1.0}},
    "iron": {"unit": "мкмоль/л", "key": "umol/l", "from": {"ug/dl": 0.1791, "umol/l": 1.0}},
    "protein": {"unit": "г/л", "key": "g/l", "from": {"g/dl": 10.0, "g/l": 1.0}},
    "albumin": {"unit": "г/л", "key": "g/l", "from": {"g/dl": 10.0, "g/l": 1.0}},
    "hemoglobin": {"unit": "г/л", "key": "g/l", "from": {"g/dl": 10.0, "g/l": 1.0}},
}

# Which indicator a scale belongs to. An id has to match one of these exactly: a ratio, a urine
# collection or a fraction is a different measurement and must not borrow another's factor.
INDICATORS: dict[str, str] = {
    "creatinine": "creatinine",
    "urea": "urea",
    "glucose": "glucose", "fasting-glucose": "glucose",
    "uric-acid": "uric acid",
    "bilirubin": "bilirubin", "total-bilirubin": "bilirubin", "direct-bilirubin": "bilirubin", "free-bilirubin": "bilirubin",
    "total-cholesterol": "cholesterol", "hdl-cholesterol": "cholesterol", "ldl-cholesterol": "cholesterol",
    "non-hdl-cholesterol": "cholesterol", "vldl-cholesterol": "cholesterol",
    "triglyceride": "triglyceride",
    "total-calcium": "calcium", "calcium": "calcium", "ionized-calcium": "calcium",
    "phosphate": "phosphate", "phosphorus": "phosphate", "inorganic-phosphorus": "phosphate",
    "magnesium": "magnesium",
    "iron": "iron", "serum-iron": "iron",
    "total-protein": "protein", "protein": "protein",
    "albumin": "albumin",
    "hemoglobin": "hemoglobin",
}  # fmt: skip

# A unit written in the reference range beside a value, where the value itself carries none.
# "53-115 мкмоль/л" says the scale as plainly as a unit column would.
_REFERENCE_UNITS = (
    ("umol/l", ("мкмоль/л", "мкмоль/ л", "мкм/л", "µmol/l", "umol/l", "μmol/l")),
    ("mmol/l", ("ммоль/л", "мм/л", "мМ/л", "mmol/l", "mm/l", "ммол/л")),
    ("mg/dl", ("мг/дл", "mg/dl", "мг%")),
    ("g/l", ("г/л", "g/l", "гр/л")),
    ("g/dl", ("г/дл", "g/dl")),
    # The prefixed spellings stand in the table in their own right. Without them "мг/л" and
    # "мкг/л" were read as "г/л", which is the same range a thousand or a million times over.
    ("mg/l", ("мг/л", "mg/l")),
    ("ug/l", ("мкг/л", "ug/l", "µg/l", "μg/l")),
    ("ng/l", ("нг/л", "ng/l")),
    ("ng/ml", ("нг/мл", "ng/ml")),
    ("pg/ml", ("пг/мл", "pg/ml")),
    ("ug/dl", ("мкг/дл", "ug/dl", "µg/dl")),
    ("u/l", ("ед/л", "од/л", "е/л", "u/l", "iu/l")),
    # Hormones and vitamin D are printed in these and in nothing else, and neither half of this
    # file knew them: a value whose form printed no unit column got no unit from anywhere.
    ("nmol/l", ("нмоль/л", "nmol/l")),
    ("pmol/l", ("пмоль/л", "pmol/l")),
)
# And the same spellings with one letter out of the other alphabet, because a range is transcribed
# by the same model that transcribes a unit column: "53-115 мкмoль/л", with a Latin o, named no
# unit at all, so a value whose own form printed no unit column got nothing from the range either
# and stood on a chart with no unit over it.
#
# Five slips are refused here and each one of them matters: "μg/l" is one letter from "mg/l" and
# "μmol/l" one letter from "mmol/l", which is a thousandfold either way, and a slip two units
# could both have been is read as neither. The rule and the measurement are in
# printed_values.with_the_one_letter_slips.
REFERENCE_UNITS = tuple(with_the_one_letter_slips(dict(_REFERENCE_UNITS)).items())
# Folded once, here, rather than once per spelling on every call. The table is three times the
# size it was and the reader of ranges is asked once per value in the archive; the length kept
# beside each one is the length of the spelling as printed, because that is what decides which of
# two spellings found in the same range is the one the form meant.
REFERENCE_UNITS_FOLDED = tuple((len(spelling), key, fold(spelling))
                               for key, spellings in REFERENCE_UNITS for spelling in spellings)  # fmt: skip

# The printed name has to say the analyte too. The factor depends on a molar mass, so it hangs on
# the analyte being the one the table means, and that a name was grouped under an indicator is a
# model's judgement. An abbreviation nobody can read alone ("Cr.", which is also chromium) is left
# unconverted rather than multiplied by a guess.
_NAMES: dict[str, tuple[str, ...]] = {
    "creatinine": ("креатинин", "креатинін", "creatinin", "creatinina", "creatinine", "kreatinin", "κρεατινιν"),
    "urea": ("мочевина", "сечовина", "urea", "ουρια", "ουρία", "harnstoff"),
    "glucose": ("глюкоз", "цукор", "glucos", "glucosa", "glukos", "γλυκοζ", "σακχαρ"),
    "uric acid": ("сечова кислота", "сечова к-та", "мочевая кислота", "мочевая к-та", "uric acid", "urato", "ουρικο"),
    "bilirubin": ("білірубін", "билирубин", "bilirrubina", "bilirubin", "χολερυθρ"),
    "cholesterol": ("холестерин", "холестерол", "colesterol", "cholesterol", "χοληστερ"),
    "triglyceride": ("тригліцерид", "триглицерид", "triglicérido", "triglicerido", "triglyceride", "τριγλυκερ"),
    "calcium": ("кальцій", "кальций", "calcio", "calcium", "ασβεστιο"),
    "phosphate": ("фосфор", "фосфат", "fósforo", "fosforo", "fosfato", "phosphate", "phosphorus", "φωσφορ"),
    "magnesium": ("магній", "магний", "magnesio", "magnesium", "μαγνησιο"),
    "iron": ("залізо", "железо", "hierro", "iron", "σιδηρο"),
    "protein": ("білок", "белок", "proteína", "proteina", "protein", "πρωτεΐν", "πρωτειν"),
    "albumin": ("альбумін", "альбумин", "albúmina", "albumina", "albumin", "λευκωματ"),
    "hemoglobin": ("гемоглоб", "hemoglobin", "haemoglobin", "hemoglobina", "hgb", "αιμοσφαιρ"),
}
# "креатинiн", with a Latin i where the Ukrainian і belongs, stood in the list above by hand: one
# spelling of one analyte, met once and written down once, while the same slip in any other of the
# fourteen would have gone on costing the conversion it gates. It is generated now, and so is the
# same slip of every other spelling here — and a slip that two analytes could both be is read as
# neither, which is what keeps a molar mass from being applied to the wrong substance.
NAMES: dict[str, tuple[str, ...]] = with_the_one_letter_slips(_NAMES)


# The id an indicator was given when its label had no letters an address could carry.
OPAQUE_ID = re.compile(r"^indicator(-\d+)?$")


def name_says_analyte(printed_name: str | None, analyte: str) -> bool:
    """Whether the name on the form names this analyte itself, not only the group it was put in."""
    folded = fold(printed_name or "")
    return any(fold(word) in folded for word in NAMES.get(analyte, ()))


def scale_of(indicator_id: str | None, printed_name: str | None = None) -> dict | None:
    """The scale this indicator is brought to, or None when it is not one this table knows."""
    analyte = analyte_of(indicator_id, printed_name)
    return SCALES.get(analyte) if analyte else None


def analyte_of(indicator_id: str | None, printed_name: str | None = None) -> str | None:
    """Which analyte a value is of: by the indicator's id, or by the name printed on the form.

    The id is a slug of whatever the person called the group, so an archive whose labels are
    written in Cyrillic or Greek has ids this table cannot match and conversion was silently
    inert for it — on exactly the archives the conversion was written for. The printed name is
    the same evidence the conversion already requires before it will move a value at all.
    """
    identifier = (indicator_id or "").strip()
    known = INDICATORS.get(identifier)
    if known:
        return known
    # Only where the id says nothing at all. An id this table does not hold is usually a decision
    # rather than a gap — "urine-creatinine" is left out on purpose, because a urine collection is
    # not a serum measurement and must not borrow its factor. The gap this fills is the opaque id
    # an archive with Cyrillic or Greek labels used to get, which named nothing.
    # A value in no group at all is not converted either: which values are one test is a
    # person's judgement, and the factor hangs on it.
    if not identifier or not OPAQUE_ID.match(identifier):
        return None
    for analyte in SCALES:
        if name_says_analyte(printed_name, analyte):
            return analyte
    return None


def convert(value: float | None, unit_key: str, indicator_id: str | None, printed_name: str | None = None) -> tuple[float, str, float] | None:
    """(value on the common scale, its unit as written, the factor used), or None when not converted."""
    analyte = analyte_of(indicator_id, printed_name)
    scale = SCALES.get(analyte) if analyte else None
    if scale is None or value is None or not name_says_analyte(printed_name, analyte):
        return None
    factor = scale["from"].get(unit_key)
    if factor is None:
        return None
    return value * factor, scale["unit"], factor


# A range that is nothing but numbers and a per-cent sign says its unit as plainly as a column
# would: "19,0-37,0%" is a percentage and cannot be anything else. A range holding two ranges —
# "19 - 37 % 1,200 - 3,000*10⁹/л", the relative and the absolute count on one line — says two
# things, and which of them the value belongs to is not written anywhere, so it says nothing here.
PER_CENT_RANGE = re.compile(r"^[\d\s.,;:–—+-]*\d[\d\s.,;:–—+-]*%$")

# A unit printed inside its own range, where the form wrote out the power of ten it counts in:
# "Базофіли (абс.)  0,06   0,01-0,08 x10 9 /л" — no unit column anywhere on the line, and the unit
# standing in the range itself. The fold has read that spelling in a unit column for a long time,
# in all the ways a form writes it (10⁹, 10*9, 10 9, ·10⁶), because it is the commonest unit of a
# blood count; the reader of ranges could not read it at all, so eight values of three archives
# were drawn with no scale named on them, beside the chart they belong to.
#
# The shape is loose and the acceptance is narrow: whatever is found is handed to the fold, and the
# answer is believed only where it comes back a power of ten per a volume. That keeps the volumes
# in one place — the table of words above — and keeps a guess out: anything else inside a range is
# text, and a unit read out of text is not a reading of the page.
POWER_PER_VOLUME = re.compile(r"(?:[xх×*·]\s*)?10\s*[\^*eе]?\s*\d{1,2}\s*/\s*[^\s,;)\]]+")
COUNT_PER_VOLUME = re.compile(r"^10\^\d+/(?:l|ul|ml)$")


def unit_from_reference(reference: str | None) -> str | None:
    """The unit named inside a printed reference range, for a value whose own unit is missing.

    The longest spelling that occurs wins, not the first one in the table. "г/л" is inside
    "мкг/дл", "мг/л" and "нг/л": read in table order, a range printed in micrograms was read as
    grams and a value put on an axis a thousand times off, under a heading naming the wrong unit.
    """
    # The backslash first, for the reason unit_key gives: a unit's capital letter is read from the
    # printed text and not from the folded one, so a form that typed "Г\\л" where it meant "Г/л"
    # would miss the capitals below and fall through to the folded table as grams. Four values
    # across three archives carry a backslash in a unit column; none carries one in a range yet,
    # which is why this half is proved by a form that was invented rather than scanned.
    printed = BACKSLASH.sub("/", reference or "")
    text = fold(printed)
    if not text or not re.search(r"\d", text):
        return None
    for pattern, key in CAPITAL_IS_THE_UNIT:
        if pattern.search(printed):
            return key
    found = [(length, key) for length, key, folded in REFERENCE_UNITS_FOLDED if folded in text]
    if found:
        return max(found)[1]
    # The power of ten a form wrote into its own range, and only where the range names no other
    # unit. A line holding two ranges — the relative count in per cent and the absolute count after
    # it, "19 - 37 % 1,200 - 3,000*10⁹/л" — says two things, and which of them the value belongs to
    # is written nowhere, so the power that is plainly there must not be read: it would be a guess
    # at which half. That stands, and it is asked of the whole line, which names two units and so
    # names none; the halves are read one at a time by reference.a_band_for_each_unit, which cuts
    # the line into its bands and asks this function about each of them with its own unit beside
    # it, and answers for the unit the value in hand is read in. Every match is tried, not the first: a laboratory that prints "до 1000/мл
    # 10⁶/л" has written the same range at two scales, and the one this file can read is the power.
    if "%" not in text:
        for shape in POWER_PER_VOLUME.finditer(printed.translate(SUPERSCRIPT)):
            key = unit_key(shape.group())
            if COUNT_PER_VOLUME.match(key):
                return key
    return "%" if PER_CENT_RANGE.match(text.strip().strip("[]()").strip()) else None


# Two scales of one measure
#
# A laboratory that prints urine specific gravity as 1,015 and one that prints it as 1015 are
# printing the same measurement, and a haematocrit of 0,44 is the 44% of the next form. Drawn
# together they are two clouds a thousand apart, and the line between them says nothing.
#
# The form itself says which scale it used: the reference range printed beside the value is
# written at the scale of that value. So the bands decide and the numbers do not — where the
# bands of one test are the same band ten or a hundred or a thousand times over, the scale most
# of the values are printed at becomes the scale of the chart.
#
# What keeps this honest: nothing moves unless the printed bands themselves say this test is
# printed at two scales. A value far outside the band printed beside it is one a person has to
# see as the form printed it, and it is never quietly divided by ten. Where a single band does not fit the others
# as a whole power of ten, the test has bands that are simply different, and nothing moves at
# all. Nothing converted is stored: the value, its range and its unit stay as printed beside
# the chart, and every moved point says what it was moved by.

# The defaults; a rule file may say otherwise, and the rule is rules/shipped/two-scales-in-one-test.md
SAME_BAND = 0.15  # how far from a whole power of ten two bands may sit and still be one band
BANDS_TO_SEE_A_SCALE = 2


def band_middle(band: tuple[float | None, float | None] | None) -> float | None:
    """Where a printed range sits on the scale: its middle, geometrically.

    Only a closed range says a scale. "less than 150" says where a value stops being ordinary,
    not what size the numbers on this form are.
    """
    if not band or band[0] is None or band[1] is None or band[0] <= 0 or band[1] <= 0:
        return None
    return math.sqrt(band[0] * band[1])


def numbers_fit_the_range(band: tuple[float | None, float | None] | None, numbers: list[float],
                          agreement: float) -> bool:  # fmt: skip
    """Whether every one of these numbers could have been printed beside this reference range.

    The question a page answers and a spread of numbers cannot: a prostate-specific antigen form
    printing "up to 4" stands beside values of 1.96 and 4.35 on another form, and the two are one
    scale. Each printed end is loosened by the agreement, because a result is free to sit outside
    its own range, and an end the form left open bounds nothing — which is the whole difficulty of
    a range printed with one end, and the third paragraph below.

    Comparing the two spreads end to end refused exactly this case: the values with no unit cover
    fifteen years and start at 0.21, the named ones are two readings starting at 1.96, and a factor
    of 9.3 between two low ends says only that one group is longer than the other.

    Where the form printed one end and left the other open, that one end has to be the end of
    these numbers as well, and not merely a bound they keep on one side. A floor alone bounds
    nothing above it, so "more than 0,6" accepted every positive number there is: a creatinine
    printed in milligrammes per decilitre was one reading away from being drawn on an axis of
    micromoles per litre, which is the pair of scales this whole rule exists to keep apart, and
    the comparison of both ends that would have refused it was never reached, because a printed
    range is read first and instead of it. A ceiling alone is the same hole the other way up. So a
    lone printed end is asked the question the ends ask each other: is it the same size as the end
    of these numbers facing it. "Up to 4" beside readings of 2.08 and 4.61 is their ceiling and
    joins; a floor of 0,6 beside readings of 34 to 88.6 is nobody's floor.
    """
    if not band or not numbers:
        return False
    low, high = band
    floor = low / agreement if low and low > 0 else None
    ceiling = high * agreement if high and high > 0 else None
    if floor is None and ceiling is None:
        return False
    if not all(reading > 0 and (floor is None or reading >= floor) and (ceiling is None or reading <= ceiling)
               for reading in numbers):  # fmt: skip
        return False
    # An end the form printed and an end it did not. A nought printed in front of the dash bounds
    # nothing either, and counting it as open was measured on three archives: it took a thymol
    # turbidity printed "0-4 од." away from the five readings in units it belongs to, seven values
    # for the two it rightly refused on a urine albumin. Two ends printed is a page having spoken
    # about both of them, and this reading does not go behind what it said.
    if (low is None) != (high is None):
        printed, nearest = (high, max(numbers)) if low is None else (low, min(numbers))
        return the_same_size(printed, nearest, agreement)
    return True


def the_same_size(one: float, other: float, agreement: float) -> bool:
    """Whether two numbers are the same size, within the agreement, both of them above nought.

    A nought is not on any scale: nothing times anything reaches it, so it agrees with nothing.
    """
    return one > 0 and other > 0 and max(one, other) <= agreement * min(one, other)


def ends_agree(mine: tuple[float, float], theirs: tuple[float, float], agreement: float) -> bool:
    """Whether two spreads of numbers are the same size at both ends, low against low, high against high.

    Both ends and not the middle. Measured on three archives: a sedimentation rate of 4 to 35 with
    no unit printed, beside one of 2 to 35 printed in millimetres an hour, is one history, and
    comparing the middles of the two groups refused it; the ends say it at once, 2 against 4 and 35
    against 35. The ends also refuse what has to be refused, where comparing how far the two
    spreads overlap joined it: a creatinine of 0.5 to 55.3 beside one of 30 to 92.8 micromoles per
    litre is two scales, milligrammes per decilitre and micromoles, and the low ends are a factor
    of sixty apart.
    """
    return all(the_same_size(mine_end, their_end, agreement)
               for mine_end, their_end in zip(mine, theirs, strict=True))  # fmt: skip


def onto_one_scale(numbers: list[float | None], bands: list[tuple[float | None, float | None] | None],
                   same_band: float = SAME_BAND, bands_to_see_a_scale: int = BANDS_TO_SEE_A_SCALE) -> list[tuple[int, int]]:  # fmt: skip
    """How many powers of ten to move each value, and its own printed band, to draw one test.

    Two powers and not one: a form that printed its range at one scale and wrote the number in
    by hand at another has said both, and each of them moves the distance it is actually at.

    Zero everywhere unless the printed bands say there are two scales. A value with no band of
    its own is put on the scale its own size is nearest to, which is unambiguous when the scales
    are a hundred apart and is the only reading here not taken from a form.
    """
    nothing = [(0, 0)] * len(numbers)
    middles = [band_middle(band) for band in bands]
    known = [middle for middle in middles if middle is not None]
    if len(known) < bands_to_see_a_scale:
        return nothing
    smallest = min(known)

    def power_of(middle: float) -> int | None:
        distance = math.log10(middle / smallest)
        return round(distance) if abs(distance - round(distance)) <= same_band else None

    printed = [power_of(middle) for middle in known]
    if None in printed or len(set(printed)) < 2:
        return nothing  # bands that are not one band ten times over, or one scale and nothing to do

    scales = sorted(set(printed))

    def nearest(value: float) -> int:
        return min(scales, key=lambda scale: abs(math.log10(value / (smallest * 10.0**scale))))

    own: list[tuple[int | None, int | None]] = []
    for value, band, middle in zip(numbers, bands, middles, strict=True):
        # The range decides the value's scale only while the number is inside it: where it is
        # not, the number was written at a scale of its own and the two move apart.
        printed_at = power_of(middle) if middle is not None else None
        if printed_at is not None and (value is None or band[0] <= value <= band[1]):
            own.append((printed_at, printed_at))
        elif value and value > 0:
            own.append((nearest(value), printed_at))
        else:
            own.append((None, printed_at))
    counted = Counter(scale for scale, _ in own if scale is not None)
    common = max(counted, key=lambda scale: (counted[scale], -scale))
    return [(0 if value is None else common - value, 0 if band is None else common - band) for value, band in own]
