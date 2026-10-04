"""An eye examination's one line, and the two things that go wrong when it is split.

Every line here is invented. They are built to the shapes an ophthalmic form really prints — the
whole refraction on one line, the measurement named inside the line, two alphabets in one word —
with numbers that belong to nobody and could not be anybody's prescription.
"""

import pytest

from epicrisis.eyes import measurements_named, several_measurements_in_one, the_eye_alone
from epicrisis.rules.subjects import Document
from epicrisis.validate import named_after_the_eye, several_measurements_in_one_value

#: The two shapes the whole thing was found on, with invented numbers.
A_WHOLE_REFRACTION = "Vis OD = 0.99 із  sph -9.75 cyl -9,0Д ax 99=0,9"
THE_SAME_IN_UKRAINIAN = "ОС сф.-9.5 ціл.-9.0 ах 99"
#: The same line as a Spanish and a Greek form print it. Neither named one measurement of a
#: refraction before the words of those two languages were written down: every number stayed
#: named by an eye and nothing else, and the field holding three of them was reported by nobody.
THE_SAME_IN_SPANISH = "OD esf -9.75 cil -9.00 eje 99"
THE_SAME_IN_GREEK = "ΔΟ σφ -9.75 κυλ -9.00 άξονας 99"


@pytest.mark.parametrize(("name", "eye"), [
    ("OD", "the right eye"), ("OS", "the left eye"), ("OU", "both eyes"),
    ("ОД", "the right eye"), ("ОС", "the left eye"), ("ОУ", "both eyes"),
    # As a form prints it: a full stop, a colon, spacing, lower case.
    ("ОС.", "the left eye"), ("OD:", "the right eye"), (" os ", "the left eye"),
    # One Cyrillic letter and one Latin one in the same word. Nothing on the page tells them
    # apart, so a reading comes back with either, and a list of two tidy spellings would miss it.
    ("ОD", "the right eye"), ("oС", "the left eye"),
    # The pair that was missing, and it is the one pair of the set that no eye can tell apart:
    # the Cyrillic с had a Latin s standing for it and the Latin c had nothing standing for it,
    # so «ОС» — the left eye, as a Russian or Ukrainian form prints it — was the left eye when
    # the transcription came back Cyrillic and was no eye at all when it came back Latin.
    ("OC", "the left eye"), ("ОC", "the left eye"), ("oc", "the left eye"),
    # And the other two letters of the same kind: a Latin y for the Cyrillic у, and the Greek
    # omicron, which a form printed in Greek has in front of both of them.
    ("OY", "both eyes"), ("ΟD", "the right eye"), ("ΟС", "the left eye"), ("ΟC", "the left eye"),
])  # fmt: skip
def test_a_name_that_is_nothing_but_an_eye(name, eye):
    assert the_eye_alone(name) == eye


@pytest.mark.parametrize("name", [
    # The thirty-eight that are named properly: Vis is the measurement, the eye qualifies it.
    "Vis OD", "Vis OS", "VIS OU", "sph OD", "ОС сф.",
    # A name that holds anything more than the eye is saying something more than the eye.
    "OD 1", "ОСТ", "Осмолярність", "OS right eye", "", None,
    # The soft sign, which this module keeps out of the general fold for exactly this: «ось» is
    # the axis and an ordinary Ukrainian word, and it is «ос» with one letter more.
    "ось", "ОСь",
    # Two eyes named together are not one eye, whichever alphabet either of them came back in.
    "ОД/ОС", "OD/OC",
    # Greek omicron now stands for the O, and «ου» is an ordinary Greek word — so the second
    # letter of a key stays the Latin u, the Cyrillic у and the Latin y, and never the upsilon.
    "ου",
])  # fmt: skip
def test_a_name_that_says_more_than_the_eye_is_not_this(name):
    assert the_eye_alone(name) is None


def test_which_measurements_a_printed_line_names():
    """In the order the line names them, which is the order a person reads it in."""
    assert measurements_named(A_WHOLE_REFRACTION) == ["visual acuity", "sphere", "cylinder", "axis"]
    assert measurements_named(THE_SAME_IN_UKRAINIAN) == ["sphere", "cylinder", "axis"]
    # Named twice is named once: one line carrying the sphere of both eyes names one measurement.
    assert measurements_named("OD sph -9.0  OS sph -9.5") == ["sphere"]


def test_a_spanish_and_a_greek_form_name_their_measurements_too():
    """Two of the five languages named nothing at all, which is two archives' worth of silence."""
    assert measurements_named(THE_SAME_IN_SPANISH) == ["sphere", "cylinder", "axis"]
    assert measurements_named(THE_SAME_IN_GREEK) == ["sphere", "cylinder", "axis"]
    # The words in full, as a form with room on the line prints them.
    assert measurements_named("OD esfera -9.75 cilindro -9.00 eje 99") == ["sphere", "cylinder", "axis"]
    assert measurements_named("OD σφαίρα -9.75 κύλινδρος -9.00 άξων 99") == ["sphere", "cylinder", "axis"]
    # Named twice is named once in Spanish as well, and the second eye of a Spanish form is OI.
    assert measurements_named("OD esf -9.0  OI esf -9.5") == ["sphere"]


def test_a_greek_word_is_the_same_word_in_capitals():
    """A Greek form prints its headings in capitals, and capitals lose the accent — while a
    casefold turns the final sigma into the medial one, so the written word would meet neither.
    Two of the three words of this line are different strings in capitals from in lower case."""
    assert measurements_named("ΔΟ ΣΦ -9.75 ΚΥΛ -9.00 ΑΞΟΝΑΣ 99") == ["sphere", "cylinder", "axis"]


@pytest.mark.parametrize("line", [
    # An ordinary word of the language on its own. «ось» is "here" in Ukrainian and «ах» is an
    # interjection, and a value named «ОС» on a form that has nothing to do with eyes would be
    # reported for ever on the strength of one of them.
    "ось 9 днів тому", "ах, вже 9 разів",
    # A spelling inside another word. "ax" is in "max" and in "axial", "sph" is in "sphincter",
    # "ціл" is in "цілий".
    "max 99 mm", "axial 99 mm", "sphincter 9 mm", "цілий 9 раз",
    # A word with no number behind it labels nothing.
    "sph cyl ax", "сф. ціл. ах",
    # The axis of the other two languages is an ordinary word of them too, and the form that
    # proves it is one this archive holds: an electrocardiogram prints the axis of the heart
    # with a number beside it, and has nothing whatever to do with a refraction.
    "eje eléctrico 99º", "άξονας 99 μοίρες",
    # A spelling of those two inside another word, which is the same trap as "max" and "цілий".
    "esfínter 9 mm", "facilitar 9 días", "ejemplo 9 veces",
    # And an ordinary line of an ordinary form, which is almost every line there is.
    "Глюкоза 9.9 ммоль/л (3,9-9,9)", "", None,
])  # fmt: skip
def test_a_line_that_names_no_measurement(line):
    assert measurements_named(line) == []


def test_an_ordinary_word_is_read_in_the_company_of_a_measurement():
    """«ось» is the axis on a line that is plainly about eyes, and nothing anywhere else."""
    assert measurements_named("сф.-9.5 ось 99") == ["sphere", "axis"]


def test_a_word_is_credited_only_with_the_number_it_stands_beside():
    """The stretch between one word and the next is what that word labels, and no further."""
    assert measurements_named("sph cyl -9,0") == ["cylinder"]
    assert measurements_named("sph -9.75 cyl") == ["sphere"]


def test_several_measurements_in_one_stored_value():
    """The nineteen that no renaming can mend: a whole refraction in the field of one number."""
    assert several_measurements_in_one("sph -9.75 cyl -9,0Д ax") == ["sphere", "cylinder"]
    assert several_measurements_in_one("сф.-9.5 ціл.-9.0 ах 99") == ["sphere", "cylinder", "axis"]
    # The same field on a Spanish and on a Greek form, where it was reported by nobody at all.
    assert several_measurements_in_one("esf -9.75 cil -9.00 eje 99") == ["sphere", "cylinder", "axis"]
    assert several_measurements_in_one("σφ -9.75 κυλ -9.00 άξονας 99") == ["sphere", "cylinder", "axis"]
    # One measurement is one value, however it is written, and an ordinary number is neither.
    assert several_measurements_in_one("sph -9.75") == []
    assert several_measurements_in_one("0,9") == []
    assert several_measurements_in_one(None) == []


def value(name: str, printed: str, snippet: str) -> dict:
    return {"name_as_printed": name, "value_as_printed": printed,
            "provenance": {"page": 1, "snippet": snippet}}  # fmt: skip


def document(*values: dict) -> Document:
    return Document(file_sha256="a" * 64, pages=(1,), item={"observations": list(values)})


def test_the_eye_rule_says_which_measurement_the_line_names():
    """So that a person can put the name right in one read, without opening the scan."""
    found = named_after_the_eye(document(value("ОС", "-9.5", THE_SAME_IN_UKRAINIAN)), {})
    assert len(found) == 1 and found[0].first_page == 1
    assert "the left eye" in found[0].line
    assert "sphere, cylinder, axis" in found[0].line


def test_a_value_already_named_by_its_measurement_is_left_alone():
    """A name of Vis and the eye is the right name on this line, and thirty-eight values on one
    archive were in that state. A rule reporting them would be reporting correct work."""
    assert named_after_the_eye(document(value("Vis OD", "0.99", A_WHOLE_REFRACTION)), {}) == []


def test_a_form_that_has_nothing_to_do_with_eyes_is_left_alone():
    """«ОС» is an abbreviation elsewhere too, and its line is what tells the difference."""
    assert named_after_the_eye(document(value("ОС", "9,9", "ОС 9,9 ммоль/л  (3,9-9,9)")), {}) == []


def test_the_eye_rule_is_silent_where_renaming_cannot_fix_it():
    """A field holding a whole refraction has no right name, so asking for one is asking for the
    wrong work. The other rule has it, and says what it really needs."""
    glued = document(value("ОС", "сф.-9.5 ціл.-9.0 ах 99", THE_SAME_IN_UKRAINIAN))
    assert named_after_the_eye(glued, {}) == []
    found = several_measurements_in_one_value(glued, {})
    assert len(found) == 1 and "read again" in found[0].line
    assert "sphere, cylinder, axis" in found[0].line


def test_the_two_rules_reach_a_spanish_and_a_greek_form():
    """What the silence cost: the eye rule said nothing and the other rule said nothing either,
    so a Spanish or a Greek refraction was invisible to both at once."""
    named = named_after_the_eye(document(value("OD", "-9.75", THE_SAME_IN_SPANISH)), {})
    assert len(named) == 1 and "sphere, cylinder, axis" in named[0].line
    glued = document(value("OD", "σφ -9.75 κυλ -9.00 άξονας 99", THE_SAME_IN_GREEK))
    assert named_after_the_eye(glued, {}) == []
    found = several_measurements_in_one_value(glued, {})
    assert len(found) == 1 and "sphere, cylinder, axis" in found[0].line


def test_an_ordinary_value_is_reported_by_neither():
    """Every other line of every other form in the archive, which is what both rules must ignore."""
    ordinary = document(value("Глюкоза", "9,9", "Глюкоза 9,9 ммоль/л  (3,9-9,9)"))
    assert named_after_the_eye(ordinary, {}) == [] and several_measurements_in_one_value(ordinary, {}) == []


def test_both_rules_are_shipped_and_cost_nothing():
    """A rule file nobody ships is a rule nobody can switch on, and a finding at the extract step
    would mean reading documents again with a model. Both of these read what is already stored."""
    from epicrisis import rules

    shipped = rules.load()
    assert not shipped.problems
    for rule_id in ("named_after_the_eye", "several_measurements_in_one_value"):
        rule = shipped.get(rule_id)
        assert rule is not None and rule.does == "marks" and rule.at == "validate"
        assert rule.attaches == "value" and rule.settles and rule.check.looks_at == "one document"
