"""How values are printed on real forms, for checks that compare stored fields with the page.

Typewriters printed the digit 1 as a letter I and 0 as O; Spanish and Ukrainian forms group
thousands with a dot or space; powers come as superscripts; comparators come as signs or words.
These helpers never change stored data, they only tell a real mismatch from a way of printing.

The fold at the bottom of this file — case, accents, the apostrophe, the Ukrainian and Russian
letters that stand beside each other — is the form every match in this program is made on, and
`as_a_name` beside it
answers the one question that follows from the same alphabets: what a name somebody typed comes to
when a file has to be called it. Both are decisions about letters and neither reads a meaning.
"""

import math
import re
import unicodedata
from collections.abc import Iterable
from functools import cache

# One word holding two alphabets is a letter read from the wrong one. The ranges rather than a
# list of letters, because these are whole alphabets and a form can print any of them.
CYRILLIC = re.compile(r"[\u0400-\u04FF]")
LATIN = re.compile(r"[A-Za-z]")


def mixed_script_words(text: str | None) -> list[str]:
    """Words holding both alphabets at once, as in "Кліnіка": a letter read from the wrong one.

    A name may hold words of each alphabet ("Клініка VITAMED"); one word holding both is a slip.

    Here rather than in the step that first needed it: this is a decision about letters, which is
    what this module owns, and it is asked by a check of the extract step — one module reaching
    up into another for a text predicate, which is the shape `ARCHITECTURE.md` names.
    """
    return [word for word in re.findall(r"[^\W\d_]+", text or "") if CYRILLIC.search(word) and LATIN.search(word)]


SIGNS = ("<", ">", "≤", "≥")
# The words a form prints instead of a sign, in the five languages of this archive, and which way
# each one points. One list for the whole program: there were two, in two files, and they had
# already drifted — "menos de" was a comparator to one and not to the other, so every Spanish
# value written that way was reported as carrying a comparator its form had not printed, and no
# Greek word was known to the reader of ranges at all, so a Greek one-sided range drew no band
# and was never compared with anything.
# A word that stands before its number and one that stands after it are both here, and both
# alphabets of each language: a form prints "до 5" as readily as "5 и более", and "не вище" exists
# because "не выше" does. Each language was written in once, by whoever met it, and each time the
# other half of it was left out — so a Ukrainian ceiling was read as a floor and an English "20 or
# less" was read as nothing at all, on forms that print them by the thousand.
BELOW_WORDS = ("до", "менее", "меньше", "ниже", "не более", "не больше", "не выше", "нижче",
               "менше", "не більше", "не вище", "і менше", "и менее", "или менее", "або менше",
               "less than", "up to", "below", "under", "max", "or less", "and below", "or fewer",
               "hasta", "menor de", "menos de", "inferior a", "hasta de", "o menos",
               "έως", "μέχρι", "κάτω από", "μικρότερο από", "μικροτερο απο", "ή λιγότερο")  # fmt: skip
ABOVE_WORDS = ("від", "от", "более", "больше", "свыше", "выше", "не менее", "не ниже", "понад",
               "вище", "більше", "не менше", "не нижче", "і більше", "и более", "или более",
               "або більше", "more than", "above", "over", "min", "or more", "and above",
               "mayor de", "más de", "mas de", "superior a", "desde", "o más",
               "άνω του", "άνω από", "πάνω από", "μεγαλύτερο από", "μεγαλυτερο απο", "ή περισσότερο")  # fmt: skip
@cache
def _comparator_words() -> re.Pattern[str]:
    """The words above, in the same folded form as the text they are looked for in.

    Case alone was not enough and could not be: a form printing ΕΩΣ or ΜΕΧΡΙ in capitals loses the
    accents that the lower-case words carry, and a Greek word ending in ς meets itself only after a
    fold. So those printed in capitals were no comparator at all — while reference.parse, which does
    fold, read the very same strings correctly. One list of words, two readers, and they disagreed.
    """
    return re.compile(r"^\s*(" + _any_comparator_word() + r")(?![^\W\d_])")


#: Two of the words above are read in front of their number and never behind it, because behind a
#: number they are not a direction but a unit: "120 мин" is a time, "уд/мин" is a pulse, and "max"
#: standing after a number is a shape no form of this archive prints at all. Both are headings of
#: a column, and a heading stands in front of what it heads. reference.parse goes on reading them
#: wherever they stand, and that is not the disagreement this one list was made to end: it reads
#: the range printed beside a value, where "120 мин" is not something a laboratory prints, while
#: this reads the value itself. Of every value on these archives that prints one of the two words
#: after its number, both are a count of minutes and neither is a direction.
NOT_BEHIND_A_NUMBER = ("min", "max")


def _any_comparator_word(without: tuple[str, ...] = ()) -> str:
    """The words above as one alternation, longest first so that "не менее" beats "менее"."""
    words = {fold(word) for word in (*BELOW_WORDS, *ABOVE_WORDS)} - {fold(word) for word in without}
    return "|".join(sorted(words, key=len, reverse=True)).replace(" ", r"\s+")


@cache
def _a_comparator_behind_the_number() -> re.Pattern[str]:
    """The same words standing after their number instead of in front of it, as half of them do.

    The list above holds both halves of every language and says so: a form prints "до 5" as
    readily as "5 и более". The reader of it did not. Anchored to the start of the string, it
    could never match a word standing behind its number, so not one of "20 or less", "18 и более",
    "5 і більше", "40 and above", "5 o menos" or "5 ή λιγότερο" was a comparator here — in all
    five languages at once — while reference.parse, which reads a word "wherever it stands", read
    every one of them correctly. One list, two readers, and the comment over the list named the
    very shape the reader was blind to: "an English '20 or less' was read as nothing at all, on
    forms that print them by the thousand".

    What it cost: validate.comparator_missing and the same check in extract/run.py handed
    `comparator_not_printed` to a value whose comparator had been read exactly right, and the
    document went to "to check" for it.

    Nothing but space and the form's own punctuation between the number and the word, so that this
    answers for a comparator and not for any comparator word anywhere in a line. Where the word
    stands in front, the other reader also has to say where it ends; this one only has to say
    whether there is one.
    """
    return re.compile(r"\d[\s.,;)\]]*(" + _any_comparator_word(NOT_BEHIND_A_NUMBER) + r")(?![^\W\d_])")


def comparator_end(printed: str | None) -> int | None:
    """Where a comparator word before a number ends, counted in the text as printed; None if none.

    One place answers "is there a word, and where does it stop", because two readers need it: the
    check that a stored comparator was really printed, and the check for letters a value has no
    business carrying. They used to ask separately, and a word one of them read was a word the
    other counted as an unexplained letter — two false findings for every such value.
    """
    whole = printed or ""
    folded, offsets = fold_with_offsets(whole)
    match = _comparator_words().match(folded)
    if not match:
        return None
    return offsets[match.end()] if match.end() < len(offsets) else len(whole)
SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
# A letter counts as a digit only between digits or before one, never at the start of a unit ("75lpm").
_TYPEWRITER_ONE = re.compile(r"(?<![^\W\d_])[IlІ](?=[\d,.]?\d)|(?<=[\d,.])[IlІ](?![^\W\d_])")
_TYPEWRITER_ZERO = re.compile(r"(?<![^\W\d_])[OoОо](?=[\d,.]?\d)|(?<=[\d,.])[OoОо](?![^\W\d_])")
_POWER = re.compile(r"(\d+)\s*(?:\^|\*\*)?\s*([⁰¹²³⁴⁵⁶⁷⁸⁹⁻]+)")
# The space between groups of thousands is a space to a person and any of five characters to a
# computer. Text pulled out of a PDF is full of the non-breaking one, and a form typeset properly
# uses the narrow one — and where the pattern took only the plain space, "1 234" became two
# tokens, which switched the check for a misread number off entirely (two tokens means "nothing
# to compare") and left a person's own correction with no number at all.
_GROUP_SPACE = " \u00a0\u202f\u2009\u2007'\u2019"
# The two shapes a grouped number comes in, and neither of them begins with a lone zero: no form
# has ever printed 0,033 for thirty-three, or 0.033 for thirty-three, which is what saves an
# ordinary three-decimal value from being read as a question it does not hold.
_NOT_AFTER_A_LONE_ZERO = rf"(?![-+]?0[.,{_GROUP_SPACE}])"
_DOT_GROUPS = re.compile(rf"^{_NOT_AFTER_A_LONE_ZERO}[-+]?\d{{1,3}}(?:[.{_GROUP_SPACE}]\d{{3}})+(?:,\d+)?$")
_COMMA_GROUPS = re.compile(rf"^{_NOT_AFTER_A_LONE_ZERO}[-+]?\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?$")
# A comma groups thousands on an American form as a dot does on a Spanish one, and the tail of the
# number is then written with the other mark: 1,234.56 beside 1.234,56. Taken as two tokens, such a
# number counted as "nothing to compare" and a person's own correction was left with no number.
#
# The two things that keep the grouped shapes from eating an ordinary decimal, and which this
# pattern was missing while `readings` above had both: a grouped number never begins with a lone
# zero, and a group of thousands is never followed by a fourth digit. Without them "0,0035" was cut
# into "0,003" and "5" — two tokens, so the check that a stored number is the number on the page
# switched itself off in silence, and a correction typed by hand was left with no number at all.
# Four decimals after a comma is how the Ukrainian and Russian forms of this archive print a small
# result, so the check was off for that whole half of it.
_NOT_A_LONE_ZERO = rf"(?!0[.,{_GROUP_SPACE}])"
_NOT_BEFORE_A_DIGIT = r"(?!\d)"
_TOKEN = re.compile(
    rf"[-+]?(?:{_NOT_A_LONE_ZERO}\d{{1,3}}(?:[.{_GROUP_SPACE}]\d{{3}})+(?:,\d+)?{_NOT_BEFORE_A_DIGIT}"
    rf"|{_NOT_A_LONE_ZERO}\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?{_NOT_BEFORE_A_DIGIT}"
    rf"|\d+(?:[.,]\d+)?|[.,]\d+)")


def typewriter_digits(text: str) -> str:
    return _TYPEWRITER_ZERO.sub("0", _TYPEWRITER_ONE.sub("1", text or ""))


def number_tokens(text: str) -> list[str]:
    return _TOKEN.findall(typewriter_digits(text))


def readings(token: str) -> set[float]:
    """Every number a printed token can mean: decimal comma, decimal point, grouped thousands.

    Read by shape rather than by trying every substitution, because the substitutions answer for
    tokens that never had a question in them: "4,5" is four and a half on four of this archive's
    five languages, and taking its comma out as a separator of thousands made it forty-five.
    """
    plain = token
    for space in _GROUP_SPACE[1:]:  # every way a form writes the space between thousands
        plain = plain.replace(space, " ")
    stripped = plain.replace(" ", "")
    values = set()

    def maybe(text: str) -> None:
        if text.startswith((".", "-.", "+.")):
            text = text.replace(".", "0.", 1)
        try:
            values.add(float(text))
        except ValueError:
            pass

    # Grouped thousands, written either way round: the separator comes out and the tail, which is
    # written with the other mark, is the decimal part. 1.234,56 on one form and 1,234.56 on
    # another are the same number, and both say so themselves.
    if _DOT_GROUPS.match(plain):
        maybe(stripped.replace(".", "").replace(",", "."))
    if _COMMA_GROUPS.match(plain):
        maybe(stripped.replace(",", ""))
    # And as one number with a decimal mark, where there is only one mark to be it.
    if stripped.count(",") + stripped.count(".") <= 1:
        maybe(stripped.replace(",", "."))
    return values


def reads_at_two_scales(text: str | None) -> bool:
    """Whether any number in this printed text could have been meant at two scales.

    One place answers it, and it answers by reading rather than by a second pattern. A number
    written as 1.234 means one thing on a Spanish form and another on an English one, and nothing
    in the text says which; a number grouped by a space means only one thing, because no form has
    ever printed a space for a decimal point. Two patterns used to decide this separately — one
    here, one in reference.py — and they disagreed exactly there: a range printed "150 000 -
    400 000" was called unreadable and lost its band, and could not settle the scale of an
    ambiguous value beside it, which is the one job it was fit for.
    """
    return any(len(readings(token)) > 1 for token in number_tokens(text or ""))


def number_as_printed(observation: dict) -> float | None:
    """The number a corrected value now holds, or nothing where the correction is not a number.

    Read the way every printed value in this program is read, rather than by one rule of its own.
    The rule of its own was "comma is a point, spaces come out", which made 1.234 into 1.234 where
    the form meant one thousand two hundred and thirty-four — a value a thousand out, standing in
    the table as the person typed it and marked corrected, wrong only on the chart and in the
    answer given over the network, with no check able to see it because the checks read the
    model's transcription and not the correction.

    Where the text genuinely reads two ways, no number is taken. The person's own text stands as
    they wrote it; a value with no number is drawn nowhere and compared with nothing, which is
    what a program should do with something it cannot read, and it is not a thousand out.
    """
    printed = (observation.get("value_as_printed") or "").strip()
    tokens = number_tokens(printed)
    if len(tokens) != 1:
        return None
    could_be = readings(tokens[0])
    if len(could_be) == 1:
        return could_be.pop()
    if not could_be:
        return None
    if len(could_be) > 1:
        # Genuinely two readings. The form itself usually settles it: the range printed beside the
        # value is on the scale the value was printed at, and only one reading falls in it. This
        # is how the rest of the program reasons about a number it is unsure of, and it is what
        # keeps a urine specific gravity of 1.005, printed beside "1.005 - 1.030", a number at all.
        printed_beside = observation.get("reference_as_printed")
        # A range written the same two-ways way settles nothing: it carries the very question it
        # is being asked to answer, and answering with it made the two agree while both were a
        # thousand out — which is worse than not knowing, because then no check can see it.
        band = None if _reads_two_ways(printed_beside) else _printed_range(printed_beside)
        if band:
            low, high = band
            inside = [reading for reading in could_be
                      if (low is None or reading >= low) and (high is None or reading <= high)]  # fmt: skip
            if len(inside) == 1:
                return inside[0]
        return None
    # Several readings and no grouping: "0.93" reads as 93 only by taking a leading zero for a
    # thousands group, which no form has ever printed. The decimal reading is the one meant.
    try:
        return float(tokens[0].replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def _printed_range(text: str | None):
    """The range as the form printed it, through the one reader of a range this program has."""
    from epicrisis import reference

    return reference.parse(text)


def _reads_two_ways(text: str | None) -> bool:
    """Whether that printed range is itself written at a scale the text does not settle."""
    from epicrisis import reference

    return reference.reads_two_ways(text)


def number_matches(printed: str, value: float) -> bool:
    """False only when the printed text holds exactly one number and no reading of it is the value."""
    text = typewriter_digits(printed)
    for base, exponent in _POWER.findall(text):
        try:
            power = float(base) ** int(exponent.translate(SUPERSCRIPTS))
        except (OverflowError, ValueError):
            # "4,5⁹⁹⁹⁹⁹" is not a power anybody printed on a form; it is a misread superscript,
            # and it used to end the whole validation run for the archive.
            continue
        if math.isclose(power, value, rel_tol=1e-9):
            return True
    tokens = _TOKEN.findall(text)
    if len(tokens) != 1:
        return True
    return any(math.isclose(reading, value, rel_tol=1e-9, abs_tol=1e-12) for reading in readings(tokens[0]))


def comparator_printed(printed: str) -> bool:
    """Whether the form itself printed a comparator: a sign, or a word on either side of the number."""
    text = printed or ""
    if text.lstrip().startswith(SIGNS) or comparator_end(text) is not None:
        return True
    return _a_comparator_behind_the_number().search(fold(text)) is not None


def unexplained_letters(printed: str) -> bool:
    """Letters in a numeric value that are not a comparator word, typewriter digits or a unit after the number."""
    ends = comparator_end(printed)
    text = typewriter_digits((printed or "")[ends:] if ends is not None else (printed or ""))
    text = re.sub(r"(?<=\d)\s*[^\W\d_][^\d]*$", "", text.strip())
    return bool(re.search(r"[^\W\d_]", text))


def numbers_in_text(printed: str, text: str) -> bool:
    """Every number of a printed field appears in the page text, wherever the lines were joined."""
    squeezed = re.sub(r"\s+", "", typewriter_digits(text)).casefold()
    return all(re.sub(r"\s+", "", token) in squeezed for token in number_tokens(printed))


# Letters that differ between Ukrainian and Russian spellings of the same word. ы and э belong
# here for the commonest pairs of all: Эритроциты and Еритроцити, Белок and Білок, Мышцы and
# М'язи. Without them a Russian spelling found nothing in an archive whose forms are Ukrainian,
# on a page that promises the two are matched as one.
#
# Two of those three examples are wishes, not facts, and saying so is better than letting the
# comment stand as a test nobody ran: і→и cannot join Білок to Белок or Залізо to Железо, where
# the languages differ by і↔е and і↔о rather than by a letter this table can pair. Эритроциты
# and Еритроцити do join, and so do Кальций/Кальцій, Гемоглобин/Гемоглобін, Креатинин/Креатинін.
# The rest needs a list of words, not a list of letters, and there is not one yet.
#
# The letters drawn the same in three alphabets are not folded here, and that is deliberate: the
# folded form of a whole Cyrillic word must stay Cyrillic, or "белок" becomes "бelok" and nothing
# matches anything. Where they matter is a short printed abbreviation — "В12", "С-реактивный",
# "Т4", "Са", "К" are typed in Cyrillic on a Russian or Ukrainian form, and a person at a Latin
# keyboard types Latin — and that is answered where a question is asked, by looking for both, not
# by changing what a word folds to. See query.also_written_as.
_DRAWN_ALIKE = {"а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p",
                "с": "c", "т": "t", "у": "y", "х": "x", "і": "i", "ѕ": "s", "ј": "j",
                "α": "a", "β": "b", "ε": "e", "η": "h", "ι": "i", "κ": "k", "μ": "m", "ν": "v",
                "ο": "o", "ρ": "p", "τ": "t", "υ": "y", "χ": "x", "ς": "c", "σ": "c"}  # fmt: skip


# And the way back. A Latin letter is drawn like a Cyrillic one and like a Greek one, so the other
# spellings of a Latin word are two, not one — which is why this is a list and the table above is
# not simply reversed.
_DRAWN_ALIKE_BACK: dict[str, list[str]] = {}
for _from, _to in _DRAWN_ALIKE.items():
    _DRAWN_ALIKE_BACK.setdefault(_to, []).append(_from)


def also_written_as(word: str) -> list[str]:
    """The same short word typed in the other alphabets, where every letter of it is drawn alike.

    "В12" on a Ukrainian form is Cyrillic; the person looking for it types Latin "B12", and the two
    share not one character. Only for words whose every letter has a twin, so an ordinary word is
    never rewritten into nonsense, and only as something more to look for.

    Both ways round. It used to answer only for a word typed in Cyrillic or Greek, and the case it
    was written for is the other one: a person at a Latin keyboard typing B12 or T4 against forms
    printed in Cyrillic found nothing at all, while the same question asked from the other side
    worked. The docstring described the case that did not work.
    """
    letters = [ch for ch in word if ch.isalpha()]
    if not letters:
        return []
    if all(ch in _DRAWN_ALIKE for ch in letters):
        swapped = "".join(_DRAWN_ALIKE.get(ch, ch) for ch in word)
        return [swapped] if swapped != word else []
    if all(ch in _DRAWN_ALIKE_BACK for ch in letters):
        # One word in, two out: the Cyrillic spelling and the Greek one, where they differ.
        spellings = []
        for alphabet in (0, 1):
            made = "".join(_DRAWN_ALIKE_BACK.get(ch, [ch] * 2)[min(alphabet, len(_DRAWN_ALIKE_BACK.get(ch, [ch])) - 1)]
                           if ch in _DRAWN_ALIKE_BACK else ch for ch in word)  # fmt: skip
            made = fold(made)  # the index holds folded text, and a final sigma folds to a medial one
            if made != word and made not in spellings:
                spellings.append(made)
        return spellings
    return []


def one_letter_in_the_other_alphabet(word: str) -> list[str]:
    """This word with exactly one of its letters typed in the other alphabet it is drawn in.

    Between the fold above and `also_written_as` there is a shape neither of them covers, and it
    is the one a model transcribing a page produces by the hundred: a Cyrillic word with a single
    Latin letter inside it, because on paper "і" and "i" are one mark and the model picked the
    other alphabet for that one character. The fold cannot answer it — fold the letters drawn
    alike and "белок" becomes "бelok" and nothing matches anything — and `also_written_as` cannot
    either, because it answers only for a word whose *every* letter has a twin, which is "В12" and
    never "креатинін". So the program has met this three times and patched it three times one
    spelling at a time: "вiд" in quotations, "креатинiн" in units.NAMES, "xв" in units.WORDS.

    Exactly one letter, and that is the whole of what makes these spellings safe to put in a
    table: a word of one alphabet carrying one letter of another is a word of no language at all,
    so none of them can ever be an ordinary word that somebody meant. Two letters and the
    guarantee is gone — "мар", the stem of March, with all three of its letters swapped is the
    English word "map", and a date reader holding that would read "map" as a month.
    """
    letters = [(place, letter) for place, letter in enumerate(word) if letter.isalpha()]
    if len(letters) < 2:
        # A word of one letter has no "rest of the word" left in its own alphabet, so the swap
        # does not make a spelling of no language: it makes an ordinary letter of another one.
        return []
    spellings: list[str] = []
    for place, letter in letters:
        twins = (_DRAWN_ALIKE[letter],) if letter in _DRAWN_ALIKE else _DRAWN_ALIKE_BACK.get(letter, ())
        for twin in twins:
            made = word[:place] + twin + word[place + 1:]
            if made != word and made not in spellings:
                spellings.append(made)
    return spellings


def with_the_one_letter_slips(by_meaning: dict) -> dict:
    """Each meaning's printed spellings, and the one-letter slips of them that only it could be.

    What a table of printed spellings is to be built with, so that one letter out of the other
    alphabet does not cost the whole entry. Written here and not in each table because the tables
    had been patched one spelling at a time and the spelling that was patched was the one somebody
    happened to meet.

    A slip two meanings could both have been is read as neither, and that rule is not a nicety:
    "mg/l" is one letter from "μg/l" — a Latin m where a Greek mu belongs — and those two are a
    thousandfold apart, so a table that read the slip would put milligrams and micrograms on one
    axis and under one heading. Five such spellings are refused in the table of units alone.
    Compared both as written and as folded, because the micro sign and the Greek mu are two
    characters before a fold and one after it: "μg/dl" walked straight through the first version
    of this guard, which compared the written form only.
    """
    def shapes(word: str) -> set[str]:
        return {word, fold(word)}

    claimed: dict[str, set] = {}
    for meaning, spellings in by_meaning.items():
        for spelling in spellings:
            for made in (spelling, *one_letter_in_the_other_alphabet(spelling)):
                for shape in shapes(made):
                    claimed.setdefault(shape, set()).add(meaning)
    whole = {}
    for meaning, spellings in by_meaning.items():
        extra: list[str] = []
        for spelling in spellings:
            for made in one_letter_in_the_other_alphabet(spelling):
                if all(claimed[shape] == {meaning} for shape in shapes(made)):
                    if made not in spellings and made not in extra:
                        extra.append(made)
        whole[meaning] = (*spellings, *extra)
    return whole
_FOLD = str.maketrans({"і": "и", "ї": "и", "є": "е", "ё": "е", "ы": "и", "э": "е", "ґ": "г", "й": "и", "ъ": "", "ь": ""})

#: The apostrophe goes out with the soft sign, because it is the soft sign: Ukrainian prints one
#: where Russian prints ь, and the table above already drops the ь so that the two alphabets'
#: spellings of one word meet. Kept, it undid that in the one place it matters most — "Дем'яненко"
#: and "Демьяненко" were two strings to every search in this program, and a person looking for
#: their own doctor found half their documents.
#:
#: people.the_words_in had taken it out before folding since the day the apostrophe cost a pair of
#: names, so the two halves of this program disagreed about what an apostrophe is; now the fold
#: answers it once and the names module asks.
#:
#: Every shape a form, a keyboard or an export prints for it. Taken out **before** the NFKD
#: normalising below and not after: ´ (U+00B4), which people type where the key for an apostrophe
#: is missing, decomposes to a space and a combining accent, so by the time the accents come off
#: there is nothing left to take out. ʼ (U+02BC) survives for the other reason — it is a letter to
#: `\w`, so nothing that splits on non-word characters ever noticed it.
NO_APOSTROPHE = str.maketrans("", "", "'’‘ʼʻʽˈ`´′")


def squeezed(text: str | None) -> str:
    """All space taken out and the case dropped: for telling one printed string from another."""
    return re.sub(r"\s+", "", text or "").casefold()


def fold(text: str | None) -> str:
    """Search form of a text: lower case, no accents, no apostrophe, Ukrainian and Russian paired.

    Everything stored in a folded form — the `search` table of an index, the spellings under an
    indicator — was folded by the fold of its own day, so a change here makes those rows stale.
    The index says which version built it and refuses to answer when that is not this one
    (`query.open_index`, `index.build.SCHEMA_VERSION`); the spellings a person approved are folded
    again as they are read (`indicators.load`), because that file is their own work and no change
    of ours rewrites it.
    """
    without = (text or "").casefold().translate(NO_APOSTROPHE)
    decomposed = unicodedata.normalize("NFKD", without)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).translate(_FOLD)


def in_name_order(name: str | None) -> str:
    """The sort key for a list of printed names and labels a person reads down.

    Ordered by what the code points happen to be, or by a casefold, the Ukrainian і, ї, є and ґ
    and the Russian ё sit below я, because Unicode put them in a block of their own after the
    thirty-two letters both alphabets share. A person looking for a surname on «І» looked where it
    belongs and found it at the very bottom of the list, under every Russian name there was.

    The fold answers it, because it pairs those letters with the ones they stand beside — і with
    и, є with е, ґ with г — and that is one decision this program has already made, for
    matching, and may as well keep making in one place.

    **It folds letters; it does not sort by anybody's alphabet, and this is the whole of what it
    gives.** і, ї and й all land among the и, so a list of them is in no Ukrainian order inside
    that run; ы and э land among и and е rather than where Russian puts them; the soft sign is
    dropped, so «Ольга» and «Олга» fall together. Latin comes before Greek and Greek before
    Cyrillic, which is the blocks' own order and not a claim about any language. What it fixes is
    one thing: a letter of a person's own alphabet is no longer below every letter of another's.
    """
    return fold(name)


def fold_with_offsets(text: str) -> tuple[str, list[int]]:
    """The search form of a text and, for every character of it, its place in the original."""
    folded, offsets = [], []
    for position, character in enumerate(text):
        piece = fold(character)
        folded.append(piece)
        offsets.extend([position] * len(piece))
    return "".join(folded), offsets


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


def as_a_name(text: str, taken: Iterable[str] = (), fallback: str = "a-name", longest: int = 40) -> str:
    """A name somebody typed, as a file can be called and a URL can carry: one answer, here.

    There were two, and the second had no transliteration in it. An indicator took this one;
    a rule a person writes on the settings page took four lines of its own that kept the Latin
    letters and threw the rest away. So every rule named in Ukrainian, Russian or Greek came out
    as the fallback alone — "a-rule" — and the second such rule a person wrote was refused with
    "There is already a rule called 'a-rule'", an id they had never typed, about a file called
    a-rule.md that said nothing either. On a Ukrainian, Russian or Greek instance a person could
    write their own rule once.

    It lives beside the fold because it is the same question about the same alphabets: what a
    printed name comes to when it has to be carried by something that holds Latin letters only.
    Transliteration is not a reading of the name and changes nothing printed — the label and the
    rule's name are kept as typed, and this answers only what the thing may be called.

    `taken` is the names already spoken for, and a name that is spoken for steps aside to
    base-2, base-3: a person naming two things alike is not an error to refuse them with.
    `fallback` is what a name with no Latin letter and no digit left in it is called instead.
    """
    latin = "".join(TRANSLITERATED.get(letter, letter) for letter in fold(text))
    base = re.sub(r"[^a-z0-9]+", "-", latin).strip("-")[:longest] or fallback
    spoken_for = set(taken)
    candidate, number = base, 2
    while candidate in spoken_for:
        candidate, number = f"{base}-{number}", number + 1
    return candidate
