"""The indicator page asked directly: what it shows, and what one press of its forms does.

Both halves used to be a route, so nothing could ask this page a question without fetching an
address and reading five hundred groups of vocabulary out of the markup. The two defects it has
been mended of are both of a kind a question would have caught: a label that could not be read
was answered with one sentence of plain text on a white background, having lost the whole page,
and "I have looked at this group" rebuilt every archive's index — five hundred full builds for
the one job this page exists to do.

`indicators_view` and `indicators_pressed` are where those are decided now.

The press is asked what it refused as well as what it stored, and what it stored is asked to
carry no label and no spelling: `indicators.slug` names files in data/ from a label, and the
journal beside it is written never to hold one.
"""

import ast
import inspect
import json

import pytest
from test_extract import FakeExtractBackend, setup  # noqa: F401

from epicrisis import indicators as indicator_store
from epicrisis.sources import NO_ARCHIVES, SourceRegistry
from epicrisis.web import indicators_page as the_page
from epicrisis.web.app import create_app
from epicrisis.web.indicators_page import INDICATOR_PAGE, indicators_pressed, indicators_view

from test_ask import archive_index  # noqa: F401

#: Nothing is built again by these presses unless a test asks for it: the building is handed in,
#: which is the whole reason the press can be asked this at all.
NOTHING_WAS_BUILT = "nothing was built"


def a_counting_build(built: list):
    """The building of every archive's index, replaced by a count of how often it was asked for."""
    def build(archives) -> str | None:
        built.append(archives)
        return None
    return build


def test_the_indicator_page_gathers_what_it_shows(archive_index):  # noqa: F811
    """The groups, their spellings, what counts them, and what no group holds yet."""
    data_dir, source, _labs = archive_index

    shown = indicators_view(data_dir, source.id)
    assert shown["current"] == "indicators" and "missing" not in shown
    assert shown["status"] == "all" and shown["show"] == "all" and shown["skip"] == 0
    assert shown["page_size"] == INDICATOR_PAGE
    assert shown["rows_total"] == len(indicator_store.load(data_dir))
    assert len(shown["rows"]) == min(shown["rows_total"], INDICATOR_PAGE)
    assert shown["printed_total"] > 0, "this archive prints names, so the page counts them"
    # The whole count, and the cut of it this page draws. Written as "they agree, or there are
    # more than two hundred", this line excused the one case it was about: the block printed the
    # whole count over two hundred rows and said nothing, and the test said nothing either.
    assert shown["waiting_total"] == len(shown["waiting"]) <= the_page.WAITING_PAGE
    # Every group carries its own count of values, and the page is ordered by it.
    counts = [row["values_count"] for row in shown["rows"]]
    assert counts == sorted(counts, reverse=True), "the groups are not in the order the page draws"
    for row in shown["rows"]:
        assert row["indicator"].id, "a group with no id names no file"
        assert all(one["folded"] for one in row["spellings"])


def test_a_spelling_this_archive_never_printed_is_marked_rather_than_shown_as_a_name(archive_index):  # noqa: F811
    """What is left of such a spelling is the folded key, lower case with the two alphabets
    merged. Drawn as it is, it reads as a misspelling; it is marked, and the mark says why."""
    data_dir, source, _labs = archive_index
    indicator_store.upsert(data_dir, None, "A group of this test",
                           ["a spelling no form here prints"], "approved")  # fmt: skip

    row = next(one for one in indicators_view(data_dir, source.id)["rows"]
               if one["indicator"].label == "A group of this test")  # fmt: skip
    assert row["spellings"] == [{"folded": "a spelling no form here prints",
                                 "name": "a spelling no form here prints", "times": 0,
                                 "units": [], "elsewhere": True}]  # fmt: skip
    assert row["values_count"] == 0


def test_a_filter_this_page_does_not_offer_narrows_nothing(archive_index):  # noqa: F811
    """An archive drawn with none of its vocabulary reads as an archive that lost it."""
    data_dir, source, _labs = archive_index
    whole = indicators_view(data_dir, source.id)

    for asked in ({"status": "nonsense"}, {"show": "nonsense"}):
        drawn = indicators_view(data_dir, source.id, **asked)
        assert drawn["rows_total"] == whole["rows_total"], asked
        assert drawn["status"] == "all" and drawn["show"] == "all", asked

    # And the filters that are offered do narrow, or the lines above are about nothing.
    indicator_store.upsert(data_dir, None, "A proposed group of this test", ["one spelling"], "proposed")
    assert indicators_view(data_dir, source.id, status="proposed")["rows_total"] == 1
    assert indicators_view(data_dir, source.id, status="approved")["rows_total"] == whole["rows_total"]


def test_the_everyday_word_answers_where_the_printed_name_found_nothing(archive_index):  # noqa: F811
    """"sugar" is printed on no form anywhere, and this box answered nothing over an archive
    holding values of Glucose — and offered no way on. The page says which word it answered by."""
    data_dir, source, _labs = archive_index
    indicator_store.upsert(data_dir, None, "Glucose", ["glucose"], "approved")

    by_the_word = indicators_view(data_dir, source.id, find="sugar")
    assert by_the_word["said_instead"] == "sugar"
    assert [row["indicator"].label for row in by_the_word["rows"]] == ["Glucose"]

    # A question that already answers is never widened, so nothing says a word was used instead.
    by_a_name = indicators_view(data_dir, source.id, find="glucose")
    assert by_a_name["said_instead"] == "" and by_a_name["rows"]

    # And a word that stands for nothing here is an empty answer that claims nothing.
    nothing = indicators_view(data_dir, source.id, find="no-such-test-anywhere")
    assert nothing["rows"] == [] and nothing["said_instead"] == ""


def test_a_page_asked_for_past_the_end_lands_on_the_last_one(archive_index):  # noqa: F811
    data_dir, source, _labs = archive_index
    total = indicators_view(data_dir, source.id)["rows_total"]
    assert indicators_view(data_dir, source.id, skip=-5)["skip"] == 0
    assert indicators_view(data_dir, source.id, skip=99999)["skip"] == max(total - 1, 0)


def test_an_archive_with_no_index_is_an_answer_and_not_a_fault(archive_index):  # noqa: F811
    """The page that offers to build the index is drawn from the same gathering as the page."""
    data_dir, _source, _labs = archive_index
    nothing = indicators_view(data_dir, "an-archive-with-no-index-of-its-own")
    assert nothing["missing"] is True and nothing["current"] == "indicators"
    assert "rows" not in nothing, "nothing of anybody's is gathered over a missing index"


def test_the_page_cannot_be_gathered_without_naming_an_archive(archive_index):  # noqa: F811
    """The first entry of the constitution: a door into an archive has no default for which one.

    The vocabulary is the instance's and is meant to be. What is of one person is the counting
    beside each group — how many values that archive printed under each spelling — and a page
    showing one person's counts is a page about that person.
    """
    data_dir, _source, _labs = archive_index
    with pytest.raises(TypeError):
        indicators_view(data_dir)
    which = inspect.signature(indicators_view).parameters["the_archive"]
    assert which.default is inspect.Parameter.empty
    assert which.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD


def test_a_label_that_cannot_be_read_is_refused_out_loud_and_writes_nothing(tmp_path):
    """The refusal this page lost. A person who cleared the label and pressed Save was shown one
    sentence of plain text on a white background, having lost five hundred groups off the page —
    while the page already had a channel for saying exactly this and it went unused."""
    data_dir = tmp_path / "data"
    built: list = []

    saved = indicators_pressed(data_dir, NO_ARCHIVES, action="save", label="", names="",
                               rebuild_index=a_counting_build(built))  # fmt: skip

    assert saved.stored == (), "a press that was refused stored something"
    assert len(saved.refused) == 1 and saved.refused[0].endswith(".")
    assert "label" in saved.trouble and saved.trouble == saved.refused[0]
    assert built == [], "a press that was refused built every archive's index"
    assert indicator_store.load(data_dir) == []


def test_a_press_that_only_says_it_was_looked_at_builds_nothing(tmp_path):
    """Rebuilding every archive for it made working through five hundred groups — which is what
    this page is for — five hundred full builds, each a hung request."""
    data_dir = tmp_path / "data"
    made = indicator_store.upsert(data_dir, None, "A group of this test", ["one spelling"], "approved")
    built: list = []

    saved = indicators_pressed(data_dir, NO_ARCHIVES, action="reviewed", indicator_id=made.id,
                               rebuild_index=a_counting_build(built))  # fmt: skip

    assert built == [], "a press that changed no spelling built every archive's index"
    assert saved.stored == ("reviewed — 0 spellings",) and saved.trouble == ""
    assert indicator_store.load(data_dir)[0].reviewed is True


def test_a_form_that_asked_for_nothing_this_page_does_changes_nothing_at_all(tmp_path):
    data_dir = tmp_path / "data"
    built: list = []

    saved = indicators_pressed(data_dir, NO_ARCHIVES, action="nothing-this-page-does",
                               indicator_id="whatever", rebuild_index=a_counting_build(built))  # fmt: skip

    assert saved.stored == () and saved.refused == () and saved.trouble == ""
    assert built == [] and indicator_store.load(data_dir) == []
    # And it is not recorded as somebody settling a group by hand either.
    assert not (data_dir / "journal.jsonl").exists() or "settled by hand" not in \
        (data_dir / "journal.jsonl").read_text(encoding="utf-8")


@pytest.mark.parametrize("asked, written", [
    ({"action": "save", "label": "A group of this test", "names": "one spelling\nanother spelling"},
     "save — 2 spellings"),
    ({"action": "assign", "spelling": "a third spelling"}, "assign — 1 spelling"),
    ({"action": "drop", "spelling": "one spelling"}, "drop — 1 spelling"),
    ({"action": "accept", "names": "one spelling"}, "accept — 1 spelling"),
    ({"action": "delete"}, "delete — 0 spellings"),
])
def test_a_press_that_changes_a_spelling_builds_every_index_once(tmp_path, asked, written):
    """Which spellings are one test decides the indicator of every value in the index, so a
    decision here is built in at once — and once, not twice."""
    data_dir = tmp_path / "data"
    made = indicator_store.upsert(data_dir, None, "A group of this test", ["one spelling"], "approved")
    built: list = []

    saved = indicators_pressed(data_dir, NO_ARCHIVES,
                               indicator_id="" if asked["action"] == "save" else made.id,
                               rebuild_index=a_counting_build(built), **asked)  # fmt: skip

    assert len(built) == 1, "every archive's index was built a number of times that is not one"
    assert built == [NO_ARCHIVES], "the press built over a reading of the list it was not given"
    assert saved.stored == (written,) and saved.refused == ()


def test_a_build_that_failed_is_said_rather_than_swallowed(tmp_path):
    """The page showing the old answer to a question that has changed, in silence, is how a
    person comes to trust a number that is stale."""
    data_dir = tmp_path / "data"

    saved = indicators_pressed(data_dir, NO_ARCHIVES, action="save", label="A group of this test",
                               names="one spelling",
                               rebuild_index=lambda archives: "The index of archive x could not be built again: OSError.")  # fmt: skip

    assert saved.trouble == "The index of archive x could not be built again: OSError."
    assert saved.stored == ("save — 1 spelling",), "the refusal swallowed what was stored"
    assert saved.refused == (), "a build that failed is not the form being refused"


def test_what_a_press_says_it_stored_carries_no_label_and_no_spelling(tmp_path):
    """The same discipline the journal beside it is written to: never the label and never a
    spelling, because those are the printed names of tests and a line holding them says which
    tests this person has had. What this returns can reach a page or an address."""
    data_dir = tmp_path / "data"
    label, spelling = "A group of this test", "a spelling of this test"

    saved = indicators_pressed(data_dir, NO_ARCHIVES, action="save", label=label, names=spelling,
                               rebuild_index=a_counting_build([]))  # fmt: skip

    assert saved.stored and label not in saved.said and spelling not in saved.said
    # And the journal line is the two facts and no third.
    written = [json.loads(line) for line in
               (data_dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()]  # fmt: skip
    settled = [one for one in written if one.get("event") == "a group of spellings was settled by hand"]
    assert len(settled) == 1 and settled[0]["action"] == "save" and settled[0]["names"] == 1
    assert label not in json.dumps(settled[0], ensure_ascii=False)
    assert spelling not in json.dumps(settled[0], ensure_ascii=False)


def test_a_label_that_leaves_no_latin_letter_still_names_its_file_the_same_way(tmp_path):
    """`indicators.slug` names the files this page writes, so what it answers and the order it is
    asked in are the measurement this move had to leave alone.

    Written down as a test and not only measured once: a label of one alphabet is transliterated
    and a second group of the same label is numbered after the first, and both of those are file
    names in somebody's data directory.
    """
    data_dir = tmp_path / "data"
    built: list = []
    for _twice in (1, 2):
        indicators_pressed(data_dir, NO_ARCHIVES, action="save", label="Гемоглобін",
                           names="гемоглобін" if _twice == 1 else "гемоглобін, ще раз",
                           rebuild_index=a_counting_build(built))  # fmt: skip
    assert [one.id for one in indicator_store.load(data_dir)] == ["hemohlobyn", "hemohlobyn-2"]


def test_every_half_of_this_page_takes_which_archive_with_no_default(tmp_path):
    for door in (indicators_view, indicators_pressed):
        asked = inspect.signature(door).parameters
        which = "the_archive" if door is indicators_view else "archives"
        assert asked[which].default is inspect.Parameter.empty, door.__name__
        assert asked["data_dir"].default is inspect.Parameter.empty, door.__name__
    assert inspect.signature(indicators_pressed).parameters["rebuild_index"].default \
        is inspect.Parameter.empty, "the building of the indexes is handed in, never reached for"
    with pytest.raises(TypeError):
        indicators_pressed(tmp_path / "data")


def test_nothing_in_this_module_knows_about_the_web():
    """The routes are the shells, read off the imports rather than the text."""
    reached = set()
    for node in ast.walk(ast.parse(inspect.getsource(the_page))):
        if isinstance(node, ast.Import):
            reached |= {one.name for one in node.names}
        elif isinstance(node, ast.ImportFrom):
            reached.add(node.module or "")
    assert reached
    for name in sorted(reached):
        assert name.split(".")[0] in ("epicrisis", "collections", "dataclasses", "pathlib"), name


def test_the_two_places_the_defaults_are_written_say_the_same_thing(tmp_path):
    """FastAPI reads what an address may leave out off the route's own signature, so the defaults
    live in both places and are held together here."""
    app = create_app(tmp_path / "data", background_jobs=False)
    route = next(one for one in app.routes if getattr(one, "path", None) == "/indicators"
                 and "GET" in getattr(one, "methods", ()))  # fmt: skip
    asked = inspect.signature(route.endpoint).parameters
    gathered = inspect.signature(indicators_view).parameters
    shared = sorted(set(asked) & set(gathered))
    assert shared == ["all_waiting", "find", "show", "skip", "status", "trouble"]
    for name in shared:
        assert asked[name].default == gathered[name].default, name
        assert asked[name].annotation == gathered[name].annotation, name


def test_the_press_and_its_form_ask_for_the_same_things(tmp_path):
    """The route is a shell, and a field it forgot to hand on is a field the press never sees."""
    app = create_app(tmp_path / "data", background_jobs=False)
    route = next(one for one in app.routes if getattr(one, "path", None) == "/indicators"
                 and "POST" in getattr(one, "methods", ()))  # fmt: skip
    asked = set(inspect.signature(route.endpoint).parameters)
    applied = set(inspect.signature(indicators_pressed).parameters)
    assert applied - asked == {"data_dir", "rebuild_index"}, (
        "the press asks for something the form does not carry")
    assert {"action", "indicator_id", "label", "names", "status", "spelling"} <= asked & applied


def test_the_registry_of_one_instance_and_the_gathering_agree_about_the_open_archive(archive_index):  # noqa: F811
    """One reading of the list, and the page gathered for the archive it names and no other."""
    data_dir, source, _labs = archive_index
    archives = SourceRegistry(data_dir).as_one_reading()
    assert archives.showing_id == source.id
    assert indicators_view(data_dir, archives.showing_id)["printed_total"] > 0
    assert indicators_view(data_dir, "somebody-elses-archive")["missing"] is True


#: Printed names of one invented test, more of them than either of the two cuts on this page
#: holds. "Tevmurel" is a meaningless syllable and is already the invented word of this suite's
#: other long-list shape; the numbers keep the names apart, and nothing here is any laboratory's
#: word for anything.
A_LONG_VOCABULARY = 240


def a_vocabulary_longer_than_the_page(data_dir, source, how_many: int = A_LONG_VOCABULARY) -> int:
    """One group, and `how_many` printed names sharing a word with it and held by nothing.

    The shape has to be invented: the three archives read on 4 October 2026 have 179, 90 and 81
    printed names in no indicator, all under the two hundred this page cuts at, so measuring them
    shows the lookalike count lying and says nothing about the other one. Written straight into
    the index, as the By test view's own long-list shape is, because the point is the page's
    arithmetic and not another reading of anybody's documents.

    Returns how many names were in no indicator before this added any.
    """
    import sqlite3

    from epicrisis.index.build import index_path

    before = indicators_view(data_dir, source.id)["waiting_total"]
    indicator_store.upsert(data_dir, None, "Tevmurel", ["Tevmurel plain"], "approved")
    connection = sqlite3.connect(index_path(data_dir, source.id))
    connection.execute("INSERT OR IGNORE INTO files (sha256, file_id) VALUES ('f', 'ffffffff')")
    connection.execute(
        "INSERT INTO documents (id, source_id, file_sha256, date, primary_copy)"
        " VALUES (8000, ?, 'f', '2011-07-09', 1)", (source.id,))  # fmt: skip
    for number in range(how_many):
        connection.execute(
            "INSERT INTO observations (document_id, page, kind, name, value, value_numeric,"
            " value_role, derived, material) VALUES (8000, 1, 'observation', ?, '1', 1.0, 'result', 0, 'swab')",
            (f"Tevmurel {number:03d}",))  # fmt: skip
    connection.commit()
    connection.close()
    return before


def as_a_person_reads_it(text: str) -> str:
    """The page as words: no tags, no entities, one space between things.

    A sentence asserted against the markup is a sentence no human reads — "&laquo;" and "&mdash;"
    stand where the reader sees a quotation mark and a dash, and a count printed inside a <span>
    is not next to the words it belongs to until the tags are gone.
    """
    import html
    import re

    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def test_the_names_in_no_indicator_say_how_many_of_them_are_being_shown(archive_index):  # noqa: F811
    """The block printed the whole count over a list cut at two hundred, and said nothing.

    "307 names, most used first" stood over exactly two hundred rows: no footer, no count of what
    was shown, and no way to the two hundred and first, while the groups above it page properly.
    The sentence under the Find box said it a second time — "those 307 are listed below".
    """
    from starlette.testclient import TestClient

    data_dir, source, _labs = archive_index
    before = a_vocabulary_longer_than_the_page(data_dir, source)
    whole = before + A_LONG_VOCABULARY
    assert whole > the_page.WAITING_PAGE, "the shape is under the cut and shows nothing"

    shown = indicators_view(data_dir, source.id)
    assert shown["waiting_total"] == whole
    assert len(shown["waiting"]) == the_page.WAITING_PAGE
    # Most used first, so the cut is of the least used and not of an arbitrary two hundred.
    assert [item["times"] for item in shown["waiting"]] == sorted((item["times"] for item in shown["waiting"]), reverse=True)

    # And the whole of it one press away, which is the only way to the names past the cut: the
    # three boxes at the top of this page do not narrow this block.
    every = indicators_view(data_dir, source.id, all_waiting=True)
    assert len(every["waiting"]) == whole and every["waiting_total"] == whole

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = as_a_person_reads_it(client.get("/indicators").text)
    assert f"{the_page.WAITING_PAGE} of {whole} names, most used first" in page
    assert f"Showing {the_page.WAITING_PAGE} of {whole} names in no indicator" in page
    assert "show every name" in page
    # The number on its own is not the claim: the sentence has to be of this list and not of the
    # groups beside it, and it has to move when the list does.
    assert f"Showing {whole} of {whole} names in no indicator" not in page
    opened = as_a_person_reads_it(client.get("/indicators", params={"all_waiting": "1"}).text)
    assert f"Showing {whole} of {whole} names in no indicator" in opened
    assert "show every name" not in opened, "the way on is offered where there is nothing behind it"


def test_a_group_says_how_many_lookalikes_the_archive_holds_and_not_how_many_it_drew(archive_index):  # noqa: F811
    """"12 names in the archive share a word with this one" was the length of a list cut at 12.

    It is a count of the archive in the page's own words, taken off a list that a cap had already
    thinned — thirty-nine of the sixty groups on the first page of one archive printed it, where
    the true numbers are 78, 76 and 67.
    """
    from starlette.testclient import TestClient

    data_dir, source, _labs = archive_index
    a_vocabulary_longer_than_the_page(data_dir, source)

    row = next(one for one in indicators_view(data_dir, source.id)["rows"]
               if one["indicator"].label == "Tevmurel")  # fmt: skip
    assert row["related_total"] == A_LONG_VOCABULARY, "the lookalikes of this group are gone"
    assert len(row["related"]) == the_page.RELATED, "the list under the group is not cut any more"

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = as_a_person_reads_it(client.get("/indicators").text)
    assert f"{A_LONG_VOCABULARY} names in the archive share a word with this one" in page
    assert f"{the_page.RELATED} names in the archive share a word with this one" not in page
    # And what is not there is said, because a list that stops without a word is the count again.
    assert f"The {the_page.RELATED} most used are here. {A_LONG_VOCABULARY - the_page.RELATED} more" in page
