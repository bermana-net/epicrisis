"""The timeline page asked questions directly, with no address and no HTML in the way.

Every one of these assertions used to be reachable only by fetching `/` and reading the answer
out of the markup — the page's own counts were a hundred and sixty lines deep inside a FastAPI
handler, and nothing but a request could run them. So the counts that disagreed with each other
were all found by eye, on a screen, after they shipped: a heading counting the archive over a
list cut to one laboratory, a row of tabs counting the archive under a year that holds none, an
axis built from one set of years with another set of points drawn on it.

`timeline_view` is where those are decided now, and this is them asked as questions.
"""

import inspect

import pytest
from test_extract import FakeExtractBackend, setup  # noqa: F401

from epicrisis.web.app import create_app
from epicrisis.web.timeline import timeline_view

from test_ask import archive_index  # noqa: F401

#: A name no archive of this suite prints, so what it narrows to is nothing — which is the point.
#: Every count below taken under it has to be of nothing, and not of the archive.
NO_SUCH_INSTITUTION = "No institution of this name"


def test_the_year_strip_is_counted_by_the_view_that_will_be_drawn(archive_index):  # noqa: F811
    """The feed's strip counts the chosen type; the other two views must not.

    This is the refusal the long comment in `timeline_view` was bought with: a type carried over
    from the feed built the axis out of that type's years and then every type was drawn on it, so
    eleven points of forty stood from -31% to 107% of the width — ten off the left of a phone and
    the rest on the wrong year, which is a page stating a date that is not true.
    """
    data_dir, source, _labs = archive_index
    whole = [2003, 2011]

    feed = timeline_view(data_dir, source.id, view="feed", doc_type="lab_panel")
    assert [row["year"] for row in feed["years"]] == [2011], "the feed counts the type it lists"
    for other in ("lanes", "indicators"):
        drawn = timeline_view(data_dir, source.id, view=other, doc_type="lab_panel")
        assert [row["year"] for row in drawn["years"]] == whole, f"{other} narrowed its own axis"

    # A word in the address that is no view at all falls back to the feed, and the strip has to
    # fall back with it: it once read the raw word instead and drew the feed over every type.
    unknown = timeline_view(data_dir, source.id, view="nonsense", doc_type="lab_panel")
    assert unknown["years"] == feed["years"] and unknown["view"] == "feed"


def test_what_the_heading_counts_is_what_the_page_will_draw(archive_index):  # noqa: F811
    """`shown` is of the narrowed set in the feed, and of its own dots in the By type view.

    The heading printed the whole archive whatever was in force, so a feed cut to one laboratory
    read "41 documents · 2013-03-06 – 2025-09-21" above ten documents of 2019 to 2021, with no
    date in the heading belonging to anything on the page.
    """
    data_dir, source, _labs = archive_index

    feed = timeline_view(data_dir, source.id, provider=NO_SUCH_INSTITUTION)
    assert feed["overview"]["documents"] == 3, "the archive is still three documents"
    assert feed["shown"] == {"documents": 0, "first_date": None, "last_date": None}
    assert feed["total"] == 0 and feed["documents"] == []

    # And the two views beside it apply no name at all, because they list no documents one at a
    # time. A narrowing announced where nothing performs it is the defect the notice above the By
    # test view was written for, so their counts stay the archive's own.
    for other in ("lanes", "indicators"):
        drawn = timeline_view(data_dir, source.id, view=other, provider=NO_SUCH_INSTITUTION)
        assert drawn["shown"]["documents"] > 0, f"{other} narrowed by a name it does not apply"

    # The By type view counts off the dots it drew rather than asking again: it draws only the
    # documents that carry a date, so the feed's count would promise the undated one.
    lanes = timeline_view(data_dir, source.id, view="lanes")
    dots = sum(len(lane["documents"]) for lane in lanes["lanes"])
    assert lanes["shown"]["documents"] == dots


def test_every_tab_counts_what_pressing_it_will_show(archive_index):  # noqa: F811
    """With a year chosen, the row of types is counted inside that year and not over the archive.

    A tab read "consultation 3" in a year that holds none, and pressing it gave "Showing 0 of 0" —
    because every one of those links carries the year on. The same holds for a name chosen in one
    of the two cuts, which the links carry the same way.
    """
    data_dir, source, _labs = archive_index

    assert timeline_view(data_dir, source.id)["type_counts"] == {"lab_panel": 1, "insurance": 1, "discharge": 1}
    assert timeline_view(data_dir, source.id, year=2003)["type_counts"] == {"lab_panel": 0, "insurance": 0, "discharge": 1}
    assert timeline_view(data_dir, source.id, year=2011)["type_counts"] == {"lab_panel": 1, "insurance": 0, "discharge": 0}
    under_a_name = timeline_view(data_dir, source.id, provider=NO_SUCH_INSTITUTION)
    assert set(under_a_name["type_counts"].values()) == {0}

    # The Records and Paperwork tabs add up to the year they are counted in, so the row of tabs
    # adds up to the archive instead of leaving a person to guess what the difference was.
    for year, documents in ((None, 3), (2003, 1), (2011, 1)):
        view = timeline_view(data_dir, source.id, year=year)
        assert view["records_count"] + view["paperwork_count"] == documents, year

    # "1 document carries no date at all" is of the documents this page is about: counted over the
    # archive with a name chosen, it promises one of somebody else's, and the link under it
    # carries the name on.
    assert timeline_view(data_dir, source.id)["undated_count"] == 1
    assert under_a_name["undated_count"] == 0


def test_a_name_in_the_address_opens_the_cut_it_belongs_to(archive_index):  # noqa: F811
    """The Doctors and clinics page links to "/?doctor=…" and says nothing else.

    The control has to stand open under such a link rather than leave a person on a page narrowed
    by something they cannot see.
    """
    data_dir, source, _labs = archive_index

    assert timeline_view(data_dir, source.id, doctor="Nobody of this archive")["cut"] == "doctor"
    assert timeline_view(data_dir, source.id, provider=NO_SUCH_INSTITUTION)["cut"] == "institution"
    assert timeline_view(data_dir, source.id)["cut"] == ""
    assert timeline_view(data_dir, source.id, cut="nonsense")["cut"] == ""

    # The row of cuts is drawn in every view, so it is gathered in every view: a cut that appears
    # in one of the three and not in the others reads as the interface losing it.
    for kind in ("feed", "lanes", "indicators"):
        view = timeline_view(data_dir, source.id, view=kind)
        assert [one["name"] for one in view["institutions"]] == ["Synthetic Lab"], kind
        assert view["doctors"] == [], kind


def test_an_archive_with_no_index_is_an_answer_and_not_a_fault(archive_index):  # noqa: F811
    """The page that offers to build the index is drawn from the same gathering as the page itself."""
    data_dir, _source, _labs = archive_index
    nothing = timeline_view(data_dir, "an-archive-with-no-index-of-its-own")
    assert nothing["missing"] is True and nothing["current"] == "timeline"
    assert "documents" not in nothing, "nothing of anybody's is gathered over a missing index"


def test_the_timeline_cannot_be_gathered_without_naming_an_archive(archive_index):  # noqa: F811
    """The first entry of the constitution: a door into an archive has no default for which one.

    Checked as the signature and not only as a call, because the way this goes wrong is somebody
    writing `the_archive: str | None = None` to save a caller the trouble — which is exactly what
    `open_index` once had, and on an instance holding one archive it answered every caller that
    had simply not got round to naming it.
    """
    data_dir, _source, _labs = archive_index
    with pytest.raises(TypeError):
        timeline_view(data_dir)
    which = inspect.signature(timeline_view).parameters["the_archive"]
    assert which.default is inspect.Parameter.empty
    assert which.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD


def test_the_two_places_the_defaults_are_written_say_the_same_thing(tmp_path):
    """What an address that asked for nothing means is written twice, and must not drift.

    FastAPI reads the defaults off the route's own signature to know which parameters a query
    string may leave out, so they cannot live only in `timeline_view` — and a gatherer with no
    defaults at all would make every test of it a list of thirteen arguments. So they are in both
    places and held together here.
    """
    app = create_app(tmp_path / "data", background_jobs=False)
    route = next(one for one in app.routes if getattr(one, "path", None) == "/" and "GET" in getattr(one, "methods", ()))
    asked = inspect.signature(route.endpoint).parameters
    gathered = inspect.signature(timeline_view).parameters
    shared = sorted(set(asked) & set(gathered))
    assert shared == ["all_tests", "cut", "doc_type", "doctor", "material", "paperwork",
                      "provider", "skip", "test", "undated", "view", "year"]  # fmt: skip
    for name in shared:
        assert asked[name].default == gathered[name].default, name
        assert asked[name].annotation == gathered[name].annotation, name


def test_the_count_of_tests_is_of_the_archive_and_not_of_the_cut_list(archive_index):  # noqa: F811
    """"Showing 40 of N tests" has to be the archive's N, and the link has to show all of it.

    The view asked for a thousand tests and `within_limit` handed it two hundred, because an
    asked-for number is held to MAX_LIMIT — the cap for an answer a model reads, not for a page
    the person whose history it is reads. The number printed above the list was then the length
    of the cut list, so it could never exceed the cap and could never disagree out loud.

    The shape has to be invented, because measuring the live archives does not show it: their
    largest material holds 161 tests, thirty-nine short of the cap, and no archive of this suite
    holds a tenth of it. Two hundred and twelve is one over that measured largest plus the fifty
    the vocabulary grows by between readings — the first number at which the page starts lying,
    rounded away from the boundary so that moving the cap by one does not quietly pass this.
    """
    import sqlite3

    from epicrisis.index.build import index_path
    from epicrisis.query import MAX_LIMIT

    data_dir, source, _labs = archive_index
    how_many = 212
    assert how_many > MAX_LIMIT, "the shape only shows the defect above the cap"
    connection = sqlite3.connect(index_path(data_dir, source.id))
    for number in range(how_many):
        # Meaningless syllables, one per test, so that nothing here is any laboratory's word.
        indicator_id, label = f"t{number:03d}", f"Tevmurel {number:03d}"
        connection.execute("INSERT INTO indicators (id, label, status, names) VALUES (?, ?, 'approved', '[]')",
                           (indicator_id, label))  # fmt: skip
        connection.execute(
            "INSERT INTO documents (id, source_id, file_sha256, date, primary_copy)"
            " VALUES (?, ?, 'f', '2011-07-09', 1)", (9000 + number, source.id))  # fmt: skip
        connection.execute(
            "INSERT INTO observations (document_id, page, kind, name, value, value_numeric,"
            " value_role, derived, indicator_id, material)"
            " VALUES (?, 1, 'observation', ?, '1', 1.0, 'result', 0, ?, 'swab')",
            (9000 + number, label, indicator_id))  # fmt: skip
    connection.execute("INSERT OR IGNORE INTO files (sha256, file_id) VALUES ('f', 'ffffffff')")
    connection.commit()
    connection.close()

    drawn = timeline_view(data_dir, source.id, view="indicators", material="swab", all_tests=True)

    assert drawn["series_total"] == how_many, "the count above the list is not the archive's"
    assert len(drawn["series"]) == how_many, "show every test showed some of them"


def test_a_material_tab_counts_the_values_the_list_under_it_draws(archive_index):  # noqa: F811
    """The template says it in those words, and the two numbers were of two different questions.

    *"Every tab here means 'click and see this many'"* stands over this row in `timeline.html`.
    The tab counted every value an indicator holds; the list under it draws only the values it
    has a day and a line for. Three differences, and none of them was written down anywhere: a
    value of a document carrying no date has no place on a year axis, a value the laboratory
    derived is not drawn at all, and a form filed twice is counted once. On the three archives
    read on 4 October 2026 the blood tab read 2048 over 1665 values, urine 1406 over 1220, and
    the smaller archive's blood 156 over 129 — so this is not a shape that has to be invented,
    only one that has to be held.

    Each of the three is put in here, because each disagrees on its own and a fix that caught two
    of them would pass a test that only held the third.
    """
    import sqlite3

    from epicrisis.index.build import index_path

    data_dir, source, _labs = archive_index
    connection = sqlite3.connect(index_path(data_dir, source.id))
    connection.execute("INSERT INTO indicators (id, label, status, names) VALUES ('tv', 'Tevmurel', 'approved', '[]')")
    connection.execute("INSERT OR IGNORE INTO files (sha256, file_id) VALUES ('f', 'ffffffff')")
    # A day, no day, and the second filing of a form somebody already has.
    for number, (date, primary) in enumerate((("2011-07-09", 1), (None, 1), ("2011-07-09", 0))):
        connection.execute(
            "INSERT INTO documents (id, source_id, file_sha256, date, primary_copy)"
            " VALUES (?, ?, 'f', ?, ?)", (9100 + number, source.id, date, primary))  # fmt: skip
    for document, derived in ((9100, 0), (9100, 1), (9101, 0), (9102, 0)):
        connection.execute(
            "INSERT INTO observations (document_id, page, kind, name, value, value_numeric,"
            " value_role, derived, indicator_id, material)"
            " VALUES (?, 1, 'observation', 'Tevmurel', '1', 1.0, 'result', ?, 'tv', 'swab')",
            (document, derived))  # fmt: skip
    connection.commit()
    connection.close()

    # Four values of one test on that tab, and one of them is the only one the list can draw.
    drawn = timeline_view(data_dir, source.id, view="indicators", material="swab", all_tests=True)
    tab = next(one for one in drawn["materials"] if one["key"] == "swab")
    assert sum(one["count"] for one in drawn["series"]) == 1, "the shape this is about is gone"
    assert tab["count"] == 1, f'the tab promises {tab["count"]} values over a list holding 1'

    # And every other tab of the row means the same thing, so none of them is counted another way.
    for item in drawn["materials"]:
        under = timeline_view(data_dir, source.id, view="indicators", material=item["key"], all_tests=True)
        assert sum(one["count"] for one in under["series"]) == item["count"], item["key"]


def test_the_tabs_count_the_undated_cut_when_that_is_what_the_page_shows(archive_index):  # noqa: F811
    """"The documents that carry no date at all" is a cut the tabs over it were not counted by.

    The comment in `timeline_view` describes this very defect found and mended for the year, and
    it was never carried to `undated`: the list and its footer took it, the links under the tabs
    carried it on, and the three counts beside them were of the whole archive. On the archive
    read on 4 October 2026 the undated feed held 20 documents under a Records tab reading 386 and
    a lab_panel tab reading 217 — press one of those and the page says "Showing 0 of 0".

    Asked the way the row is read: pressing a tab shows as many as the tab said it would.
    """
    data_dir, source, _labs = archive_index

    whole = timeline_view(data_dir, source.id)
    undated = timeline_view(data_dir, source.id, undated=True)
    assert undated["undated_count"] == 1 and whole["overview"]["documents"] == 3, "the shape is gone"

    # The one document here that carries no date is paperwork, so over the undated cut the
    # Records tab counts none of it and the paperwork tab counts the one — while over the whole
    # archive the two stand the other way round. A count blind to the cut cannot tell those
    # apart, so both are asked.
    assert (undated["records_count"], undated["paperwork_count"]) == (0, 1)
    assert (whole["records_count"], whole["paperwork_count"]) == (2, 1)
    assert undated["type_counts"] == {"lab_panel": 0, "insurance": 1, "discharge": 0}

    # And each tab read by pressing it: the link carries `undated` on, drops the paperwork and
    # names the type, so what comes back has to be what the tab promised.
    for name, promised in undated["type_counts"].items():
        pressed = timeline_view(data_dir, source.id, undated=True, doc_type=name)
        assert pressed["total"] == promised, f"the {name} tab promised {promised}, pressing it shows {pressed['total']}"
    assert undated["total"] == undated["records_count"], "the Records tab promised another number"
