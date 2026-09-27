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
RANGE_SHAPE = re.compile(
    rf"(?<![\d.,])(?<!\d\s)(?<!\d\u00a0)(?<!\d\u202f)({_END_OF_A_RANGE})"
    rf"\s*(?:-|–|—|\.\.|…|to|по|до)\s*({_END_OF_A_RANGE})(?![\d.,])",
    re.IGNORECASE,
)
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


def parse(reference: str | None) -> tuple[float | None, float | None] | None:
    """(low, high) of a printed range, either side open, or None when it cannot be read.

    Two numbers make a range. One number with a word or sign of direction makes a half-open one.
    Anything else — two ranges in one line, a word, no numbers — is not read.
    """
    if not reference:
        return None
    text = UNIT_TAIL.sub(" ", reference.strip())
    if ";" in text or text.count("-") > 1 and len(NUMBER.findall(text)) > 2:
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
    both = RANGE_SHAPE.search(text)
    if both:
        # Printed as a range, and read in the order it is printed. A pair that reads backwards is
        # a finding for a person to look at, not something to sort quietly into place.
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
            return None
        low, high = _as_number(both.group(1)), _as_number(both.group(2))
        return (low, high) if low <= high else None
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


def outside(value: float | None, reference: str | None, comparator: str | None = None) -> bool | None:
    """True when the number falls outside the range printed beside it, None when it cannot be told."""
    if value is None:
        return None
    bounds = parse(reference)
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
