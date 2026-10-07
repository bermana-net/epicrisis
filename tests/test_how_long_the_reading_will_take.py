"""That the estimate is measured, says nothing where it cannot, and never becomes a promise."""

import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from epicrisis import how_long


def a_ledger(folder: Path, pages: int, seconds_each: float, kind: str) -> None:
    """One archive's history: `pages` pages of one kind, each taking that many seconds.

    The inventory says what the pages are and the ledger says when each finished, which is the
    pair the fit reads. Written by hand rather than by running the pipeline, because the pipeline
    needs a model and these tests need neither network nor one.
    """
    folder.mkdir(parents=True, exist_ok=True)
    started = datetime(2026, 1, 1, tzinfo=UTC)
    with (folder / "ledger.jsonl").open("w", encoding="utf-8") as fh:
        for page in range(pages):
            at = started + timedelta(seconds=seconds_each * page)
            fh.write(json.dumps({"step": "classify", "file_sha256": "a" * 64, "page": page + 1,
                                 "status": "done", "at": at.isoformat()}) + "\n")  # fmt: skip
    with (folder / "inventory.jsonl").open("w", encoding="utf-8") as fh:
        if kind == how_long.A_PAGE_OF_TEXT:
            # A text export: one file, no pages of its own, read as text throughout.
            fh.write(json.dumps({"path": "export.txt", "name": "export.txt", "sha256": "a" * 64,
                                 "size": 10, "mime": "text/plain", "category": "text",
                                 "folder_year_hint": 2026,
                                 "text": {"pages": pages, "of_document": list(range(pages))}}) + "\n")  # fmt: skip
        else:
            fh.write(json.dumps({"path": "scan.pdf", "name": "scan.pdf", "sha256": "a" * 64,
                                 "size": 10, "mime": "application/pdf", "category": "pdf",
                                 "folder_year_hint": 2026,
                                 "pdf": {"encrypted": False, "pages": pages, "pages_with_text": 0,
                                         "text_layer": "none",
                                         "text_chars_per_page": [0] * pages,
                                         "has_images": True}}) + "\n")  # fmt: skip


def test_an_instance_that_has_read_almost_nothing_says_nothing(tmp_path: Path):
    """The failure this guards against is a number, not a silence.

    Fitted on one afternoon, the figure reads as a measurement and is one run's weather: the
    archive here with 69 pages comes out 63% away from what it actually took, while the two with
    hundreds are within 2%. So under ENOUGH_TO_LEARN_FROM the answer is None, and the pages print
    the sentence they printed before rather than a plausible hour.
    """
    # Both kinds, so that the refusal can only come from how little has been read: with one kind
    # alone the fit refuses for a different reason, and this test passed a mutation of the
    # threshold to zero without noticing.
    a_ledger(tmp_path / "text", pages=20, seconds_each=15, kind=how_long.A_PAGE_OF_TEXT)
    a_ledger(tmp_path / "scans", pages=20, seconds_each=120, kind=how_long.A_PAGE_TO_BE_LOOKED_AT)

    assert how_long.prices([tmp_path / "text", tmp_path / "scans"]) is None
    # And the same history one page over the line does answer, so the refusal is the threshold
    # and not something else about these archives.
    a_ledger(tmp_path / "more", pages=170, seconds_each=15, kind=how_long.A_PAGE_OF_TEXT)
    assert how_long.prices([tmp_path / "text", tmp_path / "scans", tmp_path / "more"]) is not None
    assert how_long.hours_for(Counter({how_long.A_PAGE_OF_TEXT: 500}), None) is None
    assert how_long.in_words(None) == ""


def test_one_kind_of_page_alone_cannot_price_the_other(tmp_path: Path):
    """Two unknowns out of one kind of row is not a fit, and the determinant says so.

    An instance that has only ever read text exports knows nothing about what a scan costs. One
    price asked of both kinds would read as a measurement and would be eight times out, which is
    the measured difference between them.
    """
    a_ledger(tmp_path / "a", pages=300, seconds_each=15, kind=how_long.A_PAGE_OF_TEXT)
    a_ledger(tmp_path / "b", pages=300, seconds_each=15, kind=how_long.A_PAGE_OF_TEXT)

    assert how_long.prices([tmp_path / "a", tmp_path / "b"]) is None


def test_the_two_prices_are_the_two_prices_that_were_read(tmp_path: Path):
    """The fit returns what the history holds, and the history here is plain on purpose."""
    a_ledger(tmp_path / "text", pages=400, seconds_each=10, kind=how_long.A_PAGE_OF_TEXT)
    a_ledger(tmp_path / "scans", pages=400, seconds_each=100, kind=how_long.A_PAGE_TO_BE_LOOKED_AT)

    fitted = how_long.prices([tmp_path / "text", tmp_path / "scans"])

    assert fitted is not None
    assert fitted.a_page_of_text == pytest.approx(10, rel=0.02)
    assert fitted.a_page_to_be_looked_at == pytest.approx(100, rel=0.02)
    assert fitted.pages_learnt_from == 800
    # And the estimate off those prices is the arithmetic anybody would do by hand.
    hours = how_long.hours_for(Counter({how_long.A_PAGE_OF_TEXT: 360,
                                       how_long.A_PAGE_TO_BE_LOOKED_AT: 360}), fitted)  # fmt: skip
    assert hours == pytest.approx((360 * 10 + 360 * 100) / 3600, rel=0.02)


def test_the_hours_a_person_stopped_for_are_not_the_reading(tmp_path: Path):
    """A run stopped overnight and continued in the morning took one evening, not a night.

    The subscription's usage limit stops a run rather than waiting inside it, so a gap of this
    length is somebody's day and never work. Without this the fit priced a page at whatever the
    person's sleep divided by the pages came to.
    """
    folder = tmp_path / "stopped"
    a_ledger(folder, pages=400, seconds_each=10, kind=how_long.A_PAGE_OF_TEXT)
    a_ledger(tmp_path / "scans", pages=400, seconds_each=100, kind=how_long.A_PAGE_TO_BE_LOOKED_AT)
    # One line a day later, as a run continued the next morning leaves behind.
    with (folder / "ledger.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"step": "classify", "file_sha256": "a" * 64, "page": 401,
                             "status": "done",
                             "at": datetime(2026, 1, 2, 9, tzinfo=UTC).isoformat()}) + "\n")  # fmt: skip

    fitted = how_long.prices([folder, tmp_path / "scans"])

    assert fitted is not None
    assert fitted.a_page_of_text == pytest.approx(10, rel=0.05), fitted


def test_the_estimate_is_rounded_to_what_it_can_support():
    """Twenty hours, not 19.7: the fit is an order of magnitude and must not read as a clock."""
    assert how_long.in_words(19.7) == "about 20 hours"
    assert how_long.in_words(3.4) == "about 3 hours"
    assert how_long.in_words(1.0) == "about 1 hour"
    assert how_long.in_words(0.3) == "about 20 minutes"
    # Never zero minutes: a page that is waiting takes some time, whatever the rounding says.
    assert how_long.in_words(0.001) == "about 5 minutes"


def test_a_page_that_has_to_be_looked_at_is_counted_as_one(tmp_path: Path):
    """The one distinction the model rests on, asked of the code that does the reading.

    `page_refs` is what the run itself walks, so a page is counted here exactly as it will be
    read. A count taken off the file extension instead would call a scanned PDF and a born
    digital one the same thing, and they differ by eight times.
    """
    a_ledger(tmp_path / "scans", pages=7, seconds_each=100, kind=how_long.A_PAGE_TO_BE_LOOKED_AT)
    from epicrisis.records import read_records

    counted = how_long.waiting_by_kind(list(read_records(tmp_path / "scans" / "inventory.jsonl")))

    assert counted[how_long.A_PAGE_TO_BE_LOOKED_AT] == 7
    assert counted[how_long.A_PAGE_OF_TEXT] == 0


def an_instance_with(tmp_path: Path, histories: list[tuple[int, float, str]]):
    """A data directory whose archives hold the readings given, and the client to look at it.

    The archives are registered the way the registry registers them, so the pages gather from
    them exactly as they do on a real instance — which is the half a test of the module alone
    cannot reach: whether the page asks for the estimate at all.
    """
    from fastapi.testclient import TestClient

    from epicrisis.sources import SourceRegistry
    from epicrisis.web.app import create_app

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    registry = SourceRegistry(data_dir)
    for number, (pages, seconds_each, kind) in enumerate(histories):
        scans = tmp_path / f"scans{number}"
        scans.mkdir()
        source = registry.add(str(scans), owner=f"Somebody {number}")
        registry.set_active(source.id)
        a_ledger(data_dir / "sources" / source.id, pages, seconds_each, kind)
    return TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")


def test_the_page_before_the_button_says_about_how_long(tmp_path: Path):
    """The whole point of the card: the owner with a visit in an hour, and the reader deciding
    whether to send thirty years of forms, both got a count of pages and no time at all."""
    client = an_instance_with(tmp_path, [(400, 10, how_long.A_PAGE_OF_TEXT),
                                         (400, 100, how_long.A_PAGE_TO_BE_LOOKED_AT)])  # fmt: skip

    page = client.get("/consent").text

    assert "On what this instance has already read itself" in page
    # 400 pages at 10 seconds and 400 at 100 is 12.2 hours, which the words round to ten.
    assert "about 10 hours" in page, page[page.find("already read itself"):][:200]
    assert "not a promise" in page


def test_an_instance_that_has_read_nothing_promises_nothing_on_the_page(tmp_path: Path):
    """And says what it said before, which was honest: the shape of the wait, not a figure.

    Both pages, because the estimate reaches both and a figure on either is the same promise.
    The sentence the status page falls back to is held by the template and not asserted here:
    which of its sections draws depends on how far the pipeline has got, and a test that set that
    up would be testing the status page and not this.
    """
    client = an_instance_with(tmp_path, [(20, 10, how_long.A_PAGE_OF_TEXT)])

    for page in ("/consent", "/status"):
        assert "On what this instance has already read itself" not in client.get(page).text
        assert "about" not in client.get(page).text.split("pages are waiting")[-1][:400]
