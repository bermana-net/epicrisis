"""A name printed where the institution goes: what the index does with it, and who says so.

A hospital's own export prints the doctor's name where a letterhead would print the clinic. The
index notices and files that name as the doctor, leaving the institution empty — the move is
right, it is why one archive here has doctors at all, and it was made in silence: nothing recorded
it, the shipped rule meant to mark it read the provider column the move had emptied and found 0
documents on every archive for ever, and the extract step's own check counted the same fact into
a line with no name and no switch.

So the index writes the move down and the rule reads the record. These tests are that sentence,
both halves, on synthetic archives: no model, no network, nobody's documents. The names are the
ones the suite already uses — invented, and looked for in all three live indexes.
"""

import json
import sqlite3
from contextlib import closing

from epicrisis import rules
from epicrisis.extract.run import extract_source, load_extracted, transcription_problems, write_document
from epicrisis.index.build import build_index, index_path
from epicrisis.printed_values import fold
from epicrisis.rules import kinds
from epicrisis.settings import rules_on, set_rule_on
from epicrisis.suspects import find, rows_from_index
from epicrisis.validate import validate_source
from epicrisis.web.looks_misread import how_many_look_misread
from test_extract import FakeExtractBackend, setup  # noqa: F401

# Printed exactly as a form prints a signature under a stamp, and invented: looked for in every
# live index as a whole string and found in none of them.
A_SIGNATURE_WHERE_THE_CLINIC_GOES = "Кедров В. П."
ANOTHER_SIGNATURE = "Гриценко С.А."
A_DOCTOR_WITH_A_TITLE = "проф. Дорошенко Д.Г."
# The shape that only reads as a person once the title is read with it: an ordinary-looking name,
# and the institution's own words standing in the title because the two fields were swapped.
A_NAME_WITH_NO_INITIALS = "Javier Morales Ortega"
A_TITLE_HOLDING_THE_CLINIC = "Dr. Navarro Clínica Ocular"


def read_as(data_dir, source, output, labs, **fields):
    """Rewrite the header fields of the transcribed laboratory form, then check and index it."""
    document = load_extracted(output / "extracted", labs)["documents"][0]
    write_document(output / "extracted", labs, {**document, **fields})
    result = validate_source(output)
    build_index(data_dir, [source])
    return result


def the_document(data_dir, source, labs):
    with closing(sqlite3.connect(f"file:{index_path(data_dir, source.id)}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        return dict(connection.execute(
            "SELECT provider, doctor, person_printed_as_the_institution FROM documents WHERE file_sha256 = ?",
            (labs,),
        ).fetchone())  # fmt: skip


def what_the_rules_find(data_dir, source, labs):
    """What every rule of the suspects step this archive runs says about that one document."""
    with closing(sqlite3.connect(f"file:{index_path(data_dir, source.id)}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        rows, documents, spellings = rows_from_index(connection)
    chosen = rules_on(data_dir, rules.load(data_dir), kinds.SUSPECTS)
    return [found for found in find(rows, documents, spellings, chosen) if found.file_sha256 == labs]


def still_failing(result, labs: str) -> int:
    """How much of "the checks still fail after the strong model" this document carries."""
    found = next((item for item in result["documents"] if item["file_sha256"] == labs), None)
    return (found or {"findings": {}})["findings"].get("checks_still_failing", 0)


def test_the_index_writes_down_the_name_it_moved(setup):  # noqa: F811
    """The move, and the printed string kept beside it rather than only under the doctor."""
    data_dir, source, output, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    labs = records["labs.pdf"]["sha256"]

    read_as(data_dir, source, output, labs, provider_as_printed=A_SIGNATURE_WHERE_THE_CLINIC_GOES)

    row = the_document(data_dir, source, labs)
    assert row["provider"] is None  # a person is not this document's laboratory
    assert row["doctor"] == A_SIGNATURE_WHERE_THE_CLINIC_GOES
    # The second entry of the constitution: the form printed that name in the institution's place,
    # and the archive can still say so. Without this column the string survives only under the
    # doctor's heading, where nothing says where it was printed.
    assert row["person_printed_as_the_institution"] == A_SIGNATURE_WHERE_THE_CLINIC_GOES
    # And the transcription itself is untouched: it is what a model said, once.
    assert load_extracted(output / "extracted", labs)["documents"][0]["provider_as_printed"] == A_SIGNATURE_WHERE_THE_CLINIC_GOES


def test_the_rule_finds_the_document_whose_provider_column_is_empty(setup):  # noqa: F811
    """The permanent zero, as a test: the rule marks a document the move has emptied."""
    data_dir, source, output, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    labs = records["labs.pdf"]["sha256"]

    read_as(data_dir, source, output, labs, provider_as_printed=A_SIGNATURE_WHERE_THE_CLINIC_GOES)

    found = what_the_rules_find(data_dir, source, labs)
    assert [item.codes["institution_looks_like_a_name"] for item in found] == [1]
    # The line a person reads names the printed string and says what became of it.
    said = " ".join(found[0].lines)
    assert A_SIGNATURE_WHERE_THE_CLINIC_GOES in said and "read here as the doctor" in said
    # And the page that counts those findings counts this one: the line on the page of findings
    # and the list behind it are one gathering, so this is the number beside the switch too.
    assert how_many_look_misread(data_dir, source.id)["findings"] >= 1


def test_one_printed_fact_makes_one_finding(setup):  # noqa: F811
    """The whole measurement, on one document: the rule gains it and the nameless line lets go.

    `checks_still_failing` is the line with no name and no switch. The extract step's own check
    still sees this fact — it decides whether a document is read again by a stronger model — and
    the fact no longer reaches that line, so the document carries exactly one finding of it.
    """
    data_dir, source, output, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    labs = records["labs.pdf"]["sha256"]

    with_a_person = read_as(data_dir, source, output, labs, provider_as_printed=A_SIGNATURE_WHERE_THE_CLINIC_GOES)
    document = load_extracted(output / "extracted", labs)["documents"][0]
    with_a_clinic = read_as(data_dir, source, output, labs, provider_as_printed="Synthetic Lab")

    assert "institution_looks_like_a_name" in transcription_problems(document, {})
    # Asked as the difference between the two readings and not as a number written down here:
    # whatever else this synthetic form fails, the printed fact adds nothing to that line.
    assert still_failing(with_a_person, labs) == still_failing(with_a_clinic, labs)
    # And a clinic in the institution's place is marked by nobody: no record, no finding.
    assert the_document(data_dir, source, labs)["person_printed_as_the_institution"] is None
    assert not any("institution_looks_like_a_name" in item.codes
                   for item in what_the_rules_find(data_dir, source, labs))  # fmt: skip


def test_switching_the_rule_off_takes_the_finding_away_for_good(setup):  # noqa: F811
    """Off is off: the finding goes and does not come back under another name.

    Measured against the same document with a clinic in the institution's place, because "the same
    as it was before the switch" is a sentence that stays true when the finding never left — the
    one shape of test this project keeps finding green and asleep.
    """
    data_dir, source, output, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    labs = records["labs.pdf"]["sha256"]
    with_a_clinic = read_as(data_dir, source, output, labs, provider_as_printed="Synthetic Lab")
    read_as(data_dir, source, output, labs, provider_as_printed=A_SIGNATURE_WHERE_THE_CLINIC_GOES)
    assert what_the_rules_find(data_dir, source, labs), "nothing to switch off"

    set_rule_on(data_dir, "institution_looks_like_a_name", False)
    off = validate_source(output)

    assert not any("institution_looks_like_a_name" in item.codes
                   for item in what_the_rules_find(data_dir, source, labs))  # fmt: skip
    # Nowhere else either: this document now carries exactly what a document with a clinic on it
    # carries, and the index still records the move, because what the index did is not a finding.
    assert still_failing(off, labs) == still_failing(with_a_clinic, labs)
    assert json.dumps(off["totals"], sort_keys=True) == json.dumps(with_a_clinic["totals"], sort_keys=True)
    assert the_document(data_dir, source, labs)["person_printed_as_the_institution"] == A_SIGNATURE_WHERE_THE_CLINIC_GOES


def test_a_name_beside_a_doctor_stays_where_it_was_printed_and_is_still_marked(setup):  # noqa: F811
    """The shape none of the three live archives prints: both fields naming a person.

    Nowhere to move the name to, because the form already said who the doctor was. The sixth
    entry of the constitution: a shape the archive in front of us does not happen to hold is
    exactly the one to write down.
    """
    data_dir, source, output, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    labs = records["labs.pdf"]["sha256"]

    read_as(data_dir, source, output, labs, provider_as_printed=ANOTHER_SIGNATURE,
            doctor_as_printed=A_DOCTOR_WITH_A_TITLE)  # fmt: skip

    row = the_document(data_dir, source, labs)
    assert (row["provider"], row["doctor"]) == (ANOTHER_SIGNATURE, A_DOCTOR_WITH_A_TITLE)
    assert row["person_printed_as_the_institution"] == ANOTHER_SIGNATURE
    found = what_the_rules_find(data_dir, source, labs)
    assert [item.codes["institution_looks_like_a_name"] for item in found] == [1]
    assert "read here as the doctor" not in " ".join(found[0].lines)


def test_the_title_is_read_with_the_provider_wherever_the_question_is_asked(setup):  # noqa: F811
    """The sign that needs both fields, and the one the rule used to be blind to.

    A name with no title in front and no initials beside it reads like a person only once the
    title is read with it: the institution's own words stand there and the institution's field
    holds none of them, so the two were swapped. The rule asked without the title and the index
    asks with it — one question with two answers — and this is the shape where that showed.
    """
    data_dir, source, output, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    labs = records["labs.pdf"]["sha256"]

    read_as(data_dir, source, output, labs, provider_as_printed=A_NAME_WITH_NO_INITIALS,
            title_as_printed=A_TITLE_HOLDING_THE_CLINIC)  # fmt: skip

    row = the_document(data_dir, source, labs)
    assert row["person_printed_as_the_institution"] == A_NAME_WITH_NO_INITIALS
    assert [item.codes["institution_looks_like_a_name"] for item in what_the_rules_find(data_dir, source, labs)] == [1]


def test_the_card_says_where_the_name_went(setup):  # noqa: F811
    """The seventh entry of the constitution, on the one page that prints both fields.

    The card shows the institution and the doctor as the model read them, so on such a document it
    showed a person under one heading and a dash under the other, while every page drawn from the
    index called that person the doctor of this document. Two answers on one screen and nothing
    saying which was which.
    """
    from fastapi.testclient import TestClient

    from epicrisis.web.app import create_app

    data_dir, source, output, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    labs = records["labs.pdf"]["sha256"]
    read_as(data_dir, source, output, labs, provider_as_printed=A_SIGNATURE_WHERE_THE_CLINIC_GOES)
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    card = client.get(f"/documents/{source.id}/{labs}/1").text

    assert "The institution's place on this form printed a person's name." in card
    assert "reads it as the doctor of this document" in card
    assert A_SIGNATURE_WHERE_THE_CLINIC_GOES in card, "and the printed name itself is still on the page"
    # A form that printed a clinic says none of it.
    read_as(data_dir, source, output, labs, provider_as_printed="Synthetic Lab")
    assert "printed a person's name" not in client.get(f"/documents/{source.id}/{labs}/1").text


def test_the_moved_name_is_still_found_by_searching_for_it(setup):  # noqa: F811
    """Nothing is lost to the move: the string is searchable where it always was."""
    data_dir, source, output, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    labs = records["labs.pdf"]["sha256"]

    read_as(data_dir, source, output, labs, provider_as_printed=A_SIGNATURE_WHERE_THE_CLINIC_GOES)

    with closing(sqlite3.connect(f"file:{index_path(data_dir, source.id)}?mode=ro", uri=True)) as connection:
        hits = connection.execute("SELECT count(*) FROM search WHERE provider MATCH ?",
                                  (f'"{fold(A_SIGNATURE_WHERE_THE_CLINIC_GOES)}"',)).fetchone()[0]  # fmt: skip
    assert hits == 1
