"""Suspicion checks. Synthetic values only; no model and no archive."""

from epicrisis.suspects import find, provider_looks_like_a_person


def value(name, number, unit, indicator="creatinine", sha="a" * 64, page=1, **rest):
    return {"name": name, "value": str(number).replace(".", ","), "number": number, "unit": unit,
            "indicator_id": indicator, "file_sha256": sha, "first_page": page, "date": "2020-01-01", **rest}  # fmt: skip


def document(sha="a" * 64, page=1, **rest):
    return {"file_sha256": sha, "first_page": page, "date": "2020-01-01", "doc_type": "lab_panel",
            "title": "Biochemistry", "provider": "City Laboratory", "transcribed": 1, **rest}  # fmt: skip


def test_a_number_far_from_every_other_reading_of_the_same_test_is_a_candidate():
    history = [value("Creatinine", n, "mg/dL", sha=f"{i}" * 64) for i, n in enumerate([0.9, 1.0, 1.1, 0.95])]
    odd = value("Creatinine", 44.1, "mg/dL", sha="f" * 64)

    found = find([*history, odd], [document(sha=f"{i}" * 64) for i in range(4)] + [document(sha="f" * 64)])

    assert [item.file_id for item in found] == ["f" * 8]
    assert found[0].codes["number_far_from_the_others"] == 1
    assert "44,1" in found[0].lines[0]


def test_units_differing_between_laboratories_are_not_suspicious_but_a_missing_one_is():
    printed = [value("Creatinine", 80 + n, "мкмоль/л", sha=f"{n}" * 64) for n in range(4)]
    other_lab = value("Creatinine", 1.0, "mg/dL", sha="e" * 64)  # another unit, same test: fine
    no_unit = value("Creatinine", 88, None, sha="f" * 64)

    found = {item.file_id: item for item in find([*printed, other_lab, no_unit], [document(sha=f"{n}" * 64) for n in range(4)])}

    assert "e" * 8 not in found
    assert found["f" * 8].codes["unit_missing_where_others_have_one"] == 1


def test_an_institution_read_as_a_person_and_a_lab_form_with_no_title():
    found = {item.file_id: item for item in find([], [
        document(sha="1" * 64, provider="Кедров В. П."),
        document(sha="2" * 64, provider="TRW, KLN"),
        document(sha="3" * 64, title=None),
        document(sha="4" * 64),
    ])}  # fmt: skip

    assert found["1" * 8].codes["institution_looks_like_a_name"] == 1
    assert found["2" * 8].codes["institution_looks_like_a_name"] == 1
    assert found["3" * 8].codes["lab_form_without_a_title"] == 1
    assert "4" * 8 not in found
    assert not provider_looks_like_a_person("Aegean Laboratories Cyprus Ltd")
    assert provider_looks_like_a_person("Гриценко С.А.")
    # A title before the name, and the institution's own words standing in the title instead.
    assert provider_looks_like_a_person("проф. Дорошенко Д.Г.")
    assert provider_looks_like_a_person("Javier Morales Ortega", "Dr. Navarro Clínica Ocular")
    assert not provider_looks_like_a_person("Optivue Systems")
    assert not provider_looks_like_a_person("NORDLENS Technology Sp. z o.o.")
    assert not provider_looks_like_a_person("Клініка VITAMED", "Біохімія крові")
