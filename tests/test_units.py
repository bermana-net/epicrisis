"""Bringing units to one scale. Synthetic values only."""

import pytest

from epicrisis import rules
from epicrisis.units import SCALES, convert, scale_of, unit_from_reference
from epicrisis.series import charts

# The rules as they ship: what a chart does with units is theirs to decide now.
ALL = rules.load()
TO_SCALE = [ALL.get("unit_from_range"), ALL.get("one_scale_for_a_test")]


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

    joined = charts(values, indicator="creatinine", placing=TO_SCALE)
    assert len(joined) == 1
    assert joined[0]["unit"] == "мкмоль/л" and joined[0]["converted_from"] == {"mg/dL": 88.4}
    # The printed values stay printed: the table under the chart is untouched.
    assert [row["value"] for row in joined[0]["rows"]] == ["80.0", "75.0", "0.9", "0.95"]
    assert [round(point["value_numeric"]) for point in joined[0]["points"]] == [80, 75, 80, 84]


def test_a_value_with_no_unit_takes_the_one_printed_in_its_range():
    values = [value("мкмоль/л", 80.0, 2019), value(None, 75.0, 2020, reference="53-115 мкмоль/л"),
              value(None, 4.2, 2021)]  # fmt: skip

    made = {chart["unit"]: chart for chart in charts(values, indicator="creatinine", placing=TO_SCALE[:1])}

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

    drawn = charts(values, indicator="creatinine", placing=TO_SCALE)[0]
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


def test_one_unit_written_in_two_alphabets_is_one_unit():
    """Од/л and U/L are the same unit, and they were two keys.

    A word left out of the table does not fail loudly: it stays in the key half translated, and
    the key comes out in two alphabets at once — "нmol/l" beside "nmol/l" — so one enzyme printed
    on a Ukrainian form and on an English one drew two separate charts of one history. On the
    real archive that was ten pairs of charts and fifteen per cent of every value with a unit.
    """
    from epicrisis.units import unit_key

    same = [("Од/л", "U/L"), ("Ед/л", "U/L"), ("Е/л", "U/L"), ("МЕ/л", "IU/L"),
            ("нмоль/л", "nmol/L"), ("пмоль/л", "pmol/L"), ("мкм/л", "umol/L"),
            ("мкмоль/л", "µmol/L"), ("мм/год", "mm/h"), ("мм/ч", "mm/h"),
            ("мл/хв/1,73 м²", "ml/min/1.73 m2"), ("мл/мин/1,73 м²", "ml/min/1.73 m2")]  # fmt: skip
    for cyrillic, latin in same:
        assert unit_key(cyrillic) == unit_key(latin), f"{cyrillic} and {latin}"

    # And the key of a unit this program knows is written in one alphabet, not in two.
    for printed, _ in same:
        assert not any("Ѐ" <= letter <= "ӿ" for letter in unit_key(printed)), printed

    # Units that are not the same must not become the same: the table is read longest word first,
    # and read shortest first it turned an hour into a unit — "мм/год" folded to "мм/gu".
    assert unit_key("мг/л") != unit_key("г/л") != unit_key("мкг/л")
    assert unit_key("ммоль/л") != unit_key("мкмоль/л") != unit_key("нмоль/л")


def test_the_capital_in_a_printed_range_is_part_of_the_unit():
    """Г/л is giga per litre — a count of cells. г/л is grams per litre. One letter apart.

    The unit named inside a printed range was read with the case dropped, which is right for
    мг/дл and MG/DL and wrong for exactly this pair: a platelet count printed "180,0-320,0 Г/л",
    on a form with no unit column, was given grams per litre and drawn on the scale of the
    proteins, a thousand million times away from what it is.
    """
    from epicrisis.units import unit_from_reference

    assert unit_from_reference("180,0-320,0 Г/л") == "10^9/l"
    assert unit_from_reference("4,0-9,0 Г/л") == "10^9/l"
    assert unit_from_reference("60 - 80 г/л") == "g/l"
    assert unit_from_reference("3,5-5,5 g/l") == "g/l"


def test_the_capital_is_the_unit_only_when_it_is_the_whole_unit():
    """"Г/Л" is inside "МГ/Л" and "МКГ/Л" and "MG/L".

    Looked for as a substring, the capital that means giga per litre matched the tail of
    milligrams and micrograms per litre, and put a range printed in milligrams on the scale of a
    cell count: the very mistake the capital was added to prevent, in the other direction and
    over more values than it ever fixed.
    """
    from epicrisis.units import unit_from_reference

    assert unit_from_reference("10,0-25,0 МГ/Л") == "mg/l"
    assert unit_from_reference("3 - 8 МКГ/Л") == "ug/l"
    assert unit_from_reference("0,5-2,0 MG/L") == "mg/l"
    # And the unit it was added for still reads as itself.
    assert unit_from_reference("180,0-320,0 Г/л") == "10^9/l"
    assert unit_from_reference("4,0-9,0 Г/Л") == "10^9/l"
