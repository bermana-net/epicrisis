"""How the archive behaves when it is much larger than the one it was written for, and when
several people read it at the same time.

The archive these pages were built against holds 439 documents. The index here holds twenty
times that, with ten values on every document, because a page that is quick on four hundred
rows can still be unusable on nine thousand: a query without an index, a view built per request,
a template that loops over everything. Nothing here calls a model; the index is written
directly, from the same schema the real build writes.
"""

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from epicrisis import query
from epicrisis.index.build import SCHEMA, SCHEMA_VERSION, index_path
from epicrisis.printed_values import fold
from epicrisis.sources import SourceRegistry, source_output_dir
from epicrisis.web.app import create_app

DOCUMENTS = 9_000
VALUES_EACH = 10
FILES = 900
YEARS = range(1996, 2027)
# Names a laboratory prints, in the languages this archive holds, so search and folding have
# something real to do rather than one word repeated nine thousand times.
NAMES = [
    ("creatinine", "Креатинін", "мкмоль/л", "53-115"),
    ("hemoglobin", "Гемоглобін", "г/л", "130-160"),
    ("glucose", "Глюкоза", "ммоль/л", "3,9-5,8"),
    ("leukocyte", "Лейкоцити", "10⁹/л", "4,0-9,0"),
    ("cholesterol", "Colesterol total", "mg/dL", "0-200"),
    ("urea", "Ουρία", "mg/dL", "10-50"),
]
TYPES = ("lab_panel", "imaging_report", "discharge", "consultation", "insurance")
# Generous: these are upper bounds that catch a page that became unusable, not benchmarks.
SLOW = 8.0


def build_big_index(tmp_path: Path):
    """An index of DOCUMENTS documents, written straight from the schema the real build uses."""
    data_dir = (tmp_path / "data").resolve()
    archive = tmp_path / "archive"
    archive.mkdir(parents=True)
    source = SourceRegistry(data_dir).add(str(archive), owner="A Person")
    source_output_dir(data_dir, source.id).mkdir(parents=True, exist_ok=True)

    path = index_path(data_dir, source.id)
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    with connection:
        connection.execute("INSERT INTO sources VALUES (?, ?)", (source.id, source.name))
        connection.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [("built_at", "2026-09-21T00:00:00+00:00"), ("schema_version", str(SCHEMA_VERSION))],
        )
        connection.executemany(
            "INSERT INTO indicators VALUES (?, ?, ?, ?)",
            [(key, key.title(), "approved", json.dumps([name])) for key, name, _unit, _ref in NAMES],
        )
        files = [(f"{index:064x}", f"{index:08x}") for index in range(FILES)]
        connection.executemany(
            "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?)",
            [(sha, file_id, source.id, f"{1996 + index % 30}/scan {index}.pdf", "pdf", 4)
             for index, (sha, file_id) in enumerate(files)],  # fmt: skip
        )
        for number in range(DOCUMENTS):
            sha, _file_id = files[number % FILES]
            year = 1996 + number % len(YEARS)
            date = f"{year}-{1 + number % 12:02d}-{1 + number % 28:02d}"
            doc_type = TYPES[number % len(TYPES)]
            connection.execute(
                """INSERT INTO documents VALUES (NULL, ?, ?, ?, ?, ?, 'uk', ?, ?, NULL, ?, 'day', ?, 0, '[]',
                                                 NULL, NULL, 1, 'claude-opus-5', '4', '2026-01-01T00:00:00+00:00',
                                                 0, 0, NULL, 1)""",
                (source.id, sha, 1 + number % 4, json.dumps([1 + number % 4]), doc_type,
                 f"Analysis number {number}", f"Laboratory {number % 40}", date, date),  # fmt: skip
            )
            document_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            names = []
            for position in range(VALUES_EACH):
                key, name, unit, reference = NAMES[(number + position) % len(NAMES)]
                names.append(name)
                connection.execute(
                    """INSERT INTO observations VALUES (NULL, ?, 1, 'analyte', 'Biochemistry', ?, ?, ?, NULL,
                                                        'quantitative', 'result', ?, ?, NULL, NULL, NULL, NULL,
                                                        ?, 0, ?, 'blood', 'printed', 0)""",
                    (document_id, name, f"{70 + position}", float(70 + position), unit, reference,
                     f"{name} {70 + position} {unit}", key),  # fmt: skip
                )
            connection.execute(
                "INSERT INTO search (rowid, title, provider, names, body) VALUES (?, ?, ?, ?, ?)",
                (document_id, fold(f"Analysis number {number}"), fold(f"Laboratory {number % 40}"),
                 fold(" ".join(names)), fold(f"Report of {date} with values printed on it")),  # fmt: skip
            )
    connection.close()
    return data_dir, source


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    return build_big_index(tmp_path_factory.mktemp("scale"))


def test_an_index_twenty_times_the_size_answers_every_question(big):
    data_dir, source = big
    connection = query.open_index(data_dir, source.id)
    with connection:
        overview = query.overview(connection)
        assert overview["documents"] == DOCUMENTS
        assert overview["values"] == DOCUMENTS * VALUES_EACH

        started = time.monotonic()
        found = query.search(connection, "Креатинін", limit=40)
        assert 0 < len(found) <= 40  # a page of results, not nine thousand
        assert time.monotonic() - started < SLOW

        # Asking for more than the ceiling gives the ceiling: no caller can pull fifteen
        # thousand values into one answer by asking nicely.
        started = time.monotonic()
        history = query.values(connection, indicator="creatinine", limit=500)
        assert len(history) == query.MAX_LIMIT and all(item["date"] for item in history)
        assert time.monotonic() - started < SLOW

        assert len(query.timeline(connection, limit=120)) == 120
        assert len(query.value_names(connection, "креат")) >= 1
        assert len(query.years(connection)) == len(YEARS)
    connection.close()


PAGES = ("/status", "/", "/?view=indicators", "/?view=lanes", "/documents", "/indicators",
         "/review", "/search?q=Креатинін", "/tests/creatinine")  # fmt: skip


@pytest.mark.parametrize("page", PAGES)
def test_every_page_still_opens_on_a_large_archive(big, page):
    data_dir, _source = big
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    started = time.monotonic()
    answer = client.get(page)
    spent = time.monotonic() - started

    assert answer.status_code == 200, page
    assert spent < SLOW, f"{page} took {spent:.1f}s on {DOCUMENTS} documents"


def test_a_page_of_a_long_list_is_a_page_and_not_the_whole_list(big):
    """The guard that matters at this size: a list page must not put every row in the answer."""
    data_dir, _source = big
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    feed = client.get("/").text
    assert feed.count('class="doc-link"') < DOCUMENTS / 10
    assert "Analysis number 0" in feed or "Analysis number" in feed


def test_many_readers_at_once_all_get_their_answer(big):
    """Several people, or one person and an assistant, reading the same archive at the same time.

    Each request opens its own connection to the index; SQLite objects cannot be shared between
    threads, and a connection kept on the application would fail here rather than in a test.
    """
    data_dir, _source = big
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    wanted = ["/status", "/", "/documents", "/search?q=Глюкоза", "/tests/creatinine", "/indicators"] * 5

    def fetch(page: str) -> tuple[str, int]:
        return page, client.get(page).status_code

    with ThreadPoolExecutor(max_workers=12) as pool:
        answers = list(pool.map(fetch, wanted))

    assert len(answers) == len(wanted)
    assert all(code == 200 for _page, code in answers), [item for item in answers if item[1] != 200]


def test_reading_and_writing_at_the_same_time_loses_nothing(big):
    """Corrections written from several threads while the pages are being read.

    Corrections go to a file, one record per line, under one lock. A line lost or half-written
    here would be a person's own words disappearing, which is the worst failure this project has.
    """
    from epicrisis.corrections import load_value_corrections, set_value

    data_dir, source = big
    output = source_output_dir(data_dir, source.id)
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    sha = f"{0:064x}"

    def write(number: int) -> None:
        set_value(output, sha, [1], f"1|name{number}|70", {"value_as_printed": str(number)})

    def read(_number: int) -> int:
        return client.get("/documents").status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        writing = [pool.submit(write, number) for number in range(120)]
        reading = [pool.submit(read, number) for number in range(12)]
        for task in writing:
            task.result()
        assert all(task.result() == 200 for task in reading)

    lines = (output / "corrections.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 120
    assert all(json.loads(line)["field"] == "value" for line in lines)  # none half-written
    assert len(load_value_corrections(output)) == 120


def test_the_view_by_test_grows_with_the_number_of_measurements(big):
    """A known limit, written down rather than discovered by a person one day.

    The by-test view draws a mark for every day a test was measured, and does not thin them.
    Nine thousand documents of six tests mean fifteen hundred marks per row, and the page it
    sends grows with them. The archive this was built for has 145 measurements of its busiest
    test, which is a hundredth of that, so the view is left as it is and the size recorded here.
    Should a real archive approach it, the row wants thinning, not a larger page.
    """
    data_dir, _source = big
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    by_test = client.get("/?view=indicators")
    feed = client.get("/")

    assert by_test.status_code == 200 and feed.status_code == 200
    assert len(feed.text) < 1_000_000  # the ordinary views stay small whatever the archive holds
    assert len(by_test.text) > len(feed.text)  # this one does not, and that is the limit
