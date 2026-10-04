"""A value quoted from another study, and the printed range that is not a date.

Every line here is invented. They are built to the shapes the forms of these archives really use —
a note retelling an earlier result, a printout with dotted leaders, a range in brackets — with
numbers that belong to nobody.
"""

from datetime import date

import pytest

from epicrisis.quotations import quoted_date


@pytest.mark.parametrize(("line", "document", "measured"), [
    # A doctor retelling an earlier result, which is what a consultation is largely made of.
    ("ТТГ  9.99  від 11.02.15 р. на дозі 50 мкг.", date(2019, 7, 1), date(2015, 2, 11)),
    ("Холестерин заг 07.06.14р.-9.1  (3,6-6,2 мМ/л)", date(2019, 9, 13), date(2014, 6, 7)),
    ("PSA 9,99 ng/ml від 08.08.2018", date(2019, 11, 5), date(2018, 8, 8)),
    ("PSA (03.03.2017) 8,88 ng/ml", date(2019, 11, 5), date(2017, 3, 3)),
    # The date in front of the test, introduced by nothing but the writer's hurry.
    ("09.09.2011 Глікозильований гемоглоб.9.9  (4,0-6,0)", date(2019, 1, 9), date(2011, 9, 9)),
    # A month and a year is all a note often gives, and sometimes it names the laboratory too.
    ("ПСА-9,99 (07.2014)", date(2019, 1, 14), date(2014, 7, 1)),
    ("ПСА-9,99 нг/мл (07.2014: Invented Medical Lab)", date(2019, 1, 14), date(2014, 7, 1)),
    ("УЗО амбулаторно від 05.2013 - простата 99см3", date(2016, 2, 26), date(2013, 5, 1)),
])  # fmt: skip
def test_a_line_that_says_when_it_was_measured(line, document, measured):
    """The date is in the value's own line because the sentence means nothing without it."""
    assert quoted_date(line, document) == measured


@pytest.mark.parametrize("line", [
    # The whole reason this module is careful. A printed range is two numbers with a dash between
    # them and dots inside them, and to a careless reader "7.77-9.99" is the seventh of July 1999.
    # A careless reader found eight of these on one archive, every one of them a real laboratory
    # value it would then have moved years from where it was measured, or hidden altogether.
    "Глюкоза 8.88 7.77-9.99 ммоль/л",
    "Нейтрофіли (абс.) 9.99 1.11-9.99 x10 9 /л",
    "Cistatina C (S) Cys C 0.999 mg/L 0.11-1.99",
    "* 99999-9   Cystatin C 9.9 mg/L 0.99-1.99 mg/L  18 - 60 y.o.",
    "Сечовина.................9.9  (1.11-9.99 мМоль/л)",
    "низький нормальний 1.11-9.99 високий 9.99 ммоль/л",
    # A formula of several numbers over slashes, which is not a date however it is cut.
    "B:99/9/1/99/ 99  Z9A",
    # A number that happens to have the shape of a month and a year, with nobody putting it there.
    "Коефіцієнт 1.2024 умовних одиниць",
])  # fmt: skip
def test_a_printed_range_is_never_a_date(line):
    assert quoted_date(line, date(2021, 7, 6)) is None


@pytest.mark.parametrize("line", [
    # A printed range with a word of its own in front of it, inside brackets of its own — so the
    # brackets say nothing and the word says nothing, and all that is left to tell a range from a
    # date is the dash. Three languages of the five print the label, and every one of them put a
    # ferritin twenty-one years from where it was measured.
    "Феритин 23 нг/мл (норма 4-2000)",
    "Ferritina 23 ng/ml (ref. 4-2000)",
    "Φερριτίνη 23 ng/ml (τιμές 4-2000)",
    # The same range opening the line, where there is no word in front of it at all.
    "4-2000 нг/мл феритин 23",
    # And the same range behind a word that really does introduce dates everywhere else.
    "IgE от 5-2015 МЕ/мл",
])  # fmt: skip
def test_a_dash_between_two_numbers_is_a_range_and_never_a_month(line):
    """A month and a year are printed with a dot or a slash; a range is printed with a dash.

    Every other mark of a date is present in these five lines — brackets of its own, the start of
    the line, a word that introduces one — so the separator is the whole of the difference, and
    the module asks nothing else of them.
    """
    assert quoted_date(line, date(2021, 7, 6)) is None


@pytest.mark.parametrize("line", [
    "по 1 таблетці 3 рази на день 5-7-10 днів",   # a course of treatment
    "Еналаприл 5/10/20 мг",                        # the doses a tablet comes in
    "Епітелій 2-3-19 в полі зору",                 # a count in a field of view
    "Vis 6/9/18",                                  # a line of visual acuities
    "2.1.19 Загальні показники",                   # a numbered heading
    "аналізатор версія v5.2.19",                   # the version a device prints
])  # fmt: skip
def test_three_small_numbers_over_one_separator_are_not_always_a_date(line):
    """The second half of the one thing this module must never do, and it had been left open.

    A range was guarded against from the first line of this file; a triple was taken to be beyond
    doubt — "three parts with one separator cannot be anything else". These six are all three
    parts over one separator and none of them is a date, and every one of them was read as one and
    would have carried a value years from where it was measured.
    """
    assert quoted_date(line, date(2021, 7, 6)) is None


def test_a_date_with_a_short_year_is_printed_in_two_digits_throughout():
    """What tells the six lines above from a real quotation: a form pads a shortened date.

    Every quotation measured on these archives is printed that way, and with the year written in
    full the triple is unmistakable, so nothing is asked of the other two parts.
    """
    assert quoted_date("ТТГ 9.99 від 11.02.15 р.", date(2019, 7, 1)) == date(2015, 2, 11)
    assert quoted_date("ТТГ 9.99 від 11.2.15 р.", date(2019, 7, 1)) is None
    assert quoted_date("ТТГ 9.99 від 1.02.15 р.", date(2019, 7, 1)) is None
    assert quoted_date("ТТГ 9.99 від 1.2.2015 р.", date(2019, 7, 1)) == date(2015, 2, 1)


def test_a_triple_that_can_only_be_month_first_needs_a_word_in_front_of_it():
    """Day first is the habit of all five languages here; month first is the habit of none.

    So a triple whose second number is above twelve is the weaker evidence of the two and takes
    the word a bare month and year takes. Without the word the narrowing above is undone from the
    other side: a list of doses whose second number happens to be above twelve becomes a day.
    """
    assert quoted_date("TSH 4.12 from 3/15/2019", date(2021, 7, 6)) == date(2019, 3, 15)
    assert quoted_date("Еналаприл 10/20/19 мг", date(2021, 7, 6)) is None
    # And where both numbers could be either, it stays day first and nothing is guessed.
    assert quoted_date("TSH 4.12 from 09/07/2011", date(2021, 7, 6)) == date(2011, 7, 9)


def test_the_document_s_own_day_is_not_a_quotation():
    """A form prints its own date in its own lines, and that is the date it already has."""
    assert quoted_date("Зразок взято 03.03.2026, ТТГ 9.99", date(2026, 3, 3)) is None
    # A form printed on the fifth and signed on the twelfth is one visit, not two studies.
    assert quoted_date("взято 05.03.2026", date(2026, 3, 12)) is None


def test_nothing_impossible_is_read_as_a_date():
    """Both ends matter: a range read as a date lands outside them far oftener than inside."""
    assert quoted_date("щось 11.11.1899 щось", date(2020, 1, 1)) is None  # before any archive
    # A form cannot quote a study done after it was printed. Without this, a serial number on a
    # 2015 form reads as a visit in 2031 and the chart grows a point in the future.
    assert quoted_date("направлення 01.01.2031", date(2015, 1, 1)) is None
    assert quoted_date("щось 45.13.2015 щось", date(2020, 1, 1)) is None  # no such day


def test_a_date_needs_one_separator_and_not_two():
    """The one thing that tells a date from a range, written down as a test so it is not lost.

    "11.02.15" is a date; "1.11-9.99" is a range. Both are two digits, a separator, two digits, a
    separator, two digits. The difference is that a date's two separators are the same character.
    """
    assert quoted_date("щось 11.02.15 щось", date(2020, 1, 1)) == date(2015, 2, 11)
    assert quoted_date("щось 11/02/15 щось", date(2020, 1, 1)) == date(2015, 2, 11)
    assert quoted_date("щось 11.02-15 щось", date(2020, 1, 1)) is None
    assert quoted_date("щось 11-02.15 щось", date(2020, 1, 1)) is None


@pytest.mark.parametrize(("line", "measured"), [
    # Greek, which could not work at all: casefold turns the final ς of "στις" into σ, so the
    # literal in the list could never meet the word in the text, and Greek was the one language of
    # the five with no word that introduces a month. The same spelling in capitals, as a form
    # headed in capitals prints it, has to meet it too.
    ("ΤΣΗ 4.12 στις 12.2019", date(2019, 12, 1)),
    ("ΤΣΗ 4.12 ΣΤΙΣ 12.2019", date(2019, 12, 1)),
    # A label and its colon. Every label a form prints ends in one, and the word in front of it
    # was compared with nothing: the split left an empty piece and the empty piece was matched.
    ("Дата: 12.2019 ТТГ 4.12", date(2019, 12, 1)),
    # Russian "с" is the same word as Ukrainian "з", which has been in the list from the start.
    ("ТТГ 4.12 с 12.2019", date(2019, 12, 1)),
])  # fmt: skip
def test_a_word_that_introduces_a_month_is_found_in_every_language(line, measured):
    assert quoted_date(line, date(2021, 7, 6)) == measured


def test_a_label_that_is_not_about_the_date_still_introduces_nothing():
    """The fix above must not turn every word in front of a number into an introduction.

    "Дата народження" ends in a colon as well, and the date behind it is a whole life away from
    the document — the one date that must never be read as a study.
    """
    assert quoted_date("Дата народження: 12.1975 ТТГ 4.12", date(2021, 7, 6)) is None
    # A plausible year, so that what refuses this is the word in front of it and not the far end
    # of the range of years a date is allowed to land in.
    assert quoted_date("Коефіцієнт норма 1.2019 умовних одиниць", date(2021, 7, 6)) is None


@pytest.mark.parametrize(("line", "measured"), [
    ("ТТГ 4.12 від 19 січня 2019 р.", date(2019, 1, 19)),
    ("TSH 4.12 from Jan 19, 2019", date(2019, 1, 19)),
    ("TSH 4.12, 10-NOV-2019", date(2019, 11, 10)),        # how a laboratory system prints it
    ("TSH 4,12 de 19 de enero de 2019", date(2019, 1, 19)),
    ("ΤΣΗ 4.12 στις 19 Ιανουαρίου 2019", date(2019, 1, 19)),
    ("ТТГ 4.12 з 19.ІХ.2019", date(2019, 9, 19)),          # the month in Roman numerals
    ("ΤΣΗ 4.12 στις 8 ΜΑΪΟΥ 2019", date(2019, 5, 8)),      # a form headed in capitals
    # A day and a month and a year is three parts, so it stands on its own like a numeric triple.
    ("ТТГ 4.12 19 січня 2019 р.", date(2019, 1, 19)),
])  # fmt: skip
def test_a_month_written_as_a_word_is_a_date_in_every_one_of_the_five_languages(line, measured):
    """Not one month's name in any of the five languages was read: both patterns were digits only.

    Read by dates.py, which is the program's one reader of month names and already holds the five
    languages, the case each declines the month into, the abbreviations a laboratory prints and
    the Roman numerals an old form types with Cyrillic letters. A second reader written here would
    need every correction that one has had, separately, and would not get them.
    """
    assert quoted_date(line, date(2021, 7, 6)) == measured


@pytest.mark.parametrize("line", [
    # The reason the reader above cannot simply be trusted on a sentence. A Roman month is one or
    # two letters, and "х" is the multiplication sign of every blood count printed here: read as a
    # date, "5 х 10" is the fifth of October 2010. The shape really is found — dates.py answers
    # with it — and the only thing refusing it is that a date in Roman numerals is printed tight.
    "Лейкоцити 5 х 10 9/л",
    "Лейкоцити 5.5 х 10 9/л",
    "Еритроцити 4,5 х 1012/л",
    "WBC 9.9 x 10 9/L",
    # A month's name with no day beside it is two parts, so it wants the word or the brackets that
    # a numeric month and year wants. Nobody put this one there.
    "Феритин 23 нг/мл march 2019",
])  # fmt: skip
def test_what_the_reader_of_month_names_finds_is_not_taken_on_trust(line):
    assert quoted_date(line, date(2021, 7, 6)) is None


def test_a_month_s_name_behind_a_word_that_introduces_it_is_read():
    """The other side of the gate above: introduced, two parts are enough, exactly as for digits."""
    assert quoted_date("ТТГ 4.12 від січня 2019", date(2021, 7, 6)) == date(2019, 1, 1)
    assert quoted_date("ТТГ 4.12 (січня 2019)", date(2021, 7, 6)) == date(2019, 1, 1)


def test_nothing_at_all_is_not_a_quotation():
    assert quoted_date(None, date(2020, 1, 1)) is None
    assert quoted_date("", date(2020, 1, 1)) is None
    # A value whose document has no date of its own cannot be compared with one, so it is left be.
    assert quoted_date("ТТГ 9.99 від 11.02.15 р.", None) is None


# How a chart behaves with the rule on. Loaded as it ships, so the test fails if the rule file and
# the kind ever stop agreeing with each other.
from epicrisis import rules  # noqa: E402
from epicrisis.series import charts  # noqa: E402

QUOTING = [rules.load().get("value_quoted_from_another_study")]


def a_value(number, document_day, line, unit="", name="Thyrotropin"):
    """One row as the index hands it to a chart. Invented throughout."""
    return {"name": name, "value": str(number), "value_numeric": number, "unit": unit,
            "indicator_id": "thyrotropin", "material": "blood", "date": document_day,
            "snippet": line, "kind": "quantitative", "value_role": "result"}  # fmt: skip


def test_a_quoted_value_is_drawn_on_the_day_its_own_line_prints():
    """Measured on a real archive: the middle quotation sat 308 days from where it was taken."""
    values = [a_value(2.1, "2019-01-10", "ТТГ 2.1"),
              a_value(9.9, "2021-03-03", "ТТГ  9.9  від 11.02.15 р. на дозі 50 мкг."),
              a_value(3.4, "2022-05-05", "ТТГ 3.4")]  # fmt: skip

    where_the_document_was = charts(values, indicator="thyrotropin")[0]
    assert [point["date"] for point in where_the_document_was["rows"]] == ["2019-01-10", "2021-03-03", "2022-05-05"]

    moved = charts(values, indicator="thyrotropin", placing=QUOTING)[0]
    assert [point["date"] for point in moved["rows"]] == ["2015-02-11", "2019-01-10", "2022-05-05"]
    quotation = next(row for row in moved["rows"] if row.get("quoted"))
    # And it says where it was quoted from, so the page can show both days rather than one.
    assert quotation["quoted_from"] == "2021-03-03"


def test_a_quotation_of_a_form_this_archive_holds_is_not_a_second_point():
    """Twenty-six of twenty-eight quotations on a real archive were a copy of a form already here.

    Drawn as well as the form, one measurement becomes two points sitting on top of each other,
    and the count over the chart says a history is longer than it is.
    """
    values = [a_value(9.9, "2015-02-11", "ТТГ.......9.9  (0,23 - 4,2)"),          # the form itself
              a_value(9.9, "2021-03-03", "ТТГ  9.9  від 11.02.15 р."),            # a doctor quoting it
              a_value(3.4, "2022-05-05", "ТТГ 3.4")]  # fmt: skip

    drawn = charts(values, indicator="thyrotropin", placing=QUOTING)[0]

    assert drawn["count"] == 2  # the form and the later reading, not the retelling as well
    assert not any(row.get("quoted") for row in drawn["rows"])


def test_the_chart_says_how_many_retellings_it_folded_away():
    """The heading said 26 values and the chart said 25, and nothing on the page said why.

    Everything else this program does to a value, it says: a value moved to another scale, one
    placed by its own numbers, one printed beside the result, one whose unit came from a range —
    each has its own word on the page. Folding a retelling away was the only thing done silently,
    and it is the one that changes a count. The seventh entry: a count that differs from another
    count on the same page is a defect, not a detail.
    """
    values = [a_value(9.9, "2015-02-11", "ТТГ.......9.9  (0,23 - 4,2)"),   # the form itself
              a_value(9.9, "2021-03-03", "ТТГ  9.9  від 11.02.15 р."),     # one doctor quoting it
              a_value(9.9, "2022-04-04", "ТТГ  9.9  від 11.02.15 р."),     # and another
              a_value(3.4, "2022-05-05", "ТТГ 3.4")]  # fmt: skip

    drawn = charts(values, indicator="thyrotropin", placing=QUOTING)[0]

    assert drawn["count"] == 2  # the form and the later reading
    assert drawn["folded"] == 2  # and the page says where the other two went
    # Named on the row that stood in for them, so a reader looking at the one point knows it is
    # carrying three documents rather than one.
    stood_in = next(row for row in drawn["rows"] if row.get("folded_retellings"))
    assert stood_in["folded_retellings"] == 2
    assert stood_in["date"] == "2015-02-11"  # the form, not either of the consultations
    # And a chart that folded nothing says nothing: the word appears where it is true and nowhere
    # else, or it becomes the kind of notice nobody reads.
    plain = charts([a_value(3.4, "2022-05-05", "ТТГ 3.4"),
                    a_value(3.9, "2023-06-06", "ТТГ 3.9")], indicator="thyrotropin", placing=QUOTING)[0]  # fmt: skip
    assert plain["folded"] == 0


def test_a_retelling_kept_for_want_of_a_form_says_the_date_came_off_the_line():
    """The point moved by years, and the row it was drawn from carried no mark at all.

    A retelling whose form was never scanned is drawn on the day the line names, not on the day of
    the consultation — which is right, and is the whole reason the rule exists. But a value moved
    anywhere else on this page says so on its row, and this one said nothing, so the one case where
    a date was decided by reading a sentence looked exactly like a date off a form.
    """
    values = [a_value(9.9, "2021-03-03", "ТТГ  9.9  від 11.02.15 р."),
              a_value(3.4, "2022-05-05", "ТТГ 3.4")]  # fmt: skip

    drawn = charts(values, indicator="thyrotropin", placing=QUOTING)[0]

    kept = next(row for row in drawn["rows"] if row.get("quoted"))
    assert kept["date"] == "2015-02-11"  # the day the line names
    assert kept["quoted_from"] == "2021-03-03"  # and the day of the consultation, kept to say so
    assert drawn["folded"] == 0  # nothing was folded here: there was no form to fold it into


def test_a_quotation_of_a_form_nobody_scanned_is_kept():
    """Two of those twenty-eight were the only surviving record of a measurement.

    Dropping every quotation would lose them to tidiness: there is no form behind them to fall
    back on, and the doctor's line is all that is left of the day they were taken.
    """
    values = [a_value(9.9, "2021-03-03", "ТТГ  9.9  від 11.02.15 р."),
              a_value(3.4, "2022-05-05", "ТТГ 3.4")]  # fmt: skip

    drawn = charts(values, indicator="thyrotropin", placing=QUOTING)[0]

    assert drawn["count"] == 2
    kept = next(row for row in drawn["rows"] if row.get("quoted"))
    assert kept["date"] == "2015-02-11"


def test_a_quotation_of_another_test_is_not_a_copy_of_this_one():
    """The same number on the same day says nothing: two tests share a number all the time."""
    values = [a_value(9.9, "2015-02-11", "ТТГ.......9.9", name="Thyrotropin"),
              {**a_value(9.9, "2021-03-03", "Інше  9.9  від 11.02.15 р."), "indicator_id": "something-else"}]

    drawn = charts(values, indicator="thyrotropin", placing=QUOTING)

    assert sum(chart["count"] for chart in drawn) == 2


def test_two_doctors_quoting_one_measurement_draw_one_point():
    """Found by looking at a real chart rather than at a ruler, which saw nothing.

    A thyrotropin taken in January 2016 was retold in three later consultations and its own form
    was never scanned, so nothing folded any of them away — and the chart drew one reading as
    three points standing on one day. The form is preferred where there is one; where there is
    none, the first retelling is kept and the rest are the same sentence said again.
    """
    values = [a_value(9.9, "2016-03-03", "ТТГ  9.9  від 11.02.15 р."),
              a_value(9.9, "2016-07-27", "ТТГ  9.9  від 11.02.15 р."),
              a_value(9.9, "2018-01-31", "ТТГ  9.9  від 11.02.15 р."),
              a_value(3.4, "2022-05-05", "ТТГ 3.4")]  # fmt: skip

    drawn = charts(values, indicator="thyrotropin", placing=QUOTING)[0]

    assert drawn["count"] == 2
    kept = [row for row in drawn["rows"] if row.get("quoted")]
    assert len(kept) == 1 and kept[0]["date"] == "2015-02-11"


def test_a_retelling_that_names_no_specimen_is_the_same_measurement_and_the_one_that_names_it_is_kept():
    """Two doctors retelling one result, one of them writing the specimen and one of them silent.

    The folding runs before the charts are split by material, so which of the two is kept decides
    which chart the measurement lands on. It was an exact match on the specimen first, and that
    cost the owner the chart he complained about: two consultations retold one prostate antigen of
    December, one naming the specimen and the unit and one naming neither, and the silent one went
    to a chart of its own with no unit and no specimen beside the chart it belongs on.

    Silence is not another specimen, so the two fold; and the one that says more is the one kept,
    which is the half this needs to be measured. Kept the other way round, of three consultations
    quoting one thyrotropin the only one left was the one that named no specimen, it went to a
    chart of its own and the blood chart lost the reading altogether.
    """
    no_specimen = {**a_value(9.9, "2016-03-03", "ТТГ  9.9  від 11.02.15 р."), "material": None}
    values = [no_specimen,
              a_value(9.9, "2016-07-27", "ТТГ  9.9  від 11.02.15 р."),
              a_value(3.4, "2022-05-05", "ТТГ 3.4")]  # fmt: skip

    drawn = {chart["material"]: chart for chart in charts(values, indicator="thyrotropin", placing=QUOTING)}

    assert sorted(drawn) == ["blood"]  # one history, one chart, and it is the chart of the specimen
    assert [row["date"] for row in drawn["blood"]["rows"] if row.get("quoted")] == ["2015-02-11"]
    kept = next(row for row in drawn["blood"]["rows"] if row.get("quoted"))
    assert kept["material"] == "blood" and kept["folded_retellings"] == 1


def test_a_retelling_of_one_specimen_never_stands_in_for_a_retelling_of_another():
    """Blood is never joined to urine anywhere here; it must not be joined by the back door.

    Two specimens printed is a page having spoken about both of them, and nothing goes behind what
    it said. Only silence on one side folds, which is the test above.
    """
    urine = {**a_value(9.9, "2016-03-03", "ТТГ  9.9  від 11.02.15 р."), "material": "urine"}
    values = [urine,
              a_value(9.9, "2016-07-27", "ТТГ  9.9  від 11.02.15 р."),
              a_value(3.4, "2022-05-05", "ТТГ 3.4")]  # fmt: skip

    drawn = {chart["material"]: chart for chart in charts(values, indicator="thyrotropin", placing=QUOTING)}

    assert sorted(drawn) == ["blood", "urine"]
    assert [row["date"] for row in drawn["blood"]["rows"] if row.get("quoted")] == ["2015-02-11"]
    assert [row["date"] for row in drawn["urine"]["rows"] if row.get("quoted")] == ["2015-02-11"]


def test_a_form_in_another_unit_is_not_the_same_measurement():
    """Found by the QA round, hours after the folding shipped. Measured: adding one document in
    another unit destroyed a whole chart — two points became no chart at all.

    The same door was shut for the specimen and for the indicator on the day the folding was
    written, and left open for the unit, although the first paragraph of series.py says that values
    in different units never share a chart.
    """
    mine = [a_value(7.7, "2019-05-05", "ТТГ 7.7"), a_value(8.8, "2021-05-05", "ТТГ 8.8"),
            a_value(9.9, "2022-05-05", "ТТГ  9.9  від 11.02.15 р.")]  # fmt: skip
    for row in mine:
        row["unit"] = "mmol/L"

    other_scale = [*mine, {**a_value(9.9, "2015-02-11", "ТТГ 9.9"), "unit": "mg/dL"}]
    same_scale = [*mine, {**a_value(9.9, "2015-02-11", "ТТГ 9.9"), "unit": "mmol/L"}]

    assert len(charts(other_scale, indicator="thyrotropin", placing=QUOTING)[0]["points"]) == 3
    assert any(row.get("quoted") for row in charts(other_scale, indicator="thyrotropin", placing=QUOTING)[0]["rows"])
    # And where the form is on the scale the retelling names, it is still the same measurement.
    assert not any(row.get("quoted") for row in charts(same_scale, indicator="thyrotropin", placing=QUOTING)[0]["rows"])


def test_a_form_that_printed_no_unit_is_still_the_same_measurement():
    """The commonest shape of all, and the reason the rule above is not an exact match.

    A doctor retelling a result writes the unit out because his sentence needs it; the laboratory
    printout it came from puts it in a column heading nobody transcribed. On the archive this was
    written against, every prostate-antigen quotation carries a unit and every form holding the
    same number carries none — an exact match would have folded none of them.
    """
    mine = [{**a_value(7.7, "2019-05-05", "ТТГ 7.7"), "unit": "mmol/L"},
            {**a_value(8.8, "2021-05-05", "ТТГ 8.8"), "unit": "mmol/L"},
            {**a_value(9.9, "2022-05-05", "ТТГ  9.9  від 11.02.15 р."), "unit": "mmol/L"},
            a_value(9.9, "2015-02-11", "ТТГ 9.9")]  # the form, with no unit printed on it

    drawn = charts(mine, indicator="thyrotropin", placing=QUOTING)

    assert not any(row.get("quoted") for chart in drawn for row in chart["rows"])


def test_a_row_the_chart_never_draws_cannot_fold_a_retelling():
    """A form's "previous value" column is listed and never drawn.

    Read as a form it took the retelling away and left the measurement of that day on no chart at
    all, represented by the one row that is not drawn. values.py says of such a column that it
    "lands on the date of the form that quoted it, which is a date no laboratory ever gave it":
    preferring it to the retelling is preferring the record this program itself calls wrong.
    """
    mine = [a_value(7.7, "2019-05-05", "ТТГ 7.7"), a_value(8.8, "2021-05-05", "ТТГ 8.8"),
            a_value(9.9, "2022-05-05", "ТТГ  9.9  від 11.02.15 р."),
            {**a_value(9.9, "2015-02-11", "попереднє 9.9"), "value_role": "previous"}]  # fmt: skip

    drawn = charts(mine, indicator="thyrotropin", placing=QUOTING)[0]

    assert len(drawn["points"]) == 3
    assert any(row.get("quoted") for row in drawn["rows"])
