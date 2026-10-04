"""The few things a form prints about the person rather than about the day they came in.

A blood group does not change; leucocytes do. That is the whole distinction this module exists
for: where two documents of one archive print different answers to a question that has one answer
for a person, one of them is wrong — a misfiled page, a mistyped field, a reading that went
astray — and a person should be told, with both pages to open.

Nothing here settles anything. It says "these two disagree", names both, and stops.

Only what a page states plainly is read. Sex is taken from a labelled field and only where the
answer is one of the words the forms of five countries use for it: a form printing "Ч/Ж" against
an empty box is offering two choices, not stating one, and a program that read that as an answer
would cry wolf on every archive that has such a form.
"""

import re

from epicrisis.printed_values import fold

#: A labelled field and a known answer. The label stands on a word boundary of its own, because
#: "пол" lives inside "полость" and a program looking for the one would find the other.
# The answer is the first word after the label and nothing more: a form prints "Sex: F   Age: 73"
# on one line, and everything up to the line end is not an answer to anything.
# The longer label first and a letter forbidden after it: "sex" lives inside "sexo", and matching
# the short one left the "o" standing where the answer should be.
SEX_LABEL = re.compile(r"(?:^|[\s(\[|;])(?:стать|пол|sexo|sex|gender|φύλο)(?![^\W\d_])"
                       r"\s*[:\-]?[ \t]*([^\s,;|]{1,14})", re.IGNORECASE | re.MULTILINE)  # fmt: skip
SEX_WORDS = {
    "male": ("чоловіча", "чоловічa", "чоловік", "мужской", "муж", "male", "m", "ч", "м",
             "hombre", "varón", "varon", "άνδρας", "αρσενικό"),
    "female": ("жіноча", "женский", "жен", "female", "f", "ж", "mujer", "γυναίκα", "θηλυκό"),
}


def sex_as_printed(text: str | None) -> set[str]:
    """Which answers to "sex" a page states plainly. Several, where a page states several."""
    said = set()
    for answer in SEX_LABEL.findall(text or ""):
        folded = fold(answer).strip().strip(".:")
        for which, words in SEX_WORDS.items():
            if folded in {fold(word) for word in words}:
                said.add(which)
    return said


def birth_dates_printed(text: str | None, language: str | None = None) -> set:
    """Dates of birth a page prints, as dates. A year alone is a year, and is kept as one."""
    from epicrisis.dates import birth_dates

    return {printed.value for printed in birth_dates(text or "", language) if printed.value}


def dates_disagree(dates: set) -> bool:
    """Whether two printed dates of birth cannot be the same person's.

    A year printed alone comes back as the first of January of that year, so a document that
    prints only the year of birth must not be read as disagreeing with one that prints the day.
    Different years disagree; two full dates inside one year disagree if they are not the same day.
    """
    if len(dates) < 2:
        return False
    if len({date.year for date in dates}) > 1:
        return True
    full = {date for date in dates if (date.month, date.day) != (1, 1)}
    return len(full) > 1
