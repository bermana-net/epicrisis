"""The doctor read out of stored text: what shape proves a name, and what is never read at all.

Every name below is invented and was looked for in all three archives on this machine before it
was written down — in the provider, doctor and title columns, in the printed names of values, and
in every page of text — because a plausible surname in the right language is usually a real one
(§5). The words share no substring with anything printed on anybody's documents, and the oddness
is deliberate: a test looking for "Петров" in a page of Russian proves nothing.

What these assert is the one decision the module turns on. A label followed by a word is not a
reading, because the word after a label is a department as often as a surname and a stop list of
the form words somebody has already been caught by is not a design. A name has to prove that it is
a name — initials, a patronymic behind two other names, or an honorific printed in front — and
every test here is either that proof holding or that proof refusing.

The ones that look like trivia are the measured defects. Each names what it cost.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from epicrisis import doctors_in_text, people
from epicrisis.index.build import SCHEMA, SCHEMA_VERSION, index_path
from epicrisis.web import who
from epicrisis.web.app import create_app

from test_the_wall_between_people import THEIRS, _both_on_the_list
from test_the_wall_between_people import _an_archive as _a_walled_archive

#: Two archives, and nothing of one is a substring of anything of the other.
HERS = {"id": "cccc3333", "doctor": "Квазитрофенко А.В", "provider": "Northgale Clinical Rooms",
        "latin": "Qualtrina Vexmoor"}  # fmt: skip
HIS = {"id": "dddd4444", "doctor": "Пселлофазюк О.П", "provider": "Southmere Imaging Practice",
       "latin": "Zhmyrko Dreemoklych"}  # fmt: skip


def read(text: str) -> list[str]:
    """Just the names, for the tests that are about which shapes are read and which are not."""
    return [one.name for one in doctors_in_text.readings(text)]


# --- what proves a name, and what does not -------------------------------------------------

def test_a_label_and_a_form_word_is_not_a_reading():
    """The whole design in one assertion, and the reason there is no stop list anywhere here.

    The first search was a label followed by a surname, minus a list of the form words that follow
    such a label — «Відділення», «Замовлення», «Найменування», the Spanish «Colaborador». A list
    like that holds the words somebody has already been caught by and admits the next one in
    silence. So the proof moved into the shape of the name: a department does not come with
    initials, and no list of departments is kept.
    """
    assert read("Лікар: Відділення") == []
    assert read("Лікар: Замовлення") == []
    assert read("Médico: Colaborador") == []
    # And the same label, with something that proves itself.
    assert read("Лікар: Квазитрофенко А.В.") == ["Квазитрофенко А.В"]


def test_a_hospital_holds_the_word_for_a_doctor_and_is_not_one():
    """«лікарня» is a hospital and the first five letters of it are the label. The word stands on
    206 documents of the archives here, so a label matched loosely reads every letterhead in
    Ukrainian as a signature.

    What guards it is the lookbehind on each word of the filler and nothing else: the label may be
    followed by letters, but the first word after it may not begin in the middle of one. The label
    carried a word boundary of its own as well until this test was written, and the test could not
    fail with it lifted out — because these two archives print «лікарня» and «лікарні», whose two
    remaining letters the filler refuses on its own count. Two statements of one guard, and the
    measurement said so: 50, 29 and 5 names with the boundary and without it.

    **The third line is invented, and §6 asks for exactly that.** The live archives are blind to
    the shape where the two guards differ — a label followed by three lower-case letters or more
    — so it is written here: «лікарняний лист», a sick-note, on which the name is the
    **patient's**. A reading that crossed into it would name the person whose archive this is as
    the doctor who signed it.
    """
    assert read('ЛІКАРНЯ "Мляводзьоб"') == []
    assert read("Мляводзьобська міська клінічна лікарня № 97") == []
    assert read("Лікарняний лист видано пацієнтові Квазитрофенко А.В.") == []


def test_the_filler_between_a_label_and_a_name_never_crosses_the_name():
    """What cost 29 of the 84 names read here, and gave every one of them wrong.

    The lower-case class was first written as the Cyrillic block `Ѐ-ӿ`, which holds the capitals
    too — so the filler walked straight over the surname and the reading came back as the initials
    welded to the next word of the form. One archive prints its referrals on a single line, and
    all 29 of its doctors came out as "А.В Виконано".
    """
    line = "Направлено : 02.03.2026  № напр.:09767  Спеціаліст: Уролог  Лікар:  Квазитрофенко А.В  Виконано: 02.03.2026"
    assert read(line) == ["Квазитрофенко А.В"]


def test_a_surname_that_ends_like_a_patronymic_is_not_a_name_and_a_patronymic():
    """Two words are not proof; three are. A great many Ukrainian surnames end in -евич and -ович,
    exactly as a patronymic does, so «Завідуюча КДЛ Пселлофазович» read as a surname with a
    patronymic behind it and came back as the department welded to the name. Measured on the
    archives here: dropping the two-word shape took one wrong name away and lost no right one."""
    assert "КДЛ Пселлофазович" not in read("Завідуюча КДЛ Пселлофазович")
    # Three words, which is the shape a form really prints a full name in, and is read.
    assert read("Лікар Квазитрофенко Орися Пселлофазівна") == ["Квазитрофенко Орися Пселлофазівна"]


def test_a_bare_surname_under_a_label_is_not_read_and_that_is_the_price():
    """What this design costs, asserted rather than left in a docstring.

    A form that prints the label and the surname and nothing else has told a reader who signed,
    and this module does not read it: nothing in those letters tells a surname from a speciality
    or a kind of room. It is the honest half of the bargain and it is written down here so that
    nobody mistakes the silence for a bug.
    """
    assert read("Зав. відділенням Квазитрофенко") == []
    assert read("Лікар Пселлофазюк") == []


def test_a_degree_printed_on_a_letterhead_is_not_the_role_of_whoever_signed():
    """«доктор медичних наук» is a degree beside a name at the top of the paper, not a signature
    under the text. It named a scientific supervisor off the heading of four documents here."""
    assert read("Науковий керівник доктор медичних наук А.В.Квазитрофенко т. 2471495") == []
    assert read("Научный руководитель доктор медицинских наук О.П.Пселлофазюк") == []


def test_an_academic_degree_between_the_label_and_the_name_is_stepped_over():
    """«к.м.н.» is three capitals and three dots and would read as initials. A whole hospital's
    discharge summaries print it between the label and the name."""
    assert read("Зав. відділенням    к.м.н.  [підпис]  О.П.Пселлофазюк") == ["О.П.Пселлофазюк"]


def test_a_department_in_capitals_is_stepped_over_too():
    """«КДЦ» stands between the label and the name on one archive's reports, and capitals are let
    through only two to five of them with no dot after — which is an abbreviation and never a
    name. Before it was, the whole line read as nothing at all."""
    assert read("Лікар: завідувач КДЦ Квазитрофенко А.В. [підпис]") == ["Квазитрофенко А.В"]


# --- what is never read, however well it matches -------------------------------------------

def test_who_referred_is_not_who_signed():
    """The field asks for the person who saw, performed or signed, and a referring doctor did none
    of the three. The Greek laboratories print «ΠΑΡΑΠΕΜΠΩΝ ΙΑΤΡΟΣ:» in the same place a signature
    goes, and a Spanish note prints «SOLICITA:» in front of the consultants it asks for."""
    assert read("ФИО врача :Квазитрофенко А.В.    ЛПУ : Northgale") == []
    assert read("SOLICITA: Nefrología (Dr. Qualtrina Vexmoor)") == []
    assert read("Направив лікар Пселлофазюк О.П.") == []


def test_a_transcribers_bracket_is_a_description_of_a_mark_and_not_a_form():
    """Inside a bracket the order of a label and a name is somebody describing a picture, not the
    layout of a form. A round stamp here reads «[печать: ... * ЛІКАР * ...]», and read as a form
    it gave a patronymic with no surname in front of it."""
    assert read("[печать: Україна * м.Київ * Квазитрофенко Орися Пселлофазівна * ЛІКАР]") == []
    assert read("[Stamp: Δρ Qualtrina Vexmoor Personal Doctor] [signature]") == []
    # And a bracket standing between a real label and a real name hides neither of them.
    assert read("Лікар [підпис] /Пселлофазюк О.П./") == ["Пселлофазюк О.П"]


def test_an_honorific_is_the_proof_and_a_word_that_merely_ends_in_it_is_not():
    """No form prints "Dr." in front of a department, so the honorific is the proof a Latin name
    has instead of initials. An eye examination here prints «AR (Mydr.)», and the first search
    read a refraction table as a doctor.

    The second line is the invented shape (§6) and the first could not fail without it: on the
    line as the archive really prints it a bracket closes right after the honorific, so the space
    the pattern requires is what refuses it and the lookbehind is never asked. Take the bracket
    off and put a name after it — an export folding a refraction table and a signature onto one
    line — and the lookbehind is the only thing left between «Mydr.» and a doctor.

    The third asserts what is **not** in the honorifics: «и др.» is Russian for "and others" and
    stands once in these archives, and no lookbehind can tell it from a title, because the word in
    front of it is a space either way. Measured: the bare Cyrillic form read nobody on all 706
    documents, so it is not in the list at all.
    """
    assert read("AR (Mydr.) | +6,25 | +1,25 | 58") == []
    assert read("AR Mydr. Квазитрофенко А.В.") == []
    assert read("Обстеження, аналізи и др. Квазитрофенко А.В.") == []
    assert read("Dr. Qualtrina Vexmoor") == ["Qualtrina Vexmoor"]
    assert read("Fdo: Dr. Zhmyrko Dreemoklych") == ["Zhmyrko Dreemoklych"]
    # And the hyphenated form, which is a title and is read.
    assert read("Консультант-онколог    д-р Пселлофазюк О., MD") == ["Пселлофазюк О"]


def test_a_stamp_with_a_role_welded_onto_the_name_is_not_read():
    """Four capitalised words behind an honorific is a name with a role after it, and nothing in
    the letters says where the name stops. A guess there is the one thing the page could not show
    to be wrong, so nothing is read."""
    assert read("Dr Qualtrina Vexmoor Personal Doctor") == []
    assert read("DR QUALTRINA VEXMOOR NORTHGALE ROOMS") == []


def test_a_capital_surname_running_into_the_next_word_stops_where_it_stops():
    """One archive's export writes the next word onto the end of the surname with no space. The
    run of capitals took one letter too many and gave a surname that stands on no document."""
    assert read("DRA. QUALTRINA VEXMOORColegiado nº 292912206") == ["QUALTRINA VEXMOOR"]


def test_the_lines_the_forms_really_print_are_read_whole():
    """The shapes measured on the three archives here, one of each, so that a change which breaks
    one of them fails rather than quietly reading fewer names."""
    assert read("Лікар /Квазитрофенко А.В./") == ["Квазитрофенко А.В"]
    assert read("Врач______________/Пселлофазюк О.П.") == ["Пселлофазюк О.П"]
    assert read("Лікар:\t[підпис]\tКвазитрофенко А.В.") == ["Квазитрофенко А.В"]
    assert read("Лечащий врач:  м.н.с.  [подпись]  О.П.Пселлофазюк") == ["О.П.Пселлофазюк"]
    assert read("Врач -лаборант : Квазитрофенко  А. В.") == ["Квазитрофенко А. В"]
    assert read("Лікар невролог Пселлофазюк О.П.") == ["Пселлофазюк О.П"]


def test_a_run_of_spaces_inside_a_printed_name_is_closed_up_and_nothing_else_is():
    """A form's columns leave two spaces inside a name and that is the same printed name. Case,
    letters and order are left exactly as printed — the second entry — and the test says so by
    keeping a name whose initials have lost their final dot exactly as the form lost it."""
    assert read("Лікар   Квазитрофенко  А.  В.") == ["Квазитрофенко А. В"]
    assert read("Лікар: Квазитрофенко А.В") == ["Квазитрофенко А.В"]


# --- the reading over a whole archive ------------------------------------------------------

def _an_archive(data_dir: Path, mine: dict, lines: list[list[str]]) -> Path:
    """One archive whose documents carry the given pages of text and no doctor in any field."""
    file = index_path(data_dir, mine["id"])
    index = sqlite3.connect(file)
    with index:
        index.executescript(SCHEMA)
        index.executemany("INSERT INTO meta VALUES (?, ?)",
                          [("built_at", "2026-01-01T00:00:00+00:00"),
                           ("schema_version", str(SCHEMA_VERSION))])  # fmt: skip
        for number, pages in enumerate(lines):
            sha = f"{mine['id']}{number:02d}" * 4
            index.execute(
                """INSERT INTO files (sha256, file_id, source_id, path, category, page_count)
                   VALUES (?, ?, ?, ?, 'scan', 1)""",
                (sha, f"{mine['id'][:4]}{number:04d}", mine["id"], f"/scans/{number}.pdf"),
            )  # fmt: skip
            index.execute(
                """INSERT INTO documents (source_id, file_sha256, first_page, pages, doc_type,
                                          language, title, provider, date, date_precision,
                                          transcribed, primary_copy)
                   VALUES (?, ?, 1, '[1]', 'discharge', 'uk', 'Виписка', ?, '2011-07-09', 'day', 1, 1)""",
                (mine["id"], sha, mine["provider"]),
            )  # fmt: skip
            document = index.execute("SELECT last_insert_rowid()").fetchone()[0]
            for page, text in enumerate(pages, start=1):
                index.execute("INSERT INTO page_texts (document_id, page, text) VALUES (?, ?, ?)",
                              (document, page, text))  # fmt: skip
    index.close()
    return file


def _open(file: Path):
    return sqlite3.connect(f"file:{file}?mode=ro", uri=True)


def test_the_count_is_of_documents_and_not_of_readings(tmp_path):
    """A discharge summary prints the treating doctor twice, once under the summary and once under
    the recommendations. Counting readings said two documents where there is one, and §7 calls a
    count disagreeing with another count on the same page a defect rather than a detail."""
    file = _an_archive(tmp_path, HERS, [
        ["Лікуючий лікар Квазитрофенко А.В. [підпис]", "Лікар: Квазитрофенко А.В."],
    ])  # fmt: skip
    with _open(file) as connection:
        standing = doctors_in_text.who_stands_in_the_text(connection)
    assert [(one["name"], one["documents"]) for one in standing] == [("Квазитрофенко А.В", 1)]
    # Both lines travel with it, because the line is what makes the reading readable as wrong.
    assert len(standing[0]["lines"]) == 2


def test_the_commonest_doctor_stands_first_and_every_name_carries_its_line(tmp_path):
    """The doctor somebody is looking for is the one they saw often, so the list is ordered by how
    many documents name them. And each row carries the printed line: §4's third condition holds
    here only because it does — a name shown without it is a claim with its evidence hidden."""
    file = _an_archive(tmp_path, HERS, [
        ["Лікар Квазитрофенко А.В."], ["Лікар Квазитрофенко А.В."],
        ["Зав. відділенням к.м.н. О.П.Пселлофазюк"],
    ])  # fmt: skip
    with _open(file) as connection:
        standing = doctors_in_text.who_stands_in_the_text(connection)
    assert [one["name"] for one in standing] == ["Квазитрофенко А.В", "О.П.Пселлофазюк"]
    assert [one["documents"] for one in standing] == [2, 1]
    assert standing[0]["lines"] == ["Лікар Квазитрофенко А.В."]
    assert standing[0]["labels"] == ["Лікар"]
    assert standing[1]["labels"] == ["Зав."]


def test_a_copy_is_not_counted_twice(tmp_path):
    """The same result arrives three times — a letter quoting a printout quoting a laboratory —
    and counting all three would say one doctor signed three documents where he signed one."""
    file = _an_archive(tmp_path, HERS, [["Лікар Квазитрофенко А.В."], ["Лікар Квазитрофенко А.В."]])
    index = sqlite3.connect(file)
    with index:
        index.execute("UPDATE documents SET primary_copy = 0 WHERE id = 2")
    index.close()
    with _open(file) as connection:
        standing = doctors_in_text.who_stands_in_the_text(connection)
    assert [(one["name"], one["documents"]) for one in standing] == [("Квазитрофенко А.В", 1)]


def test_the_reading_writes_nothing_at_all(tmp_path):
    """§4's first condition, in the strongest form it can take: there is nothing to undo.

    Nothing is stored, no transcription is touched, no file of decisions is written and no name
    reaches the doctor column. Asserted over the whole archive folder rather than over the one
    file this might have been tempted to write, because the failure to catch would be a file
    nobody thought to look for.
    """
    file = _an_archive(tmp_path, HERS, [["Лікар Квазитрофенко А.В."]])
    before = {path: path.read_bytes() for path in sorted(tmp_path.rglob("*")) if path.is_file()}
    with _open(file) as connection:
        assert doctors_in_text.who_stands_in_the_text(connection)
    after = {path: path.read_bytes() for path in sorted(tmp_path.rglob("*")) if path.is_file()}
    assert after == before


def test_a_name_read_out_of_the_text_never_reaches_the_doctor_column(tmp_path):
    """That column is what the index built out of the fields. A reading out of the text is a
    proposal and the ninth entry says the fourth governs it exactly as it governs a model's, so it
    may stand beside the column and never in it."""
    file = _an_archive(tmp_path, HERS, [["Лікар Квазитрофенко А.В."]])
    with _open(file) as connection:
        assert doctors_in_text.who_stands_in_the_text(connection)
        assert [row[0] for row in connection.execute("SELECT doctor FROM documents")] == [None]


def test_one_archives_doctors_never_come_out_of_anothers_text(tmp_path):
    """The first line of the constitution, over the one new door this adds into an archive.

    `who_stands_in_the_text` takes an open connection and nothing else, so it has no way to open a
    second archive and no default to forget — which is the entry's own prescription, and not a
    filter written where the answer is used. This is the test that proves it rather than the rule
    that asks for it.
    """
    hers = _an_archive(tmp_path, HERS, [["Лікар Квазитрофенко А.В."]])
    his = _an_archive(tmp_path, HIS, [["Лікар Пселлофазюк О.П."]])
    with _open(hers) as connection:
        only_hers = doctors_in_text.who_stands_in_the_text(connection)
    with _open(his) as connection:
        only_his = doctors_in_text.who_stands_in_the_text(connection)
    assert [one["name"] for one in only_hers] == ["Квазитрофенко А.В"]
    assert [one["name"] for one in only_his] == ["Пселлофазюк О.П"]
    said = json.dumps(only_hers, ensure_ascii=False)
    for word in (HIS["doctor"], HIS["provider"], HIS["latin"], HIS["id"]):
        assert word not in said


# --- the page -------------------------------------------------------------------------------

MINE, THEIRS_TOO = THEIRS["one"], THEIRS["two"]
#: A doctor who signed inside the text of one document and stands in no field of it. Invented, and
#: looked for in all three archives on this machine before it was written here (§5).
SIGNED_INSIDE = "Шпакоцвіт Р.Ю"


def _signed_in_the_text(data_dir: Path, mine: dict, line: str) -> None:
    """One more document of an archive, naming a doctor in its text and in no field of it."""
    sha = (mine["id"][::-1] + "eeee")[:8] * 8
    index = sqlite3.connect(index_path(data_dir, mine["id"]))
    with index:
        index.execute(
            """INSERT INTO files (sha256, file_id, source_id, path, category, page_count)
               VALUES (?, ?, ?, ?, 'scan', 1)""",
            (sha, mine["id"][:4] + "eeee", mine["id"], f"/scans/{mine['id']}-signed.pdf"),
        )  # fmt: skip
        index.execute(
            """INSERT INTO documents (source_id, file_sha256, first_page, pages, doc_type,
                                      language, title, provider, date, date_precision,
                                      transcribed, primary_copy)
               VALUES (?, ?, 1, '[1]', 'discharge', 'uk', ?, ?, '2013-02-11', 'day', 1, 1)""",
            (mine["id"], sha, mine["test"], mine["provider"]),
        )  # fmt: skip
        document = index.execute("SELECT last_insert_rowid()").fetchone()[0]
        index.execute("INSERT INTO page_texts (document_id, page, text) VALUES (?, 1, ?)",
                      (document, line))  # fmt: skip
    index.close()


@pytest.fixture
def two_archives_one_signed(tmp_path):
    """Two people on one server, the first with a doctor who signed inside the text of a document.

    The archives of the sweep that guards the wall, because every assertion below about "nothing
    of the other" is then an assertion about strings that cannot appear by accident.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    _both_on_the_list(data_dir, "one")
    for mine in THEIRS.values():
        _a_walled_archive(data_dir, mine)
    _signed_in_the_text(data_dir, MINE, f"Лікуючий лікар {SIGNED_INSIDE}. [підпис]")
    return data_dir


def test_the_page_shows_a_doctor_who_stands_only_in_the_text(two_archives_one_signed):
    """The list that answers the owner looking here for two of his own doctors and finding neither.

    And the two things that stand beside it: where the name came from, in the page's own words,
    and the printed line it was read from — §4's third condition holds for this claim only
    because the evidence is on the screen next to it.
    """
    page = who.who_view(two_archives_one_signed, MINE["id"], kind="doctor")

    assert [one["name"] for one in page["in_the_text"]] == [SIGNED_INSIDE]
    assert page["in_the_text"][0]["documents"] == 1
    assert page["in_the_text"][0]["labels"] == ["Лікуючий лікар"]
    assert page["in_the_text"][0]["lines"] == [f"Лікуючий лікар {SIGNED_INSIDE}. [підпис]"]
    assert "Read out of this document's own text" in page["where_it_came_from"]
    assert "Nobody has confirmed it" in page["where_it_came_from"]


def test_the_doctor_the_index_already_read_is_not_listed_a_second_time(two_archives_one_signed):
    """This list is what cannot reach the page any other way. A name standing in a field is already
    below, counted off that field, and a second row saying the same thing would be two counts of
    one doctor on one page — which §7 calls a defect rather than a detail."""
    _signed_in_the_text(two_archives_one_signed, THEIRS_TOO, f"Лікар {THEIRS_TOO['doctor']}.")
    page = who.who_view(two_archives_one_signed, THEIRS_TOO["id"], kind="doctor")
    assert THEIRS_TOO["doctor"] in [one["name"] for one in page["makers"]]
    assert THEIRS_TOO["doctor"] not in [one["name"] for one in page["in_the_text"]]


def test_the_institutions_tab_is_offered_nothing_out_of_the_text(two_archives_one_signed):
    """A hospital is printed on the letterhead, which the reading already has, and no form prints a
    label beside a signature for a building to stand under. An empty heading there would be the
    page promising something again, which is what this whole page was caught doing."""
    page = who.who_view(two_archives_one_signed, MINE["id"], kind="institution")
    assert page["in_the_text"] == []


def test_the_heading_counts_the_names_that_stand_only_in_the_text(two_archives_one_signed):
    """The sentence under the heading used to end "a name standing only inside a document's own
    text is not on this page", and that stopped being true the moment such names went on it. A
    sentence that goes on describing what the page used to do is the promise it replaced, made a
    second time."""
    page = who.who_view(two_archives_one_signed, MINE["id"], kind="doctor")
    assert "1 name stands only inside the documents' own text" in page["holds"]
    assert "is not on this page" not in page["holds"]


def test_a_name_out_of_the_text_is_offered_against_a_field_by_the_presses_already_there(
        two_archives_one_signed):  # fmt: skip
    """How such a reading ever takes effect: the same word count, the same four presses, the same
    hand. Nothing here settles that the two spellings are one — the pair goes in front of somebody
    and they press — and what is new is only that the spelling out of the text reaches the page."""
    data_dir = two_archives_one_signed
    # The field carries the speciality in front of the name, which is the shape the index's own
    # fallback leaves: an export names who saw the person where the institution goes, speciality
    # and all. The text of the next document prints the name without it, under a label — and this
    # module reads the name and leaves the speciality behind, because a speciality is not part of
    # a name. So the two spellings are the pair `people.worth_joining` was written for.
    speciality = f"уролог {THEIRS_TOO['doctor']}"
    index = sqlite3.connect(index_path(data_dir, THEIRS_TOO["id"]))
    with index:
        index.execute("UPDATE documents SET doctor = ?", (speciality,))
    index.close()
    _signed_in_the_text(data_dir, THEIRS_TOO, f"Лікар {THEIRS_TOO['doctor']}.")
    page = who.who_view(data_dir, THEIRS_TOO["id"], kind="doctor")

    assert [one["name"] for one in page["in_the_text"]] == [THEIRS_TOO["doctor"]]
    offered = [set(family.names) for family in page["proposals"]]
    assert {THEIRS_TOO["doctor"], speciality} in offered
    # And it is offered, not applied: this person's own file of decisions is still empty.
    assert page["groups"] == [] and people.load(data_dir, THEIRS_TOO["id"]) == []


def test_the_page_prints_the_sentence_and_the_line_it_was_read_from(two_archives_one_signed):
    """Drawn, and not only gathered: the sentence and the evidence have to be in the markup a
    person reads, beside the name and not in a footer."""
    from fastapi.testclient import TestClient

    client = TestClient(create_app(two_archives_one_signed, background_jobs=False),
                        base_url="http://localhost:8050")  # fmt: skip
    drawn = client.get("/who", params={"kind": "doctor"})

    assert drawn.status_code == 200
    assert "Named only inside the text" in drawn.text
    assert SIGNED_INSIDE in drawn.text
    # In fragments, because the template escapes the apostrophe of "document's" as a browser needs
    # it: asserting the sentence whole passed on nothing and failed on the escaping.
    for fragment in ("Read out of this document", "under the label the form prints beside a "
                     "signature", "Nobody has confirmed it"):  # fmt: skip
        assert fragment in drawn.text
    # The whole printed line, and not just the label in it: the label is drawn a second time in
    # the row above, so asserting the label alone passed with the line left out altogether.
    assert f"Лікуючий лікар {SIGNED_INSIDE}. [підпис]" in drawn.text
    # To the search and never to the doctor filter of the index, which holds no such name and
    # would answer "no documents" about a doctor the page has just said signed one.
    #
    # **And as a press, never as an address.** The search answers a POST so that what is being
    # looked for stays out of a browser's history, out of what that history syncs to a vendor,
    # and out of the log of any tunnel in front of this dashboard — and this link carried a
    # doctor's surname into one. The name is still the heading; what changed is the verb.
    assert "/search?q=" not in drawn.text, "a name is being put into an address"
    assert f'<input type="hidden" name="q" value="{SIGNED_INSIDE}">' in drawn.text
    assert f'/?doctor={SIGNED_INSIDE.replace(" ", "%20")}' not in drawn.text
    # And nothing of the other person's archive, on the page this reading added a list to.
    for word in (THEIRS_TOO["doctor"], THEIRS_TOO["provider"], THEIRS_TOO["test"]):
        assert word not in drawn.text
