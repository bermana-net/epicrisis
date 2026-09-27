"""The rule registry: what a rule file is, and what happens to one that is wrong."""

import pytest

from epicrisis import rules
from epicrisis.rules.kinds import KINDS, Kind
from test_ask import archive_index  # noqa: F401
from test_extract import FakeExtractBackend, setup  # noqa: F401

GOOD = """+++
id = "a-test-rule"
name = "A test rule"
summary = "One line beside the switch."
kind = "for-the-tests"
attaches = "value"
order = 3
settles = "One sentence saying what would settle a finding of it."
does = "marks"
at = "validate"
on_by_default = false
[settings]
how_far = 2.5
words = ["one", "two"]
+++

# What it looks at

Two paragraphs a person can read before deciding to turn it on.

## How it can be wrong

It cannot tell a rare form from a misreading.
"""


@pytest.fixture(autouse=True)
def a_kind_to_test_with():
    KINDS["for-the-tests"] = Kind(name="for-the-tests", does="marks", at="validate", looks_at="one document",
                                  about="only for the tests",
                                  settings={"how_far": 10.0, "words": [], "at_least": 2})  # fmt: skip
    yield
    KINDS.pop("for-the-tests", None)


def write(folder, name, text):
    (folder / name).write_text(text, encoding="utf-8")
    return folder


def test_a_rule_is_a_header_a_machine_reads_and_a_body_a_person_reads(tmp_path):
    loaded = rules.load(shipped_dir=write(tmp_path, "a-test-rule.md", GOOD))
    assert not loaded.problems and len(loaded) == 1
    rule = loaded.get("a-test-rule")
    assert (rule.name, rule.kind, rule.does, rule.at, rule.on_by_default) == ("A test rule", "for-the-tests", "marks", "validate", False)
    assert rule.summary == "One line beside the switch."
    assert rule.attaches == "value" and rule.order == 3 and rule.settles.startswith("One sentence")
    # What the file says, over what the kind defaults to, and the kind's own for the rest.
    assert rule.settings == {"how_far": 2.5, "words": ["one", "two"], "at_least": 2}
    assert rule.about.startswith("# What it looks at") and "wrong" in rule.about
    assert rule.shipped and rule.check.does == "marks"


@pytest.mark.parametrize(
    "broken, says",
    [
        (GOOD.replace('kind = "for-the-tests"', 'kind = "invented"'), "no such kind"),
        (GOOD.replace('does = "marks"', 'does = "decides"'), "does"),
        (GOOD.replace('does = "marks"', 'does = "places"'), "marks"),  # the kind marks, the file claims otherwise
        (GOOD.replace('at = "validate"', 'at = "whenever"'), "at"),
        (GOOD.replace('at = "validate"', 'at = "charts"'), "runs at"),  # the kind runs elsewhere
        (GOOD.replace('at = "validate"', ""), "at is missing"),
        (GOOD.replace("how_far = 2.5", "how_far = true"), "how_far"),
        (GOOD.replace("how_far = 2.5", 'how_far = "far"'), "how_far"),
        (GOOD.replace("how_far = 2.5", "hoW_far = 2.5"), "hoW_far"),  # a misspelt setting is not silently ignored
        (GOOD.replace('name = "A test rule"', ""), "name is missing"),
        (GOOD.replace('summary = "One line beside the switch."', ""), "summary is missing"),
        (GOOD.replace('settles = "One sentence saying what would settle a finding of it."', ""), "settles is missing"),
        (GOOD.replace('attaches = "value"', 'attaches = "somewhere"'), "attaches"),
        (GOOD.replace('id = "a-test-rule"', 'id = "another-name"'), "a-test-rule"),
        (GOOD.replace("+++", "", 1), "header"),
        (GOOD.replace("how_far = 2.5", "how_far = "), "TOML"),
        (GOOD.split("+++")[0] + "+++" + GOOD.split("+++")[1] + "+++", "nothing is written"),
    ],
)
def test_a_rule_file_that_is_wrong_is_reported_and_never_used(tmp_path, broken, says):
    loaded = rules.load(shipped_dir=write(tmp_path, "a-test-rule.md", broken))
    assert len(loaded) == 0
    assert len(loaded.problems) == 1 and says in loaded.problems[0]


def test_a_broken_file_does_not_take_the_good_ones_with_it(tmp_path):
    write(tmp_path, "a-test-rule.md", GOOD)
    write(tmp_path, "broken.md", "+++\nnot toml at all\n+++\n\nbody\n")
    loaded = rules.load(shipped_dir=tmp_path)
    assert [rule.id for rule in loaded] == ["a-test-rule"] and len(loaded.problems) == 1


def test_an_archive_may_add_rules_of_its_own_and_may_not_bring_code(tmp_path):
    shipped, data = tmp_path / "shipped", tmp_path / "data"
    (data / rules.FOLDER_NAME).mkdir(parents=True)
    shipped.mkdir()
    write(shipped, "a-test-rule.md", GOOD)
    write(data / rules.FOLDER_NAME, "mine.md", GOOD.replace("a-test-rule", "mine"))
    # A rule of this archive's own that names a kind nobody wrote is refused, which is what
    # keeps a shared rule a thing you read rather than a thing that runs.
    write(data / rules.FOLDER_NAME, "clever.md", GOOD.replace("a-test-rule", "clever").replace("for-the-tests", "os.system"))

    loaded = rules.load(data_dir=data, shipped_dir=shipped)
    assert [rule.id for rule in loaded] == ["a-test-rule", "mine"]
    assert [rule.shipped for rule in loaded] == [True, False]
    assert len(loaded.problems) == 1 and "no such kind" in loaded.problems[0]


def test_one_id_belongs_to_one_rule(tmp_path):
    shipped, data = tmp_path / "shipped", tmp_path / "data"
    (data / rules.FOLDER_NAME).mkdir(parents=True)
    shipped.mkdir()
    write(shipped, "a-test-rule.md", GOOD)
    write(data / rules.FOLDER_NAME, "a-test-rule.md", GOOD)
    loaded = rules.load(data_dir=data, shipped_dir=shipped)
    assert len(loaded) == 1 and loaded.get("a-test-rule").shipped
    assert "already a rule" in loaded.problems[0]


def test_no_folder_and_no_rules_are_not_a_failure(tmp_path):
    loaded = rules.load(data_dir=tmp_path / "nowhere", shipped_dir=tmp_path / "neither")
    assert len(loaded) == 0 and not loaded.problems


def test_every_rule_that_ships_loads():
    """The rules in the repository are read on every start, so a broken one is a broken start."""
    loaded = rules.load()
    assert not loaded.problems
    assert all(rule.check.run is not None and rule.cost for rule in loaded)


def test_a_step_asks_for_its_own_rules_and_gets_no_others(tmp_path):
    write(tmp_path, "a-test-rule.md", GOOD)
    write(tmp_path, "drawn.md", GOOD.replace("a-test-rule", "drawn").replace(
        'kind = "for-the-tests"', 'kind = "value-against-its-printed-range"').replace(
        'does = "marks"', 'does = "places"').replace('at = "validate"', 'at = "charts"').replace(
        "how_far = 2.5", "same_band = 0.2").replace('words = ["one", "two"]', "bands_to_see_a_scale = 3"))
    loaded = rules.load(shipped_dir=tmp_path)
    assert not loaded.problems
    assert [rule.id for rule in loaded.at("validate")] == ["a-test-rule"]
    assert [rule.id for rule in loaded.at("charts")] == ["drawn"]
    assert loaded.get("drawn").settings == {"same_band": 0.2, "bands_to_see_a_scale": 3}


def test_a_switch_belongs_to_a_rule_and_survives_rules_coming_and_going(tmp_path):
    """Kept by id, so a rule added later arrives with its own answer and a deleted one is dust."""
    from epicrisis import settings

    data = tmp_path / "data"
    data.mkdir()
    loaded = rules.load(shipped_dir=write(tmp_path, "a-test-rule.md", GOOD))
    rule = loaded.get("a-test-rule")

    assert settings.rule_on(data, rule) is False  # its own default, nobody having said otherwise
    assert settings.rules_on(data, loaded, "validate") == []

    settings.set_rule_on(data, rule.id, True)
    assert settings.rule_on(data, rule) is True
    assert [item.id for item in settings.rules_on(data, loaded, "validate")] == ["a-test-rule"]
    assert settings.rules_on(data, loaded, "charts") == []  # another step's rules are not this step's

    # An answer stored for a rule that no longer exists says nothing about the ones that do.
    settings.set_rule_on(data, "a-rule-since-deleted", True)
    assert [item.id for item in settings.rules_on(data, loaded, "validate")] == ["a-test-rule"]


def test_a_rule_that_costs_a_model_s_reading_is_not_stored_on_one_click(tmp_path, monkeypatch):
    """A switch that means hours of reading, and money on an API key, is asked about first."""
    from fastapi.testclient import TestClient

    from epicrisis import settings
    from epicrisis.web.app import create_app

    data = tmp_path / "data"
    (data / rules.FOLDER_NAME).mkdir(parents=True)
    KINDS["for-the-tests"] = Kind(name="for-the-tests", does="marks", at="extract", looks_at="one document",
                                  about="only for the tests", settings={})  # fmt: skip
    write(data / rules.FOLDER_NAME, "costly.md",
          GOOD.replace("a-test-rule", "costly").replace('at = "validate"', 'at = "extract"')
              .replace("[settings]\nhow_far = 2.5\nwords = [\"one\", \"two\"]\n", ""))  # fmt: skip
    loaded = rules.load(data_dir=data, shipped_dir=tmp_path / "none")
    assert not loaded.problems and loaded.get("costly").costly

    client = TestClient(create_app(data), base_url="http://127.0.0.1:8050")
    head = {"Sec-Fetch-Site": "same-origin"}
    asked = client.post("/settings", data={"rule_on": "costly", "shown": "costly", "tab": "rules"},
                        headers=head, follow_redirects=False)  # fmt: skip
    assert asked.status_code == 200 and "read again by a model" in asked.text
    assert settings.rule_on(data, loaded.get("costly")) is False  # nothing changed on the asking

    said_yes = client.post("/settings", headers=head, follow_redirects=False,
                           data={"rule_on": "costly", "shown": "costly", "confirm_rule": "costly", "tab": "rules"})  # fmt: skip
    assert said_yes.status_code == 303
    assert settings.rule_on(data, loaded.get("costly")) is True


def test_the_weight_of_a_signal_comes_from_its_rule_file(tmp_path):
    """Turning one down, or off, is a file and not a release."""
    from epicrisis.suspects import find

    row = {"name": "Creatinine", "indicator_id": "creatinine", "first_page": 1,
           "date": "2020-01-01", "material": "blood"}  # fmt: skip
    # Five ordinary readings on five other forms, then one page carrying both signals at once.
    rows = [{**row, "number": 80.0 + n, "value": str(80 + n), "unit": "мкмоль/л", "file_sha256": f"{n}" * 64}
            for n in range(5)]  # fmt: skip
    rows += [{**row, "number": 880.0, "value": "880", "unit": "мкмоль/л", "file_sha256": "a" * 64},
             {**row, "number": 91.0, "value": "91", "unit": "", "file_sha256": "a" * 64}]  # fmt: skip
    documents = [{"file_sha256": "a" * 64, "first_page": 1, "date": "2020-01-01", "doc_type": "lab_panel",
                  "title": "Biochemistry", "provider": "City Laboratory", "transcribed": 1}]  # fmt: skip

    shipped = rules.load().at("suspects")
    both = find(rows, documents, {}, shipped)
    assert both and set(both[0].codes) == {"number_far_from_the_others", "unit_missing_where_others_have_one"}
    assert both[0].weight == 3 + 1  # what the two files say, not a table in the code

    # The same finding, with one rule turned off, is the other rule's finding alone.
    without = find(rows, documents, {}, [rule for rule in shipped if rule.id != "number_far_from_the_others"])
    assert set(without[0].codes) == {"unit_missing_where_others_have_one"} and without[0].weight == 1


def test_the_findings_are_written_again_when_a_check_is_switched(archive_index):  # noqa: F811
    """Turning a check off and the finding it made is gone from what the page reads."""
    import json

    from fastapi.testclient import TestClient

    from epicrisis import layout
    from epicrisis.sources import source_output_dir
    from epicrisis.web.app import create_app

    data_dir, source, _labs = archive_index
    stored = source_output_dir(data_dir, source.id) / layout.VALIDATION
    before = json.loads(stored.read_text(encoding="utf-8"))["totals"]
    turned_off = next(iter(before), None)
    if turned_off is None:
        return  # this archive has no findings at all; nothing to switch off

    client = TestClient(create_app(data_dir), base_url="http://127.0.0.1:8050")
    on = [rule.id for rule in rules.load(data_dir).at("validate") if rule.id != turned_off]
    client.post("/settings", data={"mode": "as_printed", "rule_on": on, "shown": [rule.id for rule in rules.load(data_dir)]},
                headers={"Sec-Fetch-Site": "same-origin"}, follow_redirects=False)  # fmt: skip

    after = json.loads(stored.read_text(encoding="utf-8"))["totals"]
    # The one switched off is gone, and the rest are still being counted. Their counts are not
    # compared: this fixture checked the archive once without a path to the originals, and the
    # checks that read the page itself find more the second time round.
    assert turned_off in before and turned_off not in after
    assert after and set(after) - {turned_off}


def test_what_a_rule_found_is_counted_beside_its_switch(archive_index):  # noqa: F811
    """A rule nobody can count is a rule nobody can ever delete."""
    from epicrisis import settings
    from epicrisis.rules import tally

    data_dir, source, _labs = archive_index
    loaded = rules.load(data_dir)
    on = {rule.id for rule in loaded if settings.rule_on(data_dir, rule)}
    counts = tally.counts(data_dir, source.id, loaded, on)

    assert set(counts) == {rule.id for rule in loaded}  # every rule says something
    assert all(not counts[rule.id].counted for rule in loaded.at("charts"))
    assert all(counts[rule.id].counted for rule in loaded.at("validate") + loaded.at("suspects"))

    # A rule that is off is counted all the same, and says it would find rather than found:
    # deciding whether to turn one on is exactly when knowing what it finds is worth having.
    off = next(rule for rule in loaded.at("suspects") if rule.id not in on)
    assert counts[off.id].ran is False and "would find" in counts[off.id].says
    assert all("would" not in counts[rule.id].says for rule in loaded.at("suspects") if rule.id in on)


def test_a_scale_is_not_reported_as_an_excursion():
    """The list that judges a value against its printed range knows what the chart knows.

    A test two laboratories printed a thousand apart was reported as twelve excursions, because
    each row was judged alone against a range printed at the other scale.
    """
    import sqlite3

    from epicrisis.query import printed_at_another_scale

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("""CREATE TABLE observations (indicator_id TEXT, material TEXT, unit TEXT,
                          value_numeric REAL, reference TEXT, value_role TEXT, derived INTEGER)""")  # fmt: skip
    printed = [(1.02, "1,001-1,040"), (1.015, "1,001-1,040"), (1.016, "1,005-1,025"),
               (1015.0, "1,001-1,040"), (1017.0, "1010 - 1030"), (1016.0, "1010 - 1030")]  # fmt: skip
    connection.executemany(
        "INSERT INTO observations VALUES ('gravity', 'urine', '', ?, ?, 'result', 0)", printed
    )
    placing = [rules.load().get("two-scales-in-one-test")]
    moves = printed_at_another_scale(connection, placing)

    assert len(moves) == 3  # the three forms that printed the thousandfold scale
    # The form with its range printed at one scale and the number written in at another moves
    # by the whole thousand; the forms that printed both at the other scale do not move at all
    # against their own range, and are compared where they stand.
    assert sorted(round(factor, 6) for factor in moves.values()) == [0.001, 1.0, 1.0]
    assert not printed_at_another_scale(connection, [])  # no rules, nothing moves


def test_a_person_can_say_a_finding_was_real_or_noise(archive_index):  # noqa: F811
    """The second half of counting a rule: how loud it is, and whether it was right."""
    from fastapi.testclient import TestClient

    from epicrisis import judgements, settings
    from epicrisis.rules import tally
    from epicrisis.sources import source_output_dir
    from epicrisis.web.app import create_app

    data_dir, source, labs = archive_index
    output = source_output_dir(data_dir, source.id)
    client = TestClient(create_app(data_dir), base_url="http://127.0.0.1:8050")
    head = {"Sec-Fetch-Site": "same-origin"}
    said = client.post(f"/review/{source.id}/judge", headers=head, follow_redirects=False,
                       data={"rule": "unreadable_parts", "sha256": labs, "pages": "1,2", "verdict": "real"})  # fmt: skip
    assert said.status_code == 303

    loaded = rules.load(data_dir)
    on = {rule.id for rule in loaded if settings.rule_on(data_dir, rule)}
    counts = tally.counts(data_dir, source.id, loaded, on)
    assert counts["unreadable_parts"].real == 1 and counts["unreadable_parts"].noise == 0

    # Changing one's mind is saying so again; the earlier word stays on the file.
    client.post(f"/review/{source.id}/judge", headers=head, follow_redirects=False,
                data={"rule": "unreadable_parts", "sha256": labs, "pages": "1,2", "verdict": "noise"})  # fmt: skip
    assert judgements.counted(output)["unreadable_parts"] == judgements.Counted(real=0, noise=1)
    assert len(judgements.path_for(output).read_text(encoding="utf-8").splitlines()) == 2

    # And it comes back to the check it was said in, open, rather than to the top of a page with
    # every check shut again: a verdict on the fortieth row must not lose a person's place.
    assert said.headers["location"] == "/review?check=unreadable_parts#unreadable_parts"
    assert '<details class="docs-year" id="number_differs">' in client.get("/review").text
    assert '<details class="docs-year" id="number_differs" open>' in client.get("/review?check=number_differs").text

    # Anything that is not a judgement is refused rather than written, and says so as a page.
    refused = client.post(f"/review/{source.id}/judge", headers=head, follow_redirects=False,
                          data={"rule": "unreadable_parts", "sha256": labs, "pages": "1,2", "verdict": "rubbish"})  # fmt: skip
    assert refused.status_code == 400
    assert "That is not a verdict this page can record" in refused.text


def test_an_answer_stored_the_old_way_is_still_read(tmp_path):
    """It began as {id: true}. Changing how answers are written must not lose the answers."""
    import json

    from epicrisis import settings

    data = tmp_path / "data"
    data.mkdir()
    loaded = rules.load(shipped_dir=write(tmp_path, "a-test-rule.md", GOOD))
    rule = loaded.get("a-test-rule")  # its own default is off
    settings.settings_path(data).write_text(json.dumps({"rules": {"a-test-rule": True}}), encoding="utf-8")
    assert settings.rule_on(data, rule) is True

    # And writing a setting does not lose the switch that was stored the old way.
    settings.set_rule_settings(data, rule, {"how_far": 4})
    assert settings.rule_on(data, rule) is True
    assert settings.rule_settings(data, rule)["how_far"] == 4.0


def test_a_rule_runs_with_what_this_archive_chose(tmp_path):
    from epicrisis import settings

    data = tmp_path / "data"
    data.mkdir()
    loaded = rules.load(shipped_dir=write(tmp_path, "a-test-rule.md", GOOD))
    rule = loaded.get("a-test-rule")
    assert rule.settings["how_far"] == 2.5 and rule.settings["at_least"] == 2

    settings.set_rule_settings(data, rule, {"how_far": 9, "at_least": 5, "invented": 1})
    chosen = settings.as_chosen(data, rule)
    assert chosen.settings == {"how_far": 9.0, "at_least": 5, "words": ["one", "two"]}
    assert rule.settings["how_far"] == 2.5  # the file itself is untouched

    # A setting the rule does not have is never stored, so it cannot travel doing nothing.
    assert "invented" not in chosen.settings

    # And a value of the wrong kind is refused rather than written.
    with pytest.raises(ValueError):
        settings.set_rule_settings(data, rule, {"at_least": "many"})


def test_typing_the_shipped_number_back_in_leaves_nothing_behind(tmp_path):
    """Undoing a change should leave no trace that one was ever made."""
    import json

    from epicrisis import settings

    data = tmp_path / "data"
    data.mkdir()
    loaded = rules.load(shipped_dir=write(tmp_path, "a-test-rule.md", GOOD))
    rule = loaded.get("a-test-rule")

    settings.set_rule_settings(data, rule, {"how_far": 9})
    assert json.loads(settings.settings_path(data).read_text())["rules"]["a-test-rule"]["settings"] == {"how_far": 9.0}

    settings.set_rule_settings(data, rule, {"how_far": 2.5})  # what it ships with
    assert json.loads(settings.settings_path(data).read_text())["rules"]["a-test-rule"]["settings"] == {}
    assert settings.rule_settings(data, rule)["how_far"] == 2.5


def test_a_half_sent_form_turns_nothing_off(archive_index):  # noqa: F811
    """A checkbox that is not ticked is not sent, so silence must not mean "off".

    A form posted without the rules — a stale page, a script, a page whose rules failed to draw
    — once turned off all nineteen at a stroke and rebuilt the index with it.
    """
    from fastapi.testclient import TestClient

    from epicrisis import settings
    from epicrisis.web.app import create_app

    data_dir, source, _labs = archive_index
    loaded = rules.load(data_dir)
    before = {rule.id: settings.rule_on(data_dir, rule) for rule in loaded}
    assert any(before.values())

    client = TestClient(create_app(data_dir), base_url="http://127.0.0.1:8050")
    client.post("/settings", data={"mode": "as_printed"}, headers={"Sec-Fetch-Site": "same-origin"},
                follow_redirects=False)  # fmt: skip
    assert {rule.id: settings.rule_on(data_dir, rule) for rule in loaded} == before

    # A form that says which switches it drew turns off exactly those and no others.
    one = next(rule.id for rule in loaded if before[rule.id])
    client.post("/settings", data={"mode": "as_printed", "shown": one}, headers={"Sec-Fetch-Site": "same-origin"},
                follow_redirects=False)  # fmt: skip
    after = {rule.id: settings.rule_on(data_dir, rule) for rule in loaded}
    assert after[one] is False and {k: v for k, v in after.items() if k != one} == {k: v for k, v in before.items() if k != one}


def test_a_rule_of_ones_own_is_written_read_back_and_kept(tmp_path):
    """Written, then read back before it is allowed to stay."""
    from epicrisis.rules import kinds

    data = tmp_path / "data"
    data.mkdir()
    made, wrong = rules.write_one(
        data, {"kind": "lab-form-without-a-title", "name": "A rule of my own",
               "summary": "One line.", "settles": "Open the page.", "attaches": "document"},
        "# What it looks at\n\nSomething.\n\n# How it can be wrong\n\nOften.", kinds.KINDS)  # fmt: skip

    assert not wrong and made == "a-rule-of-my-own"
    mine = rules.load(data).get(made)
    assert mine is not None and not mine.shipped
    assert mine.on_by_default is False  # somebody else's archive has not agreed to it
    assert mine.settings == kinds.KINDS["lab-form-without-a-title"].settings
    assert "How it can be wrong" in mine.about


def test_a_rule_of_ones_own_cannot_bring_a_kind_that_does_not_exist(tmp_path):
    from epicrisis.rules import kinds

    data = tmp_path / "data"
    data.mkdir()
    made, wrong = rules.write_one(data, {"kind": "os.system", "name": "Clever"}, "body", kinds.KINDS)
    assert not made and "kind" in wrong
    assert not (data / rules.FOLDER_NAME).exists() or not list((data / rules.FOLDER_NAME).glob("*.md"))


def test_a_rule_the_registry_will_not_take_does_not_stay_on_disk(tmp_path, monkeypatch):
    """A file it cannot read would say so on every page, to somebody who had moved on.

    The written file is read back before it is allowed to stay, and the reading is what is being
    tested — so the reading is made to refuse. There is no set of answers to the form that
    produces a file the loader rejects, which is the point of the form; this checked that with
    an assertion that was true either way and so could not fail.
    """
    from epicrisis.rules import RuleFileProblem, kinds

    data = tmp_path / "data"
    data.mkdir()

    def refuses(path, shipped=False):
        raise RuleFileProblem("this rule says two things at once")

    monkeypatch.setattr(rules, "read", refuses)
    made, wrong = rules.write_one(
        data, {"kind": "lab-form-without-a-title", "name": "No words at all", "summary": "x",
               "settles": "x", "attaches": "document"}, "a body", kinds.KINDS)  # fmt: skip

    assert not made and "two things at once" in wrong
    assert list((data / "rules").glob("*.md")) == [], "the file it refused is gone, not left saying so"

    # And an empty body is not one of the things it refuses: the form fills it in.
    monkeypatch.undo()
    made, wrong = rules.write_one(
        data, {"kind": "lab-form-without-a-title", "name": "No words at all", "summary": "x",
               "settles": "x", "attaches": "document"}, "   ", kinds.KINDS)  # fmt: skip
    assert made and not wrong
    assert "No more was said" in (data / "rules" / f"{made}.md").read_text(encoding="utf-8")
    assert not rules.load(data).problems


def test_a_name_already_taken_is_refused(tmp_path):
    from epicrisis.rules import kinds

    data = tmp_path / "data"
    data.mkdir()
    made, _ = rules.write_one(data, {"kind": "lab-form-without-a-title", "name": "Mine",
                                     "summary": "x", "settles": "x", "attaches": "document"},
                              "# What it looks at\n\nSomething.", kinds.KINDS)  # fmt: skip
    again, wrong = rules.write_one(data, {"kind": "lab-form-without-a-title", "name": "Mine",
                                          "summary": "x", "settles": "x", "attaches": "document"},
                                   "# What it looks at\n\nSomething.", kinds.KINDS)  # fmt: skip
    assert made == "mine" and not again and "already" in wrong


def test_trying_a_threshold_stores_nothing(archive_index):  # noqa: F811
    """A person turning a number over in their hands has not decided anything yet."""
    from fastapi.testclient import TestClient

    from epicrisis import settings
    from epicrisis.web.app import create_app

    data_dir, _source, _labs = archive_index
    rule = rules.load(data_dir).get("number_far_from_the_others")
    before = settings.rule_settings(data_dir, rule)

    client = TestClient(create_app(data_dir), base_url="http://127.0.0.1:8050")
    tried = client.post("/settings", headers={"Sec-Fetch-Site": "same-origin"}, follow_redirects=False,
                        data={"try_rule": rule.id, "knob_name": f"{rule.id}:times_away", "knob_value": "20"})  # fmt: skip

    assert tried.status_code == 200 and "nothing saved yet" in tried.text
    assert settings.rule_settings(data_dir, rule) == before
    # And the number typed comes back in the field, not the stored one.
    assert 'name="knob_value" value="20"' in tried.text


def test_a_name_a_person_types_cannot_reach_the_shape_of_the_file(tmp_path):
    """The header used to be built by putting the typed name between three quotes.

    A name holding three quotes of its own closed the string there, and the rest was read as more
    keys of the rule's header — enough to set a rule on by default that nobody turned on.
    """
    import tomllib

    from epicrisis.rules import kinds, write_one

    named = next(name for name, item in kinds.KINDS.items() if item.does == kinds.MARKS)
    typed = 'Awkward """\non_by_default = true\nname = """taken over'
    made, wrong = write_one(tmp_path, {"kind": named, "name": typed, "summary": "A rule with a difficult name.",
                                       "settles": "Open the page and see.", "attaches": "document"},
                            "# Written here\n\nNo more was said.", kinds.KINDS)  # fmt: skip
    assert not wrong and made

    written = (tmp_path / "rules" / f"{made}.md").read_text(encoding="utf-8")
    header = tomllib.loads(written.split("+++")[1])
    assert header["name"] == typed          # kept whole, and only as a value
    assert header["on_by_default"] is False  # nothing of the name became a key


def test_what_the_tools_answer_over_the_network_carries_no_path_into_the_archive(archive_index):  # noqa: F811
    """The path is the name the owner gave the file in their own folders.

    Which in an archive like this is a surname, a laboratory, often the reason for the visit —
    and the consent screen says nothing about it leaving. file_id names the file for a person and
    card_url reaches it; nothing outside this machine needs more.
    """
    from epicrisis import query
    from epicrisis.query import open_index

    data_dir, _source, _labs = archive_index
    with open_index(data_dir) as connection:
        rows = query.timeline(connection, limit=5) + query.search(connection, "a", limit=5)
    assert rows, "the fixture archive should hold documents"
    for row in rows:
        assert "path" not in row, row.keys()
        assert row["file_id"] and row["card_url"]


def test_a_rule_whose_findings_a_person_keeps_calling_noise_says_so():
    """"A rule you cannot count is a rule you can never delete" — and one nobody judged either.

    The registry could always switch a rule off; what it could not do was tell a person whether
    to. This says only what their own verdicts say, and only once there are enough of them for
    the saying to mean anything. It decides nothing and switches nothing off.
    """
    from epicrisis.rules.tally import ENOUGH_TO_JUDGE, Tally

    all_noise = Tally(found=40, documents=12, real=0, noise=ENOUGH_TO_JUDGE + 4)
    assert "candidate to switch off" in all_noise.worth_keeping

    all_real = Tally(found=40, documents=12, real=ENOUGH_TO_JUDGE + 4, noise=0)
    assert "was real" in all_real.worth_keeping and "switch off" not in all_real.worth_keeping

    # A rule a person has judged both ways says nothing: that is a rule doing its job.
    assert Tally(found=40, documents=12, real=4, noise=5).worth_keeping == ""
    # And too few verdicts to mean anything says nothing either, however one-sided they are.
    assert Tally(found=9, documents=3, real=0, noise=ENOUGH_TO_JUDGE - 1).worth_keeping == ""
    # A rule nobody has judged at all is not a candidate for anything.
    assert Tally(found=40, documents=12).worth_keeping == ""
    assert Tally(counted=False).worth_keeping == ""


def test_a_rule_of_the_whole_archive_hangs_its_finding_on_one_document():
    """A file can hold two documents, so a hash alone does not say which one a finding is about.

    The check for copies looks at every document at once and says which of them have twins. Hung
    by the hash of the file, its findings landed on every document of that file: forty-seven
    copies of a real archive became a hundred and seven, which is the same defect as counting a
    thing twice and calling it twice the work.
    """
    from epicrisis.rules.subjects import Found
    from epicrisis.validate import _the_document_of

    two_documents_in_one_file = [
        {"file_sha256": "a" * 64, "pages": [1, 2], "findings": {}},
        {"file_sha256": "a" * 64, "pages": [3, 4], "findings": {}},
        {"file_sha256": "b" * 64, "pages": [1], "findings": {}},
    ]

    found = _the_document_of(two_documents_in_one_file, Found("a" * 64, 3, None, ""))

    assert [doc["pages"] for doc in found] == [[3, 4]]


def test_what_counts_as_a_copy_is_four_numbers_a_person_can_see():
    """They were constants in validate.py: unseeable, unmovable, unmeasurable.

    Whether two files of one day are the same result is a judgement — a urinalysis and a
    coprogram share a handful of small numbers and are not copies — and a judgement belongs in
    the registry, where it can be switched off, tuned and counted.
    """
    from epicrisis import rules

    copy = next(rule for rule in rules.load() if rule.id == "possible_copy")

    assert copy.at == "validate" and copy.check.does == "marks"
    assert set(copy.settings) == {"results_shared", "results_at_least", "similar_in_size", "results_in_common"}
    # Every setting says what it means, or a person is being handed a number and no question.
    assert all(copy.check.means.get(name) for name in copy.settings)


def test_a_kind_whose_subject_its_step_never_builds_is_refused_where_it_is_written():
    """Accepted and then skipped in silence by every loop of that step: no error, no line anywhere,
    the rule switched on in the settings and finding nothing for ever — which looks exactly like a
    rule that works. The next rule written with another subject would have gone the same way."""
    from epicrisis.rules import kinds

    with pytest.raises(ValueError, match="hands a rule"):
        @kinds.kind("a-kind-nobody-feeds", does=kinds.MARKS, at=kinds.VALIDATE,
                    looks_at=kinds.A_SERIES, about="x")  # fmt: skip
        def _never_runs(subject, settings):
            return []

    # And every kind this program ships declares a pair its own step really hands out.
    for name, one in kinds.KINDS.items():
        assert one.looks_at in kinds.SERVED[one.at], f"{name}: {one.at} never builds {one.looks_at}"


def test_each_step_says_in_one_place_what_it_is_built_from():
    """Two lists, written apart, and each was short by a file: the checks did not count
    settings.json, so turning a rule off left their badge saying "done" while the index went on
    hiding documents by the old answer, and the index did not count inventory.jsonl although it
    builds its whole table of files out of it."""
    from epicrisis import layout

    for step in ("validate", "index"):
        here, instance = layout.BUILT_FROM[step]
        assert layout.INVENTORY in here, f"{step} reads the walk of the folder"
        assert layout.SETTINGS in instance, f"{step} is decided by what this instance allows"
    assert layout.INDICATORS in layout.BUILT_FROM["index"][1]


def test_every_file_under_data_belongs_to_exactly_one_list():
    """The lists say what a backup takes and what it leaves, and a file in none of them is a file
    whose fate nobody decided."""
    from epicrisis import layout

    named = (set(layout.THEIR_OWN_WORK) | set(layout.THEIR_CHOICES) | set(layout.MADE_AGAIN_BY_CODE)
             | set(layout.MADE_AGAIN_BY_A_MODEL) | set(layout.ASKED_FOR_AGAIN))  # fmt: skip
    for name in (layout.SOURCES, layout.SETTINGS, layout.CONSENT, layout.INDICATORS, layout.CHATS,
                 layout.CORRECTIONS, layout.JUDGEMENTS, layout.REPLACED, layout.INVENTORY,
                 layout.CLASSIFY, layout.EXTRACTED, layout.VALIDATION, layout.MATERIALS):  # fmt: skip
        assert name in named, f"{name} is in no list: nobody has decided whether a copy carries it"


def test_the_two_readings_of_a_printed_range_are_compared_and_neither_decides():
    """The band is read by a parser, and a parser alone is never wrong out loud.

    The model that transcribed the page is asked for the same range as two numbers. Where the two
    answers differ a person is shown the page; where the model was never asked, there is nothing to
    disagree with and nothing is said.
    """
    from epicrisis.rules.subjects import Document
    from epicrisis.validate import range_read_two_ways

    def value(printed, **read_by_the_model):
        return {"name_as_printed": "X", "value_as_printed": "1", "reference_as_printed": printed,
                "provenance": {"page": 1, "snippet": "X 1"}, **read_by_the_model}  # fmt: skip

    def findings(*values) -> int:
        document = Document(file_sha256="a" * 64, pages=(1,), item={"observations": list(values)})
        return len(range_read_two_ways(document, {"apart_by": 0.0}))

    # The two agree, in both shapes a range comes in.
    assert findings(value("3,5 - 5,5", reference_low=3.5, reference_high=5.5)) == 0
    assert findings(value("< 5,0", reference_low=None, reference_high=5.0)) == 0
    # Both say it is not one range for this person: an age table, and they share that answer.
    assert findings(value("Діти: 1-6 років: 110-145\nДорослі: 130-160", reference_low=None, reference_high=None)) == 0

    # A number one read and the other did not, in either direction. This is the case the rule is
    # for: a band missing under a chart, or a band drawn where the form printed a table.
    assert findings(value("150,000 - 400,000", reference_low=150000.0, reference_high=400000.0)) == 1
    assert findings(value("Діти: 1-6 років: 110-145\nДорослі: 130-160", reference_low=130.0, reference_high=160.0)) == 1
    # And two numbers that are simply different.
    assert findings(value("3,5 - 5,5", reference_low=3.5, reference_high=55.0)) == 1

    # Silent where the model was never asked: every document transcribed before those two fields.
    assert findings(value("3,5 - 5,5")) == 0
    # And silent where the form printed no range at all, whatever the model answered.
    assert findings(value(None, reference_low=None, reference_high=None)) == 0

    # How far apart they may be before it is reported is the rule's own number, and a bound one
    # reading has and the other has not is reported whatever it is set to.
    document = Document(file_sha256="a" * 64, pages=(1,),
                        item={"observations": [value("3,5 - 5,5", reference_low=3.5, reference_high=5.6)]})  # fmt: skip
    assert len(range_read_two_ways(document, {"apart_by": 0.0})) == 1
    assert len(range_read_two_ways(document, {"apart_by": 0.05})) == 0


def test_a_verdict_about_a_document_that_no_longer_exists_stops_counting(tmp_path):
    """The two numbers that decide whether a rule is kept were reading verdicts about nothing.

    A verdict is kept against the pages the classification grouped, exactly as a date put in by hand
    is. A page read again can be grouped differently — a two-page form becoming two documents — and
    then the verdict applies to no document at all. A correction in that state has been counted and
    shown on the page since the day it could happen; a verdict was neither counted as lost nor
    dropped from the pair of numbers.
    """
    import json

    from epicrisis import judgements

    output = tmp_path / "sources" / "aa11bb22"
    output.mkdir(parents=True)

    def classified(page: int, role: str) -> dict:
        return {"file_sha256": "e" * 64, "page": page, "route": "text", "doc_type": "lab_panel",
                "page_role": role, "language": "en", "date_on_page": None, "provider_on_page": None,
                "has_tabular_results": True, "legible": True, "confidence": 0.9}  # fmt: skip

    # The archive holds one document of one page, and one of two.
    (output / "classify.jsonl").write_text("".join(json.dumps(line) + "\n" for line in [
        classified(1, "first"), classified(2, "first"), classified(3, "continuation"),
    ]), encoding="utf-8")  # fmt: skip
    judgements.record(output, "possible_copy", "e" * 64, [1], judgements.REAL)
    judgements.record(output, "possible_copy", "e" * 64, [7, 8], judgements.NOISE)

    counted = judgements.counted(output)

    assert counted["possible_copy"] == judgements.Counted(real=1, noise=0)
    lost = judgements.unmatched(output)
    assert [(item["pages"], item["verdict"]) for item in lost] == [([7, 8], judgements.NOISE)]
    assert lost[0]["rule"] == "possible_copy"

    # A person who says it again about the document as it stands now is counted again.
    judgements.record(output, "possible_copy", "e" * 64, [2, 3], judgements.NOISE)
    assert judgements.counted(output)["possible_copy"] == judgements.Counted(real=1, noise=1)

    # And with no classification at all nothing can be told about which documents exist, so a
    # verdict is counted rather than dropped: the wrong way to be wrong here is to lose somebody's word.
    (output / "classify.jsonl").unlink()
    assert judgements.counted(output)["possible_copy"].judged == 3 and judgements.unmatched(output) == []


def test_a_switch_that_does_more_than_stop_a_finding_says_so_where_it_is_pressed(tmp_path):
    """Turning off the rule that marks copies turns off the folding of copies for the whole archive.

    One document of a group answers; the others are there and a question that does not ask for them
    does not get them, which is what keeps one blood draw exported three times from appearing three
    times in a series. Switch the rule off and every copy answers for itself — the same measurement
    twice or three times on every chart, in every median and in every answer over the network. The
    rule's own page said the opposite ("nothing is merged by this and no value is hidden"), and the
    settings page invites the press: a rule whose findings a person called noise is labelled a
    candidate to switch off.
    """
    from fastapi.testclient import TestClient

    from epicrisis import rules
    from epicrisis.web.app import create_app

    copy = next(rule for rule in rules.load() if rule.id == "possible_copy")

    assert "every copy answers for itself" in copy.switching_off
    assert "It is not only the finding that goes." in copy.switching_off
    # And the rule's own page no longer says the opposite of it.
    assert "Nothing is merged by this and no value is hidden" not in copy.about
    assert "one document of a group answers" in copy.about

    # The sentence is beside the switch, not only behind the click that opens the rule.
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = client.get("/settings?tab=rules").text
    at_the_switch = page[: page.index(copy.about[:40])] if copy.about[:40] in page else page
    assert "every copy answers for itself" in at_the_switch

    # Nothing else claims one, and nothing has to: this is for the switch that does more than report.
    assert [rule.id for rule in rules.load() if rule.switching_off] == ["possible_copy"]
