"""Printed dates read into calendar dates. Synthetic strings only."""

from datetime import date

import pytest

from epicrisis.dates import read_printed_date

TODAY = date(2026, 9, 17)


@pytest.mark.parametrize(
    ("printed", "language", "expected", "precision", "ambiguous"),
    [
        ("03.02.2026", "el", date(2026, 2, 3), "day", False),
        ("03/02/2026 11:37:48", "en", date(2026, 2, 3), "day", True),
        ("13/02/2026", "en", date(2026, 2, 13), "day", False),
        ("02/13/2026", "en", date(2026, 2, 13), "day", False),
        ("«12» 03 2003 г.", "ru", date(2003, 3, 12), "day", False),
        ("«5» марта 2003г.", "ru", date(2003, 3, 5), "day", False),
        ("12 березня 2019 р.", "uk", date(2019, 3, 12), "day", False),
        ("3 de febrero de 2026", "es", date(2026, 2, 3), "day", False),
        ("February 3, 2026", "en", date(2026, 2, 3), "day", False),
        ("12.03.03", "ru", date(2003, 3, 12), "day", False),
        ("17.05.92", "ru", date(1992, 5, 17), "day", False),
        ("2026-02-03", "en", date(2026, 2, 3), "day", False),
        ("с «12» 03 2003 г. по «20» 03 2003 г.", "ru", date(2003, 3, 12), "day", False),
        ("12 12 2002", "uk", date(2002, 12, 12), "day", False),
        ("2007 г.", "ru", date(2007, 1, 1), "year", False),
        ("март 2005", "ru", date(2005, 3, 1), "month", False),
        ("12.III.03", "ru", date(2003, 3, 12), "day", False),
        ("12/III-03г.", "ru", date(2003, 3, 12), "day", False),
        ("24/УI-92г.", "ru", date(1992, 6, 24), "day", False),
        ("08. 89", "ru", date(1989, 8, 1), "month", False),
        ("12.03", "ru", None, None, False),
        ("5 січня 2008 р.", "uk", date(2008, 1, 5), "day", False),
        ("12 квітня 2019", "uk", date(2019, 4, 12), "day", False),
        ("1 листопада 2005 р.", "uk", date(2005, 11, 1), "day", False),
        ("5/ХІ 2001", "uk", date(2001, 11, 5), "day", False),
        ("10:30:00 03-02-26", "en", date(2026, 2, 3), "day", True),
    ],
)
def test_printed_dates(printed, language, expected, precision, ambiguous):
    result = read_printed_date(printed, language, TODAY)
    assert (result.value, result.precision, result.ambiguous, result.printed) == (expected, precision, ambiguous, printed)


@pytest.mark.parametrize("printed", [None, "", "   ", "без даты"])
def test_unreadable_dates_stay_empty(printed):
    assert read_printed_date(printed, "ru", TODAY).value is None


def test_impossible_day_keeps_only_the_year():
    result = read_printed_date("32.13.2020", "ru", TODAY)
    assert (result.value, result.precision) == (date(2020, 1, 1), "year")


def test_birth_dates_are_found_by_their_label():
    from epicrisis.dates import birth_dates

    text = "Paciente: Synthetic Person\nFecha de nacimiento (día, mes, año): 06.12.61\nConsulta 19 de junio de 2023"
    assert [item.value for item in birth_dates(text, "es", TODAY)] == [date(1961, 12, 6)]
    assert [item.value for item in birth_dates("Дата рождения: «5» марта 1960 г.", "ru", TODAY)] == [date(1960, 3, 5)]
    assert [item.value for item in birth_dates("D.O.B. : 01/02/1970", "en", TODAY)] == [date(1970, 2, 1)]
    assert birth_dates("Дата исследования 12.03.2003", "ru", TODAY) == []


def test_a_birth_date_is_never_the_document_date():
    from epicrisis.document_dates import document_date

    extracted = {
        "language": "es",
        "date_of_study_as_printed": "06.12.61",
        "date_of_report_as_printed": "19 de junio de 2023",
        "page_texts": [{"page": 1, "text": "Fecha de nacimiento: 06.12.61\n19 de junio de 2023"}],
    }
    result = document_date(extracted, [{"language": "es", "date_on_page": None}], TODAY)

    assert (result["value"], result["label"]) == (date(2023, 6, 19), "19.06.2023")
    assert [flag["code"] for flag in result["flags"]] == ["birth_date"]


def test_day_first_dates_in_the_same_document_settle_an_ambiguous_one():
    from epicrisis.document_dates import document_date

    pages = [{"language": "en", "date_on_page": None}]
    settled = document_date({"language": "en", "date_of_study_as_printed": "12/01/2026", "date_of_report_as_printed": "13/01/2026 10:15"}, pages, TODAY)
    unsettled = document_date({"language": "en", "date_of_study_as_printed": "05/04/2019"}, pages, TODAY)
    printed_later = document_date({"language": "es", "date_of_study_as_printed": "22/03/2022", "date_of_report_as_printed": "11/06/2025"}, pages, TODAY)
    before_study = document_date({"language": "uk", "date_of_study_as_printed": "18.09.2014", "date_of_report_as_printed": "29.12.2000"}, pages, TODAY)

    assert settled["flags"] == [] and [flag["code"] for flag in unsettled["flags"]] == ["ambiguous"]
    assert printed_later["flags"] == [] and [flag["code"] for flag in before_study["flags"]] == ["apart"]


def test_how_a_document_writes_its_dates_is_read_by_the_one_reader_of_a_printed_date():
    """Whether a document prints day first was asked with a pattern written out by hand, twice.

    The copy had neither the back-reference that makes the two separators of a date match nor the
    spaced shape, so it answered wrongly in both directions. A document printing "19 05 2020" —
    a date this program reads to the day — gave no evidence of its habit, and another date of the
    same document kept "Day and month may be swapped" although the document had said plainly how
    it writes dates. And "19.05-2020", which this program does not read as a date at all but only
    for its year, was answered day first: a string never read as a date settled the reading of
    dates that were, and through day_first_evidence that habit carried to every document of the
    same institution, taking an honest "not known" off each of them. That is the half that
    matters most, because the flag is this program saying it does not know.
    """
    from epicrisis.dates import DAY_FIRST, MONTH_FIRST, day_or_month_first
    from epicrisis.document_dates import day_first_evidence, document_date, prints_day_first

    assert day_or_month_first("19 05 2020") == DAY_FIRST
    assert day_or_month_first("19.05.2020") == DAY_FIRST
    assert day_or_month_first("02/28/2020") == MONTH_FIRST
    assert day_or_month_first("05/06/2020") is None  # either way round
    assert day_or_month_first("19.05-2020") is None  # not a date this program reads
    assert day_or_month_first("08:30 12.05.2020") is None  # the time is not the day
    assert day_or_month_first(None) is None

    pages = [{"page": 1, "language": "en", "date_on_page": None, "provider_on_page": "A laboratory"}]

    def flags(report):
        found = document_date({"language": "en", "date_of_study_as_printed": "05/06/2020",
                               "date_of_report_as_printed": report}, pages, TODAY)  # fmt: skip
        return [flag["code"] for flag in found["flags"]]

    assert "ambiguous" not in flags("19 05 2020")  # the document said it, with spaces
    assert "ambiguous" in flags("19.05-2020")  # the document said nothing this program read
    assert "ambiguous" in flags("07/08/2020")  # and said nothing at all
    assert "ambiguous" not in flags("19.05.2020")

    # The habit of an institution carries to its every document, so it is the same question again.
    def habit(printed):
        document = {"language": "en", "date_of_report_as_printed": printed}
        seen, providers = day_first_evidence([("a" * 64, document, pages)])
        return prints_day_first(document, pages), len(providers)

    assert habit("19 05 2020") == (True, 1)
    assert habit("19.05-2020") == (False, 0)
    assert habit("19.05.2020") == (True, 1)
    assert habit("05/06/2020") == (False, 0)


def test_a_time_or_a_page_number_printed_before_the_date_is_not_part_of_it():
    """A stamp reading 08:30 12.05.2020 was filed under 30 December 2005, with no flag at all."""
    from datetime import date

    from epicrisis.dates import read_printed_date

    today = date(2026, 9, 24)
    for printed in ("08:30 12.05.2020", "10:30  12.05.2020", "Стр. 1 из 2  12.05.2020", "№ 4517 12.05.2020"):
        assert read_printed_date(printed, "ru", today).value == date(2020, 5, 12), printed

    # A date written with spaces is still a date, and one written year first with dots is too.
    assert read_printed_date("12 05 2020", "ru", today).value == date(2020, 5, 12)
    assert read_printed_date("Дата 2020.05.12", "ru", today).value == date(2020, 5, 12)
    assert read_printed_date("2020/05/12", "ru", today).value == date(2020, 5, 12)

    # And the separators have to be the same on both sides: 12.05 2020 is two numbers and a year.
    assert read_printed_date("Палата 12 05.06.2020", "ru", today).value == date(2020, 6, 5)


def test_a_date_written_with_hyphens_keeps_its_day_and_its_month():
    """DD-MON-YYYY is what a laboratory system prints, and both parts were lost.

    The document went quietly to the first of January with no flag to say the date had been read
    more roughly than it was printed. And the Greek genitive of May failed for a different
    reason: casefold splits ΐ into a letter and two combining marks, and a pattern of letters
    stops at the first mark it cannot take — so the month in capitals read perfectly and the
    month in lower case did not.
    """
    from epicrisis.dates import read_printed_date

    for text, expected in (("10-NOV-2021", "2021-11-10"), ("9-ago-2011", "2011-08-09"),
                           ("9-лип-2011", "2011-07-09"), ("09/JUL/2011", "2011-07-09"),
                           ("8 Μαΐου 2019", "2019-05-08"), ("8 ΜΑΙΟΥ 2019", "2019-05-08"),
                           ("1º de marzo de 2019", "2019-03-01")):  # fmt: skip
        got = read_printed_date(text)
        assert got and str(got.value) == expected, f"{text} -> {got}"
        assert got.precision == "day", text

    # What was already read stays read, and what is not a date stays not a date: a printed range
    # is two numbers with a dash between them, and the hyphen must not make it a date.
    assert str(read_printed_date("12.05.2020").value) == "2020-05-12"
    assert str(read_printed_date("08:30 12.05.2020").value) == "2020-05-12"
    assert read_printed_date("3,89-5,84").value is None
    assert read_printed_date("менее 5").value is None


def test_a_word_that_is_not_a_month_does_not_take_the_date_behind_it():
    """The day-month-year shape matches any word where a month's name belongs, and finditer then
    carries on from the end of whatever matched — so a word that named no month took the rest of
    the sentence with it.

    "ТТГ 4.12 від 19 січня 2019" matched on "12 від 19" first, and the date printed two characters
    later was never looked at. What answered instead was the month-and-year reader, so the day the
    form printed was dropped and the reading stood on the first of the month, with the precision
    saying "month" and nothing saying a day had been there to lose. It happened in all five
    languages, on whatever word the writer put in front of the date: "12 de 19" in Spanish,
    "12 στις 19" in Greek.
    """
    from epicrisis.dates import read_printed_date

    for text, expected in (("ТТГ 4.12 від 19 січня 2019 р.", "2019-01-19"),
                           ("TSH 4,12 de 19 de enero de 2019", "2019-01-19"),
                           ("ΤΣΗ 4.12 στις 19 Ιανουαρίου 2019", "2019-01-19"),
                           ("TSH 4.12 from Jan 19, 2019", "2019-01-19"),
                           ("Дата дослідження: 8 травня 2019", "2019-05-08")):  # fmt: skip
        got = read_printed_date(text)
        assert got and str(got.value) == expected, f"{text} -> {got}"
        assert got.precision == "day", text

    # And a month with no day beside it is still a month, not a day invented to fill the gap.
    assert read_printed_date("ТТГ 4.12 від січня 2019").precision == "month"


def test_a_date_of_birth_printed_in_front_of_its_own_label():
    """Two columns of a form, flattened into one line, put the value before the label.

    Taking what follows the label then reaches past it into the next line: on a Greek form it took
    the date a study was completed, three years out and on the wrong side of a whole life.
    """
    from epicrisis.dates import birth_dates

    greek = "ΠΑΡΑΠΕΜΠΩΝ ΙΑΤΡΟΣ: NOT ASSIGNED\n06/12/1975ΗΜ.ΓΕΝΝΗΣΗΣ:\n13/06/2025ΗΜΕΡ.ΟΛΟΚΛΗΡΩΣΗΣ:"
    assert [one.value.isoformat() for one in birth_dates(greek, "el")] == ["1975-12-06"]

    # The ordinary way round still reads, on one line and over a line break.
    assert [one.value.isoformat() for one in birth_dates("Дата народження: 06.12.1975", "uk")] == ["1975-12-06"]
    assert [one.value.isoformat() for one in birth_dates("Дата народження:\n06.12.1976", "uk")] == ["1976-12-06"]
    # A month written as a word is eaten by the label's own run of non-digits, so such a form gives
    # the year and not the day. That is how it has always read here and is not what this is about.
    assert [one.value.isoformat() for one in birth_dates("Год рождения: Dec 06, 1975", "ru")] == ["1975-01-01"]


def test_an_empty_birth_field_does_not_borrow_the_date_of_the_field_below_it():
    """"Дата народження: Вік:" is a form printing nothing, and what follows it is another field."""
    from epicrisis.dates import birth_dates

    empty = "Пацієнт: Хтось\nДата народження: Вік:\nДата обстеження: 14.03.12\n"
    assert birth_dates(empty, "uk") == []

    # Nor the date of the field above it, which ends at a line break rather than at the label.
    above = "ДАТА: Aug 11, 2011\nГод рождения: Dec 06, 1975\n"
    assert [one.value.isoformat() for one in birth_dates(above, "ru")] == ["1975-01-01"]


def test_how_precisely_a_date_is_known_is_said_once_by_the_reading_that_knows_it():
    """The index read the precision back out of the label by counting the full stops in it.

    `dates.read_printed_date` knows whether a form printed a day, a month or a year; the date a
    document carries threw that away and formatted a label, and the index then recovered "day"
    from two dots, "month" from one and "year" from none. The two agreed only while the label
    kept that shape — printed "2019-05" or "May 2019", every month-precision date in the archive
    would have been indexed as a year, and no test anywhere would have said so, because the only
    statement of the precision in the index was the punctuation of a string three modules away.

    So the date says how precisely it is known, and the label is only a label.
    """
    from epicrisis.document_dates import document_date

    pages = [{"language": "uk", "date_on_page": None}]
    a_day = document_date({"language": "uk", "date_of_study_as_printed": "18.09.2014"}, pages, TODAY)
    a_month = document_date({"language": "ru", "date_of_study_as_printed": "март 2005"}, pages, TODAY)
    a_year = document_date({"language": "uk", "date_of_study_as_printed": "за 2017 рік"}, pages, TODAY)
    nothing_printed = document_date({"language": "uk"}, pages, TODAY)

    # All three the reader has, because the one it was replacing could only answer in three and
    # a fourth precision added to dates.py would have come out of the index as "year".
    assert a_day["precision"] == "day" and a_month["precision"] == "month"
    assert a_year["precision"] == "year"
    assert nothing_printed["precision"] is None, "a date nobody printed has no precision either"

    # And it is the reader's own answer rather than a reading of what the label happens to look
    # like: this month-precision date carries a label with one dot in it and would have come out
    # "month" either way, which is the whole reason the duplication survived so long.
    assert a_month["label"] == "03.2005" and a_day["label"] == "18.09.2014"
