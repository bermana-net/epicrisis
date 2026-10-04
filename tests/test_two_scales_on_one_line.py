"""A form that prints both bands of one test on one line, and reading it as the two it is.

A blood count prints the relative count and the absolute one side by side —
"47 – 72 % 2,000 – 5,500*10⁹/л" — and read as one range that is "47 to 72" and nothing else: the
per-cent half taken for the whole of what the form printed, the absolute half lost, and a value
with no unit beside it measured against a band of neither.

What makes the shape readable is written in reference.a_band_for_each_unit and is the subject of
most of these tests: every range on the line names a unit of its own, and no two name the same
one, so a value read in one of those units has exactly one band there and the choice is the
form's. Everything short of that — two bands for men and women, a range with a stray number, a
table of what a result would mean — goes on being refused, and the second half of these tests is
about that, because a reader that accepts too much is the same defect the other way round.
"""

from epicrisis import reference, rules
from epicrisis.index.build import build_index
from epicrisis.query import open_index
from epicrisis.series import _band_of, charts
from epicrisis.settings import rules_on
from test_extract import FakeExtractBackend, setup  # noqa: F401
from conftest import A_DAY_FOR_AN_ILLUSTRATION

#: The line as one of this archive's forms prints it, en dashes, decimal commas and all.
BOTH_BANDS = "47 – 72 % 2,000 – 5,500*10⁹/л"

ALL = rules.load()
FROM_RANGE = [ALL.get("unit_from_range")]
BY_NUMBERS = [ALL.get("unit_by_numbers")]


def test_a_line_that_prints_a_band_for_each_unit_is_read_as_two_bands():
    """Each band by the unit the form labelled it with, and neither of them as the whole line."""
    assert reference.a_band_for_each_unit(BOTH_BANDS) == {
        "%": "47 – 72 % ", "10^9/l": "2,000 – 5,500*10⁹/л"}
    # Asked with no unit in hand, the line says nothing: two ranges stand there and the form did
    # not say which of them the value beside it was printed in.
    assert reference.parse(BOTH_BANDS) is None
    assert reference.parse(BOTH_BANDS, "%") == (47.0, 72.0)
    # Every spelling of the absolute scale finds the same band, because the unit is read by the
    # one reader of units and not by the text of the range.
    assert reference.parse(BOTH_BANDS, "10⁹/л") == (2.0, 5.5)
    assert reference.parse(BOTH_BANDS, "х10⁹/л") == (2.0, 5.5)
    assert reference.parse(BOTH_BANDS, "10^9/L") == (2.0, 5.5)
    # And a unit the line never named has no band on it.
    assert reference.parse(BOTH_BANDS, "г/л") is None
    assert reference.parse(BOTH_BANDS, "мм/ч") is None


def test_the_same_shape_however_the_form_spaced_and_ordered_it():
    """The unit chooses the band, not the order the form printed the two in."""
    plainly = "19 - 37 % 1,200 - 3,000 10⁹/л"
    assert reference.parse(plainly) is None
    assert reference.parse(plainly, "%") == (19.0, 37.0)
    assert reference.parse(plainly, "10⁹/л") == (1.2, 3.0)
    backwards = "1,200 - 3,000 10⁹/л 19 - 37 %"
    assert reference.parse(backwards) is None
    assert reference.parse(backwards, "%") == (19.0, 37.0)
    assert reference.parse(backwards, "10⁹/л") == (1.2, 3.0)


def test_two_bands_the_line_does_not_label_are_refused_as_they_always_should_have_been():
    """A band for men and a band for women is not a band per scale, and never was.

    What tells those two apart is a person's sex, which is not printed on the line. The guard for
    it counted the dashes and knew only the ASCII hyphen, so the shape printed with the en dash
    forms use — and three values of this archive are printed that way — was read as the band for
    men. A woman's value drawn against a man's band is exactly what this module's own first
    paragraph promises not to do.
    """
    for one_each in ("М 130,0 – 160,0 Ж 120,0 – 140,0 г/л", "М 2 – 10 Ж 2 – 15 мм/ч",
                     "М 4,0 – 5,0 Ж 3,9 – 4,7 * 10¹²/л", "Ч 11 – 61 Од/л Ж 9 – 39 Од/л",
                     "Varones 13,0 a 17,0 Mujeres 11,5 a 15,5"):  # fmt: skip
        assert reference.a_band_for_each_unit(one_each) is None, one_each
        assert reference.parse(one_each) is None, one_each
        # And naming a unit does not let one of them in: the line labelled no band with it.
        assert reference.parse(one_each, "г/л") is None, one_each


def test_one_range_with_a_stray_number_is_still_one_range():
    """The shape accepted is narrow, and everything these lines hold is read as it was before."""
    # One dash too many: nothing on the line says what the third number is.
    assert reference.parse("0-8,5-20,5 мкмоль/л") is None
    # A unit printed in front of its range carries numbers of its own and is not a second band.
    assert reference.parse("х10^9/л 4,0-9,0") == (4.0, 9.0)
    assert reference.parse("10⁹/л 4,0-9,0") == (4.0, 9.0)
    # One band with its unit, which is this shape with its other half missing.
    assert reference.parse("47 – 72 %") == (47.0, 72.0)
    assert reference.parse("2,000 – 5,500*10⁹/л") == (2.0, 5.5)
    # A single band is the band of the value beside it, so it answers whichever unit asks: the
    # unit settles one question only, which of several bands, and there is only one here.
    assert reference.parse("47 – 72 %", "10⁹/л") == (47.0, 72.0)
    assert reference.parse("3,5-5,5 ммоль/л", "мг/дл") == (3.5, 5.5)
    # A table of what a result would mean is not two bands either.
    assert reference.parse("< 20 Normal, 20 - 200 High") is None


def _a_blood_count(unit: str | None, *values: float) -> list[dict]:
    """Rows of one test, all of them printed beside the line that holds both bands."""
    return [{"material": "blood", "date": f"20{10 + year:02d}-01-15", "value": str(value),
             "value_numeric": value, "unit": unit, "reference": BOTH_BANDS}
            for year, value in enumerate(values)]  # fmt: skip


def test_the_band_drawn_is_the_one_printed_in_the_unit_of_the_chart():
    """One line, two charts, and each of them draws the band the form printed for it.

    The chart's own unit is the only thing on either side that says which band belongs to the
    value, so it travels with the row. Drawn without it, the absolute chart carried the per-cent
    corridor — a band from 47 to 72 over values between two and five, which sets the top of the
    axis and lays a history flat along the bottom.
    """
    drawn = charts([*_a_blood_count("%", 54.0, 68.0, 72.0),
                    *_a_blood_count("х10⁹/л", 2.4, 3.1, 5.9)])  # fmt: skip
    by_unit = {chart["unit"]: chart for chart in drawn}
    assert set(by_unit) == {"%", "х10⁹/л"}
    assert all(_band_of(row) == (47.0, 72.0) for row in by_unit["%"]["rows"])
    assert all(_band_of(row) == (2.0, 5.5) for row in by_unit["х10⁹/л"]["rows"])
    # And the page can say what was done: the program chose one of two printed bands, so every
    # row drawn that way is marked, and series.html prints the mark beside the printed text.
    assert all(row["band_by_its_unit"] for chart in drawn for row in chart["rows"])


def test_a_row_on_a_chart_of_another_scale_altogether_gets_no_band_and_no_mark():
    """The mark says a band was chosen, so it is not written where none was.

    A line naming per cent and 10⁹/л printed nothing for a chart drawn in grams per litre, and
    the row there carries no band at all rather than the first half of somebody else's.
    """
    drawn = charts(_a_blood_count("г/л", 3.9, 4.4))
    assert [chart["unit"] for chart in drawn] == ["г/л"]
    assert all(_band_of(row) is None for row in drawn[0]["rows"])
    assert not any(row.get("band_by_its_unit") for row in drawn[0]["rows"])


def test_values_with_no_unit_are_not_placed_by_half_of_a_two_band_line():
    """The defect that brought this about, in the shape the archive prints it in.

    Old forms print a leukocyte formula with no unit column: per-cent values with nothing beside
    them but, on one of the forms, a line holding both bands. Read as one range, "47 – 72" was
    handed to the rule that prefers a printed range to its own arithmetic; it fits neither scale
    in front of it — the per-cent readings of this test start at 21, which is below the floor
    even loosened — so the rule fell silent and every one of those values stood off its own chart
    in a series of its own with no unit at all.

    The line printed one band for each of two scales, both of them fit their own scale's numbers
    because one laboratory printed both, and so nothing there says which scale these values are
    on. Told that, the rule reaches its reading of the readings nearest in time, and they place
    them — which is what it does for every other unitless leukocyte formula in the archive.
    """
    named = [(2000, 21.0), (2011, 53.0), (2013, 56.0), (2015, 62.0), (2017, 65.0), (2019, 68.0), (2021, 72.0)]
    per_cent = [{"material": "blood", "date": f"{year}-01-01", "value": str(value),
                 "value_numeric": value, "unit": "%", "reference": "47 – 72 %"}
                for year, value in named]  # fmt: skip
    bare = [{"material": "blood", "date": f"{year}-06-01", "value": str(value),
             "value_numeric": value, "unit": None, "reference": None}
            for year, value in [(2011, 46.0), (2012, 50.0), (2014, 55.0), (2016, 65.0), (2018, 68.0), (2020, 76.0)]]  # fmt: skip
    bare += [{"material": "blood", "date": "2020-01-15", "value": "72", "value_numeric": 72.0,
              "unit": None, "reference": BOTH_BANDS}]  # fmt: skip

    drawn = charts([*bare, *per_cent], placing=[*FROM_RANGE, *BY_NUMBERS])

    assert [chart["unit"] for chart in drawn] == ["%"]
    assert drawn[0]["count"] == 14 and drawn[0]["by_numbers"] == 7
    # The one row of the seven whose form printed the line keeps the per-cent band, because the
    # chart it was put on is drawn in per cent.
    bands = [_band_of(row) for row in drawn[0]["rows"] if row["reference"] == BOTH_BANDS]
    assert bands == [(47.0, 72.0)]


def test_the_one_door_that_compares_a_number_with_its_range_asks_in_the_unit_printed():
    """The third answer mode compares a number with the band its own unit names, or not at all.

    Against the per-cent half, an absolute count of 2,4 was reported as below a floor of 47 — a
    verdict about the notation and not about the value. With the unit in hand it is compared with
    the band the form printed for it, and with no unit printed there is no comparison to make.
    """
    assert reference.outside(2.4, BOTH_BANDS, None, "х10⁹/л") is False
    assert reference.outside(6.0, BOTH_BANDS, None, "х10⁹/л") is True
    assert reference.outside(1.4, BOTH_BANDS, None, "10⁹/л") is True
    assert reference.outside(68.0, BOTH_BANDS, None, "%") is False
    assert reference.outside(80.0, BOTH_BANDS, None, "%") is True
    # No unit printed, so which band stands beside the value is not known and nothing is said.
    assert reference.outside(68.0, BOTH_BANDS) is None
    # And a unit the line never named is not compared with either of its bands.
    assert reference.outside(68.0, BOTH_BANDS, None, "г/л") is None


def test_the_page_that_compares_with_printed_ranges_hands_over_the_printed_unit(setup):  # noqa: F811
    """The wiring, not the arithmetic: the unit of the row reaches reference.outside.

    Without it the count of values compared against their printed ranges put every value beside
    such a line into range_not_read, although the form had labelled the band for it — and before
    that it compared them with whichever band came first.
    """
    from epicrisis import query
    from epicrisis.corrections import set_document_date
    from epicrisis.extract.run import extract_source, load_extracted, write_document
    from epicrisis.validate import validate_source

    data_dir, source, output, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    labs = records["labs.pdf"]["sha256"]
    document = load_extracted(output / "extracted", labs)["documents"][0]
    template = document["observations"][0]
    document["observations"] = [
        dict(template, name_as_printed="Нейтрофили", value_as_printed="2,4", value_numeric=2.4,
             unit_as_printed="х10⁹/л", reference_as_printed=BOTH_BANDS, value_role="result"),
        dict(template, name_as_printed="Нейтрофили %", value_as_printed="80", value_numeric=80.0,
             unit_as_printed="%", reference_as_printed=BOTH_BANDS, value_role="result"),
    ]
    document["page_texts"] = [{"page": 1, "text": f"Нейтрофили 2,4 х10⁹/л {BOTH_BANDS}"}]
    write_document(output / "extracted", labs, document)
    set_document_date(output, labs, [1, 2], A_DAY_FOR_AN_ILLUSTRATION)
    validate_source(output)
    build_index(data_dir, [source])

    with open_index(data_dir, None) as connection:
        rows, counts, _how_many = query.flagged_values(
            connection, compare_with_printed_range=True,
            placing=rules_on(data_dir, rules.load(data_dir), "charts"))  # fmt: skip

    said = {row["value"]: row.get("outside_printed_range") for row in rows
            if row["reference"] == BOTH_BANDS}  # fmt: skip
    # 2,4 sits inside 2,000 – 5,500 and 80 sits above 47 – 72, each against the band its own unit
    # names; neither of them is a value this program could not read.
    assert said == {"80": True}
    # And neither of the two is a value this program could not read: every line of this document
    # was compared with a band of its own unit.
    assert counts["range_not_read"] == 0
