"""Charts: geometry from printed numbers, and the page that draws them."""

from fastapi.testclient import TestClient

from epicrisis import rules
from epicrisis.index.build import index_path
import pytest

from epicrisis.series import _band_of, _the_pairs_in_time_agree, charts, printed_range
from epicrisis.units import ends_agree, numbers_fit_the_range, unit_key
from epicrisis.web.app import create_app
from test_ask import archive_index  # noqa: F401
from test_extract import FakeExtractBackend, setup  # noqa: F401


def test_a_printed_range_is_read_only_when_it_is_one():
    assert printed_range("4,0-9,0") == (4.0, 9.0)
    assert printed_range("0.5 – 1.0") == (0.5, 1.0)
    assert printed_range("< 5") == (None, 5.0) and printed_range("до 5") == (None, 5.0)
    assert printed_range("> 60") == (60.0, None)
    assert printed_range("9,0 - 4,0") is None  # printed the wrong way round: not a band
    assert printed_range("negative") is None and printed_range(None) is None


def test_one_unit_written_three_ways_is_one_chart_and_another_unit_is_another():
    assert unit_key("мкМоль/л") == unit_key("umol/L") == unit_key("мкмоль/л")
    assert unit_key("mg/dL") != unit_key("мкмоль/л")

    values = [
        {"date": "2011-07-09", "value_numeric": 71, "value": "71", "unit": "мкмоль/л", "reference": "62-106"},
        {"date": "2021-03-02", "value_numeric": 78, "value": "78", "unit": "мкМоль/л", "reference": "62-106"},
        {"date": "2024-04-11", "value_numeric": 80, "value": "80", "unit": "umol/L", "reference": "59-104"},
        {"date": "2023-01-05", "value_numeric": 0.9, "value": "0,9", "unit": "mg/dL", "reference": "0,7-1,2"},
        {"date": "2022-02-02", "value_numeric": None, "value": "Absent", "unit": "", "reference": None},
    ]
    drawn = charts(values)
    first = drawn[0]
    assert first["unit"] == "мкмоль/л" and len(first["points"]) == 3
    assert first["spellings"] == ["мкмоль/л", "мкМоль/л", "umol/L"]
    assert [point["x"] for point in first["points"]] == sorted(point["x"] for point in first["points"])
    # The band is the range printed on each form, held until another form prints a different
    # one: three stretches side by side, the last one higher because its range is 53-115 rather
    # than 53-97, and every one of them drawn inside the plot.
    bands = first["bands"]
    assert len(bands) == 3
    assert [round(band["x"]) for band in bands] == sorted(round(band["x"]) for band in bands)
    # The first two forms print one range and the third another, so the band steps where the
    # laboratory changed it and nowhere else.
    assert bands[0]["y"] == bands[1]["y"] and bands[2]["y"] != bands[1]["y"]
    assert all(band["height"] > 0 and band["width"] > 0 for band in bands)
    assert any(chart["unit"] == "mg/dL" for chart in drawn)
    assert any(chart["as_printed"] and chart["as_printed"][0]["value"] == "Absent" for chart in drawn)
    assert sum(len(chart["rows"]) for chart in drawn) == len(values)  # nothing falls out of the listing


def test_a_single_value_draws_no_line_but_is_still_listed():
    drawn = charts([{"date": "2020-01-01", "value_numeric": 5, "value": "5", "unit": "g/L", "reference": None}])
    assert drawn[0]["points"] == [] and drawn[0]["count"] == 1 and len(drawn[0]["rows"]) == 1


def test_the_page_draws_a_point_for_every_value_and_never_reads_them(archive_index):  # noqa: F811
    from epicrisis import indicators
    from epicrisis.index.build import build_index

    data_dir, source, labs = archive_index
    # A chart follows an indicator, so the printed name needs one before anything can be drawn.
    indicators.upsert(data_dir, None, "Cystatin C", ["Цистатин С"], status="approved")
    build_index(data_dir, [source])
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    by_test = client.get("/?view=indicators").text
    assert "/tests/" in by_test

    indicator_id = by_test.split('href="/tests/')[1].split('"')[0].split("?")[0]
    page = client.get(f"/tests/{indicator_id}")
    assert page.status_code == 200
    # One value in this archive: no line is drawn, and the value is still listed as printed. This
    # is the one cause of an empty chart where a further measurement really would draw the line,
    # and it is the only one the page may say so about.
    assert "a line needs 2 points to run between" in page.text
    assert "0,85" in page.text and "0,5-1,0" in page.text
    # The footer says what is drawn and what is not. The line between the points is drawn, so it
    # is named rather than denied: saying "no trend is drawn" under a picture with a line in it
    # teaches a person that the line they can see is not there.
    assert "nothing is fitted, smoothed or averaged" in page.text and "high or low" in page.text
    assert "joined in date order" in page.text
    assert client.get("/tests/no-such-test").status_code == 404

    # From a value on the card straight to that test's history.
    card = client.get(f"/documents/{source.id}/{labs}/1").text
    assert f'href="/tests/{indicator_id}"' in card


def test_a_list_of_records_holds_records_only(archive_index):  # noqa: F811
    """Paperwork and blank pages are kept, but a list of records is not where they belong."""
    import sqlite3

    from epicrisis import query

    data_dir, source, _ = archive_index
    writable = sqlite3.connect(index_path(data_dir, source.id))
    with writable:
        total = writable.execute("SELECT count(*) FROM documents").fetchone()[0]
        # By type, not by id: the synthetic scans hash differently on every run, so ids move.
        writable.execute("UPDATE documents SET doc_type = 'admin' WHERE doc_type = 'discharge'")
        writable.execute("UPDATE documents SET doc_type = 'blank' WHERE doc_type = 'insurance'")
    writable.close()

    connection = query.open_index(data_dir, None)
    records = query.count_documents(connection, with_paperwork=False)
    assert records == total - 2  # the paperwork and the blank page are both out
    assert query.count_documents(connection, with_paperwork=True) == total - 1  # the blank page stays out
    assert query.count_documents(connection, doc_type="blank") == 1  # still reachable by type
    assert all(item["doc_type"] not in ("admin", "blank") for item in query.timeline(connection, limit=50, with_paperwork=False))
    connection.close()


def test_one_measure_written_many_ways_gets_one_chart():
    """Spellings are joined where the writing itself is certain, and not otherwise."""
    from epicrisis.units import unit_key

    one_measure = ["10¹²/л", "10¹²/l", "10*12/л", "х10¹²/л", "10^12 клітин/л", "10E12/L", "*10^12/л",
                   "1012/L", "10¹²/Л", "x10 12 клітин/л", "Т/л", "* 10¹²/л"]  # fmt: skip
    assert len({unit_key(spelling) for spelling in one_measure}) == 1

    # Under the microscope, four languages for one thing.
    assert {unit_key(item) for item in ("в п/з", "в п/зр.", "п/з", "/hpf", "в полі зору", "κ.ο.π - hpf")} == {"hpf"}
    # Capitals carry the prefix: "Г/л" is giga per litre, "г/л" is grams. Folding them together would be wrong.
    assert unit_key("Г/л") != unit_key("г/л")
    # Different sizes stay apart: joining them would mean converting, and nothing here converts.
    assert len({unit_key(item) for item in ("ммоль/л", "мг/дл", "мкмоль/л")}) == 3
    # A lone 1 where the letter for litre belongs is read as that letter. This reverses an earlier
    # decision — "a spelling that looks like a misreading is left alone rather than guessed at" —
    # and the archives are why: five values carry "10⁹/1" against a hundred and seventy-six carrying
    # "10⁹/л", and the five were drawn as a chart of their own, a second history of one test. There
    # is no unit "per one": the digit stands alone beside the slash only where a letter was read as
    # a digit, which is the same misreading the readers of values have always undone.
    assert unit_key("10¹²/1") == unit_key("10¹²/л")
    assert unit_key("g/1") == unit_key("g/l") and unit_key("1/1") == unit_key("l/l")
    # And only where it stands alone: a number keeps its digits.
    assert unit_key("mg/24 h") != unit_key("mg/l") and unit_key("10⁹/л") != unit_key("10¹²/л")


def test_a_litre_and_a_microlitre_are_joined_only_when_the_numbers_agree():
    """10⁶/µL and 10¹²/L are one measure by definition — but only where the archive's numbers say so."""
    from epicrisis.series import charts

    def value(unit, number, day):
        return {"date": f"2020-01-{day:02d}", "unit": unit, "value_numeric": number, "value": str(number),
                "name": "Erythrocytes", "reference": None}  # fmt: skip

    blood = [value("10¹²/л", 5.0, 1), value("10¹²/л", 4.9, 2), value("x10^6/µL", 5.1, 3), value("x10^6/µL", 4.8, 4)]
    assert len(charts(blood)) == 1

    # The same pair of spellings, but one side counts from zero: these are not the same measure.
    urine = [value("10¹²/л", 5.0, 1), value("10¹²/л", 4.9, 2), value("/µL", 0.0, 3), value("/µL", 2.0, 4)]
    assert len(charts(urine)) == 2


def test_the_line_runs_through_the_years_in_order():
    """Joining two spellings must not let the line double back: points are drawn by date."""
    from epicrisis.series import charts

    def value(unit, number, year):
        return {"date": f"{year}-05-01", "unit": unit, "value_numeric": number, "value": str(number),
                "name": "Erythrocytes", "reference": None}  # fmt: skip

    # Two spellings of one measure, each sorted on its own but interleaved in time.
    mixed = [value("10¹²/л", 5.0, y) for y in (2002, 2008, 2020)] + [value("x10^6/µL", 4.9, y) for y in (2005, 2012)]
    chart = charts(mixed)[0]

    assert [row["date"][:4] for row in chart["rows"]] == ["2002", "2005", "2008", "2012", "2020"]
    assert [point["x"] for point in chart["points"]] == sorted(point["x"] for point in chart["points"])


def test_every_year_on_the_strip_keeps_its_label(archive_index):  # noqa: F811
    """2020 lost its label once: "2020" with both pairs of digits replaced comes out empty."""
    from fastapi.testclient import TestClient

    from epicrisis.web.app import create_app

    data_dir, _, _ = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = client.get("/").text

    assert '<span class="label caps"></span>' not in page


def test_urine_never_joins_the_blood_line_even_in_the_same_unit():
    """The case the archive showed: creatinine 44,1 mg/dL of urine beside 0,46 mg/dL of blood.

    The names match, the units match, and the numbers differ by a hundred. Joined, the urine
    value stands as a spike on the blood line; kept apart, each is what its form measured.
    """
    values = [
        {"date": "2022-09-22", "value_numeric": 0.64, "value": "0,64", "unit": "mg/dL", "reference": "0,67 - 1,17",
         "name": "Creatinina", "material": None},
        {"date": "2024-06-17", "value_numeric": 0.50, "value": "0,50", "unit": "mg/dL", "reference": "0,67 - 1,17",
         "name": "Creatinina", "material": None},
        {"date": "2024-07-15", "value_numeric": 0.46, "value": "0,46", "unit": "mg/dL", "reference": "0,67 - 1,17",
         "name": "Creatinina", "material": None},
        {"date": "2024-07-15", "value_numeric": 44.1, "value": "44,1", "unit": "mg/dL", "reference": None,
         "name": "Creatinina", "material": "urine"},
    ]
    for to_scale in ((), TO_SCALE):
        drawn = charts(values, indicator="creatinine", placing=[*FROM_RANGE, *to_scale])
        blood = [chart for chart in drawn if chart["material"] == ""]
        urine = [chart for chart in drawn if chart["material"] == "urine"]
        assert len(blood) == 1 and len(urine) == 1
        assert blood[0]["count"] == 3 and urine[0]["count"] == 1
        assert all(float(row["value_numeric"]) < 100 for row in blood[0]["rows"])
        assert drawn[0]["material"] == ""  # blood and the unmarked lead


def test_a_material_of_its_own_gets_its_own_chart_on_the_page(archive_index):  # noqa: F811
    """A urine value of the same test, in the same unit, is drawn apart and says so."""
    import sqlite3

    from epicrisis import indicators
    from epicrisis.index.build import build_index

    data_dir, source, _labs = archive_index
    indicators.upsert(data_dir, None, "Cystatin C", ["Цистатин С"], status="approved")
    build_index(data_dir, [source])

    writable = sqlite3.connect(index_path(data_dir, source.id))
    writable.row_factory = sqlite3.Row
    with writable:
        row = dict(writable.execute("SELECT * FROM observations WHERE indicator_id IS NOT NULL LIMIT 1").fetchone())
        indicator_id = row["indicator_id"]
        row.pop("id", None)
        row.update(value="85,0", value_numeric=85.0, material="urine")
        writable.execute(
            f"INSERT INTO observations ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values())
        )
    writable.close()

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = client.get(f"/tests/{indicator_id}").text
    assert "One material at a time" in page
    # A tab per material, and no tab that puts them together. What the form did not say is its
    # own answer, and the page opens on it here because this archive has no blood values.
    assert 'material=urine"' in page and 'material=unknown"' in page
    assert "Every material" not in page and "blood and unmarked" not in page

    urine = client.get(f"/tests/{indicator_id}?material=urine").text
    assert "85,0" in urine  # the value this test put in urine, and only it
    # Every chart names its test and its material under the drawing, so it reads on its own.
    assert 'class="chart-what"' in urine and ">urine<" in urine
    assert client.get(f"/tests/{indicator_id}?material=stool").status_code == 200  # falls back to a real tab


def test_a_person_chooses_which_copy_answers_and_the_choice_is_kept(archive_index):  # noqa: F811
    """The rule picks one of a group; a person who has seen both scans can move the choice."""
    import json
    import sqlite3

    from epicrisis.corrections import load_primary_copies
    from epicrisis.index.build import build_index
    from epicrisis.query import copy_groups, open_index

    data_dir, source, _labs = archive_index
    output = data_dir / "sources" / source.id
    writable = sqlite3.connect(index_path(data_dir, source.id))
    writable.row_factory = sqlite3.Row
    with writable:
        two = writable.execute("SELECT id FROM documents ORDER BY id LIMIT 2").fetchall()
        writable.execute("UPDATE documents SET copy_group = 1, primary_copy = (id = ?) WHERE id IN (?, ?)",
                         (two[0]["id"], two[0]["id"], two[1]["id"]))  # fmt: skip
        other = dict(writable.execute("SELECT file_sha256, first_page, pages FROM documents WHERE id = ?",
                                      (two[1]["id"],)).fetchone())  # fmt: skip
    writable.close()

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = client.get("/review").text
    assert "The same document in more than one file" in page and "Use this one" in page

    done = client.post(f"/review/{source.id}/{other['file_sha256']}/{other['first_page']}/copy",
                       follow_redirects=False)  # fmt: skip
    assert done.status_code == 303

    connection = open_index(data_dir, source.id)
    chosen = [item for group in copy_groups(connection) for item in group["members"] if item["chosen"]]
    connection.close()
    assert len(chosen) == 1 and chosen[0]["file_sha256"] == other["file_sha256"]

    pages = json.loads(other["pages"]) if other["pages"] else [other["first_page"]]
    assert (other["file_sha256"], tuple(pages)) in load_primary_copies(output)

    # Indexing again reads the choice back as a correction. This archive's group was made by
    # hand and the checks do not find it again, so what is asserted here is that a stored choice
    # is read without trouble and never promotes a document out of its group.
    build_index(data_dir, [source])
    connection = open_index(data_dir, source.id)
    still = [item for group in copy_groups(connection) for item in group["members"] if item["chosen"]]
    connection.close()
    assert not still or still[0]["file_sha256"] == other["file_sha256"]


def test_a_value_with_no_settled_date_is_listed_rather_than_dropped():
    """The heading counted it and the page showed it nowhere, which is the worst of both."""
    from epicrisis.series import charts, date_label

    values = [
        {"date": "2019-03-04", "date_precision": "day", "value": "71", "value_numeric": 71.0, "unit": "мкмоль/л", "material": "blood"},
        {"date": "2020-05-01", "date_precision": "month", "value": "74", "value_numeric": 74.0, "unit": "мкмоль/л", "material": "blood"},
        {"date": "2021-06-07", "date_precision": "day", "value": "69", "value_numeric": 69.0, "unit": "мкмоль/л", "material": "blood"},
        {"date": None, "value": "67", "value_numeric": 67.0, "unit": "мкмоль/л", "material": "blood"},
    ]  # fmt: skip

    drawn = charts(values)

    assert len(drawn) == 1
    assert drawn[0]["count"] == 4 and drawn[0]["undated"] == 4 - 3
    assert len(drawn[0]["points"]) == 3  # nowhere to draw the fourth: it has no date
    assert [row["value"] for row in drawn[0]["rows"]] == ["71", "74", "69", "67"]
    assert drawn[0]["rows"][-1]["date_label"] is None

    # A date known only to the month is shown as the month, not as the first day of it.
    assert [row["date_label"] for row in drawn[0]["rows"][:3]] == ["2019-03-04", "2020.05", "2021-06-07"]
    assert date_label({"date": "2016-01-01", "date_precision": "year"}) == "2016"


def test_a_number_stored_as_text_does_not_take_the_page_down():
    """sqlite keeps what it is given; a reading that wrote "4,2" made the page a 500."""
    from epicrisis.series import charts

    values = [
        {"date": "2019-03-04", "value": "4,2", "value_numeric": "4,2", "unit": "ммоль/л", "material": "blood"},
        {"date": "2020-03-04", "value": "4,4", "value_numeric": 4.4, "unit": "ммоль/л", "material": "blood"},
        {"date": "2021-03-04", "value": "4,6", "value_numeric": 4.6, "unit": "ммоль/л", "material": "blood"},
    ]  # fmt: skip

    drawn = charts(values)

    assert len(drawn) == 1 and len(drawn[0]["points"]) == 3
    assert [point["value"] for point in drawn[0]["points"]] == ["4,2", "4,4", "4,6"]


def test_a_value_that_is_not_a_finite_number_is_not_drawn():
    """One NaN drew an SVG of "nan,nan" points beside a table that was perfectly correct."""
    from epicrisis.series import charts

    values = [
        {"date": "2020-01-01", "value": "130", "value_numeric": float("nan"), "unit": "г/л", "material": "blood"},
        {"date": "2021-01-01", "value": "130", "value_numeric": 130.0, "unit": "г/л", "material": "blood"},
        {"date": "2022-01-01", "value": "128", "value_numeric": 128.0, "unit": "г/л", "material": "blood"},
        {"date": "2023-01-01", "value": "131", "value_numeric": 131.0, "unit": "г/л", "material": "blood"},
    ]  # fmt: skip

    drawn = charts(values)[0]

    assert len(drawn["points"]) == 3  # the value is still listed, it is only not a point
    assert len(drawn["rows"]) == 4
    assert all("nan" not in str(point["x"]) + str(point["y"]) for point in drawn["points"])
    assert "nan" not in drawn["line"].casefold()


def test_a_written_out_power_of_ten_is_the_same_measure_however_few_values_carry_it():
    """"x10³/mm³" and "10⁹/L" are one count written two ways: a litre holds a million cubic
    millimetres. A lone value in the first spelling used to draw a chart of its own beside years
    of the second, and nothing on the page said the two belonged together."""
    values = [
        {"value_numeric": "2.1", "unit": "10^9/L", "material": "blood", "date": "2026-05-29"},
        {"value_numeric": "2.4", "unit": "10^9/L", "material": "blood", "date": "2026-06-03"},
        {"value_numeric": "1.9", "unit": "x10³/mm³", "material": "blood", "date": "2025-08-11"},
    ]
    drawn = charts(values)
    assert len(drawn) == 1 and len(drawn[0]["points"]) == 3

    # A spelling that writes no power keeps the old caution: one value cannot join on its own.
    bare = [
        {"value_numeric": "5.2", "unit": "/l", "material": "blood", "date": "2026-05-29"},
        {"value_numeric": "4.8", "unit": "/l", "material": "blood", "date": "2026-06-03"},
        {"value_numeric": "6.0", "unit": "/ul", "material": "blood", "date": "2025-08-11"},
    ]
    assert len(charts(bare)) == 2


def test_a_value_printed_beside_the_result_is_listed_and_not_drawn():
    """A "previous value" column belongs to an earlier day, and the unit stands once for the row.

    Drawn as a point it landed on the date of the form that quoted it — a date that laboratory
    never gave it — and, having no unit of its own, it fell into a chart headed "no unit printed"
    that mixed per-cents with counts per litre.
    """
    row = {"document_id": 7, "name": "Linfocitos", "page": 1, "material": "blood"}
    values = [
        {**row, "value_numeric": "2.4", "unit": "10^9/L", "value_role": "result", "date": "2026-06-03"},
        {**row, "value_numeric": "2.1", "unit": None, "value_role": "other", "date": "2026-06-03",
         "column_heading": "Valor anterior"},
        {**row, "value_numeric": "2.2", "unit": "10^9/L", "value_role": "result", "date": "2026-05-29"},
    ]
    drawn = charts(values)
    assert len(drawn) == 1  # no chart of its own for the column with no unit printed
    chart = drawn[0]
    assert chart["unit"] == "10^9/L" and chart["count"] == 3
    assert len(chart["points"]) == 2 and chart["beside_the_result"] == 1
    listed = [item for item in chart["rows"] if item.get("column_heading") == "Valor anterior"]
    assert listed and listed[0]["unit_from_the_row"] is True


def test_values_with_no_unit_anywhere_are_placed_by_their_numbers_only_when_asked():
    """The one reading taken from numbers rather than from a page, and only where one scale fits."""
    blood = {"material": "blood"}
    values = [
        {**blood, "value_numeric": "32.8", "unit": "%", "date": "2009-05-19"},
        {**blood, "value_numeric": "29.0", "unit": "%", "date": "2010-08-05"},
        {**blood, "value_numeric": "1.9", "unit": "10^9/L", "date": "2009-05-19"},
        {**blood, "value_numeric": "2.1", "unit": "10^9/L", "date": "2010-08-05"},
        {**blood, "value_numeric": "30.0", "unit": None, "date": "2013-12-16"},
    ]
    as_printed = charts(values)
    assert sorted(chart["unit"] for chart in as_printed) == ["", "%", "10^9/L"]

    joined = charts(values, placing=[*FROM_RANGE, *BY_NUMBERS])
    assert sorted(chart["unit"] for chart in joined) == ["%", "10^9/L"]
    per_cent = next(chart for chart in joined if chart["unit"] == "%")
    assert per_cent["count"] == 3 and per_cent["by_numbers"] == 1
    assert [item.get("unit_by_numbers") for item in per_cent["rows"]].count(True) == 1

    # Two scales the numbers could belong to: the numbers do not say, so nothing is moved.
    unclear = [*values[:2], {**blood, "value_numeric": "31.0", "unit": "mg/dl", "date": "2011-01-01"},
               {**blood, "value_numeric": "33.0", "unit": "mg/dl", "date": "2012-01-01"},
               {**blood, "value_numeric": "30.0", "unit": None, "date": "2013-12-16"}]  # fmt: skip
    assert "" in {chart["unit"] for chart in charts(unclear, placing=[*FROM_RANGE, *BY_NUMBERS])}


# The five tests this rule was measured against, written as shapes and not as anybody's results:
# the values whose forms printed no unit, the range those same forms printed beside them, the
# scale this test is also drawn at in a unit of its own, and whether the two are really one
# scale. Three of the five are two scales mixed together and must be refused; two are one history
# printed two ways and must be joined. No single reading gets all five, which is why there are
# two of them.
FIVE_SHAPES = [
    # A creatinine whose unit-less values are milligrammes per decilitre and micromoles per litre
    # in one column. Their spread overlaps the named scale and their middle sits inside it, so
    # both of those readings joined two different measurements into one line.
    ("creatinine, two scales in one column", [0.6, 1.1, 58.2], None, "мкмоль/л", [34.0, 71.0, 88.6], False),
    ("urea", [6.9, 13.2, 22.4], None, "ммоль/л", [2.4, 5.1, 7.8], False),
    ("uric acid", [5.8, 44.0, 301.0], None, "мкмоль/л", [194.0, 318.0, 486.0], False),
    # One scale. The years that printed no unit were the years of the illness and the ones that
    # printed a unit were mostly ordinary, so the middle of each group lands a factor of four from
    # the other and comparing middles left these values on a chart headed "no unit printed" beside
    # the chart they belong on. The ends say it plainly: 2.5 against 4.0 and 36 against 33.
    ("sedimentation rate, one scale", [4.0, 9.0, 14.0, 21.0, 33.0], None, "мм/год", [2.5, 3.0, 36.0], True),
    # One scale, joined by the range the page printed. The ends of the two spreads refuse it: the
    # unit-less values are a whole history and the named ones are two readings out of the middle
    # of it, so the low ends are a factor of nearly seven apart and say nothing about the scale.
    ("prostate antigen, a printed range", [0.31, 2.44, 6.82], "до 4", "нг/мл", [2.08, 4.61], True),
]


def _two_scales(bare: list[float], printed: str | None, unit: str, named: list[float]) -> list[dict]:
    """One test drawn twice: values whose form printed no unit, and values that printed one."""
    rows = [{"material": "blood", "date": f"20{10 + year}-04-18", "value": str(value),
             "value_numeric": value, "unit": None, "reference": printed}
            for year, value in enumerate(bare)]  # fmt: skip
    return rows + [{"material": "blood", "date": f"20{20 + year}-04-18", "value": str(value),
                    "value_numeric": value, "unit": unit, "reference": None}
                   for year, value in enumerate(named)]  # fmt: skip


@pytest.mark.parametrize("name,bare,printed,unit,named,joins", FIVE_SHAPES, ids=[row[0] for row in FIVE_SHAPES])
def test_values_with_no_unit_join_a_scale_the_page_or_both_ends_agree_with(name, bare, printed, unit, named, joins):
    """All five of the tests this was measured on, and the rule has to be right about every one."""
    drawn = charts(_two_scales(bare, printed, unit, named), placing=[*FROM_RANGE, *BY_NUMBERS])
    units_drawn = sorted(chart["unit"] for chart in drawn)
    if joins:
        assert units_drawn == [unit]
        joined = drawn[0]
        assert joined["by_numbers"] == len(bare) and joined["count"] == len(bare) + len(named)
        assert [item.get("unit_by_numbers") for item in joined["rows"]].count(True) == len(bare)
    else:
        assert units_drawn == sorted(["", unit])
        assert sum(chart["by_numbers"] for chart in drawn) == 0


def test_the_printed_range_decides_before_the_numbers_and_the_numbers_would_have_said_otherwise():
    """Why the two readings are in this order, on the one test where they disagree.

    The prostate antigen: the forms with no unit print "up to 4", and that is the page saying
    which scale these numbers are on. The ends of the two spreads say the opposite, because the
    unit-less values run from 0.21 across fifteen years and the named ones are two readings from
    the middle of that history.
    """
    _, bare, printed, unit, named, _ = FIVE_SHAPES[-1]
    spread, theirs = (min(bare), max(bare)), (min(named), max(named))
    assert ends_agree(spread, theirs, 2.0) is False
    assert numbers_fit_the_range(printed_range(printed), named, 2.0) is True

    # With no range printed beside them, the same numbers have nothing but their ends to go on,
    # and they stay where they are rather than guess.
    nothing_printed = charts(_two_scales(bare, None, unit, named), placing=[*FROM_RANGE, *BY_NUMBERS])
    assert "" in {chart["unit"] for chart in nothing_printed}


def test_a_range_printed_beside_somebody_elses_row_does_not_silence_the_numbers():
    """Silence beside these values is not the page speaking about them.

    Written the other way round first: a range printed anywhere on the test meant the page had
    spoken and the numbers were not asked. Measured on three archives, that cost sixty-seven
    values their scale to gain four. The case that showed it: a haemoglobin of 14.8 printed with
    neither unit nor range, beside three readings of 15.5 in grams per decilitre that did print
    one, stopped being drawn with them — and a range printed beside somebody else's row says
    nothing at all about that one.
    """
    _, bare, _, unit, named, _ = FIVE_SHAPES[-2]
    rows = _two_scales(bare, None, unit, named)
    assert [chart["unit"] for chart in charts(rows, placing=[*FROM_RANGE, *BY_NUMBERS])] == [unit]

    with_a_range = [{**item, "reference": "2-15"} if item["unit"] == unit else item for item in rows]
    assert [chart["unit"] for chart in charts(with_a_range, placing=[*FROM_RANGE, *BY_NUMBERS])] == [unit]
    # And the printed range still wins where there is one beside the values with no unit: it is
    # read first, and it is read instead of the numbers, not after them.
    _, psa_bare, psa_range, psa_unit, psa_named, _ = FIVE_SHAPES[-1]
    assert [chart["unit"] for chart in
            charts(_two_scales(psa_bare, psa_range, psa_unit, psa_named),
                   placing=[*FROM_RANGE, *BY_NUMBERS])] == [psa_unit]  # fmt: skip


def test_a_range_printed_with_one_end_does_not_hand_a_scale_to_numbers_nowhere_near_it():
    """A floor printed alone, which no archive here happens to hold beside a scale to join.

    Invented for that reason, which is the whole of §6: the forms of the creatinine of FIVE_SHAPES
    print a floor instead of nothing — "більше 0,5", the shape of "> 0,6" and "більше 5" — and
    that is the one pair of scales this rule exists to keep apart. A floor bounds nothing above
    itself, so the printed reading degenerated into "the numbers are positive" and said yes to
    micromoles per litre, every one of which is above 0.25. It said it in place of the comparison
    of ends rather than before it, because a printed range is read first and instead of them, and
    the ends refuse this pair outright: 0.6 against 34 is a factor of sixty.
    """
    _, bare, _, unit, named, _ = FIVE_SHAPES[0]
    assert printed_range("більше 0,5") == (0.5, None)
    drawn = charts(_two_scales(bare, "більше 0,5", unit, named), placing=[*FROM_RANGE, *BY_NUMBERS])
    assert sorted(chart["unit"] for chart in drawn) == sorted(["", unit])
    assert sum(chart["by_numbers"] for chart in drawn) == 0
    assert ends_agree((min(bare), max(bare)), (min(named), max(named)), 2.0) is False

    # And a floor the values really were printed under still says which scale they are on: the
    # sedimentation rate of the same five, whose forms print "більше 2" beside readings of 2.5 to
    # 36 in millimetres an hour. Refusing every one-sided range outright would have cost this one.
    _, esr_bare, _, esr_unit, esr_named, _ = FIVE_SHAPES[-2]
    joined = charts(_two_scales(esr_bare, "більше 2", esr_unit, esr_named), placing=[*FROM_RANGE, *BY_NUMBERS])
    assert [chart["unit"] for chart in joined] == [esr_unit]
    assert joined[0]["by_numbers"] == len(esr_bare)


def test_two_spreads_are_compared_at_both_ends_and_a_printed_range_is_loosened_at_the_ends_it_printed():
    """The arithmetic on its own, where it lives."""
    assert ends_agree((4.0, 33.0), (2.5, 36.0), 2.0) is True
    assert ends_agree((0.6, 58.2), (34.0, 88.6), 2.0) is False  # the high ends agree; the low ends do not
    assert ends_agree((4.0, 35.0), (2.0, 35.0), 2.0) is True  # a factor of two exactly is still agreement
    assert ends_agree((1.0, 10.0), (0.0, 10.0), 2.0) is False  # a nought is not on any scale

    # An end the form left open limits nothing, and an open range is still worth reading: "up to 4"
    # says the size of the numbers even though it says nothing about how small they may be.
    assert numbers_fit_the_range((None, 4.0), [2.08, 4.61], 2.0) is True
    assert numbers_fit_the_range((None, 4.0), [34.0, 71.0], 2.0) is False
    assert numbers_fit_the_range((62.0, 106.0), [0.9, 1.1], 2.0) is False
    assert numbers_fit_the_range(None, [2.08], 2.0) is False
    assert numbers_fit_the_range((None, None), [2.08], 2.0) is False
    assert numbers_fit_the_range((None, 4.0), [], 2.0) is False

    # A range printed with one end is asked that end twice: the numbers have to keep to the side
    # it bounds, and they have to reach it. A floor of 0,6 bounds nothing above it, so without the
    # second question "more than 0,6" read as "the numbers are positive" and said yes to a scale
    # sixty times away from it — and said it in place of the comparison of ends, which refuses
    # exactly that pair.
    assert numbers_fit_the_range((0.6, None), [34.0, 71.0, 88.6], 2.0) is False
    assert numbers_fit_the_range((0.6, None), [34000.0, 88600.0], 2.0) is False
    assert numbers_fit_the_range((0.6, None), [0.41, 0.64], 2.0) is True  # the floor these were printed under
    assert numbers_fit_the_range((5.0, None), [5.3, 7.7], 2.0) is True
    assert numbers_fit_the_range((None, 4.0), [0.02, 0.05], 2.0) is False  # a ceiling is the hole upside down
    # Both ends printed stays as it was: the page has spoken about both of them, and a nought in
    # front of the dash is still the page speaking.
    assert numbers_fit_the_range((0.0, 4.0), [0.5, 1.8], 2.0) is True


# Where the two sets stand next to each other in time, which is the question the spreads cannot
# answer. A spread is as wide as the years and the readings that went into it, so two sets of
# different length are not the same question end to end — and the owner saw that on a marker that
# rises with age, drawn as two charts with the same unit on both of them. Two readings a few weeks
# apart are the same quantity whatever it has done over a lifetime.
#
# None of these five prints a range beside the values with no unit: a page that speaks is read
# first and instead of all of this, and FIVE_SHAPES above is where that is measured.
WHERE_THE_YEARS_MEET = [
    # A marker that rises, with the forms that printed a unit reaching further back than the ones
    # that did not. One history and one scale, and the ends refuse it: the low ends stand a factor
    # of five apart because one set begins eleven years before the other, which says which set is
    # longer and nothing at all about the scale.
    ("a marker that rises, half the forms printing no unit",
     [("2013-04-18", 1.07), ("2019-04-18", 1.82), ("2025-04-18", 4.68)],
     [("2002-04-18", 0.19), ("2012-04-18", 0.91), ("2018-04-18", 1.58), ("2024-04-18", 4.42)], "нг/мл", True),
    # Two measurements under one printed name: the share of the cells and the count of them, which
    # differ by a factor of ten and more. Every pair is of the wrong size, and the whole column
    # stays where it is.
    ("a share and a count under one name",
     [("2013-04-18", 2.4), ("2019-04-18", 3.8), ("2025-04-18", 6.1)],
     [("2012-04-18", 44.0), ("2018-04-18", 52.0), ("2024-04-18", 61.0)], "%", False),
    # And the worse half of the same shape: the values with no unit are themselves the share and
    # the count mixed together. One pair of the wrong size is enough to refuse the column, which
    # is what all-or-nothing is for.
    ("the share and the count mixed in one column",
     [("2013-04-18", 41.0), ("2019-04-18", 3.8), ("2025-04-18", 58.0)],
     [("2012-04-18", 44.0), ("2018-04-18", 52.0), ("2024-04-18", 61.0)], "%", False),
    # Values with no unit that agree with one of the two scales in front of them, and with the
    # other they do not: the one that fits takes them, because exactly one fits.
    ("one of the two scales in front of them",
     [("2013-04-18", 4.6), ("2019-04-18", 5.1), ("2025-04-18", 4.9)],
     [("2012-04-18", 4.4), ("2018-04-18", 5.3), ("2024-04-18", 4.8)], "ммоль/л", True),
    # And values that agree with neither of them: nothing here says which, so nothing is guessed.
    ("neither of the two scales in front of them",
     [("2013-04-18", 410.0), ("2019-04-18", 455.0), ("2025-04-18", 438.0)],
     [("2012-04-18", 4.4), ("2018-04-18", 5.3), ("2024-04-18", 4.8)], "ммоль/л", False),
]
#: The other scale standing in the way of the last two above: the same test printed in the unit
#: four laboratories out of five do not use, a hundred times away from the first.
THE_OTHER_SCALE = [("2014-04-18", 79.0), ("2020-04-18", 95.0), ("2026-04-18", 86.0)]


def _in_the_same_years(bare: list[tuple[str, float]], named: list[tuple[str, float]], unit: str,
                       printed: str | None = None) -> list[dict]:  # fmt: skip
    """One test drawn twice, with the two sets standing in the same stretch of years."""
    return [{"material": "blood", "date": day, "value": str(value), "value_numeric": value,
             "unit": None, "reference": printed} for day, value in bare] + \
           [{"material": "blood", "date": day, "value": str(value), "value_numeric": value,
             "unit": unit, "reference": None} for day, value in named]  # fmt: skip


@pytest.mark.parametrize("name,bare,named,unit,joins", WHERE_THE_YEARS_MEET,
                         ids=[row[0] for row in WHERE_THE_YEARS_MEET])  # fmt: skip
def test_values_with_no_unit_are_asked_against_their_neighbours_in_time_where_the_ends_refuse(
        name, bare, named, unit, joins):  # fmt: skip
    """Every one of the five, and a reading that closes one of them must not open another."""
    rows = _in_the_same_years(bare, named, unit)
    if "two scales in front of them" in name:
        rows += _in_the_same_years([], THE_OTHER_SCALE, "мг/дл")
    drawn = charts(rows, placing=[*FROM_RANGE, *BY_NUMBERS])
    if joins:
        assert unit in {chart["unit"] for chart in drawn}
        assert "" not in {chart["unit"] for chart in drawn}
        joined = next(chart for chart in drawn if chart["unit"] == unit)
        assert joined["by_numbers"] == len(bare)
        assert [item.get("unit_by_numbers") for item in joined["rows"]].count(True) == len(bare)
    else:
        assert "" in {chart["unit"] for chart in drawn}
        assert sum(chart["by_numbers"] for chart in drawn) == 0


def test_a_scale_with_fewer_values_than_the_rule_asks_for_is_not_joined_at_all():
    """The rule says nothing where the scale it would join has barely any numbers of its own.

    Both readings are noisy there: the spread of two readings is not the spread of that test, and
    a neighbour in time is one reading and not a history. least_to_join is what holds that shut,
    and the first of the five shapes above is the one to measure it on, because it is the one that
    joins.
    """
    _, bare, named, unit, _ = WHERE_THE_YEARS_MEET[0]
    rows = _in_the_same_years(bare, named[:1], unit)
    drawn = charts(rows, placing=[*FROM_RANGE, *BY_NUMBERS])
    assert sorted(chart["unit"] for chart in drawn) == sorted(["", unit])
    assert sum(chart["by_numbers"] for chart in drawn) == 0


def test_two_spellings_of_one_measure_are_one_scale_and_not_two_candidates():
    """A litre holds a thousand millilitres, so these two spellings are one scale and one chart.

    Counted as two candidates, "exactly one fits and no other does" was never true: three tests of
    the owner's archive kept a chart of their own headed with no unit beside the chart they belong
    on, and every one of them had a printed range that fitted both spellings — because both
    spellings are the same scale, and the charts join them a moment after this rule has run.
    """
    rows = [{"material": "blood", "date": "2018-03-12", "value": "6.2", "value_numeric": 6.2,
             "unit": None, "reference": "4,2 - 9,1"}]
    rows += [{"material": "blood", "date": day, "value": str(value), "value_numeric": value,
              "unit": unit, "reference": None}
             for day, value, unit in [("2016-04-11", 5.4, "10^9/L"), ("2019-04-11", 6.8, "10^9/L"),
                                      ("2021-04-11", 7.1, "10^9/L"), ("2024-04-11", 6.5, "10^3/uL"),
                                      ("2026-04-11", 5.9, "10^3/uL")]]  # fmt: skip

    drawn = charts(rows, placing=[*FROM_RANGE, *BY_NUMBERS])

    assert [chart["unit"] for chart in drawn] == ["10^9/L"]
    assert drawn[0]["by_numbers"] == 1 and drawn[0]["count"] == 6
    # Both spellings carry enough values of their own to be joined to, which is what made them two
    # candidates: the one with too few is held off by least_to_join and was never the difficulty.
    assert len([row for row in drawn[0]["rows"] if (row.get("unit") or "").endswith("uL")]) == 2


def test_the_pairs_in_time_on_their_own():
    """The arithmetic of the third reading, where it lives."""
    def rows(pairs):
        return [{"date": day, "value_numeric": value} for day, value in pairs]

    rising = [("2013-04-18", 1.07), ("2019-04-18", 1.82), ("2025-04-18", 4.68)]
    named = [("2002-04-18", 0.19), ("2012-04-18", 0.91), ("2018-04-18", 1.58), ("2024-04-18", 4.42)]
    assert _the_pairs_in_time_agree(rows(rising), rows(named), 2.0) is True
    # The ends of those same two spreads say the opposite, which is the whole reason this exists.
    assert ends_agree((1.07, 4.68), (0.19, 4.42), 2.0) is False

    # One pair of the wrong size refuses the column: that pair is a second scale in it.
    mixed = [*rising[:2], ("2025-04-18", 468.0)]
    assert _the_pairs_in_time_agree(rows(mixed), rows(named), 2.0) is False
    # And a nearest neighbour twenty years away is still the nearest one there is: the question is
    # asked and answered, and a marker that has risen tenfold since then is refused.
    assert _the_pairs_in_time_agree(rows(rising), rows(named[:1]), 2.0) is False
    # Nothing to pair with says nothing, rather than yes.
    assert _the_pairs_in_time_agree(rows(rising), [], 2.0) is False
    assert _the_pairs_in_time_agree([{"date": None, "value_numeric": 1.0}], rows(named), 2.0) is False
    assert _the_pairs_in_time_agree(rows(rising), [{"date": "2019-04-18", "value_numeric": None}], 2.0) is False


def test_the_unit_named_in_a_range_is_used_unless_a_person_turns_it_off():
    values = [
        {"value_numeric": "29.0", "unit": None, "reference": "19,0-37,0%", "material": "blood", "date": "2006-01-01"},
        {"value_numeric": "32.0", "unit": "%", "material": "blood", "date": "2007-01-17"},
    ]
    assert [chart["unit"] for chart in charts(values, placing=FROM_RANGE)] == ["%"]
    # With the rule off — which is what no rules at all means — the unit column is all that counts.
    assert sorted(chart["unit"] for chart in charts(values, placing=[])) == ["", "%"]


# The rules as they ship, read from their own files: these tests are the rules' tests too.
ALL = rules.load()
SCALE_RULES = [ALL.get("two-scales-in-one-test")]
FROM_RANGE = [ALL.get("unit_from_range")]
BY_NUMBERS = [ALL.get("unit_by_numbers")]
TO_SCALE = [ALL.get("one_scale_for_a_test")]


def _gravity(date: str, printed: str, number: float, band: str) -> dict:
    return {"date": date, "value": printed, "value_numeric": number, "unit": None, "reference": band}


def test_one_test_printed_at_two_scales_draws_one_history():
    """1,015 and 1015 are one measurement, and the range printed beside each one says so."""
    values = [
        _gravity("2004-06-25", "1,020", 1.02, "1,001-1,040"),
        _gravity("2005-02-01", "1,015", 1.015, "1,001-1,040"),
        _gravity("2015-04-17", "1,016", 1.016, "1,005-1,025"),
        _gravity("2020-11-24", "1017", 1017.0, "[ 1010 - 1030 ]"),
        _gravity("2023-05-11", "1016", 1016.0, "1010 - 1030"),
    ]
    chart = charts(values, placing=[*FROM_RANGE, *SCALE_RULES])[0]
    assert chart["scaled"] == 2  # the two forms that printed the thousandfold scale
    drawn = sorted(round(item["value_numeric"], 4) for item in chart["rows"])
    assert drawn == [1.015, 1.016, 1.016, 1.017, 1.02]
    assert [item["value"] for item in chart["rows"] if item.get("scaled")] == ["1017", "1016"]
    assert all(item["scaled"]["factor"] == 0.001 for item in chart["rows"] if item.get("scaled"))
    assert all(float(tick["label"].replace(",", ".")) < 2 for tick in chart["y_ticks"])  # one scale on the axis

    # The same values with the setting off: every number stays where the form printed it.
    left = charts(values, placing=FROM_RANGE)[0]
    assert left["scaled"] == 0
    assert sorted(round(item["value_numeric"], 4) for item in left["rows"]) == [1.015, 1.016, 1.02, 1016.0, 1017.0]


def test_a_value_far_outside_its_own_range_is_never_quietly_divided():
    """An abnormal result is a result. Only the printed ranges may say a test has two scales."""
    values = [
        {"date": "2024-07-15", "value": "384", "value_numeric": 384.0, "unit": "ng/ml", "reference": "24 - 336"},
        {"date": "2023-07-15", "value": "120", "value_numeric": 120.0, "unit": "ng/ml", "reference": "24 - 336"},
        {"date": "2022-07-15", "value": "90", "value_numeric": 90.0, "unit": "ng/ml", "reference": "24 - 336"},
    ]
    chart = charts(values, placing=[*FROM_RANGE, *SCALE_RULES])[0]
    assert chart["scaled"] == 0
    assert [item["value_numeric"] for item in chart["rows"]] == [90.0, 120.0, 384.0]


def test_ranges_that_are_simply_different_move_nothing():
    """Two bands three times apart are two laboratories, not two scales."""
    values = [
        {"date": "2019-01-01", "value": "5,4", "value_numeric": 5.4, "unit": "mg/dL", "reference": "3,4 - 7,0"},
        {"date": "2020-01-01", "value": "6,6", "value_numeric": 6.6, "unit": "mg/dL", "reference": "2,6 - 6,8"},
        {"date": "2021-01-01", "value": "7,0", "value_numeric": 7.0, "unit": "mg/dL", "reference": "3,6 - 7,7"},
    ]
    assert charts(values, placing=[*FROM_RANGE, *SCALE_RULES])[0]["scaled"] == 0


def test_a_value_with_no_range_of_its_own_joins_the_scale_its_size_matches():
    values = [
        _gravity("2004-06-25", "1,020", 1.02, "1,001-1,040"),
        _gravity("2005-02-01", "1,015", 1.015, "1,001-1,040"),
        _gravity("2019-10-15", "1.015", 1.015, None),
        _gravity("2020-11-24", "1017", 1017.0, "1010 - 1030"),
        _gravity("2023-05-11", "1016", 1016.0, "1010 - 1030"),
    ]
    chart = charts(values, placing=[*FROM_RANGE, *SCALE_RULES])[0]
    assert chart["scaled"] == 2
    assert sorted(round(item["value_numeric"], 4) for item in chart["rows"]) == [1.015, 1.015, 1.016, 1.017, 1.02]


def test_the_range_moves_its_own_distance_and_not_the_value_s():
    """A form with the range printed and the number written in by hand has said two scales.

    Moved together, the range of such a form landed a thousand below every point, stretched the
    axis from zero, and drew a history of one test as a single flat line at the top of it.
    """
    values = [
        _gravity("2004-06-25", "1,020", 1.02, "1,001-1,040"),
        _gravity("2005-02-01", "1,015", 1.015, "1,001-1,040"),
        _gravity("2015-04-17", "1,016", 1.016, "1,005-1,025"),
        _gravity("2007-01-22", "1009", 1009.0, "1,001-1,040"),  # range in one scale, number in the other
        _gravity("2020-11-24", "1017", 1017.0, "1010 - 1030"),  # both in the other
    ]
    chart = charts(values, placing=[*FROM_RANGE, *SCALE_RULES])[0]
    assert chart["scaled"] == 2
    # The form that printed its range in the drawn scale keeps that range where it printed it.
    kept = next(item for item in chart["rows"] if item["value"] == "1009")
    assert kept["scaled"]["factor"] == 0.001 and kept["scaled"]["band_factor"] == 1.0
    labels = [float(tick["label"].replace(",", ".")) for tick in chart["y_ticks"]]
    assert min(labels) > 0.9 and max(labels) < 1.1  # the axis is the width of the values, not of zero
    assert len(set(labels)) == len(labels)  # and five marks up the side say five different numbers


def test_a_value_that_is_not_a_number_is_not_moved_onto_the_scale(tmp_path):
    """"Not detected" printed where a number usually stands has a printed range beside it.

    So the range moved with the rest of the series and the value moved with the range — out of
    nothing into a nought, because `None or 0` times a factor is 0.0. That nought was drawn as a
    point on the line, joined to the real values, and it left the list of what could not be
    drawn, which is the one place a person could have checked it against the form.
    """
    from epicrisis import rules, series

    # The rule as it ships, not as this machine has it set: a test that quietly passes because a
    # rule happens to be off is a test that passes while the thing it guards is broken.
    moving = [rule for rule in rules.load(tmp_path) if rule.kind == "value-against-its-printed-range"]
    assert moving, "the rule that moves a series onto one scale ships with this program"
    items = [
        {"value": "1,015", "value_numeric": 1.015, "reference": "1.005 - 1.030"},
        {"value": "1,020", "value_numeric": 1.020, "reference": "1.005 - 1.030"},
        {"value": "1015", "value_numeric": 1015.0, "reference": "1005 - 1030"},
        {"value": "не виявлено", "value_numeric": None, "reference": "1005 - 1030"},
    ]
    moved = series._one_scale(items, moving)

    assert [row["value"] for row in moved] == [row["value"] for row in items]  # printed text untouched
    assert moved[-1]["value_numeric"] is None, "a row with no number must not acquire one"
    numbers = [row["value_numeric"] for row in moved[:3]]
    assert all(value is not None for value in numbers) and max(numbers) / min(numbers) < 1.5


def test_a_band_holds_the_value_it_was_printed_beside(tmp_path):
    """It used to run forward from its point to the next one.

    So every value stood on the left edge of its own band and was read against the band of the
    form before it — often another laboratory's. The newest value, the one a chart is usually
    opened for, got two pixels at the right-hand edge and read as a value that had left the
    shaded area. And where a form printed no range at all, the band of the form before it ran on
    over that value as though the range were still the same.
    """
    from epicrisis import series

    items = [
        {"value": "5,0", "value_numeric": 5.0, "reference": "4 - 6", "date": "2019-01-01"},
        {"value": "9,0", "value_numeric": 9.0, "reference": None, "date": "2021-01-01"},
        {"value": "5,2", "value_numeric": 5.2, "reference": "4 - 6", "date": "2023-01-01"},
    ]
    chart = series.charts(items)[0]
    bands, points = chart["bands"], [point["x"] for point in chart["points"]]

    assert len(bands) == 2, "a value with no printed range beside it gets no band"
    for band, point in zip(bands, [points[0], points[2]], strict=True):
        assert band["x"] <= point <= band["x"] + band["width"], "a band holds its own value"
        assert band["width"] > 50, "and is not a sliver at the edge of the chart"
    # The gap is the point: the range of one form says nothing about a value printed without one.
    assert bands[0]["x"] + bands[0]["width"] < points[1] < bands[1]["x"]


def test_a_range_printed_in_the_unit_of_its_value_is_brought_along_once():
    """The commonest shape in this archive, and it stretched thirty-five charts of it.

    A haemoglobin printed 15.07 g/dL is drawn as 150.7 г/л beside values printed in г/л, and the
    range printed next to it — "13.5 - 18" — is in g/dL too, because it is printed on the same
    form in the same column. It converts exactly as the value does, by the same factor.

    What happened instead: the rule that puts one test printed at two scales onto one scale was
    comparing numbers that had already been converted against ranges that had not, saw 150.7
    standing beside a range of 13.5 to 18, and moved the range by a power of ten to close a gap
    that the conversion had already explained. Then the band was multiplied by the conversion as
    well. The band came out ten times too high, and since the axis is drawn around the values and
    the bands together, fifteen years of somebody's results were drawn as one flat line along the
    floor of the chart, under a header saying ten values had been printed at another scale. None
    of them had been, and not one number was wrong.
    """
    printed_in_grams_per_litre = [
        {"date": "2019-03-04", "name": "Гемоглобин", "value": "152", "value_numeric": 152.0,
         "unit": "г/л", "reference": "130 - 160"},
        {"date": "2021-06-11", "name": "Гемоглобин", "value": "148", "value_numeric": 148.0,
         "unit": "г/л", "reference": "130 - 160"},
        {"date": "2023-09-19", "name": "Гемоглобин", "value": "160", "value_numeric": 160.0,
         "unit": "г/л", "reference": "130 - 160"},
    ]  # fmt: skip
    and_one_in_grams_per_decilitre = {
        "date": "2024-02-02", "name": "Hemoglobin", "value": "15.07", "value_numeric": 15.07,
        "unit": "g/dL", "reference": "13.5 - 18",
    }  # fmt: skip

    chart = charts([*printed_in_grams_per_litre, and_one_in_grams_per_decilitre],
                   indicator="hemoglobin", placing=[*TO_SCALE, *SCALE_RULES])[0]  # fmt: skip

    assert chart["unit"] == "г/л"
    converted = next(item for item in chart["rows"] if item["value"] == "15.07")
    assert converted["value_numeric"] == pytest.approx(150.7)
    # Nothing was printed at another scale, so nothing is said to have been.
    assert chart["scaled"] == 0
    assert _band_of(converted) == pytest.approx((135.0, 180.0))
    # And the axis is the width of the values and their ranges, not ten times it.
    labels = [float(tick["label"].replace(",", ".").replace(" ", "")) for tick in chart["y_ticks"]]
    assert max(labels) < 200, "the top of the axis is near the values, not ten times above them"
    assert min(labels) > 100, "and the floor of it is not dragged below anything that was measured"


def test_a_band_that_names_the_unit_of_the_chart_is_not_moved_onto_it():
    """A haematocrit printed 0,48 with no unit, beside a range printed "0,2-1,0%".

    The value is a fraction and belongs at 48 per cent: it moves, and the rule that moves it is
    right. The range does not move. It is already in per cent — it says so on the form — and
    carried along with the value it became a band from twenty to a hundred per cent, standing
    over values between thirty-seven and forty-eight and setting the top of the axis at a hundred
    and six. A range that names a unit has said its own scale; there is nothing to guess.
    """
    values = [
        {"date": "2019-03-04", "name": "Ht", "value": "41", "value_numeric": 41.0, "unit": "%",
         "reference": "39 - 49"},
        {"date": "2021-06-11", "name": "Ht", "value": "44", "value_numeric": 44.0, "unit": "%",
         "reference": "39 - 49"},
        {"date": "2022-02-08", "name": "Ht", "value": "0,48", "value_numeric": 0.48, "unit": None,
         "reference": "0,2-1,0%"},
        {"date": "2023-09-19", "name": "Ht", "value": "46", "value_numeric": 46.0, "unit": "%",
         "reference": "39 - 49"},
    ]  # fmt: skip

    chart = charts(values, indicator="hematocrit", placing=[*FROM_RANGE, *SCALE_RULES])[0]

    a_fraction = next(item for item in chart["rows"] if item["value"] == "0,48")
    assert a_fraction["value_numeric"] == pytest.approx(48.0), "the value is drawn where it belongs"
    assert a_fraction["scaled"]["band_factor"] == 1.0, "and its range is left where the form printed it"
    assert _band_of(a_fraction) == pytest.approx((0.2, 1.0))
    labels = [float(tick["label"].replace(",", ".")) for tick in chart["y_ticks"]]
    assert max(labels) < 60, "so the top of the axis is near the values, not at a hundred"


def test_a_corrected_number_reaches_the_chart_with_nobody_running_a_command(archive_index):  # noqa: F811
    """A card is drawn from the files and a chart from the index, and they used to disagree.

    Somebody puts a number right in order to show the doctor the chart. The card agreed with them
    at once; the chart went on drawing the model's reading until `epicrisis index` was run in a
    terminal, and no page said so or offered to do it.
    """
    from epicrisis import indicators
    from epicrisis.corrections import set_value, value_key
    from epicrisis.index.build import build_index

    data_dir, source, labs = archive_index
    output = data_dir / "sources" / source.id
    # A value is drawn on a chart under the test it belongs to, so there has to be one.
    indicators.upsert(data_dir, None, "Cystatin C", ["Цистатин С"], status="approved")
    build_index(data_dir, [source])
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    url = f"/documents/{source.id}/{labs}/1"

    card = client.get(url).text
    key = card.split('name="key" value="')[1].split('"')[0]
    chart = card.split('href="/tests/')[1].split('"')[0]
    assert "0,85" in client.get(f"/tests/{chart}").text

    client.post(f"{url}/value", data={"key": key, "name": "Цистатин С", "value": "1,85",
                                     "unit": "мг/л", "reference": "0,5-1,0", "flag": ""})  # fmt: skip
    assert "1,85" in client.get(url).text
    assert "1,85" in client.get(f"/tests/{chart}").text  # and nothing was run by hand in between

    # Every other way an index comes to be older than the files it is built from: a correction made
    # while this server was not running, a build that failed, a reading run in a terminal. Then the
    # line says so on every page, and the button on it is the thing that was missing.
    set_value(output, labs, [1, 2], value_key(1, "Цистатин С", "0,85"),
              {"value_as_printed": "2,85"})  # fmt: skip
    page = client.get("/").text
    assert "A correction here is not in the charts yet." in page
    assert f'action="/index/{source.id}/build"' in page

    assert client.post(f"/index/{source.id}/build", follow_redirects=False).status_code == 303
    assert "not in the charts yet" not in client.get("/").text
    assert "2,85" in client.get(f"/tests/{chart}").text
    # Only the archive that is open, as with every other act on somebody's records.
    assert client.post("/index/no-such-archive/build").status_code == 404


def test_a_save_while_the_index_is_being_built_is_not_the_one_left_out(archive_index, monkeypatch):  # noqa: F811
    """Five saves down a table are one build; the one made during a build is another.

    Whoever is saving does not know a build is running, and the change made while it ran is not in
    the file it wrote. Left there, the page would go on saying the chart is older than the archive
    with nothing on its way to make that untrue again.
    """
    import threading
    import time as clock

    from epicrisis.index import build as index_build
    from epicrisis.sources import SourceRegistry
    from epicrisis.web import building as building_module

    data_dir, source, _labs = archive_index
    monkeypatch.setattr(building_module, "QUIET_SECONDS", 0.05)
    builds, under_way = [], threading.Event()

    def slow_build(*_args, **_kwargs):
        builds.append(1)
        under_way.set()
        clock.sleep(0.4)
        return {}

    monkeypatch.setattr(index_build, "build_index", slow_build)
    work = building_module.Building(data_dir, SourceRegistry(data_dir))

    for _ in range(5):
        work.after_a_change(source.id)  # one line after another, as a person works down a table
    assert under_way.wait(5)
    work.after_a_change(source.id)  # and this one lands while that build is running
    waited = clock.monotonic() + 20
    while work.state(source.id)["building"] and clock.monotonic() < waited:
        clock.sleep(0.05)

    assert not work.state(source.id)["building"] and not work.state(source.id)["trouble"]
    assert 2 <= len(builds) <= 3  # the run of saves, then the one made during it


def test_a_build_that_fails_says_so_on_every_page_without_quoting_the_archive(archive_index, monkeypatch):  # noqa: F811
    """The chart is left showing the old number, so the pages have to say why."""
    from epicrisis import indicators
    from epicrisis.index import build as index_build

    data_dir, source, labs = archive_index
    indicators.upsert(data_dir, None, "Cystatin C", ["Цистатин С"], status="approved")
    index_build.build_index(data_dir, [source])
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    url = f"/documents/{source.id}/{labs}/1"
    key = client.get(url).text.split('name="key" value="')[1].split('"')[0]

    where = "/home/somebody/Documents/scans/blood-2019.pdf"
    monkeypatch.setattr(index_build, "build_index", lambda *a, **k: (_ for _ in ()).throw(OSError(where)))
    client.post(f"{url}/value", data={"key": key, "name": "Цистатин С", "value": "1,85",
                                     "unit": "мг/л", "reference": "0,5-1,0", "flag": ""})  # fmt: skip

    for page in (client.get("/").text, client.get(url).text):
        assert "could not be built in: OSError" in page and "Nothing is lost" in page
        # The kind of failure and nothing else. An exception's own words are where the name of a
        # file of somebody's archive gets out, and this sentence is drawn on every page of it.
        assert where not in page and "blood-2019" not in page


def test_a_chart_says_whose_archive_it_is_under_the_drawing(archive_index):  # noqa: F811
    """This is the page that gets held up to a doctor, and it carried no name at all.

    One server holds several people and shows one at a time, so the same address draws a different
    person's years depending on what is open. The strip of tabs is answered by the title of the
    page; a photograph of the chart is answered only by what is inside the picture.
    """
    import sqlite3

    from epicrisis import indicators
    from epicrisis.index.build import build_index

    data_dir, source, labs = archive_index
    indicators.upsert(data_dir, None, "Cystatin C", ["Цистатин С"], status="approved")
    build_index(data_dir, [source])
    # A drawing needs two numbers. This archive has one of this test, so a second is put beside it.
    writable = sqlite3.connect(index_path(data_dir, source.id))
    writable.row_factory = sqlite3.Row
    with writable:
        row = dict(writable.execute("SELECT * FROM observations WHERE indicator_id IS NOT NULL LIMIT 1").fetchone())
        row.pop("id", None)
        row.update(value="0,95", value_numeric=0.95)
        writable.execute(
            f"INSERT INTO observations ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values())
        )  # fmt: skip
    writable.close()
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    card = client.get(f"/documents/{source.id}/{labs}/1").text
    chart = card.split('href="/tests/')[1].split('"')[0]

    page = client.get(f"/tests/{chart}").text

    # And the search knows this test by its own name, in the language the question is asked in
    # rather than the one the form was printed in: the indicators gather the spellings, and the
    # search page was the one place in the program that never asked them.
    found = client.get("/search", params={"q": "cystatin"}).text
    assert "by that name" in found and "Cystatin C" in found

    assert f'class="chart-whose caps">archive of {source.whose}' in page
    # And to anybody reading the drawing through a screen reader rather than looking at it.
    assert f"from the archive of {source.whose}, oldest first" in page


def test_what_a_form_never_said_is_told_once_for_a_page_of_values(archive_index):  # noqa: F811
    """A form holding two specimens leaves its whole panel without a label.

    Under one tab called "Not said" sat two different things: seven hundred measurements made on a
    person — a refraction, the width of a kidney, a blood pressure, which are of no sample at all
    and which a model had already said so about — and a hundred lab values whose panel could not
    answer because it held blood and urine at once. The first is not work and the second is, and a
    person looking for the second saw a list made mostly of the first.
    """
    import json as json_module
    import sqlite3

    from epicrisis import indicators, query
    from epicrisis.corrections import load_value_corrections
    from epicrisis.index.build import build_index

    data_dir, source, _labs = archive_index
    output = data_dir / "sources" / source.id
    indicators.upsert(data_dir, None, "Cystatin C", ["Цистатин С"], status="approved")
    build_index(data_dir, [source])

    # One of them is of no sample, as a model said of its panel; the other is a lab value whose
    # panel held two specimens. Both have no material, and they are not the same thing.
    writable = sqlite3.connect(index_path(data_dir, source.id))
    writable.row_factory = sqlite3.Row
    with writable:
        row = dict(writable.execute("SELECT * FROM observations WHERE indicator_id IS NOT NULL LIMIT 1").fetchone())
        writable.execute("UPDATE observations SET material = NULL, material_source = 'not_a_sample' WHERE id = ?",
                         (row["id"],))  # fmt: skip
        of_a_mixed_panel = dict(row)
        of_a_mixed_panel.pop("id", None)
        of_a_mixed_panel.update(material=None, material_source=None, value="0,91")
        writable.execute(
            f"INSERT INTO observations ({', '.join(of_a_mixed_panel)}) VALUES ({', '.join('?' * len(of_a_mixed_panel))})",
            tuple(of_a_mixed_panel.values()),
        )  # fmt: skip
    writable.close()

    with sqlite3.connect(index_path(data_dir, source.id)) as check:
        check.row_factory = sqlite3.Row
        present = query.materials_present(check)
    assert present.get("not_a_sample") == 1 and present.get("unknown") == 1

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    card = client.get(f"/documents/{source.id}/{_labs}/1").text
    chart = card.split('href="/tests/')[1].split('"')[0].split("?")[0]

    page = client.get(f"/tests/{chart}?material=unknown").text
    assert "Material unknown" in page and "Not said" not in page
    assert "of a specimen nobody has been able to name yet" not in page  # this tab is that specimen
    assert "lab values missing a label" in page
    assert f'action="/tests/{source.id}/{chart}/material"' in page and 'name="material"' in page

    beside = client.get(f"/tests/{chart}?material=not_a_sample").text
    assert "measured on the person rather than in a sample" in beside
    assert 'action="/tests/' not in beside  # nothing to settle: it is an answer, not a gap

    # One press says it for every value of this test that had no answer, as the person's own word.
    done = client.post(f"/tests/{source.id}/{chart}/material", data={"material": "blood"},
                       follow_redirects=False)  # fmt: skip

    assert done.status_code == 303
    written = [line for line in load_value_corrections(output).values()]
    assert written and all(line["changes"]["material"] == "blood" for line in written)
    assert len(written) == 1  # the one of a mixed panel, and not the one that is of no sample

    # A material this program does not know is refused, and nothing is written for it.
    refused = client.post(f"/tests/{source.id}/{chart}/material", data={"material": "moonlight"})
    assert refused.status_code == 400 and "not a material" in refused.text
    assert len(load_value_corrections(output)) == 1
    assert json_module  # the correction file is JSON lines, read above through its own reader


def _an_archive_printing_the_same_test(data_dir, source_id: str, indicator_id: str, printed: str) -> None:
    """A second archive, with one value of the same test and no specimen named for it either.

    Two people both having a haemoglobin is the ordinary case, and that the printed name is the
    same in both archives is the shared vocabulary doing its job: it names a form, not a person.
    Built by hand rather than read by a model, because what is under test is which folder a press
    writes into and nothing about the reading.
    """
    import sqlite3

    from epicrisis.index.build import SCHEMA, SCHEMA_VERSION

    index = sqlite3.connect(index_path(data_dir, source_id))
    with index:
        index.executescript(SCHEMA)
        index.executemany("INSERT INTO meta VALUES (?, ?)",
                          [("built_at", "2026-01-01T00:00:00+00:00"), ("schema_version", str(SCHEMA_VERSION))])  # fmt: skip
        index.execute(
            """INSERT INTO files (sha256, file_id, source_id, path, category, page_count)
               VALUES (?, ?, ?, ?, 'scan', 1)""",
            ("dd" * 32, "dddddddd", source_id, "/scans/theirs.pdf"),
        )  # fmt: skip
        index.execute(
            """INSERT INTO documents (source_id, file_sha256, first_page, pages, doc_type, language,
                                      title, date, date_precision, transcribed, primary_copy)
               VALUES (?, ?, 1, '[1]', 'lab_panel', 'uk', ?, '2015-05-05', 'day', 1, 1)""",
            (source_id, "dd" * 32, printed),
        )  # fmt: skip
        document = index.execute("SELECT last_insert_rowid()").fetchone()[0]
        index.execute(
            """INSERT INTO observations (document_id, page, kind, name, value, value_numeric, unit,
                                         reference, indicator_id, value_role)
               VALUES (?, 1, 'quantitative', ?, '1,11', 1.11, 'мг/л', '0,5-1,0', ?, 'result')""",
            (document, printed, indicator_id),
        )  # fmt: skip
    index.close()


def test_a_specimen_settled_on_one_archives_page_is_never_written_against_anothers(archive_index, tmp_path):  # noqa: F811
    """The one press that says what a page of values was measured in, and whose page it was.

    It read `registry.active()` — the archive open at the moment the press landed — and wrote a
    correction, one line per value, into that archive's own folder. A page of values takes a
    while to read and the archive can be switched from the bar of any page in another tab
    meanwhile, so the press settled the specimen of every unlabelled value of that test in an
    archive the person was not looking at: their own work, written against somebody else's
    printed lines, and said out loud nowhere. The constitution's first entry asks every door into
    an archive to take which archive it is with no default; this one had one.
    """
    import sqlite3

    from epicrisis import indicators
    from epicrisis.corrections import load_value_corrections
    from epicrisis.index.build import build_index
    from epicrisis.sources import SourceRegistry, source_output_dir

    data_dir, source, labs = archive_index
    printed = "Цистатин С"
    indicators.upsert(data_dir, None, "Cystatin C", [printed], status="approved")
    build_index(data_dir, [source])
    # One value of this archive whose panel never said what it was measured in, beside one that
    # printed its specimen: the page draws its tabs, and the button, only where there are two.
    writable = sqlite3.connect(index_path(data_dir, source.id))
    writable.row_factory = sqlite3.Row
    with writable:
        writable.execute("UPDATE observations SET material = NULL, material_source = NULL "
                         "WHERE indicator_id IS NOT NULL")  # fmt: skip
        row = dict(writable.execute("SELECT * FROM observations WHERE indicator_id IS NOT NULL").fetchone())
        chart = row["indicator_id"]
        row.pop("id", None)
        row.update(material="blood", material_source="printed", value="0,91")
        writable.execute(
            f"INSERT INTO observations ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
            tuple(row.values()),
        )  # fmt: skip
    writable.close()

    registry = SourceRegistry(data_dir)
    elsewhere = tmp_path / "another-archive"
    elsewhere.mkdir()
    other = registry.add(str(elsewhere), "Dovbushenko Myrosya")
    _an_archive_printing_the_same_test(data_dir, other.id, chart, printed)
    theirs = source_output_dir(data_dir, other.id)

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = client.get(f"/tests/{chart}?material=unknown").text
    # The form says which archive these values are of, so that the press cannot be about another.
    assert f'action="/tests/{source.id}/{chart}/material"' in page

    registry.set_active(other.id)
    refused = client.post(f"/tests/{source.id}/{chart}/material", data={"material": "urine"})

    assert refused.status_code == 404
    assert "nothing was changed" in refused.text  # and in words, with a way on: §7
    assert load_value_corrections(theirs) == {}, "a press about one archive corrected another's lines"
    assert load_value_corrections(source_output_dir(data_dir, source.id)) == {}

    # And with its own archive open the press does land, or the lines above are about nothing.
    registry.set_active(source.id)
    done = client.post(f"/tests/{source.id}/{chart}/material", data={"material": "urine"},
                       follow_redirects=False)  # fmt: skip
    assert done.status_code == 303
    written = list(load_value_corrections(source_output_dir(data_dir, source.id)).values())
    assert written and all(line["changes"]["material"] == "urine" for line in written)
    assert load_value_corrections(theirs) == {}


def test_the_count_over_a_test_says_which_material_it_counted(archive_index):  # noqa: F811
    """"45 values" stood over tabs reading "blood 45" and "urine 7", and counted one of them.

    The heading follows the tab that is open, which is right, and said so nowhere — so the large
    number at the top of the page read as the whole test while being one material of it, over two
    tabs whose own numbers add up to something else.
    """
    import sqlite3

    from epicrisis import indicators
    from epicrisis.index.build import build_index

    data_dir, source, labs = archive_index
    indicators.upsert(data_dir, None, "Cystatin C", ["Цистатин С"], status="approved")
    build_index(data_dir, [source])
    # The same printed name on a urine form: a different measurement, its own tab, its own count.
    writable = sqlite3.connect(index_path(data_dir, source.id))
    writable.row_factory = sqlite3.Row
    with writable:
        writable.execute("UPDATE observations SET material = 'blood' WHERE indicator_id IS NOT NULL")
        template = dict(writable.execute(
            "SELECT * FROM observations WHERE indicator_id IS NOT NULL LIMIT 1").fetchone())  # fmt: skip
        template.pop("id", None)
        for value in ("0,41", "0,52"):
            of_urine = dict(template, material="urine", value=value, value_numeric=float(value.replace(",", ".")))
            writable.execute(
                f"INSERT INTO observations ({', '.join(of_urine)}) VALUES ({', '.join('?' * len(of_urine))})",
                tuple(of_urine.values()),
            )  # fmt: skip
    writable.close()
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    card = client.get(f"/documents/{source.id}/{labs}/1").text
    test_id = card.split('href="/tests/')[1].split('"')[0].split("?")[0]

    page = client.get(f"/tests/{test_id}").text

    # The tabs are the other count on this page: one of blood, two of urine.
    assert ">blood <span class=\"muted\">1</span>" in page and ">urine <span class=\"muted\">2</span>" in page
    # So the heading says which of them its own number is, and what the whole test holds here.
    assert '1 values<span class="chart-material caps">blood</span>' in page
    assert "of 3 this test has here, one material at a time" in page

    other = client.get(f"/tests/{test_id}?material=urine").text
    assert '2 values<span class="chart-material caps">urine</span>' in other
    assert "of 3 this test has here, one material at a time" in other


def test_a_chart_that_drew_nothing_says_which_of_the_three_things_happened():
    """One sentence — "Not enough numbers to draw a line here" — stood for five different causes.

    On a chart of words it reads as "have the test taken again", and no number of further tests
    would ever draw that line. The causes are told apart here; the sentences are in series.html.
    """
    from epicrisis.series import charts

    row = {"material": "blood", "document_id": 1, "page": 1, "name": "Colour"}

    words = charts([{**row, "date": "2014-02-07", "value": "straw", "value_numeric": None, "unit": ""},
                    {**row, "date": "2018-10-18", "value": "pale yellow", "value_numeric": None, "unit": ""}])[0]  # fmt: skip
    assert words["points"] == [] and words["not_drawn"]["reason"] == "not numbers"
    assert words["not_drawn"]["shapes"] == {"a word": 2}
    assert words["not_drawn"]["examples"]["a word"] == ["straw", "pale yellow"]

    # A printed span is the third cause and was named nowhere in the program: six urine leukocyte
    # counts of the demo archive are printed "1-2" and "2-4", which is a span and not a point.
    spans = charts([{**row, "date": "2014-09-14", "value": "2-4", "value_numeric": None, "unit": "per HPF"},
                    {**row, "date": "2016-06-21", "value": "1-2", "value_numeric": None, "unit": "per HPF"}])[0]  # fmt: skip
    assert spans["not_drawn"]["reason"] == "not numbers" and spans["not_drawn"]["shapes"] == {"a span": 2}

    # And the one cause where more numbers really is the answer.
    few = charts([{**row, "date": "2020-06-28", "value": "77", "value_numeric": 77.0, "unit": "mg/dL"}])[0]
    assert few["not_drawn"]["reason"] == "too few" and few["not_drawn"]["drawable"] == 1
    assert few["not_drawn"]["least"] == 2

    # The form printed a number and the reading brought it back as a word: that one is nobody's
    # laboratory and somebody's correction, so it is not counted among the words.
    misread = charts([{**row, "date": "2014-02-07", "value": "0,033", "value_numeric": None, "unit": "г/л"},
                      {**row, "date": "2017-08-22", "value": "0,033", "value_numeric": None, "unit": "г/л"}])[0]  # fmt: skip
    assert misread["not_drawn"]["shapes"] == {"a number": 2}
    assert misread["not_drawn"]["examples"]["a number"] == ["0,033"]

    # Invented, because no demo archive holds it: numbers with no day to stand on. The archive in
    # front of us is blind to the shapes it does not happen to contain.
    nowhere = charts([{**row, "date": None, "value": "71", "value_numeric": 71.0, "unit": "мкмоль/л"},
                      {**row, "date": None, "value": "74", "value_numeric": 74.0, "unit": "мкмоль/л"}])[0]  # fmt: skip
    assert nowhere["not_drawn"]["reason"] == "nowhere to put them"
    assert nowhere["not_drawn"]["numbers"] == 2 and nowhere["not_drawn"]["numbers_undated"] == 2

    # A chart that drew a line is asked nothing and says nothing.
    drawn = charts([{**row, "date": "2019-03-04", "value": "71", "value_numeric": 71.0, "unit": "мкмоль/л"},
                    {**row, "date": "2021-06-07", "value": "69", "value_numeric": 69.0, "unit": "мкмоль/л"}])[0]  # fmt: skip
    assert drawn["points"] and "not_drawn" not in drawn


def test_the_page_says_a_different_thing_for_a_word_a_span_and_one_number(archive_index):  # noqa: F811
    """Three charts of one test, three causes, and the page said the same sentence on all of them.

    Measured on the three demo archives before this: nine charts drew nothing, eight of them held
    no number at all, and every one of the nine carried "Not enough numbers to draw a line here".
    """
    import sqlite3

    from epicrisis import indicators
    from epicrisis.index.build import build_index

    data_dir, source, labs = archive_index
    indicators.upsert(data_dir, None, "Cystatin C", ["Цистатин С"], status="approved")
    build_index(data_dir, [source])
    # One scale of words, one of printed spans, and the archive's own single number beside them.
    writable = sqlite3.connect(index_path(data_dir, source.id))
    writable.row_factory = sqlite3.Row
    with writable:
        template = dict(writable.execute(
            "SELECT * FROM observations WHERE indicator_id IS NOT NULL LIMIT 1").fetchone())  # fmt: skip
        template.pop("id", None)
        for value, unit in [("negative", ""), ("not detected", ""), ("0-1", "per HPF"), ("1-2", "per HPF")]:
            beside = dict(template, value=value, value_numeric=None, unit=unit, reference=None)
            writable.execute(
                f"INSERT INTO observations ({', '.join(beside)}) VALUES ({', '.join('?' * len(beside))})",
                tuple(beside.values()),
            )  # fmt: skip
    writable.close()
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    card = client.get(f"/documents/{source.id}/{labs}/1").text
    test_id = card.split('href="/tests/')[1].split('"')[0].split("?")[0]

    page = client.get(f"/tests/{test_id}").text

    assert "Not enough numbers" not in page
    assert "a word the form printed" in page and "no height on an axis" in page
    assert "printed as a span rather than a number" in page and "no one height to stand at" in page
    assert "a line needs 2 points to run between" in page
    # Both charts that will never draw a line say so; the one waiting on a laboratory does not.
    assert page.count("no further test would draw one") == 2


def test_the_asterisk_on_a_specimen_a_model_read_is_keyed_on_the_page(archive_index):  # noqa: F811
    """The key stood in the note that only appears where a test has more than one material.

    So on a test with one — which is most of them — the rows carried an asterisk and a dotted
    underline, the page said nothing anywhere about either, and the only words were in a title= a
    phone and a keyboard never show. The fourth entry of the constitution lets a model settle what
    names a form on three conditions, and one of them is that the page says it was a model, in the
    page's own words, beside the group and not in a footer.
    """
    import sqlite3

    from epicrisis import indicators
    from epicrisis.index.build import build_index

    data_dir, source, labs = archive_index
    indicators.upsert(data_dir, None, "Cystatin C", ["Цистатин С"], status="approved")
    build_index(data_dir, [source])
    # One material over the whole test, so the tabs that used to carry the key are not drawn.
    writable = sqlite3.connect(index_path(data_dir, source.id))
    with writable:
        writable.execute("UPDATE observations SET material = 'blood', material_source = 'model'")
    writable.close()
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    card = client.get(f"/documents/{source.id}/{labs}/1").text
    test_id = card.split('href="/tests/')[1].split('"')[0].split("?")[0]

    page = client.get(f"/tests/{test_id}").text

    assert 'class="materials caps"' not in page  # one material: no tabs, and that was the hiding place
    assert "An asterisk on a specimen below means the form printed none" in page
    assert "a model read the table the value stands in" in page
    assert "blood*" in page
    # And the words are on the page instead of in the tooltip they used to be the only copy of.
    assert "A model read the table this value stands in." not in page


def test_the_word_corrected_on_a_chart_row_is_the_way_to_what_it_used_to_say(archive_index):  # noqa: F811
    """The chart is the page the readme offers for showing a doctor from a phone.

    A row there said "corrected" and stopped: what the model had read is on the document's own
    card, and the page named neither the fact nor the way to it. So the badge is the way — the
    same tap that reaches it — and the note under the drawing says so, rather than leaving a
    person to guess that the file ID at the other end of the row is where their own earlier
    reading went.
    """
    from epicrisis import indicators
    from epicrisis.index.build import build_index

    data_dir, source, labs = archive_index
    indicators.upsert(data_dir, None, "Cystatin C", ["Цистатин С"], status="approved")
    build_index(data_dir, [source])
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    where = f"/documents/{source.id}/{labs}/1"
    key = client.get(where).text.split('name="key" value="')[1].split('"')[0]
    assert client.post(f"{where}/value", data={"key": key, "name": "Цистатин С", "value": "8,5",
                                               "unit": "мг/л", "reference": "0,5-1,0", "flag": ""},
                       follow_redirects=False).status_code == 303  # fmt: skip
    build_index(data_dir, [source])
    card = client.get(where).text
    test_id = card.split('href="/tests/')[1].split('"')[0].split("?")[0]

    page = client.get(f"/tests/{test_id}").text

    assert f'<a class="caps signal corrected-to" href="{where}">corrected</a>' in page
    assert "what the model had read is kept beside the way back to it" in page
