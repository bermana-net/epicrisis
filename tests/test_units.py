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


def test_a_power_of_ten_printed_inside_its_own_range_is_read_from_it():
    """A blood count printed "0,01-0,08 x10 9 /л", with no unit column anywhere on the line.

    The fold has read that spelling for as long as it has read anything — it is the commonest unit
    of a blood count, and forms write it five ways — and the reader of printed ranges could not
    read it at all. So a value whose form names its unit only inside its own range was drawn with
    no scale named beside it, next to the chart it belongs to, and the key the line gives,
    "10^9/l", is exactly that chart's key. Reading it is reading the page, which the second entry
    of the constitution allows in those words.
    """
    from epicrisis.units import unit_from_reference, unit_key

    assert unit_key("x10 9 /л") == "10^9/l"
    for printed in ("0,01-0,08 x10 9 /л", "0,01-0,08 x10^9/л", "0,01-0,08 10^9/л",
                    "0,01-0,08 10⁹/л", "0,01-0,08 ·10⁹/л", "0,01-0,08 x10 9 /л.",
                    "4,0-9,0 x10 9 /л (норма)"):  # fmt: skip
        assert unit_from_reference(printed) == "10^9/l", printed
    assert unit_from_reference("4,0-5,0 x10 12 /л") == "10^12/l"
    assert unit_from_reference("3,5-5,5 x10³/µL") == "10^3/ul"
    assert unit_from_reference("до 2,0·10⁶/л") == "10^6/l"

    # A range that names no unit names none still, and a number that is not a power of ten is not
    # one: specific gravity is printed "1010 - 1030" and must not come out as a count of cells.
    for printed in ("1005 - 1035", "[ 1010 - 1030 ]", "4 - 5", "0,67 - 1,17", "не виявлено", "до 100/мкл"):
        assert unit_from_reference(printed) is None, printed

    # A line holding two ranges says two things — the relative count in per cent and the absolute
    # count after it — and which of them the value belongs to is written nowhere, so the power
    # standing plainly in it is not read.
    assert unit_from_reference("19 – 37 % 1,200 – 3,000*10⁹/л") is None

    # And the chart, which is what this is for: a laboratory that prints a unit column and one
    # that prints the unit inside the range are one history of one test.
    printed = [{"date": "2019-05-01", "unit": "10⁹/л", "value": "4,2", "value_numeric": 4.2,
                "name": "Лейкоцити", "reference": "4,0-9,0"},
               {"date": "2021-05-01", "unit": None, "value": "5,1", "value_numeric": 5.1,
                "name": "Лейкоцити", "reference": "4,0-9,0 x10 9 /л"}]  # fmt: skip
    assert len(charts(printed, indicator="leukocyte", placing=TO_SCALE[:1])) == 1


def test_a_count_per_millilitre_in_a_range_is_left_where_its_numbers_put_it():
    """"до 1000/мл" is the same measure as "10⁶/л", and reading it literally would split a chart.

    A thousand per millilitre and a million per litre are one measure written at two scales, and
    one laboratory here prints both in one range. Read as a unit of its own the value would be
    taken off the chart of seven it is drawn on and given a chart of its own, because nothing in
    this fold converts anything — so the honest answer is to read only a power of ten written as a
    power, and leave this one to the rule that places a value by its own numbers.
    """
    from epicrisis.units import unit_from_reference

    assert unit_from_reference("до 1000/мл") is None
    # And where the same range writes the power out as well, the power is what is read.
    assert unit_from_reference("до 1000/мл 10⁶/л") == "10^6/l"


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


def test_a_prefix_in_front_of_a_word_of_units_is_read_whole():
    """"мкМЕ/мл" and "µIU/mL" are one unit, and they came to two keys.

    The table of words is read longest first, and that is no cure where one word begins another.
    "мкм" stands in it in its own right, so it was taken out of the middle of "мкМЕ" — the
    spelling thyrotropin and insulin are printed in on Russian and Ukrainian forms — and the key
    came out "umolе/ml": half translated, in two alphabets, a chart of its own beside the English
    one for the same test in the same unit. "мМЕ/л" went the same way through "мм", and the
    kilogramme stood in no list at all, so "мг/кг" folded to "mg/кg".

    No archive here prints these yet, which is the reason for inventing them: a form printed in
    another town next year is not a rare case. What the archives do print and this moves is three
    spellings of the kilogramme and three of the international unit, named in the commit.
    """
    from epicrisis.units import unit_key

    same = [("мкМЕ/мл", "µIU/mL"), ("мкМО/мл", "µIU/mL"), ("мМЕ/л", "mIU/L"), ("мМО/л", "mIU/L"),
            ("мкОд/мл", "µU/mL"), ("мкЕд/мл", "µU/mL"), ("мЕд/л", "mU/L"), ("мОд/л", "mU/L"),
            ("мг/кг", "mg/kg"), ("мкг/кг/хв", "ug/kg/min"), ("кг", "kg")]  # fmt: skip
    for cyrillic, latin in same:
        assert unit_key(cyrillic) == unit_key(latin), f"{cyrillic} and {latin}"

    # And the key of a unit this program knows is written in one alphabet, not in two.
    for printed, _ in same:
        assert not any("Ѐ" <= letter <= "ӿ" for letter in unit_key(printed)), printed

    # The words the prefixes were taken out of still read as themselves: an international unit is
    # not a mole, and neither of them may borrow the other's key.
    assert unit_key("мкмоль/л") == unit_key("мкМоль/л") == unit_key("мкМ/л") == "umol/l"
    assert unit_key("ммоль/л") == unit_key("мМоль/л") == unit_key("мМ/л") == "mmol/l"
    # The international unit and the plain one do share a key, and the prefix shares it with them.
    # They are the same measure — the reader of printed ranges in units.py has read "iu/l" as
    # "u/l" since it was written — and the two halves of that file disagreeing is what drew one
    # test as two charts in what the forms call one unit.
    assert unit_key("МЕ/мл") == unit_key("ед/мл") == "u/ml" and unit_key("Од/л") == "u/l"
    assert len({unit_key(spelling) for spelling in ("мкМЕ/мл", "мкЕд/мл", "мкмоль/л")}) == 2

    # And the whole of the defect, which is a chart and not a key: one test printed in Cyrillic on
    # one form and in Latin on the next is one history, and this drew it as two. No archive here
    # holds such a form, so here is one.
    printed = [{"date": "2019-05-01", "unit": "мкМЕ/мл", "value": "1,2", "value_numeric": 1.2,
                "name": "Тиреотропний гормон"},
               {"date": "2021-05-01", "unit": "µIU/mL", "value": "1.4", "value_numeric": 1.4,
                "name": "Thyrotropin"}]  # fmt: skip
    assert len(charts(printed, indicator="thyrotropin")) == 1


def test_a_backslash_is_the_slash_it_was_meant_to_be():
    """Two charts of one test, in one unit, because a form printed the wrong one of two keys.

    Reported by the archive's owner: prostate-specific antigen stood on his page as two separate
    histories, "both of them in nanograms per millilitre, one in Cyrillic and one in Latin". The
    Cyrillic folded to Latin exactly as it should; what did not fold was the backslash. On a
    Cyrillic keyboard it shares a key with the slash, and a form had printed "нг\\мл".

    A backslash has no meaning inside a unit — there is nothing it could be but a mistyped slash —
    so it is read as one. Four values across three archives carried it, and they were enough to
    split two tests into four charts.
    """
    from epicrisis.units import unit_key

    assert unit_key("нг\\мл") == unit_key("ng/mL") == "ng/ml"
    assert unit_key("мМ\\л") == unit_key("ммоль/л") == "mmol/l"
    assert unit_key("мг\\\\дл") == unit_key("mg/dL")
    # And nothing that was already right moves: the slash of a rate, the power of ten, the hour.
    assert unit_key("мл/хв/1,73 м²") == unit_key("ml/min/1.73 m2")
    assert unit_key("10^9/л") == "10^9/l" and unit_key("мг/24 год") == unit_key("mg/24 h")
    # And the capital letter two lines below is read through the backslash too. This is here
    # because the fix was first written with the fold running after the prefixes, which left
    # "Г\\л" meeting none of them and coming out as plain grams per litre — the one pair in this
    # file that is a thousand million times apart, now sharing an axis. A wrong key draws a chart
    # nobody recognises; a key that is quietly another unit draws one that looks right.
    assert unit_key("Г\\л") == unit_key("Г/л") == "10^9/l"
    assert unit_key("G\\L") == unit_key("G/L") == "10^9/l"
    assert unit_key("Т\\л") == unit_key("Т/л") == "10^12/l"
    assert unit_key("г\\л") == unit_key("г/л") == "g/l"  # and the small letter stays grams


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


def test_the_capital_is_read_in_whichever_alphabet_each_letter_is_printed_in():
    """"Г/L" and "G/л" are a count of cells, and both came out as grams per litre.

    The table held the two tidy pairs — a Cyrillic measure with a Cyrillic litre, a Latin one with
    a Latin litre — and a form that mixes the alphabets is not a rare case: `eyes.py` keeps its own
    list of both alphabets and the mixtures for the same reason, because "OD" and "ОД" are the same
    two shapes on paper and a reading comes back with a Cyrillic letter in front of a Latin one and
    nobody can see it. So "Г/L" met no pair at all, fell through to the fold, and a count of cells
    stood on the scale of the proteins, a thousand million times away from itself. "Г/Л" in
    capitals fell the same way — and the reader of printed ranges read that one correctly, which is
    the other half of this: two tables of one piece of knowledge, disagreeing in silence. There is
    one table now, and both readers read it.
    """
    from epicrisis.units import unit_from_reference, unit_key

    for measure, key in (("Г", "10^9/l"), ("G", "10^9/l"), ("Т", "10^12/l"), ("T", "10^12/l")):
        for litre in "лЛlL":
            assert unit_key(f"{measure}/{litre}") == key, f"{measure}/{litre}"
            assert unit_key(f"{measure}\\{litre}") == key, f"{measure} through a backslash"
            assert unit_from_reference(f"4,0-9,0 {measure}/{litre}") == key, f"{measure}/{litre} in a range"

    # The small letter is grams, in either alphabet and whichever case the litre is printed in.
    for measure in "гg":
        for litre in "лЛlL":
            assert unit_key(f"{measure}/{litre}") == "g/l", f"{measure}/{litre}"
    assert unit_from_reference("60 - 80 г/л") == unit_from_reference("3,5-5,5 g/l") == "g/l"

    # And the capital is the unit only where it is the whole unit, in both readers.
    assert unit_key("МГ/Л") == "mg/l" and unit_from_reference("10,0-25,0 МГ/Л") == "mg/l"
    assert unit_key("МКГ/Л") == "ug/l" and unit_from_reference("3 - 8 МКГ/Л") == "ug/l"
    assert unit_key("мкГ/л") == "ug/l" and unit_from_reference("0,5-2,0 MG/L") == "mg/l"


def test_a_backslash_in_a_printed_range_is_the_slash_it_was_meant_to_be():
    """"One place to add a unit", says this file, and the backslash was read in one of the two.

    `unit_key` folds a run of backslashes to the slash it was mistyped for — on a Cyrillic keyboard
    the two share a key — and the reader of printed ranges did not, so a value whose form printed
    no unit column and a range of "1,5-5,0 нг\мл" was given no unit from anywhere and drew a chart
    with no scale named on it. Four values across three archives carry a backslash in a unit
    column and none carries one in a range, so every range below is invented, which is the point
    of inventing them.
    """
    from epicrisis.units import unit_from_reference

    assert unit_from_reference("1,5-5,0 нг\\мл") == unit_from_reference("1,5-5,0 нг/мл") == "ng/ml"
    assert unit_from_reference("53-115 мкмоль\\л") == "umol/l"
    # And the capital letter is read through the backslash, which is the order that matters: with
    # the fold running first, "Г\л" meets no capital and comes out as plain grams per litre — the
    # one pair in this file that is a thousand million times apart, sharing an axis in silence.
    assert unit_from_reference("180,0-320,0 Г\\л") == "10^9/l"
    assert unit_from_reference("60 - 80 г\\л") == "g/l"
    assert unit_from_reference("4,0-5,0 Т\\л") == "10^12/l"
    # A range that says nothing says nothing still: a backslash is not a unit by itself.
    assert unit_from_reference("0,67 - 1,17") is None and unit_from_reference("не виявлено") is None


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


def test_the_spanish_words_of_a_unit_are_read_as_the_other_languages_are():
    """"lpm" is a pulse, and it was a chart of its own beside the nine spellings already folded.

    Spanish is one of the five languages these forms are printed in, and it stood in the table of
    words only where a word happens to be spelt the same in Latin letters. So the forms that write
    the word out were half translated — "mm/hora" beside "мм/год", "seg" beside "сек", "gramos"
    beside "г", "UI/L" beside "U/L" — which is the failure the paragraph above that table
    describes, in the one language nobody had read it in.

    Measured on the archives here: 11 printed spellings carrying 48 values moved, 12 charts of 9
    tests became one each, and no value changed its number, its printed unit or its band.
    """
    from epicrisis.units import unit_key

    same = [("lpm", "bpm"), ("latidos por minuto", "в 1 минуту"), ("lat./min", "уд./мин"),
            ("por minuto", "/хв"), ("mm/hora", "мм/год"), ("ng/mL/hora", "ng/mL/h"),
            ("seg", "сек"), ("milisegundos", "ms"), ("gramos", "г"), ("miligramos/dL", "mg/dL"),
            ("microgramos/L", "µg/L"), ("kilogramos", "кг"), ("UI/L", "U/L"),
            ("UI/mL", "МЕ/мл"), ("microUI/mL", "мкМЕ/мл"), ("UFC/mL", "cfu/mL")]  # fmt: skip
    for spanish, elsewhere in same:
        assert unit_key(spanish) == unit_key(elsewhere), f"{spanish} and {elsewhere}"

    # And the key of a unit this program knows is written in one alphabet, not in two.
    for spanish, _ in same:
        assert not any("Ѐ" <= letter <= "ӿ" for letter in unit_key(spanish)), spanish

    # The prefixed spellings stand in the table themselves rather than as a prefix and a word: a
    # table entry is replaced wherever it stands, so "mili" standing for the prefix would read
    # "milimetros" as "mmetros" — the mixed key all of this exists to prevent, made by the cure.
    assert unit_key("milisegundos") == "ms" and unit_key("miligramos") == "mg"
    assert unit_key("microgramos") == "ug" and unit_key("picogramos/mL") == "pg/ml"

    # Units that are not the same must not become the same. The minute alone is a length of time
    # and not a rate, in Spanish as in the other four.
    assert unit_key("minutos") == unit_key("мин") == "min" != unit_key("lpm")
    assert unit_key("gramos") != unit_key("miligramos") != unit_key("microgramos")

    # Three readings of this archive that are left exactly where they are, each for its own
    # reason. "mm" is a length even where a sedimentation rate printed it: 48 values of these
    # archives are printed in "mm" and 44 of them are lengths, so reading it as a rate is a claim
    # about what a form meant, which belongs to a rule that places and says so on the page.
    # "mmHg/h" is a misreading of one, and a rule already marks it for a person to look at.
    # "años" is a year, and there is no year in this table in any language to fold it with.
    assert unit_key("mm") == "mm" != unit_key("mm/hora")
    assert unit_key("mmHg/h") == "mmhg/h" != unit_key("мм/год")
    assert unit_key("años") == "años"

    # And the whole of the defect, which is a chart and not a key: one pulse printed in Spanish on
    # one form and in Russian on the next is one history, and this drew it as two.
    printed = [{"date": "2019-05-01", "unit": "lpm", "value": "75", "value_numeric": 75.0,
                "name": "Zhabborin por minuto"},
               {"date": "2021-05-01", "unit": "в 1 минуту", "value": "74", "value_numeric": 74.0,
                "name": "Жабборин в минуту"}]  # fmt: skip
    assert len(charts(printed, indicator="pulse")) == 1
