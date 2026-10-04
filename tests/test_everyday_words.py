"""The word a person says, and the row a laboratory printed. Synthetic data only.

Out of the box there was no path at all from an everyday word to a test. A person searching for
their own blood sugar typed "sugar", the search answered nothing, the find box on the indicators
page answered nothing, and the one thing offered instead — "Ask for it in your own words" — needs
a model and is off in the installation this project ships.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from epicrisis import everyday_words
from epicrisis import indicators as indicator_store
from epicrisis import query
from epicrisis.corrections import set_document_date
from epicrisis.extract.run import extract_source, load_extracted, write_document
from epicrisis.index.build import build_index
from epicrisis.printed_values import fold
from epicrisis.validate import validate_source
from epicrisis.web.app import create_app
from conftest import A_DAY_FOR_AN_ILLUSTRATION
from test_extract import FakeExtractBackend, setup  # noqa: F401


# Words that must never reach this table, and the reason each is refused. A line here is the rule
# of everyday_words.py written as code: the left of the table is a word for a row a form prints,
# so a complaint, an organ, what an organ does, a diagnosis and a verdict on a value are all out.
NEVER = {
    "chest pain": "a complaint, and no row of any form is named it",
    "боль в груди": "the same complaint in another language",
    "tired": "a complaint",
    "thyroid": "an organ, and which rows stand for one is a medical judgement",
    "щитовидка": "the same organ",
    "kidney function": "what an organ does",
    "liver": "an organ",
    "anaemia": "a diagnosis",
    "diabetes": "a diagnosis",
    "good cholesterol": "a verdict on the value, which this program never gives",
    "bad cholesterol": "the same verdict",
    "high sugar": "a verdict on the value",
}


@pytest.fixture
def archive_of_one_test(setup):  # noqa: F811
    """An archive printing Глюкоза, with a group over it labelled in English, as a person would.

    The everyday word has to cross both a language and the gap between what people say and what
    forms print, and those are two different things: "sugar" is not Russian for "Глюкоза", it is
    not printed anywhere at all.
    """
    data_dir, source, output, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    labs = records["labs.pdf"]["sha256"]
    document = load_extracted(output / "extracted", labs)["documents"][0]
    template = document["observations"][0]
    document["observations"] = [
        dict(template, name_as_printed="Глюкоза", value_as_printed="5,1", unit_as_printed="ммоль/л", reference_as_printed="4,1-5,9"),
    ]  # fmt: skip
    document["page_texts"] = [{"page": 1, "text": "Глюкоза 5,1 ммоль/л 4,1-5,9"}]
    write_document(output / "extracted", labs, document)
    set_document_date(output, labs, [1, 2], A_DAY_FOR_AN_ILLUSTRATION)
    indicator_store.upsert(data_dir, None, "Glucose", ["Глюкоза", "Glucose"], status="approved")
    validate_source(output)
    build_index(data_dir, [source])
    return data_dir, source, labs


def test_every_line_of_the_table_names_a_form_and_not_a_person_or_a_complaint():
    """The rule, as code, because the table is where this would go wrong quietly.

    A row of this table is only allowed where the sentence "what people call X, a form prints as
    a row named Y" can be written about it. A symptom, an organ, a diagnosis or a verdict on a
    value would turn a dictionary of names into the interpretation the third entry of the
    constitution refuses, and it would do it one plausible line at a time.
    """
    for word, why in NEVER.items():
        assert everyday_words.stands_for(word) == (), f"{word!r} is {why}"
    assert everyday_words.EVERYDAY_WORDS, "an empty table helps nobody"
    for said, printed_names in everyday_words.EVERYDAY_WORDS.items():
        # Folded on both sides, because every match in this program is made on the folded form.
        assert said == fold(said), said
        assert printed_names and all(name == fold(name) for name in printed_names), said
        assert len(set(printed_names)) == len(printed_names), f"{said}: a name offered twice"
        # And the everyday word is not itself one of the printed names it stands for. Where it is,
        # the ordinary search already answers it literally and this table must keep out of the way.
        assert said not in printed_names, said
        assert said not in everyday_words.EVERYDAY_WORDS.get(printed_names[0], ()), said


def test_the_whole_question_is_answered_and_never_a_word_inside_it():
    """"sugar beet" is not a question about blood glucose.

    A word taken out of the middle of a sentence would make this table fire on questions nobody
    asked, and a page that cannot say plainly which word it answered by is worse than one that
    answers nothing.
    """
    assert everyday_words.stands_for("sugar")
    assert everyday_words.stands_for("Sugar") == everyday_words.stands_for("sugar")
    assert everyday_words.stands_for("  sugar  ") == everyday_words.stands_for("sugar")
    for asked in ("sugar beet", "salty food", "my sugar level please", "no sugar", ""):
        assert everyday_words.stands_for(asked) == (), asked
    assert everyday_words.stands_for(None) == ()


def test_an_everyday_word_finds_the_test_and_the_answer_says_which_word_it_used(archive_of_one_test):
    """`said` on a row is what the seventh entry of the constitution asks of this.

    The page may not let a reader believe they typed the printed name. A question answered by a
    name of its own carries nothing here; one answered by the table carries the word, so the page
    can say it in its own words beside the row.
    """
    data_dir, _source, _labs = archive_of_one_test
    with query.open_index(data_dir, None) as connection:
        by_an_everyday_word = query.indicators_matching(connection, "sugar", everyday_words_too=True)
        assert [item["label"] for item in by_an_everyday_word] == ["Glucose"]
        assert [item["said"] for item in by_an_everyday_word] == ["sugar"]
        # Every language of the table reaches the same group, and the word travels unchanged.
        for asked in ("сахар", "цукор", "blood sugar", "azúcar"):
            found = query.indicators_matching(connection, asked, everyday_words_too=True)
            assert [item["label"] for item in found] == ["Glucose"], asked
            assert found[0]["said"] == asked, asked

        # Off unless a caller asks, and the default is the contract the tools over the network
        # make: matching there is literal and per-language, and no answer of theirs may say it
        # searched a spelling that is nobody's spelling of anything.
        assert query.indicators_matching(connection, "sugar") == []

        # A question that already answers by name is never widened, and says nothing about a word
        # it did not need: the table is reached only where no name of any language held the words.
        for asked in ("Глюкоза", "glucose", "глюк"):
            found = query.indicators_matching(connection, asked, everyday_words_too=True)
            assert [item["label"] for item in found] == ["Glucose"], asked
            assert found[0]["said"] == "", asked
            assert found == query.indicators_matching(connection, asked), asked
        # And a word in neither is still nothing, which is the honest answer.
        for asked in ("chest pain", "thyroid", "цистатин"):
            assert query.indicators_matching(connection, asked, everyday_words_too=True) == [], asked


def test_the_three_doors_to_a_test_all_answer_an_everyday_word_and_all_say_so(archive_of_one_test):
    """Out of the box there was no path from the word a person has to the row a form printed.

    Three places ask "which test do these words lead to" — the search page, the find box on the
    indicators page, and the Find box of the By test view, which is where the search page sends
    somebody who found nothing. All three answered nothing for "sugar" over an archive that holds
    glucose, and the only thing offered instead was /ask, which needs a model and ships off.
    """
    data_dir, _source, _labs = archive_of_one_test
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    search = client.get("/search?q=sugar").text
    assert 'href="/tests/glucose"' in search and "&ldquo;sugar&rdquo;" in search
    assert "Nothing here is printed" in search, "the page claims the word was printed somewhere"
    assert "no document of this archive holds" in search.lower()

    grouped = client.get("/indicators?find=sugar").text
    assert ">Glucose<" in grouped
    assert "Nothing in this vocabulary is named" in grouped, "answered by a synonym and did not say so"

    lanes = client.get("/?view=indicators&test=sugar").text
    assert "/tests/glucose" in lanes
    assert "No test here is named" in lanes, "answered by a synonym and did not say so"

    # A question answered by a printed name says none of that: the sentence would be untrue, and a
    # page that announces a widening it did not perform is the defect from the other side.
    byname = client.get("/search?q=glucose").text
    assert 'href="/tests/glucose"' in byname and "by that name" in byname
    assert "Nothing here is printed" not in byname

    # And a word in neither the archive nor the table is still a dead end that says so, with the
    # ways on that do not need a model.
    nowhere = client.get("/search?q=thyroid").text
    assert "no test is named that in any of its languages" in nowhere
    assert 'href="/?view=indicators"' in nowhere and 'href="/indicators"' in nowhere
