"""Reading a printed reference range, and comparing a value with it.

The archive stores what the form printed and nothing else. This module is the one place that
does arithmetic on it, and it is used only where a person has turned interpretation on for their
own instance: comparing a value with the range printed beside it on the same form.

It answers "cannot tell" often and on purpose. A range printed for men and women at once, a
range with no numbers, a value that is a word — all give None rather than a guess. Nothing here
knows anything about health: it compares two numbers that the same laboratory printed together.
"""

import re

# A sign only counts when nothing numeric precedes it: in "3,89-5,84" the dash separates.
NUMBER = re.compile(r"(?<![\d.,])[-+]?\d+(?:[.,]\d+)?")
BELOW = ("<", "≤", "до", "less", "menor", "menos", "menee", "hasta", "under", "up to", "max", "менее", "менше", "не более", "не больше")
ABOVE = (">", "≥", "від", "от ", "more", "mayor", "desde", "over", "min", "более", "больше", "не менее", "понад", "свыше")
# Two numbers are a range only where the second stands beside the first as a range is printed:
# "3,5-5,5", "3,5 – 5,5", "3,5 to 5,5". A number that is part of a unit ("мг/24 ч"), a titer
# ("1:40"), or a sex-specific pair ("М <5 Ж <7") is not the other end of anything.
RANGE_SHAPE = re.compile(
    r"(?<![\d.,])([-+]?\d+(?:[.,]\d+)?)\s*(?:-|–|—|\.\.|…|to|по|до)\s*([-+]?\d+(?:[.,]\d+)?)(?![\d.,])",
    re.IGNORECASE,
)
# What a range is measured in, taken out before the numbers are counted, so that "мг/24 ч" does
# not add a 24 to the reading.
UNIT_TAIL = re.compile(r"[a-zа-яіїєґ%°]+\s*/\s*\d+\s*[a-zа-яіїєґ.]+", re.IGNORECASE)


def parse(reference: str | None) -> tuple[float | None, float | None] | None:
    """(low, high) of a printed range, either side open, or None when it cannot be read.

    Two numbers make a range. One number with a word or sign of direction makes a half-open one.
    Anything else — two ranges in one line, a word, no numbers — is not read.
    """
    if not reference:
        return None
    text = UNIT_TAIL.sub(" ", reference.strip())
    if ";" in text or ":" in text or text.count("-") > 1 and len(NUMBER.findall(text)) > 2:
        return None  # separate ranges for men and women or for ages, or a titer
    both = RANGE_SHAPE.search(text)
    if both:
        # Printed as a range, and read in the order it is printed. A pair that reads backwards is
        # a finding for a person to look at, not something to sort quietly into place.
        low, high = float(both.group(1).replace(",", ".")), float(both.group(2).replace(",", "."))
        return (low, high) if low <= high else None
    numbers = [float(item.replace(",", ".")) for item in NUMBER.findall(text)]
    if len(numbers) > 1:
        # Two numbers that are not printed as a range say nothing this program may act on.
        return None
    if len(numbers) == 1:
        folded = text.casefold()
        if any(word in folded for word in BELOW):
            return (None, numbers[0])
        if any(word in folded for word in ABOVE):
            return (numbers[0], None)
    return None


def outside(value: float | None, reference: str | None, comparator: str | None = None) -> bool | None:
    """True when the number falls outside the range printed beside it, None when it cannot be told."""
    if value is None:
        return None
    bounds = parse(reference)
    if bounds is None:
        return None
    low, high = bounds
    if comparator in ("<", "<=") and low is not None:
        return value <= low  # "<0,5" against a low bound: only a clear miss counts
    if comparator in (">", ">=") and high is not None:
        return value >= high
    if low is not None and value < low:
        return True
    if high is not None and value > high:
        return True
    return False
