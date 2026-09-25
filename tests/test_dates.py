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
