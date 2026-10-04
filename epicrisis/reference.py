"""Reading a printed reference range, and comparing a value with it.

The archive stores what the form printed and nothing else. This module is the one place that
does arithmetic on it, and it is used only where a person has turned interpretation on for their
own instance: comparing a value with the range printed beside it on the same form.

It answers "cannot tell" often and on purpose. A range printed for men and women at once, a
range with no numbers, a value that is a word — all give None rather than a guess. Nothing here
knows anything about health: it compares two numbers that the same laboratory printed together.
"""

import re

from epicrisis import printed_values

# A sign only counts when nothing numeric precedes it: in "3,89-5,84" the dash separates.
# Grouped-by-space first, so that "150 000" is one number here as it is everywhere else.
_GROUP_SPACES = "\u0020\u00a0\u202f\u2009\u2007"
_GROUPED_BY_SPACE = rf"[-+]?\d{{1,3}}(?:[{_GROUP_SPACES}]\d{{3}})+"
_PLAIN = r"[-+]?\d+(?:[.,]\d+)?"
NUMBER = re.compile(rf"(?<![\d.,])(?:{_GROUPED_BY_SPACE}|{_PLAIN})")


def _as_number(text: str) -> float:
    """One printed end of a range as a number: the spaces that group thousands come out."""
    return float(re.sub(rf"[{_GROUP_SPACES}]", "", text).replace(",", "."))
# The same words the rest of the program knows, and the signs. One list, in printed_values, so
# that a word cannot be a comparator on one side of the program and not on the other.
BELOW = ("<", "≤", *printed_values.BELOW_WORDS)
ABOVE = (">", "≥", *printed_values.ABOVE_WORDS)
# Two numbers are a range only where the second stands beside the first as a range is printed:
# "3,5-5,5", "3,5 – 5,5", "3,5 to 5,5". A number that is part of a unit ("мг/24 ч"), a titer
# ("1:40"), or a sex-specific pair ("М <5 Ж <7") is not the other end of anything.
# A number grouped by a space is one number: no form has ever printed a space for a decimal point,
# so "150 000" is unambiguous where "150.000" is not. Read as two numbers it was worse than
# unreadable — "000 - 400" was a printed platelet range turned into a band the values could only sit
# above — so the ends of a range are matched grouped-first, and the guards against beginning
# part-way through a group stay for everything else.
_END_OF_A_RANGE = rf"(?:{_GROUPED_BY_SPACE}|{_PLAIN})"
# The words a form puts between the two ends, in the five languages this archive is written in.
# Two of those five print a range with a word and nothing else between them — a Spanish form
# writes "3,5 a 5,5" or "de 3,5 a 5,5", a Greek one "3,5 έως 5,5" or "3,5 μέχρι 5,5" — and while this
# list held the other three only, a range printed that way was no range at all: no band on the
# chart, and nothing for the third answer mode to compare the value with, in two languages of five.
#
# Each Greek word stands here twice, with its accent and without, because a form printing ΕΩΣ in
# capitals has no accent to lower-case — printed_values lists the same two words both ways for the
# same reason. The final sigma needs no entry of its own: this pattern is matched without case, and
# "εως" meets "ΕΩΣ" that way.
#
# The Spanish word is one letter, and what keeps it from making ranges out of ordinary text is
# where it has to stand: between two numbers, with a letter on neither side of it. "vitamina 5"
# has no number in front of the a and "1,5 mg/día" none behind it, so neither is a range. The
# boundary is written in for every word here and not only for the new one, because a word that a
# letter touches is not the word at all in any of the five.
_WORDS_BETWEEN_THE_ENDS = ("to", "по", "до", "a", "έως", "εως", "μέχρι", "μεχρι")
_A_WORD_BETWEEN = r"(?<![^\W\d_])(?:" + "|".join(
    re.escape(word) for word in sorted(_WORDS_BETWEEN_THE_ENDS, key=len, reverse=True)
) + r")(?![^\W\d_])"  # fmt: skip
RANGE_SHAPE = re.compile(
    rf"(?<![\d.,])(?<!\d\s)(?<!\d\u00a0)(?<!\d\u202f)({_END_OF_A_RANGE})"
    rf"\s*(?:-|–|—|\.\.|…|{_A_WORD_BETWEEN})\s*({_END_OF_A_RANGE})(?![\d.,])",
    re.IGNORECASE,
)
# A letter somewhere between the two ends is what tells a range written in words from one written
# with a dash, and only the stretch between the ends is looked at: the word has to be counted where
# it stands between two numbers, because "до" is a word of direction far more often than it is a
# separator — "Діти: до 1 року: 100-140" holds one of each — and counting the word wherever it
# appeared would refuse ranges that are read correctly today.
_A_LETTER = re.compile(r"[^\W\d_]")


def _ranges_written_in_words(text: str) -> int:
    """How many times a range stands in this text with a word between its ends, not a sign.

    Two of them, and more numbers than one range has, is a pair of ranges printed side by side:
    "Varones 13,0 a 17,0 Mujeres 11,5 a 15,5" is a man's band and a woman's, and reading the first
    of them draws a man's band under a woman's value. The dash spelling of that same pair is
    already refused, by counting dashes, and a word needs a count of its own.
    """
    return sum(1 for found in RANGE_SHAPE.finditer(text)
               if _A_LETTER.search(text[found.end(1):found.start(2)]))  # fmt: skip


# "150.000" is a hundred and fifty thousand on a Spanish form and a hundred and fifty on an English
# one, and nothing in the text says which. The range itself is still read — a urine specific gravity
# prints "1.005 - 1.030" and that has to keep its band — but a range written this way cannot settle
# the scale of anything else, because it holds the same question. Which numbers those are is decided
# in printed_values, by reading them, and not by a second pattern here that drifted from the first.
# A threshold stated on its own: a sign or a word of direction, and a number for it to point at.
# Two of those in one line, or one beside a range, is a table of what a result would mean rather
# than a range — "< 20 Normal, 20 - 200 Microalbuminuria", "Норма до 20, 20 - 200 микроальбуминурия",
# "20-52 Suspicious, > 52 Positive". Read as a range, the middle band of such a table becomes the
# normal range, so a value the form itself calls normal is reported as outside it.
#
# The number is required. A unit printed in front of its range carries numbers of its own —
# "х10⁹/л 4,0-9,0" — and a range written "від 3,5 до 5,5" carries its words; neither is a second
# threshold, because in the first there is no word or sign and in the second no number left over.
A_THRESHOLD = None  # built below, once the words are known


# Who a range is for, rather than what a result would mean: "40 - 130 > 15 ετών" is one range, for
# people over fifteen. A number followed by one of these words is an age or a span of time, and a
# form that qualifies its range that way has not printed a second band. Where a form really does
# print one range per age, it prints two ranges, and a text holding two ranges is refused before
# this is ever asked.
AN_AGE = ("ετών", "ετη", "років", "роки", "року", "рік", "лет", "года", "год", "years", "year",
          "yrs", "y.o", "yo", "años", "anos", "днів", "дней", "days", "day", "місяц", "месяц",
          "months", "month", "тижн", "недел", "weeks", "week")  # fmt: skip
# Folded like the text they are looked for in: "ετών" loses its accent and "años" its tilde on the
# way, and a word compared against itself and losing is the kind of thing nobody finds by reading.
_AGE_AFTER = re.compile(r"\s*(?:" + "|".join(re.escape(printed_values.fold(word))
                        for word in sorted(AN_AGE, key=len, reverse=True)) + r")")  # fmt: skip


def _a_threshold_outside(text: str, start: int, end: int) -> bool:
    """Whether a threshold of its own stands outside this range: before it or after it."""
    global A_THRESHOLD
    if A_THRESHOLD is None:
        words = "|".join(_as_a_phrase(word)[:-len("(?![^\\W\\d_])")]
                         for word in sorted((*BELOW, *ABOVE), key=len, reverse=True)
                         if word.isalpha() or " " in word)  # fmt: skip
        A_THRESHOLD = re.compile(rf"(?:[<>≤≥]|(?:{words})\s*)\s*[-+]?\d")
    folded = printed_values.fold(text)
    for where in (folded[:start], folded[end:]):
        for found in A_THRESHOLD.finditer(where):
            rest = where[found.end():]
            # The number itself may run on past what the pattern took of it.
            rest = re.sub(r"^[\d.,]*", "", rest)
            if not _AGE_AFTER.match(rest):
                return True
    return False


def reads_two_ways(reference: str | None) -> bool:
    """Whether the numbers of this printed range could be read at two scales."""
    return printed_values.reads_at_two_scales(reference)
# What a range is measured in, taken out before the numbers are counted, so that "мг/24 ч" does
# not add a 24 to the reading.
UNIT_TAIL = re.compile(r"[a-zа-яіїєґ%°]+\s*/\s*\d+\s*[a-zа-яіїєґ.]+", re.IGNORECASE)
# A limit written as a share of another measurement on the same form, rather than as a range in
# the unit of the value beside it: "≤75% від білірубіну загального", "< 30% of total". A person
# reads it and it means something; a chart cannot draw it, and a comparison of two numbers cannot
# use it, because the other number is not here.
SHARE_OF_SOMETHING = re.compile(
    r"%\s*(від|вiд|от|of|del|de|da|από|απο|z|з)(?![^\W\d_])", re.IGNORECASE)


# A colon between two numbers is a titer — "1:40", "1:160" — and is never a range: the two numbers
# are one measurement written as a ratio. A colon after words is something else entirely, and it is
# the commonest thing a form puts in front of a range: "Норма: 3,5-5,5", "Reference range: 4.0-9.0".
# Both were refused together, because the guard was the colon itself, and every range printed under
# a label of its own lost its band — which is a band a person can see on the page and the chart
# cannot show.
A_TITRE = re.compile(r"\d\s*:\s*\d")


def a_band_for_each_unit(reference: str | None) -> dict[str, str] | None:
    """Where this line prints one band per unit, each band by the unit the form labelled it with.

    A blood count form prints both bands of one test on one line: the relative count in per cent
    and the absolute count after it, "47 – 72 % 2,000 – 5,500*10⁹/л". Two ranges stand there, the
    form said which scale each of them is, and reading it as two is reading rather than
    interpretation — the same permission the second entry of the constitution gives to a unit named
    inside a printed range. Read as one range it is a lie about the page: "47 – 72" becomes the
    whole of what the form printed, the half in per cent is lost and so is the half in cells per
    litre, and a value with no unit beside it is then measured against a band of neither.

    **What makes it unambiguous, and the whole of what is accepted here:**

      * every range on the line names a unit of its own — asked of units.py, which is the one
        place that reads the unit a printed range names, so this cannot drift from it;
      * no two of those units are the same unit, so a value read in one of them has exactly one
        band on the line, and which band is the form's own answer and not this program's.

    Anything short of that is refused and goes on being read as it was. "Varones 13,0 a 17,0
    Mujeres 11,5 a 15,5" labels neither band; "Ч. 11-61 Од/л Ж. 9-39 Од/л" labels both with the
    same unit, and what tells those two apart is a person's sex, which is not printed on the line
    and is not a scale; "0-8,5-20,5 мкмоль/л" is one dash too many to be anything at all. A range
    with a stray number in it is not this shape either: the number is not a range and carries no
    unit of its own.

    Measured over the 1143 printed ranges of the three archives here: five lines are read this way
    and no other line is touched.
    """
    from epicrisis import units  # units.py reads printed values; a top-level import would circle

    if not reference or not reference.strip():
        return None
    text = reference.strip()
    found = list(RANGE_SHAPE.finditer(text))
    if len(found) < 2:
        return None
    bands: dict[str, str] = {}
    for one, where in enumerate(found):
        # The stretch one range owns runs from its own first digit to the next range's: the unit a
        # form prints for a band stands after its numbers, "47 – 72 %", and the next band's
        # numbers are where that stretch ends.
        ends = found[one + 1].start() if one + 1 < len(found) else len(text)
        piece = text[where.start():ends]
        named = units.unit_from_reference(piece)
        if not named or named in bands:
            return None
        bands[named] = piece
    return bands


def _one_range_for_one_value(reference: str | None, unit: str | None = None) -> str | None:
    """This printed text with its unit taken off and its label flattened, ready to read a range
    out of — or None where the text is not one range for one value at all.

    Everything refused here is refused whatever is asked of the text afterwards: two bands
    printed side by side, a titer, a share of another measurement. Written as its own step
    because two questions are asked of the same text — where the band is, and whether the form
    printed its ends backwards — and a guard that held for one of them only would be a second
    reader of a printed range, which is the thing this module exists not to be.

    A unit may be named by the caller, and it answers one question only: which of the bands a
    line printing one per unit is the band for the value in hand. Where such a line is read with
    no unit in hand, nothing here says which half the value belongs to, so it says nothing — and
    the caller that prefers a printed band to its own arithmetic is then told the truth rather
    than handed one of the two.
    """
    if not reference:
        return None
    labelled = a_band_for_each_unit(reference)
    if labelled is not None:
        from epicrisis import units

        mine = labelled.get(units.unit_key(unit)) if unit else None
        # One band of that line, read by the same reader as any other range: a band has exactly
        # one range in it, so this goes no deeper than once.
        return _one_range_for_one_value(mine) if mine else None
    text = UNIT_TAIL.sub(" ", reference.strip())
    # More than one range on the line, counted by the one pattern that knows what a range is. It
    # was counted by the dashes, which know only the ASCII hyphen: printed with the en dash forms
    # use, "М 130,0 – 160,0 Ж 120,0 – 140,0 г/л" was read as the band for men, and a woman's
    # value drawn against a man's band is the thing the first paragraph of this module promises
    # not to do. The dash count stays beside it, because it catches what no range accounts for:
    # "0-8,5-20,5 мкмоль/л" holds one readable range and one dash too many, and is refused.
    several = (text.count("-") > 1 or len(RANGE_SHAPE.findall(text)) > 1
               or _ranges_written_in_words(text) > 1)  # fmt: skip
    if ";" in text or several and len(NUMBER.findall(text)) > 2:
        return None  # separate ranges for men and women or for ages
    if ":" in text:
        # One colon, with nothing numeric in front of it, is a label: the range is what follows.
        # A colon standing between digits is a titer, two colons are two bands printed side by side
        # ("М: <5 Ж: <7"), and digits before the colon mean the line began with a band of its own
        # ("< 20 Норма: 20 - 200") — a table of what a result would mean, whose middle band read as
        # the range makes a value the form itself calls normal report as outside it.
        if A_TITRE.search(text) or text.count(":") > 1 or any(letter.isdigit() for letter in text.split(":")[0]):
            return None
        # The colon goes and the label stays, because the direction may be printed in the label
        # itself — "Норма до: 20" is a ceiling of twenty, and the word for it is in front.
        text = text.replace(":", " ")
    if SHARE_OF_SOMETHING.search(text):
        # "≤75% від білірубіну загального" — at most seventy-five per cent of another measurement
        # on the same form. It is a real limit and a person can read it, but it is not a range in
        # the unit of the value it stands beside, and drawn as a band on that value's chart it is
        # simply a wrong band: seventy-five, in micromoles, over values between five and
        # twenty-five. What this module is allowed to do is compare two numbers one laboratory
        # printed together in one unit; this is not that.
        return None
    return text


def _ends_of_the_range(text: str) -> tuple[tuple[float, float] | None, bool]:
    """The two ends of the range printed in this text, in the printed order, and whether a range
    was printed here at all.

    The second answer is not the first one being None. A text with a threshold stated beside its
    range has a range printed in it and no ends to read, and a text with one number has neither;
    the first goes no further and the second goes on to be read as a half-open range.
    """
    both = RANGE_SHAPE.search(text)
    if not both:
        return None, False
    if _a_threshold_outside(text, both.start(), both.end()):
        # Another range stated before this one: "< 20 Φυσιολογική, 20 - 200 Μικροαλβουμινουρία"
        # is a table of what the result would mean, printed in place of a range, and reading
        # the second half of it as the range gave a band ten times the width of every value
        # under it. Two ranges in one line are already refused where they are separated by a
        # semicolon or a colon; a comma and a word are the same thing.
        #
        # A sign with its number, and not merely a number: a form that prints the unit before
        # the range — "х10⁹/л 4,0-9,0" — has numbers in front of it that belong to the unit,
        # and refusing those took the band off a white cell count and told outside() nothing.
        return None, True
    return (_as_number(both.group(1)), _as_number(both.group(2))), True


def printed_ends(reference: str | None, unit: str | None = None) -> tuple[float, float] | None:
    """The two ends of a printed range, in the order the form printed them, or None for no range.

    parse() below is what draws a band and what a value is compared with, and it answers None
    for a range printed backwards: two numbers in that order say nothing about where a value
    should sit. This answers with them anyway, in the printed order, for the one question whose
    whole subject is that a form printed them the wrong way round — reference_reversed in
    validate.py, which exists to put that in front of a person.

    That check had a pattern of its own, which knew a dash between two plain numbers and nothing
    else. Of nine spellings of one reversed range it caught one: not a Spanish "17,0 a 13,0",
    not a Greek "5,5 έως 3,5", not "5,5..3,5", not a range under a label of its own, not one
    with its unit printed after it, and not "150 000 - 100 000" — so in two of the five
    languages of this archive the check never once fired, and the thing it was there to report
    is exactly the thing that takes the band off the chart.
    """
    text = _one_range_for_one_value(reference, unit)
    return _ends_of_the_range(text)[0] if text is not None else None


def parse(reference: str | None, unit: str | None = None) -> tuple[float | None, float | None] | None:
    """(low, high) of a printed range, either side open, or None when it cannot be read.

    Two numbers make a range. One number with a word or sign of direction makes a half-open one.
    Anything else — a word, no numbers, or two ranges in one line that nothing on the line tells
    apart — is not read.

    The unit is the one the value in hand is read in, and it answers one question: a form that
    prints one band per unit on one line — "47 – 72 % 2,000 – 5,500*10⁹/л" — printed a band for
    this unit, and that band is the answer. Asked with no unit, such a line is read as what it is:
    two ranges, with nothing here to say which of them the value belongs to. See
    a_band_for_each_unit for the shape and for what it refuses.
    """
    text = _one_range_for_one_value(reference, unit)
    if text is None:
        return None
    ends, printed_as_a_range = _ends_of_the_range(text)
    if ends is not None:
        # Printed as a range, and read in the order it is printed. A pair that reads backwards is
        # a finding for a person to look at, not something to sort quietly into place.
        low, high = ends
        return (low, high) if low <= high else None
    if printed_as_a_range:
        return None
    numbers = [_as_number(item) for item in NUMBER.findall(text)]
    if len(numbers) > 1:
        # Two numbers that are not printed as a range say nothing this program may act on.
        return None
    if len(numbers) == 1:
        # A sign first, because a sign is printed against the number itself and a word may be
        # anywhere. "≤75% від білірубіну загального" — a ceiling of seventy-five per cent of
        # another measurement — was read as a floor of seventy-five, because "від" ("from") is a
        # word of direction in Ukrainian and appeared four characters later in an ordinary
        # sentence. The band was then drawn upside down and the value judged against it the
        # wrong way round.
        if any(sign in text for sign in ("<", "≤")):
            return (None, numbers[0])
        if any(sign in text for sign in (">", "≥")):
            return (numbers[0], None)
        # No sign anywhere, so a word is all there is, and it is read wherever it stands. Russian
        # and Ukrainian put it after as readily as before — "18 и более", "5 і більше" — and
        # English does too: "40 and above". Reading only what stood in front took the band off
        # every one of those.
        #
        # Compared in the search form, both sides. casefold alone turns a final Greek sigma into
        # a medial one, so "έως" stopped matching the word "έως" — and a word compared against
        # itself and losing is the kind of thing that never gets found by reading.
        said = printed_values.fold(text)
        below, above = _longest(said, BELOW), _longest(said, ABOVE)
        if below or above:
            return (None, numbers[0]) if below > above else (numbers[0], None)
    return None


def _longest(folded_text: str, words) -> int:
    """The longest of these words of direction standing in this text, by its length, or nought.

    The longest and not the first, because one of these words is inside another and means the
    opposite of it. "не менее 18" — at least eighteen — holds the word "менее", which is "less
    than", so a floor of eighteen was read as a ceiling of eighteen and the band drawn upside
    down. Whichever list holds the longer phrase has the better claim to what the form meant.
    """
    found = [len(word) for word in words if (word.isalpha() or " " in word)
             and re.search(_as_a_phrase(word), folded_text)]  # fmt: skip
    return max(found, default=0)


def _as_a_phrase(word: str) -> str:
    """This word or phrase, as a form may have spaced it: one space, two, or a line break.

    A phrase escaped whole matches only the spacing it was written with here, so "не менее",
    printed across a line break as forms do, stopped being "не менее" and became "менее" — which
    means the opposite, and drew the band upside down. The comparator words a few files away
    already allow any run of whitespace for exactly this reason; this half did not.
    """
    between = r"\s+".join(re.escape(part) for part in printed_values.fold(word).split())
    return rf"(?<![^\W\d_]){between}(?![^\W\d_])"


def outside(value: float | None, reference: str | None, comparator: str | None = None,
            unit: str | None = None) -> bool | None:  # fmt: skip
    """True when the number falls outside the range printed beside it, None when it cannot be told.

    The unit is the one the form printed for the value, and it is passed on to parse for the one
    thing it settles: which band of a line that printed one per unit stands beside this value.
    Without it such a line is not read at all, and the comparison is not made — which is the
    answer, because a value measured against the other scale's band is a verdict about nothing.
    """
    if value is None:
        return None
    bounds = parse(reference, unit)
    if bounds is None:
        return None
    low, high = bounds
    if reads_two_ways(reference):
        # The range was written in a way that reads at two scales, and the value is a thousand or
        # more away from it: the two are not on one scale, and which of them moved is not
        # something this text can say. Reporting a value as outside its range on that basis is
        # reporting the notation, not the value.
        edge = next((one for one in (low, high) if one), None)
        if edge and value and not 0.001 < abs(value / edge) < 1000:
            return None
    if comparator in ("<", "<=") and low is not None:
        return value <= low  # "<0,5" against a low bound: only a clear miss counts
    if comparator in (">", ">=") and high is not None:
        return value >= high
    if low is not None and value < low:
        return True
    if high is not None and value > high:
        return True
    return False
