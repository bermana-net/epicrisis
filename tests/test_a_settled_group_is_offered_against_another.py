"""Two groups standing for one doctor, and the page that never asked.

Once a person had joined some spellings into a group, that group was never again offered beside
another group, so two groups standing for one doctor stayed apart for ever with nothing on the
page even asking. The cause is one line: a group appears on the page of doctors and clinics as its
label, and the filter that dropped a family whose every name was already settled dropped exactly
the family of two labels. `people.join` has absorbed a settled group holding one of the names
being joined since the day it was written — the machinery to merge two groups was there, and only
the offering was missing.

`who.who_view` is what decides what the page offers and the four presses are what decide what a
press does, so three of the four tests here are them asked as questions, with no address and no
template. The fourth draws the page, because the row this adds is a row of markup and a heading
that counts: counting right in `web/who.py` while the template says something else is the shape of
the finding beside this one.

**Why this file exists rather than a measurement on the live archives.** The word count finds no
family at all on any of the three archives on this machine — not before this change and not after
it, because their owner has already answered every family it can see: 106 institution names on the
largest of them, 21 settled groups, and nought families offered. So the change is untested by the
live data, and the groups below are invented. Every word of them was looked for in the provider,
doctor and title of every document and in the name of every value of all three archives before it
was written down, and found nowhere; they are built out of the fixture the wall between people is
proved with, whose two archives share no substring at all.
"""

import html
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from epicrisis import people
from epicrisis.query import index_path
from epicrisis.sources import SourceRegistry
from epicrisis.web import who
from epicrisis.web.app import _the_open_archive, create_app

from test_the_wall_between_people import THEIRS, _an_archive, _both_on_the_list, _printed_a_second_way

MINE = THEIRS["one"]

#: The laboratory of the fixture archive, written a third and a fourth way: its own name without
#: the middle word, and that again with a comma after it. Two words, so the family is offered at
#: all — one word is never offered as a name — and every word of them already stands in the name
#: the fixture prints, so nothing new about anybody is written down here.
A_SHORTER_NAME = "Westhollow Laboratory"
THE_SHORTER_NAME_AGAIN = A_SHORTER_NAME + ","


def _also_printed(data_dir: Path, mine: dict, provider: str, tail: str, date: str) -> None:
    """One more document of this archive, naming the laboratory the way this one prints it."""
    index = sqlite3.connect(index_path(data_dir, mine["id"]))
    with index:
        index.execute(
            """INSERT INTO files (sha256, file_id, source_id, path, category, page_count)
               VALUES (?, ?, ?, ?, 'scan', 1)""",
            (tail * 8, tail[:8], mine["id"], f"/scans/{mine['id']}-{tail}.pdf"),
        )  # fmt: skip
        index.execute(
            """INSERT INTO documents (source_id, file_sha256, first_page, pages, doc_type,
                                      language, title, provider, date, date_precision,
                                      transcribed, primary_copy)
               VALUES (?, ?, 1, '[1]', 'lab_panel', 'uk', ?, ?, ?, 'day', 1, 1)""",
            (mine["id"], tail * 8, mine["test"], provider, date),
        )  # fmt: skip
    index.close()


@pytest.fixture
def two_groups_of_one_laboratory(tmp_path):
    """One archive printing its laboratory four ways, joined by hand into two groups.

    Joined through the press and not written into the file here: a fixture that writes people.json
    itself proves the offering against a file somebody believed the program writes, and the shape
    of this finding is that the program's own two halves disagreed about what a group is.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    _both_on_the_list(data_dir, "one")
    for theirs in THEIRS.values():
        _an_archive(data_dir, theirs)
    with_a_comma = _printed_a_second_way(data_dir, MINE)
    _also_printed(data_dir, MINE, A_SHORTER_NAME, "dddd4444", "2015-11-13")
    _also_printed(data_dir, MINE, THE_SHORTER_NAME_AGAIN, "eeee5555", "2016-12-14")
    archives = SourceRegistry(data_dir).as_one_reading()

    # Two presses, each over one pair, which is a person joining the four spellings into two
    # groups — and the page's own answer that it did what it said.
    for pair in ((MINE["provider"], with_a_comma), (A_SHORTER_NAME, THE_SHORTER_NAME_AGAIN)):
        decided = who.joined(data_dir, archives, MINE["id"], the_open_archive=_the_open_archive,
                             kind="institution", names=list(pair), label=pair[0])  # fmt: skip
        assert decided.stored == ("2 spellings joined as one institution",), decided.refused
    settled = people.settled(people.load(data_dir, MINE["id"]), "institution")
    assert sorted(one.label for one in settled) == sorted([A_SHORTER_NAME, MINE["provider"]])
    return data_dir, archives


def test_two_groups_whose_labels_look_like_one_name_are_offered(two_groups_of_one_laboratory):
    """The offering that did not exist, and what the page says it would join.

    Both halves matter. That the family is there at all is the finding; that the heading over it
    counts two groups and four printed spellings rather than "2 spellings" is §7 — the press joins
    four, and a page claiming two while the button joins four is a count disagreeing with itself.
    """
    data_dir, _archives = two_groups_of_one_laboratory

    offered = who.who_view(data_dir, MINE["id"], kind="institution")["proposals"]

    assert len(offered) == 1, "two settled groups are not being offered against each other"
    family = offered[0]
    assert sorted(family.names) == sorted([MINE["provider"], A_SHORTER_NAME])
    assert family.spellings == 4
    assert sorted(family.under) == sorted([MINE["provider"], A_SHORTER_NAME])
    assert family.said == ("2 names that look like one — 2 of them groups you joined, "
                           "4 printed spellings in all")  # fmt: skip
    # And the spellings under each label are on the page, because a label alone shows nothing and
    # §4 lets a page offer a pair only where a reader can see that it is wrong.
    assert set(family.under[A_SHORTER_NAME]) == {A_SHORTER_NAME, THE_SHORTER_NAME_AGAIN}
    assert MINE["provider"] in family.under[MINE["provider"]]
    # Nothing of the other person's archive, on the page where that went wrong once.
    assert THEIRS["two"]["provider"] not in repr(offered)


def test_one_press_joins_every_spelling_under_both_groups(two_groups_of_one_laboratory):
    """Or the offering is a question whose answer does nothing.

    `people.join` absorbs the settled groups holding any of the ticked names, so the two groups
    become one group of all four spellings under the label that was kept — and the page stops
    asking, because there is one name left where there were two.

    The names pressed are the ones the page offered, taken off what it gathered rather than
    written out here: a press built in a test is a test of what somebody believed the page offers,
    and the number the page printed over the tick boxes is held against what the press then wrote.
    """
    data_dir, archives = two_groups_of_one_laboratory
    offered = who.who_view(data_dir, MINE["id"], kind="institution")["proposals"]
    assert len(offered) == 1, "nothing is offered to press, so this test is about nothing"

    decided = who.joined(data_dir, archives, MINE["id"], the_open_archive=_the_open_archive,
                         kind="institution", names=list(offered[0].names),
                         label=MINE["provider"])  # fmt: skip

    assert decided.refused == () and decided.stored == ("2 spellings joined as one institution",)
    settled = people.settled(people.load(data_dir, MINE["id"]), "institution")
    assert len(settled) == 1, "the two groups were not merged into one"
    assert sorted(settled[0].names) == sorted([MINE["provider"], MINE["provider"] + ",",
                                               A_SHORTER_NAME, THE_SHORTER_NAME_AGAIN])  # fmt: skip
    assert len(settled[0].names) == offered[0].spellings, (
        "the page counted one number of spellings over the button and the press joined another")
    assert settled[0].label == MINE["provider"]
    shown = who.who_view(data_dir, MINE["id"], kind="institution")
    assert shown["proposals"] == [], "the page asks again what was just answered"
    assert [one["name"] for one in shown["makers"]] == [MINE["provider"]]


def test_a_refusal_between_two_groups_is_remembered_as_one_between_two_spellings(two_groups_of_one_laboratory):
    """And taken back the same way, or this page is the circle it was before.

    The three functions that remember "no" are asked about the two labels, which are names like
    any other, so there is one way of remembering it here and this needed no second one. What it
    has to hold is the whole round trip: said no to, the family is gone from what is offered and
    standing under "You said these are not the same"; asked for again, it comes back.
    """
    data_dir, archives = two_groups_of_one_laboratory
    both = [MINE["provider"], A_SHORTER_NAME]

    said_no = who.declined(data_dir, archives, MINE["id"], the_open_archive=_the_open_archive,
                           kind="institution", names=both)  # fmt: skip

    assert said_no.stored == ("2 spellings said not to be one institution",)
    assert people.says_no_to(people.load(data_dir, MINE["id"]), "institution", both)
    refused = who.who_view(data_dir, MINE["id"], kind="institution")
    assert refused["proposals"] == [], "a family said no to is offered again"
    assert [sorted(one.names) for one in refused["refused"]] == [sorted(both)]
    # And the two groups are untouched by having been refused: a refusal says what is not one, and
    # changes nothing about what is.
    assert len(people.settled(people.load(data_dir, MINE["id"]), "institution")) == 2

    again = who.reconsidered(data_dir, archives, MINE["id"], the_open_archive=_the_open_archive,
                             kind="institution", names=both)  # fmt: skip

    assert again.stored == ("a refusal of 2 spellings taken back",)
    offered = who.who_view(data_dir, MINE["id"], kind="institution")
    assert [sorted(one.names) for one in offered["proposals"]] == [sorted(both)]
    assert offered["refused"] == []


def test_the_drawn_page_says_what_one_press_over_two_groups_would_join(two_groups_of_one_laboratory):
    """The heading of the row, and the spellings of each group beside its label, on the page.

    The tick boxes carry the two labels, and a reader looking at two labels cannot see that one of
    the spellings under one of them is somebody else. §4 lets a page put a pair in front of a
    person only where it can show that it is wrong, so the spellings stand in the row itself —
    asserted inside that row and not anywhere on the page, because every spelling of a settled
    group is also printed further down under "Joined by you", and a test satisfied by that would
    pass over a row that shows nothing at all.
    """
    data_dir, _archives = two_groups_of_one_laboratory
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    drawn = html.unescape(client.get("/who", params={"kind": "institution"}).text)

    assert ("2 names that look like one — 2 of them groups you joined, 4 printed spellings in all"
            in drawn), "the row does not say what a press over it would join"  # fmt: skip
    # Said at the row it is about since 7 Oct 2026, not over the whole page: it used to stand at
    # the top for every reader, including the ones with no such row in front of them.
    assert "One of these is a group you joined before" in drawn
    ticked = re.search(r'<ul class="ticks">(.*?)</ul>', drawn, re.S)
    assert ticked, "no tick boxes on this page, so this test is about nothing"
    for spelling in (A_SHORTER_NAME, THE_SHORTER_NAME_AGAIN, MINE["provider"], MINE["provider"] + ","):
        assert spelling in ticked.group(1), f"not shown in the row that would join it: {spelling}"
