"""A list of printed names and labels, in the order a person looks down it.

Unicode put і, ї, є and ґ, and the Russian ё, in a block of their own after the thirty-two letters
the two alphabets share, so ordered by what the code points happen to be — or by a casefold, which
does not move them — every one of those letters sorts below я. A person looking for a surname on
«І» looked where it belongs and found it at the very bottom of the list, under every Russian name
there was, and the lists this happened on are the ones they go to in order to find a name: the
doctors and institutions of the archive, the spellings a joined name stands for, the labels of
every test.

Every name and label here is invented, in meaningless syllables, and was looked for in each
archive's index before it was written down.
"""

import sqlite3

import pytest

from epicrisis import people, query
from epicrisis.index.build import SCHEMA
from epicrisis.printed_values import in_name_order

#: One invented surname per letter that fell below я, with the letters they now stand beside, and
#: one name in each of the other two alphabets this archive is written in.
A_LATIN_NAME = "Zurmelo"
A_GREEK_NAME = "Κβαρπέλο"
JUMBLED = ["Яшмірель", "Ґормелю", "Іврамель", "Авмурель", "Ёрбуміль", "Їлмарен",
           "Євтамель", "Гавтелю", "Ермабіль", "Ивмарель"]  # fmt: skip
BY_THE_LETTERS_THEY_BEGIN_WITH = [
    "Авмурель", "Гавтелю", "Ґормелю", "Євтамель", "Ёрбуміль",
    "Ермабіль", "Ивмарель", "Іврамель", "Їлмарен", "Яшмірель",
]  # fmt: skip


def test_a_letter_of_one_alphabet_no_longer_sorts_below_every_letter_of_another():
    """ґ beside г, є and ё beside е, і and ї beside и — and я last, where я belongs."""
    assert sorted(JUMBLED, key=in_name_order) == BY_THE_LETTERS_THEY_BEGIN_WITH


def test_what_a_casefold_did_with_the_same_ten_names():
    """Five of the ten under every name beginning with я, which is the bottom of the list, and the
    five are one alphabet's own letters. This is the defect, kept where it can be read."""
    assert sorted(JUMBLED, key=str.casefold)[-5:] == [
        "Ёрбуміль", "Євтамель", "Іврамель", "Їлмарен", "Ґормелю"]


def test_the_three_alphabets_of_one_list_each_keep_their_own_run():
    """Latin, then Greek, then Cyrillic. That is the blocks' own order and not a claim about any
    language — what matters is that it is the same order every time and that no letter of one
    alphabet is scattered through the middle of another."""
    mixed = ["Яшмірель", A_GREEK_NAME, A_LATIN_NAME, "Авмурель"]
    assert sorted(mixed, key=in_name_order) == [A_LATIN_NAME, A_GREEK_NAME, "Авмурель", "Яшмірель"]


@pytest.mark.parametrize(("one", "other"), [
    # The fold pairs letters; it does not sort by anybody's alphabet, and these are the places
    # where the two differ. They are written down so that nobody reads more into this order than
    # it gives. і, ї and й all land among the и, so a run of them is in no Ukrainian order inside
    # itself — Ukrainian puts і and ї after з and й after и.
    ("Іврамель", "Ивмарель"), ("Їлмарен", "Ивмарель"), ("Йовмарель", "Ивмарель"),
    # ы and э land among и and е rather than near the end, where Russian puts them.
    ("Ырмавель", "Ивмарель"), ("Эрмавель", "Ермабіль"),
    # And the soft sign is dropped, so two names differing only by one fall together entirely.
    ("Ольмарен", "Олмарен"),
])  # fmt: skip
def test_what_this_order_folds_together_and_does_not_sort(one, other):
    assert in_name_order(one)[0] == in_name_order(other)[0]


def test_the_spellings_a_joined_name_stands_for_read_in_order(data_dir):
    """The page shows them in the order they are held in, so they are held in that order — on the
    way into the file, on the way back out of it, and when something asks what a label stands for.
    A file written before this holds the order the code points gave it, and the page showing it is
    the page where somebody is looking for one of those spellings."""
    jumbled = ["Яшмірель А.Б.", "Іврамель В.Г.", "Ґормелю Д.Е.", "Авмурель Ж.З."]
    in_order = ["Авмурель Ж.З.", "Гавтелю И.К.", "Ґормелю Д.Е.", "Іврамель В.Г.", "Яшмірель А.Б."]
    after = people.join(data_dir, "a_source", "doctor",
                        [*jumbled, "Гавтелю И.К."], "Авмурель Ж.З.")  # fmt: skip

    assert people.settled(after, "doctor")[0].names == in_order
    assert people.names_under(after, "doctor", "Авмурель Ж.З.") == in_order
    # And read back from the file, which is where the page gets them.
    assert people.load(data_dir, "a_source")[0].names == in_order


def an_index(doctors: tuple[str, ...] = (), tests: tuple[tuple[str, str], ...] = ()):
    """An index holding nothing but what these two orderings are asked about."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    connection.execute("INSERT INTO files (sha256, file_id, source_id, path) VALUES ('f', 'f', 's', 'a.pdf')")
    for number, doctor in enumerate(doctors, start=1):
        connection.execute(
            "INSERT INTO documents (id, source_id, file_sha256, doctor, date, primary_copy) "
            "VALUES (?, 's', 'f', ?, ?, 1)", (number, doctor, f"20{number:02d}-01-01"))  # fmt: skip
    for number, (indicator_id, label) in enumerate(tests, start=1):
        connection.execute("INSERT INTO indicators (id, label, status, names) VALUES (?, ?, 'approved', '[]')",
                           (indicator_id, label))  # fmt: skip
        connection.execute(
            "INSERT INTO documents (id, source_id, file_sha256, date, primary_copy) "
            "VALUES (?, 's', 'f', ?, 1)", (100 + number, f"20{number:02d}-02-02"))  # fmt: skip
        connection.execute(
            "INSERT INTO observations (document_id, kind, name, value, value_numeric, value_role, "
            "derived, indicator_id) VALUES (?, 'observation', ?, '1', 1.0, 'result', 0, ?)",
            (100 + number, label, indicator_id))  # fmt: skip
    return connection


def test_the_doctors_of_an_archive_read_in_order():
    """The list a person goes to in order to find who wrote what. Ordered by bare code points
    before this, a doctor on «І» stood under every doctor on «Я»."""
    connection = an_index(doctors=("Яшмірель А.Б.", "Іврамель В.Г.", "Ґормелю Д.Е.", "Авмурель Ж.З."))

    assert [one["name"] for one in query.who_made_them(connection)] == [
        "Авмурель Ж.З.", "Ґормелю Д.Е.", "Іврамель В.Г.", "Яшмірель А.Б."]
    connection.close()


def test_the_tests_measured_as_often_as_each_other_read_in_order():
    """The timeline puts the commonest first and breaks the tie by the label, and a label
    beginning with one of the five letters went below every label beginning with я."""
    connection = an_index(tests=(("one", "Яшмірелін"), ("two", "Іврамелін"),
                                 ("three", "Ґормелін"), ("four", "Авмурелін")))  # fmt: skip

    assert [one["label"] for one in query.indicator_timeline(connection)] == [
        "Авмурелін", "Ґормелін", "Іврамелін", "Яшмірелін"]
    connection.close()
