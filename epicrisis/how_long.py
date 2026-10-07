"""How long reading an archive will take, out of what this instance has already read.

Two people asked for this and neither got a number: the owner with a visit in an hour, and the
reader of the consent page deciding whether to send thirty years of forms at all. The pages said
how many pages would go and never how long that would be — "the slowest and costliest step there
is" and nothing else.

**Nothing here is shipped as a figure.** The prices are fitted every time, from this machine's
own ledgers: another machine, another network and another model answer differently, and a table
of seconds carried in the source would be a promise about somebody else's computer. Where this
instance has read too little to fit anything, the answer is None and the page says what it said
before rather than guessing.

What the estimate rests on, measured on the three archives here (1,017 pages, 17.2 hours of work):

  * **A page carries its text, or it has to be looked at**, and that is the whole of the model.
    Fitted: 15 seconds against 127, a difference of eight times. `classify.pages.page_refs`
    already answers which a page is — `route` — before anything reads it, so the estimate is
    available on the consent page, before the owner presses anything.
  * It reproduces the two archives that have hundreds of pages within 2%, and overshoots the one
    with 69 pages by 63%. So it is an order of magnitude with the word "about" in front of it,
    which is what the two people above were short of, and never a time anybody may plan against.

Three models that looked right and are not, each tried and dropped, so that nobody fits them
again:

  * **Per step, from the model that answered.** The ledger names the model, so classify and
    extract can be priced apart — 9 seconds and 28. But `extract` runs per *document*, and the
    documents of a file are not known until classify has found them, so the one number that
    matters most cannot be had before the run it is meant to describe.
  * **Seconds a page, one figure per stretch of work.** Eleven stretches gave 15 seconds to 626,
    a spread of forty times, which reads as noise and is not: a stretch that mostly re-read
    already classified pages divides its hours by almost no new pages at all. The denominator was
    wrong, not the archive.
  * **The route of the page, timed from the gaps between ledger lines.** This said a page to be
    looked at costs 13 seconds against 17 for a text one — that is, no difference and the wrong
    way round. The expense sits in the extract lines, which carry a document and not a page, so
    joining them to a page's route silently dropped 636 of 1,406 lines on one archive.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from epicrisis import layout
from epicrisis.records import read_records

# A gap in the ledger longer than this is a run that was stopped and started again later, and the
# hours between belong to the person's day and not to the reading. Ten minutes, because the
# subscription's usage limit *stops* a run rather than waiting inside it (`parallel.py`), so there
# is no legitimate pause of that length in the middle of work.
A_PAUSE_IN_A_RUN = 600
# How many pages this instance has to have read before it will put a number on anything. Under
# this the fit is one afternoon's weather: the archive here with 69 pages is 63% out, and the two
# with hundreds are within 2%.
ENOUGH_TO_LEARN_FROM = 200
# What a page is, for the one distinction that turned out to matter. The words are the page's,
# not the reader's: somebody deciding whether to send their archive is not obliged to know that
# this program calls them routes.
A_PAGE_OF_TEXT = "text"
A_PAGE_TO_BE_LOOKED_AT = "vision"


@dataclass(frozen=True)
class Prices:
    """Seconds a page of each kind, and how much reading they were fitted on."""

    a_page_of_text: float
    a_page_to_be_looked_at: float
    pages_learnt_from: int
    hours_learnt_from: float


def waiting_by_kind(records: list[dict]) -> Counter:
    """How many pages of each kind an inventory holds, asked of the same code that reads them.

    `page_refs` is what the reading itself walks, so a page is counted here exactly as it will be
    read — and a file this program cannot take apart contributes nothing to either count rather
    than being guessed at from its extension.
    """
    from epicrisis.classify.pages import page_refs

    counted: Counter = Counter()
    for record in records:
        for ref in page_refs(record):
            counted[ref.route] += 1
    return counted


def _busy_and_pages(folder: Path) -> tuple[float, Counter]:
    """Seconds of work in one archive's ledger, and the pages of each kind it holds."""
    times = sorted(datetime.fromisoformat(line["at"])
                   for line in read_records(folder / layout.LEDGER)
                   if line.get("status") == "done" and line.get("at"))  # fmt: skip
    busy, last = 0.0, None
    for moment in times:
        if last is not None:
            between = (moment - last).total_seconds()
            if 0 < between <= A_PAUSE_IN_A_RUN:
                busy += between
        last = moment
    return busy, waiting_by_kind(list(read_records(folder / layout.INVENTORY)))


def prices(folders: list[Path]) -> Prices | None:
    """What a page of each kind has cost this instance, or None where too little has been read.

    The folders are given and never found here, because this answer stands beside a count of
    pages that some caller has already decided the scope of — the consent page speaks for every
    archive on the server, and a page about one archive would have to say so.

    Two unknowns out of however many archives have been read: the normal equations of a least
    squares fit, solved in four lines rather than by bringing in a library to do it. A single
    archive of one kind of page leaves the other price undetermined, and the determinant says so.
    """
    rows = []
    for folder in folders:
        if not (folder / layout.LEDGER).exists() or not (folder / layout.INVENTORY).exists():
            continue
        busy, pages = _busy_and_pages(folder)
        if busy > 0 and sum(pages.values()):
            rows.append((pages[A_PAGE_OF_TEXT], pages[A_PAGE_TO_BE_LOOKED_AT], busy))
    if sum(text + looked for text, looked, _ in rows) < ENOUGH_TO_LEARN_FROM:
        return None
    sxx = sum(text * text for text, _, _ in rows)
    syy = sum(looked * looked for _, looked, _ in rows)
    sxy = sum(text * looked for text, looked, _ in rows)
    sxb = sum(text * busy for text, _, busy in rows)
    syb = sum(looked * busy for _, looked, busy in rows)
    determinant = sxx * syy - sxy * sxy
    if not determinant:
        # Every archive read here is of one kind of page, so the other price is not a number this
        # history can produce. One price asked of two kinds would read as a measurement and be a
        # guess, and the pages say nothing rather than that.
        return None
    text_price = (sxb * syy - syb * sxy) / determinant
    looked_price = (syb * sxx - sxb * sxy) / determinant
    if text_price <= 0 or looked_price <= 0:
        # A fit that prices a page at nothing or less than nothing is a fit, not a measurement.
        return None
    return Prices(text_price, looked_price,
                  sum(text + looked for text, looked, _ in rows),
                  sum(busy for _, _, busy in rows) / 3600)  # fmt: skip


def hours_for(waiting: Counter, fitted: Prices | None) -> float | None:
    """About how many hours those pages will take, or None where there is nothing to say."""
    if fitted is None:
        return None
    seconds = (waiting[A_PAGE_OF_TEXT] * fitted.a_page_of_text
               + waiting[A_PAGE_TO_BE_LOOKED_AT] * fitted.a_page_to_be_looked_at)  # fmt: skip
    return seconds / 3600 if seconds > 0 else None


def in_words(hours: float | None) -> str:
    """The estimate as a person reads it, rounded to what it can actually support.

    Never a range of two figures: the fit is an order of magnitude, and "between 4 and 50 hours"
    was measured on this instance before the model was right, reads as a refusal, and is what the
    page already said in words. One number with "about" in front of it says the same honestly.
    """
    if hours is None:
        return ""
    if hours < 1:
        return f"about {max(round(hours * 60 / 5) * 5, 5)} minutes"
    if hours < 10:
        return f"about {hours:.0f} hour{'s' if round(hours) != 1 else ''}"
    return f"about {round(hours / 5) * 5} hours"
