"""What a rule is handed to look at.

Every kind of check is called the same way — `run(subject, settings)` — and what differs is the
subject. A kind declares which one it takes, by name, so that a rule of that kind can be handed
the right thing without anyone reading the function to find out what its arguments mean.

Four subjects are enough for every check this program makes today, and they are four because
they are four different questions:

- `a series` — every value of one test, one material and one unit, oldest first. A check that
  needs the other readings to judge this one: a scale, a unit nothing else uses, a number far
  from the rest.
- `one value` — a single line of a form with what was printed beside it. A check that needs
  nothing but the line: a comparator that is printed and not stored, a range that reads
  backwards.
- `one document` — a transcription with the pages it came from and the text of those pages. A
  check that compares what was read with what the page holds.
- `the archive` — every document at once, for the questions that are about documents together,
  such as which of them are copies of one another.

A subject holds what was printed and nothing else. It never carries the means to change
anything: a rule is given a view of the archive, not a handle on it.
"""

from dataclasses import dataclass

A_SERIES = "a series"
ONE_VALUE = "one value"
ONE_MATERIAL = "one material"
ONE_DOCUMENT = "one document"
THE_ARCHIVE = "the archive"
LOOKS_AT = (A_SERIES, ONE_VALUE, ONE_MATERIAL, ONE_DOCUMENT, THE_ARCHIVE)


@dataclass(frozen=True)
class Found:
    """One thing a rule has to say about one document. The rule's own id is the code.

    A line of plain words for a person, and nowhere to put a verdict: a rule says where to look
    and why it looked, and stops there.
    """

    file_sha256: str
    first_page: int
    date: str | None
    line: str


@dataclass(frozen=True)
class Value:
    """One line of a form, with what the program has made of it so far.

    unit_key is the unit it is being drawn under at this moment, "" where the form printed
    none: a rule that places a value has to know where it stands before it can move it.
    """

    item: dict
    indicator: str | None = None
    unit_key: str = ""


@dataclass(frozen=True)
class Material:
    """Every chart of one specimen at once, kept by the unit each is drawn under.

    For the one question that is about the charts together: which scale a set of values with no
    unit at all belongs to is answered by the other scales of the same test, and by nothing else.
    """

    by_unit: dict[str, list[dict]]


@dataclass(frozen=True)
class Document:
    """One transcription, with what it was read from.

    item is the transcription itself, or None where the document was never read. sent_texts is
    the text of the pages that went to the model as text, page by page, for the checks that
    compare what came back with what the page holds; tabular_pages are the pages classification
    said carry a table.
    """

    file_sha256: str
    pages: tuple[int, ...]
    item: dict | None
    sent_texts: dict[int, str] = None
    tabular_pages: tuple[int, ...] = ()
    goes_to_extract: bool = False  # whether this document was one to transcribe at all
    date_flags: tuple[str, ...] = ()  # what document_dates.py could not settle about its date


@dataclass(frozen=True)
class Archive:
    """Every value and every document at once, for the questions that are about them together.

    habits and numbers are what one test usually prints — its units, and its readings per unit
    and specimen — worked out once by whoever assembled this and handed to every rule, because
    two rules needing the same medians should not each walk the archive to find them.
    """

    rows: list[dict]
    documents: list[dict]
    habits: dict = None
    numbers: dict = None


@dataclass(frozen=True)
class Series:
    """Every value of one test, one material and one unit, in the order they were printed.

    Numbers and bands run together: bands[i] is the reference range the same form printed beside
    numbers[i], or None where it printed none. A value that is not a number at all — "Absent",
    "traces" — is None in numbers and keeps its place, because its band still says something
    about the form it came from.
    """

    numbers: list[float | None]
    bands: list[tuple[float | None, float | None] | None]

    def __len__(self) -> int:
        return len(self.numbers)
