"""Read-only questions to the index, for the MCP server and the Ask page.

Every answer carries where it came from: the file id, the pages and the document date, so an
answer can always be checked against the original. Values are given as printed; nothing here
computes, compares with reference ranges or interprets. Copies of the same document are
represented by one primary document unless a caller asks for all of them.
"""

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from epicrisis import everyday_words
from epicrisis import people
from epicrisis.index.build import SCHEMA_VERSION, index_path
from epicrisis.printed_values import also_written_as, fold, fold_with_offsets
from epicrisis.printed_values import in_name_order
from epicrisis.state import Unreadable
from epicrisis.values import only_results
from epicrisis.invocation import CLI

MAX_LIMIT = 200
# A tool's answer is read by a model and has to fit in what it can hold; a page of one test's
# history is read by the person whose history it is, and cutting it silently would make the
# count printed above it untrue. Charts of a few thousand points draw in a tenth of a second.
MAX_SERIES = 5000
SNIPPET_CHARS = 240
DOCUMENT_TEXT_CHARS = 20_000


class IndexMissing(Exception):
    """The index has not been built yet."""


def open_index(data_dir: Path, source_id: str | None) -> sqlite3.Connection:
    """The index of one archive. A connection holds one owner's records and no one else's.

    Which archive has no default, and the first entry of the constitution is why: a call that
    forgets it must fail rather than answer about somebody. It had one, and on an instance holding
    exactly one archive `open_index(data_dir)` handed that archive's own index to whoever asked —
    so a caller that had simply not got round to naming the archive was answered, correctly, until
    the day a second archive arrived. `choose_primary_copy` below, the door of this pair that
    writes, has never had one.

    `None` is still an answer, and it is a different thing from forgetting: it names the single
    index of an instance built before archives had owners, which is the only index there is
    between such an upgrade and the next `epicrisis index`. See `_the_only_index`.

    Three things can be wrong with it, and only one of them was answered. A missing index was
    answered well: every page said so and offered to build it, in a sentence that also promised
    nothing would be sent anywhere. An index that is there and will not open — a machine that died
    mid-build, a disk that filled, a file copied half-way — took every page of the dashboard down
    with the words Internal Server Error, including the status page and the settings page, which
    are the two places a person goes when something is wrong. An index built by another version of
    this program opened as though it were ours: at best a page failed on a column that is not
    there, at worst it answered questions from tables whose meaning had changed, and looked well
    while doing it. The MCP server had already been taught to answer all three in words; the owner
    of the archive, on their own screen, had not.
    """
    path = index_path(Path(data_dir), source_id)
    if not path.exists():
        path = _the_only_index(Path(data_dir), path, source_id)
    if not path.exists() or path.stat().st_size == 0:
        # A file of no bytes is an empty database to sqlite, which would answer every question
        # with "nothing" over an archive that has been read: an index cut off at nothing is one
        # that has not been built, and that already has a page of its own offering to build it.
        raise IndexMissing(f"Run '{CLI} index' first")
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.create_function("fold", 1, fold, deterministic=True)
        # sqlite3.connect opens nothing: it takes a path and returns. A file of zeroes, or half a
        # file, is met on the first read — and if that read is the first query a page happens to
        # make, the trouble arrives as a broken page and not as an answer. So the file is read here.
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        built_by = _version_of_the_index(connection)
    except (sqlite3.DatabaseError, OSError) as broken:
        raise Unreadable(
            path.name,
            "Nothing that was read is lost. The index holds no answer of its own: it is built "
            "from the files already on this machine, in seconds, without a model and without "
            "sending anything anywhere.",
            f"Build it again: '{CLI} index'.",
        ) from broken
    if "documents" not in tables:
        # Half a file: readable as a database, with none of this program's tables in it. Every page
        # would have failed on its own first query instead, which is a broken page and not an answer.
        connection.close()
        raise Unreadable(
            path.name,
            "It holds none of the tables an index of this program has, so a reading of it was cut "
            "off part-way. Nothing that was read is lost.",
            f"Build it again: '{CLI} index'.",
        )
    if built_by is not None and built_by != SCHEMA_VERSION:
        connection.close()
        raise Unreadable(
            path.name,
            f"It was built by another version of Epicrisis (index {built_by}, this one reads "
            f"{SCHEMA_VERSION}), and reading it as ours would answer from tables whose meaning has "
            "changed. Nothing that was read is lost.",
            f"Build it again: '{CLI} index'.",
        )
    return connection


def _version_of_the_index(connection: sqlite3.Connection) -> int | None:
    """Which version of this program's schema built this file, where the file says.

    None for an index built before the field was written, or by a version that kept no meta table:
    an old index that still answers every question asked of it is not a reason to refuse. The
    number was written into every index for six versions and read by nothing at all.
    """
    try:
        row = connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.OperationalError:
        return None  # no meta table: an index from before there was one. Not a damaged file.
    try:
        return int(row[0]) if row is not None else None
    except (TypeError, ValueError):
        return None


def _the_only_index(data_dir: Path, asked_for: Path, source_id: str | None) -> Path:
    """Where an archive's index is when it is not where it was asked for.

    Only for a caller that asked for no archive in particular: an index built before archives
    had owners sits in the old single file, and an instance with one archive has one index
    whatever it is called.

    A caller that named an archive is never given another one. That was a real leak: an archive
    added and not yet read has no index file, the only file in the folder is somebody else's,
    and every page answered from it under the new owner's name. An archive with no index has no
    index, and the page says so.

    The leak was closed by counting files rather than by asking whose they were, and counting
    left one shape out: an instance upgraded from before archives had owners, where a second
    archive was added on the dashboard before `epicrisis index` was next run. The old single file
    is then the only index there is, so "no per-owner index exists" was true, and the second
    archive's every page — the documents, the laboratory, the test, the value — came out of the
    first person's index under the second person's name. So the file is asked whose it is instead,
    which is a question it can answer: every document in an index carries the id of the archive
    it was read from, and has since before that single file was last written.
    """
    older = index_path(data_dir)
    if source_id is not None:
        # A named archive is answered from its own file, or from the one file that says in so many
        # words that these are that archive's documents, or from nothing at all.
        return older if _index_of_only(older) == source_id else asked_for
    per_owner = sorted(data_dir.glob("index-*.sqlite"))
    if older.exists():
        return older
    return per_owner[0] if len(per_owner) == 1 else asked_for


def _index_of_only(path: Path) -> str | None:
    """Which archive every document in this index was read from, where it is one archive.

    None for a file that is not there, will not open, holds no documents, holds documents of more
    than one archive, or is old enough not to have written the id down. Every one of those is an
    index that cannot be shown to be a named archive's own, and an index that cannot be shown to
    be somebody's is not handed to them: the whole point of asking is that the answer "I do not
    know whose this is" and the answer "it is yours" stop being the same answer.

    Nothing else here opens a database to decide which file to open, and this does it on one path
    only — a named archive whose own index file is missing — which is a page that is about to say
    there is nothing to show. The cost of being wrong in the other direction is the first line of
    the constitution.
    """
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
            whose = connection.execute("SELECT DISTINCT source_id FROM documents LIMIT 2").fetchall()
    except (sqlite3.DatabaseError, OSError):
        return None
    if len(whose) != 1 or not whose[0][0]:
        return None
    return str(whose[0][0])


def overview(connection: sqlite3.Connection) -> dict:
    """What the archive holds: counts, span of dates, types and languages.

    Copies are left out, as they are everywhere else a document is counted or listed: one blood
    draw filed in three files is one document, and a heading that counted three above a list of
    one was counting files while calling them documents.
    """
    row = connection.execute(
        "SELECT count(*) AS documents, sum(transcribed) AS transcribed, min(date) AS first_date, max(date) AS last_date,"
        " sum(date IS NULL) AS without_date FROM documents WHERE primary_copy = 1"
    ).fetchone()
    return {
        **dict(row),
        "values": connection.execute("SELECT count(*) FROM observations").fetchone()[0],
        "files": connection.execute("SELECT count(*) FROM files").fetchone()[0],
        "types": {r["doc_type"]: r["n"] for r in connection.execute("SELECT doc_type, count(*) AS n FROM documents WHERE primary_copy = 1 GROUP BY 1 ORDER BY 2 DESC")},
        "languages": {r["language"]: r["n"] for r in connection.execute("SELECT language, count(*) AS n FROM documents WHERE language IS NOT NULL AND primary_copy = 1 GROUP BY 1 ORDER BY 2 DESC")},
        "copy_groups": connection.execute("SELECT count(DISTINCT copy_group) FROM documents WHERE copy_group IS NOT NULL").fetchone()[0],
        "built_at": connection.execute("SELECT value FROM meta WHERE key = 'built_at'").fetchone()[0],
    }


def _match_of(query: str) -> str:
    """The words of a question, as FTS5 wants them, each one looked for both ways it may be typed.

    The question is **folded before its words are cut out of it**, and that order is the whole of
    it. Text pasted from a Mac arrives decomposed, and a combining accent split "πρωτεΐνη" into
    two half-words that matched nothing while the same text stored in the index had been folded
    and matched fine; the fold takes the accent off, so the word stays one word. One side folded
    and the other not is the worst of both, and it is the apostrophe that showed the order
    matters, not only the folding: cut first, a surname typed "Аб'ва" becomes the two words "аб"
    and "ва", and the index — which holds "абва" in one piece now that the fold drops the
    apostrophe — answers nothing at all. Folded first it is one word, and it matches both
    spellings of the surname, which is the point of dropping the apostrophe in the first place.

    And a word every letter of which is drawn alike in two alphabets is looked for in both: "В12"
    typed in Cyrillic on the form and "B12" typed in Latin by the person share no character at
    all, and an empty answer here is read as "the archive does not have it".
    """
    words = re.findall(r"[^\W_]+", fold(query), re.UNICODE)
    terms = []
    for word in words:
        folded = fold(word)
        if not folded:
            continue
        spellings = [folded, *also_written_as(folded)]
        terms.append("(" + " OR ".join(f'"{one}"*' for one in spellings) + ")" if len(spellings) > 1
                     else f'"{folded}"*')  # fmt: skip
    # AND between the words, spelled out. A space between two bare terms is an AND in FTS5 and
    # reads better, which is why it was written that way — but a space in front of a bracket is a
    # syntax error, and the moment a word above got a second spelling it came in brackets. So any
    # question of two words where either of them is drawn alike in two alphabets answered with
    # "fts5: syntax error near (" — which the dashboard showed as 500 and nothing recorded. Seven
    # of twelve ordinary questions were that shape: "витамин в12", "гемоглобин а1с", "vitamin b12",
    # "psa свободный", "са 125". Found by the journal on the day it was written, from one line.
    return " AND ".join(terms)


def search(connection: sqlite3.Connection, query: str, limit: int = 20, since: str | None = None, until: str | None = None,
           doc_type: str | None = None, all_copies: bool = False, offset: int = 0) -> list[dict]:  # fmt: skip
    """Documents whose text, title, institution or value names match the words of the query.

    A page of them, from offset. The tool that answers a model with this had no way to ask for the
    next page and no way to learn there was one: twenty-two matches answered as twenty, and the
    answer was shaped exactly like the answer to "that is all there is".
    """
    match = _match_of(query)
    if not match:
        return []
    rows = connection.execute(
        f"""SELECT d.id FROM search JOIN documents d ON d.id = search.rowid
            WHERE search MATCH ? {_filters(since, until, doc_type, all_copies)}
            ORDER BY bm25(search), d.date DESC LIMIT ? OFFSET ?""",
        (match, *_filter_values(since, until, doc_type), within_limit(limit), max(0, offset)),
    ).fetchall()
    return [{**_document_row(connection, row["id"]), "snippet": _snippet(connection, row["id"], query)} for row in rows]


# Paperwork, not medicine: appointment slips, insurance letters, receipts. They are kept and
# listed on their own, but they never held a result, so they do not belong in a list of records.
PAPERWORK = ("admin", "insurance")
# A blank page is not a document at all. It stays in the archive and on the status page, and it
# can be asked for by type, but it is never a line in a list of records.
NOT_A_RECORD = ("blank",)


def timeline(connection: sqlite3.Connection, since: str | None = None, until: str | None = None, doc_type: str | None = None,
             limit: int = 100, all_copies: bool = False, offset: int = 0, undated: bool = False,
             with_paperwork: bool = True, provider: str | None = None, doctor: str | None = None) -> list[dict]:  # fmt: skip
    """Documents by their own date, newest first. undated: only the ones carrying no date at all."""
    only = "AND d.date IS NULL" if undated else ""
    only += _without(doc_type, with_paperwork)
    by = (provider, doctor)
    rows = connection.execute(
        f"""SELECT id FROM documents d WHERE 1 = 1 {only} {_filters(since, until, doc_type, all_copies, by)}
            ORDER BY d.date IS NULL, d.date DESC, d.id LIMIT ? OFFSET ?""",
        (*_filter_values(since, until, doc_type, by), within_limit(limit), max(0, int(offset))),
    ).fetchall()
    return [_document_row(connection, row["id"]) for row in rows]


def count_documents(connection: sqlite3.Connection, since: str | None = None, until: str | None = None,
                    doc_type: str | None = None, all_copies: bool = False, undated: bool = False,
                    with_paperwork: bool = True, provider: str | None = None, doctor: str | None = None) -> int:  # fmt: skip
    """How many documents the same filters hold, so a page can say what it is not showing."""
    only = "AND d.date IS NULL" if undated else ""
    only += _without(doc_type, with_paperwork)
    by = (provider, doctor)
    return connection.execute(
        f"SELECT count(*) FROM documents d WHERE 1 = 1 {only} {_filters(since, until, doc_type, all_copies, by)}",
        _filter_values(since, until, doc_type, by),
    ).fetchone()[0]


def span_of_documents(connection: sqlite3.Connection, since: str | None = None, until: str | None = None,
                      doc_type: str | None = None, all_copies: bool = False, undated: bool = False,
                      with_paperwork: bool = True, provider: str | None = None,
                      doctor: str | None = None) -> dict:  # fmt: skip
    """From when to when the documents these filters hold run, for the heading over them.

    The same arguments as count_documents, and for the same reason it takes them: the timeline's
    heading printed the span of the whole archive over a cut of it, so a feed narrowed to one
    laboratory stood under "41 documents · 2013-03-06 – 2025-09-21" while showing ten documents of
    2019 to 2021 — and not one date in the heading belonged to anything on the page.
    """
    only = "AND d.date IS NULL" if undated else ""
    only += _without(doc_type, with_paperwork)
    by = (provider, doctor)
    row = connection.execute(
        f"""SELECT min(d.date) AS first_date, max(d.date) AS last_date FROM documents d
            WHERE 1 = 1 {only} {_filters(since, until, doc_type, all_copies, by)}""",
        _filter_values(since, until, doc_type, by),
    ).fetchone()
    return {"first_date": row["first_date"], "last_date": row["last_date"]}


def count_search(connection: sqlite3.Connection, query: str, since: str | None = None, until: str | None = None,
                 doc_type: str | None = None, all_copies: bool = False) -> int:  # fmt: skip
    """How many documents match, whether or not they all fit on the page.

    Every filter the page itself was narrowed by, or the count is of a different question. Without
    the dates, a search over a year answered "22 documents" where the page held two of them, and
    offered a next page that came back empty: the number said one thing, the list another, and the
    one reading it was a model writing about somebody's archive from what it was told.
    """
    match = _match_of(query)
    if not match:
        return 0
    return connection.execute(
        f"""SELECT count(*) FROM search JOIN documents d ON d.id = search.rowid
            WHERE search MATCH ? {_filters(since, until, doc_type, all_copies)}""",
        (match, *_filter_values(since, until, doc_type)),
    ).fetchone()[0]


def years(connection: sqlite3.Connection, doc_type: str | None = None, provider: str | None = None,
          doctor: str | None = None) -> list[dict]:  # fmt: skip
    """How many documents carry each year, oldest first. Years with nothing are years with nothing.

    Whose work, as well as which type: the bars and the rows drawn under them have to be of one
    set. The row of type tabs had exactly this defect with a year in force — the comment over that
    row in the page records what it cost — and a strip counted over the whole archive beside a feed
    narrowed to one doctor offers years that hold nothing of theirs.
    """
    by = (provider, doctor)
    rows = connection.execute(
        f"""SELECT CAST(substr(d.date, 1, 4) AS INTEGER) AS year, count(*) AS documents
            FROM documents d WHERE d.date IS NOT NULL {_filters(None, None, doc_type, False, by)}
            GROUP BY 1 ORDER BY 1""",
        _filter_values(None, None, doc_type, by),
    ).fetchall()
    return [dict(row) for row in rows]


def lanes(connection: sqlite3.Connection, since: str | None = None, until: str | None = None,
          doc_type: str | None = None) -> list[dict]:  # fmt: skip
    """Documents as points on a line, one lane per type: what kind of care happened when.

    `doc_type` narrows it to one lane. Without it, a type chosen in another view was carried in the
    address, applied to the years the axis is drawn from and not to the documents drawn on it.
    """
    rows = connection.execute(
        f"""SELECT d.doc_type, d.date, d.title, d.provider, d.first_page, f.file_id, d.source_id, d.file_sha256
            FROM documents d JOIN files f ON f.sha256 = d.file_sha256
            WHERE d.date IS NOT NULL {_filters(since, until, doc_type, False)}
            ORDER BY d.doc_type, d.date""",
        _filter_values(since, until, doc_type),
    ).fetchall()
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["doc_type"], []).append(dict(row))
    return sorted(
        ({"doc_type": doc_type, "documents": documents, "count": len(documents)} for doc_type, documents in grouped.items()),
        key=lambda lane: -lane["count"],
    )


# What a value is grouped under when the question is "what was measured". Two of these keys are not
# materials at all, and that is the point: they were one bucket, labelled "Not said", holding both a
# keratometry reading — measured on a person, in no sample — and a urea whose form carried two
# specimens at once, so that the panel could not answer for it. 705 of the first and 115 of the
# second in one real archive, and a person looking for the second saw a list made mostly of the
# first and stopped reading.
#
# not_a_sample: a model read the panel and said it is of no sample. An answer, and not work.
# unknown: nobody has been able to say yet, and somebody still can. That is the work.
NOT_A_SAMPLE, UNKNOWN_MATERIAL = "not_a_sample", "unknown"
MATERIAL_KEY = ("CASE WHEN o.material IS NOT NULL AND o.material != '' THEN o.material "
                "WHEN o.material_source = 'not_a_sample' THEN 'not_a_sample' ELSE 'unknown' END")


def material_is(material: str) -> str:
    """The condition for "this value is of that material", for a key that may not be a material."""
    if material in (NOT_A_SAMPLE, UNKNOWN_MATERIAL):
        return " AND " + MATERIAL_KEY + " = '" + material + "'"
    return " AND o.material = ?"


def drawn_against_a_day(include_derived: bool = False) -> str:
    """Which values the by-test view draws, in the one wording both halves of it ask with.

    The list of tests and the row of material tabs over it are two queries, and they asked two
    different questions: the tabs counted every value an indicator holds, the list only the ones
    it can draw a dot for. Three differences, none of them written down anywhere — a value from a
    document carrying no date has no place on a year axis, a value the laboratory derived is not
    drawn at all, and a form filed twice is counted once. Measured on 4 October 2026 over the
    three archives here, with the template above the list saying *"Every tab here means 'click and
    see this many'"*: the blood tab read 2048 over 1665 values, urine 1406 over 1220, and the
    smallest archive's blood 156 over 129.

    So it is one sentence, asked twice, rather than two sentences held together by care. A query
    that takes it joins `documents` as `d` and `observations` as `o`.
    """
    return (f"o.indicator_id IS NOT NULL AND d.date IS NOT NULL AND {only_results()}"
            f" AND d.primary_copy = 1{'' if include_derived else ' AND o.derived = 0'}")  # fmt: skip


def indicator_timeline(connection: sqlite3.Connection, material: str | None = None, limit: int = 40,
                       include_derived: bool = False, cap: int = MAX_LIMIT) -> list[dict]:  # fmt: skip
    """Per indicator: the days it was measured and the last value, as printed.

    cap is how many this caller may have at most, as it is for the values of one test: a tool
    keeps the small one, and the page that prints how many tests there are asks through
    `every_indicator` below.
    """
    conditions = drawn_against_a_day(include_derived)
    filters: list = []
    if material:
        conditions += material_is(material)
        if material not in (NOT_A_SAMPLE, UNKNOWN_MATERIAL):
            filters.append(material)
    rows = connection.execute(
        f"""SELECT o.indicator_id, i.label, o.value, o.unit, o.comparator, o.material,
                   {MATERIAL_KEY} AS material_key, d.date, d.source_id,
                   d.file_sha256, d.first_page, f.file_id
            FROM observations o JOIN documents d ON d.id = o.document_id
            JOIN files f ON f.sha256 = d.file_sha256 JOIN indicators i ON i.id = o.indicator_id
            WHERE {conditions}
            ORDER BY o.indicator_id, d.date""",
        tuple(filters),
    ).fetchall()
    grouped: dict[str, dict] = {}
    for row in rows:
        item = grouped.setdefault(
            row["indicator_id"],
            {"indicator_id": row["indicator_id"], "label": row["label"], "points": [], "materials": set()},
        )
        item["points"].append({"date": row["date"], "value": row["value"], "unit": row["unit"],
                               "comparator": row["comparator"], "source_id": row["source_id"],
                               "file_sha256": row["file_sha256"], "first_page": row["first_page"],
                               "file_id": row["file_id"]})  # fmt: skip
        # A value whose form did not say goes in as "none" rather than being left out: Protein is
        # printed without a material on a blood panel and as "urine" on a urine one, so counting
        # only the named ones made that pair look like one specimen — which is the very case the
        # answer below is guarding against.
        item["materials"].add(row["material_key"])
    series = []
    for item in grouped.values():
        last = item["points"][-1]
        # An indicator holds one printed name, and one printed name can be two tests: Protein is
        # the blood one and the urine one, because that is what the form calls both. Asked for one
        # material this cannot arise; asked for all of them, "the last value" would be whichever
        # was measured most recently, of whichever specimen, under a name a person reads as one
        # test. There is no honest single last value there, so there is none.
        of_one_material = len(item["materials"]) <= 1
        series.append({
            "indicator_id": item["indicator_id"], "label": item["label"], "points": item["points"],
            "count": len(item["points"]),
            "materials": sorted((name for name in item["materials"]
                                 if name not in (NOT_A_SAMPLE, UNKNOWN_MATERIAL)), key=in_name_order),  # fmt: skip
            "first_date": item["points"][0]["date"], "last_date": last["date"],
            "last_value": last["value"] if of_one_material else None,
            "last_unit": last["unit"] if of_one_material else None,
            "last_comparator": last["comparator"] if of_one_material else None,
        })  # fmt: skip
    # Commonest first, and where two have been measured as often, by the name a person reads
    # them under. A casefold alone put every label beginning with і, ї, є, ґ or ё below every
    # one beginning with я, which is the bottom of the list.
    series.sort(key=lambda item: (-item["count"], in_name_order(item["label"])))
    return series[: within_limit(limit, cap)]


def every_indicator(connection: sqlite3.Connection, material: str | None = None) -> list[dict]:
    """Every test of one material, not a page of them: what the "by test" view is made of.

    It prints how many tests there are beside the ones it draws — "Showing 40 of 161 tests" —
    so the whole list is what it has to be given, and how much that may be is decided here,
    once, as it is for the whole history of one test.

    The caller asked for a thousand and was handed two hundred, because an asked-for number is
    held to MAX_LIMIT, which is the cap for an answer a model reads and not for a page its own
    owner reads. The number printed above the list was then the length of the cut list, so it
    could never exceed the cap and could never disagree out loud. Measured when this was written:
    the largest material of the three archives here holds 161 tests, so the page is honest today
    with thirty-nine to spare, and the link offering to show every test does show every test. At
    201 it would say 200 and mean more, which is the seventh entry of the constitution, and the
    comment over MAX_SERIES says in the same words why a page's cap is not a tool's.
    """
    return indicator_timeline(connection, material=material, limit=MAX_SERIES, cap=MAX_SERIES)


def language_counts(connection: sqlite3.Connection) -> dict[str, int]:
    """Documents by the language they are written in. An empty search means nothing without this."""
    rows = connection.execute(
        "SELECT coalesce(language, 'not said') AS language, count(*) AS documents FROM documents GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    return {row["language"]: row["documents"] for row in rows}


def indicators_matching(connection: sqlite3.Connection, words: str | None,
                        everyday_words_too: bool = False) -> list[dict]:  # fmt: skip
    """Indicators whose label or any of its printed spellings holds these words.

    This is what makes a question asked in one language find values printed in another: the
    indicator already gathers the spellings, and a search that knows about it searches them all.

    `everyday_words_too` adds, where no name of any language held the words, the test an everyday
    word stands for — "sugar", which no form prints, for the row a laboratory prints as Glucose.
    `said` on a row carries the word that found it and is empty where the printed name itself did,
    so a page can say which of the two happened rather than let a reader think they typed the
    printed name. Only where nothing matched by name, so a question that already answers is never
    widened and no answer this gave before can change.

    It is off by default, and the default is the contract: the tools over the network promise that
    matching is literal and per-language, and `searched_every_spelling_of` on one of their answers
    would be untrue of a word that is nobody's spelling of anything. A model holding those tools
    knows that sugar is glucose without being told. The pages of the dashboard are the doors a
    person types into, and they are the ones that ask for this.
    """
    if not words or not words.strip():
        return []
    folded = fold(words)
    groups = [(row["id"], row["label"], json.loads(row["names"]))
              for row in connection.execute("SELECT id, label, names FROM indicators")]  # fmt: skip
    found = []
    for identifier, label, names in groups:
        # A spelling inside the question counts only when it is a word of its own: "АТ" for blood
        # pressure sits inside "цистатин" and would drag every question into the wrong indicator.
        if folded in fold(label) or any(folded in name or _stands_alone(name, folded) for name in names):
            found.append({"id": identifier, "label": label, "names": names, "said": ""})
    if found or not everyday_words_too:
        return found
    # "sugar" is printed on no form anywhere, and a person looking for their own blood sugar typed
    # it and was told the archive held nothing — over forty-four values of Glucose. See
    # everyday_words.py for what may be in that table and what may not.
    said = words.strip()
    for printed in everyday_words.stands_for(said):
        for identifier, label, names in groups:
            if any(item["id"] == identifier for item in found):
                continue
            if printed in fold(label) or any(printed in name or _stands_alone(name, printed) for name in names):
                found.append({"id": identifier, "label": label, "names": names, "said": said})
    return found


def _the_words_asked_for(name: str | None) -> list[str]:
    """The words of a question about a printed name, folded, in one place because two callers ask.

    The list of values and the count of them, and a count whose words were cut differently from
    the list's would say a total about another question. Folded before the words are cut out, for
    the reason _match_of gives: an apostrophe is not a letter and is not a space either, so
    "сер.об'ем ер." must come out as the words "сер", "обем" and "ер" rather than as "об" and
    "ем" — four substrings ANDed together find more than the name a person typed.
    """
    return re.findall(r"[^\W_]+", fold(name), re.UNICODE)


def _stands_alone(name: str, text: str) -> bool:
    return len(name) >= 4 and re.search(rf"(?<![^\W\d_]){re.escape(name)}(?![^\W\d_])", text) is not None


def _printed_names_where(query: str | None, include_derived: bool) -> tuple[str, list]:
    """Which printed names a question is about. One place, because two callers ask it: the page of
    them and the count of them, and a count that filtered differently would say the wrong total."""
    where = [only_results()]
    values: list = []
    if not include_derived:
        where.append("o.derived = 0")
    if query:
        where.append("fold(o.name) LIKE ?")
        values.append(f"%{fold(query)}%")
    return " AND ".join(where), values


def value_names(connection: sqlite3.Connection, query: str | None = None, limit: int = 100,
                include_derived: bool = False, offset: int = 0) -> list[dict]:  # fmt: skip
    """Names of values as the labs printed them, with how often and over which years. A page."""
    where, values = _printed_names_where(query, include_derived)
    rows = connection.execute(
        f"""SELECT o.name, o.unit, count(*) AS times, min(d.date) AS first_date, max(d.date) AS last_date, o.kind
            FROM observations o JOIN documents d ON d.id = o.document_id
            WHERE {where} GROUP BY fold(o.name), o.unit ORDER BY times DESC, o.name LIMIT ? OFFSET ?""",
        (*values, within_limit(limit), max(0, offset)),
    ).fetchall()
    return [dict(row) for row in rows]


def count_value_names(connection: sqlite3.Connection, query: str | None = None, include_derived: bool = False) -> int:
    """How many printed names match, whether or not they all fit on the page."""
    where, values = _printed_names_where(query, include_derived)
    return connection.execute(
        f"""SELECT count(*) FROM (SELECT o.name FROM observations o JOIN documents d ON d.id = o.document_id
            WHERE {where} GROUP BY fold(o.name), o.unit)""",
        tuple(values),
    ).fetchone()[0]


def indicator_list(connection: sqlite3.Connection, status: str | None = "approved", brief: bool = False,
                   limit: int | None = None, offset: int = 0) -> list[dict]:  # fmt: skip
    """Indicators in the index: one label over the many ways a test is printed.

    brief drops the spellings and keeps their number: the whole list of 466 indicators with every
    spelling is larger than a model's answer can hold, and a silently cut list is worse than a
    short one. Ask for one indicator's spellings with value_names when they are needed.
    """
    rows = connection.execute(
        f"""SELECT i.id, i.label, i.status, i.names, count(o.id) AS values_count, min(d.date) AS first_date, max(d.date) AS last_date,
                   group_concat(DISTINCT {MATERIAL_KEY}) AS materials
            FROM indicators i LEFT JOIN observations o ON o.indicator_id = i.id LEFT JOIN documents d ON d.id = o.document_id
            {"WHERE i.status = ?" if status else ""} GROUP BY i.id ORDER BY values_count DESC, i.label
            {"LIMIT ? OFFSET ?" if limit is not None else ""}""",
        ((status,) if status else ()) + ((within_limit(limit), max(0, int(offset))) if limit is not None else ()),
    ).fetchall()
    items = []
    for row in rows:
        item = {**dict(row), "materials": sorted(set((row["materials"] or "").split(",")))}
        names = json.loads(row["names"])
        item["names_count"] = len(names)
        if brief:
            item.pop("names")
        else:
            item["names"] = names
        items.append(item)
    return items


def count_indicators(connection: sqlite3.Connection, status: str | None = "approved") -> int:
    return connection.execute(
        "SELECT count(*) FROM indicators" + (" WHERE status = ?" if status else ""), (status,) if status else ()
    ).fetchone()[0]  # fmt: skip


def values(connection: sqlite3.Connection, name: str | None = None, since: str | None = None, until: str | None = None,
           include_derived: bool = False, all_copies: bool = False, limit: int = 200, indicator: str | None = None,
           material: str | None = None, cap: int = MAX_LIMIT) -> list[dict]:  # fmt: skip
    """Values of one indicator, or whose printed name contains the given words. As printed, oldest first.

    cap is how many this caller may have at most. A tool keeps the small one; the page of one
    test asks for the whole history, because it prints how many values there are beside them.
    """
    words = _the_words_asked_for(name)
    if indicator:
        conditions, words = "o.indicator_id = ?", [indicator]
    elif words:
        conditions = " AND ".join("fold(o.name) LIKE ?" for _ in words)
        words = [f"%{word}%" for word in words]
    else:
        return []
    if material:
        conditions += material_is(material)
        if material not in (NOT_A_SAMPLE, UNKNOWN_MATERIAL):
            words = [*words, material]
    rows = connection.execute(
        f"""SELECT o.name, o.value, o.value_numeric, o.comparator, o.unit, o.reference, o.flag, o.value_role, o.derived,
                   o.kind, o.material, {MATERIAL_KEY} AS material_key, o.material_source, o.corrected, o.table_heading, o.column_heading, o.snippet, o.page, d.id AS document_id, d.date,
                   d.date_precision, d.doc_type, d.provider, d.language, d.copy_group, d.primary_copy, f.file_id, o.indicator_id,
                   d.source_id, d.file_sha256, d.first_page, d.pages
            FROM observations o JOIN documents d ON d.id = o.document_id JOIN files f ON f.sha256 = d.file_sha256
            WHERE {conditions} {"" if include_derived else "AND o.derived = 0"}
            {_filters(since, until, None, all_copies)}
            ORDER BY d.date IS NULL, d.date, o.page LIMIT ?""",
        (*words, *_filter_values(since, until, None), within_limit(limit, cap)),
    ).fetchall()
    return [
        {**{name: value for name, value in dict(row).items() if name not in ("source_id", "file_sha256", "first_page")},
         "card_url": f"/documents/{row['source_id']}/{row['file_sha256']}/{row['first_page']}"}
        for row in rows
    ]  # fmt: skip


def values_with_no_material(connection: sqlite3.Connection, indicator: str) -> list[dict]:
    """Values of one test that nobody has named a specimen for, with what a correction needs.

    Not through values(), which is the shape the tools answer a model with and which deliberately
    drops the file and the pages: this is for the page where a person says what these were measured
    in, and a correction is written against the file, the pages of the document and the printed
    line. Only the values of the archive being looked at, because that is all that page holds.
    """
    return [
        dict(row)
        for row in connection.execute(
            f"""SELECT o.page, o.name, o.value, o.unit, o.reference, o.corrected, d.file_sha256, d.pages
                FROM observations o JOIN documents d ON d.id = o.document_id
                WHERE o.indicator_id = ? AND {MATERIAL_KEY} = '{UNKNOWN_MATERIAL}' AND {only_results()}
                ORDER BY d.date, o.page""",
            (indicator,),
        )
    ]  # fmt: skip


def whole_history(connection: sqlite3.Connection, indicator: str, material: str | None = None) -> list[dict]:
    """Every value of one test, not a page of them: what the page of one test is made of.

    It prints the count and the span of the whole history beside the values, so the whole
    history is what it has to be given. How much that may be is decided here, once.
    """
    return values(connection, indicator=indicator, material=material, limit=MAX_SERIES, cap=MAX_SERIES)


def count_values(connection: sqlite3.Connection, indicator: str | None = None, material: str | None = None,
                 include_derived: bool = False, all_copies: bool = False,
                 since: str | None = None, until: str | None = None,
                 name: str | None = None, indicators: tuple[str, ...] = ()) -> int:  # fmt: skip
    """How many values one test has here, whether or not a page asks for all of them.

    Under the same period as the list it is counting, or the count answers a different question
    from the one that was asked: a caller narrowing to a year and told the total of every year
    would report a whole history as a cut-off page of one.

    `name` and `indicators` count the union a question by printed name really gathers: the values
    whose own name holds the words, and the values of every indicator that name matched. Counted as
    separate sums they were both wrong — a value under both was counted twice, a value under the
    name alone not at all — and the answer said "these are the 50 earliest of 89" where 185 matched.
    """
    if name is not None or indicators:
        words = _the_words_asked_for(name)
        by_name = " AND ".join("fold(o.name) LIKE ?" for _ in words)
        pieces = ([f"({by_name})"] if words else []) + (
            [f"o.indicator_id IN ({', '.join('?' for _ in indicators)})"] if indicators else [])
        if not pieces:
            return 0
        conditions, words = "(" + " OR ".join(pieces) + ")", [f"%{word}%" for word in words] + list(indicators)
    else:
        conditions, words = "o.indicator_id = ?", [indicator]
    if material:
        conditions += material_is(material)
        if material not in (NOT_A_SAMPLE, UNKNOWN_MATERIAL):
            words = [*words, material]
    row = connection.execute(
        f"""SELECT count(*) FROM observations o JOIN documents d ON d.id = o.document_id
            WHERE {conditions} {"" if include_derived else "AND o.derived = 0"}
            {_filters(since, until, None, all_copies)}""",
        (*words, *_filter_values(since, until, None)),
    ).fetchone()
    return int(row[0])



def printed_at_another_scale(connection: sqlite3.Connection, placing) -> dict[int, float]:
    """Values a form printed at a scale of its own, and what it takes to read them on one.

    A test printed at two scales — a specific gravity of 1,015 on one form and 1015 on the next —
    is drawn as one history on a chart, and a list that judges each value against its own printed
    range has to know the same thing, or it reports a scale as an excursion. Which values those
    are is decided in units.py, by the rules the caller passes; this only asks the question of
    every test in the archive at once, because the answer needs the whole of a test and not the
    page of it somebody happened to ask for.

    The band moves by its own distance and not the value's: a form with the range printed and the
    number written in by hand has named two scales, not one.

    A test here is every value of one indicator, one specimen and one unit, and the unit is the
    one the charts read rather than the spelling a form happened to print.
    """
    from epicrisis.rules.subjects import Series, Value
    from epicrisis.series import _join_equivalent, printed_range
    from epicrisis.units import unit_key

    rules = [rule for rule in placing if rule.kind == "value-against-its-printed-range"]
    if not rules:
        return {}
    # The same reading of a unit the chart makes, and for the same reason. Grouped by the printed
    # spelling, one unit written in two alphabets — "мкмоль/л" on one form, "umol/L" on the next —
    # was two series here and one history on the chart: each half held printed ranges standing at a
    # single scale, so neither half could see that the test is printed at two, and the rows whose
    # number and range disagree went out over the network as values outside their range after all.
    # A unit named inside a printed range counts for the same reason, where the form printed no
    # unit column of its own; whether it is read at all is the person's switch, not this list's.
    # The spellings of one measure that only the archive's own numbers can join — per litre beside
    # per microlitre — are joined by the chart's own function rather than by a second copy of it
    # here, because a second copy is how the two came apart in the first place.
    from_range = next((rule for rule in placing if rule.kind == "unit-from-the-printed-range"), None)
    rows = connection.execute(
        f"""SELECT o.rowid AS row_id, o.indicator_id, o.material, o.unit, o.value_numeric, o.reference
            FROM observations o WHERE o.indicator_id IS NOT NULL AND {only_results()} AND o.derived = 0"""
    ).fetchall()
    series: dict[tuple, dict[str, list[dict]]] = {}
    # Folded once per spelling and not once per value: an archive holds a hundred and fifty
    # spellings of a unit and tens of thousands of values, and folding each value's own took half
    # again as long over forty thousand rows, on a function the list asks for every answer.
    folded: dict[str | None, str] = {}
    for row in rows:
        item = dict(row)
        spelling = item["unit"]
        if spelling not in folded:
            folded[spelling] = unit_key(spelling)
        key = folded[spelling]
        if not key and from_range:
            key = from_range.check.run(Value(item=item), from_range.settings) or ""
        series.setdefault((item["indicator_id"], item["material"]), {}).setdefault(key, []).append(item)
    moves: dict[int, float] = {}
    for by_unit in series.values():
        for items in _join_equivalent(by_unit).values():
            subject = Series(numbers=[item["value_numeric"] for item in items],
                             bands=[printed_range(item["reference"]) for item in items])  # fmt: skip
            for rule in rules:
                powers = rule.check.run(subject, rule.settings)
                if not any(value or band for value, band in powers):
                    continue
                for item, (value, band) in zip(items, powers, strict=True):
                    if value or band:
                        moves[item["row_id"]] = 10.0 ** (value - band)
                break
    return moves


def flagged_values(connection: sqlite3.Connection, since: str | None = None, until: str | None = None,
                   flag: str | None = None, indicator: str | None = None, include_derived: bool = False,
                   all_copies: bool = False, compare_with_printed_range: bool = False, limit: int = 100,
                   offset: int = 0, placing=()) -> tuple[list[dict], dict, int]:  # fmt: skip
    """Values a laboratory itself marked, for looking over a whole period at once.

    The mark is the one printed on the form — H, L, an asterisk, an arrow. The archive never adds
    one: whether a value sits outside its range is not the application's to say.

    compare_with_printed_range asks for the other thing, and it is not the same: the number is
    compared with the range printed beside it on the same form. That is the application doing
    arithmetic on a person's results, so the caller has to have been allowed it — the MCP server
    passes it only where the person has taken every limit off their own instance. What comes back
    is a statement about that laboratory's printed range and nothing more. Values whose range cannot be read plainly are left
    out rather than guessed, so this is a way to look, never a count of what is wrong.
    """
    from epicrisis.reference import outside

    where = ["1 = 1"] if compare_with_printed_range else ["o.flag IS NOT NULL", "trim(o.flag) <> ''"]
    extra: list = []
    if flag:
        where.append("lower(trim(o.flag)) = lower(?)")
        extra.append(flag.strip())
    if indicator:
        where.append("o.indicator_id = ?")
        extra.append(indicator)
    if compare_with_printed_range:
        where += ["o.reference IS NOT NULL", "o.value_numeric IS NOT NULL"]
    moved = printed_at_another_scale(connection, placing) if compare_with_printed_range else {}
    rows = connection.execute(
        f"""SELECT o.rowid AS row_id, o.name, o.value, o.value_numeric, o.comparator, o.unit, o.reference, o.flag, o.value_role, o.derived,
                   o.kind, o.material, o.material_source, o.corrected, o.table_heading, o.page, d.id AS document_id, d.date, d.doc_type,
                   d.provider, f.file_id, o.indicator_id, d.source_id, d.file_sha256, d.first_page
            FROM observations o JOIN documents d ON d.id = o.document_id JOIN files f ON f.sha256 = d.file_sha256
            WHERE {" AND ".join(where)} AND {only_results()} {"" if include_derived else "AND o.derived = 0"}
            {_filters(since, until, None, all_copies)}
            ORDER BY d.date IS NULL, d.date, o.page""",
        (*extra, *_filter_values(since, until, None)),
    ).fetchall()
    items = []
    counts = {"outside": 0, "inside": 0, "range_not_read": 0}
    if compare_with_printed_range:
        # The three counts above read as a whole divided into three, and they are not: the values
        # whose form printed no range beside them at all are cut by the WHERE clause above and
        # appear in none of them. On the older forms in an archive like this — no unit column, no
        # range column — that can be a large part of it, and a count that leaves it unnamed is a
        # count that overstates how much was looked at.
        counts["no_range_printed"] = connection.execute(
            f"""SELECT count(*) FROM observations o JOIN documents d ON d.id = o.document_id
                WHERE {" AND ".join(one for one in where if one not in ("o.reference IS NOT NULL", "o.value_numeric IS NOT NULL"))}
                  AND (o.reference IS NULL OR o.value_numeric IS NULL)
                  AND {only_results()} {"" if include_derived else "AND o.derived = 0"}
                  {_filters(since, until, None, all_copies)}""",
            (*extra, *_filter_values(since, until, None)),
        ).fetchone()[0]  # fmt: skip
    for row in rows:
        item = {**{name: value for name, value in dict(row).items() if name not in ("source_id", "file_sha256", "first_page", "row_id")},
                "card_url": f"/documents/{row['source_id']}/{row['file_sha256']}/{row['first_page']}"}  # fmt: skip
        if compare_with_printed_range:
            # Where the form printed the number and the range at different scales, the number is
            # brought to the range before they are compared. Nothing is stored and nothing shown
            # changes: only the comparison is made on one scale instead of two.
            scale = moved.get(row["row_id"])
            # The unit the form printed goes with them, for the one line it settles: a form that
            # printed both bands of a test on one line, each with its own unit, printed one of
            # them for this value and the unit says which. Without it such a line is not read at
            # all and the value lands in range_not_read, which is the honest answer where the
            # form printed no unit either.
            verdict = outside(row["value_numeric"] * scale if scale else row["value_numeric"],
                              row["reference"], row["comparator"], row["unit"])  # fmt: skip
            if scale:
                item["read_on_the_printed_scale"] = True
            counts["range_not_read" if verdict is None else "outside" if verdict else "inside"] += 1
            if verdict is not True:
                continue
            item["outside_printed_range"] = True
        items.append(item)
    start = max(0, int(offset))
    # How many there are in all, which this function has in its hands and used to throw away: it
    # reads every matching row and then cuts a page out of them, so the number costs nothing. Six
    # values came back to a caller that had asked for a hundred, under a line saying the next page
    # begins at six — and a model reading that asks the same question again with a larger limit.
    # That was one of two repeated calls in a run of ten. See _page in mcp_server.
    return items[start : start + within_limit(limit)], counts, len(items)


PARTS = ("values", "sections", "text", "diagnoses", "medications", "unreadable", "to_check", "copies")
DEFAULT_PART_LIMIT = 50


def document(connection: sqlite3.Connection, document_id: int | None = None, file_id: str | None = None,
             first_page: int | None = None, with_text: bool = True, parts: tuple[str, ...] | list[str] | None = None,
             offset: int = 0, limit: int = DEFAULT_PART_LIMIT, text_offset: int = 0) -> dict | None:  # fmt: skip
    """One document: header, values, sections, text, findings and the documents it copies.

    A long document does not fit in one answer, and an answer cut in the middle loses lines
    without saying so. So each part is returned a page at a time and the document says what is
    left: "more": {"values": {"total": 209, "returned": 50, "next_offset": 50}}. parts asks for
    some of them only, for instance ("sections", "text") when the words matter and not the table.
    """
    if document_id is None:
        row = connection.execute(
            "SELECT d.id FROM documents d JOIN files f ON f.sha256 = d.file_sha256 WHERE f.file_id = ?"
            + (" AND d.first_page = ?" if first_page else "") + " ORDER BY d.first_page LIMIT 1",
            (file_id, first_page) if first_page else (file_id,),
        ).fetchone()  # fmt: skip
        if row is None:
            return None
        document_id = row["id"]
    base = _document_row(connection, document_id)
    if base is None:
        return None
    wanted = tuple(parts) if parts else PARTS
    start, size = max(0, int(offset)), within_limit(limit)
    whole = {
        "values": lambda: [dict(r) for r in connection.execute(
            "SELECT name, value, value_numeric, comparator, unit, reference, flag, value_role, derived, indicator_id, material,"
            " corrected, table_heading, column_heading, page, snippet FROM observations WHERE document_id = ? ORDER BY page, id", (document_id,))],
        "sections": lambda: [dict(r) for r in connection.execute(
            "SELECT page, heading, text FROM sections WHERE document_id = ? ORDER BY page", (document_id,))],
        "diagnoses": lambda: [r["text"] for r in connection.execute("SELECT text FROM diagnoses WHERE document_id = ?", (document_id,))],
        "medications": lambda: [r["text"] for r in connection.execute("SELECT text FROM medications WHERE document_id = ?", (document_id,))],
        "unreadable": lambda: [dict(r) for r in connection.execute("SELECT page, what, why FROM unreadable WHERE document_id = ?", (document_id,))],
        "to_check": lambda: _findings(connection, document_id),
        "copies": lambda: _copies(connection, base["copy_group"], document_id),
    }  # fmt: skip
    counts = {
        "values": connection.execute("SELECT count(*) FROM observations WHERE document_id = ?", (document_id,)).fetchone()[0],
        "sections": connection.execute("SELECT count(*) FROM sections WHERE document_id = ?", (document_id,)).fetchone()[0],
        "diagnoses": connection.execute("SELECT count(*) FROM diagnoses WHERE document_id = ?", (document_id,)).fetchone()[0],
        "medications": connection.execute("SELECT count(*) FROM medications WHERE document_id = ?", (document_id,)).fetchone()[0],
        "unreadable": connection.execute("SELECT count(*) FROM unreadable WHERE document_id = ?", (document_id,)).fetchone()[0],
        "text_chars": connection.execute(
            "SELECT coalesce(sum(length(text)), 0) FROM page_texts WHERE document_id = ?", (document_id,)).fetchone()[0],
    }  # fmt: skip
    # Counts of every part, whatever was asked for: a caller can see what it has not been given.
    found: dict = {**base, "parts": list(wanted), "counts": counts}
    more: dict = {}
    for name, read in whole.items():
        if name not in wanted:
            continue
        items = read()
        page = items[start : start + size]
        found[name] = page
        if len(items) > start + len(page):
            more[name] = {"total": len(items), "returned": len(page), "next_offset": start + len(page)}
    if "text" in wanted and with_text:
        text = "\n\n".join(r["text"] for r in connection.execute(
            "SELECT text FROM page_texts WHERE document_id = ? ORDER BY page", (document_id,)))  # fmt: skip
        from_here = max(0, int(text_offset))
        found["text"] = text[from_here : from_here + DOCUMENT_TEXT_CHARS]
        if len(text) > from_here + len(found["text"]):
            more["text"] = {"total_chars": len(text), "returned_chars": len(found["text"]), "next_text_offset": from_here + len(found["text"])}
    else:
        found["text"] = None
    if more:
        found["more"] = more
    return found


def _its_data_dir(connection: sqlite3.Connection) -> Path | None:
    """The data directory this index file sits in, so the archive's own rules can be read.

    A rule written for this archive lives in <data>/rules/ and its findings are in the index
    under its own id. Asked without the directory, the vocabulary knows only the rules that
    shipped, and a code it has never heard of used to be an index error rather than a name it
    could not put a label on — which took down the whole answer, for every document at once.
    """
    for _sequence, name, file in connection.execute("PRAGMA database_list"):
        if name == "main" and file:
            return Path(file).parent
    return None


def count_to_check(connection: sqlite3.Connection, code: str | None = None) -> int:
    """How many documents the validation flagged, whether or not they all fit on the page."""
    return connection.execute(
        "SELECT count(DISTINCT document_id) FROM findings" + (" WHERE code = ?" if code else ""),
        (code,) if code else (),
    ).fetchone()[0]


def to_check(connection: sqlite3.Connection, code: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    """Documents the validation flagged, worst first. A page of them, from offset."""
    from epicrisis.validate import vocabulary

    said = vocabulary(_its_data_dir(connection))
    order = {code: position for position, code in enumerate(said)}
    rows = connection.execute(
        "SELECT document_id, code, count FROM findings" + (" WHERE code = ?" if code else ""), (code,) if code else ()
    ).fetchall()
    by_document: dict[int, list] = {}
    for row in rows:
        by_document.setdefault(row["document_id"], []).append(
            {"code": row["code"], "count": row["count"], "what": said.get(row["code"], {}).get("label", row["code"])}
        )  # fmt: skip
    documents = []
    for document_id, findings in by_document.items():
        findings.sort(key=lambda item: order.get(item["code"], len(order)))
        documents.append({**_document_row(connection, document_id), "to_check": findings})
    documents.sort(key=lambda item: order.get(item["to_check"][0]["code"], len(order)))
    return documents[max(0, offset) : max(0, offset) + within_limit(limit)]


def _document_row(connection: sqlite3.Connection, document_id: int) -> dict | None:
    row = connection.execute(
        """SELECT d.id AS document_id, d.date, d.date_precision, d.date_printed, d.date_by_hand, d.date_flags, d.doc_type,
                  d.language, d.title, d.provider, d.department, d.person_printed_as_the_institution,
                  d.pages, d.transcribed, d.model, d.unreadable_count,
                  d.finding_count, d.copy_group, d.primary_copy, f.file_id, d.source_id, d.file_sha256,
                  (SELECT count(*) FROM observations o WHERE o.document_id = d.id) AS value_count
           FROM documents d JOIN files f ON f.sha256 = d.file_sha256 WHERE d.id = ?""",
        (document_id,),
    ).fetchone()
    if row is None:
        return None
    # The path of the file is deliberately not among these columns. These rows are what the tools
    # answer a model with over the network, and the path is the name the owner gave the file
    # inside their own folders — which in an archive like this is a surname, a laboratory, often
    # the reason for the visit. Nothing outside this machine needs it: file_id names the file, and
    # card_url reaches it. The pages of the interface take the path from their own layer, where it
    # never leaves the browser on this machine.
    item = dict(row)
    item.pop("file_sha256")
    item["pages"] = json.loads(item["pages"])
    item["date_flags"] = json.loads(item["date_flags"] or "[]")
    source_id = item.pop("source_id")
    item["original_pages_url"] = [f"/sources/{source_id}/files/{row['file_sha256']}/pages/{page}" for page in item["pages"]]
    item["card_url"] = f"/documents/{source_id}/{row['file_sha256']}/{item['pages'][0]}"
    return item


def _findings(connection: sqlite3.Connection, document_id: int) -> list[dict]:
    from epicrisis.validate import vocabulary

    said = vocabulary(_its_data_dir(connection))
    rows = connection.execute("SELECT code, count FROM findings WHERE document_id = ?", (document_id,))
    # A code with no label is still a finding. The label is what a person reads, and not having
    # one is a reason to show the code itself, never a reason for the answer to fail.
    return [{"code": r["code"], "count": r["count"], "what": said.get(r["code"], {}).get("label", r["code"])}
            for r in rows]  # fmt: skip


def _copies(connection: sqlite3.Connection, copy_group: int | None, document_id: int) -> list[dict]:
    if copy_group is None:
        return []
    rows = connection.execute(
        "SELECT d.id FROM documents d WHERE d.copy_group = ? AND d.id != ?", (copy_group, document_id)
    ).fetchall()
    return [_document_row(connection, row["id"]) for row in rows]


def _snippet(connection: sqlite3.Connection, document_id: int, query: str) -> str | None:
    """A piece of the document's own text around the query, taken from the original wording.

    The words are cut out of the folded question, for the reason _match_of gives: a name typed
    with an apostrophe is one word and not two, and cut the other way round both halves of "Аб'ва"
    are two letters long and thrown away by the length test below — so the piece shown was the
    opening of the document rather than the place the name stands.
    """
    texts = [r["text"] for r in connection.execute("SELECT text FROM page_texts WHERE document_id = ? ORDER BY page", (document_id,))]
    words = [word for word in re.findall(r"[^\W_]+", fold(query), re.UNICODE) if len(word) > 2]
    for text in texts:
        folded, offsets = fold_with_offsets(text)
        for word in words:
            found = folded.find(word)
            if found != -1:
                start = max(0, offsets[found] - SNIPPET_CHARS // 3)
                return ("…" if start else "") + text[start : start + SNIPPET_CHARS].strip() + "…"
    return (texts[0][:SNIPPET_CHARS].strip() + "…") if texts else None


def _without(doc_type: str | None, with_paperwork: bool) -> str:
    """What a list of records leaves out when nothing was asked for by type."""
    if doc_type:
        return ""
    kinds = [*NOT_A_RECORD, *([] if with_paperwork else PAPERWORK)]
    return " AND d.doc_type NOT IN ({})".format(", ".join(f"'{kind}'" for kind in kinds))


def _filters(since: str | None, until: str | None, doc_type: str | None, all_copies: bool,
             by: tuple[str | None, str | None] = (None, None)) -> str:  # fmt: skip
    parts = []
    if since:
        parts.append("AND d.date >= ?")
    if until:
        parts.append("AND d.date <= ?")
    if doc_type:
        parts.append("AND d.doc_type = ?")
    # Whose work this is: the institution that made the document, or the person who saw, performed
    # or signed. As printed, letter for letter — one doctor is written five ways across an archive
    # and this program does not decide that two spellings are one person.
    for column, wanted in (("provider", by[0]), ("doctor", by[1])):
        if wanted:
            parts.append(f"AND d.{column} IN ({', '.join('?' * len(_spellings(wanted)))})")
    if not all_copies:
        parts.append("AND d.primary_copy = 1")
    return " ".join(parts)


def _filter_values(since: str | None, until: str | None, doc_type: str | None,
                   by: tuple[str | None, str | None] = (None, None)) -> tuple:  # fmt: skip
    named = [name for wanted in by if wanted for name in _spellings(wanted)]
    return (*(value for value in (since, until, doc_type) if value), *named)


def _spellings(wanted) -> list[str]:
    """A name as asked for, or every spelling it stands for where a person joined several."""
    return list(wanted) if isinstance(wanted, (list, tuple, set)) else [wanted]


# Written on the forms of five countries, and all of it means one of two things. A value is read
# by what it starts with, because a form writes "позитивна", "поз(+)", "pos." and "+" for one
# answer. Anything that is neither is not an answer and is not compared with one.
RH_POSITIVE = ("поз", "pos", "θετ", "+")
RH_NEGATIVE = ("нег", "neg", "αρν", "-")
#: The letter of a blood group, as the alphabets and the typists of five countries write it: the
#: digit nought and the letters O of two alphabets are one group, and so are А and A, В and B.
ABO_LETTERS = {"0": "O", "o": "O", "о": "O", "a": "A", "а": "A", "b": "B", "в": "B"}


def _rh_of(value: str | None) -> str | None:
    """Positive or negative, where the value says one of them plainly. Nothing where it does not."""
    said = fold(value).strip().lstrip("(").strip()
    for answer, words in (("positive", RH_POSITIVE), ("negative", RH_NEGATIVE)):
        if any(said.startswith(word) for word in words):
            return answer
    return None


def _abo_of(value: str | None) -> str | None:
    """The group a value names — O, A, B or AB — however the form wrote its letter."""
    letters = [ABO_LETTERS[ch] for ch in fold(value) if ch in ABO_LETTERS]
    if not letters:
        return None
    if letters[:2] == ["A", "B"]:
        return "AB"
    return letters[0]


#: What the line is about, read from the name the form printed. Without this the reader of a
#: group letter was handed the Rh lines too, and "негативна" gave it an А and a В and it answered
#: "AB" — a page crying wolf about a blood group, on the one line where it must not.
GROUP_NAMES = ("група крові", "группа крови", "blood group", "blood type", "grupo sanguíneo",
               "grupo sanguineo", "ομάδα αίματος", "ομαδα αιματος")  # fmt: skip
#: Five languages, as the group above is, and two letters long in three of them — which is why no
#: reader of these may look inside a printed name for them. Spanish and Greek forms write the Latin
#: "Rh" as well, so this list is shorter than its neighbour and not because a language is missing.
RH_NAMES = ("rh", "резус", "rhesus")

#: How many answers to one of these questions the first tab of the card shows. It counts answers
#: and never the rows they were read from: an archive carries one blood group on every form that
#: ever asked for one, and counting rows meant the first fact on the page spent the whole budget.
AT_MOST = 8

#: The words a form prints over a height. A height belongs with the blood group and not with the
#: measurements that make a series: it is about the person rather than about the day they came in.
HEIGHT_NAMES = ("зріст", "ріст", "рост", "height", "talla", "altura", "ύψος")


def _is_height(name: str | None) -> bool:
    """Whether a printed name is a height, read from the start of the name and never from inside it.

    The substring match the blood group uses cannot be used here: "рост" stands inside "прирост",
    which a form prints of a change over time and not of the person, and the card would then carry
    a line that answers nothing about them.
    """
    folded = fold(name).strip().lstrip("(").strip()
    return any(folded.startswith(fold(word)) for word in HEIGHT_NAMES)


def _is_rh(name: str | None) -> bool:
    """Whether a printed name is the Rh of the person, and not a word with those letters inside it.

    "Rh" is two letters, and read as a substring it stood inside "Rheumatoid factor", "Arrhythmia",
    "Cirrhosis" and "Diarrhea". The card printed a rheumatoid factor on the personal tab as "Rh
    negative", and the tab that names disagreements then put it against the real Rh and said the
    documents fell out about the resus factor of the person — a page crying wolf, invented out of
    two lines that never disagreed about anything.

    The start of the name is not enough by itself here, as it is for a height: "Rheumatoid" starts
    with "rh". So the word has to end where it ends — what follows must not be another letter, and
    a form writing "Rh-фактор", "Rh (D)", "Rh+" or "Резус-фактор" is read, while one writing
    "Rheumatoid" is not.
    """
    folded = fold(name).strip().lstrip("(").strip()
    for word in RH_NAMES:
        said = fold(word)
        if folded.startswith(said) and not folded[len(said):len(said) + 1].isalpha():
            return True
    return False


def _is_group(name: str | None) -> bool:
    """Whether a printed name is the blood group of the person.

    Read as a substring, which is safe here and is not for its neighbour: each of GROUP_NAMES is a
    phrase of two words, so none of them stands inside a single word a form prints, and a form that
    writes "Група крові (АВ0)" or "Blood group / Rh" is read by looking inside its own line.
    """
    return _about(name, GROUP_NAMES)


def _about(name: str | None, words) -> bool:
    folded = fold(name)
    return any(fold(word) in folded for word in words)


def _where_they_disagree(blood: list[dict]) -> list[dict]:
    """Documents of one archive that print different answers to one question about the person.

    Said as a disagreement and never settled: two forms printing two blood groups is one of them
    being wrong, and which is not a thing this program can know. What it can do is put the two
    lines side by side with the date and the page each came from.

    A difference of spelling is not a disagreement. "0 (І)" and "O (І)" are the same group written
    with a nought and with a letter, and a page that called those a conflict would cry wolf on the
    one line where it must not.
    """
    found = []
    for about, reading, is_it in (("blood group", _abo_of, _is_group), ("Rh", _rh_of, _is_rh)):
        lines = [one for one in blood if is_it(one["name"]) and reading(one["value"])]
        answers = {reading(one["value"]) for one in lines}
        if len(answers) > 1:
            found.append({"about": about, "answers": sorted(answers),
                          "lines": _one_page_of_each(lines, reading)})  # fmt: skip
    return found


def _one_page_of_each(lines: list[dict], reading) -> list[dict]:
    """The newest page printing each answer first, and the pages after those up to the limit.

    Every answer is shown before any answer is shown twice, which is what a page naming a
    disagreement owes the reader: a limit that falls on one side of it leaves the page saying two
    forms differ and showing only one of them. That is what happened while the limit was taken off
    the rows before they reached here — nine forms printing one answer and one printing the other,
    and the one went over the edge with nothing saying so.
    """
    newest: dict = {}
    for one in lines:
        newest.setdefault(reading(one["value"]), one)
    shown = list(newest.values())
    after = [one for one in lines if not any(one is already for already in shown)]
    return shown + after[:max(0, AT_MOST - len(shown))]


def patient_card(connection: sqlite3.Connection) -> dict:
    """What the documents of this archive print about the person, rather than about one day.

    Diagnoses, medications, and the handful of facts a form states about the person themselves —
    the sex, the date of birth, the blood group, the Rh and the height — each as printed, grouped
    by the printed words and counted, with the newest document that carries it. The page shows
    them a tab apart, which is why they come back a key apart rather than in one list.

    Nothing here is a judgement: a medication
    printed in 2019 is a medication printed in 2019, and whether it is still taken is not a thing
    a program can read off a page. The page says so, and the newest date is there for a person to
    judge by.

    Newest first, and that is the whole order. It used to be by how many documents carried a line,
    with the date only breaking a tie, and the owner of an archive read the top of his medications
    and asked why they stopped in 2014: a drug prescribed to him this year stood on one document,
    under one prescribed in 1992 that had been copied into four. On a page whose question is what
    this person is on, the count is a remark and the date is the answer. Both are printed; only
    their order changed.
    """
    def roll(table: str) -> list[dict]:
        rows = connection.execute(
            f"""SELECT t.text AS text, count(*) AS documents, max(d.date) AS last_date, min(d.date) AS first_date,
                       (SELECT d2.id FROM {table} t2 JOIN documents d2 ON d2.id = t2.document_id
                        WHERE t2.text = t.text AND d2.primary_copy = 1
                        ORDER BY d2.date IS NULL, d2.date DESC LIMIT 1) AS newest
                FROM {table} t JOIN documents d ON d.id = t.document_id
                WHERE d.primary_copy = 1 AND trim(t.text) != ''
                GROUP BY t.text ORDER BY max(d.date) IS NULL, max(d.date) DESC, count(*) DESC"""
        ).fetchall()
        return [dict(row, **_where(connection, row["newest"])) for row in rows]

    blood = connection.execute(
        """SELECT o.name AS name, o.value AS value, o.unit AS unit, d.date AS date, d.id AS newest
           FROM observations o JOIN documents d ON d.id = o.document_id
           WHERE d.primary_copy = 1 ORDER BY d.date IS NULL, d.date DESC"""
    ).fetchall()
    # Two readings and not one list of words: a blood group is a phrase and is looked for inside
    # the printed line, an Rh is two letters and has to end where it ends. Asked as one substring
    # list, "rh" picked up a rheumatoid factor, an arrhythmia, a cirrhosis and a diarrhoea, and the
    # card then printed one of them as this person's Rh.
    # Uncut here, and cut by the tab that shows them. These are one row per document, and the
    # limit used to be taken off them: one answer printed on nine forms spent the whole of it, and
    # the fact printed beside it — the Rh under the blood group — fell off the first tab and out of
    # the disagreements with it, where neither the page nor anything else said a word about it.
    about_the_person = [dict(row, **_where(connection, row["newest"])) for row in blood
                        if _is_group(row["name"]) or _is_rh(row["name"])]  # fmt: skip
    height_lines = [dict(row, **_where(connection, row["newest"])) for row in blood
                    if _is_height(row["name"])]  # fmt: skip
    # Read once and used twice. Sex and the date of birth were read only to be compared, so the
    # two facts a form states most plainly about a person could be seen on the card only when the
    # documents fell out about them; reading them again for the personal tab would be a second
    # pass over every page text of the archive for the same two answers.
    sex, births = _sex_said(connection), _births_said(connection)
    return {"diagnoses": roll("diagnoses"), "medications": roll("medications"),
            "blood": about_the_person,
            "personal": _about_the_person(sex, births, about_the_person, height_lines),
            "conflicts": (_where_they_disagree(about_the_person) + _sex_disagrees(sex)
                          + _births_disagree(births))}  # fmt: skip


def _about_the_person(sex: dict, births: dict, blood: list[dict], height: list[dict]) -> list[dict]:
    """The few lines a form states about the person rather than about the day they came in.

    Every answer the documents state, not one of them chosen: where two pages print two blood
    groups both stand here, because choosing between them is the thing this program must not do.
    The tab that names them as a disagreement is the fourth one, and it says so there.

    A value stands once however many pages carry it, under the newest of them, which is the page
    a person opens to check it. The limit is on those values and not on the rows they were read
    from, and that is the whole of it: it used to be taken off the rows, one per document, before
    anything had been folded together, so a single blood group printed on nine forms used the lot
    and the Rh printed beside it on the same nine never reached the tab. Nothing said it had been
    left out, which is the part that makes it a defect rather than a short page — and the limit is
    per fact, so a long run of one of them can no longer crowd out another.
    """
    lines = [{"about": "Sex", **one} for one in sex.values()]
    lines += [{"about": "Date of birth", **one} for one in births.values()]
    for named, rows in (("Blood group", [one for one in blood if _is_group(one["name"])]),
                        ("Rh", [one for one in blood if _is_rh(one["name"])]),
                        ("Height", height)):  # fmt: skip
        seen: dict[str, dict] = {}
        for one in rows:
            seen.setdefault(fold(one["value"]), {"about": named, **one})
        lines += list(seen.values())[:AT_MOST]
    # The form's own word for the fact, where it is not the word this page uses. A person checking
    # a line against the page has to be able to find it there, and "Blood group" is not what is
    # printed on a Ukrainian form.
    for line in lines:
        line["printed"] = line["name"] if fold(line["name"]) != fold(line["about"]) else None
    return lines


def _births_said(connection: sqlite3.Connection) -> dict:
    """Every date of birth the pages of this archive print, under the newest page that prints it."""
    from epicrisis.about_the_person import birth_dates_printed

    said: dict = {}
    for row in connection.execute(
        """SELECT p.text AS text, d.language AS language, d.id AS document, d.date AS date
           FROM page_texts p JOIN documents d ON d.id = p.document_id WHERE d.primary_copy = 1
           ORDER BY d.date IS NULL, d.date DESC"""
    ):
        for printed in birth_dates_printed(row["text"], row["language"]):
            said.setdefault(printed, {"name": "Date of birth", "value": printed.isoformat(), "unit": None,
                                      "date": row["date"], **_where(connection, row["document"])})  # fmt: skip
    return said


def _births_disagree(said: dict) -> list[dict]:
    """Where the pages of one archive print two dates of birth: one of them is another person's.

    A year printed alone is not a disagreement with the day of that same year — a form that prints
    "1975" and one that prints "06.12.1975" say the same thing with different care.
    """
    from epicrisis.about_the_person import dates_disagree

    if not dates_disagree(set(said)):
        return []
    return [{"about": "date of birth", "answers": sorted(one["value"] for one in said.values()),
             "lines": list(said.values())}]  # fmt: skip


def _sex_said(connection: sqlite3.Connection) -> dict[str, dict]:
    """Which sexes the pages of this archive state. Read from a labelled field and nowhere else.

    Only the words the forms of five countries use for an answer count as one: a form printing
    "Ч/Ж" against an empty box offers two choices and states nothing, and a page that read that as
    an answer would cry wolf on every archive holding such a form.
    """
    from epicrisis.about_the_person import sex_as_printed

    said: dict[str, dict] = {}
    for row in connection.execute(
        """SELECT p.text AS text, d.id AS document, d.date AS date FROM page_texts p
           JOIN documents d ON d.id = p.document_id WHERE d.primary_copy = 1
           ORDER BY d.date IS NULL, d.date DESC"""
    ):
        for answer in sex_as_printed(row["text"]):
            said.setdefault(answer, {"name": "Sex", "value": answer, "unit": None,
                                     "date": row["date"], **_where(connection, row["document"])})  # fmt: skip
    return said


def _sex_disagrees(said: dict[str, dict]) -> list[dict]:
    """Where the pages of one archive state two sexes. One of the two is not this person's."""
    if len(said) < 2:
        return []
    return [{"about": "sex", "answers": sorted(said), "lines": list(said.values())}]


def _where(connection: sqlite3.Connection, document_id: int | None) -> dict:
    """Enough of a document to make a link to its card: the file it is in and its first page."""
    if document_id is None:
        return {"source_id": None, "file_sha256": None, "first_page": None}
    row = connection.execute(
        "SELECT source_id, file_sha256, first_page FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    return dict(row) if row else {"source_id": None, "file_sha256": None, "first_page": None}


def who_made_them(connection: sqlite3.Connection, groups: list | None = None) -> list[dict]:
    """The institutions and doctors read into those two fields of this archive, with how many each.

    **It said "every institution and doctor named on the documents of this archive", and that is
    not true.** A name reaches this list by having been read into the provider or the doctor field
    of a document; a surname printed inside the document's own text and nowhere else never arrives
    here, and nothing in this query can find it. Measured on the archive it was read on: the doctor
    field is filled on 20 of its 414 documents, and 38 documents carry a labelled surname in their
    transcribed text — 20 distinct names — that is in no field. The owner looked on the page this
    feeds for two doctors he had seen, by their surnames, did not find either, and concluded the
    archive did not hold them. See how_many_name_them, which is the count that says so.

    As printed and nothing else. One doctor is written "Нетудихата І.В", "Нетудихата І. В." and
    "уролог Нетудихата" across one archive, and joining those is the same question as joining the
    printed names of one test — a person's to answer, not a program's to guess. Where a document
    names an institution and a person both, it stands under each of them.
    """
    rows = connection.execute(
        """SELECT provider, doctor, count(*) AS documents, min(date) AS first_date, max(date) AS last_date
           FROM documents d WHERE primary_copy = 1 AND (provider IS NOT NULL OR doctor IS NOT NULL)
           GROUP BY provider, doctor"""
    ).fetchall()
    together: dict[tuple[str, str], dict] = {}
    for row in rows:
        for whose, name in (("institution", row["provider"]), ("doctor", row["doctor"])):
            if not name:
                continue
            # Under the name a person chose for them, where they said two spellings are one.
            shown = people.label_of(groups, whose, name) if groups else name
            found = together.setdefault((whose, shown), {"what": whose, "name": shown, "documents": 0,
                                                         "first_date": None, "last_date": None,
                                                         "spellings": set()})  # fmt: skip
            found["documents"] += row["documents"]
            found["spellings"].add(name)
            for edge, which in (("first_date", min), ("last_date", max)):
                dates = [date for date in (found[edge], row[edge]) if date]
                found[edge] = which(dates) if dates else None
    for one in together.values():
        one["spellings"] = sorted(one["spellings"], key=in_name_order)
    # On the most documents first, and then by the name itself — ordered by its bare code points,
    # a doctor whose surname begins with І stood under every doctor whose surname begins with Я.
    return sorted(together.values(), key=lambda one: (-one["documents"], in_name_order(one["name"])))


def how_many_name_them(connection: sqlite3.Connection) -> dict[str, int]:
    """How many documents this archive holds, and on how many of them each of the two was read.

    The denominator the page of doctors and clinics needs in order to say what it is a page of.
    Without it that page carried a promise — every institution and every doctor — which it cannot
    keep and which was read as one: a name that was never read into either field is not on it, and
    a person who does not find a doctor there concludes the archive does not hold them.

    Counted over the primary copy of each document, which is what every other count of "the
    documents of this archive" means (`overview`) and what `who_made_them` gathers over. The two
    numbers then stand on one page without disagreeing, which §7 asks of them. A field that is
    there and empty counts as none, because `who_made_them` skips a falsy name too.
    """
    row = connection.execute(
        """SELECT count(*) AS documents,
                  sum(coalesce(provider, '') <> '') AS institution,
                  sum(coalesce(doctor, '') <> '') AS doctor
           FROM documents WHERE primary_copy = 1"""
    ).fetchone()
    # sum() over no rows is null, not nought, and an archive whose index holds no documents yet is
    # the one this page is first opened on.
    return {which: int(row[which] or 0) for which in ("documents", "institution", "doctor")}


def within_limit(limit: int, cap: int = MAX_LIMIT) -> int:
    """How many a caller may actually have. Every asked-for number passes through here."""
    return max(1, min(int(limit), cap))


def copy_groups(connection: sqlite3.Connection) -> list[dict]:
    """Documents the checks found to be copies of one another, group by group.

    One of each group stands for it: that one answers a question, and the others are reachable
    but do not repeat the answer. The group is what a person needs to see to agree or to choose
    differently, so it comes back whole, with the chosen one marked and the reasons beside each
    member — which model read it, how much it holds, what could not be read.
    """
    rows = connection.execute(
        """SELECT d.id, d.copy_group, d.primary_copy, d.file_sha256, d.first_page, d.pages, d.doc_type,
                  d.date, d.date_printed, d.title, d.provider, d.model, d.unreadable_count, d.date_by_hand,
                  f.file_id, f.path,
                  (SELECT count(*) FROM observations o WHERE o.document_id = d.id) AS values_count
           FROM documents d JOIN files f ON f.sha256 = d.file_sha256
           WHERE d.copy_group IS NOT NULL
           ORDER BY d.copy_group, d.primary_copy DESC, d.date"""
    ).fetchall()
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        item = dict(row)
        item["pages"] = json.loads(item["pages"]) if item["pages"] else [item["first_page"]]
        item["chosen"] = bool(item.pop("primary_copy"))
        grouped.setdefault(item["copy_group"], []).append(item)
    groups = [
        {"group": number, "members": members, "count": len(members),
         "date": next((item["date"] for item in members if item["date"]), None)}
        for number, members in grouped.items()
    ]  # fmt: skip
    groups.sort(key=lambda group: (group["date"] or "", group["group"]), reverse=True)
    return groups


def choose_primary_copy(data_dir: Path, source_id: str | None, file_sha256: str, first_page: int) -> dict | None:
    """Mark one document of a group of copies as the one that answers.

    Returns the chosen document's pages and every other member of its group, or None where there
    is no group. The other members come back because the caller has to take the choice off them
    as well: a choice kept only as "this one" left the one before it still written down, and the
    next indexing found two chosen documents in one group and picked between them by the quality
    of the transcription — that is, it silently undid what the person had pressed, and did it
    again every time they pressed it.

    The choice is a person's, kept in corrections.jsonl by the caller; this writes it into the
    index so the answer changes at once rather than at the next indexing. Only the one column
    moves, and only inside the group the document already belongs to.
    """
    path = index_path(Path(data_dir), source_id)
    if not path.exists():
        path = _the_only_index(Path(data_dir), path, source_id)
    if not path.exists():
        raise IndexMissing(f"Run '{CLI} index' first")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT id, copy_group, pages, first_page FROM documents WHERE file_sha256 = ? AND first_page = ?",
            (file_sha256, first_page),
        ).fetchone()
        if row is None or row["copy_group"] is None:
            return None
        others = [
            {"file_sha256": member["file_sha256"],
             "pages": json.loads(member["pages"]) if member["pages"] else [member["first_page"]]}
            for member in connection.execute(
                "SELECT file_sha256, pages, first_page FROM documents WHERE copy_group = ? AND id != ?",
                (row["copy_group"], row["id"]),
            )
        ]  # fmt: skip
        with connection:
            connection.execute(
                "UPDATE documents SET primary_copy = (id = ?) WHERE copy_group = ?", (row["id"], row["copy_group"])
            )
        return {"pages": json.loads(row["pages"]) if row["pages"] else [row["first_page"]], "others": others}
    finally:
        connection.close()


def unreadable_parts(connection: sqlite3.Connection) -> dict[tuple[str, int], list[dict]]:
    """What a model said it could not read, by document: its own words, page by page.

    Most of these are a signature or a stamp and want nothing from anybody. Which is which is
    visible from the description alone, so the description belongs on the page that lists them,
    rather than behind three hundred and fifty clicks.
    """
    rows = connection.execute(
        """SELECT d.file_sha256, d.first_page, u.page, u.what, u.why
           FROM unreadable u JOIN documents d ON d.id = u.document_id
           ORDER BY d.file_sha256, u.page"""
    ).fetchall()
    found: dict[tuple[str, int], list[dict]] = {}
    for row in rows:
        found.setdefault((row["file_sha256"], row["first_page"]), []).append(
            {"page": row["page"], "what": row["what"], "why": row["why"]}
        )
    return found


def materials_present(connection: sqlite3.Connection, include_derived: bool = False) -> dict[str, int]:
    """Every material this archive printed, and how many values it has, with the two absences apart.

    See MATERIAL_KEY: a value with no material is one of two things, and calling both of them
    "not said" put seven hundred measurements that are of no sample — a refraction, the width of a
    kidney, a blood pressure — in front of a hundred lab values that lost their label on a form
    holding two specimens. The first is not work; the second is.

    These are the numbers on the tabs over the by-test view, so they count what pressing a tab
    will draw and nothing else: `drawn_against_a_day` is that condition, written once and asked
    here and by `indicator_timeline`, which is the list underneath.
    """
    return {
        row["material_key"]: row["n"]
        for row in connection.execute(
            f"SELECT {MATERIAL_KEY} AS material_key, count(*) AS n"
            f" FROM observations o JOIN documents d ON d.id = o.document_id"
            f" WHERE {drawn_against_a_day(include_derived)} GROUP BY material_key"
        )
    }
