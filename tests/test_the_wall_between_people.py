"""Two people's records never meet. This is the test that proves it rather than the rule that asks.

The first line of the constitution, and the one failure that cannot be undone by an apology. It has
gone wrong once already, and the shape of it is worth keeping in front of whoever reads this next:
a file of a person's own decisions was kept for the whole instance, a page read it without asking
whose it was, and one person's screen showed another person's doctors — while a label chosen in one
archive renamed a clinic on thirty-four documents of somebody else, under a line reading "as printed
on the documents themselves".

The fix for that was a filter at the point of use, which is exactly the thing that had been
forgotten. So this is written instead: two archives whose every printed string is disjoint, and a
sweep over **every** page this program serves and every reading the tools answer with, asserting
that nothing of the one appears in any answer about the other.

It takes the routes from the application itself rather than from a list written here, so a page
added next month is swept without anybody remembering to add it. That is the whole point: the wall
is not a rule a person has to keep, it is a test that fails when the wall is breached.

A test name is in the forbidden set although the vocabulary that groups spellings is deliberately
shared across archives — that is the asset, and it names forms rather than people. The sharing is
of the dictionary, not of the page: an archive's page shows what that archive prints. So a test
name of the other archive appearing here is still a defect, and still this test's business.

Every name, number and word below is invented, and the two sets share no substring.
"""

import json
import sqlite3
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from epicrisis import indicators, people
from epicrisis.index.build import SCHEMA, SCHEMA_VERSION, index_path
from epicrisis.indicator_proposals import propose_indicators
from epicrisis.web.app import create_app

#: What each archive prints, and nothing of one is a substring of anything of the other. The
#: oddness is deliberate: a sweep looking for "Smith" in a page full of English would find it in
#: "blacksmith" and prove nothing.
THEIRS = {
    "one": {"id": "aaaa1111", "whose": "Zoryana Vdovychenko",
            "doctor": "Нетудихата І.В", "provider": "Westhollow Medical Laboratory",
            "test": "Квазитрофин", "value": "7,77", "unit": "кю/мл",
            "diagnosis": "Квазитрофиновая недостаточность", "medication": "Квазитрофин-форте 11 мг",
            "line": "Квазитрофин 7,77 кю/мл, норма 1,11-9,99"},
    "two": {"id": "bbbb2222", "whose": "Opanas Zhuravskyi",
            "doctor": "Загуменна О.П", "provider": "Eastmarsh Diagnostic Rooms",
            "test": "Пселлофаза", "value": "3,33", "unit": "зю/дл",
            "diagnosis": "Пселлофазная дисплазия", "medication": "Пселлофазин 22 мг",
            "line": "Пселлофаза 3,33 зю/дл, норма 2,22-4,44"},
}  # fmt: skip


def _an_archive(data_dir: Path, mine: dict, at: Path | None = None) -> None:
    """One archive with one document, holding only strings of its own.

    `at` writes the index somewhere other than this archive's own file, which is how an instance
    from before archives had owners is built: one index, named for no one, in the single old file.
    """
    index = sqlite3.connect(at or index_path(data_dir, mine["id"]))
    with index:
        index.executescript(SCHEMA)
        index.executemany("INSERT INTO meta VALUES (?, ?)",
                          [("built_at", "2026-01-01T00:00:00+00:00"), ("schema_version", str(SCHEMA_VERSION))])  # fmt: skip
        index.execute(
            """INSERT INTO files (sha256, file_id, source_id, path, category, page_count)
               VALUES (?, ?, ?, ?, 'scan', 1)""",
            (mine["id"] * 8, mine["id"][:8], mine["id"], f"/scans/{mine['id']}.pdf"),
        )  # fmt: skip
        index.execute(
            """INSERT INTO documents (source_id, file_sha256, first_page, pages, doc_type,
                                      language, title, provider, doctor, date, date_precision,
                                      transcribed, primary_copy)
               VALUES (?, ?, 1, '[1]', 'lab_panel', 'uk', ?, ?, ?, '2011-07-09', 'day', 1, 1)""",
            (mine["id"], mine["id"] * 8, mine["test"], mine["provider"], mine["doctor"]),
        )  # fmt: skip
        document = index.execute("SELECT last_insert_rowid()").fetchone()[0]
        index.execute(
            """INSERT INTO observations (document_id, page, kind, name, value, value_numeric, unit,
                                         reference, snippet, derived, material_source, value_role)
               VALUES (?, 1, 'quantitative', ?, ?, ?, ?, ?, ?, 0, 'none', 'result')""",
            (document, mine["test"], mine["value"], float(mine["value"].replace(",", ".")),
             mine["unit"], "1,11-9,99", mine["line"]),
        )  # fmt: skip
        index.execute("INSERT INTO diagnoses (document_id, text) VALUES (?, ?)",
                      (document, mine["diagnosis"]))  # fmt: skip
        index.execute("INSERT INTO medications (document_id, text) VALUES (?, ?)",
                      (document, mine["medication"]))  # fmt: skip
        index.execute("INSERT INTO page_texts (document_id, page, text) VALUES (?, 1, ?)",
                      (document, mine["line"]))  # fmt: skip
    index.close()


def _printed_a_second_way(data_dir: Path, mine: dict) -> str:
    """One more document of the same archive, naming the same laboratory with a comma after it.

    So that this archive's page of doctors and clinics offers a join to press — a family of one
    spelling is not a question and the page draws no button over it. A trailing comma is one of
    the shapes `people.worth_joining` is written for, the same words in the same order printed
    differently, so the family is offered without a syllable that is not already in THEIRS.
    """
    spelling = mine["provider"] + ","
    index = sqlite3.connect(index_path(data_dir, mine["id"]))
    with index:
        index.execute(
            """INSERT INTO files (sha256, file_id, source_id, path, category, page_count)
               VALUES (?, ?, ?, ?, 'scan', 1)""",
            (mine["id"][::-1] * 8, mine["id"][:4] + "cccc", mine["id"], f"/scans/{mine['id']}-again.pdf"),
        )  # fmt: skip
        index.execute(
            """INSERT INTO documents (source_id, file_sha256, first_page, pages, doc_type,
                                      language, title, provider, date, date_precision,
                                      transcribed, primary_copy)
               VALUES (?, ?, 1, '[1]', 'lab_panel', 'uk', ?, ?, '2012-08-10', 'day', 1, 1)""",
            (mine["id"], mine["id"][::-1] * 8, mine["test"], spelling),
        )  # fmt: skip
    index.close()
    return spelling


def _both_on_the_list(data_dir: Path, open_one: str) -> None:
    """The list of archives this server holds, with one of them open."""
    (data_dir / "sources.json").write_text(json.dumps([
        {"id": mine["id"], "name": f"the box of {mine['whose']}", "path": f"/scans/{mine['id']}",
         "owner": mine["whose"], "added_at": "2026-01-01T00:00:00+00:00",
         "active": which == open_one}
        for which, mine in THEIRS.items()
    ]), encoding="utf-8")  # fmt: skip


@pytest.fixture
def two_archives(tmp_path: Path) -> Path:
    """Two people on one server, with the first of them open."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    _both_on_the_list(data_dir, "one")
    for mine in THEIRS.values():
        _an_archive(data_dir, mine)
    # The first archive prints its laboratory twice, one of them with a comma, so that its own
    # page offers a join: a press is half of what this file is about, and a page with no button
    # on it cannot be pressed at the wrong moment.
    _printed_a_second_way(data_dir, THEIRS["one"])
    # And a decision the second person made about their own archive, under a label of their own
    # choosing. This is the hardest case and the one the leak was made of: the file holding it was
    # kept for the whole instance, so the label reached the documents of whoever else was reading.
    #
    # The kind is passed, and it has to be: join() takes (data_dir, source_id, kind, names, label)
    # and answers a kind it does not know by returning what is already there, in silence. Written
    # here without it, this fixture wrote no file at all, and the test below then asserted that a
    # label which had never been made was not on the page — it passed, and could not have failed.
    # A test guarding the first line of the constitution is the last place for that.
    people.join(data_dir, THEIRS["two"]["id"], "institution",
                [THEIRS["two"]["provider"], THEIRS["two"]["provider"] + " Eastgate"],
                THEIRS["two"]["provider"] + " Eastgate")  # fmt: skip
    assert people.path(data_dir, THEIRS["two"]["id"]).exists(), "the decision was not written"
    return data_dir


def _nothing_of_theirs(which: str) -> list[str]:
    """Everything the other archive prints, except the one string that is meant to be seen.

    The name of whoever an archive belongs to stands in the picker in the bar on every page, and
    that is deliberate: a person keeping two archives on one server cannot choose between them if
    the choice is unnamed. It is also the only thing of theirs that is ever shown — not a document,
    not a doctor, not a value, not a word of a diagnosis. Written out here rather than quietly
    skipped, so that widening the exception means editing this sentence.
    """
    return [value for key, value in THEIRS[which].items() if key not in ("id", "whose")]


def _the_tabs_of(path: str) -> list[str]:
    """What else one address answers, where a page holds more than one thing at it.

    A route is not a page here. `/who` answers about the doctors or about the institutions
    depending on one word in the query and defaults to the doctors — and both halves of the leak
    this file was written for were on the institutions, which the sweep was therefore never
    asking for: a group of another person's spellings sat under "Joined by you" on that tab while
    every page the sweep read came back clean. The lists are the program's own, so a third tab
    added to any of these is swept without anybody remembering this function.
    """
    from epicrisis.web import app as dashboard

    return {
        "/who": [f"?kind={kind}" for kind in people.KINDS],
        "/card": [f"?tab={tab}" for tab in dashboard.CARD_TABS],
        "/settings": [f"?tab={tab}" for tab in dashboard.SETTINGS_TABS],
    }.get(path, [""])


def _every_page(client: TestClient, data_dir: Path) -> dict[str, str]:
    """Every page this program serves, answered for whichever archive is open."""
    app = client.app
    showing = next(one for one in json.loads((data_dir / "sources.json").read_text()) if one.get("active"))
    standing_in = {"chat_id": "none", "source_id": showing["id"], "sha256": showing["id"] * 8,
                   "first_page": "1", "page": "1", "indicator_id": "none"}  # fmt: skip
    answers = {}
    for route in app.routes:
        path = getattr(route, "path", "")
        if "GET" not in getattr(route, "methods", set()) or path.endswith("/image"):
            continue
        address = path
        for name, value in standing_in.items():
            address = address.replace("{" + name + "}", value)
        if "{" in address:
            continue
        for tab in _the_tabs_of(address):
            answers[address + tab] = client.get(address + tab, follow_redirects=True).text
    return answers


class _TheFormOnThePage(HTMLParser):
    """One form of a drawn page, as a browser holds it: where it posts, and with what.

    Read off the page rather than written out here. What the test below is about is a press on a
    page that has already been drawn, and an address written into the test would be an assertion
    about today's routes instead — it would go on passing while the form on the page said
    something else entirely. The fields are the ones a browser would send: a tick box only while
    it is ticked, and the first option of a picker where none is marked selected.
    """

    def __init__(self, posting_to: str):
        super().__init__()
        self.posting_to, self.action, self.fields = posting_to, "", []
        self._inside, self._picker = False, None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        written = dict(attrs)
        if tag == "form":
            self._inside = not self.action and (written.get("action") or "").endswith(self.posting_to)
            if self._inside:
                self.action = written["action"]
        elif not self._inside:
            return
        elif tag == "input":
            if written.get("type") != "checkbox" or "checked" in written:
                self.fields.append((written.get("name", ""), written.get("value", "")))
        elif tag == "select":
            self._picker = written.get("name", "")
        elif tag == "option" and self._picker is not None:
            self.fields.append((self._picker, written.get("value", "")))
            self._picker = None

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._inside = False


def _the_press_the_page_offers(page: str, posting_to: str) -> tuple[str, dict[str, list[str]]]:
    """The address a button on this page posts to, and the fields that go with it.

    The fields come back as a name to its values, because one name carries several here — a tick
    box per spelling — and that is the shape the client sends as a form rather than as a body.
    """
    form = _TheFormOnThePage(posting_to)
    form.feed(page)
    assert form.action, f"the page offers no form posting to …{posting_to}, so nothing can be pressed"
    sending: dict[str, list[str]] = {}
    for name, value in form.fields:
        sending.setdefault(name, []).append(value)
    return form.action, sending


def test_no_page_of_one_persons_archive_holds_a_word_of_anothers(two_archives):
    """The sweep. Every page, every string, both directions.

    The routes come from the application, so a page added next month is swept without anybody
    remembering to add it here — which is the difference between a wall and a promise.
    """
    client = TestClient(create_app(two_archives, background_jobs=False), base_url="http://localhost:8050",
                        raise_server_exceptions=False)  # fmt: skip

    pages = _every_page(client, two_archives)
    assert len(pages) >= 15, "the sweep found almost no pages; it is testing nothing"

    theirs = _nothing_of_theirs("two")
    leaked = {address: [word for word in theirs if word in text]
              for address, text in pages.items() if any(word in text for word in theirs)}  # fmt: skip
    assert leaked == {}, f"another person's archive is on these pages: {leaked}"

    # And the archive that is open does answer about itself, or the sweep above proves nothing: a
    # server showing empty pages would pass it.
    mine = THEIRS["one"]
    assert any(mine["test"] in text for text in pages.values())
    assert any(mine["provider"] in text for text in pages.values())


def test_the_wall_stands_from_the_other_side_too(two_archives):
    """Switch the archive and sweep again. A wall with one good side is a door."""
    client = TestClient(create_app(two_archives, background_jobs=False), base_url="http://localhost:8050",
                        raise_server_exceptions=False)  # fmt: skip
    client.post("/owner", data={"source": THEIRS["two"]["id"], "back": "/"}, follow_redirects=True)

    pages = _every_page(client, two_archives)
    theirs = _nothing_of_theirs("one")
    leaked = {address: [word for word in theirs if word in text]
              for address, text in pages.items() if any(word in text for word in theirs)}  # fmt: skip

    assert leaked == {}, f"the first person's archive is on these pages: {leaked}"
    assert any(THEIRS["two"]["test"] in text for text in pages.values())


def test_a_decision_made_in_one_archive_does_not_rename_anything_in_another(two_archives):
    """The half of the leak that was worse than seeing a stranger's name.

    A group of spellings is joined under a label the person chose. That file is kept for the whole
    instance, so a label holding a spelling that exists in one archive alone was being applied to
    the documents of another — on the page, and in the cut of the timeline by institution, under a
    line reading "as printed on the documents themselves".
    """
    client = TestClient(create_app(two_archives, background_jobs=False), base_url="http://localhost:8050",
                        raise_server_exceptions=False)  # fmt: skip

    page = client.get("/who?kind=institution").text

    assert THEIRS["one"]["provider"] in page  # what this archive prints
    assert "Eastgate" not in page  # and not the label somebody chose over there

    # And the label does reach the page of the archive it was chosen in, which is what makes the
    # line above an assertion rather than a sentence about nothing. Without this, a decision that
    # silently failed to be written would satisfy the test — and one did: see the fixture.
    client.post("/owner", data={"source": THEIRS["two"]["id"], "back": "/"}, follow_redirects=True)
    theirs = client.get("/who?kind=institution").text
    assert "Eastgate" in theirs, "the decision is not on the page of the archive it was made in"
    assert THEIRS["one"]["provider"] not in theirs  # and still nothing of the first person's

    # And the press that lands after the archive has been switched under the page it was drawn
    # on. Three ordinary acts and nothing mocked: draw the first archive's page, move the server
    # to the second with the picker standing in the bar of every page, press Join on the page
    # still open. The four forms of this page carried the kind, the spellings and the label and
    # said nothing at all about whose spellings they were, so the group was settled inside the
    # second person's own file of decisions, labelled as the first archive prints it — and the
    # second person's page then printed the first person's laboratory under their own name.
    #
    # The test above cannot catch this and could not have: it draws and presses with the archive
    # standing still, which is the one arrangement in which reading the open archive at the
    # moment of the press gives the right answer.
    client.post("/owner", data={"source": THEIRS["one"]["id"], "back": "/"}, follow_redirects=True)
    drawn = client.get("/who?kind=institution").text
    where, fields = _the_press_the_page_offers(drawn, "join")
    before = people.load(two_archives, THEIRS["two"]["id"])

    client.post("/owner", data={"source": THEIRS["two"]["id"], "back": "/"}, follow_redirects=True)
    client.post(where, data=fields, follow_redirects=True)

    pages = _every_page(client, two_archives)
    assert len(pages) >= 15, "the sweep found almost no pages; it is testing nothing"
    theirs_now = _nothing_of_theirs("one")
    leaked = {address: [word for word in theirs_now if word in text]
              for address, text in pages.items() if any(word in text for word in theirs_now)}  # fmt: skip
    assert leaked == {}, f"a press made after the archive was switched put it on these pages: {leaked}"
    assert people.load(two_archives, THEIRS["two"]["id"]) == before, (
        "a decision about one archive was written into another person's file of their own decisions")

    # And the press does land where the page was drawn, or the lines above are about nothing.
    client.post("/owner", data={"source": THEIRS["one"]["id"], "back": "/"}, follow_redirects=True)
    client.post(where, data=fields, follow_redirects=True)
    settled = people.settled(people.load(two_archives, THEIRS["one"]["id"]), "institution")
    assert [one.label for one in settled] == [THEIRS["one"]["provider"]], "the join did not happen at all"


@pytest.fixture
def one_old_index_and_an_unread_archive(tmp_path: Path) -> Path:
    """An instance from before archives had owners, with a second archive added and never read.

    The shape of a real upgrade, and the narrowest window there is: one archive was read by a
    version that kept a single `index.sqlite` named for nobody, a second archive was then added on
    the dashboard, and `epicrisis index` — which is what moves that file under the one archive it
    was built from — has not been run since. So the folder holds one index, no per-owner index at
    all, and the archive that is open has never been read.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    _both_on_the_list(data_dir, "two")
    _an_archive(data_dir, THEIRS["one"], at=index_path(data_dir))
    assert not sorted(data_dir.glob("index-*.sqlite")), "the per-owner indexes are the thing missing"
    return data_dir


def test_the_single_index_of_an_upgraded_instance_is_not_handed_to_another_archive(one_old_index_and_an_unread_archive):
    """An archive whose index is not built is an archive there is nothing to answer about.

    The docstring of `_the_only_index` already said this was closed, and an exception in it held
    the door open for exactly one shape: an old single index, no per-owner index yet, and a named
    archive that has none of its own. Every page then answered out of the first person's index
    under the second person's name — the documents, the laboratory, the test and the value, all of
    it at once, and not one word of it marked as anybody else's.
    """
    data_dir = one_old_index_and_an_unread_archive
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050",
                        raise_server_exceptions=False)  # fmt: skip

    pages = _every_page(client, data_dir)
    assert len(pages) >= 15, "the sweep found almost no pages; it is testing nothing"

    theirs = _nothing_of_theirs("one")
    leaked = {address: [word for word in theirs if word in text]
              for address, text in pages.items() if any(word in text for word in theirs)}  # fmt: skip
    assert leaked == {}, f"the single old index was answered from under another owner: {leaked}"

    # And it says so in words, rather than drawing an empty page: an archive with no index of its
    # own is an archive there is nothing to answer about yet, and the page names whose it is and
    # the one step that fills it.
    assert THEIRS["two"]["whose"] in pages["/"]
    assert "have not been read yet" in pages["/"]


def test_the_single_index_of_an_upgraded_instance_still_answers_for_its_own_archive(one_old_index_and_an_unread_archive):
    """And the upgrade still works, which is what the exception was there for.

    Refusing the old file to everybody would have been the cheap fix and would have left every
    instance holding one with nothing to show: between the upgrade and the next `epicrisis index`
    that file is the only index there is. It is given to the archive whose documents are in it,
    and to no other.
    """
    data_dir = one_old_index_and_an_unread_archive
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050",
                        raise_server_exceptions=False)  # fmt: skip
    client.post("/owner", data={"source": THEIRS["one"]["id"], "back": "/"}, follow_redirects=True)

    pages = _every_page(client, data_dir)
    mine = THEIRS["one"]
    assert any(mine["test"] in text for text in pages.values()), "the old index now answers for nobody"
    assert any(mine["provider"] in text for text in pages.values())


@pytest.mark.parametrize("switched_while", ["the pass is being checked", "the index is being opened"])
def test_one_call_of_one_tool_answers_out_of_one_archive_however_the_server_moves(
    two_archives, monkeypatch, switched_while
):
    """Three readings of which archive is open, inside one answer, and a switch between them.

    `showing()` reads sources.json afresh every time, which is right — the archive can be
    switched while a client is connected, and an answer that went on quoting the archive the
    connection opened with would be the leak the other way round. What was wrong is that one tool
    call read it three times: the pass was checked against the first reading, the index opened on
    the second, and the name put into `archive_of` on the third. A switch landing between them
    served one archive's counts under another archive's owner — and these instructions tell the
    model that `archive_of` is the field to trust and to quote, so it writes about the records of
    one person under the name of another.

    The lock is the half that is worse. `mcp_lock.require(archive=…)` exists so that nothing of
    one person is read as another's, and it was being given the first reading while the data came
    from the second: a pass granted over one archive served a read of the other, which is the one
    thing that lock is for.

    So the archive is decided once per call and carried, and both seams are held here: the
    instant after the pass is checked, and the instant after the index is opened.
    """
    import asyncio

    from epicrisis import mcp_lock, query
    from epicrisis.mcp_server import build_server
    from epicrisis.sources import SourceRegistry

    data_dir = two_archives
    switched = []

    def the_other_tab() -> None:
        """The archive switched from a page open somewhere else, mid-answer. Once, so that a
        second reading inside the same call is not switched back and quietly agrees."""
        if not switched:
            SourceRegistry(data_dir).set_active(THEIRS["two"]["id"])
            switched.append(THEIRS["two"]["id"])

    if switched_while == "the pass is being checked":
        checking = mcp_lock.Lock.require

        def require(self, *args, **rest):
            answer = checking(self, *args, **rest)
            the_other_tab()
            return answer

        monkeypatch.setattr(mcp_lock.Lock, "require", require)
    else:
        opening = query.open_index

        def open_index(*args, **rest):
            connection = opening(*args, **rest)
            the_other_tab()
            return connection

        monkeypatch.setattr(query, "open_index", open_index)

    said = asyncio.run(build_server(data_dir).call_tool("archive_overview", {})).structured_content

    assert switched, f"the archive was never switched while {switched_while}, so this proves nothing"
    assert SourceRegistry(data_dir).active().id == THEIRS["two"]["id"], "the switch did not take"
    # One archive, in the counts and in the name over them. The first one, because that is the
    # archive the call began about and the one its pass was checked against.
    assert said["archive_of"] == THEIRS["one"]["whose"], "the answer is of one archive under another's name"
    assert said["documents"] == 2, "the counts are not the first archive's"  # its two printings
    both = [*_nothing_of_theirs("two"), THEIRS["two"]["whose"]]
    assert [word for word in both if word in str(said)] == [], "the other archive is in the answer"


def test_the_door_that_writes_into_an_index_asks_the_same_question_as_the_one_that_reads(
    one_old_index_and_an_unread_archive,
):
    """The worse half of the same hole: a choice made in one archive, written into another's index.

    Two doors in `query.py` find an index when it is not where it was asked for, and one of them
    writes — pressing "show this copy" takes the choice off the other members of the group, inside
    the index, so that the page changes before the next indexing rather than after it. Under the
    second owner's name that press would have reached into the first person's index, which is the
    shape of the leak this file was written for: a decision made in one archive applied to the
    documents of somebody else. Both doors resolve the path in one place, so one answer closes
    both — and this says so, because the next person to touch that function will not know.
    """
    from epicrisis import query

    data_dir = one_old_index_and_an_unread_archive
    document = (THEIRS["one"]["id"] * 8, 1)

    with pytest.raises(query.IndexMissing):
        query.choose_primary_copy(data_dir, THEIRS["two"]["id"], *document)
    # And the archive whose documents those are still makes the choice.
    assert query.choose_primary_copy(data_dir, THEIRS["one"]["id"], *document) is None  # one copy, no group


def test_an_index_cannot_be_opened_by_a_call_that_did_not_say_whose_it_is(two_archives):
    """"Every door into an archive takes which archive it is, and takes it as an argument that has
    no default. A call that forgets it must fail, not answer about somebody."

    The reading door had a default and the writing door beside it never did. What the default did
    on an instance holding one archive is answer: `open_index(data_dir)` found no index of that
    name, counted the per-owner files, found exactly one and handed over that person's records —
    which is right until the day a second archive is added, and silently wrong from then on. An
    instance of one archive is what every instance is on its first day, and it is the arrangement
    every caller is written and tested against.

    So there is nothing to forget: a call that names no archive does not compile a page about
    somebody, it raises. `None` still means the single index of an instance from before archives
    had owners, and that is said rather than defaulted to — the difference between asking for the
    nameless file and not having asked at all.
    """
    from epicrisis import query

    data_dir = two_archives
    # The arrangement the default answered in, and the one every instance is in on its first day:
    # one per-owner index and no nameless file. The second archive's index is taken away rather
    # than its entry on the list, because what the default counted was files.
    index_path(data_dir, THEIRS["two"]["id"]).unlink()
    assert [path.name for path in sorted(data_dir.glob("index-*.sqlite"))] == [
        index_path(data_dir, THEIRS["one"]["id"]).name], "the shape this is about was not built"  # fmt: skip

    with pytest.raises(TypeError):
        query.open_index(data_dir)  # type: ignore[call-arg]

    # And both answers it does give are still given, because each of them was asked for. The
    # archive named answers about itself; `None` reaches the one index of an instance with one
    # archive, which is what the upgrade path needs and is said out loud instead of fallen into.
    for asked_for in (THEIRS["one"]["id"], None):
        connection = query.open_index(data_dir, asked_for)
        try:
            assert query.overview(connection)["documents"] == 2, asked_for  # its two printings
        finally:
            connection.close()


class _AskedNothing:
    """A model that answers no group and keeps the question it was asked."""

    def __init__(self):
        self.asked = []

    def group(self, existing: str, names: str, workdir) -> dict:
        self.asked.append({"existing": existing, "names": names})
        return {"groups": [], "unclear": []}


def test_the_question_put_to_a_model_about_one_archive_carries_the_shared_dictionary_and_no_more(two_archives):
    """The one thing that leaves this machine, and the sharp line drawn through it.

    Grouping printed names is the only question this program asks a model about an archive's
    vocabulary, and the spellings it shows the model are the whole instance's — every archive's,
    not only the one the names come from. That is deliberate and it is the asset: which printed
    spellings are one test names a form, so it crosses, and locking it per archive would mean
    teaching the program the same thing again for every person. The owner settled it in b9b7acf
    and the first entry of the constitution says why.

    So this is the test that keeps the line where it is, in both directions at once: the other
    archive's *test name* is in the question on purpose, and nothing else of theirs is anywhere
    near it — not the doctor, not the laboratory, not the value, not the unit, not a word of the
    diagnosis or the medication, not the printed line, not the name of whose archive it is.

    The code was right here and the comment above it was not: it read "this archive's own forms
    printed", which is a sentence that invites the next reader to narrow the question and throw
    the vocabulary away. Measured before it was rewritten: on the live instance, narrowing takes
    the two smaller archives from 541 groups and 1133 spellings to 83 and 102 groups with 121 and
    134 spellings. Hence the last assertion, which is about the comment and not the code.
    """
    import epicrisis.indicator_proposals as proposals

    data_dir = two_archives
    # The vocabulary as it stands once both archives have been read: one group per test, each
    # holding the spelling of the archive that prints it.
    for mine in THEIRS.values():
        indicators.upsert(data_dir, None, mine["test"], [mine["test"]], "approved")

    # And a name of the second archive that no group holds yet, which is the question being asked.
    unheld = THEIRS["two"]["test"] + "-2"
    model = _AskedNothing()
    propose_indicators(data_dir, [{"name": unheld, "folded": indicators.fold(unheld), "units": [], "times": 1}],
                       model, data_dir)  # fmt: skip

    assert len(model.asked) == 1, "the model was not asked anything"
    question = model.asked[0]

    # The dictionary crosses: the group of the other archive's test is in the question, under the
    # label somebody gave it, because that is how a spelling lands in a group that already exists.
    assert THEIRS["one"]["test"] in question["existing"]
    # Nothing else of theirs does, in either half of the question.
    whole = question["existing"] + "\n" + question["names"]
    theirs = [value for value in _nothing_of_theirs("one") if value != THEIRS["one"]["test"]]
    assert [word for word in theirs if word in whole] == [], "the question carries more than the dictionary"
    assert THEIRS["one"]["whose"] not in whole
    # And the names being grouped are this archive's and only this archive's.
    assert question["names"].strip().startswith(unheld)

    # The sentence that was wrong about the code beneath it. A comment inviting the next reader to
    # narrow this question is how the vocabulary gets locked per archive by mistake.
    said = Path(proposals.__file__).read_text(encoding="utf-8")
    assert "A group is shown with what this archive's own forms printed" not in said
    assert "the vocabulary of this whole instance holds" in said


def _a_chat_recording(data_dir: Path, **what_it_says) -> dict:
    """A conversation in the shape a version of this program once wrote them.

    Written through `new_chat` and then cut down, so that the only difference from a chat of today
    is the fields under argument — a hand-written file would also be testing the reader.
    """
    from epicrisis import ask

    chat = ask.new_chat(data_dir)
    path = ask.chats_dir(data_dir) / f"{chat['id']}.json"
    chat = {**json.loads(path.read_text(encoding="utf-8")), **what_it_says}
    path.write_text(json.dumps(chat), encoding="utf-8")
    return chat


def _answered_with_the_archive_switched_under_it(data_dir: Path, chat_id: str, switch_to: str, monkeypatch) -> dict:
    """Answer one question, and switch the archive from another tab while it is being answered.

    The tools are asked afterwards, exactly as the model would ask them: through the MCP server
    this program starts for the question, built with whatever `answer` pinned it to. So what comes
    back here is what a model would have been handed, and not an assertion about an argument.
    """
    import asyncio

    from epicrisis import ask
    from epicrisis.mcp_server import build_server
    from epicrisis.sources import SourceRegistry

    handed = {}

    def one_question(data_dir, prompt, mode="as_printed", pinned_to=None):
        handed["pinned_to"] = pinned_to
        SourceRegistry(Path(data_dir)).set_active(switch_to)  # the other tab, mid-answer
        server = build_server(Path(data_dir), pinned_to=pinned_to)
        said = [str(asyncio.run(server.call_tool(tool, {}))) for tool in ("archive_overview", "list_documents", "value_names")]
        yield {"kind": "answer", "text": " ".join(said)}

    monkeypatch.setattr(ask, "_stream", one_question)
    ask.ask(data_dir, chat_id, "What does this archive hold?", run=lambda *args: None)
    ask.answer(data_dir, chat_id)
    stored = ask.load_chat(data_dir, chat_id)
    return {"handed": handed, "message": stored["messages"][-1]}


@pytest.mark.parametrize("what_it_says, called", [
    ({"archive_id": "", "archive": ""}, "neither an id nor a name"),
    ({"archive_id": "", "archive": THEIRS["one"]["whose"]}, "a name and no id"),
], ids=["nothing at all", "a name only"])  # fmt: skip
def test_an_old_conversation_is_answered_out_of_the_archive_it_is_filed_under(
    two_archives, monkeypatch, what_it_says, called
):
    """A conversation older than the field that says whose it is, answered while the archive moves.

    Both shapes were written by versions of this program and both are still read: a chat with
    nothing but the owner's name, and a chat with not even that, which can only be about the
    archive that was the only one there at the time. `list_chats` and `load_chat` work out which
    archive each belongs to and show it in that archive alone.

    Answering did not ask that question. It read the id, found it empty, and handed the tools no
    archive at all — so the MCP server fell back to whichever archive was open at that moment, and
    a question takes tens of seconds to answer while the archive can be switched from any page in
    another tab. The comment directly above the line said exactly that about the case it did
    cover. Three of the five conversations on the live instance are the second shape.
    """
    data_dir = two_archives
    chat = _a_chat_recording(data_dir, **what_it_says)

    answered = _answered_with_the_archive_switched_under_it(data_dir, chat["id"], THEIRS["two"]["id"], monkeypatch)

    assert answered["handed"]["pinned_to"] == THEIRS["one"]["id"], called
    said = answered["message"]["text"] + " " + str(answered["message"].get("error") or "")
    theirs = [*_nothing_of_theirs("two"), THEIRS["two"]["whose"]]
    assert [word for word in theirs if word in said] == [], f"the other archive answered: {called}"
    assert THEIRS["one"]["test"] in said, "and the archive it is filed under did answer"


def test_a_conversation_about_an_archive_that_is_not_here_is_refused_and_says_so(two_archives, monkeypatch):
    """The one shape nothing on the list settles, and the only honest answer to it.

    A conversation naming an archive by an id that is no longer on the list cannot be shown in any
    archive — `load_chat` hides it from every owner — and so there is nobody it could be asked
    about. Answering it from whichever archive is open is the defect; answering it from the first
    archive would be a guess about whose records these are, which is the one guess this program
    never makes. So it is refused, in a sentence that names the file the conversation is in, says
    that nothing in it is lost, and gives the two things that put it right.
    """
    data_dir = two_archives
    chat = _a_chat_recording(data_dir, archive_id="cccc3333", archive="")

    answered = _answered_with_the_archive_switched_under_it(data_dir, chat["id"], THEIRS["two"]["id"], monkeypatch)

    assert answered["handed"] == {}, "the question was put to a model over nobody's archive"
    message = answered["message"]
    assert message["state"] == "failed"
    assert f"{chat['id']}.json" in message["error"], "the refusal does not name the file"
    assert "Nothing in it is lost" in message["error"]
    assert "Ask page of the archive you mean" in message["error"], "the refusal gives no way out"
    said = message["text"] + " " + message["error"]
    both = [*_nothing_of_theirs("one"), *_nothing_of_theirs("two")]
    assert [word for word in both if word in said] == [], "the refusal carries somebody's records"


def test_a_conversation_is_only_ever_answered_out_of_an_archive_it_is_shown_in(two_archives):
    """The two sides of one question, held to each other for every shape a chat comes in.

    `_belongs` decides which archive a conversation is shown in; `whose_archive` decides which
    archive it is answered from. Nothing made them agree, and they did not: a conversation shown
    in the first archive alone was answered from whichever archive was open. So the rule is
    written here rather than hoped for, and in both directions, which is where this test used to
    stop. It excused one shape — a name two archives answer to settles nothing, so the
    conversation is answered from neither — and that shape was exactly the one still wrong: it
    was answered from neither and *shown in both*, with its title, the questions a person asked
    about their own health and the answers quoting their values, standing on the page of somebody
    else's archive. "Not on a page" is the first line of the constitution, and an archive a
    conversation is not answered from is an archive it is not shown in either.

    So it is one question with one answer: shown in exactly the archive it is answered from, and
    in no other. One function decides it and both sides ask that one.
    """
    from epicrisis import ask
    from epicrisis.sources import SourceRegistry

    data_dir = two_archives
    sources = SourceRegistry(data_dir).list()
    shapes = [
        {"archive_id": THEIRS["one"]["id"], "archive": THEIRS["one"]["whose"]},  # a chat of today
        {"archive_id": "", "archive": THEIRS["two"]["whose"]},  # a name and no id
        {"archive_id": "", "archive": ""},  # neither, from before there was anybody else
        {"archive_id": "cccc3333", "archive": ""},  # an archive that is not here any more
        {"archive_id": "", "archive": "Dovbushenko Myrosya"},  # a name no archive here answers to
    ]
    for shape in shapes:
        chat = _a_chat_recording(data_dir, **shape)
        answered_from, why_not = ask.whose_archive(data_dir, chat)
        assert bool(answered_from) != bool(why_not), ("one or the other, never both", shape)
        shown_in = [source.id for source in sources
                    if ask.load_chat(data_dir, chat["id"], source) is not None]  # fmt: skip
        assert shown_in == ([answered_from] if answered_from else []), (shape, answered_from, shown_in)

    # And the shape this used to excuse: one name, two archives of it. A person keeping the
    # archive of a parent and of a child of the same name is not an odd case, and nothing on the
    # list tells those two conversations apart — so the conversation is answered from neither,
    # and shown in neither, rather than shown in both.
    registry = SourceRegistry(data_dir)
    second_folder = Path(two_archives).parent / "a-second-folder"
    second_folder.mkdir()
    also_named = registry.add(str(second_folder), THEIRS["one"]["whose"])
    of_that_name = _a_chat_recording(data_dir, archive_id="", archive=THEIRS["one"]["whose"])
    answered_from, why_not = ask.whose_archive(data_dir, of_that_name)

    assert answered_from is None and "more than one archive" in why_not
    for source in registry.list():
        assert ask.load_chat(data_dir, of_that_name["id"], source) is None, source.id
    assert [chat["id"] for chat in ask.list_chats(data_dir, also_named)] == []
    shown = [source.id for source in registry.list()
             if of_that_name["id"] in [one["id"] for one in ask.list_chats(data_dir, source)]]  # fmt: skip
    assert shown == [], f"a conversation nothing settles is on the page of {shown}"


@pytest.mark.parametrize("page", ["the timeline", "the conversations"])
def test_one_page_is_drawn_out_of_one_archive_however_the_bar_is_used(two_archives, monkeypatch, page):
    """Two readings of which archive is open, inside one page, and a switch between them.

    The same shape as the tool call above, through the other door. A page asked `_showing` once to
    open the index and again, further down, to load the file of decisions laid over its rows — and
    the switcher stands in the bar of every page, so the switch is an ordinary POST that the server
    answers on another thread while this page is still being built. Nothing holds a request still.

    What a switch landing between the two readings drew: one archive's documents under the other
    archive's joined names, on the page this program opens on. The page of conversations had the
    same pair, between the conversation it shows and the list it shows it in.

    Held by the archive the second reading is given, because that is the defect itself and it does
    not depend on how a template chooses to print a label. The page's own body is swept after it
    for the whole forbidden set, so a leak arriving some other way is caught as well.
    """
    from epicrisis import ask, people
    from epicrisis.sources import SourceRegistry
    from epicrisis.web import app as the_app

    data_dir = two_archives
    switched, asked_about = [], []

    def the_other_tab() -> None:
        """The archive switched from a page open somewhere else, mid-request. Once, so that a
        second reading inside the same request is not switched back and quietly agrees."""
        if not switched:
            SourceRegistry(data_dir).set_active(THEIRS["two"]["id"])
            switched.append(THEIRS["two"]["id"])

    def watching(call, note):
        """Call through, remembering which archive it was asked about, and switch after the first."""

        def watched(*args, **rest):
            note(*args, **rest)
            answer = call(*args, **rest)
            the_other_tab()
            return answer

        return watched

    if page == "the timeline":
        address = "/"
        # The index is opened first and the decisions are loaded second, so the switch is held the
        # instant the index is open and the archive is asked for again below.
        monkeypatch.setattr(the_app, "open_index", watching(the_app.open_index, lambda *a, **k: None))
        monkeypatch.setattr(people, "load",
                            lambda data_dir_given, source_id, *a, **k: asked_about.append(source_id))  # fmt: skip
    else:
        mine = _a_chat_recording(data_dir, archive_id=THEIRS["one"]["id"],
                                   archive=THEIRS["one"]["whose"], title="A question of their own")
        address = f"/ask/{mine['id']}"
        monkeypatch.setattr(the_app, "load_chat", watching(the_app.load_chat, lambda *a, **k: None))
        monkeypatch.setattr(the_app, "list_chats",
                            lambda data_dir_given, source=None, *a, **k: asked_about.append(
                                getattr(source, "id", source)) or [])  # fmt: skip

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050",
                        headers={"host": "localhost:8050"})  # fmt: skip
    with client:
        answer = client.get(address)

    assert answer.status_code == 200
    assert switched, "the archive was never switched while the page was being built, so this proves nothing"
    assert SourceRegistry(data_dir).active().id == THEIRS["two"]["id"], "the switch did not take"
    assert asked_about, f"{address} never asked a second time which archive it is of"
    assert set(asked_about) == {THEIRS["one"]["id"]}, (
        f"{address} was drawn out of one archive and then asked about another: {asked_about}")
    for theirs in _nothing_of_theirs("two"):
        assert theirs not in answer.text, f"{address} shows {theirs!r} of the other archive"


def test_the_bar_of_a_page_names_the_archive_the_page_under_it_was_drawn_from(two_archives, monkeypatch):
    """The owner's name over the page, and the page. One switch, and they were two people.

    The other half of the test above, and the half its own sweep cannot reach. The name of
    whoever an archive belongs to is the one thing of theirs that is ever shown — it stands in
    the picker in the bar of every page, and `_nothing_of_theirs` leaves it out of the forbidden
    set for that reason. So a bar naming the wrong person over the right documents passes every
    assertion in this file, and it was reachable by three ordinary acts: open the timeline, let
    the body be built out of the archive that is open, and switch the archive from another tab
    while it is being built.

    The body was read once and carried; the bar was not. It asked the list of archives as it
    rendered — after the handler had finished — so the header printed the owner it found then,
    over one person's documents, their doctors and their values, with the picker marking the
    other archive as the open one. "Not on a page" is the first line of the constitution, and a
    page whose heading says one person and whose body says another is that line broken whichever
    of the two the reader believes.

    Held by the two things the bar says about whose archive it is: the name in the title of the
    page, and which archive of the picker is marked as the open one. Every archive's owner is
    named in that picker on purpose, so the question is never whether the other name is on the
    page — it is which of the two the page says it was drawn from.
    """
    from epicrisis.sources import SourceRegistry
    from epicrisis.web import app as the_app

    data_dir = two_archives
    switched = []

    def the_other_tab() -> None:
        """The archive switched from a page open somewhere else, while this page is being built."""
        if not switched:
            SourceRegistry(data_dir).set_active(THEIRS["two"]["id"])
            switched.append(THEIRS["two"]["id"])

    # The switch lands while the body of the page is being built out of the index, which is the
    # window the bar used to read the list of archives in: the handler had finished and the
    # template had not started.
    drawing = the_app.query_index.who_made_them

    def who_made_them(*args, **rest):
        answer = drawing(*args, **rest)
        the_other_tab()
        return answer

    monkeypatch.setattr(the_app.query_index, "who_made_them", who_made_them)

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050",
                        headers={"host": "localhost:8050"})  # fmt: skip
    with client:
        answer = client.get("/")

    assert answer.status_code == 200
    assert switched, "the archive was never switched while the page was being built, so this proves nothing"
    assert SourceRegistry(data_dir).active().id == THEIRS["two"]["id"], "the switch did not take"
    # Whose archive this is, printed in the title of every page and beside the picker in its bar.
    # Both come from one answer, and that answer is the archive the documents below came out of.
    assert f"· {THEIRS['one']['whose']} ·" in answer.text, (
        "the title of the page does not name the archive its documents came out of")
    # And which archive the picker says is open. Both names stand in it, which is the one thing
    # of theirs that is ever shown; exactly one of them carries the mark.
    assert f'value="{THEIRS["one"]["id"]}" selected>' in answer.text, (
        "the picker does not say this page is of the archive its documents came out of")
    assert f'value="{THEIRS["two"]["id"]}" selected>' not in answer.text, (
        "the picker over one person's documents says the other archive is the open one")
    # And the body is still the body it was: the archive that was open when the page began.
    assert THEIRS["one"]["test"] in answer.text
    for theirs in _nothing_of_theirs("two"):
        assert theirs not in answer.text, f"the page shows {theirs!r} of the other archive"


#: The two addresses of this dashboard that ask a second time which archive they are about, and
#: the one door that does it: `ask.list_chats` and `ask.load_chat` work out for themselves which
#: archive a conversation belongs to, out of the list, because a conversation written before that
#: field existed says only its owner's name — see `ask._one_archive_or_none`, which is the one
#: place that decides it. What they read the list for is which archives there are and in what
#: order, not which of them is open, so a switch landing in the middle of it cannot change the
#: answer; it is a cost and not a seam. /ask/<id> reads it once more where the conversation at
#: that address exists, which the one asked for here does not.
#:
#: Everything else answers out of the one reading its request was decided by. Widening this means
#: editing these two lines, which is why they are written out.
ASKS_AGAIN = {"/ask": 2}


def test_every_page_asks_once_which_archive_it_is_of(two_archives):
    """One reading of the list of archives per request, counted rather than reasoned about.

    Three closures in `web/app.py` answered the question "which archive is open", and each of them
    read sources.json afresh every time it was called. The shell of a page asked three times for
    how far the instance has got, once for the picker and once for the line about the index; the
    handler asked once or twice more; and one GET of the timeline read that file ten times, the
    status page fifteen. Every one of those readings is a chance to be told a different archive,
    because the switch is an ordinary POST the server answers on another thread and nothing holds
    a request still — and four of them had already turned out to be exactly that, found one at a
    time and after the fact.

    So the archive is decided once, at the top of the request, and handed on as a value. This
    counts the readings, over every address the application serves rather than a list written
    here, so a page added next month is measured without anybody remembering this test.
    """
    reads: dict[str, int] = {}
    counting = {"n": 0}
    whole = Path.read_text

    def read_text(self, *rest, **more):
        if self.name == "sources.json":
            counting["n"] += 1
        return whole(self, *rest, **more)

    client = TestClient(create_app(two_archives, background_jobs=False), base_url="http://localhost:8050",
                        raise_server_exceptions=False)  # fmt: skip
    app = client.app
    showing = THEIRS["one"]
    standing_in = {"chat_id": "none", "source_id": showing["id"], "sha256": showing["id"] * 8,
                   "first_page": "1", "page": "1", "indicator_id": "none"}  # fmt: skip
    addresses = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if "GET" not in getattr(route, "methods", set()) or path.endswith("/image"):
            continue
        address = path
        for name, value in standing_in.items():
            address = address.replace("{" + name + "}", value)
        if "{" not in address:
            addresses.append(address)

    assert len(addresses) >= 15, "the sweep found almost no addresses; it is counting nothing"
    try:
        Path.read_text = read_text
        for address in addresses:
            counting["n"] = 0
            client.get(address, follow_redirects=False)
            reads[address] = counting["n"]
    finally:
        Path.read_text = whole

    assert reads, "nothing was counted"
    assert {address: count for address, count in reads.items() if count != 1} == ASKS_AGAIN, reads
