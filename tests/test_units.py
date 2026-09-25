"""Bringing units to one scale. Synthetic values only."""

import pytest

from epicrisis.units import SCALES, convert, scale_of, unit_from_reference
from epicrisis.series import charts


def test_a_factor_is_used_only_where_the_table_names_it():
    assert convert(0.5, "mg/dl", "creatinine", "Creatinina") == pytest.approx((44.2, "мкмоль/л", 88.4), rel=1e-6)
    assert convert(0.05, "mmol/l", "creatinine", "Креатинін") == pytest.approx((50.0, "мкмоль/л", 1000.0), rel=1e-6)
    assert convert(80.0, "umol/l", "creatinine", "Креатинин")[0] == 80.0  # already on the scale
    assert convert(14.6, "g/dl", "hemoglobin", "Hemoglobina") == pytest.approx((146.0, "г/л", 10.0), rel=1e-6)

    # The printed name has to say the analyte: an abbreviation alone is not multiplied by a guess.
    assert convert(0.5, "mg/dl", "creatinine", "Cr.") is None
    assert convert(0.5, "mg/dl", "creatinine", None) is None

    # A ratio, a urine collection and a fraction are different measurements: no borrowed factors.
    assert convert(0.5, "mg/dl", "urine-creatinine", "Creatinina") is None
    assert convert(0.5, "mg/dl", "albumin-creatinine-ratio", "Creatinina") is None
    assert convert(0.5, "mg/dl", None, "Creatinina") is None
    # A unit the table does not name is left alone, however familiar it looks.
    assert convert(5.0, "g/kg", "hemoglobin", "Hemoglobina") is None
    assert scale_of("leukocyte") is None  # cell counts are joined by their writing, not converted


def test_every_scale_converts_its_own_unit_by_one():
    """A factor of one for the target unit: a value already on the scale must not move."""
    for analyte, scale in SCALES.items():
        assert scale["from"][scale["key"]] == 1.0, analyte


def test_a_unit_named_inside_a_printed_range_is_read_from_it():
    assert unit_from_reference("53-115 мкмоль/л") == "umol/l"
    assert unit_from_reference("Ч. 0,05-0,11 мМ/л Ж. 0,045-0,097 мМ/л") == "mmol/l"
    assert unit_from_reference("0,67 - 1,17") is None  # a range with no unit says nothing
    assert unit_from_reference("не виявлено") is None
    assert unit_from_reference(None) is None


def value(unit, number, year, reference=None):
    return {"date": f"{year}-05-01", "unit": unit, "value_numeric": number, "value": str(number),
            "name": "Creatinine", "reference": reference}  # fmt: skip


def test_one_scale_joins_the_charts_and_says_what_it_moved():
    values = [value("мкмоль/л", 80.0, 2019), value("мкмоль/л", 75.0, 2020),
              value("mg/dL", 0.9, 2021), value("mg/dL", 0.95, 2022)]  # fmt: skip

    assert len(charts(values, indicator="creatinine")) == 2

    joined = charts(values, indicator="creatinine", to_scale=True)
    assert len(joined) == 1
    assert joined[0]["unit"] == "мкмоль/л" and joined[0]["converted_from"] == {"mg/dL": 88.4}
    # The printed values stay printed: the table under the chart is untouched.
    assert [row["value"] for row in joined[0]["rows"]] == ["80.0", "75.0", "0.9", "0.95"]
    assert [round(point["value_numeric"]) for point in joined[0]["points"]] == [80, 75, 80, 84]


def test_a_value_with_no_unit_takes_the_one_printed_in_its_range():
    values = [value("мкмоль/л", 80.0, 2019), value(None, 75.0, 2020, reference="53-115 мкмоль/л"),
              value(None, 4.2, 2021)]  # fmt: skip

    made = {chart["unit"]: chart for chart in charts(values, indicator="creatinine")}

    assert made["мкмоль/л"]["count"] == 2  # the one whose range names the unit joins it
    assert made[""]["count"] == 1  # the one that names nothing stays apart


def test_a_converted_chart_moves_the_printed_range_with_the_values():
    """Values on one scale and a band on another is a chart of two different things."""
    from epicrisis.series import charts

    values = [
        {"date": f"201{year}-01-01", "value": "0,9", "value_numeric": 0.9, "unit": "mg/dL",
         "reference": "0,51 - 0,95", "material": "blood", "name": "Креатинін"}
        for year in range(3)
    ]  # fmt: skip

    drawn = charts(values, indicator="creatinine", to_scale=True)[0]
    point = drawn["points"][0]

    assert drawn["unit"] == "мкмоль/л"
    assert round(point["value_numeric"]) == 80  # 0,9 mg/dL
    # The value sits inside the band, as it does on the form: between 45 and 84 µmol/L.
    assert point["band_top"] < point["y"] < point["band_bottom"]

    # And with the conversion off, the printed range and the printed value are drawn as printed.
    plain = charts(values, indicator="creatinine")[0]
    assert plain["unit"] == "mg/dL" and plain["points"][0]["value_numeric"] == 0.9


def test_an_archive_whose_labels_are_not_latin_converts_too():
    """Its indicators are called "indicator-2", and every table here is keyed by what a test is."""
    from epicrisis.units import convert
    from epicrisis.indicators import slug

    # The id such a label gets is readable now, and an old opaque one still converts by the name.
    assert slug("Креатинін", set()) == "kreatynyn"
    assert convert(0.9, "mg/dl", "indicator-2", "Креатинін") == (79.56, "мкмоль/л", 88.4)

    # What was deliberate stays deliberate: a urine collection borrows no serum factor, and a
    # value that is in no group at all is not converted by its name alone.
    assert convert(0.5, "mg/dl", "urine-creatinine", "Creatinina") is None
    assert convert(0.5, "mg/dl", None, "Creatinina") is None
    assert convert(0.9, "mg/dl", "indicator-2", "Глюкоза крові") != (79.56, "мкмоль/л", 88.4)


def test_a_range_that_is_only_numbers_and_a_per_cent_sign_says_its_unit():
    """"19,0-37,0%" is a percentage and can be nothing else; reading it is reading the form.

    A range holding two ranges — the relative and the absolute count printed on one line — says
    two things, and which of them the value belongs to is written nowhere, so it says nothing.
    """
    assert unit_from_reference("19,0-37,0%") == "%"
    assert unit_from_reference("[ 20 - 44 % ]") == "%"
    assert unit_from_reference("19 – 37 % 1,200 – 3,000*10⁹/л") is None
    assert unit_from_reference("20 - 44") is None
    # A unit named outright still wins over the per-cent shape: "мг%" is milligrams per decilitre.
    assert unit_from_reference("0 - 5 мг%") == "mg/dl"
