"""Indicators: printed names grouped under one label, proposed by a model, decided by a person."""


from fastapi.testclient import TestClient

from epicrisis import indicators as store
from epicrisis.printed_values import fold
from epicrisis.extract.run import load_extracted, write_document
from epicrisis.index.build import build_index
from epicrisis.indicator_proposals import propose_indicators, unassigned
from epicrisis.query import open_index, values
from epicrisis.web.app import create_app
from test_ask import archive_index  # noqa: F401
from test_extract import FakeExtractBackend, setup  # noqa: F401


class FakeProposals:
    def __init__(self, groups):
        self.groups, self.seen = groups, []

    def group(self, existing, names, workdir):
        self.seen.append((existing, names))
        return {"groups": self.groups, "unclear": []}


def test_one_spelling_belongs_to_one_indicator(tmp_path):
    first = store.upsert(tmp_path, None, "Creatinine", ["Креатинін", "CREATININE"], "approved")
    second = store.upsert(tmp_path, None, "Cystatin C", ["Цистатин С"], "approved")
    store.upsert(tmp_path, second.id, "Cystatin C", ["Цистатин С", "creatinine"], "approved")

    names = {indicator.id: indicator.names for indicator in store.load(tmp_path)}
    assert names[first.id] == ["креатинин"] and sorted(names[second.id]) == ["creatinine", "цистатин с"]
    assert store.approved_names(tmp_path)["creatinine"] == second.id


def test_proposed_spellings_wait_for_a_person(tmp_path):
    indicator = store.upsert(tmp_path, None, "Haemoglobin", ["Гемоглобін"], "approved")
    store.propose_names(tmp_path, indicator.id, ["HGB", "Hemoglobina"])

    assert store.approved_names(tmp_path) == {"гемоглобин": indicator.id}
    store.decide_names(tmp_path, indicator.id, ["HGB"], accept=True)
    store.decide_names(tmp_path, indicator.id, ["Hemoglobina"], accept=False)
    stored = store.load(tmp_path)[0]
    assert sorted(stored.names) == ["hgb", "гемоглобин"] and stored.proposed_names == []
    assert "hemoglobina" not in store.assigned_names(tmp_path)


def test_a_model_fills_groups_it_is_sure_of_and_leaves_the_rest_waiting(archive_index):  # noqa: F811
    data_dir, source, _ = archive_index
    connection = open_index(data_dir)
    printed = store.printed_names(connection)
    connection.close()
    # The fixture also holds measurements of a scan; only the lab name matters here.
    assert "Цистатин С" in [item["name"] for item in printed]

    backend = FakeProposals([{"label": "Cystatin C", "existing_indicator": None, "names": ["Цистатин С"], "sure": True}])
    counts = propose_indicators(data_dir, printed, backend, data_dir)

    assert counts["new_indicators"] == 1 and "Цистатин С | мг/л | 1" in backend.seen[0][1]
    assert len(backend.seen) == 1
    indicator = store.load(data_dir)[0]
    # A group the model is sure of applies at once, marked as not looked at by a person.
    assert (indicator.status, indicator.source, indicator.reviewed, indicator.names) == ("approved", "model", False, ["цистатин с"])
    assert store.approved_names(data_dir) == {"цистатин с": indicator.id}
    assert "цистатин с" not in [item["folded"] for item in unassigned(data_dir, printed)]

    build_index(data_dir, [source])
    connection = open_index(data_dir)
    assert [item["indicator_id"] for item in values(connection, indicator="cystatin-c")] == ["cystatin-c"]
    connection.close()


def test_an_unsure_group_waits_for_a_person(archive_index):  # noqa: F811
    data_dir, _, _ = archive_index
    connection = open_index(data_dir)
    printed = store.printed_names(connection)
    connection.close()
    store.upsert(data_dir, None, "Cystatin C", ["цистатин с"], "approved")

    backend = FakeProposals([{"label": "Cystatin C", "existing_indicator": "cystatin-c", "names": ["Analyte 2"], "sure": False}])
    counts = propose_indicators(data_dir, printed, backend, data_dir)

    indicator = store.load(data_dir)[0]
    assert counts["waiting"] == 1 and indicator.proposed_names == ["analyte 2"] and "analyte 2" not in indicator.names


def test_indicators_page_edits_and_decides(archive_index):  # noqa: F811
    data_dir, _, _ = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    page = client.get("/indicators").text
    assert "names in no indicator" in page and "Цистатин С" in page

    client.post("/indicators", data={"action": "save", "label": "Cystatin C", "names": "Цистатин С", "status": "approved"})
    indicator = store.load(data_dir)[0]
    assert indicator.names == ["цистатин с"] and indicator.status == "approved"

    store.propose_names(data_dir, indicator.id, ["Cistatina C"])
    page = client.get("/indicators").text
    assert "1 to decide" in page and "cistatina c" in page  # a spelling with no values yet is shown folded
    client.post("/indicators", data={"action": "accept", "indicator_id": indicator.id, "names": "cistatina c"})
    assert sorted(store.load(data_dir)[0].names) == ["cistatina c", "цистатин с"]

    # One click takes a spelling out again, and one click says the group has been looked at.
    client.post("/indicators", data={"action": "drop", "indicator_id": indicator.id, "spelling": "cistatina c"})
    assert store.load(data_dir)[0].names == ["цистатин с"]
    store.upsert(data_dir, indicator.id, "Cystatin C", ["Цистатин С"], "approved", source="model", reviewed=False)
    assert "not looked at yet" in client.get("/indicators").text
    client.post("/indicators", data={"action": "reviewed", "indicator_id": indicator.id})
    assert store.load(data_dir)[0].reviewed is True

    client.post("/indicators", data={"action": "delete", "indicator_id": indicator.id})
    assert store.load(data_dir) == []


def test_the_same_name_in_urine_and_in_blood_stays_apart(archive_index):  # noqa: F811
    from epicrisis.index.build import material_of

    data_dir, source, labs = archive_index
    document = load_extracted(data_dir / "sources" / source.id / "extracted", labs)["documents"][0]
    template = document["observations"][0]
    document["observations"] = [
        dict(template, name_as_printed="Білок", value_as_printed="0,033", unit_as_printed="г/л", table_as_printed="ЗАГАЛЬНИЙ АНАЛІЗ СЕЧІ"),
        dict(template, name_as_printed="Білок", value_as_printed="71", unit_as_printed="г/л", table_as_printed="Біохімія крові"),
    ]
    write_document(data_dir / "sources" / source.id / "extracted", labs, document)
    store.upsert(data_dir, None, "Protein", ["Білок"], "approved")
    build_index(data_dir, [source])

    assert material_of({"table_as_printed": "Análisis de orina"}, {}) == "urine"
    assert material_of({"table_as_printed": "Bioquímica"}, {"title_as_printed": "Аналіз калу"}) == "stool"
    assert material_of({"table_as_printed": "Biochemistry"}, {}) is None  # a heading naming none says none
    # Blood is read from a heading, never from the name of a value: on a urine strip "Кров" is
    # the test, and "Реакція на приховану кров" is printed on a form for stool.
    assert material_of({"table_as_printed": "Біохімія крові"}, {}) == "blood"
    assert material_of({"name_as_printed": "Кров"}, {"title_as_printed": "АНАЛІЗ СЕЧІ"}) == "urine"
    assert material_of({"name_as_printed": "Occult Blood"}, {"title_as_printed": "Аналіз калу"}) == "stool"
    assert material_of({"name_as_printed": "Blood"}, {}) is None

    connection = open_index(data_dir)
    history = values(connection, indicator="protein")
    assert sorted((item["material"], item["value"]) for item in history) == [("blood", "71"), ("urine", "0,033")]
    assert [item["value"] for item in values(connection, indicator="protein", material="urine")] == ["0,033"]
    assert [item["value"] for item in values(connection, indicator="protein", material="blood")] == ["71"]
    connection.close()


def test_coverage_finds_lookalikes_left_outside(tmp_path):
    from epicrisis.printed_values import fold

    printed = [
        {"name": name, "folded": fold(name), "times": times, "units": []}
        for name, times in [("Лейкоцити", 9), ("Лейкоцити (мікроскопія)", 7), ("WBC", 4), ("Еритроцити", 5)]
    ]
    indicator = store.upsert(tmp_path, None, "Leukocyte", ["Лейкоцити", "WBC"], "approved")

    related = store.coverage(tmp_path, printed)[indicator.id]

    # The spelling left outside is offered; a name of another test is not.
    assert [item["name"] for item in related] == ["Лейкоцити (мікроскопія)"]
    assert related[0]["indicator"] is None

    other = store.upsert(tmp_path, None, "Urine leukocyte count", ["Лейкоцити (мікроскопія)"], "approved")
    assert store.coverage(tmp_path, printed)[indicator.id][0]["indicator"] == other.id


def test_a_second_reader_is_shown_the_whole_group_including_what_waits(tmp_path):
    """A reader asked about half a group answers about half a group."""
    from epicrisis.indicator_check import _block, groups_to_check, names_key

    store.upsert(tmp_path, None, "Creatinine", ["Креатинін"], "approved")
    indicator = store.load(tmp_path)[0]
    store.propose_names(tmp_path, indicator.id, ["Creatinina"])
    printed = [{"folded": "креатинин", "name": "Креатинін", "units": ["мкмоль/л"], "times": 9},
               {"folded": "creatinina", "name": "Creatinina", "units": ["mg/dL"], "times": 4}]  # fmt: skip

    groups = groups_to_check(tmp_path, printed)

    # One spelling plus one waiting is a grouping, and it goes.
    assert len(groups) == 1 and len(groups[0]["names"]) == 2
    assert [item["waiting"] for item in groups[0]["names"]] == [False, True]
    block = _block(1, groups[0])
    assert "Creatinina" in block and "waiting for a person" in block
    assert "Креатинін" in block and block.count("waiting for a person") == 1

    # A spelling on its own is not a grouping and never goes.
    store.upsert(tmp_path, None, "Cystatin C", ["Цистатин С"], "approved")
    assert len(groups_to_check(tmp_path, printed)) == 1
    assert names_key(groups[0]) == "creatinina|креатинин"


def test_only_what_both_readers_agree_on_is_put_into_use(tmp_path):
    """The point of the second reader: it decides whose time is spent, not what is true."""
    from epicrisis.indicator_check import FILE_NAME, apply_agreed
    from epicrisis.records import append_line

    kept = store.upsert(tmp_path, None, "Creatinine", ["Креатинін"], "approved")
    store.propose_names(tmp_path, kept.id, ["Creatinina", "Cr."])
    guessed = store.upsert(tmp_path, None, "Lymphocyte", ["Лімфоцити", "Linfocitos"], "proposed", source="model")
    doubted = store.upsert(tmp_path, None, "APTT", ["АЧТЧ", "PTT"], "proposed", source="model")

    append_line(tmp_path / FILE_NAME, {"indicator": kept.id, "agrees": False, "names_key": "x",
                                       "does_not_belong": [{"name": "Cr.", "why": "could be chromium"}]})  # fmt: skip
    append_line(tmp_path / FILE_NAME, {"indicator": guessed.id, "agrees": True, "names_key": "y", "does_not_belong": []})
    append_line(tmp_path / FILE_NAME, {"indicator": doubted.id, "agrees": False, "names_key": "z",
                                       "does_not_belong": [{"name": "PTT", "why": "a different assay"}]})  # fmt: skip

    counts = apply_agreed(tmp_path)

    by_id = {item.id: item for item in store.load(tmp_path)}
    # The spelling nobody objected to is in use; the doubted one still waits for a person.
    assert "creatinina" in by_id[kept.id].names and by_id[kept.id].proposed_names == ["cr."]
    assert counts["spellings_added"] == 1 and counts["spellings_left_waiting"] == 1
    # A group both readers agree on is in use; one with an objection is not.
    assert by_id[guessed.id].status == "approved" and by_id[doubted.id].status == "proposed"
    assert counts["groups_approved"] == 1 and counts["groups_left"] == 1
    # And nothing here counts as a person having looked.
    assert by_id[guessed.id].reviewed is False


def test_a_group_nobody_read_again_is_left_alone(tmp_path):
    from epicrisis.indicator_check import apply_agreed

    store.upsert(tmp_path, None, "Lymphocyte", ["Лімфоцити", "Linfocitos"], "proposed", source="model")
    counts = apply_agreed(tmp_path)

    assert counts["spellings_added"] == 0 and counts["groups_approved"] == 0
    # It is counted as still waiting, and it is left exactly as it was.
    assert counts["groups_left"] == 1
    assert store.load(tmp_path)[0].status == "proposed"


def test_nothing_but_names_units_and_counts_ever_leaves_for_the_web(tmp_path):
    """The only step that talks to anything but Anthropic, and what it is allowed to carry."""
    from epicrisis.indicator_web_check import (SYNONYM_PROMPT, _test_block, names_to_settle,
                                               tests_to_look_up, web_command)  # fmt: skip

    store.upsert(tmp_path, None, "Oxalate", ["Оскалаты"], "proposed", source="model")
    store.upsert(tmp_path, None, "Creatinine", ["Креатинін", "Creatinina"], "approved")
    # Folded here the way the index folds them, rather than by hand: the pairs of letters this
    # program treats as one are its own business and have changed before.
    printed = [{"folded": fold("Оскалаты"), "name": "Оскалаты", "units": ["мг/с"], "times": 1},
               {"folded": fold("Креатинін"), "name": "Креатинін", "units": ["мкмоль/л"], "times": 9},
               {"folded": fold("Creatinina"), "name": "Creatinina", "units": ["mg/dL"], "times": 4}]  # fmt: skip

    # One spelling is the question the web answers; a grouping is not.
    alone = names_to_settle(tmp_path, printed)
    assert [item["name"] for item in alone] == ["Оскалаты"]

    # And a group with values is worth asking what else it is called.
    looked_up = tests_to_look_up(tmp_path, printed)
    assert [item["label"] for item in looked_up] == ["Creatinine"]
    block = _test_block(1, looked_up[0])
    assert "Creatinine" in block and "Креатинін" in block and "мкмоль/л" in block
    for forbidden in ("2019", "sha256", ".pdf", "Lindqvist"):
        assert forbidden not in block

    # The command reaches the web and nothing else: no files, no shell, no archive.
    command = web_command("claude", "claude-opus-5", SYNONYM_PROMPT, {"type": "object"})
    assert command[command.index("--tools") + 1] == "WebSearch"
    assert command[command.index("--allowedTools") + 1] == "WebSearch"
    assert "Read" not in command and "Bash" not in command


def test_a_name_from_a_reference_is_never_a_spelling_this_archive_holds(tmp_path):
    """It helps place a name nobody has seen. It is not a thing any form printed."""
    from epicrisis.indicator_check import fold
    from epicrisis.indicator_web_check import SYNONYM_FILE, load_web_names
    from epicrisis.indicator_proposals import _also_known_as
    from epicrisis.records import append_line

    indicator = store.upsert(tmp_path, None, "Creatinine", ["Креатинін"], "approved")
    append_line(tmp_path / SYNONYM_FILE, {"indicator": indicator.id, "label": "Creatinine",
                                          "usual_name": "Creatinine",
                                          "also_printed_as": ["CREA", "Kreatinin"],
                                          "found_in": "Labcorp 001370"})  # fmt: skip

    # It is kept apart: the indicator itself holds only what the archive printed.
    assert store.load(tmp_path)[0].names == ["креатинин"]
    assert store.load(tmp_path)[0].proposed_names == []
    assert store.approved_names(tmp_path) == {"креатинин": indicator.id}
    assert fold("CREA") not in store.assigned_names(tmp_path)

    # And it reaches the model that places new names, marked as coming from a reference.
    shown = _also_known_as(load_web_names(tmp_path)[indicator.id])
    assert "CREA" in shown and "Kreatinin" in shown and "from a reference" in shown
    assert _also_known_as(None) == "" and _also_known_as({"also_printed_as": []}) == ""


def test_a_reference_settles_a_group_a_second_reader_cannot_see(tmp_path):
    """One spelling is no grouping, so agreement there can only come from a catalogue."""
    from epicrisis.indicator_check import apply_agreed
    from epicrisis.indicator_web_check import FILE_NAME as WEB_FILE
    from epicrisis.records import append_line

    real = store.upsert(tmp_path, None, "Oxalate", ["Oxalates urine 24h"], "proposed", source="model")
    junk = store.upsert(tmp_path, None, "Vish hb", ["виш. hb в ер."], "proposed", source="model")
    unsure = store.upsert(tmp_path, None, "Ax", ["ax"], "proposed", source="model")
    for indicator, verdict, found in ((real, "a test", "Labcorp 003970"), (junk, "not a test", None),
                                      (unsure, "unclear", None)):  # fmt: skip
        append_line(tmp_path / WEB_FILE, {"folded": indicator.names[0], "indicator": indicator.id,
                                          "verdict": verdict, "found_in": found, "why": "…"})  # fmt: skip

    counts = apply_agreed(tmp_path)

    by_id = {item.id: item for item in store.load(tmp_path)}
    assert by_id[real.id].status == "approved"  # a catalogue names it
    assert by_id[junk.id].status == "proposed"  # a reference says it is no test at all
    assert by_id[unsure.id].status == "proposed"  # and one it could not settle keeps waiting
    assert counts["groups_approved"] == 1 and counts["groups_confirmed_by_a_reference"] == 1
    assert counts["groups_left"] == 2
    # Nothing here counts as a person having looked at it.
    assert by_id[real.id].reviewed is False


def test_why_a_group_is_in_use_is_written_on_it_and_shown(tmp_path):
    """The reference's own words, kept on the indicator so the page needs no second file."""
    from fastapi.testclient import TestClient

    from epicrisis.indicator_check import apply_agreed
    from epicrisis.indicator_web_check import FILE_NAME as WEB_FILE
    from epicrisis.records import append_line
    from epicrisis.web.app import create_app

    real = store.upsert(tmp_path, None, "Oxalate", ["Oxalates urine 24h"], "proposed", source="model")
    junk = store.upsert(tmp_path, None, "Lymph nodes", ["лимфатични вузли"], "proposed", source="model")
    append_line(tmp_path / WEB_FILE, {"folded": real.names[0], "indicator": real.id, "verdict": "a test",
                                      "usual_name": "Oxalate, Quantitative, 24-Hour Urine",
                                      "found_in": "Labcorp 003970", "why": "Urinary oxalate in mg/24 h."})  # fmt: skip
    append_line(tmp_path / WEB_FILE, {"folded": junk.names[0], "indicator": junk.id, "verdict": "not a test",
                                      "usual_name": None, "found_in": None,
                                      "why": "An anatomical region from a heading, with no unit."})  # fmt: skip

    apply_agreed(tmp_path)

    by_id = {item.id: item for item in store.load(tmp_path)}
    assert "Labcorp 003970" in by_id[real.id].note and "Oxalate, Quantitative" in by_id[real.id].note
    assert "no test" in by_id[junk.id].note and "no unit" in by_id[junk.id].note

    # A note survives an edit that does not mention it: it used to be cleared by every caller.
    store.upsert(tmp_path, real.id, "Oxalate", real.names, "approved")
    kept = next(item for item in store.load(tmp_path) if item.id == real.id)
    assert "Labcorp 003970" in kept.note

    page = TestClient(create_app(tmp_path / "data", background_jobs=False),
                      base_url="http://localhost:8050").get("/indicators")  # fmt: skip
    assert page.status_code == 200


class FakeWebBackend:
    """Stands in for a model with the web. Records everything it was handed."""

    name = "fake"
    model = "fake-opus"
    executable = "claude"
    timeout_seconds = 1

    def __init__(self, verdicts=None, synonyms=None):
        self.verdicts, self.synonyms, self.sent = verdicts or {}, synonyms or {}, []

    def settle(self, names, workdir):
        self.sent.append(names)
        out = []
        for line in names.splitlines():
            ref, name = (part.strip() for part in line.split("|")[:2])
            verdict, found = self.verdicts.get(name, ("unclear", None))
            out.append({"ref": ref, "verdict": verdict, "usual_name": None, "found_in": found, "why": "…"})
        return {"names": out}


def test_the_web_pass_writes_a_verdict_for_every_name_and_asks_none_of_them_twice(tmp_path):
    from epicrisis.indicator_web_check import load_web_checks, settle_names

    store.upsert(tmp_path, None, "Oxalate", ["Oxalates urine 24h"], "proposed", source="model")
    store.upsert(tmp_path, None, "Age", ["Edad"], "proposed", source="model")
    printed = [{"folded": "oxalates urine 24h", "name": "Oxalates urine 24h", "units": ["mg/24h"], "times": 3},
               {"folded": "edad", "name": "Edad", "units": ["años"], "times": 1}]  # fmt: skip
    backend = FakeWebBackend({"Oxalates urine 24h": ("a test", "Labcorp 003970"), "Edad": ("not a test", None)})

    counts = settle_names(tmp_path, printed, backend, tmp_path)

    assert counts == {"names": 2, "a test": 1, "not a test": 1, "unclear": 0, "batches": 1}
    settled = load_web_checks(tmp_path)
    assert settled["oxalates urine 24h"]["found_in"] == "Labcorp 003970"
    assert settled["edad"]["verdict"] == "not a test"
    assert all(line["by"] == "fake-opus" and line["at"] for line in settled.values())

    # What was sent: names, units and counts, and not one thing more.
    sent = "\n".join(backend.sent)
    assert "Oxalates urine 24h | mg/24h | 3" in sent and "Edad | años | 1" in sent
    for forbidden in ("2019", "sha256", ".pdf", "Lindqvist", "Anders"):
        assert forbidden not in sent

    # Nothing is asked a second time.
    again = settle_names(tmp_path, printed, backend, tmp_path)
    assert again["names"] == 0 and len(backend.sent) == 1


def test_a_verdict_for_a_name_that_was_not_asked_about_is_dropped(tmp_path):
    from epicrisis.indicator_web_check import load_web_checks, settle_names

    store.upsert(tmp_path, None, "Oxalate", ["Oxalates urine 24h"], "proposed", source="model")
    printed = [{"folded": "oxalates urine 24h", "name": "Oxalates urine 24h", "units": [], "times": 1}]

    class Wanders(FakeWebBackend):
        def settle(self, names, workdir):
            self.sent.append(names)
            return {"names": [{"ref": "999", "verdict": "a test", "usual_name": None, "found_in": None, "why": "…"},
                              {"ref": "1", "verdict": "not a real verdict", "usual_name": None,
                               "found_in": None, "why": "…"}]}  # fmt: skip

    counts = settle_names(tmp_path, printed, Wanders(), tmp_path)

    assert counts["a test"] == 0 and counts["not a test"] == 0 and counts["unclear"] == 0
    assert load_web_checks(tmp_path) == {}


def test_names_a_reference_gives_are_kept_apart_and_never_repeat_the_archive_s_own(tmp_path):
    from epicrisis.classify import backend as classify_backend
    from epicrisis.indicator_web_check import WebCheckBackend, load_web_names, look_up_names

    indicator = store.upsert(tmp_path, None, "Creatinine", ["Креатинін"], "approved")
    printed = [{"folded": "креатинин", "name": "Креатинін", "units": ["мкмоль/л"], "times": 9}]
    handed = {}

    def fake_run(command, request, workdir, timeout):
        handed["command"], handed["request"] = command, request
        return {"tests": [{"ref": "1", "usual_name": "Creatinine",
                           "also_printed_as": ["CREA", "Креатинін", "  ", "Kreatinin"],
                           "found_in": "Labcorp 001370"}]}, "fake-opus"  # fmt: skip

    import epicrisis.indicator_web_check as web
    run_before = web.run_claude
    web.run_claude = fake_run
    try:
        counts = look_up_names(tmp_path, printed, WebCheckBackend(model="fake-opus"), tmp_path)
    finally:
        web.run_claude = run_before

    # A spelling the archive already holds is not handed back to it as a discovery.
    found = load_web_names(tmp_path)[indicator.id]
    assert found["also_printed_as"] == ["CREA", "Kreatinin"]
    assert counts == {"tests": 1, "with_names": 1, "names": 2, "batches": 1}

    # None of it becomes a spelling in use, and the request carried no archive of anybody's.
    assert store.load(tmp_path)[0].names == ["креатинин"]
    assert store.approved_names(tmp_path) == {"креатинин": indicator.id}
    assert "Креатинін" in handed["request"] and "мкмоль/л" in handed["request"]
    assert handed["command"][handed["command"].index("--tools") + 1] == "WebSearch"
    assert classify_backend.STRONG_MODEL not in handed["command"]  # the chosen model, not a constant


def test_a_group_is_asked_about_once_and_again_only_when_its_names_change(tmp_path):
    """The rule built for the second archive: a verdict is about a set of names, not a label."""
    from epicrisis.indicator_check import check_groups, load_checks

    indicator = store.upsert(tmp_path, None, "Creatinine", ["Креатинін", "Creatinina"], "approved")
    printed = [{"folded": "креатинин", "name": "Креатинін", "units": ["мкмоль/л"], "times": 9},
               {"folded": "creatinina", "name": "Creatinina", "units": ["mg/dL"], "times": 4},
               {"folded": "crea", "name": "CREA", "units": ["mg/dL"], "times": 2}]  # fmt: skip

    class Reader:
        name, model = "fake", "fake-fable"

        def __init__(self):
            self.seen = []

        def check(self, groups, workdir):
            self.seen.append(groups)
            return {"groups": [{"ref": "1", "agrees": True, "does_not_belong": []}]}

    reader = Reader()
    first = check_groups(tmp_path, printed, reader, tmp_path)
    assert first == {"groups": 1, "agreed": 1, "disagreed": 0, "names_questioned": 0, "batches": 1}
    assert load_checks(tmp_path)[indicator.id]["agrees"] is True

    # Asked again with nothing changed, it is not asked again.
    assert check_groups(tmp_path, printed, reader, tmp_path)["groups"] == 0
    assert len(reader.seen) == 1

    # A spelling waiting for a person changes the question, so the question is put again.
    store.propose_names(tmp_path, indicator.id, ["CREA"])
    third = check_groups(tmp_path, printed, reader, tmp_path)
    assert third["groups"] == 1 and len(reader.seen) == 2
    assert "CREA" in reader.seen[-1] and "waiting for a person" in reader.seen[-1]


def test_a_reader_may_only_object_to_names_it_was_shown(tmp_path):
    from epicrisis.indicator_check import apply_agreed, check_groups, load_checks

    indicator = store.upsert(tmp_path, None, "APTT", ["АЧТЧ", "PTT"], "approved")
    printed = [{"folded": "ачтч", "name": "АЧТЧ", "units": ["с"], "times": 5},
               {"folded": "ptt", "name": "PTT", "units": ["s"], "times": 3}]  # fmt: skip

    class Wanders:
        name, model = "fake", "fake-fable"

        def check(self, groups, workdir):
            return {"groups": [
                {"ref": "1", "agrees": False, "does_not_belong": [
                    {"name": "PTT", "why": "a different assay"},
                    {"name": "Something nobody printed", "why": "…"},
                ]},
                {"ref": "99", "agrees": False, "does_not_belong": [{"name": "x", "why": "…"}]},
            ]}  # fmt: skip

    counts = check_groups(tmp_path, printed, Wanders(), tmp_path)

    # The objection to a name it was never shown is dropped, and so is a block with no group.
    assert counts["disagreed"] == 1 and counts["names_questioned"] == 1
    said = load_checks(tmp_path)[indicator.id]
    assert [item["name"] for item in said["does_not_belong"]] == ["PTT"]

    # And a group with an objection is not put into use by the step that applies agreement.
    store.upsert(tmp_path, indicator.id, "APTT", indicator.names, "proposed", source="model", reviewed=False)
    assert apply_agreed(tmp_path)["groups_approved"] == 0
    assert next(item for item in store.load(tmp_path) if item.id == indicator.id).status == "proposed"


def test_one_run_of_a_step_at_a_time(tmp_path):
    """Two runs of the same step raced over one archive's ledgers and over one temporary file."""
    import os

    import pytest

    from epicrisis.runs import Busy, holder, one_at_a_time, temporary_name

    lock = tmp_path / "step.lock"
    with one_at_a_time(lock, "Doing the thing"):
        assert holder(lock) == os.getpid()
        with pytest.raises(Busy, match="already running"):
            with one_at_a_time(lock, "Doing the thing"):
                raise AssertionError("two runs held the same lock")
    assert not lock.exists() and holder(lock) is None

    # A lock left behind by a process that is gone is not a lock.
    lock.write_text('{"pid": 999999, "started_at": "then"}', encoding="utf-8")
    with one_at_a_time(lock, "Doing the thing"):
        assert holder(lock) == os.getpid()

    # And two writers never share the name they write under before the rename.
    assert temporary_name(tmp_path / "index.sqlite").name.endswith(f".{os.getpid()}.tmp")


def test_two_writers_of_the_vocabulary_do_not_lose_each_other_s_edits(tmp_path):
    """indicators.json is one file for the whole server, and every change reads it first."""
    import pytest

    from epicrisis import indicators as store
    from epicrisis.runs import Busy

    store.upsert(tmp_path, None, "Haemoglobin", ["Гемоглобін"], "approved")
    with store.editing(tmp_path):
        with pytest.raises(Busy, match="Editing the indicators"):
            store.upsert(tmp_path, None, "Creatinine", ["Креатинін"], "approved")
    assert [item.label for item in store.load(tmp_path)] == ["Haemoglobin"]
