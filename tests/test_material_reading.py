"""What was measured, where the form did not print it: read by a model, kept apart from the form."""

import json
from pathlib import Path

from epicrisis.material_reading import load_materials, panel_key, panels_to_read, read_materials


class FakeMaterialBackend:
    """Answers from the table heading alone, the way the real one is asked to."""

    name = "fake"
    model = "fake-haiku"

    def __init__(self, answers: dict[str, tuple[str, bool]]):
        self.answers, self.seen = answers, []

    def read(self, panels: str, workdir: Path) -> dict:
        self.seen.append(panels)
        out = []
        for block in panels.split("\n\n"):
            lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
            material, sure = self.answers.get(lines.get("table heading", ""), ("unclear", False))
            out.append({"ref": lines["ref"], "material": material, "sure": sure, "why": "the heading says so"})
        return {"panels": out}


def documents() -> list[dict]:
    def value(name, table):
        return {"name_as_printed": name, "table_as_printed": table, "value_as_printed": "1",
                "provenance": {"page": 1}}  # fmt: skip

    return [
        {
            "file_sha256": "a" * 64, "pages": [1], "title_as_printed": "INFORME MÉDICO",
            "observations": [
                value("Glucosa", "Laboratorio"), value("Calcio", "Laboratorio"),
                value("Septo VI td", "Medidas del Ventriculo"),
                value("Leucocitos", "ANÁLISIS DE ORINA"),  # the form says it: never sent
            ],
        },
    ]


def test_only_the_tables_the_form_left_unsaid_are_sent(tmp_path):
    panels = panels_to_read(documents())

    assert sorted(panel["table"] for panel in panels) == ["Laboratorio", "Medidas del Ventriculo"]
    assert [panel["values"] for panel in panels if panel["table"] == "Laboratorio"] == [2]
    # One panel is one table on one document; its values answer together.
    assert panels[0]["panel"] == panel_key("a" * 64, [1], "Laboratorio")


def test_a_reading_is_kept_apart_and_only_what_it_was_sure_of_applies(tmp_path):
    backend = FakeMaterialBackend({
        "Laboratorio": ("blood", True),
        "Medidas del Ventriculo": ("none", True),  # measured on the person, not in a sample
    })  # fmt: skip

    counts = read_materials(tmp_path, documents(), backend, tmp_path)

    assert counts["panels"] == 2 and counts["decided"] == 2 and counts["values"] == 3
    written = [json.loads(line) for line in (tmp_path / "materials.jsonl").read_text().splitlines()]
    assert {item["table"] for item in written} == {"Laboratorio", "Medidas del Ventriculo"}
    assert all(item["by"] == "fake-haiku" and item["at"] for item in written)

    # "none" is an answer, and not a material: an echocardiogram measurement is in no specimen.
    applied = load_materials(tmp_path)
    assert list(applied) == [panel_key("a" * 64, [1], "Laboratorio")]
    assert applied[panel_key("a" * 64, [1], "Laboratorio")]["material"] == "blood"

    # Nothing is asked twice.
    again = read_materials(tmp_path, documents(), backend, tmp_path)
    assert again["panels"] == 0 and len(backend.seen) == 1


def test_a_guess_waits_and_never_reaches_the_index(tmp_path):
    backend = FakeMaterialBackend({"Laboratorio": ("blood", False), "Medidas del Ventriculo": ("unclear", False)})

    counts = read_materials(tmp_path, documents(), backend, tmp_path)

    assert counts["waiting"] == 1 and counts["unclear"] == 1 and counts["decided"] == 0
    assert load_materials(tmp_path) == {}  # a guess about a specimen is not a fact about one
    assert len(load_materials(tmp_path, sure_only=False)) == 1  # but it is kept, for a person to see


def test_no_number_no_date_and_no_file_name_is_ever_sent(tmp_path):
    backend = FakeMaterialBackend({"Laboratorio": ("blood", True)})
    read_materials(tmp_path, documents(), backend, tmp_path)

    sent = "\n".join(backend.seen)
    assert "Glucosa" in sent and "INFORME MÉDICO" in sent  # headings and names, which is the question
    assert "a" * 64 not in sent and "value" not in sent.casefold().replace("value names", "")
    for forbidden in ("2019", "1,", "sha", ".pdf"):
        assert forbidden not in sent


def test_what_a_model_read_reaches_the_index_marked_as_read(tmp_path):
    """The whole way through: a decision is applied, and never looks like a printed word."""
    import sqlite3

    from epicrisis.index.build import build_index, index_path
    from epicrisis.material_reading import FILE_NAME
    from epicrisis.records import append_line
    from test_extract import build_archive

    from epicrisis.settings import set_trusts_read_materials
    from epicrisis.extract.run import extract_source
    from test_extract import FakeExtractBackend

    data_dir, source, output, _records = build_archive(tmp_path)
    set_trusts_read_materials(data_dir, True)  # off by default; this test is about it being on
    extract_source(data_dir, source, FakeExtractBackend())
    build_index(data_dir, [source])

    connection = sqlite3.connect(index_path(data_dir, source.id))
    connection.row_factory = sqlite3.Row
    before = connection.execute(
        "SELECT o.table_heading, d.file_sha256, d.pages FROM observations o"
        " JOIN documents d ON d.id = o.document_id WHERE o.material IS NULL LIMIT 1"
    ).fetchone()
    connection.close()
    assert before is not None  # this synthetic archive prints no material anywhere

    append_line(output / FILE_NAME, {
        "panel": panel_key(before["file_sha256"], json.loads(before["pages"]), before["table_heading"]),
        "file_sha256": before["file_sha256"], "pages": json.loads(before["pages"]),
        "table": before["table_heading"], "material": "blood", "sure": True,
        "why": "a biochemistry panel", "values": 1, "by": "fake-haiku", "at": "2026-09-21T00:00:00+00:00",
    })  # fmt: skip
    build_index(data_dir, [source])

    connection = sqlite3.connect(index_path(data_dir, source.id))
    connection.row_factory = sqlite3.Row
    rows = connection.execute("SELECT material, material_source, count(*) AS n FROM observations GROUP BY 1, 2").fetchall()
    connection.close()
    read = {(row["material"], row["material_source"]): row["n"] for row in rows}
    assert read.get(("blood", "model"), 0) >= 1  # applied
    assert ("blood", "printed") not in read  # and never passed off as something a form printed

    # Turned off again, the same archive says only what its forms said.
    set_trusts_read_materials(data_dir, False)
    build_index(data_dir, [source])
    connection = sqlite3.connect(index_path(data_dir, source.id))
    left = connection.execute("SELECT count(*) FROM observations WHERE material_source = 'model'").fetchone()[0]
    connection.close()
    assert left == 0


def test_a_reading_is_used_only_when_the_person_asked_for_it(tmp_path):
    """The setting decides, and a page says which way it is set. Off in the repository."""
    from fastapi.testclient import TestClient

    from epicrisis.settings import trusts_read_materials
    from epicrisis.web.app import create_app

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    assert trusts_read_materials(data_dir) is False  # what a form prints, and nothing else

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = client.get("/settings").text
    assert "Let a model say what a form did not" in page
    assert 'name="read_materials" value="on"' in page and "checked" not in page.split('name="read_materials"')[1][:40]

    client.post("/settings", data={"read_materials": "on"}, follow_redirects=False)
    assert trusts_read_materials(data_dir) is True
    assert "checked" in client.get("/settings").text.split('name="read_materials"')[1][:40]

    client.post("/settings", data={}, follow_redirects=False)
    assert trusts_read_materials(data_dir) is False


def test_which_model_does_which_reading_is_chosen_and_used(tmp_path):
    """Three readings, three choices, and every step asks the settings rather than a constant."""
    from fastapi.testclient import TestClient

    from epicrisis.settings import chosen_models
    from epicrisis.models import PASSES, model_for
    from epicrisis.web.app import create_app

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    # What the program ships with, until someone says otherwise.
    assert model_for(data_dir, "first").startswith("claude-haiku")
    assert model_for(data_dir, "strong") == "claude-opus-5"
    assert model_for(data_dir, "second_reader") == "claude-fable-5-1"

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = client.get("/settings").text
    for item in PASSES.values():
        assert item["label"] in page
    assert 'name="model_first"' in page and 'name="model_second_reader"' in page

    client.post("/settings", data={"model_first": "claude-sonnet-5", "model_strong": "claude-opus-5",
                                   "model_second_reader": "claude-fable-5-1"}, follow_redirects=False)  # fmt: skip
    assert model_for(data_dir, "first") == "claude-sonnet-5"
    assert chosen_models(data_dir)["first"] == "claude-sonnet-5"

    # The steps that run a model build it from the choice, not from a constant.
    from epicrisis.extract.backend import default_extract_backend

    ladder = default_extract_backend(data_dir)
    assert ladder.model.startswith("claude-sonnet-5>")


def test_a_table_printed_sideways_is_read_the_right_way_up():
    """Rows named for a specimen, under a heading that names the test. The form, sideways."""
    from epicrisis.index.build import analyte_of, inverted_tables

    sideways = [
        {"table_as_printed": "Мочевая кислота ммоль/л", "name_as_printed": "моча"},
        {"table_as_printed": "Мочевая кислота ммоль/л", "name_as_printed": "кровь"},
    ]
    # On a urinalysis "Кров" is one row of many and means the test for blood in the urine.
    upright = [
        {"table_as_printed": "Аналіз сечі загальний", "name_as_printed": "Кров"},
        {"table_as_printed": "Аналіз сечі загальний", "name_as_printed": "Білок"},
    ]
    # A heading naming a section is never the name of a test, whatever its rows are called.
    section = [{"table_as_printed": "Мікроскопічне дослідження", "name_as_printed": "кров"}]

    assert inverted_tables(sideways) == {"Мочевая кислота ммоль/л"}
    assert inverted_tables(upright) == set()
    assert inverted_tables(section) == set()
    assert inverted_tables(sideways + upright) == {"Мочевая кислота ммоль/л"}

    names = {"мочевая кислота": "uric-acid"}
    assert analyte_of("Мочевая кислота ммоль/л", names) == "uric-acid"  # the unit is dropped
    assert analyte_of("Оскалаты мг/с", names) is None  # nothing is invented


def test_a_person_says_what_was_measured_and_their_word_wins(tmp_path):
    """The escape hatch for a form no rule can read: one line, set by hand, marked as theirs."""
    from epicrisis.index.build import _material

    observation = {"name_as_printed": "кровь", "table_as_printed": "Мочевая кислота ммоль/л",
                   "provenance": {"page": 1}}  # fmt: skip
    document = {"title_as_printed": "Транспорт солей"}

    # Uric acid is a blood test whose Russian name begins with the word for urine, so the rules
    # now read nothing from that heading at all. The row itself says blood, when the table is
    # known to be printed sideways.
    assert _material(observation, document, None, None, "a" * 64, (1,))[0] is None
    assert _material(observation, document, None, None, "a" * 64, (1,), sideways=True) == ("blood", "printed")

    by_hand = {"changes": {"material": "blood"}}
    assert _material(observation, document, None, None, "a" * 64, (1,), by_hand) == ("blood", "person")

    # "none" is an answer: measured on the person, not in a sample.
    no_sample = {"changes": {"material": "none"}}
    assert _material(observation, document, None, None, "a" * 64, (1,), no_sample) == (None, "person")


def test_a_word_for_urine_inside_another_word_is_not_a_specimen():
    """Мочевина is a blood test, Blood pressure is not a specimen, and a smear of blood is blood."""
    from epicrisis.index.build import is_derived, material_of

    def material(heading=None, name="x", title=None):
        return material_of({"table_as_printed": heading, "name_as_printed": name},
                           {"title_as_printed": title})  # fmt: skip

    assert material(name="Мочевина") is None
    assert material(name="Мочевая кислота") is None
    assert material(title="ВЫПИСКА: кесарево сечение") is None
    assert material(heading="Blood pressure", name="Систолическое") is None

    # And the headings that do name a specimen still do.
    assert material(heading="ОБЩИЙ АНАЛИЗ МОЧИ", name="Белок") == "urine"
    assert material(heading="ЗАГАЛЬНИЙ АНАЛІЗ СЕЧІ", name="Білок") == "urine"
    assert material(heading="АНАЛИЗ КАЛА", name="Скрытая кровь") == "stool"
    assert material(heading="Faecal occult blood") == "stool"
    assert material(heading="Мазок крові", name="Лейкоцити") == "blood"
    assert material(heading="мазок из уретры", name="Лейкоциты") == "swab"

    # A rate is calculated only where the form prints it per body surface, or names it.
    assert is_derived({"name_as_printed": "Скорость инфузии", "unit_as_printed": "мл/мин"}) is False
    assert is_derived({"name_as_printed": "ШКФ (CKD-EPI)", "unit_as_printed": ""}) is True
    assert is_derived({"name_as_printed": "Ρυθμός σπειραματικής διήθησης", "unit_as_printed": ""}) is True
    assert is_derived({"name_as_printed": "x", "unit_as_printed": "mL/min/1.73m²"}) is True
