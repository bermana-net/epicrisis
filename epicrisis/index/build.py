"""Step 05: one SQLite index built from classify, extract, corrections and validation.

The index is derived data: it is rebuilt whole from the files under data/sources/ in seconds and
replaced atomically, so nothing is ever edited in it. Values stay as printed; a person's
corrections take their place next to them. Search text is folded (case, accents, Ukrainian and
Russian letter pairs) in a separate full-text table, and results are shown from the originals.

Documents found to be copies of each other form a copy group with one primary document, so a
result printed in two files is not counted twice.
"""

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from epicrisis import layout
from epicrisis.classify.pages import page_refs
from epicrisis.classify.report import goes_to_extract, group_documents, latest_pages
from epicrisis.corrections import CORRECTABLE, load_corrections, load_primary_copies, load_value_corrections, value_key
from epicrisis.settings import trusts_read_materials
from epicrisis.material_reading import load_materials, panel_key
from epicrisis.datesearch import load_search_results
from epicrisis.document_dates import document_date, provider_key, source_day_first
from epicrisis import indicators
from epicrisis.extract.run import load_extracted
from epicrisis.records import read_records
from epicrisis.printed_values import fold, number_tokens
from epicrisis.sources import Source, source_output_dir
from epicrisis.validate import load_validation
from epicrisis.runs import one_at_a_time, put_in_place, temporary_name

FILE_NAME = "index.sqlite"
SCHEMA_VERSION = 6

# Fields of a value a person may correct; everything else stays as the model read it.
# What was measured, from the heading of the table or the title of the document: the same name
# means a different test in urine and in blood ("Білок" in a urine panel is not serum protein).
MATERIALS = {
    # The words end where the word ends. "Мочевина" and "Мочевая кислота" are blood tests whose
    # Russian names begin with the word for urine, and "кесарево сечение" is not a specimen at
    # all: both were read as urine, and a title matches every value in its document.
    "urine": (r"сеч[іїея]\b|сечі\b|моч[иеаую]\b|urine|urina\b|urinari|orina|ουρ[ωο]|ούρων|uri-|urin"),
    "stool": (r"кал[аоуіы]?\b|фекал|копрограм|копрологи|stool|faec(?:es|al)|fec(?:es|al)|heces|"
              r"coprogram|coprolog|κοπραν|κοπράν|κοπρολογ"),
    "csf": r"ліквор|ликвор|спинномозков|cerebrospinal|líquido cefalorraqu|εγκεφαλονωτιαί",
    "saliva": r"слин[иа]|слюн|saliva|σίελο",
    "sputum": r"мокрот|sputum|esputo|πτύελ",
    "semen": r"спермограм|еякулят|эякулят|semen|sperm|σπέρμα",
    # A smear of blood is blood: the swab words stop where the form names what was smeared.
    "swab": r"мазок(?!\s+кров)|мазк(?!\w*\s+кров)|зіскр|соскоб|(?<!blood )smear|frotis|exudado|επίχρισμα",
    # Last, so that a form naming two things is read as the more particular one, and a urinalysis
    # that happens to say "кров" somewhere stays a urinalysis.
    # Every one of these is a word a form prints for what was put in the machine: blood itself,
    # its serum or plasma in five languages, or a word that means a count of blood ("hemograma").
    # "Pla-" is how one Spanish laboratory writes plasma in front of every name on its list.
    # "Blood pressure" is a measurement on a person, not a specimen put into a machine.
    "blood": (r"кров|крови|blood(?!\s*pressure)|sangre|sangu|αιμα|αίμα|αιματολογ|serum|suero|сироват|сыворот|"
              r"plasma|плазм|ορου|ορός|\bpla-|hemogram|haemogram|гемограм|гематолог"),
}
MATERIAL_PATTERNS = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in MATERIALS.items()}

# A row whose whole printed name is the name of a specimen is not a test. Some laboratories
# head a table with the test ("Мочевая кислота ммоль/л") and name each row for what the test was
# done on ("кровь", "моча"), which is the form printed sideways. Read straight, such a row
# becomes a test called "blood", filed under whatever indicator holds that word, with a material
# taken from the heading — three things wrong from one layout.
SPECIMEN_AS_A_NAME = {
    fold(word): material
    for material, words in {
        "blood": ("кров", "кровь", "крови", "сыворотка", "сироватка", "blood", "serum", "suero", "sangre", "plasma", "плазма"),
        "urine": ("моча", "мочи", "сеча", "сечі", "urine", "orina"),
        "stool": ("кал", "калу", "stool", "faeces", "heces"),
    }.items()
    for word in words
}  # fmt: skip


def inverted_tables(observations: list[dict]) -> set[str]:
    """The headings of tables printed sideways: every row named for a specimen, not for a test.

    Every row, not merely one: on a urinalysis "Кров" is one row of thirteen and is the test for
    blood in the urine, which is a real test and must not be turned into a specimen.
    """
    by_table: dict[str, list[dict]] = {}
    for observation in observations:
        heading = (observation.get("table_as_printed") or "").strip()
        if heading:
            by_table.setdefault(heading, []).append(observation)
    return {
        heading
        for heading, rows in by_table.items()
        if not SECTION_HEADING.search(heading)
        # A heading of one word is not the name of a test with a unit after it; a table headed
        # simply "Кров", holding one row called "кров", is something else and is left alone.
        and len(fold(heading).split()) > 1
        and all(fold(row.get("name_as_printed") or "").strip() in SPECIMEN_AS_A_NAME for row in rows)
    }  # fmt: skip


def analyte_of(heading: str, indicator_names: dict[str, str]) -> str | None:
    """The indicator a table heading names, with its trailing unit dropped if it carries one."""
    parts = fold(heading).split()
    for cut in range(len(parts), 0, -1):
        found = indicator_names.get(" ".join(parts[:cut]))
        if found:
            return found
    return None


# Blood is read from a heading and never from the name of a value. On a urine strip "Кров" is a
# test, not the specimen, and "Реакція на приховану кров" is printed on a stool form. A heading
# says what the laboratory put in the machine; a value name says what it looked for.
FROM_A_HEADING_ONLY = frozenset({"blood"})

# A form printed on two sheets. The front is headed with what was measured ("АНАЛІЗ СЕЧІ
# ЗАГАЛЬНИЙ"); the back carries only the name of the section it continues ("Мікроскопічне
# дослідження"), because on paper it is obvious which form it is the back of. Read as two
# documents, the back says nothing about material, and its sediment — leukocytes, erythrocytes,
# protein, casts — falls in among blood values. The heading of a section is not the heading of a
# form, so a document headed with one takes the material of the form on the page before it.
SECTION_HEADING = re.compile(r"мікроскопічн|микроскопич|microscop|μικροσκοπ|осад(?:ок)?\b|sediment", re.IGNORECASE)

# Values a lab calculates from others (filtration rates): named so, or given in a rate unit.
# Folded before it is matched, so the Greek is written without accents and with the plain sigma
# a final ς folds to, and the Ukrainian abbreviation stands beside the Russian one.
DERIVED_NAME = re.compile(r"egfr|\bgfr\b|ckd[\s-]*epi|mdrd|cockcroft|скф|шкф|рскф|клубоч|fgp|filtrac|filtrad|filtrat|"
                          r"клирен|клиренс|ρυθμοσ\s+σπειραματ|σπειραματικησ\s+διηθησ")  # fmt: skip
# A filtration rate is printed per body surface: "mL/min/1.73 m²". Millilitres per minute alone
# is a rate of something else — an infusion, a diuresis — and calling those calculated hid
# measured values from every chart. Where a laboratory prints no surface, the name says eGFR.
RATE_UNIT = re.compile(r"^\s*(ml|мл)\s*/\s*(min|мин|хв)\s*/\s*1[.,]73")

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE sources (id TEXT PRIMARY KEY, name TEXT);
CREATE TABLE files (
    sha256 TEXT PRIMARY KEY, file_id TEXT, source_id TEXT, path TEXT, category TEXT, page_count INTEGER
);
CREATE TABLE documents (
    id INTEGER PRIMARY KEY, source_id TEXT, file_sha256 TEXT, first_page INTEGER, pages TEXT, doc_type TEXT,
    language TEXT, title TEXT, provider TEXT, department TEXT,
    date TEXT, date_precision TEXT, date_printed TEXT, date_by_hand INTEGER, date_flags TEXT,
    study_date_printed TEXT, report_date_printed TEXT,
    transcribed INTEGER, model TEXT, prompt_version TEXT, extracted_at TEXT,
    unreadable_count INTEGER, finding_count INTEGER, copy_group INTEGER, primary_copy INTEGER
);
CREATE TABLE observations (
    id INTEGER PRIMARY KEY, document_id INTEGER, page INTEGER, kind TEXT, table_heading TEXT, name TEXT,
    value TEXT, value_numeric REAL, comparator TEXT, value_kind TEXT, value_role TEXT, unit TEXT,
    reference TEXT, flag TEXT, method TEXT, column_heading TEXT, reference_column_heading TEXT, snippet TEXT,
    derived INTEGER, indicator_id TEXT, material TEXT, material_source TEXT, corrected INTEGER
);
CREATE TABLE indicators (id TEXT PRIMARY KEY, label TEXT, status TEXT, names TEXT);
CREATE TABLE sections (document_id INTEGER, page INTEGER, heading TEXT, text TEXT);
CREATE TABLE page_texts (document_id INTEGER, page INTEGER, text TEXT);
CREATE TABLE diagnoses (document_id INTEGER, text TEXT);
CREATE TABLE medications (document_id INTEGER, text TEXT);
CREATE TABLE unreadable (document_id INTEGER, page INTEGER, what TEXT, why TEXT);
CREATE TABLE findings (document_id INTEGER, code TEXT, count INTEGER);
CREATE VIRTUAL TABLE search USING fts5(title, provider, names, body, tokenize = 'unicode61');
CREATE INDEX observations_document ON observations (document_id);
CREATE INDEX observations_name ON observations (name);
CREATE INDEX observations_indicator ON observations (indicator_id);
CREATE INDEX documents_date ON documents (date);
"""

def index_path(data_dir: Path, source_id: str | None = None) -> Path:
    """Each archive has its own index file, so one owner's question cannot reach another's values.

    Without an id the old single file is named, which is what an instance built before archives
    had owners still holds; `epicrisis index` moves it under the one archive it was built from.
    """
    return data_dir / (f"index-{source_id}.sqlite" if source_id else FILE_NAME)


def index_state(data_dir: Path, output: Path, source_id: str | None = None) -> dict:
    """Whether the index was built after the latest change to this source's data."""
    path = index_path(data_dir, source_id)
    if not path.exists():
        return {"state": "not_started", "label": "", "title": "Index: not built yet"}
    inputs = [output / name for name in (layout.CLASSIFY, layout.CORRECTIONS, layout.DATE_SEARCH, layout.VALIDATION, layout.EXTRACTED)]
    changed = max((item.stat().st_mtime for item in inputs if item.exists()), default=0)
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        documents = connection.execute("SELECT count(*) FROM documents").fetchone()[0]
    finally:
        connection.close()
    if path.stat().st_mtime < changed:
        return {"state": "partial", "label": "Outdated", "title": f"Index: {documents} documents, data changed since"}
    return {"state": "done", "label": str(documents), "title": f"Index: {documents} documents"}


def build_index(data_dir: Path, sources: list[Source]) -> dict:
    """Build the index of one archive. Sources are given as a list for the old single-file build."""
    path = index_path(data_dir, sources[0].id if len(sources) == 1 else None)
    # Two builds of one index race over the same rows and over the file they rename into place.
    with one_at_a_time(path.with_suffix(".lock"), "Building this index"):
        return _build_index(path, data_dir, sources)


def _build_index(path: Path, data_dir: Path, sources: list[Source]) -> dict:
    temporary = temporary_name(path)
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    try:
        connection.executescript(SCHEMA)
        names = indicators.approved_names(data_dir)
        for indicator in indicators.load(data_dir):
            connection.execute(
                "INSERT INTO indicators VALUES (?, ?, ?, ?)",
                (indicator.id, indicator.label, indicator.status, json.dumps(sorted(indicator.names), ensure_ascii=False)),
            )
        totals = {"documents": 0, "transcribed": 0, "observations": 0, "copy_groups": 0}
        for source in sources:
            output = source_output_dir(data_dir, source.id)
            if (output / layout.CLASSIFY).exists():
                _index_source(connection, source, output, totals, names, data_dir)
        built_at = datetime.now(UTC).isoformat(timespec="seconds")
        connection.executemany(
            "INSERT INTO meta VALUES (?, ?)", [("built_at", built_at), ("schema_version", str(SCHEMA_VERSION))]
        )
        connection.commit()
    finally:
        connection.close()
    put_in_place(temporary, path)
    return {**totals, "built_at": built_at}


def _index_source(connection: sqlite3.Connection, source: Source, output: Path, totals: dict,
                  indicator_names: dict[str, str], data_dir: Path) -> None:  # fmt: skip
    connection.execute("INSERT INTO sources VALUES (?, ?)", (source.id, source.name))
    records = {record["sha256"]: record for record in read_records(output / layout.INVENTORY) if "sha256" in record}
    for sha256, record in records.items():
        connection.execute(
            "INSERT OR IGNORE INTO files VALUES (?, ?, ?, ?, ?, ?)",
            (sha256, sha256[:8], source.id, record["path"], record.get("category"), len(page_refs(record))),
        )

    groups = group_documents(latest_pages(output / layout.CLASSIFY))
    corrections = load_corrections(output)
    # The person whose archive this is decides whether a material a model read is used at all.
    read_materials = load_materials(output) if trusts_read_materials(data_dir) else {}
    value_corrections = load_value_corrections(output)
    searches = load_search_results(output)
    day_first_files, day_first_providers = source_day_first(output, groups)
    validation = load_validation(output) or {"documents": []}
    findings = {(item["file_sha256"], tuple(item["pages"])): item for item in validation["documents"]}

    ids: dict[tuple, int] = {}
    quality: dict[int, tuple] = {}
    # The heading of the last document seen in each file, with the page it ended on: what the
    # back of a two-sheet form needs in order to know which form it is the back of.
    before: dict[str, tuple[int, str | None]] = {}
    for group in groups:
        sha256, pages = group[0]["file_sha256"], tuple(page["page"] for page in group)
        if sha256 not in records:
            continue
        extracted = load_extracted(output / layout.EXTRACTED, sha256)
        item = next((doc for doc in (extracted or {"documents": []})["documents"] if tuple(doc["pages"]) == pages), None)
        if not goes_to_extract(group[0]):
            item = None
        date = document_date(
            item,
            group,
            correction=corrections.get((sha256, pages, "document_date")),
            search=searches.get((sha256, pages)),
            day_first=sha256 in day_first_files or provider_key(item, group) in day_first_providers,
        )
        found = findings.get((sha256, pages), {}).get("findings", {})
        provenance = (item or {}).get("provenance", {})
        # Only the page immediately before, and only in the same file: a form's back page is the
        # next sheet of the same form, never a document further off in the folder.
        ended = before.get(sha256)
        carries_on_from = ended[1] if ended and ended[0] == pages[0] - 1 else None
        before[sha256] = (pages[-1], (item or {}).get("title_as_printed"))
        cursor = connection.execute(
            "INSERT INTO documents VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1)",
            (
                source.id, sha256, pages[0], json.dumps(list(pages)), group[0].get("doc_type"),
                (item or {}).get("language") or group[0].get("language"),
                (item or {}).get("title_as_printed"),
                (item or {}).get("provider_as_printed") or next((p.get("provider_on_page") for p in group if p.get("provider_on_page")), None),
                (item or {}).get("department_as_printed"),
                date["value"].isoformat() if date["value"] else None,
                _precision(date), date["printed"], int(date["by_hand"]), json.dumps([flag["code"] for flag in date["flags"]]),
                (item or {}).get("date_of_study_as_printed"), (item or {}).get("date_of_report_as_printed"),
                int(item is not None), provenance.get("model"), provenance.get("prompt_version"), provenance.get("extracted_at"),
                len((item or {}).get("unreadable", [])), sum(found.values()),
            ),
        )  # fmt: skip
        document_id = cursor.lastrowid
        ids[(sha256, pages)] = document_id
        totals["documents"] += 1
        for code, count in found.items():
            connection.execute("INSERT INTO findings VALUES (?, ?, ?)", (document_id, code, count))
        if item is None:
            connection.execute(
                "INSERT INTO search (rowid, title, provider, names, body) VALUES (?, NULL, ?, NULL, NULL)",
                (document_id, fold(group[0].get("provider_on_page"))),
            )
            continue
        totals["transcribed"] += 1
        quality[document_id] = (
            item["doc_type"] == "lab_panel",
            provenance.get("model", "").startswith("claude-opus"),
            -len(item["unreadable"]),
            len(item["observations"]),
        )
        _index_transcription(connection, document_id, item, indicator_names, value_corrections, sha256, pages,
                             carries_on_from=carries_on_from, read_materials=read_materials)  # fmt: skip
        totals["observations"] += len(item["observations"])

    copy_groups = _copy_groups(validation, ids)
    chosen = load_primary_copies(output)
    where = {document_id: key for key, document_id in ids.items()}
    for group_number, members in enumerate(copy_groups, totals["copy_groups"] + 1):
        # The better transcription stands for the group: a lab report before a letter citing it,
        # then Opus, fewer unreadable parts, more values. A person's own choice comes before all
        # of it — they have seen both scans, and the rule has not.
        primary = max(members, key=lambda document_id: (
            where.get(document_id) in chosen, quality.get(document_id, ()), -document_id,
        ))  # fmt: skip
        for document_id in members:
            connection.execute(
                "UPDATE documents SET copy_group = ?, primary_copy = ? WHERE id = ?",
                (group_number, int(document_id == primary), document_id),
            )
    totals["copy_groups"] += len(copy_groups)


def _index_transcription(
    connection: sqlite3.Connection, document_id: int, item: dict, indicator_names: dict[str, str],
    value_corrections: dict, file_sha256: str, pages: tuple[int, ...], carries_on_from: str | None = None,
    read_materials: dict[str, dict] | None = None,
) -> None:  # fmt: skip
    kind = "analyte" if item["doc_type"] == "lab_panel" else "measurement"
    sideways = inverted_tables(item["observations"])
    for observation in item["observations"]:
        correction = value_corrections.get((file_sha256, pages, value_key(observation["provenance"]["page"], observation["name_as_printed"], observation["value_as_printed"])))
        if correction and correction.get("removed"):
            continue  # a person said this line is not a value
        if correction:
            observation = {**observation, **{name: text for name, text in correction["changes"].items() if name in CORRECTABLE}}
            # The number follows the value a person wrote. Without this the table showed 13,5
            # with a "corrected" badge and the chart drew the model's 1,35, and the same stale
            # number answered "outside the printed range" over the network.
            if "value_as_printed" in correction["changes"]:
                observation = {**observation, "value_numeric": number_as_printed(observation)}
        connection.execute(
            "INSERT INTO observations VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                document_id, observation["provenance"]["page"], kind, observation.get("table_as_printed"),
                observation["name_as_printed"], observation["value_as_printed"], observation.get("value_numeric"),
                observation.get("comparator"), observation.get("value_kind"), observation.get("value_role", "result"),
                observation.get("unit_as_printed"), observation.get("reference_as_printed"), observation.get("flag_as_printed"),
                observation.get("method_as_printed"), observation.get("column_as_printed"),
                observation.get("reference_column_as_printed"), observation["provenance"].get("snippet"),
                int(is_derived(observation)),
                _indicator_of(observation, indicator_names, sideways),
                *_material(observation, item, carries_on_from, read_materials, file_sha256, pages,
                           correction, (observation.get("table_as_printed") or "").strip() in sideways),  # fmt: skip
                int(bool(correction)),
            ),
        )  # fmt: skip
    connection.executemany(
        "INSERT INTO sections VALUES (?, ?, ?, ?)",
        [(document_id, section["page"], section.get("heading_as_printed"), section["text"]) for section in item["sections"]],
    )
    connection.executemany(
        "INSERT INTO page_texts VALUES (?, ?, ?)", [(document_id, text["page"], text["text"]) for text in item["page_texts"]]
    )
    connection.executemany("INSERT INTO diagnoses VALUES (?, ?)", [(document_id, text) for text in item["diagnoses_as_printed"]])
    connection.executemany("INSERT INTO medications VALUES (?, ?)", [(document_id, text) for text in item["medications_as_printed"]])
    connection.executemany(
        "INSERT INTO unreadable VALUES (?, ?, ?, ?)",
        [(document_id, part["page"], part.get("what"), part.get("why")) for part in item["unreadable"]],
    )
    names = " ".join(observation["name_as_printed"] for observation in item["observations"])
    body = "\n".join([item.get("full_text") or "", *item["diagnoses_as_printed"], *item["medications_as_printed"]])
    connection.execute(
        "INSERT INTO search (rowid, title, provider, names, body) VALUES (?, ?, ?, ?, ?)",
        (document_id, fold(item.get("title_as_printed")), fold(item.get("provider_as_printed")), fold(names), fold(body)),
    )


# Headings scanned from a form often come out letter-spaced, because the form was typeset that
# way: "U R I N E   A N A L Y S I S", "Γ Ε Ν Ι Κ Η  Ε Ξ Ε Τ Α Σ Η  Ο Υ Ρ Ω Ν". The word is there
# and says what was measured; only the spaces are in the way. So a heading that matches nothing
# as printed is tried once more with the spaces between single letters closed up. Never the
# other way round: what is printed is matched first, and the closed-up form only adds.
LETTER_SPACED = re.compile(r"(?<=\b\w)\s(?=\w\b)")


def unspaced(text: str) -> str:
    previous = ""
    while text != previous:
        previous, text = text, LETTER_SPACED.sub("", text)
    return text


def _says(pattern: re.Pattern, text: str | None) -> bool:
    """Whether a heading says this, as printed, with its spacing closed, or with its accents off.

    A Greek word printed in capitals loses its accents — ΑΙΜΑΤΟΛΟΓΙΚΟΣ is αιματολογικός with
    nothing over the ο — so a pattern written with them matches the one and not the other. The
    folded form has no accents at all, and matching it as well catches both.
    """
    if not text:
        return False
    return bool(pattern.search(text) or pattern.search(unspaced(text))
                or pattern.search(fold(text)) or pattern.search(unspaced(fold(text))))  # fmt: skip


def material_of(observation: dict, document: dict, carries_on_from: str | None = None) -> str | None:
    """Urine, stool and the rest, from the table heading, the value name or the document title.

    carries_on_from is the heading of the document on the page right before this one, in the
    same file. It is read only when this document is headed with a section name and says nothing
    about material itself: the back of a form belongs to its front. See SECTION_HEADING.
    """
    heading = observation.get("table_as_printed")
    for text in (heading, observation.get("name_as_printed"), observation.get("provenance", {}).get("snippet")):
        for material, pattern in MATERIAL_PATTERNS.items():
            if material in FROM_A_HEADING_ONLY and text is not heading:
                continue
            if _says(pattern, text):
                return material
    title = document.get("title_as_printed") or ""
    for material, pattern in MATERIAL_PATTERNS.items():
        if _says(pattern, title):
            return material
    if carries_on_from and _says(SECTION_HEADING, title):
        for material, pattern in MATERIAL_PATTERNS.items():
            if _says(pattern, carries_on_from):
                return material
    return None


def _indicator_of(observation: dict, indicator_names: dict[str, str], sideways: set[str]) -> str | None:
    """Which test a value is of. On a table printed sideways, the heading says it, not the row."""
    heading = (observation.get("table_as_printed") or "").strip()
    if heading in sideways:
        return analyte_of(heading, indicator_names)
    return indicator_names.get(fold(observation["name_as_printed"]))


def _material(observation: dict, document: dict, carries_on_from: str | None,
              read_materials: dict[str, dict] | None, file_sha256: str, pages: tuple[int, ...],
              correction: dict | None = None, sideways: bool = False) -> tuple[str | None, str | None]:  # fmt: skip
    """(what was measured, how that is known). A person first, then the form, then a model.

    A person who has looked at the scan knows what no rule can work out, so their word wins and
    is marked as theirs. Then the form's own word. Where the form printed nothing, a model may
    have read the panel — see material_reading — and the value carries "model" rather than
    "printed", so a page never shows a reading and a printed word as the same kind of fact.
    """
    by_hand = ((correction or {}).get("changes") or {}).get("material")
    if by_hand:
        # "none" is a person saying this was measured on them and not in a sample, which is an
        # answer and not an absence: it is kept as theirs, with no material.
        chosen = by_hand.strip()
        return (None if chosen in ("", "none") else chosen), "person"
    # A table printed sideways names the specimen on the row itself, which is the plainest
    # statement of it there is: the form says "кровь" and means blood.
    if sideways:
        named = SPECIMEN_AS_A_NAME.get(fold(observation.get("name_as_printed") or "").strip())
        if named:
            return named, "printed"
    printed = material_of(observation, document, carries_on_from)
    if printed is not None:
        return printed, "printed"
    key = panel_key(file_sha256, list(pages), observation.get("table_as_printed"))
    read = (read_materials or {}).get(key)
    return (read["material"], "model") if read else (None, None)


def number_as_printed(observation: dict) -> float | None:
    """The number a corrected value now holds, or nothing where the correction is not a number.

    Only one reading counts: the printed text with a decimal comma read as a point. A value a
    person rewrote as words ("not detected") has no number at all, and saying so is the answer.
    """
    printed = (observation.get("value_as_printed") or "").strip()
    tokens = number_tokens(printed)
    if len(tokens) != 1:
        return None
    try:
        return float(tokens[0].replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def is_derived(observation: dict) -> bool:
    """A filtration rate or similar calculation: by its name, its rate unit, or, with no unit, its table."""
    unit = fold(observation.get("unit_as_printed"))
    if DERIVED_NAME.search(fold(observation.get("name_as_printed"))) or RATE_UNIT.match(unit):
        return True
    return not unit.strip() and bool(DERIVED_NAME.search(fold(observation.get("table_as_printed"))))


def _copy_groups(validation: dict, ids: dict[tuple, int]) -> list[set[int]]:
    """Connected documents from the possible copies found by validation."""
    parent: dict[int, int] = {}

    def root(node: int) -> int:
        while parent.setdefault(node, node) != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for item in validation["documents"]:
        one = ids.get((item["file_sha256"], tuple(item["pages"])))
        for copy in item.get("copies", []):
            other = ids.get((copy["file_sha256"], tuple(copy["pages"])))
            if one and other:
                parent[root(one)] = root(other)
    groups: dict[int, set[int]] = {}
    for node in list(parent):
        groups.setdefault(root(node), set()).add(node)
    return sorted((members for members in groups.values() if len(members) > 1), key=min)


def _precision(date: dict) -> str | None:
    if date["value"] is None:
        return None
    label = date["label"] or ""
    return "day" if label.count(".") == 2 else "month" if label.count(".") == 1 else "year"
