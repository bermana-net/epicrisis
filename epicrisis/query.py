"""Read-only questions to the index, for the MCP server and the Ask page.

Every answer carries where it came from: the file id, the pages and the document date, so an
answer can always be checked against the original. Values are given as printed; nothing here
computes, compares with reference ranges or interprets. Copies of the same document are
represented by one primary document unless a caller asks for all of them.
"""

import json
import re
import unicodedata
import sqlite3
from pathlib import Path

from epicrisis.index.build import SCHEMA_VERSION, index_path
from epicrisis.printed_values import also_written_as, fold, fold_with_offsets
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


def open_index(data_dir: Path, source_id: str | None = None) -> sqlite3.Connection:
    """The index of one archive. A connection holds one owner's records and no one else's.

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
    """
    older = index_path(data_dir)
    per_owner = sorted(data_dir.glob("index-*.sqlite"))
    if source_id is not None:
        # A named archive is answered from its own file or from nothing. The one exception is an
        # instance upgrading from before archives had owners: its single file is that archive's,
        # and it is only that archive's while no per-owner index exists at all.
        return older if older.exists() and not per_owner else asked_for
    if older.exists():
        return older
    return per_owner[0] if len(per_owner) == 1 else asked_for


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

    The question is normalised before its words are cut out of it: text pasted from a Mac arrives
    decomposed, and a combining accent split "πρωτεΐνη" into two half-words that matched nothing,
    while the same text stored in the index had been folded and matched fine. One side normalised
    and the other not is the worst of both.

    And a word every letter of which is drawn alike in two alphabets is looked for in both: "В12"
    typed in Cyrillic on the form and "B12" typed in Latin by the person share no character at
    all, and an empty answer here is read as "the archive does not have it".
    """
    words = re.findall(r"[^\W_]+", unicodedata.normalize("NFC", query or ""), re.UNICODE)
    terms = []
    for word in words:
        folded = fold(word)
        if not folded:
            continue
        spellings = [folded, *also_written_as(folded)]
        terms.append("(" + " OR ".join(f'"{one}"*' for one in spellings) + ")" if len(spellings) > 1
                     else f'"{folded}"*')  # fmt: skip
    return " ".join(terms)


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
             with_paperwork: bool = True) -> list[dict]:  # fmt: skip
    """Documents by their own date, newest first. undated: only the ones carrying no date at all."""
    only = "AND d.date IS NULL" if undated else ""
    only += _without(doc_type, with_paperwork)
    rows = connection.execute(
        f"""SELECT id FROM documents d WHERE 1 = 1 {only} {_filters(since, until, doc_type, all_copies)}
            ORDER BY d.date IS NULL, d.date DESC, d.id LIMIT ? OFFSET ?""",
        (*_filter_values(since, until, doc_type), within_limit(limit), max(0, int(offset))),
    ).fetchall()
    return [_document_row(connection, row["id"]) for row in rows]


def count_documents(connection: sqlite3.Connection, since: str | None = None, until: str | None = None,
                    doc_type: str | None = None, all_copies: bool = False, undated: bool = False,
                    with_paperwork: bool = True) -> int:  # fmt: skip
    """How many documents the same filters hold, so a page can say what it is not showing."""
    only = "AND d.date IS NULL" if undated else ""
    only += _without(doc_type, with_paperwork)
    return connection.execute(
        f"SELECT count(*) FROM documents d WHERE 1 = 1 {only} {_filters(since, until, doc_type, all_copies)}",
        _filter_values(since, until, doc_type),
    ).fetchone()[0]


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


def years(connection: sqlite3.Connection, doc_type: str | None = None) -> list[dict]:
    """How many documents carry each year, oldest first. Years with nothing are years with nothing."""
    rows = connection.execute(
        f"""SELECT CAST(substr(d.date, 1, 4) AS INTEGER) AS year, count(*) AS documents
            FROM documents d WHERE d.date IS NOT NULL {_filters(None, None, doc_type, False)}
            GROUP BY 1 ORDER BY 1""",
        _filter_values(None, None, doc_type),
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


def indicator_timeline(connection: sqlite3.Connection, material: str | None = None, limit: int = 40,
                       include_derived: bool = False) -> list[dict]:  # fmt: skip
    """Per indicator: the days it was measured and the last value, as printed."""
    conditions = f"o.indicator_id IS NOT NULL AND d.date IS NOT NULL AND {only_results()}"
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
            WHERE {conditions} {"" if include_derived else "AND o.derived = 0"}
            {_filters(None, None, None, False)}
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
            "materials": sorted(name for name in item["materials"]
                                if name not in (NOT_A_SAMPLE, UNKNOWN_MATERIAL)),  # fmt: skip
            "first_date": item["points"][0]["date"], "last_date": last["date"],
            "last_value": last["value"] if of_one_material else None,
            "last_unit": last["unit"] if of_one_material else None,
            "last_comparator": last["comparator"] if of_one_material else None,
        })  # fmt: skip
    series.sort(key=lambda item: (-item["count"], item["label"].casefold()))
    return series[: within_limit(limit)]


def language_counts(connection: sqlite3.Connection) -> dict[str, int]:
    """Documents by the language they are written in. An empty search means nothing without this."""
    rows = connection.execute(
        "SELECT coalesce(language, 'not said') AS language, count(*) AS documents FROM documents GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    return {row["language"]: row["documents"] for row in rows}


def indicators_matching(connection: sqlite3.Connection, words: str | None) -> list[dict]:
    """Indicators whose label or any of its printed spellings holds these words.

    This is what makes a question asked in one language find values printed in another: the
    indicator already gathers the spellings, and a search that knows about it searches them all.
    """
    if not words or not words.strip():
        return []
    folded = fold(words)
    found = []
    for row in connection.execute("SELECT id, label, names FROM indicators"):
        names = json.loads(row["names"])
        # A spelling inside the question counts only when it is a word of its own: "АТ" for blood
        # pressure sits inside "цистатин" and would drag every question into the wrong indicator.
        if folded in fold(row["label"]) or any(folded in name or _stands_alone(name, folded) for name in names):
            found.append({"id": row["id"], "label": row["label"], "names": names})
    return found


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
    words = [fold(word) for word in re.findall(r"[^\W_]+", name or "", re.UNICODE)]
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
                   d.date_precision, d.doc_type, d.provider, d.copy_group, d.primary_copy, f.file_id, o.indicator_id,
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
        words = [fold(word) for word in re.findall(r"[^\W_]+", name or "", re.UNICODE)]
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
    """
    from epicrisis.rules.subjects import Series
    from epicrisis.series import printed_range

    rules = [rule for rule in placing if rule.kind == "value-against-its-printed-range"]
    if not rules:
        return {}
    rows = connection.execute(
        f"""SELECT o.rowid AS row_id, o.indicator_id, o.material, o.unit, o.value_numeric, o.reference
            FROM observations o WHERE o.indicator_id IS NOT NULL AND {only_results()} AND o.derived = 0"""
    ).fetchall()
    series: dict[tuple, list] = {}
    for row in rows:
        series.setdefault((row["indicator_id"], row["material"], (row["unit"] or "").strip()), []).append(row)
    moves: dict[int, float] = {}
    for items in series.values():
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
                   offset: int = 0, placing=()) -> tuple[list[dict], dict]:  # fmt: skip
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
            verdict = outside(row["value_numeric"] * scale if scale else row["value_numeric"],
                              row["reference"], row["comparator"])  # fmt: skip
            if scale:
                item["read_on_the_printed_scale"] = True
            counts["range_not_read" if verdict is None else "outside" if verdict else "inside"] += 1
            if verdict is not True:
                continue
            item["outside_printed_range"] = True
        items.append(item)
    start = max(0, int(offset))
    return items[start : start + within_limit(limit)], counts


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
                  d.language, d.title, d.provider, d.department, d.pages, d.transcribed, d.model, d.unreadable_count,
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
    """A piece of the document's own text around the query, taken from the original wording."""
    texts = [r["text"] for r in connection.execute("SELECT text FROM page_texts WHERE document_id = ? ORDER BY page", (document_id,))]
    words = [word for word in re.findall(r"[^\W_]+", query, re.UNICODE) if len(word) > 2]
    for text in texts:
        folded, offsets = fold_with_offsets(text)
        for word in words:
            found = folded.find(fold(word))
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


def _filters(since: str | None, until: str | None, doc_type: str | None, all_copies: bool) -> str:
    parts = []
    if since:
        parts.append("AND d.date >= ?")
    if until:
        parts.append("AND d.date <= ?")
    if doc_type:
        parts.append("AND d.doc_type = ?")
    if not all_copies:
        parts.append("AND d.primary_copy = 1")
    return " ".join(parts)


def _filter_values(since: str | None, until: str | None, doc_type: str | None) -> tuple:
    return tuple(value for value in (since, until, doc_type) if value)


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


def materials_present(connection: sqlite3.Connection) -> dict[str, int]:
    """Every material this archive printed, and how many values it has, with the two absences apart.

    See MATERIAL_KEY: a value with no material is one of two things, and calling both of them
    "not said" put seven hundred measurements that are of no sample — a refraction, the width of a
    kidney, a blood pressure — in front of a hundred lab values that lost their label on a form
    holding two specimens. The first is not work; the second is.
    """
    return {
        row["material_key"]: row["n"]
        for row in connection.execute(
            f"SELECT {MATERIAL_KEY} AS material_key, count(*) AS n FROM observations o"
            f" WHERE o.indicator_id IS NOT NULL AND {only_results('o')} GROUP BY material_key"
        )
    }
