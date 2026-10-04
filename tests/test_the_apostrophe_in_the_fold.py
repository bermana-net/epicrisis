"""The apostrophe is the soft sign, and the fold had been keeping the two apart.

Ukrainian prints an apostrophe where Russian prints ь. printed_values.fold drops the ь for the one
purpose of making the two alphabets' spellings of a word meet, and it kept the apostrophe — so one
surname written the Ukrainian way and the Russian way was two different strings to every search in
this program, and a person looking for their own doctor found half their documents. people.py had
known this since the day it cost a pair of names and took the apostrophe out before folding in a
table of its own, which is the shape ARCHITECTURE.md exists to prevent: two halves of one program
answering the same question about letters differently.

What the change moves beyond the letters is in this file too, because the folded form is stored.
An index keeps folded text in its `search` table and an indicator keeps the spellings a person
approved in their folded form, so a fold that changes makes both stale — and an index answering
from half-old folded rows is worse than one that refuses, because it would say nothing at all
about the rows the new fold no longer reaches and look exactly like an answer.

Every name here is invented and was looked for in all three live indexes before it was written
down — in provider, doctor, title, department, every value's name, heading and printed value,
every section and page of text, every diagnosis and medication, and the indicator vocabulary —
and found in none of them.
"""

import json
import sqlite3

import pytest

from epicrisis import indicators, people, query
from epicrisis.index.build import SCHEMA, SCHEMA_VERSION, index_path
from epicrisis.printed_values import as_a_name, fold

#: One invented surname in both alphabets' spellings, and the shapes a form, a keyboard or an
#: export prints the apostrophe in. ʼ (U+02BC) is a letter to `\w` and ´ (U+00B4) decomposes to a
#: space and a combining accent, which is why the fold takes them out before it normalises.
UKRAINIAN = "Аб'ва О.П."
RUSSIAN = "Абьва О.П."
EVERY_SHAPE = ("'", "’", "‘", "ʼ", "ʻ", "ʽ", "ˈ", "`", "´", "′")

#: An invented test, printed with an apostrophe on one form and with a soft sign on another.
A_TEST_WITH_AN_APOSTROPHE = "Квазитроф'ин"
THE_SAME_TEST_IN_THE_OTHER_ALPHABET = "Квазитрофьин"


def test_one_surname_in_two_alphabets_folds_to_one_string():
    assert fold(UKRAINIAN) == fold(RUSSIAN)
    for shape in EVERY_SHAPE:
        assert fold(f"Аб{shape}ва О.П.") == fold(RUSSIAN), shape


def test_the_names_module_asks_the_fold_instead_of_answering_a_second_time():
    """Both measurements that bought people.py's own table still hold, through the fold.

    They point opposite ways and that is why both are here: splitting on the apostrophe made
    "Аб'ва О.П." four words against three for "Абьва О.П.", so two spellings of one surname were
    never offered as one — and it made "Д'Абва" two words, which passes LEAST_WORDS, a guard that
    exists so that one word is never offered as a name.
    """
    assert people.the_words_in(UKRAINIAN) == people.the_words_in(RUSSIAN) == ("абва", "о", "п")
    assert (UKRAINIAN, RUSSIAN) in people.worth_joining("doctor", [UKRAINIAN, RUSSIAN])
    assert people.the_words_in("Д'Абва") == ("дабва",)
    assert people.worth_joining("institution", ["Д'Абва", "Лабораторія Абва, корпус Д"]) == []


def _one_document(data_dir, source_id="cccc3333", schema_version=SCHEMA_VERSION, folder=fold):
    """An archive of one document whose text was folded by the fold given.

    `folder` is how an index built by yesterday's program is written here: the folded text of its
    `search` table is what that day's fold made of the page, apostrophe and all.
    """
    index = sqlite3.connect(index_path(data_dir, source_id))
    with index:
        index.executescript(SCHEMA)
        index.executemany("INSERT INTO meta VALUES (?, ?)",
                          [("built_at", "2026-01-01T00:00:00+00:00"), ("schema_version", str(schema_version))])  # fmt: skip
        index.execute("INSERT INTO sources VALUES (?, ?)", (source_id, "An invented archive"))
        index.execute("""INSERT INTO files (sha256, file_id, source_id, path, category, page_count)
                         VALUES ('f1', 'f1', ?, 'one.pdf', 'scan', 1)""", (source_id,))
        index.execute(
            """INSERT INTO documents (id, source_id, file_sha256, first_page, pages, doc_type, language,
                                      title, provider, doctor, date, transcribed, primary_copy)
               VALUES (1, ?, 'f1', 1, '[1]', 'lab_panel', 'uk', ?, 'Лабораторія Гдеж', ?, '2011-07-09', 1, 1)""",
            (source_id, A_TEST_WITH_AN_APOSTROPHE, UKRAINIAN),
        )
        index.execute(
            """INSERT INTO observations (id, document_id, page, kind, name, value, value_role, derived)
               VALUES (1, 1, 1, 'analyte', ?, '7,77', 'result', 0)""", (A_TEST_WITH_AN_APOSTROPHE,)
        )
        page = f"{A_TEST_WITH_AN_APOSTROPHE} 7,77 кю/мл\nЛікар: {UKRAINIAN}"
        index.execute("INSERT INTO page_texts VALUES (1, 1, ?)", (page,))
        index.execute(
            "INSERT INTO search (rowid, title, provider, names, body) VALUES (1, ?, ?, ?, ?)",
            (folder(A_TEST_WITH_AN_APOSTROPHE), folder("Лабораторія Гдеж"),
             folder(A_TEST_WITH_AN_APOSTROPHE), folder(page)),
        )
    index.close()
    return source_id


@pytest.mark.parametrize("typed", [A_TEST_WITH_AN_APOSTROPHE, THE_SAME_TEST_IN_THE_OTHER_ALPHABET, "Квазитрофин"])
def test_a_search_finds_the_document_whichever_alphabet_the_name_was_typed_in(data_dir, typed):
    """The payoff, and the half of it the question side had to be fixed for.

    The index holds the folded text in one piece now that the apostrophe is gone from it, and the
    question's words were being cut out of it before it was folded — so "Квазитроф'ин" arrived at
    FTS5 as the two words "квазитроф" and "ин" and matched nothing at all. Folding first makes it
    one word, and all three spellings of the one test are one question.
    """
    source_id = _one_document(data_dir)
    with query.open_index(data_dir, source_id) as connection:
        assert [row["document_id"] for row in query.search(connection, typed)] == [1]


def test_a_doctor_is_found_by_the_other_alphabets_spelling_of_their_name(data_dir):
    source_id = _one_document(data_dir)
    with query.open_index(data_dir, source_id) as connection:
        assert [row["document_id"] for row in query.search(connection, RUSSIAN)] == [1]


@pytest.mark.parametrize("typed", [A_TEST_WITH_AN_APOSTROPHE, "Квазитрофин"])
def test_a_question_about_a_printed_name_asks_the_same_thing_however_it_is_typed(data_dir, typed):
    """A value's own name, where the words are cut for a LIKE of each one.

    Cut before the fold, "Квазитроф'ин" became the two substrings "квазитроф" and "ин" ANDed
    together, which is a looser question than the name a person typed — so the same name typed two
    ways asked two different things, and the count beside the list is built from the same words.

    The two spellings are here for opposite reasons, which is worth saying so that neither is
    mistaken for the other. "Квазитрофин" is the guard: without the change it finds nothing,
    because the stored name folded with an apostrophe in it. "Квазитроф'ин" is the half that must
    not break, and it answered correctly before and after — ANDed substrings happen to find this
    name whichever way the words were cut. It is asserted so that it cannot be traded away.
    """
    source_id = _one_document(data_dir)
    with query.open_index(data_dir, source_id) as connection:
        assert [row["name"] for row in query.values(connection, name=typed)] == [A_TEST_WITH_AN_APOSTROPHE]
        assert query.count_values(connection, name=typed) == 1


#: The index version that wrote folded text with the apostrophe still in it. Written down as the
#: number it is and not as SCHEMA_VERSION - 1: an index stamped 6 holds rows this program can no
#: longer read as its own, and that stays true however far the version goes on from here. Asked
#: the other way the test could not fail — SCHEMA_VERSION - 1 is refused by every version there
#: has ever been, including the one that would have forgotten to move the number.
THE_VERSION_THAT_FOLDED_THE_APOSTROPHE = 6


def test_an_index_folded_by_the_old_fold_refuses_rather_than_answering_from_half_of_it(data_dir):
    """The worst of the three outcomes, and the number that stops it.

    An index built before this change holds "квазитроф'ин" where it now holds "квазитрофин", and
    nothing about its tables says so: a question would be answered from whatever rows the new fold
    happens to reach and say nothing about the rest — an answer shaped exactly like the answer to
    "that is all there is". The index is derived data, rebuilt whole from the files on this machine
    in seconds and without a model, so the schema version moving is what this costs, and the
    refusal already says which file, what is safe and what puts it right.
    """
    source_id = _one_document(data_dir, schema_version=THE_VERSION_THAT_FOLDED_THE_APOSTROPHE,
                              folder=lambda text: fold(text).replace("квазитрофин", "квазитроф'ин"))  # fmt: skip
    with pytest.raises(Exception) as refused:
        query.open_index(data_dir, source_id)
    said = str(refused.value)
    assert "built by another version" in said and f"index {THE_VERSION_THAT_FOLDED_THE_APOSTROPHE}" in said
    assert "Nothing that was read is lost" in said and "index" in said.split("Build it again")[-1]


def test_the_spellings_a_person_approved_are_folded_again_as_they_are_read(data_dir):
    """indicators.json is the one file here nothing can rebuild, and it holds folded text.

    28 of this archive's approved spellings were folded by a fold that kept the apostrophe, so
    after the change they were no longer what the printed name folds to, and every value under
    them would have fallen quietly out of its indicator. Folding them again on the way out costs
    one pass over a few thousand short strings and needs no write.
    """
    (data_dir / "indicators.json").write_text(json.dumps({"version": 1, "indicators": [{
        "id": "a-made-up-test", "label": A_TEST_WITH_AN_APOSTROPHE, "status": "approved",
        # As the fold of its own day wrote it: lower case, і paired with и, apostrophe kept.
        "names": ["квазитроф'ин"], "proposed_names": ["квазитрофьин"], "note": "", "reviewed": True,
        "source": "person", "updated_at": "",
    }]}, ensure_ascii=False), encoding="utf-8")

    held = indicators.load(data_dir)[0]
    assert held.names == [fold(A_TEST_WITH_AN_APOSTROPHE)]
    assert indicators.approved_names(data_dir) == {fold(A_TEST_WITH_AN_APOSTROPHE): "a-made-up-test"}
    # The spelling waiting in the other alphabet folds onto the one already approved, and a
    # spelling that is approved is not also waiting: the page counts each in a line of its own.
    assert held.proposed_names == []
    # And nothing was written over the person's own file.
    assert "квазитроф'ин" in (data_dir / "indicators.json").read_text(encoding="utf-8")


def test_an_indicators_id_is_the_one_it_was_given_and_no_fold_recomputes_it(data_dir):
    """The sharp edge of changing the fold, and the honest answer: the id must not move.

    An id is written into indicators.json, into every index's `indicators` table and into every
    value's `indicator_id`, so an id that changed would orphan all three. It is computed once, by
    indicators.slug, on the day a person approves a label, and read from the file ever after —
    which is what this holds. On the live archive one label would be given a different id today
    ("Pasternatsky's sign", whose id has stood as pasternatsky-s-sign and is on three values), and
    that id does not move, because nothing asks the question a second time.
    """
    indicators.upsert(data_dir, None, A_TEST_WITH_AN_APOSTROPHE, [A_TEST_WITH_AN_APOSTROPHE], "approved")
    given = indicators.load(data_dir)[0].id

    stored = json.loads((data_dir / "indicators.json").read_text(encoding="utf-8"))
    stored["indicators"][0]["id"] = "an-id-no-fold-would-write"
    (data_dir / "indicators.json").write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")

    assert indicators.load(data_dir)[0].id == "an-id-no-fold-would-write"
    assert indicators.approved_names(data_dir) == {fold(A_TEST_WITH_AN_APOSTROPHE): "an-id-no-fold-would-write"}
    # What the fold does reach is the id a label would be given today, and an apostrophe is not a
    # letter: it leaves no hyphen of its own behind any more.
    assert given == as_a_name(A_TEST_WITH_AN_APOSTROPHE) == "kvazytrofyn"
