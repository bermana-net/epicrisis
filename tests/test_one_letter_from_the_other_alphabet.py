"""One letter of a word typed in the other alphabet, and the four tables that were blind to it.

Nothing on paper tells "і" from "i", "о" from "o" or "с" from "c", so a model transcribing a
Ukrainian or Russian form comes back with one letter of a word in Latin and the rest in Cyrillic.
The general fold must not answer that — fold the letters drawn alike and "белок" becomes "бelok"
and nothing matches anything — and `also_written_as` cannot, because it answers only for a word
whose every letter has a twin, which is "В12" and never "креатинін". So the tables in between were
patched one spelling at a time, three times, each time by whoever met the spelling: "вiд" in
quotations, "креатинiн" in units.NAMES, "xв" in units.WORDS.

Every text here is invented. The units and the month names are what forms print; the numbers
belong to nobody.
"""

import pytest

from epicrisis.printed_values import (
    one_letter_in_the_other_alphabet,
    with_the_one_letter_slips,
)

CYRILLIC = range(0x0400, 0x0500)
GREEK = range(0x0370, 0x0400)


def alphabets_of(word: str) -> set[str]:
    """Which alphabets the letters of a word are written in."""
    found = set()
    for letter in word:
        if not letter.isalpha():
            continue
        found.add("cyrillic" if ord(letter) in CYRILLIC else
                  "greek" if ord(letter) in GREEK else "latin")  # fmt: skip
    return found


@pytest.mark.parametrize(("word", "wanted"), [
    ("квіт", "квiт"),       # Ukrainian April, with the і a model typed in Latin
    ("січ", "сiч"),         # and January, the other month stem of the twelve that carries one
    ("мкмоль", "мкмoль"),   # micromoles, which came out of unit_key as "umololь/l"
    ("хв", "xв"),           # per minute, the spelling that stood in units.WORDS by hand
    ("від", "вiд"),         # the word that introduces a date, patched by hand in quotations
    ("креатинін", "креатинiн"),  # and the analyte name, patched by hand in units.NAMES
])  # fmt: skip
def test_the_spelling_each_table_was_patched_with_by_hand_is_now_one_this_answers(word, wanted):
    assert wanted in one_letter_in_the_other_alphabet(word)


def test_every_spelling_it_answers_with_is_a_word_of_no_language_at_all():
    """Which is the whole of why these are safe to put in a table of printed spellings.

    One letter moves, so what comes back is a word of one alphabet carrying a letter of another,
    and no form has ever printed such a word on purpose. Two letters and the guarantee is gone:
    "мар", the stem of March, with all three of its letters swapped is the English word "map", and
    a date reader holding that would read "map 2019" as March.
    """
    for word in ("квіт", "мкмоль", "креатинін", "january", "mayo", "ιαν", "μονάδες"):
        for made in one_letter_in_the_other_alphabet(word):
            assert len(alphabets_of(made)) == 2, f"{made!r} from {word!r} is a word of one alphabet"
    assert "map" not in one_letter_in_the_other_alphabet("мар")


def test_a_word_of_one_letter_is_left_alone():
    """There is no rest of the word left in its own alphabet, so the swap makes an ordinary letter.

    "с" is a word that introduces a date in Russian and "г" is grams; answered for, they would
    become the Latin "c" and a bare "g", which are an ordinary letter of an ordinary word and
    would match inside half the table.
    """
    assert one_letter_in_the_other_alphabet("с") == [] and one_letter_in_the_other_alphabet("г") == []


def test_a_slip_two_meanings_could_both_be_is_read_as_neither():
    """The pair this rule was written for, and it is a thousandfold wide.

    "mg/l" is one letter from "μg/l" — a Latin m where a Greek mu belongs — so a table that read
    the slip would answer "milligrams" for a range printed in micrograms, and put the two under one
    heading on one axis. The same holds for "mmol/l" and "μmol/l". Five spellings are refused in
    the table of units for this reason, and the two directions of each of those two pairs are four
    of them.
    """
    whole = with_the_one_letter_slips({"mg/l": ("мг/л", "mg/l"), "ug/l": ("мкг/л", "ug/l", "μg/l")})
    assert "μg/l" not in whole["mg/l"], "a Latin m for a Greek mu is a thousandfold, not a slip"
    assert "mg/l" not in whole["ug/l"]
    # And the spellings each unit really is printed with are all still there.
    assert set(whole["mg/l"]) > {"мг/л", "mg/l"} and set(whole["ug/l"]) > {"мкг/л", "ug/l", "μg/l"}


def test_the_micro_sign_and_the_greek_mu_are_one_character_to_the_fold():
    """Which is how "μg/dl" walked through the first version of that guard.

    The guard compared the spellings as written, and "µg/dl" with the micro sign is a different
    string from "μg/dl" with the mu — until a fold, which normalises one to the other, and a fold
    is the form every one of these tables is matched in. So the slip of "mg/dl" that reads as
    micrograms was refused by nothing and the table held both.
    """
    whole = with_the_one_letter_slips({"mg/dl": ("мг/дл", "mg/dl"), "ug/dl": ("мкг/дл", "µg/dl")})
    assert "μg/dl" not in whole["mg/dl"] and "µg/dl" not in whole["mg/dl"]


def test_no_two_meanings_of_a_table_end_up_claiming_one_spelling():
    """Asked of the four tables the program really builds this way, as they stand."""
    from epicrisis import dates, quotations, units

    tables = {
        "month names": dates.MONTH_STEMS,
        "words of a unit": {key: [word for word, its in units.WORDS if its == key]
                            for _word, key in units.WORDS},  # fmt: skip
        "units named inside a range": dict(units.REFERENCE_UNITS),
        "names of an analyte": units.NAMES,
    }
    for what, table in tables.items():
        claimed: dict[str, object] = {}
        for meaning, spellings in table.items():
            for spelling in spellings:
                assert claimed.setdefault(spelling, meaning) == meaning, \
                    f"{what}: {spelling!r} is both {claimed[spelling]!r} and {meaning!r}"  # fmt: skip
    assert len(set(quotations.INTRODUCED_BY)) == len(quotations.INTRODUCED_BY)


def test_the_day_and_the_month_of_a_date_are_not_lost_to_one_letter():
    """Two of the twelve Ukrainian month stems carry an і, and April is the expensive one.

    Read with that і in Latin, the day and the month were both lost and the document stood on the
    first of January — three and a half months from where April was printed — and the page showed
    a bare "2019" with no flag beside it, because a date read to the year is a date that was read.
    """
    from epicrisis.dates import read_printed_date

    for printed, wanted in (("15 квiтня 2019", "2019-04-15"), ("15 квітня 2019", "2019-04-15"),
                            ("15 сiчня 2019", "2019-01-15"), ("15 січня 2019", "2019-01-15")):  # fmt: skip
        read = read_printed_date(printed)
        assert read.value and read.value.isoformat() == wanted and read.precision == "day", printed
    # And a word that is not a month is still not a month, however it is spelled.
    assert read_printed_date("12 map 2019").precision == "year"


def test_the_unit_and_the_analyte_a_slipped_spelling_names():
    """What the three hand-patched spellings were patched for, now that none of them is written out."""
    from epicrisis.units import name_says_analyte, unit_from_reference, unit_key

    assert unit_key("мкмoль/л") == unit_key("мкмоль/л") == "umol/l"
    assert unit_from_reference("53-115 мкмoль/л") == "umol/l"
    assert unit_key("уд/xв") == unit_key("уд/хв")
    assert name_says_analyte("Креатинiн", "creatinine") and name_says_analyte("Креатинін", "creatinine")
    # And the units a slip is one letter away from keep their own key and their own scale.
    assert unit_key("мг/л") == "mg/l" and unit_key("мкг/л") == "ug/l"
    assert unit_from_reference("0,5-2,0 μg/l") == "ug/l" and unit_from_reference("0,5-2,0 mg/l") == "mg/l"


def test_a_word_that_introduces_a_date_is_one_with_a_latin_letter_in_it():
    """"вiд" stood in that list by hand. It is generated now, and so is the rest of the list."""
    from epicrisis.printed_values import fold
    from epicrisis.quotations import INTRODUCED_BY

    assert fold("вiд") in INTRODUCED_BY and fold("від") in INTRODUCED_BY
    assert fold("oт") in INTRODUCED_BY, "the Russian word with its о in Latin"
