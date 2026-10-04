"""Three sentences the pages have to keep saying, and nothing was holding them.

They stood on a card called "done well, do not break this with the next change": a role read eight
things by hand on a demo and wrote down that they were right. Every one of them was still right a
hundred and thirty commits later, which is luck rather than protection — and of the six checked,
three had no test at all. A promise nothing can fail on is the fourth thing of its kind found in
two days: written down, explained, and connected to nothing.

So the three that nothing held are here, each named by the entry of the constitution it serves,
and the card is gone. What is worth keeping is a test; the rest was a diary.

A fourth joined them, and it is the reason the file is worth having: the heading of the page of
doctors and clinics promised every institution and every doctor on the documents, the page does
not hold every one of them, and the owner acted on the promise — looked there for two
doctors he had seen, by their surnames, and concluded the archive held neither. A promise nothing can
fail on is one thing; a promise that is false is another.
"""

import html
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from epicrisis.web.app import create_app
from test_ask import archive_index  # noqa: F401
from test_extract import FakeExtractBackend, setup  # noqa: F401


@pytest.fixture
def a_chart(archive_index):  # noqa: F811
    """An archive where one printed name has an indicator, so a chart exists to be drawn."""
    from epicrisis import indicators
    from epicrisis.index.build import build_index

    data_dir, source, _labs = archive_index
    indicators.upsert(data_dir, None, "Cystatin C", ["Цистатин С"], status="approved")
    build_index(data_dir, [source])
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    by_test = client.get("/?view=indicators").text
    assert "/tests/" in by_test, "no chart in this archive, so this test is about nothing"
    return client, by_test.split('href="/tests/')[1].split('"')[0].split("?")[0]


def test_a_chart_says_that_it_is_shown_and_not_read(a_chart):
    """The third entry: this is not a medical device, and the chart is where that is easiest to forget.

    Points joined in date order look like a trend, and a trend looks like a reading. The line under
    the chart is what keeps the drawing honest — nothing is fitted, smoothed or averaged, no value
    is called high or low, and what the numbers mean is for a doctor. Take that sentence away and
    the page starts to say something this program must never say.
    """
    client, indicator_id = a_chart
    page = client.get(f"/tests/{indicator_id}")

    assert page.status_code == 200
    assert "Shown, not read" in page.text, "the chart no longer says that it is not a reading"
    for promise in ("nothing is fitted, smoothed or averaged", "no value is marked high or low",
                    "What the numbers mean is for a doctor"):  # fmt: skip
        assert promise in page.text, promise


def test_a_chart_says_which_of_its_values_were_placed_by_their_numbers():
    """The seventh entry: if a value was placed by its own numbers, the page says so.

    This is the one reading in the program taken from numbers rather than from a page, and the
    whole permission for it is that it is said out loud — in the heading, counted, and again
    beside every value it moved. A round of this finding made the rule move values on eight tests
    of one archive where it had moved none, and nothing anywhere was holding either sentence.

    The words and not a drawn page, deliberately: a chart on which this rule fires needs an
    archive printing a unit on half of one test's forms and nothing on the other half, which is
    not a page to build but an archive to build. What a page prints is in its template, the counts
    it prints are in series.py, and the tests of those counts are in test_series.py; this holds the
    sentences that turn them into something a reader can see.
    """
    drawn = (Path(__file__).resolve().parent.parent / "epicrisis/web/templates/series.html").read_text(encoding="utf-8")

    heading, row = "with no unit printed, placed here by their numbers", "unit by numbers"
    assert heading in drawn, "the chart no longer says how many of its values were placed by their numbers"
    assert "chart.by_numbers" in drawn, "the sentence is there and nothing counts into it"
    assert row in drawn and "item.unit_by_numbers" in drawn, "a value placed by its numbers is no longer marked"
    assert "This form printed no unit for this value" in drawn, "the mark no longer says what it means"


def test_a_chart_says_when_the_band_it_drew_was_one_of_two_the_form_printed():
    """The seventh entry again, over the band rather than the point.

    A blood count form prints both bands of one test on one line — the per-cent corridor and the
    absolute one, each with its own unit — and the band drawn is the one printed in the unit of the
    chart. That is a choice this program made between two things the form printed, and nothing
    anywhere said it: the row prints the whole printed text, so a reader could see two bands there
    and had no way to see which of them was drawn behind the points.

    Asserted on the template, the way the sentence above it is, and for the same reason: an archive
    that would draw it needs a form printing two bands on one line, which is an archive to build
    and not a page. tests/test_two_scales_on_one_line.py holds the tests of the mark itself.
    """
    drawn = (Path(__file__).resolve().parent.parent / "epicrisis/web/templates/series.html").read_text(encoding="utf-8")

    assert "item.band_by_its_unit" in drawn, "a band chosen from two printed ones is no longer marked"
    assert "band drawn: the one in" in drawn, "the mark no longer says which band is on the chart"
    assert "This form printed two ranges on one line" in drawn, "the mark no longer says what it means"


def test_a_correction_offers_the_way_back_to_what_the_model_read(archive_index):  # noqa: F811
    """The eighth entry: a person's own work is never overwritten — and neither is the model's.

    A corrected value has to be undoable, and undoable in one press from the place it was made. The
    way back is drawn only where there is something to go back to, which is why this test makes a
    correction first: a card with nothing corrected on it has nothing to offer, and asserting the
    sentence over such a card would pass while proving nothing.
    """
    import re

    data_dir, source, labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    at = f"/documents/{source.id}/{labs}/1"

    card = client.get(at)
    assert card.status_code == 200
    assert "Back to what the model read" not in card.text, "nothing is corrected yet, so nothing to undo"

    # The form is taken off the drawn page rather than built here, the way the wall test takes a
    # press off the page it is about: a form written out in a test is a test of what somebody
    # believed the page offers.
    form = re.search(r'<form class="fix-form"[^>]*action="([^"]+)"(.*?)</form>', card.text, re.S)
    assert form, "no form for fixing a value on this card, so this test is about nothing"
    fields = dict(re.findall(r'name="([^"]+)"[^>]*value="([^"]*)"', form.group(2)))
    assert fields.get("key"), f"the form carries no key: {sorted(fields)}"

    saved = client.post(form.group(1), data={**fields, "action": "save", "value": "0,86"},
                        follow_redirects=True)  # fmt: skip

    assert saved.status_code == 200
    assert "Back to what the model read" in saved.text, "a correction cannot be taken back from its card"


def test_the_page_of_doctors_counts_instead_of_promising_every_name(archive_index):  # noqa: F811
    """The seventh entry, over the one promise here that a person read as a promise and acted on.

    The heading of /who read "every institution and every doctor named on these documents". It is
    not true: a name reaches that page by having been read into the provider field or the doctor
    field of a document, and a surname printed inside a document's own text and nowhere else is in
    neither. On the archive it was read on the doctor field is filled on 20 of 414 documents, while
    38 documents carry a labelled surname in their transcribed text — 20 distinct names — that is
    in no field at all. The owner looked there for two doctors he had seen, by their
    surnames, found neither, and concluded the archive did not hold them.

    Asserted on the drawn page and not only on the sentence: the counting was right in `who.py`
    and the page went on promising for as long as the template said something else, which is
    exactly the shape of this finding.
    """
    import sqlite3

    from epicrisis.index.build import index_path

    data_dir, source, _labs = archive_index
    with sqlite3.connect(index_path(data_dir, source.id)) as connection:
        # Said from nothing rather than added to whatever the fixture happens to hold: a count
        # read out of the index here would make this a test that cannot fail.
        connection.execute("UPDATE documents SET doctor = NULL")
        one = connection.execute("SELECT id FROM documents WHERE primary_copy = 1").fetchone()[0]
        connection.execute("UPDATE documents SET doctor = 'Нетудихата І.В' WHERE id = ?", (one,))
        held = connection.execute("SELECT count(*) FROM documents WHERE primary_copy = 1").fetchone()[0]
        connection.commit()
    assert held == 3, f"this archive holds {held} documents, and the sentence below counts three"

    page = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050").get("/who")
    # The apostrophe in "a document's own text" goes out of the template as an entity, and a test
    # asserting a sentence has to be asserting the sentence a person reads.
    drawn = html.unescape(page.text)

    assert page.status_code == 200
    assert "every institution and every doctor named on these documents" not in drawn, (
        "the page is promising every name again")
    # Anchored on the tag the heading is drawn in, so that a wrong number cannot pass by standing
    # inside a longer one: ">1 doctor" is not a substring of ">21 doctors".
    assert ">1 doctor, read off 1 of the 3 documents of this archive." in drawn
    assert "The other 2 print no doctor that was read" in drawn
    assert "a name standing only inside a document's own text is not on this page" in drawn


def test_an_empty_search_says_that_empty_is_not_absent(archive_index):  # noqa: F811
    """The seventh entry: the program says out loud what it does, including what it does not know.

    Matching here is literal and per-language, so a word that finds nothing may still be all over
    the archive under another spelling or another alphabet. A page answering "0 documents" and
    stopping would be making a claim about the archive that it has no way to support. It says the
    difference instead, and offers the ways on.
    """
    data_dir, _source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    found = client.get("/search?q=nothing+of+this+name+is+printed+anywhere")

    assert found.status_code == 200
    assert "is not the same as" in found.text, "the page lets 'nothing found' stand for 'nothing here'"
