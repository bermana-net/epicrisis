"""A name standing inside another name is not the same name, and for a person it never was.

`worth_joining` offered a pair whenever every word of one printed name stood in the other. That is
right for a laboratory, which writes itself as its own name, its name with the software, the
software with a version, the version with a point release, the branch and the city. It is wrong
for a person, because a person's name is made longer by adding to the name — another initial, a
patronymic written out, a second surname — and two doctors of one surname and one initial work in
two clinics of every city.

§4 is the governing entry and it is not symmetrical. A page may put a pair in front of somebody
and let them answer; what it may not do is put one there that they have no way of weighing. No
document anywhere says whether two "Петров А.Б." are one person, so the mistake cannot be caught
by reading the screen — and a row that looks obviously like one person, offered to somebody who
cannot know, is the program manufacturing a wrong answer with their hand on it.

So the two kinds are asked different questions: for a doctor the shorter name must be the run of
words the longer one ends with, which is a speciality or a title printed in front of the name; for
an institution the subset stays. Measured over the three archives on this machine: all 19 of the
doctor pairs they offer are the shape kept here, so the narrowing costs none of them, and 62 of
the 86 institution pairs are words added behind the name, so the same narrowing there would take
away nearly three-quarters of what the page offers. Not one archive here holds the shape this
refuses, which is why every shape below is invented — the sixth entry says an archive is blind to
what it does not happen to contain.

Every name here is invented and was looked for in all three live indexes across provider, doctor,
title, department, value names, headings, printed values, sections, pages, diagnoses, medications
and the indicator vocabulary, and found in none of them.
"""

import pytest

from epicrisis import people

#: One invented surname with one initial, and the second initial that makes it a different person.
#: These two are never a pair either way — neither is a subset of the other — and they are here to
#: say what the third name below is standing in for.
ONE_DOCTOR = "Абва О.П"
ANOTHER_DOCTOR_OF_THE_SAME_SURNAME = "Абва О.В"

#: The three shapes a person cannot answer, each of which was offered before this.
ONE_INITIAL_SHORT = ("Абва О", "Абва О.П")
THE_PATRONYMIC_WRITTEN_OUT = ("Абва Вмурель", "Абва Вмурель Жмиренович")
A_SURNAME_INSIDE_A_DOUBLE_ONE = ("Гдеж І.В", "Гдеж-Абва І.В")

#: And the shape the counting is for, which a person can weigh: the word in front is not a name.
A_SPECIALITY_IN_FRONT = ("Абва О.П", "Уролог Абва О.П")
A_TITLE_AND_A_SPECIALITY_IN_FRONT = ("Абва О.П", "Лікар-уролог Абва О.П")


def offered(kind: str, pair: tuple[str, str]) -> bool:
    return pair in people.worth_joining(kind, list(pair))


@pytest.mark.parametrize("pair", [ONE_INITIAL_SHORT, THE_PATRONYMIC_WRITTEN_OUT,
                                  A_SURNAME_INSIDE_A_DOUBLE_ONE])  # fmt: skip
def test_a_doctors_name_made_longer_by_adding_to_the_name_is_not_offered(pair):
    """Each of these was a row saying two human beings are one, counted and not asked.

    They are three different ways of adding to a name and they look the same to a word count: a
    second initial, a patronymic spelled out, a second surname behind the first. Nothing in the
    words tells any of them from a speciality welded in front of a surname, which is why the shape
    and not the words is what decides.
    """
    assert not offered("doctor", pair)


@pytest.mark.parametrize("pair", [A_SPECIALITY_IN_FRONT, A_TITLE_AND_A_SPECIALITY_IN_FRONT])
def test_a_speciality_in_front_of_a_doctors_name_is_still_offered(pair):
    """What the counting buys, and all 19 pairs the live archives offer are this shape."""
    assert offered("doctor", pair)


def test_two_doctors_of_one_surname_and_one_initial_are_never_a_pair():
    """The sentence §4 is written around, asserted so that no widening can reach it.

    Neither name stands inside the other, so nothing offers them — and that is the case this is
    all about: the shapes above are refused because they are the same claim reached sideways.
    """
    assert people.worth_joining("doctor", [ONE_DOCTOR, ANOTHER_DOCTOR_OF_THE_SAME_SURNAME]) == []
    assert people.families("doctor", [ONE_DOCTOR, ANOTHER_DOCTOR_OF_THE_SAME_SURNAME]) == []


@pytest.mark.parametrize("pair", [ONE_INITIAL_SHORT, THE_PATRONYMIC_WRITTEN_OUT,
                                  A_SURNAME_INSIDE_A_DOUBLE_ONE])  # fmt: skip
def test_the_same_shape_is_still_offered_for_an_institution(pair):
    """The asymmetry is deliberate, so it is asserted rather than left to be noticed.

    A clinic is not a person. Its forms print the branch, the city, the software and the version
    beside its name, so two labels standing side by side can be weighed by anyone reading them —
    §4's third condition, the one that does not hold for a human being's name. And the
    measurement: narrowing this would take 62 of the 86 institution pairs the three archives
    offer, which is most of the work the page does.
    """
    assert offered("institution", pair)


def test_what_the_narrowing_would_cost_an_institution_if_it_reached_them():
    """A laboratory's name grows at the end, and the run-at-the-end rule would refuse all of it.

    The measured 62 of 86, in the shape they are: the name, the software, a version, a point
    release and a branch, each one the name with words added behind it.
    """
    grown = ["Invented Medical Lab", "Invented Medical Lab, Analyser",
             "Invented Medical Lab, Analyser Ver 2.8", "Invented Medical Lab, Branch No 001 Kyiv"]  # fmt: skip
    pairs = people.worth_joining("institution", grown)

    assert len(pairs) >= 4
    # Not one of them is a run of words at the end of the longer name, which is what the doctors'
    # rule asks for — so asking it here would leave the page with nothing to offer about this
    # laboratory at all.
    assert not any(people.a_speciality_in_front(people.the_words_in(one), people.the_words_in(other))
                   for one, other in pairs)  # fmt: skip
    assert people.families("institution", grown) == [sorted(grown, key=lambda one: (len(one), one))]


def test_which_kind_of_name_it_is_has_no_default_and_an_unknown_one_raises():
    """The two kinds are asked different questions, so a caller that does not know must fail.

    Plainly and with ValueError, as NotAJoin says: an unknown kind is a mistake in the program and
    not a person pressing a button. The looser of the two rules as a default would mean a caller
    which forgot to say got a doctor's name asked an institution's question, which is the whole of
    what this file is about.
    """
    with pytest.raises(ValueError):
        people.worth_joining("someone else entirely", [ONE_DOCTOR, "Уролог Абва О.П"])
    with pytest.raises(ValueError):
        people.families("someone else entirely", [ONE_DOCTOR, "Уролог Абва О.П"])
    with pytest.raises(TypeError):
        people.worth_joining([ONE_DOCTOR, "Уролог Абва О.П"])  # type: ignore[arg-type,call-arg]


def test_a_family_of_doctors_is_closed_over_the_pairs_the_doctors_rule_offers():
    """families says only what the pairs said, so the narrowing has to reach it through them.

    One doctor written three ways — the bare name, the speciality in front, the title and the
    speciality in front — is one family and one press. A fourth name made longer by a second
    initial does not join it, and before this it did: the pair reached the family through the bare
    name, so a press meant to join three spellings of one person would have joined a fourth who
    may be somebody else.
    """
    names = ["Абва О.П", "Уролог Абва О.П", "Лікар-уролог Абва О.П", "Абва О"]

    assert people.families("doctor", names) == [["Абва О.П", "Уролог Абва О.П", "Лікар-уролог Абва О.П"]]
