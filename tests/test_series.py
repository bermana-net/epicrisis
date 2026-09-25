"""Charts: geometry from printed numbers, and the page that draws them."""

from fastapi.testclient import TestClient

from epicrisis.index.build import index_path
from epicrisis.series import charts, printed_range
from epicrisis.units import unit_key
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
        {"date": "2019-07-08", "value_numeric": 71, "value": "71", "unit": "мкмоль/л", "reference": "62-106"},
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
    # One value in this archive: no line is drawn, and the value is still listed as printed.
    assert "Not enough numbers" in page.text and "0,85" in page.text and "0,5-1,0" in page.text
    assert "nothing here is averaged" in page.text and "high or low" in page.text
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

    connection = query.open_index(data_dir)
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
    # A spelling that looks like a misreading is left alone rather than guessed at.
    assert unit_key("10¹²/1") != unit_key("10¹²/л")


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
    for to_scale in (False, True):
        drawn = charts(values, indicator="creatinine", to_scale=to_scale)
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
    assert 'material=urine"' in page and 'material=none"' in page
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

    joined = charts(values, by_numbers=True)
    assert sorted(chart["unit"] for chart in joined) == ["%", "10^9/L"]
    per_cent = next(chart for chart in joined if chart["unit"] == "%")
    assert per_cent["count"] == 3 and per_cent["by_numbers"] == 1
    assert [item.get("unit_by_numbers") for item in per_cent["rows"]].count(True) == 1

    # Two scales the numbers could belong to: the numbers do not say, so nothing is moved.
    unclear = [*values[:2], {**blood, "value_numeric": "31.0", "unit": "mg/dl", "date": "2011-01-01"},
               {**blood, "value_numeric": "33.0", "unit": "mg/dl", "date": "2012-01-01"},
               {**blood, "value_numeric": "30.0", "unit": None, "date": "2013-12-16"}]  # fmt: skip
    assert "" in {chart["unit"] for chart in charts(unclear, by_numbers=True)}


def test_the_unit_named_in_a_range_is_used_unless_a_person_turns_it_off():
    values = [
        {"value_numeric": "29.0", "unit": None, "reference": "19,0-37,0%", "material": "blood", "date": "2006-01-01"},
        {"value_numeric": "32.0", "unit": "%", "material": "blood", "date": "2007-01-17"},
    ]
    assert [chart["unit"] for chart in charts(values)] == ["%"]
    assert sorted(chart["unit"] for chart in charts(values, from_range=False)) == ["", "%"]
