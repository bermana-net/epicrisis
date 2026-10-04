"""A clinic whose heading runs over two lines of a form, through the page and back.

The archive here holds one such name, and the press on Join over it was refused every time, with
"one name on its own is not a join", for having ticked two. The cause is not in this program's
reasoning at all: the url-encoded form serialiser is **required** to rewrite every lone line feed
inside a form value as a carriage return and a line feed (HTML, "application/x-www-form-urlencoded
serializer"), every browser does it, and none has a setting for it. So a name printed across two
lines goes out as the document prints it and comes back one character longer than any name the
archive holds.

Nothing here fetches an address, because the rewrite happens in the browser, before any route: a
test client would hand the route whatever this file wrote, which would prove the fix against a
lenient stand-in. The names arrive here exactly as a browser is obliged to send them, and the
press is asked as a question, which is what `web/who.py` is for.
"""

import sqlite3
from pathlib import Path

import pytest

from epicrisis import people
from epicrisis.query import index_path
from epicrisis.sources import SourceRegistry
from epicrisis.web import who
from epicrisis.web.app import _the_open_archive

from test_the_wall_between_people import THEIRS, _an_archive, _both_on_the_list

MINE = THEIRS["one"]

#: One clinic, printed twice: its whole heading over two lines, and the second line on its own.
#: Both spellings are invented, and every word of them was looked for in all three archives on
#: this machine before it was written down here — no document, no value and no name holds one —
#: and they share no word with the clinic the fixture archive already prints, so the family this
#: offers is this pair and nothing else.
OVER_TWO_LINES = "Northgrove Imaging Centre\nNorthgrove Rooms Eleven"
THE_SECOND_LINE = "Northgrove Rooms Eleven"

#: What the browser sends back for OVER_TWO_LINES. Not a guess about one browser: the serialiser
#: is specified to do this, so this is the only thing that can arrive.
AS_THE_BROWSER_SENDS_IT = "Northgrove Imaging Centre\r\nNorthgrove Rooms Eleven"


def _also_printed(data_dir: Path, mine: dict, provider: str, tail: str, date: str) -> None:
    """One more document of this archive, naming its clinic the way `provider` spells it."""
    index = sqlite3.connect(index_path(data_dir, mine["id"]))
    with index:
        index.execute(
            """INSERT INTO files (sha256, file_id, source_id, path, category, page_count)
               VALUES (?, ?, ?, ?, 'scan', 1)""",
            (tail * 8, mine["id"][:4] + tail[:4], mine["id"], f"/scans/{mine['id']}-{tail}.pdf"),
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
def an_archive_with_a_two_line_heading(tmp_path):
    """One archive printing one clinic twice: over two lines, and its second line alone."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    _both_on_the_list(data_dir, "one")
    for theirs in THEIRS.values():
        _an_archive(data_dir, theirs)
    _also_printed(data_dir, MINE, OVER_TWO_LINES, "dddd4444", "2013-09-11")
    _also_printed(data_dir, MINE, THE_SECOND_LINE, "eeee5555", "2014-10-12")
    return data_dir, SourceRegistry(data_dir).as_one_reading()


def _the_family_offered(data_dir, kind="institution"):
    shown = who.who_view(data_dir, MINE["id"], kind=kind)
    return [family for family in shown["proposals"] if OVER_TWO_LINES in family.names]


def test_the_page_offers_the_two_line_heading_and_its_second_line(an_archive_with_a_two_line_heading):
    """The question is real before anything is said about the answer."""
    data_dir, _ = an_archive_with_a_two_line_heading

    offered = _the_family_offered(data_dir)
    assert offered, "the page counts the whole heading and its second line as one clinic"
    assert sorted(offered[0].names) == sorted([OVER_TWO_LINES, THE_SECOND_LINE])


def test_a_press_with_the_line_break_the_browser_sends_joins_the_two(an_archive_with_a_two_line_heading):
    """The whole bug, in one press: ticked two, and the archive is told two."""
    data_dir, archives = an_archive_with_a_two_line_heading

    decided = who.joined(data_dir, archives, MINE["id"], the_open_archive=_the_open_archive,
                         kind="institution",
                         names=[AS_THE_BROWSER_SENDS_IT, THE_SECOND_LINE])  # fmt: skip

    assert not decided.refused, f"two spellings were ticked and the press was refused: {decided.refused}"
    settled = people.settled(people.load(data_dir, MINE["id"]), "institution")
    held = [group for group in settled if THE_SECOND_LINE in group.names]
    assert held, "the join was not stored"
    assert sorted(held[0].names) == sorted([OVER_TWO_LINES, THE_SECOND_LINE]), (
        "the spelling stored is the one the document prints, not the one the browser sent")
    assert all("\r" not in name for name in held[0].names), "a carriage return reached the file"


def test_the_press_ends_the_question_rather_than_asking_it_again(an_archive_with_a_two_line_heading):
    """What made this a circle: the press was made, and the page asked again on the next draw."""
    data_dir, archives = an_archive_with_a_two_line_heading

    who.joined(data_dir, archives, MINE["id"], the_open_archive=_the_open_archive,
               kind="institution", names=[AS_THE_BROWSER_SENDS_IT, THE_SECOND_LINE])  # fmt: skip

    assert not _the_family_offered(data_dir), "the page offers again what was just settled"


def test_a_file_written_before_this_reads_back_as_the_documents_print_it(an_archive_with_a_two_line_heading):
    """His own file holds the browser's spelling, over a join that was pressed a month ago.

    It is read as printed rather than left: the spelling stored stands on no document, so the
    join it recorded took effect over one of the two names and not the other, and the page went
    on offering the pair. Nobody's work is undone by reading it this way — the group, the label
    and the names they ticked are all still theirs.
    """
    data_dir, archives = an_archive_with_a_two_line_heading
    people.save(data_dir, MINE["id"], [people.Group(
        kind="institution", label=AS_THE_BROWSER_SENDS_IT,
        names=[AS_THE_BROWSER_SENDS_IT, THE_SECOND_LINE])])  # fmt: skip

    groups = people.settled(people.load(data_dir, MINE["id"]), "institution")

    assert [group.label for group in groups] == [OVER_TWO_LINES]
    assert sorted(groups[0].names) == sorted([OVER_TWO_LINES, THE_SECOND_LINE])
    assert not _the_family_offered(data_dir), "the join that was pressed takes effect at last"


def test_nothing_else_about_a_name_is_touched(an_archive_with_a_two_line_heading):
    """A line feed a document prints is kept, and only the carriage return goes."""
    assert people.a_printed_name(OVER_TWO_LINES) == OVER_TWO_LINES
    assert people.a_printed_name(THE_SECOND_LINE) == THE_SECOND_LINE
    assert people.a_printed_name(MINE["doctor"]) == MINE["doctor"]
    assert people.a_printed_name("Нетудихата\rІ.В") == "Нетудихата\nІ.В", "a lone one is a line break too"
    assert people.a_printed_name("") == ""
