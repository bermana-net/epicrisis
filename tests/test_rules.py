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
    KINDS["for-the-tests"] = Kind(name="for-the-tests", does="marks", at="validate", looks_at="one value",
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
    asked = client.post("/settings", data={"rule_on": "costly", "tab": "rules"}, headers=head, follow_redirects=False)
    assert asked.status_code == 200 and "read again by a model" in asked.text
    assert settings.rule_on(data, loaded.get("costly")) is False  # nothing changed on the asking

    said_yes = client.post("/settings", data={"rule_on": "costly", "confirm_rule": "costly", "tab": "rules"},
                           headers=head, follow_redirects=False)  # fmt: skip
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
    both = find(rows, documents, shipped)
    assert both and set(both[0].codes) == {"number_far_from_the_others", "unit_missing_where_others_have_one"}
    assert both[0].weight == 3 + 1  # what the two files say, not a table in the code

    # The same finding, with one rule turned off, is the other rule's finding alone.
    without = find(rows, documents, [rule for rule in shipped if rule.id != "number_far_from_the_others"])
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
    client.post("/settings", data={"mode": "as_printed", "rule_on": on},
                headers={"Sec-Fetch-Site": "same-origin"}, follow_redirects=False)  # fmt: skip

    after = json.loads(stored.read_text(encoding="utf-8"))["totals"]
    # The one switched off is gone, and the rest are still being counted. Their counts are not
    # compared: this fixture checked the archive once without a path to the originals, and the
    # checks that read the page itself find more the second time round.
    assert turned_off in before and turned_off not in after
    assert after and set(after) - {turned_off}
