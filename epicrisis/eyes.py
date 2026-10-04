"""One line of an eye examination, and which measurement each number printed in it is.

An ophthalmic form writes a whole refraction on one line, with the names of the measurements
inside the line rather than in a column of their own:

    Vis OD = 0.99 із  sph -9.75 cyl -9,0Д ax 99=0,9
    ОС сф.-9.5 ціл.-9.0 ах 99

Those are five measurements and then four — the acuity of an eye, the sphere, the cylinder, the
axis, and the acuity again with the correction in front of the eye — and the only thing that
names any of them is the line itself. A reader that takes the first word of the line for the name
of what was measured stores every number of it under "OD" or "ОС", which says which eye and not
what was measured. On one archive fifty-two values were named by nothing but an eye, and a chart
of "ОС" drew dioptres and visual acuity on one axis.

Nothing here renames anything, and nothing here is read by a model: the measurement's own word is
printed beside its number, on the page, in every one of these lines, and the line is kept beside
the value. What this module does is read that word, so that a rule can say which measurement a
line names and a person can put the name right themselves.

Two guards, both of which a careless reading walks straight into. The words «ось» and «ах» are
ordinary words of the language as well as the axis — «ось» is "here" in Ukrainian and «ах» is an
interjection — so they are read only in the company of a word that can be nothing but a
measurement. And the general fold of printed_values.py must not be used here at all: it drops the
soft sign, so «ось», the axis, folds onto «ос», the left eye. The one letter it throws away is the
only letter that tells those two apart.
"""

import re

#: Which eye, as a form really prints it: oculus dexter, sinister and uterque. In every alphabet
#: and mixed between them, because "OD" and "ОД" are the same two shapes on paper — a reading
#: comes back with a Cyrillic О in front of a Latin D and nobody can see it — and a list of the
#: two tidy spellings would miss exactly that.
#:
#: Every letter that is the same mark, and not only the ones somebody happened to write down. The
#: list held a Cyrillic с for the Latin s and no Latin c for the Cyrillic с — the one pair of the
#: whole set that is genuinely indistinguishable on paper — so «ОС», the left eye as a Russian or
#: Ukrainian form prints it, read as the left eye in Cyrillic and as nothing at all the moment a
#: transcription came back with Latin letters. A value named by that eye and nothing else was then
#: invisible to the rule this module exists for, which is the fifty-two values of one archive named
#: by an eye instead of by what was measured. The Latin y for the Cyrillic у and the Greek omicron
#: for the O are here for the same reason and were missing in the same way.
#:
#: Each key is two letters and only one of them may leave its alphabet in practice, so none of
#: these twelve new spellings is an ordinary word of any language — which matters, because this
#: answers about the whole of a value's name and a false "this is only an eye" is a person sent to
#: look at a value that was named perfectly well.
_BOTH_ALPHABETS = {("d", "д"): "the right eye", ("s", "с", "c"): "the left eye",
                   ("u", "у", "y"): "both eyes"}  # fmt: skip
EYES = {first + second: eye for letters, eye in _BOTH_ALPHABETS.items()
        for second in letters for first in ("o", "о", "ο")}  # fmt: skip

#: Greek prints the same word two ways and a reader that only drops the case meets neither of
#: them halfway: «ΆΞΟΝΑΣ» in capitals carries no accent to lower-case, and a casefold turns every
#: sigma into the medial one, so «άξονας» written here would never meet «αξονασ» read off the page.
#: The general fold of printed_values.py answers this and may not be used here — it drops the soft
#: sign, and «ось», the axis, folds onto «ос», the left eye. So this is the narrowest fold that does
#: the Greek job and nothing else: a table of Greek letters only, each one letter for one letter,
#: which cannot touch a Cyrillic or a Latin word at all.
_GREEK_HOWEVER_PRINTED = str.maketrans({
    "ά": "α", "έ": "ε", "ή": "η", "ί": "ι", "ό": "ο", "ύ": "υ", "ώ": "ω",
    "ϊ": "ι", "ϋ": "υ", "ΐ": "ι", "ΰ": "υ", "ς": "σ",
})  # fmt: skip


def as_a_form_prints_it(text: str) -> str:
    """One shape of a printed word: the case dropped, and Greek's two spellings brought together."""
    return text.casefold().translate(_GREEK_HOWEVER_PRINTED)


#: What a form calls each measurement of a refraction, in the languages these archives are in,
#: and the plain words for it that go into a finding. The order here is for a reader; the
#: expression below sorts every spelling by length, so that "сфера" is read before "сф" and
#: "visus" before "vis" however this list is edited.
#:
#: Spanish and Greek were missing, both of them whole, so on a Spanish or a Greek ophthalmic form
#: not one measurement was named: every number of a refraction stayed named by an eye and nothing
#: else, and "three measurements in the field of one number" — the half of the defect no renaming
#: can mend — was not reported at all. Two of the five languages, silent.
#:
#: The acuity is not here in either of those two, and that is deliberate: Spanish prints it "AV"
#: and Greek "ΟΟ", and "av" is how an address begins on a clinic's letterhead — "Av. 9 de Julio" —
#: while "oo" is two of the letters this file already reads as an eye. A false "this names a
#: measurement" is a person sent to look at a value that was named perfectly well, so neither goes
#: in without a form in front of us that prints it.
MEASUREMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("visual acuity", ("visus", "vis", "візус", "визус")),
    ("sphere", ("sphere", "сфера", "сфер", "sph", "сф",
                "esfera", "esf", "σφαίρα", "σφ")),
    ("cylinder", ("cylinder", "циліндр", "цилиндр", "cyl", "цил", "ціл",
                  "cilindro", "cil", "κύλινδρος", "κυλ")),
    ("axis", ("axis", "ось", "осі", "оси", "ax", "ах",
              "eje", "άξονας", "άξων")),
)  # fmt: skip
_SPELLINGS = {as_a_form_prints_it(spelling): plain
              for plain, spellings in MEASUREMENTS for spelling in spellings}  # fmt: skip

#: Spellings that are ordinary words as well, read only beside a word that is not one. «ось 9» in
#: a sentence of ordinary Ukrainian is "here are 9", and a value named «ОС» on a form that has
#: nothing to do with eyes would be reported for ever on the strength of it.
#:
#: The axis of the other two languages belongs here for the same reason, and the reason is a form
#: this archive holds: an electrocardiogram prints the axis of the heart with a number beside it,
#: "eje eléctrico 99º" in Spanish and "άξονας 99º" in Greek, exactly as «ось серця» does in
#: Russian — and an electrocardiogram has nothing to do with a refraction.
ALSO_AN_ORDINARY_WORD = frozenset(as_a_form_prints_it(word) for word in
                                  ("ось", "осі", "оси", "ах", "eje", "άξονας", "άξων"))  # fmt: skip

#: A spelling standing on its own and not inside another word: "ax" is in "max" and in "axial",
#: "sph" is in "sphincter", "ціл" is in "цілий" — and the two languages added since bring their
#: own: "esf" is in "esfínter", "cil" in "facilitar", "eje" in "ejemplo", "σφ" in "σφαγή".
#: Neither side may be a letter; a digit may follow, because a form that prints "ax95" with no
#: space between them is printing the axis.
NAMES_A_MEASUREMENT = re.compile(
    r"(?<![^\W\d_])(" + "|".join(re.escape(spelling) for spelling in
                                 sorted(_SPELLINGS, key=len, reverse=True)) + r")(?![^\W\d_])"  # fmt: skip
)
#: Nothing cleverer than a digit. What is wanted is whether the word has a number to label, and
#: the numbers on these lines come in every shape a pen can make: "-9.75", "-9,0Д", "99=0,9".
A_NUMBER = re.compile(r"\d")
#: Punctuation and spacing, which a name may carry: "ОС.", "OU:", " OD ". Letters and digits are
#: kept, so that a name holding anything more than the eye stops being only the eye.
NOT_A_LETTER_OR_A_DIGIT = re.compile(r"[\W_]+")


def the_eye_alone(name: str | None) -> str | None:
    """Which eye a value's name is, where the name is nothing but an eye, in plain words.

    "OD", "ОС.", "OU:" — and never "Vis OD", where Vis is the measurement and the eye only says
    which of the two it was measured in. That distinction is the whole rule: of ninety values
    named with an eye on one archive, thirty-eight were "Vis OD" or "Vis OS" and perfectly well
    named, and fifty-two were the eye and nothing else.
    """
    return EYES.get(NOT_A_LETTER_OR_A_DIGIT.sub("", name or "").casefold())


def measurements_named(line: str | None) -> list[str]:
    """Which measurements a printed line names beside a number, in the order it names them.

    Each word is credited with the stretch of line between it and the next measurement's word,
    and it counts only if there is a number somewhere in that stretch. A trailing "ax" with
    nothing behind it labels no number; a line reading "sph cyl -9,0" has one number and one
    word to hang it on, not two. Named twice is named once: a line carrying the sphere of both
    eyes prints "sph" twice and still names one measurement.
    """
    text = as_a_form_prints_it(line or "")
    found = [(match.group(1), match.start(), match.end()) for match in NAMES_A_MEASUREMENT.finditer(text)]
    if not found:
        return []
    until = [start for _word, start, _after in found[1:]] + [len(text)]
    beside_a_number = [word for (word, _start, after), stops in zip(found, until, strict=True)
                       if A_NUMBER.search(text[after:stops])]  # fmt: skip
    # An ordinary word on its own says nothing. In the company of "сф" or "cyl" it is the axis,
    # which is how the two real shapes above print it.
    if all(word in ALSO_AN_ORDINARY_WORD for word in beside_a_number):
        return []
    named: list[str] = []
    for word in beside_a_number:
        plain = _SPELLINGS[word]
        if plain not in named:
            named.append(plain)
    return named


def several_measurements_in_one(value: str | None) -> list[str]:
    """The measurements a stored value holds, where it holds more than one of them.

    The half of this defect that no renaming can mend: "sph -9.75 cyl -9,0Д ax" is three
    measurements standing in the field of one number, and there is no name that would be right
    for such a field. Nineteen values on one archive were in that state. Empty where the value
    holds one measurement or none, which is every ordinary value there is.
    """
    named = measurements_named(value)
    return named if len(named) > 1 else []
