"""Doctors and institutions: printed names grouped under one label, and never by a program.

Everything here is invented, including the surnames. One of them was not, once: a name believed to
be made up stood in a docstring and in four other files for three days, and what found it was the
guard being taught to ask the archive for its doctors. A name in a test of this project is checked
against the archive before it is written, not after.
"""

import pytest
import json

from fastapi.testclient import TestClient

from epicrisis import people
from epicrisis.people_proposals import names_to_ask_about, propose_people
from epicrisis.web.app import create_app
from test_ask import archive_index  # noqa: F401
from test_extract import FakeExtractBackend, setup  # noqa: F401


class FakeProposals:
    """Something shaped like a model, answering what it was told to answer."""

    def __init__(self, groups):
        self.groups, self.seen = groups, []

    def group(self, kind, names, workdir):
        self.seen.append((kind, names))
        return {"groups": self.groups.get(kind, [])}


MINE = "aaaa1111"  # the archive these tests are about; the store now asks whose it is

MAKERS = [
    {"name": "Нетудихата І.В", "what": "doctor", "documents": 42, "spellings": {"Нетудихата І.В"},
     "first_date": "2019-01-01", "last_date": "2024-01-01"},
    {"name": "Уролог Нетудихата І.В", "what": "doctor", "documents": 7, "spellings": {"Уролог Нетудихата І.В"},
     "first_date": "2021-01-01", "last_date": "2023-01-01"},
    {"name": "Кривопишин В.Г", "what": "doctor", "documents": 11, "spellings": {"Кривопишин В.Г"},
     "first_date": "2020-01-01", "last_date": "2020-01-01"},
    {"name": "Kryvopyshyn V.H", "what": "doctor", "documents": 2, "spellings": {"Kryvopyshyn V.H"},
     "first_date": "2022-01-01", "last_date": "2022-01-01"},
    {"name": "Міська клінічна лікарня №7", "what": "institution", "documents": 30, "spellings": set(),
     "first_date": "2019-01-01", "last_date": "2024-01-01"},
    {"name": "МКЛ №7", "what": "institution", "documents": 4, "spellings": set(),
     "first_date": "2020-01-01", "last_date": "2021-01-01"},
]  # fmt: skip


def test_a_proposal_answers_nothing_until_a_person_agrees_with_it(tmp_path):
    """The whole point of the file. A model's sentence must change no answer the archive gives.

    Written because the easy mistake is a one-line one: a reader that walks the stored groups
    instead of the settled ones, and the cut of the archive by doctor silently answers for
    spellings a model guessed at and nobody read.
    """
    people.propose(tmp_path, MINE, "doctor", ["Кривопишин В.Г", "Kryvopyshyn V.H"], "Кривопишин В.Г",
                   why="the same surname and initials, transliterated")  # fmt: skip
    stored = people.load(tmp_path, MINE)

    assert len(stored) == 1 and not stored[0].settled
    assert people.settled(stored) == [] and len(people.waiting(stored)) == 1
    # Asked anything, the archive answers exactly as it did before the proposal was written.
    assert people.names_under(stored, "doctor", "Кривопишин В.Г") == ["Кривопишин В.Г"]
    assert people.label_of(stored, "doctor", "Kryvopyshyn V.H") == "Kryvopyshyn V.H"

    people.join(tmp_path, MINE, "doctor", ["Кривопишин В.Г", "Kryvopyshyn V.H"], "Кривопишин В.Г")
    settled = people.load(tmp_path, MINE)

    assert len(settled) == 1 and settled[0].settled  # the proposal became the group, not a second one
    assert people.names_under(settled, "doctor", "Кривопишин В.Г") == ["Kryvopyshyn V.H", "Кривопишин В.Г"]
    assert people.label_of(settled, "doctor", "Kryvopyshyn V.H") == "Кривопишин В.Г"


def test_a_proposal_is_not_quietly_settled_by_a_join_beside_it(tmp_path):
    """Joining two names must not drag in a third a model guessed at.

    A proposal holding one of the names being joined is dropped, not absorbed: its question has
    been answered by hand. If the third spelling still looks alike, the next run offers it alone.
    """
    people.propose(tmp_path, MINE, "doctor", ["Нетудихата І.В", "Уролог Нетудихата І.В", "Кривопишин В.Г"],
                   "Нетудихата І.В", why="one surname, a speciality in front")  # fmt: skip
    people.join(tmp_path, MINE, "doctor", ["Нетудихата І.В", "Уролог Нетудихата І.В"], "Нетудихата І.В")
    stored = people.load(tmp_path, MINE)

    assert len(stored) == 1 and stored[0].settled
    assert stored[0].names == ["Нетудихата І.В", "Уролог Нетудихата І.В"]  # and not the third
    assert people.label_of(stored, "doctor", "Кривопишин В.Г") == "Кривопишин В.Г"


def test_declining_answers_one_proposal_and_touches_nothing_else(tmp_path):
    """A refusal used to be forgotten. It is remembered now, and the reason for the change — the
    file moved inside the archive and already held unsettled groups, so it needs no second file —
    is written at decline(). What this test holds is that saying no to one question answers that
    one and leaves every other question, and every name, exactly where it was."""
    people.propose(tmp_path, MINE, "doctor", ["Кривопишин В.Г", "Kryvopyshyn V.H"], "Кривопишин В.Г", why="transliterated")
    people.propose(tmp_path, MINE, "institution", ["Міська клінічна лікарня №7", "МКЛ №7"], "Міська клінічна лікарня №7",
                   why="the abbreviation of the same name")  # fmt: skip

    people.decline(tmp_path, MINE, "doctor", ["Kryvopyshyn V.H", "Кривопишин В.Г"])
    left = people.load(tmp_path, MINE)

    assert [one.kind for one in people.waiting(left)] == ["institution"]  # the other is untouched
    assert [one.kind for one in people.refused(left)] == ["doctor"]
    assert people.settled(left) == []  # saying no joins nothing, as saying nothing joined nothing
    assert people.label_of(left, "doctor", "Kryvopyshyn V.H") == "Kryvopyshyn V.H"
    # And a proposal nobody has settled is never offered a second time.
    people.propose(tmp_path, MINE, "institution", ["МКЛ №7", "Міська клінічна лікарня №7"], "МКЛ №7", why="again")
    assert len(people.waiting(people.load(tmp_path, MINE))) == 1


def test_one_name_typed_twice_is_counted_and_never_paid_for(tmp_path):
    """The same words in the same order, printed differently, need no model and never did.

    Found by reading the page: the one group a model proposed on a real archive was a surname with
    and without a full stop after the second initial, and it explained, correctly and for money,
    that this was "a punctuation artifact of the form rather than a different person". The word
    count had thrown that pair away — equal sets of words looked like a name compared with itself.

    The order is what keeps it safe. Two names made of the same words in a different order are two
    people as often as they are one typing slip, and those are left alone.
    """
    pairs = people.worth_joining("doctor", ["Загуменна О.П", "Загуменна О.П.", "Петров А.Б", "Петров Б.А"])

    assert ("Загуменна О.П", "Загуменна О.П.") in pairs
    assert not any({"Петров А.Б", "Петров Б.А"} == {one, other} for one, other in pairs)
    # One pair, not two: the same question asked twice is the same question.
    assert len([pair for pair in pairs if "Загуменна" in pair[0]]) == 1


def test_an_apostrophe_is_taken_out_of_a_name_and_never_split_on():
    """Two wrong answers out of one character, and they pointed opposite ways.

    Found by reading the splitting: `the_words_in` cut a name on `[^\\w]+`, and an apostrophe is
    not a word character. Measured on invented names, before the fix:

        "Аб'ва О.П." -> ('аб', 'ва', 'о', 'п')      'Абьва О.П.' -> ('абва', 'о', 'п')

    so the two spellings of one surname were never offered as one — and the fold drops the ь for
    the single purpose of catching exactly that, because Ukrainian prints an apostrophe where
    Russian prints the soft sign.

    The other way round, "Д'Абва" -> ('д', 'абва') is two words, which passes LEAST_WORDS. That
    guard is there so that one word is never offered as a name, and with it passed a one-word
    institution was offered as the same place as a building lettered Д — a claim about identity,
    counted and not asked.
    """
    assert people.the_words_in("Аб'ва О.П.") == people.the_words_in("Абьва О.П.")
    assert ("Аб'ва О.П.", "Абьва О.П.") in people.worth_joining("doctor", ["Аб'ва О.П.", "Абьва О.П."])
    # Every shape a form, a keyboard or an export prints for it, including the acute accent typed
    # where the apostrophe key is missing and the modifier letter, which `\w` counts as a letter
    # and which therefore never split anything — it left a spelling that matched nothing at all.
    for shape in ("'", "’", "ʼ", "´", "′", "`"):
        assert people.the_words_in(f"Аб{shape}ва О.П.") == ("абва", "о", "п"), shape

    # And the one-word name stays one word, so nothing offers it as somebody's building.
    assert people.the_words_in("Д'Абва") == ("дабва",)
    assert people.worth_joining("institution", ["Д'Абва", "Лабораторія Абва, корпус Д"]) == []


def test_a_hyphen_still_splits_a_name_and_what_that_bought_and_cost():
    """The split stays; what it used to cost no longer reaches a person's name.

    A simple surname comes out a strict subset of a double one — "Гдеж І.В." inside
    "Гдеж-Абва І.В." — so counting offered them as one name, and that is an assertion that two
    people are one. Not splitting the hyphen would have closed it, and that was measured before it
    was refused: on the three archives on this machine, binding a hyphen into its word takes seven
    pairs away and adds none, and all seven are one compound printed with a hyphen on one form and
    with a space on another. The same false pair was offered for a double surname carrying no
    hyphen at all, which no rule about hyphens could have reached — which is why the answer was
    not a rule about hyphens. worth_joining asks a doctor's name a narrower question instead: the
    pair is offered where the name ends the longer string, and a hyphen in the middle of it never
    does.

    So this test holds the two halves apart. What the split buys is an institution's compound
    spelled both ways, and that must keep working. What it used to cost is asserted the other way
    round now, so that it cannot be traded back by accident.
    """
    doctors = {frozenset(pair) for pair in people.worth_joining(
        "doctor", ["Гдеж І.В.", "Гдеж-Абва І.В.", "Абьва О.П.", "Ортопед-Травматолог Абьва О.П.",
                   "Abva O.P.", "Abva Gdezh O.P."])}  # fmt: skip
    places = {frozenset(pair) for pair in people.worth_joining(
        "institution", ["Лабораторія Абва-Гдеж", "Лабораторія Абва Гдеж"])}

    # What the split buys, on both kinds: a speciality in front of a name, and one compound
    # spelled with a hyphen on one form and with a space on another.
    assert frozenset({"Абьва О.П.", "Ортопед-Травматолог Абьва О.П."}) in doctors
    assert frozenset({"Лабораторія Абва-Гдеж", "Лабораторія Абва Гдеж"}) in places
    # And what it cost: a surname inside a double surname is no longer put to anybody, with the
    # hyphen or without it. Neither spelling says which of the two it is, and neither does a page.
    assert frozenset({"Гдеж І.В.", "Гдеж-Абва І.В."}) not in doctors
    assert frozenset({"Abva O.P.", "Abva Gdezh O.P."}) not in doctors


def test_a_model_is_asked_only_what_counting_cannot_answer(tmp_path):
    """A pair the word count already offers is free and instant; asking about it spends limits."""
    groups = people.load(tmp_path, MINE)
    asking = [one["name"] for one in names_to_ask_about(MAKERS, "doctor", groups)]

    # "Нетудихата І.В" stands inside "Уролог Нетудихата І.В": the word count offers that pair itself.
    assert "Нетудихата І.В" not in asking and "Уролог Нетудихата І.В" not in asking
    assert sorted(asking) == ["Kryvopyshyn V.H", "Кривопишин В.Г"]

    people.join(tmp_path, MINE, "doctor", ["Кривопишин В.Г", "Kryvopyshyn V.H"], "Кривопишин В.Г")
    assert names_to_ask_about(MAKERS, "doctor", people.load(tmp_path, MINE)) == []


def test_what_a_model_says_is_written_down_and_nothing_more(tmp_path):
    """The commonest spelling carries the group, counted here; the model only says which are one."""
    backend = FakeProposals({
        "doctor": [{"names": ["Kryvopyshyn V.H", "Кривопишин В.Г"], "why": "the same surname and initials, transliterated"},
                   {"names": ["Нежуренко Г.П"], "why": "alone"},
                   {"names": ["Somebody Nobody Sent", "Kryvopyshyn V.H"], "why": "invented"}],
        "institution": [{"names": ["МКЛ №7", "Міська клінічна лікарня №7"], "why": "the abbreviation of the same name"}],
    })  # fmt: skip
    counts = propose_people(tmp_path, MINE, MAKERS, backend, tmp_path)
    stored = people.load(tmp_path, MINE)

    assert counts == {"asked": 4, "proposed": 2, "left_out": 0, "calls": 2}
    assert [one.settled for one in stored] == [False, False]  # nothing applied, however it was worded
    doctor = next(one for one in stored if one.kind == "doctor")
    # The commonest spelling, by documents, and not the one the model happened to write first.
    assert doctor.label == "Кривопишин В.Г" and doctor.why.startswith("the same surname")
    assert doctor.names == ["Kryvopyshyn V.H", "Кривопишин В.Г"]
    place = next(one for one in stored if one.kind == "institution")
    # In the order a person reads a list in: і stands with и, which is before к, so the name in
    # full comes before its abbreviation. Ordered by code points it did not — і sorts below every
    # letter of the alphabet it shares, so "Міська" stood under "МКЛ".
    assert place.label == "Міська клінічна лікарня №7"
    assert place.names == ["Міська клінічна лікарня №7", "МКЛ №7"]
    # A group of one is not a group, and a name nobody sent is not a name: both are left alone,
    # and the second is the one that matters — a model may not add a person to somebody's archive.
    assert not any("Somebody Nobody Sent" in one.names for one in stored)
    assert not any("Нежуренко Г.П" in one.names for one in stored)
    # The doctors and the places are asked about separately: one list, one set of rules.
    assert [kind for kind, _names in backend.seen] == ["doctor", "institution"]
    assert "Kryvopyshyn V.H | 2" in backend.seen[0][1]


def test_the_page_shows_what_a_model_thought_and_why_without_joining_it(archive_index):  # noqa: F811
    """A person is being asked to say that two human beings are one. They get the reason, and a no."""
    import sqlite3

    from epicrisis.index.build import index_path

    data_dir, source, _labs = archive_index
    with sqlite3.connect(index_path(data_dir, source.id)) as connection:
        connection.execute("UPDATE documents SET provider = 'Synthetic Laboratory', doctor = 'Кривопишин В.Г'")
        connection.commit()
    people.propose(data_dir, source.id, "doctor", ["Кривопишин В.Г", "Kryvopyshyn V.H"], "Кривопишин В.Г",
                   why="the same surname and initials, transliterated")  # fmt: skip

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = client.get("/who")

    assert "A model thinks these are one" in page.text
    assert "the same surname and initials, transliterated" in page.text
    assert "Nothing below is joined" in page.text
    assert "Joined by you" not in page.text  # it is offered, not done

    # And the timeline still answers for the one spelling the documents print, not for both.
    one_spelling = client.get("/", params={"doctor": "Кривопишин В.Г"})
    the_other = client.get("/", params={"doctor": "Kryvopyshyn V.H"})
    assert one_spelling.text.count("/documents/") > the_other.text.count("/documents/")

    said_no = client.post(f"/who/{source.id}/decline", data={"kind": "doctor",
                                                "names": ["Кривопишин В.Г", "Kryvopyshyn V.H"]},
                          follow_redirects=True)  # fmt: skip
    assert "A model thinks these are one" not in said_no.text
    assert "You said these are not the same" in said_no.text
    # Remembered as refused rather than forgotten, and joining nothing either way: the names still
    # stand for themselves, and no page and no model offers that pair again until he asks for it.
    left = people.load(data_dir, source.id)
    assert people.settled(left) == [] and people.waiting(left) == []
    assert [one.names for one in people.refused(left)] == [["Kryvopyshyn V.H", "Кривопишин В.Г"]]


def test_a_group_of_several_names_is_joined_in_one_press(archive_index):  # noqa: F811
    """A model's group may hold three spellings; the button says the same thing for all of them."""
    data_dir, source, _labs = archive_index
    people.propose(data_dir, source.id, "institution", ["МКЛ №7", "Міська клінічна лікарня №7", "MKL No 7"],
                   "Міська клінічна лікарня №7", why="an abbreviation and a transliteration of one name")  # fmt: skip

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    joined = client.post(f"/who/{source.id}/join", data={"kind": "institution", "label": "Міська клінічна лікарня №7",
                                            "names": ["МКЛ №7", "Міська клінічна лікарня №7", "MKL No 7"]},
                         follow_redirects=True)  # fmt: skip

    assert joined.status_code == 200
    stored = people.load(data_dir, source.id)
    assert len(stored) == 1 and stored[0].settled
    # Latin first, then the Ukrainian name in full, then its abbreviation: і stands with и now
    # rather than below every letter of its own alphabet.
    assert stored[0].names == ["MKL No 7", "Міська клінічна лікарня №7", "МКЛ №7"]
    assert people.names_under(stored, "institution", "Міська клінічна лікарня №7") == stored[0].names


def test_a_laboratory_written_five_ways_is_one_question_and_not_ten():
    """The owner opened the institutions of his own archive and read it as the joining not working.

    One laboratory there writes itself as its own name, its name with the software, the software
    with a version, the version with a point release, and a branch with a city. Offered as pairs
    that was ten rows about one laboratory, and pressing any of them left the other nine standing.
    A pair saying A and B are one, and B and C are one, has already said all three are one.
    """
    names = ["Invented Medical Lab",
             "Invented Medical Lab, Analyser",
             "Invented Medical Lab, Analyser Ver 2.8",
             "Invented Medical Lab, Analyser Ver 2.8.1",
             "Invented Medical Lab, Branch No 001 Kyiv",
             "Something Else Entirely"]

    assert len(people.worth_joining("institution", names)) > 4  # the pairs inside one family, as before
    found = people.families("institution", names)

    assert len(found) == 1
    assert found[0] == sorted(names[:5], key=lambda one: (len(one), one))
    # The shortest leads, because a version, a branch and a city are what a form adds to a name.
    assert found[0][0] == "Invented Medical Lab"
    # And a name that belongs to nobody's family is not dragged into one.
    assert "Something Else Entirely" not in found[0]


def test_a_family_is_joined_by_one_press_under_the_spelling_a_person_chose(archive_index):  # noqa: F811
    """Which of five spellings is the name is a question only the person reading them can answer."""
    data_dir, source, _labs = archive_index
    family = ["Invented Medical Lab", "Invented Medical Lab, Analyser", "Invented Medical Lab, Analyser Ver 2.8"]

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    joined = client.post(f"/who/{source.id}/join", data={"kind": "institution", "names": family,
                                            "label": "Invented Medical Lab, Analyser"},
                         follow_redirects=True)  # fmt: skip

    assert joined.status_code == 200
    stored = people.load(data_dir, source.id)
    assert len(stored) == 1 and stored[0].settled
    assert stored[0].names == sorted(family)
    assert stored[0].label == "Invented Medical Lab, Analyser"  # theirs, not the shortest
    assert people.names_under(stored, "institution", "Invented Medical Lab, Analyser") == sorted(family)


def test_a_torn_file_is_never_written_over_and_never_silently_emptied(tmp_path):
    """One press of Join over a torn file used to take every group a person had settled.

    Found by a survey of this project for decisions taken in more than one place. Every writer
    here is load, change, save; load answered an empty list for a file it could not read, on the
    reasoning that what this file holds is a view and the archive is whole without it. That
    reasoning is wrong in the way that costs a person their afternoon — save then wrote the
    emptiness back. Measured on a torn file: two groups before, one after, and no copy kept.

    indicators.json, the same kind of work, has refused this since the day it happened to it. This
    module was written months later and did not inherit the lesson.
    """
    from epicrisis.state import Unreadable

    people.join(tmp_path, MINE, "doctor", ["Нетудихата І.В", "Уролог Нетудихата І.В"], "Нетудихата І.В")
    people.join(tmp_path, MINE, "doctor", ["Кривопишин В.Г", "Kryvopyshyn V.H"], "Кривопишин В.Г")
    assert len(people.load(tmp_path, MINE)) == 2
    # The version a write replaces is kept beside it, so there is something to copy back.
    assert people.path(tmp_path, MINE).with_name("people.json.previous").exists()

    torn = '[{"kind": "doctor", "label": "Нету'
    (people.path(tmp_path, MINE)).write_text(torn, encoding="utf-8")

    assert people.unreadable(tmp_path, MINE) is True
    for reading in (lambda: people.load(tmp_path, MINE),
                    lambda: people.join(tmp_path, MINE, "doctor", ["Загуменна О.П", "ЛОР Загуменна О.П"]),
                    lambda: people.split(tmp_path, MINE, "doctor", "Нетудихата І.В"),
                    lambda: people.propose(tmp_path, MINE, "doctor", ["Загуменна О.П", "ЛОР Загуменна О.П"]),
                    lambda: people.decline(tmp_path, MINE, "doctor", ["Загуменна О.П", "ЛОР Загуменна О.П"])):  # fmt: skip
        with pytest.raises(Unreadable):
            reading()
    # And none of them touched it: what the person settled is still in the file to be repaired.
    assert (people.path(tmp_path, MINE)).read_text(encoding="utf-8") == torn


def test_the_page_says_which_file_will_not_read_instead_of_falling_over(archive_index):  # noqa: F811
    """Turning a silent loss into a crash would be the other half of the same mistake."""
    data_dir, source, _labs = archive_index
    people.join(data_dir, source.id, "doctor", ["Нетудихата І.В", "Уролог Нетудихата І.В"], "Нетудихата І.В")
    (people.path(data_dir, source.id)).write_text('[{"kind": "doc', encoding="utf-8")

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050",
                        raise_server_exceptions=False)  # fmt: skip
    page = client.get("/who")

    assert "Internal Server Error" not in page.text
    assert "people.json" in page.text
    assert "still in that file" in page.text  # what is safe
    assert "people.json.previous" in page.text  # and what puts it right


def test_the_file_lives_inside_the_archive_it_is_about(tmp_path):
    """The wall, as a fact about where bytes are rather than as a filter somebody must remember.

    It sat beside the instance for one day, and on that day a page read it without asking whose it
    was: one person saw another's doctors, and a label chosen in one archive renamed a clinic on
    another's documents. A file one archive cannot open is a file it cannot leak.
    """
    from epicrisis import sources

    people.join(tmp_path, "aaaa1111", "doctor", ["Нетудихата І.В", "Уролог Нетудихата І.В"])
    people.join(tmp_path, "bbbb2222", "doctor", ["Загуменна О.П", "ЛОР Загуменна О.П"])

    assert people.path(tmp_path, "aaaa1111").parent == sources.source_output_dir(tmp_path, "aaaa1111")
    assert not (tmp_path / "people.json").exists()  # nothing beside the instance any more
    # And neither archive can see the other's, because it is asking a different folder.
    assert [one.label for one in people.load(tmp_path, "aaaa1111")] == ["Нетудихата І.В"]
    assert [one.label for one in people.load(tmp_path, "bbbb2222")] == ["Загуменна О.П"]


def test_the_old_file_beside_the_instance_is_carried_in_and_not_read_where_it_lies(tmp_path):
    """Anybody who ran the version of that one day has such a file, and it holds work nothing
    else makes again. It is carried into the archives that print those names, never read from
    where it lies — reading it from there is exactly how the leak happened.
    """
    import sqlite3

    from epicrisis.index.build import SCHEMA, index_path

    for which, printed in (("aaaa1111", "Нетудихата І.В"), ("bbbb2222", "Загуменна О.П")):
        index = sqlite3.connect(index_path(tmp_path, which))
        with index:
            index.executescript(SCHEMA)
            index.execute("INSERT INTO documents (source_id, doctor) VALUES (?, ?)", (which, printed))
        index.close()
    (tmp_path / "people.json").write_text(json.dumps([
        {"kind": "doctor", "label": "Нетудихата І.В", "names": ["Нетудихата І.В", "Уролог Нетудихата І.В"]},
        {"kind": "doctor", "label": "Загуменна О.П", "names": ["Загуменна О.П", "ЛОР Загуменна О.П"]},
    ], ensure_ascii=False), encoding="utf-8")  # fmt: skip

    carried = people.carry_the_old_file_in(tmp_path)

    assert carried == {"aaaa1111": 1, "bbbb2222": 1}
    assert [one.label for one in people.load(tmp_path, "aaaa1111")] == ["Нетудихата І.В"]
    assert [one.label for one in people.load(tmp_path, "bbbb2222")] == ["Загуменна О.П"]
    # Every group found a home, so the old file is put aside rather than left to be read again.
    assert not (tmp_path / "people.json").exists()
    assert (tmp_path / "people.json.carried-into-the-archives").exists()
    # And a second run changes nothing.
    assert people.carry_the_old_file_in(tmp_path) == {}


def test_a_group_naming_nobody_here_keeps_the_old_file_where_it_is(tmp_path):
    """Losing a person's own work to a migration is the failure this module exists for."""
    import sqlite3

    from epicrisis.index.build import SCHEMA, index_path

    index = sqlite3.connect(index_path(tmp_path, "aaaa1111"))
    with index:
        index.executescript(SCHEMA)
        index.execute("INSERT INTO documents (source_id, doctor) VALUES (?, ?)", ("aaaa1111", "Нетудихата І.В"))
    index.close()
    (tmp_path / "people.json").write_text(json.dumps([
        {"kind": "doctor", "label": "Нетудихата І.В", "names": ["Нетудихата І.В", "Уролог Нетудихата І.В"]},
        {"kind": "doctor", "label": "Хтось Інший", "names": ["Хтось Інший", "Лікар Хтось Інший"]},
    ], ensure_ascii=False), encoding="utf-8")  # fmt: skip

    people.carry_the_old_file_in(tmp_path)

    assert [one.label for one in people.load(tmp_path, "aaaa1111")] == ["Нетудихата І.В"]
    assert (tmp_path / "people.json").exists()  # the group nobody here names is not thrown away


def _an_archive_naming(tmp_path, source_id: str, doctor: str) -> None:
    import sqlite3

    from epicrisis.index.build import SCHEMA, index_path

    index = sqlite3.connect(index_path(tmp_path, source_id))
    with index:
        index.executescript(SCHEMA)
        index.execute("INSERT INTO documents (source_id, doctor) VALUES (?, ?)", (source_id, doctor))
    index.close()


def test_an_archive_with_a_file_of_its_own_does_not_make_the_old_one_claim_to_be_empty(tmp_path):
    """Found by running it on copies of the demo, and the third case was the bad one.

    The group was counted as having found a home *before* the check for a people.json already in
    that archive, so an archive that had one of its own had its share of the old file written
    nowhere — while the old file was renamed as though all of it had been carried in. Every byte
    was still there; the name of the file said the opposite of what had happened, and nothing else
    pointed at those groups any more.

    A person reaches this without doing anything strange: restoring `data/people.json` from an old
    copy into an instance that has moved on, or a migration that stopped last time on an index it
    could not open while they went on pressing Join.
    """
    _an_archive_naming(tmp_path, "aaaa1111", "Нетудихата І.В")
    _an_archive_naming(tmp_path, "bbbb2222", "Загуменна О.П")
    # The second archive has a file of its own already, holding a different decision.
    people.join(tmp_path, "bbbb2222", "doctor", ["Загуменна О.П", "Загуменна О.П."], "Загуменна О.П")
    (tmp_path / "people.json").write_text(json.dumps([
        {"kind": "doctor", "label": "Нетудихата І.В", "names": ["Нетудихата І.В", "Уролог Нетудихата І.В"]},
        {"kind": "doctor", "label": "Загуменна О.П", "names": ["Загуменна О.П", "ЛОР Загуменна О.П"]},
    ], ensure_ascii=False), encoding="utf-8")  # fmt: skip

    carried = people.carry_the_old_file_in(tmp_path)

    assert carried == {"aaaa1111": 1}
    # The group whose archive already had a file is in no archive, so the old file stays where it
    # is and says so by being there. It used to be renamed .carried-into-the-archives.
    assert (tmp_path / "people.json").exists()
    assert not (tmp_path / "people.json.carried-into-the-archives").exists()
    assert people.still_beside_the_instance(tmp_path) == 2
    # And the archive's own work is untouched by the attempt: §8.
    assert [one.names for one in people.load(tmp_path, "bbbb2222")] == [sorted(["Загуменна О.П", "Загуменна О.П."])]


def test_a_second_run_of_the_migration_still_puts_the_old_file_aside(tmp_path):
    """The other side of asking rather than assuming: a group that really is in the archive it
    belongs to has found its home, whichever run put it there, so this does not become a file
    that is carried for ever."""
    _an_archive_naming(tmp_path, "aaaa1111", "Нетудихата І.В")
    written = json.dumps([{"kind": "doctor", "label": "Нетудихата І.В",
                           "names": ["Нетудихата І.В", "Уролог Нетудихата І.В"]}], ensure_ascii=False)  # fmt: skip
    (tmp_path / "people.json").write_text(written, encoding="utf-8")

    assert people.carry_the_old_file_in(tmp_path) == {"aaaa1111": 1}
    assert not (tmp_path / "people.json").exists()
    assert people.still_beside_the_instance(tmp_path) == 0
    # Put back by hand, as somebody restoring an old copy would: the archive now holds it already.
    (tmp_path / "people.json").write_text(written, encoding="utf-8")

    assert people.carry_the_old_file_in(tmp_path) == {}  # nothing to write; it is already there
    assert not (tmp_path / "people.json").exists()  # and still put aside rather than kept for ever


def test_the_command_carries_the_old_file_in_and_says_what_is_still_waiting(tmp_path):
    """The docstring promised "by the page and by the command line" and no command called it.

    A person who restored data/people.json from an old copy and ran `epicrisis people` was told
    "0 joined by you" while their own work sat in a file beside the instance, and nothing — no
    page, no command, no line of the README — said a word about the move. §7.
    """
    from typer.testing import CliRunner

    from epicrisis.cli import app as cli_app

    _an_archive_naming(tmp_path, "aaaa1111", "Нетудихата І.В")
    (tmp_path / "sources.json").write_text(json.dumps([
        {"id": "aaaa1111", "name": "an archive", "path": str(tmp_path / "scans"), "owner": "Zoryana Vdovychenko",
         "added_at": "2026-01-01T00:00:00+00:00", "active": True}]), encoding="utf-8")  # fmt: skip
    (tmp_path / "people.json").write_text(json.dumps([
        {"kind": "doctor", "label": "Нетудихата І.В", "names": ["Нетудихата І.В", "Уролог Нетудихата І.В"]},
        {"kind": "doctor", "label": "Хтось Інший", "names": ["Хтось Інший", "Лікар Хтось Інший"]},
    ], ensure_ascii=False), encoding="utf-8")  # fmt: skip

    said = CliRunner().invoke(cli_app, ["people", "--data-dir", str(tmp_path)])

    assert said.exit_code == 0, said.output
    assert "Carried 1 group(s)" in said.output and "aaaa1111" in said.output
    assert "1 joined by you" in said.output  # and not "0 joined by you" over the top of it
    # The group naming nobody this server has an index for is left where it is, and said out loud.
    assert "still stands beside this instance" in said.output and "people.json" in said.output
    assert [one.label for one in people.load(tmp_path, "aaaa1111")] == ["Нетудихата І.В"]


def test_the_status_page_names_the_file_a_migration_could_not_empty(tmp_path):
    """`curl /status | grep -c people.json` answered 0 while a person's own work waited there."""
    _an_archive_naming(tmp_path, "aaaa1111", "Нетудихата І.В")
    (tmp_path / "people.json").write_text(json.dumps([
        {"kind": "doctor", "label": "Хтось Інший", "names": ["Хтось Інший", "Лікар Хтось Інший"]},
    ], ensure_ascii=False), encoding="utf-8")  # fmt: skip

    client = TestClient(create_app(tmp_path, background_jobs=False), base_url="http://localhost:8050")
    page = client.get("/status")

    assert "people.json" in page.text
    assert "holding 1 group of doctors and clinics somebody joined by hand" in page.text
    assert "has not been carried anywhere" in page.text  # why it is still there
    assert "nothing makes it again" in page.text  # and what not to do about it
    # And it says nothing at all on an instance that never had the old file, which is every one
    # made since it moved.
    (tmp_path / "people.json").unlink()
    assert "groups of doctors and clinics somebody joined by hand" not in client.get("/status").text
    assert "group of doctors and clinics somebody joined by hand" not in client.get("/status").text


FAMILY = ["Invented Medical Lab", "Invented Medical Lab, Analyser", "Invented Medical Lab, Branch No 001 Kyiv"]


def _printed_by(data_dir, source_id, providers: list[str]) -> None:
    """Put one invented institution on each document of the archive, so a family has something
    to be a family of. Every one of them already stood in this file, so none is a name this change had to invent."""
    import sqlite3

    from epicrisis.index.build import index_path

    with sqlite3.connect(index_path(data_dir, source_id)) as connection:
        rows = [row[0] for row in connection.execute("SELECT rowid FROM documents ORDER BY rowid")]
        for row, provider in zip(rows, providers, strict=False):
            connection.execute("UPDATE documents SET provider = ?, primary_copy = 1 WHERE rowid = ?",
                               (provider, row))  # fmt: skip
        connection.commit()


def _signed_by(data_dir, source_id, doctors: list[str]) -> None:
    """The same, for the doctor field: the two tabs are offered on two different rules, so a test
    about what each of them says needs a family on each. Both names already stood in this file."""
    import sqlite3

    from epicrisis.index.build import index_path

    with sqlite3.connect(index_path(data_dir, source_id)) as connection:
        rows = [row[0] for row in connection.execute("SELECT rowid FROM documents ORDER BY rowid")]
        for row, doctor in zip(rows, doctors, strict=False):
            connection.execute("UPDATE documents SET doctor = ?, primary_copy = 1 WHERE rowid = ?",
                               (doctor, row))  # fmt: skip
        connection.commit()


def test_a_family_comes_as_tick_boxes_and_one_of_them_can_be_left_out(archive_index):  # noqa: F811
    """The owner's decision, and the refusal of §1 it is there to make possible.

    A family used to come as one button over hidden fields. Where one of five spellings is in
    fact another laboratory, that left a person two moves and both were bad: press it, and a name
    that is somebody else's is joined to the four that are right and the documents under it are
    renamed — which is the failure of the first line of the constitution, and it has happened, on
    thirty-four documents — or leave it, and the row stands on the page for ever.

    So: every spelling ticked, untick the one that does not belong, join the rest. And what was
    unticked is offered again, which is the half of this that is easy to get wrong — the page
    skipped any family touching a settled name, so the spelling left out stood beside the group
    just made and was never asked about again.
    """
    data_dir, source, _labs = archive_index
    _printed_by(data_dir, source.id, FAMILY)
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    page = client.get("/who", params={"kind": "institution"})

    assert "spellings that look like one name" in page.text
    for name in FAMILY:
        assert f'type="checkbox" name="names" value="{name}" checked' in page.text, name
    assert 'type="hidden" name="names"' not in page.text  # no family is a press over the whole of it
    # And the picker says out loud what it keeps when nobody touches it.
    assert "keep the shortest of the ones ticked" in page.text

    joined = client.post(f"/who/{source.id}/join", data={"kind": "institution", "label": "",
                                            "names": FAMILY[:2]}, follow_redirects=True)  # fmt: skip

    assert joined.status_code == 200
    stored = people.load(data_dir, source.id)
    assert len(stored) == 1 and stored[0].names == sorted(FAMILY[:2])
    assert stored[0].label == FAMILY[0]  # the shortest of the ones ticked, as the picker said
    # The one left out is not lost: it is offered again, beside the group just made, so that a
    # person who unticked it by mistake — or who looks again and decides it does belong — can say so.
    again = client.get("/who", params={"kind": "institution"})
    assert f'name="names" value="{FAMILY[2]}" checked' in again.text
    # And joining it now takes the settled group in with it rather than making a second one.
    client.post(f"/who/{source.id}/join", data={"kind": "institution", "names": [FAMILY[0], FAMILY[2]]},
                follow_redirects=True)  # fmt: skip
    after = people.load(data_dir, source.id)
    assert len(after) == 1 and after[0].names == sorted(FAMILY)


def test_the_page_says_the_one_shape_the_counting_cannot_tell_apart(archive_index):  # noqa: F811
    """A family is offered when one name stands inside another, and that is not an identity.

    The two tabs are offered on two different rules, so each says its own sentence, and the only
    thing worse than warning in general is warning about something the page no longer does.

    An institution: every word of one name standing in the other, which is what a laboratory does
    to its own name — the software, a version, a point release, a branch, a city. A different place
    of a similar name reads the same way to the counting, and what makes it visible is that the
    forms print the branch and the city beside the name, so the longest spelling of a family is the
    one to read twice. That is §4's third condition, which this shape does not get for free.

    A doctor: only a speciality or a title printed in front of the name. The shape where a name
    grows at its end is refused in the counting and never reaches the page, so the sentence says
    that rather than asking a reader to catch something they cannot catch.
    """
    data_dir, source, _labs = archive_index
    _printed_by(data_dir, source.id, FAMILY)
    # And a doctor written two ways, so the other tab has a family to say its own sentence over.
    _signed_by(data_dir, source.id, ["Абьва О.П.", "Ортопед-Травматолог Абьва О.П."])
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    said = " ".join(client.get("/who", params={"kind": "institution"}).text.split())

    assert "spellings that look like one name" in said  # there is a family on the page to warn about
    assert "A name that stands inside another is not the same name." in said
    # And it names the shape rather than warning in general, because a warning nobody can act on
    # is the same as none: the longest spelling of the family is the one to read twice.
    assert "version of the software" in said and "untick it if it is somewhere else" in said
    # The other tab says what it refuses, and does not ask the reader to watch for it.
    about_doctors = " ".join(client.get("/who", params={"kind": "doctor"}).text.split())
    assert "A name that stands inside another is not the same name." in about_doctors
    assert "is never put to you" in about_doctors
    assert "untick it if it is somewhere else" not in about_doctors


def test_a_family_said_no_to_is_not_offered_again_and_the_no_can_be_taken_back(archive_index):  # noqa: F811
    """The circle the page could not leave, both halves of it.

    A counted family had no "not these" at all, and separating a group put the family straight
    back into the list on the next draw — the filter that hid a settled family had nothing left
    to hide by. So a person who had looked at three spellings and decided they were two
    laboratories had no way of saying so that outlived one page. §7: a dead end with no way out
    is a defect, and so is a way out that leads back to the same door.

    The refusal is remembered in the file that already holds the groups nobody has settled, which
    is why the reason the old docstring gave for not remembering it — a second file and a second
    question — is written out of it. And it is taken back by hand, because a refusal nothing could
    undo is the same dead end turned round, and a worse one: the spellings stand in the list below
    as the forms print them, with nothing down there to join them by.
    """
    data_dir, source, _labs = archive_index
    _printed_by(data_dir, source.id, FAMILY)
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    assert "spellings that look like one name" in client.get("/who?kind=institution").text
    said_no = client.post(f"/who/{source.id}/decline", data={"kind": "institution", "names": FAMILY},
                          follow_redirects=True)  # fmt: skip

    assert said_no.status_code == 200
    assert "spellings that look like one name" not in said_no.text  # and not on the next draw either
    assert "You said these are not the same" in said_no.text
    stored = people.load(data_dir, source.id)
    assert people.refused(stored, "institution") and not people.waiting(stored)
    assert people.settled(stored) == []  # a refusal joins nothing and answers nothing
    # Nothing of what the forms print changed: every spelling still stands for itself.
    for name in FAMILY:
        assert people.label_of(stored, "institution", name) == name
    # Nor does a model get asked about it again, which is the same answer costing money twice.
    people.propose(data_dir, source.id, "institution", FAMILY, FAMILY[0], why="asked again")
    assert people.waiting(people.load(data_dir, source.id)) == []

    again = client.post(f"/who/{source.id}/reconsider", data={"kind": "institution", "names": FAMILY},
                        follow_redirects=True)  # fmt: skip

    assert "You said these are not the same" not in again.text
    assert "spellings that look like one name" in again.text  # the question is back on the page
    assert people.refused(people.load(data_dir, source.id)) == []


def test_separating_a_group_does_not_put_the_same_question_back_for_ever(archive_index):  # noqa: F811
    """The loop as it was met: join, separate, and the family is offered again on every draw.

    That is right the first time — separating is "I was wrong", and the question is open again.
    It is a dead end only because there was nothing to answer it with except joining, and the
    one thing a person who separated a group most likely wants to say is "these are not one".
    """
    data_dir, source, _labs = archive_index
    _printed_by(data_dir, source.id, FAMILY)
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    client.post(f"/who/{source.id}/join", data={"kind": "institution", "names": FAMILY}, follow_redirects=True)
    separated = client.post(f"/who/{source.id}/split", data={"kind": "institution", "label": FAMILY[0]},
                            follow_redirects=True)  # fmt: skip

    assert "Joined by you" not in separated.text
    assert "spellings that look like one name" in separated.text  # offered again, as it should be
    # And now there is a way out of the loop: the same button the model's groups always had.
    done = client.post(f"/who/{source.id}/decline", data={"kind": "institution", "names": FAMILY},
                       follow_redirects=True)  # fmt: skip
    assert "spellings that look like one name" not in done.text
    assert "You said these are not the same" in done.text


def test_a_join_of_something_it_does_not_understand_is_never_answered_in_silence(tmp_path):
    """The signature behind a test that could not fail, kept here so it cannot come back.

    join() took (data_dir, source_id, kind, names, label) and answered a kind it did not know by
    returning the file unchanged, saying nothing. A fixture in test_the_wall_between_people.py
    left the argument out, so it wrote no file at all — and the test guarding the first line of
    the constitution went on to assert that a label which had never been created was not on
    somebody else's page. It passed every time, and it could not have failed.

    The three refusals are not one thing. A kind nobody can mean is a mistake in the program and
    raises plainly; one spelling and a label that is none of the ticked spellings are a person
    pressing a button, and they come back with the sentence the page shows them.
    """
    with pytest.raises(ValueError):
        people.join(tmp_path, MINE, "", ["Нетудихата І.В", "Уролог Нетудихата І.В"])
    with pytest.raises(people.NotAJoin) as alone:
        people.join(tmp_path, MINE, "doctor", ["Нетудихата І.В"])
    assert alone.value.said and alone.value.mend  # what happened, and what puts it right
    with pytest.raises(people.NotAJoin):
        people.join(tmp_path, MINE, "doctor", ["Нетудихата І.В", ""])  # an empty box is not a name
    # And none of the three wrote anything: there is no file where there were no groups.
    assert not people.path(tmp_path, MINE).exists()

    people.join(tmp_path, MINE, "doctor", ["Нетудихата І.В", "Уролог Нетудихата І.В"], "Нетудихата І.В")
    before = people.path(tmp_path, MINE).read_text(encoding="utf-8")
    # A label that is none of the spellings being joined is refused whole, not quietly swapped:
    # a label standing over names it is not one of is how a label chosen in one place renamed a
    # clinic on thirty-four documents somewhere else.
    with pytest.raises(people.NotAJoin):
        people.join(tmp_path, MINE, "institution", ["МКЛ №7", "Міська клінічна лікарня №7"], "Нетудихата І.В")
    assert people.path(tmp_path, MINE).read_text(encoding="utf-8") == before


def test_the_page_says_that_one_spelling_ticked_joined_nothing(archive_index):  # noqa: F811
    """A press that does nothing and says nothing reads as a press that worked. §7."""
    data_dir, source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    one_only = client.post(f"/who/{source.id}/join", data={"kind": "institution", "names": ["Invented Medical Lab"]},
                           follow_redirects=True)  # fmt: skip

    assert one_only.status_code == 200
    assert "not a join" in one_only.text
    assert "Nothing was changed" in one_only.text
    assert "Tick at least two" in one_only.text  # and what puts it right
    assert people.load(data_dir, source.id) == []

    # The spelling to keep, unticked. The join is refused rather than relabelled in silence.
    unticked = client.post(f"/who/{source.id}/join", data={"kind": "institution",
                                              "names": ["Invented Medical Lab", "Invented Medical Lab, Analyser"],
                                              "label": "Invented Medical Lab, Analyser Ver 2.8"},
                           follow_redirects=True)  # fmt: skip

    assert "not one of the spellings being joined" in unticked.text
    assert people.load(data_dir, source.id) == []
    # And the sentence is in this server's memory, not in the address: a link that carried the
    # words would let anything able to open a page put words on the owner's own page.
    assert "not one of the spellings" not in str(unticked.url)


def test_a_press_for_another_archive_is_a_page_saying_so_and_not_a_write(archive_index, tmp_path):  # noqa: F811
    """The four presses of this page name the archive they were made about, and are checked.

    The wall between two people is held by test_the_wall_between_people.py; this is the other
    half of the same change — what a person meets when their press does arrive at the wrong
    moment. A silent 404, or a redirect to a page that quietly did nothing, is the defect §7
    names: they are standing in front of a page that worked a minute ago, and the cause is
    ordinary — they switched the archive in another tab.
    """
    from epicrisis.sources import SourceRegistry

    data_dir, source, _labs = archive_index
    _printed_by(data_dir, source.id, FAMILY)
    registry = SourceRegistry(data_dir)
    elsewhere = (tmp_path / "another-archive")
    elsewhere.mkdir()
    other = registry.add(str(elsewhere), "Dovbushenko Myrosya")
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    joined = client.post(f"/who/{source.id}/join",
                         data={"kind": "institution", "names": FAMILY, "label": FAMILY[0]},
                         follow_redirects=True)  # fmt: skip
    assert joined.status_code == 200  # while that archive is the one open, the press lands
    assert [one.names for one in people.load(data_dir, source.id)] == [sorted(FAMILY)]

    registry.set_active(other.id)
    for press in ("join", "decline", "reconsider", "split"):
        refused = client.post(f"/who/{source.id}/{press}",
                              data={"kind": "institution", "names": FAMILY, "label": FAMILY[0]})  # fmt: skip
        assert refused.status_code == 404, press
        assert "nothing was changed" in refused.text, press
        assert "before the archive was switched" in refused.text, press  # the cause, not a bare 404
        assert 'href="/who?kind=institution"' in refused.text, press  # and the way back
    # And the file of the archive that was not open is exactly as the four presses of its own
    # page left it: nothing of the archive now open reached it, and nothing of it was undone.
    assert [one.names for one in people.load(data_dir, source.id)] == [sorted(FAMILY)]
    assert people.load(data_dir, other.id) == []


def test_two_people_joining_names_at_once_never_undo_each_other(tmp_path, monkeypatch):
    """Reproduced by running it, which is how the finding was made rather than read off the code.

    `editing()` was written for exactly this and nothing in the program called it: every writer
    here went load, change, save with no lock, and the window between the load and the save is a
    window in which another writer's whole file disappears. Two threads joining names in one
    archive, with the read slowed to a quarter of a second, left one group in people.json, the
    other in people.json.previous, no people.lock anywhere, and no error at all.

    What is asserted is not "both writers won" — the lock refuses rather than queues — but that
    **nothing was lost in silence**: every writer either wrote, and its group is in the file, or
    was told Busy and knows that it did not. Without the lock both threads report success and one
    of the two groups is gone, which is the assertion that fails.

    The two are staggered rather than started together, and the waits are what makes this a test
    and not a coin toss: the second writer begins after the first has read, and writes after the
    first has written. Without a lock that order loses the first join every time; started at the
    same instant it loses it about half the time, which is a coin toss and not a test.

    It used to go on to say that the other half of those coin tosses tripped over the lock itself,
    which was created and filled as two acts — a reader in between found an empty file and took it
    over. That one was in runs.py, under the indicators as much as under this, and it is closed:
    the lock is linked into place whole, and
    tests/test_runs.py::test_two_runs_starting_together_never_both_hold_the_lock is what holds it
    closed. The stagger here stays, because it is what keeps this test about losing a join rather
    than about which thread got there first.
    """
    import threading
    import time

    from epicrisis.runs import Busy

    unlocked = people.load
    # Each writer's own window between its read and its write, by name: the first reads early and
    # writes early, the second reads early and writes late, so without a lock the second's write
    # is built on what it read before the first wrote, and puts that back.
    windows = {"first": 0.1, "second": 0.3}

    def slowly(data_dir, source_id):
        groups = unlocked(data_dir, source_id)
        time.sleep(windows[threading.current_thread().name])
        return groups

    monkeypatch.setattr(people, "load", slowly)
    pairs = {"first": ("Нетудихата І.В", ["Нетудихата І.В", "Уролог Нетудихата І.В"]),
             "second": ("Загуменна О.П", ["Загуменна О.П", "ЛОР Загуменна О.П"])}  # fmt: skip
    wrote, told = [], []

    def joining(which):
        label, names = pairs[which]
        try:
            people.join(tmp_path, MINE, "doctor", names, label)
            wrote.append(label)
        except Busy:
            told.append(label)

    threads = [threading.Thread(target=joining, args=(which,), name=which) for which in pairs]
    threads[0].start()
    time.sleep(0.05)  # long enough for the first to hold the lock and to have read the file
    threads[1].start()
    for thread in threads:
        thread.join()

    assert len(wrote) + len(told) == 2  # neither thread failed in some other way
    stored = {one.label for one in unlocked(tmp_path, MINE)}
    assert set(wrote) <= stored, (wrote, stored)  # what a writer was told it wrote is in the file
    assert not (set(told) & stored)  # and what it was told it did not write is not there
    assert not people.path(tmp_path, MINE).with_name("people.lock").exists()  # taken off after
