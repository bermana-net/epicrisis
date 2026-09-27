"""How values are printed on real forms, for checks that compare stored fields with the page.

Typewriters printed the digit 1 as a letter I and 0 as O; Spanish and Ukrainian forms group
thousands with a dot or space; powers come as superscripts; comparators come as signs or words.
These helpers never change stored data, they only tell a real mismatch from a way of printing.
"""

import math
import re
import unicodedata
from functools import cache

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
    words = sorted({fold(word) for word in (*BELOW_WORDS, *ABOVE_WORDS)}, key=len, reverse=True)
    return re.compile(r"^\s*(" + "|".join(words).replace(" ", r"\s+") + r")(?![^\W\d_])")


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
    return (printed or "").lstrip().startswith(SIGNS) or comparator_end(printed) is not None


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
_FOLD = str.maketrans({"і": "и", "ї": "и", "є": "е", "ё": "е", "ы": "и", "э": "е", "ґ": "г", "й": "и", "ъ": "", "ь": ""})


def squeezed(text: str | None) -> str:
    """All space taken out and the case dropped: for telling one printed string from another."""
    return re.sub(r"\s+", "", text or "").casefold()


def fold(text: str | None) -> str:
    """Search form of a text: lower case, no accents, Ukrainian and Russian letters paired."""
    decomposed = unicodedata.normalize("NFKD", (text or "").casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).translate(_FOLD)


def fold_with_offsets(text: str) -> tuple[str, list[int]]:
    """The search form of a text and, for every character of it, its place in the original."""
    folded, offsets = [], []
    for position, character in enumerate(text):
        piece = fold(character)
        folded.append(piece)
        offsets.extend([position] * len(piece))
    return "".join(folded), offsets
