"""The page of doctors and clinics asked directly: what it shows, and what each press does.

This is the page the first entry of the constitution was last broken on, twice over. Both halves
of it used to be a route, so nothing could ask it a question without fetching an address and
reading the answer out of the markup — and the press that wrote one person's spellings into
another person's own file of decisions could only be caught by drawing a page, switching the
archive with the picker, and pressing a button that was already on the screen.

`who_view` and the four presses in `epicrisis/web/who.py` are where those are decided now, and
this is them asked as questions. The press hands back what it stored and what it refused as a
value, which is what lets a test ask a press about somebody else's archive whether it wrote
nothing — rather than inferring it from a page.

The door is the real one: `_the_open_archive` is imported from `epicrisis.web.app`, the single
place every page that writes goes through, so nothing here is proved against a lenient stand-in.
"""

import ast
import inspect
from pathlib import Path

import pytest

from epicrisis import people
from epicrisis.sources import SourceRegistry, TheArchives
from epicrisis.web import who
from epicrisis.web.app import _the_open_archive, create_app

from test_the_wall_between_people import THEIRS, _an_archive, _both_on_the_list, _printed_a_second_way

#: The two archives of the sweep that guards the wall, which share no substring at all. Theirs is
#: the right fixture for this: every assertion below about "nothing of the other archive" is an
#: assertion about strings that cannot appear by accident.
MINE, THEIRS_TOO = THEIRS["one"], THEIRS["two"]


@pytest.fixture
def two_archives(tmp_path):
    """Two people on one server with the first open, and that one reading of the list as a value.

    The first archive prints its laboratory twice, once with a comma after it, so that its page
    offers a family to join: a page with nothing on it to press cannot be pressed at the wrong
    moment, and half of this file is about a press.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    _both_on_the_list(data_dir, "one")
    for mine in THEIRS.values():
        _an_archive(data_dir, mine)
    second_spelling = _printed_a_second_way(data_dir, MINE)
    return data_dir, SourceRegistry(data_dir).as_one_reading(), second_spelling


def test_the_page_of_doctors_gathers_what_it_shows(two_archives):
    """Both tabs of it, asked for without an address and without a template."""
    data_dir, archives, second_spelling = two_archives

    clinics = who.who_view(data_dir, MINE["id"], kind="institution")
    assert clinics["current"] == "who" and clinics["kind"] == "institution"
    assert clinics["archive"] == MINE["id"], "the forms of this page carry whose spellings these are"
    printed = sorted(one["name"] for one in clinics["makers"])
    assert printed == sorted([MINE["provider"], second_spelling])
    # Two spellings of one laboratory, every word of the shorter standing in the longer: that is
    # the one shape the word count offers, and it is offered as a family rather than as a pair.
    # Neither of them is a group yet, so the family stands for two printed spellings and says so.
    assert [one.names for one in clinics["proposals"]] == [(MINE["provider"], second_spelling)]
    assert clinics["proposals"][0].under == {} and clinics["proposals"][0].spellings == 2
    assert clinics["proposals"][0].said == "2 spellings that look like one name"
    assert clinics["groups"] == [] and clinics["thought"] == [] and clinics["refused"] == []
    assert clinics["trouble"] == "" and clinics["elsewhere"] is None

    # And nothing of the other person's, on either tab. This is the sweep's assertion asked of
    # the gathering itself, which is the layer the leak was actually in.
    doctors = who.who_view(data_dir, MINE["id"], kind="doctor")
    for gathered in (clinics, doctors):
        written = repr(gathered)
        assert THEIRS_TOO["provider"] not in written and THEIRS_TOO["doctor"] not in written


def test_the_heading_counts_what_it_holds_instead_of_promising_every_name(two_archives):
    """§7, over the one promise on these pages that somebody acted on.

    The heading read "every institution and every doctor named on these documents". A name reaches
    this page by having been read into the provider field or the doctor field of a document; a
    surname printed inside a document's own text and nowhere else is in neither, and nothing on
    this page can find it. Measured on the archive the promise was read on: the doctor field is
    filled on 20 of its 414 documents, while 38 documents carry a labelled surname in their
    transcribed text — 20 distinct names — that is in no field. The owner looked here for two
    doctors he had seen, by their surnames, found neither, and concluded the archive did not hold
    them.

    This fixture holds two documents: both name the laboratory, and one of them also names the
    doctor. So both halves of the sentence are asserted here — the tab where some documents name
    nobody, and the tab where every one of them names somebody — and the first number is the
    length of the list the page draws under it, so the two cannot disagree.
    """
    data_dir, _archives, second_spelling = two_archives

    doctors = who.who_view(data_dir, MINE["id"], kind="doctor")
    clinics = who.who_view(data_dir, MINE["id"], kind="institution")

    assert doctors["holds"] == (
        "1 doctor, read off 1 of the 2 documents of this archive. The other 1 prints no doctor "
        "that was read: a name standing only inside a document's own text is not on this page.")
    assert clinics["holds"] == "2 institutions, read off every one of the 2 documents of this archive."
    # The count in the sentence is the number of rows under it, and not a second count of its own.
    assert doctors["holds"].startswith(f"{len(doctors['makers'])} doctor")
    assert clinics["holds"].startswith(f"{len(clinics['makers'])} institution")
    assert second_spelling in {one["name"] for one in clinics["makers"]}


def test_the_heading_says_nothing_it_cannot_count(two_archives):
    """An archive with no index of its own, and a tab with nothing under it at all.

    The sentence is three counted numbers, so where there is nothing to count it does not appear
    rather than appearing with noughts in it — the page already says "No document here names a
    doctor yet" where it stands, and a heading claiming "0 doctors, read off 0 of the 0 documents"
    over that is the second count §7 forbids.
    """
    data_dir, _archives, _second = two_archives
    assert who.who_view(data_dir, "an-archive-with-no-index-of-its-own")["holds"] == ""
    # And an archive that holds documents and names nobody of this kind says which it is.
    nobody = who.what_the_page_holds("doctor", 0, {"documents": 7, "doctor": 0, "institution": 7})
    assert nobody == "None of the 7 documents of this archive names a doctor."
    assert who.what_the_page_holds("institution", 0, {"documents": 0}) == "This archive holds no documents yet."


def test_the_other_tab_is_named_where_this_one_is_empty_and_that_one_is_not(two_archives):
    """A folder of laboratory printouts names the laboratory everywhere and the doctor nowhere.

    The menu item reads "Doctors and clinics" and opens on the doctors, so that archive met "No
    document here names a doctor yet" with every name in it one tab away and nothing saying so.
    """
    data_dir, _archives, _second = two_archives
    # The second archive names a doctor on its one document, so neither of its tabs is empty.
    # The first archive's second document names a laboratory and no doctor, and its first names
    # both — so the shape is made here instead, by asking for a kind nothing is printed under.
    doctors = who.who_view(data_dir, MINE["id"], kind="doctor")
    assert doctors["makers"], "this fixture prints a doctor, so this tab is not the empty one"
    assert doctors["elsewhere"] is None

    nothing_at_all = who.who_view(data_dir, "an-archive-with-no-index-of-its-own")
    assert nothing_at_all["makers"] == [] and nothing_at_all["elsewhere"] is None
    assert nothing_at_all["current"] == "who", "a missing index is an answer and not a fault"
    assert nothing_at_all["archive"] == "an-archive-with-no-index-of-its-own"


def test_an_unknown_kind_is_the_doctors_and_draws_no_empty_page(two_archives):
    """The tabs are drawn from `kind`, so a word that is neither leaves the page about nothing."""
    data_dir, _archives, _second = two_archives
    nonsense = who.who_view(data_dir, MINE["id"], kind="a-third-kind-of-thing")
    assert nonsense["kind"] == "doctor"
    assert nonsense == who.who_view(data_dir, MINE["id"], kind="doctor")


def test_the_page_cannot_be_gathered_without_naming_an_archive(two_archives):
    """The first entry of the constitution: a door into an archive has no default for which one.

    Checked as the signature and not only as a call, because the way this goes wrong is somebody
    writing `the_archive: str | None = None` to save a caller the trouble.
    """
    with pytest.raises(TypeError):
        who.who_view(two_archives[0])
    which = inspect.signature(who.who_view).parameters["the_archive"]
    assert which.default is inspect.Parameter.empty
    assert which.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD


@pytest.mark.parametrize("press, asked", [
    ("joined", {"names": ["one spelling", "another spelling"], "label": "one spelling"}),
    ("declined", {"names": ["one spelling", "another spelling"]}),
    ("reconsidered", {"names": ["one spelling", "another spelling"]}),
    ("separated", {"label": "one spelling"}),
])
def test_a_press_about_another_archive_writes_nothing_and_names_the_cause(two_archives, press, asked):
    """The leak this page was found with, asked of the press itself.

    Three ordinary acts reach it: draw the page of one archive, switch the archive with the picker
    that stands in the bar of every page, press a button on the page still open. So the reading of
    the list says the first archive is open and the address of the form names the second — which is
    exactly what the server holds at that moment — and every one of the four presses has to refuse,
    say which archive it refused about, and write not one byte into either person's file.
    """
    data_dir, archives, _second = two_archives
    assert archives.showing_id == MINE["id"], "the first archive is the one that is open"
    before = {which: people.load(data_dir, mine["id"]) for which, mine in THEIRS.items()}

    decided = getattr(who, press)(data_dir, archives, THEIRS_TOO["id"],
                                  the_open_archive=_the_open_archive, kind="institution", **asked)  # fmt: skip

    assert decided.stored == (), "a press about another archive stored something"
    assert decided.a_dead_end is True
    assert decided.refused == (who.NOT_THIS_ARCHIVE,)
    assert "other than the one open now" in decided.trouble, "the refusal does not name the cause"
    assert decided.kind == "institution", "the way back is to the tab the press was made on"
    assert {which: people.load(data_dir, mine["id"]) for which, mine in THEIRS.items()} == before, (
        "a decision about one archive was written into a file of somebody else's own decisions")
    # And nothing of the archive it was refused about is in what came back, not even to explain
    # itself: the sentence names the switch, never the person.
    assert THEIRS_TOO["whose"] not in repr(decided) and THEIRS_TOO["provider"] not in repr(decided)


def test_a_press_about_an_archive_this_server_does_not_hold_is_the_same_dead_end(two_archives):
    """An address naming nothing at all goes the same way as an address naming somebody else."""
    data_dir, archives, _second = two_archives
    decided = who.joined(data_dir, archives, "no-such-archive-anywhere",
                         the_open_archive=_the_open_archive, kind="doctor",
                         names=[MINE["doctor"], MINE["doctor"] + "."])  # fmt: skip
    assert decided.a_dead_end is True and decided.stored == ()


def test_the_press_that_was_drawn_where_it_lands_does_store(two_archives):
    """Or every refusal above is a statement about a press that never worked anyway."""
    data_dir, archives, second_spelling = two_archives

    decided = who.joined(data_dir, archives, MINE["id"], the_open_archive=_the_open_archive,
                         kind="institution", names=[MINE["provider"], second_spelling],
                         label=MINE["provider"])  # fmt: skip

    assert decided.a_dead_end is False and decided.refused == ()
    assert decided.stored == ("2 spellings joined as one institution",)
    settled = people.settled(people.load(data_dir, MINE["id"]), "institution")
    assert [one.label for one in settled] == [MINE["provider"]]
    assert sorted(settled[0].names) == sorted([MINE["provider"], second_spelling])
    # And the archive it was not about is untouched.
    assert people.load(data_dir, THEIRS_TOO["id"]) == []

    # A group that is settled is no longer a question, so the page stops offering the family.
    assert who.who_view(data_dir, MINE["id"], kind="institution")["proposals"] == []

    # And one press takes it apart again, by the label it was settled under.
    apart = who.separated(data_dir, archives, MINE["id"], the_open_archive=_the_open_archive,
                          kind="institution", label=MINE["provider"])  # fmt: skip
    assert apart.stored == (f"the group under “{MINE['provider']}” taken apart",)
    assert people.settled(people.load(data_dir, MINE["id"]), "institution") == []


def test_a_carried_group_stands_under_its_own_heading_and_not_a_model_s(two_archives):
    """A group the migration could not place is not a model's proposal and not a join of this
    archive's, and the page has one heading for each of those three. Put in the model's list it
    would read "a model thinks these are one" over a decision this person made themselves, which
    is the third entry's defect in the one place where it is also the first entry's: the archive
    it stands in is not the archive the press was made in.
    """
    data_dir, _archives, second_spelling = two_archives
    people.save(data_dir, MINE["id"], [
        people.Group(kind="institution", label=MINE["provider"],
                     names=[MINE["provider"], second_spelling], settled=False, carried=True,
                     why=people.CARRIED_FROM_THE_INSTANCE),
    ])  # fmt: skip

    clinics = who.who_view(data_dir, MINE["id"], kind="institution")

    assert [one.names for one in clinics["carried"]] == [sorted([MINE["provider"], second_spelling])]
    assert clinics["thought"] == [], "not a model's, and the heading over it says whose it is"
    assert clinics["groups"] == [], "and not joined by anybody in this archive"
    assert clinics["carried"][0].why == people.CARRIED_FROM_THE_INSTANCE
    # Nor is the family offered a second time underneath: it is already a question on this page.
    assert clinics["proposals"] == []
    # The template has a block of its own for them, with the two presses a question needs.
    drawn = (Path(who.__file__).parent / "templates" / "who.html").read_text(encoding="utf-8")
    assert "{% if carried %}" in drawn
    assert "Carried in from before each archive kept its own joins" in drawn


def test_a_press_that_joins_nothing_says_so_instead_of_looking_like_a_join(two_archives):
    """One spelling ticked out of five looked exactly like a join that had worked.

    The only way to find out it had not was to read the list underneath, so the sentence is the
    whole point of the press having an answer at all.
    """
    data_dir, archives, _second = two_archives

    decided = who.joined(data_dir, archives, MINE["id"], the_open_archive=_the_open_archive,
                         kind="institution", names=[MINE["provider"]])  # fmt: skip

    assert decided.stored == () and decided.a_dead_end is False
    assert "One name on its own is not a join" in decided.trouble
    assert "Nothing was changed." in decided.trouble
    assert "Tick at least two" in decided.trouble, "a refusal with no way out is a dead end"
    assert people.load(data_dir, MINE["id"]) == []


def test_a_label_that_is_none_of_the_ticked_spellings_is_refused_whole(two_archives):
    """A label standing over names it is not one of is how a label renames something elsewhere."""
    data_dir, archives, second_spelling = two_archives
    decided = who.joined(data_dir, archives, MINE["id"], the_open_archive=_the_open_archive,
                         kind="institution", names=[MINE["provider"], second_spelling],
                         label=THEIRS_TOO["provider"])  # fmt: skip
    assert decided.stored == ()
    assert "The spelling to keep is not one of the spellings being joined." in decided.trouble
    assert people.load(data_dir, MINE["id"]) == [], "a refused join wrote a group anyway"


@pytest.mark.parametrize("press", ["joined", "declined", "reconsidered"])
def test_a_press_about_neither_a_doctor_nor_an_institution_comes_back_on_the_doctors(two_archives, press):
    """And is refused before the door, so nothing is written and nothing is read either."""
    data_dir, archives, _second = two_archives
    decided = getattr(who, press)(data_dir, archives, MINE["id"], the_open_archive=_the_open_archive,
                                  kind="a-third-kind-of-thing", names=["a name", "another name"])  # fmt: skip
    assert decided.stored == () and decided.a_dead_end is False
    assert decided.kind == "doctor", "the page it comes back on has to be a tab that exists"
    assert decided.refused == (who.NOT_A_KIND,)
    assert people.load(data_dir, MINE["id"]) == []


def test_taking_a_group_apart_is_asked_about_the_word_the_press_carried(two_archives):
    """And offers a way back to a tab that exists, which is not the same word.

    `people.split` is asked the kind the form sent and the page comes back on it, because that is
    what it did before this moved. The dead end is the one place that sanitises it: a button back
    to `/who?kind=a-third-kind-of-thing` is a button to a page with four links and nothing under
    them.
    """
    data_dir, archives, _second = two_archives
    on_its_own = who.separated(data_dir, archives, MINE["id"], the_open_archive=_the_open_archive,
                               kind="a-third-kind-of-thing", label="a label of nothing")  # fmt: skip
    assert on_its_own.kind == "a-third-kind-of-thing", "the page comes back on the word it carried"

    dead_end = who.separated(data_dir, archives, THEIRS_TOO["id"], the_open_archive=_the_open_archive,
                             kind="a-third-kind-of-thing", label="a label of nothing")  # fmt: skip
    assert dead_end.a_dead_end is True
    assert dead_end.kind in people.KINDS, "the way out of a dead end is a tab that exists"


def test_a_press_with_no_label_at_all_takes_nothing_apart(two_archives):
    """A form can always be made to say nothing, and nothing is what it then does."""
    data_dir, archives, second_spelling = two_archives
    who.joined(data_dir, archives, MINE["id"], the_open_archive=_the_open_archive,
               kind="institution", names=[MINE["provider"], second_spelling])  # fmt: skip
    before = people.load(data_dir, MINE["id"])
    decided = who.separated(data_dir, archives, MINE["id"], the_open_archive=_the_open_archive,
                            kind="institution", label="")  # fmt: skip
    assert decided.stored == () and decided.refused == ()
    assert people.load(data_dir, MINE["id"]) == before


def test_a_refusal_is_taken_back_only_when_two_spellings_are_ticked(two_archives):
    """Unticking all but one leaves the refusal standing, and says nothing was changed."""
    data_dir, archives, second_spelling = two_archives
    who.declined(data_dir, archives, MINE["id"], the_open_archive=_the_open_archive,
                 kind="institution", names=[MINE["provider"], second_spelling])  # fmt: skip
    said_no = people.refused(people.load(data_dir, MINE["id"]), "institution")
    assert len(said_no) == 1, "the refusal was not written"
    # A family that has been said no to is not offered again.
    assert who.who_view(data_dir, MINE["id"], kind="institution")["proposals"] == []

    one_only = who.reconsidered(data_dir, archives, MINE["id"], the_open_archive=_the_open_archive,
                                kind="institution", names=[MINE["provider"]])  # fmt: skip
    assert one_only.stored == ()
    assert people.refused(people.load(data_dir, MINE["id"]), "institution") == said_no

    both = who.reconsidered(data_dir, archives, MINE["id"], the_open_archive=_the_open_archive,
                            kind="institution", names=[MINE["provider"], second_spelling])  # fmt: skip
    assert both.stored == ("a refusal of 2 spellings taken back",)
    assert people.refused(people.load(data_dir, MINE["id"]), "institution") == []
    assert who.who_view(data_dir, MINE["id"], kind="institution")["proposals"] != []


def test_every_press_takes_which_archive_as_an_argument_with_no_default(two_archives):
    """The first entry of the constitution again, over the four doors that write.

    A default here would mean a press answering about whichever archive the server happened to
    have open, which is the failure this page is named for in CONSTITUTION.md §1.
    """
    for press in (who.joined, who.declined, who.reconsidered, who.separated):
        asked = inspect.signature(press).parameters
        for name in ("archives", "source_id", "data_dir"):
            assert asked[name].default is inspect.Parameter.empty, f"{press.__name__}.{name}"
        assert asked["the_open_archive"].default is inspect.Parameter.empty, press.__name__
        with pytest.raises(TypeError):
            press(two_archives[0])


def test_nothing_in_this_module_knows_about_the_web():
    """The routes are the shells. A module that imported FastAPI could not be asked a question
    without one, which is the whole of what this file is.

    Read off the imports rather than the text, because the text says the words: the module's own
    first paragraph is what promises this, and a promise is not what holds it.
    """
    tree = ast.parse(inspect.getsource(who))
    reached = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            reached |= {one.name for one in node.names}
        elif isinstance(node, ast.ImportFrom):
            reached.add(node.module or "")
    assert reached, "nothing was read off this module at all"
    for name in sorted(reached):
        first = name.split(".")[0]
        assert first in ("epicrisis", "collections", "contextlib", "dataclasses", "pathlib"), name


def test_the_two_places_the_defaults_are_written_say_the_same_thing(tmp_path):
    """FastAPI reads what an address may leave out off the route's own signature, so the defaults
    live in both places and are held together here."""
    app = create_app(tmp_path / "data", background_jobs=False)
    route = next(one for one in app.routes
                 if getattr(one, "path", None) == "/who" and "GET" in getattr(one, "methods", ()))  # fmt: skip
    asked = inspect.signature(route.endpoint).parameters
    gathered = inspect.signature(who.who_view).parameters
    assert sorted(set(asked) & set(gathered)) == ["kind", "trouble"]
    for name in ("kind", "trouble"):
        assert asked[name].default == gathered[name].default, name


def test_a_press_is_handed_the_one_door_the_routes_use(two_archives):
    """And the door is the one in web/app.py, not a second answer to the same question.

    ARCHITECTURE.md names four doors into an archive and says of each that it was the leak once
    and that each was a second place answering the same question differently. This is the test
    that there is no second place: the press asks whatever it is handed, and what the routes hand
    it is `_the_open_archive`.
    """
    data_dir, archives, second_spelling = two_archives
    asked: list[tuple[str, str | None]] = []

    def watched(archives_given: TheArchives, source_id: str):
        asked.append((source_id, archives_given.showing_id))
        return _the_open_archive(archives_given, source_id)

    who.joined(data_dir, archives, MINE["id"], the_open_archive=watched, kind="institution",
               names=[MINE["provider"], second_spelling])  # fmt: skip
    assert asked == [(MINE["id"], MINE["id"])], "the press did not go through the door it was handed"


def test_no_page_puts_what_is_being_looked_for_into_an_address():
    """The one thing the search route exists to keep out of addresses was being put in one.

    `/search` answers a POST, and the reason is written at that route: an address is kept in a
    browser's history, synced from there to a vendor's servers, offered in the address bar to
    whoever sits at the machine next, and written into the log of any tunnel in front of this
    dashboard. The page of doctors linked each name found in the text to `/search?q=<the name>` —
    a GET, with a person's surname in it.

    Read off the templates rather than off a rendered page: the names this is about are the ones
    found **in the text only**, which no archive built by these tests has, so a page with such a
    name on it is a page no test here can draw. What can be held to it is the markup, and the
    thing to catch is somebody writing that link again.

    Found by the interface role on 7 Oct 2026.
    """
    from pathlib import Path

    templates = Path(__file__).resolve().parent.parent / "epicrisis" / "web" / "templates"
    drawn = {file.name: file.read_text(encoding="utf-8") for file in templates.rglob("*.html")}
    assert len(drawn) > 10, "the templates moved"

    offenders = [name for name, text in drawn.items() if "/search?q=" in text]
    assert offenders == [], f"a page puts what is looked for into an address: {offenders}"
    # And what replaced it on the page of doctors is a press carrying the same word.
    assert 'action="/search"' in drawn["who.html"] and 'name="q"' in drawn["who.html"]


def test_the_printed_line_a_name_was_read_from_is_not_clipped():
    """The one line on this page that must be readable in full, and it was cut.

    `.makers dd { white-space: nowrap }` was written for the short line under each name — "41
    documents · 2013–2025" — and it caught the printed line of the document as well. Under a body
    that hides horizontal overflow, that does not push a line off the side: it cuts it, with no
    way to reach the rest.

    The line is not decoration. The template says so where it is drawn: it is what makes a wrong
    reading visible to anybody who reads it, which is the third of §4's conditions for letting a
    page offer a claim about a person's name at all.

    Read off the stylesheet, because the page that draws these lines needs an archive whose
    documents name doctors only inside their text, and no archive built by these tests has one.
    """
    from pathlib import Path

    styles = (Path(__file__).resolve().parent.parent / "epicrisis" / "web" / "static" / "app.css").read_text(encoding="utf-8")

    assert ".makers dd.note { white-space: normal;" in styles, "the printed line is nowrap again"
    # And the rule it is an exception to still stands, because the short lines want it.
    assert ".makers dd { margin: 0; color: var(--muted); white-space: nowrap; }" in styles
    # The exception has to come after the rule it narrows: at equal weight, order decides.
    assert styles.index(".makers dd.note") > styles.index(".makers dd { margin: 0")


def test_every_page_of_the_menu_says_which_page_it_is():
    """A page that does not name itself falls out of the menu under the person standing on it.

    The header keeps a page in the menu by comparing it with `current` — "whatever page a person
    typed their way to stays in the menu, so they can see where they are and get back out of it" —
    and an undefined name compared with a string is simply false, so Jinja said nothing and two
    pages dropped out wherever the menu is drawn short.
    """
    import re
    from pathlib import Path

    templates = Path(__file__).resolve().parent.parent / "epicrisis" / "web" / "templates"
    header = (templates / "_header.html").read_text(encoding="utf-8")
    named = set(re.findall(r'\("/[^"]*",\s*"([a-z]+)"', header))
    assert {"who", "card", "timeline"} <= named, "the menu no longer names its pages this way"

    for file in sorted(templates.glob("*.html")):
        text = file.read_text(encoding="utf-8")
        if "{% include \"_header.html\" %}" not in text:
            continue
        found = re.search(r'{%\s*set current = "([a-z]*)"\s*%}', text)
        assert found, f"{file.name} draws the menu and does not say which page it is"
        # An empty name is a page that is deliberately none of them — an address that could not
        # be read, something that is not here, something that went wrong. Written down rather
        # than left out, so that a page which simply forgot is still caught by this.
        assert found.group(1) in named or found.group(1) == "", \
            f"{file.name} names a page the menu does not have: {found.group(1)}"  # fmt: skip
