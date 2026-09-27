"""Every shape of printed text the readers must understand, from tests/printed-shapes.json.

The file beside this one says why it exists. In short: the readers of printed text were always
measured against the live archive, and that measurement cannot see a shape the archive does not
hold yet. Four times in one day a reader was broken over such a shape and both rulers reported no
movement, correctly, because on this archive there was none.

A shape marked with a finding is one the program reads wrongly today. It is expected to fail, and
strictly: the day it starts passing, this suite fails until somebody clears the marker and says in
the commit which finding was closed. A list of known defects that nobody has to look at again is
not a list of known defects.
"""

import json
from pathlib import Path

import pytest

SHAPES = json.loads((Path(__file__).parent / "printed-shapes.json").read_text(encoding="utf-8"))


def named(section: str) -> list:
    """One pytest parameter per shape, carrying its own marker and a readable id."""
    made = []
    for shape in SHAPES[section]:
        marks = []
        if shape.get("finding"):
            marks.append(pytest.mark.xfail(strict=True, reason=f"known: {shape['finding']} — {shape['why']}"))
        made.append(pytest.param(shape, marks=marks, id=f"{shape.get('finding', 'ok')}:{shape['why'][:44]}"))
    return made


@pytest.mark.parametrize("shape", named("ranges"))
def test_a_printed_range_is_read_as_the_form_meant_it(shape):
    from epicrisis.reference import parse

    expected = tuple(shape["expect"]) if shape["expect"] is not None else None
    assert parse(shape["text"]) == expected


@pytest.mark.parametrize("shape", named("units_named_inside_a_range"))
def test_the_unit_named_inside_a_printed_range_is_read(shape):
    from epicrisis.units import unit_from_reference

    assert unit_from_reference(shape["text"]) == shape["expect"]


@pytest.mark.parametrize("shape", named("unit_keys"))
def test_one_unit_written_many_ways_comes_to_one_key(shape):
    from epicrisis.units import unit_key

    assert unit_key(shape["text"]) == shape["expect"]


@pytest.mark.parametrize("shape", named("printed_numbers"))
def test_every_number_a_printed_token_can_mean(shape):
    """What the token could be, and nothing it could not.

    A number is refused where this set holds more than one: the value stands as printed, is drawn
    nowhere and compared with nothing, which is what to do with something that cannot be read and
    is not a thousand out. So a reading too many costs a value, and a reading too few is a value a
    thousand out with nothing to raise a doubt — the comma had the second kind.
    """
    from epicrisis.printed_values import readings

    assert sorted(readings(shape["text"])) == sorted(shape["expect"])


@pytest.mark.parametrize("shape", named("reads_two_ways"))
def test_a_printed_range_that_reads_at_two_scales_is_known_to(shape):
    from epicrisis.reference import reads_two_ways

    assert reads_two_ways(shape["text"]) is shape["expect"]


@pytest.mark.parametrize("shape", named("dates"))
def test_a_printed_date_is_read_as_the_form_meant_it(shape):
    from epicrisis.dates import read_printed_date

    read = read_printed_date(shape["text"])
    assert read.value is not None and read.value.isoformat() == shape["expect"]


def test_every_shape_says_what_it_is_for():
    """A shape nobody can read is a shape nobody will maintain."""
    for section, shapes in SHAPES.items():
        if section == "about":
            continue
        for shape in shapes:
            assert shape.get("why"), f"{section}: {shape['text']!r} has no reason written beside it"


@pytest.mark.parametrize("shape", named("tokens_of_a_printed_value"))
def test_the_numbers_a_printed_value_is_cut_into(shape):
    """Where a printed value is cut into numbers, and the silence when it is cut wrongly.

    `readings` answers for one token; this is the step before it, and the whole of the check that a
    stored number is the number on the page hangs on it: more than one token means "nothing to
    compare", and the check passes whatever was stored. A value cut in two therefore switches its
    own check off without saying anything — which is exactly what happened to four decimals after a
    comma, on the half of this archive that prints them.
    """
    from epicrisis.printed_values import number_tokens

    assert number_tokens(shape["text"]) == shape["expect"]


@pytest.mark.parametrize("shape", named("comparators"))
def test_a_comparator_word_is_one_whoever_reads_it(shape):
    """A word a form prints before a number, in five languages and in capitals.

    Two readers ask this question — the check that a stored comparator was really printed, and the
    check for letters a value has no business carrying — and while they asked separately, a Greek
    word in capitals was a comparator to neither, though `reference.parse` read the same string
    correctly. That is two false findings on every such value.
    """
    from epicrisis.printed_values import comparator_printed, unexplained_letters

    assert comparator_printed(shape["text"]) is shape["expect"]
    if shape["expect"]:
        assert not unexplained_letters(shape["text"]), "a comparator word is not an unexplained letter"


@pytest.mark.parametrize("shape", named("dates_of_birth"))
def test_a_printed_date_of_birth_is_known_for_one(shape):
    """The label before a date of birth, which is never the date of a document.

    Matched against a merely lower-cased text it could not work in Greek at all: a casefold turns
    the final ς into σ, so the literal could never meet itself, and capitals lose their accents on
    top of that. The date of birth then passed for the date of the document, in silence, on every
    Greek form.
    """
    from epicrisis.dates import birth_dates

    found = birth_dates(shape["text"])
    assert found and found[0].value.isoformat() == shape["expect"]
