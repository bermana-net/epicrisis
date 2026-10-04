"""The acts the journal records, and the many it leaves alone.

The steps of the pipeline are in `ledger.jsonl`, the calls over the network in
`mcp-access.jsonl`, what a person corrected by hand in `corrections.jsonl`, what they said about a
finding in `judgements.jsonl`. Recording any of those again would be a second list that can
disagree with the first, which is the defect this project calls a defect rather than a detail.

What was nowhere is these three:

- **Which archive is open.** The first line of the constitution is about exactly this, and the
  failure behind it was a page that read the open archive without asking whose it was. If it
  happens again the question is which archive was open when, and nothing could answer it.
- **A decision nothing can rebuild.** people.json and indicators.json hold a person's answers and
  write over the answer before, so a group joined on Tuesday and split on Wednesday leaves a file
  saying neither ever happened.
- **A change of settings.** A rule that decides what is checked on somebody's documents could be
  switched off, the file written, a copy of the version before it put beside it — and no line
  anywhere said that it had happened or when. Over the whole life of the instance this was found
  on, the journal held 36 lines and not one of them was about a setting. The same held for the
  model, the answer mode, the lock over the network and every threshold.

All three are recorded as ids, counts and this program's own words. Every name invented here is
nonsense, and never a name.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from epicrisis import journal, people
from epicrisis.sources import SourceRegistry
from epicrisis.web.app import create_app
from test_the_wall_between_people import THEIRS

# Two spellings that are plainly the same doctor. Taken from the wall test, which is where these
# words were invented and where they were looked for in the archives before being written down —
# a plausible surname in the right language is usually somebody's.
ONE = THEIRS["one"]["doctor"]
OTHER = "уролог " + THEIRS["one"]["doctor"]
ANOTHER = (THEIRS["two"]["doctor"], THEIRS["two"]["doctor"] + " (хірургія)")


def two_archives(tmp_path: Path) -> tuple[Path, str, str]:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    registry = SourceRegistry(data_dir)
    ids = []
    for folder in ("qwyzzlon-first", "pselofaza-second"):
        (tmp_path / folder).mkdir()
        ids.append(registry.add(str(tmp_path / folder), owner=f"Owner of {folder}").id)
    registry.set_active(ids[0])
    return data_dir, ids[0], ids[1]


def dashboard(data_dir: Path) -> TestClient:
    return TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050",
                      raise_server_exceptions=False)  # fmt: skip


def events(data_dir: Path, event: str) -> list[dict]:
    return [one for one in journal.entries(data_dir) if one["event"] == event]


def test_switching_the_archive_shown_is_written_down_as_both_ids(tmp_path: Path):
    """One archive is open at a time, for the whole instance, and nothing said when that changed."""
    data_dir, first, second = two_archives(tmp_path)

    dashboard(data_dir).post("/owner", data={"source": second, "back": "/"}, follow_redirects=True)

    switched = events(data_dir, "the archive shown was switched")
    assert len(switched) == 1
    assert switched[0]["archive"] == second and switched[0]["instead_of"] == first
    # The ids are random for exactly this reason: the folder names are not, and the name of
    # whoever an archive belongs to is on every page and in none of these lines.
    written = journal.path(data_dir).read_text(encoding="utf-8")
    assert "qwyzzlon" not in written and "pselofaza" not in written and "Owner of" not in written


def test_pressing_the_picker_on_the_archive_already_shown_is_still_written_down(tmp_path: Path):
    """Both ids, the same one twice: the press happened and nothing moved.

    Written down rather than left out, because the question this line answers is "what was being
    looked at, and when" — and a press that changed nothing is still an answer to it. A line
    missing from a record of presses means a press that was not recorded, and there is no way to
    tell that from a press that did not happen.
    """
    data_dir, first, _ = two_archives(tmp_path)

    dashboard(data_dir).post("/owner", data={"source": first, "back": "/"}, follow_redirects=True)

    line = events(data_dir, "the archive shown was switched")[0]
    assert line["archive"] == first and line["instead_of"] == first


def test_a_switch_on_a_server_holding_no_archive_names_nothing_before_it(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    dashboard(data_dir).post("/owner", data={"source": "qq112233", "back": "/"}, follow_redirects=True)

    line = events(data_dir, "the archive shown was switched")[0]
    assert line["archive"] == "qq112233" and "instead_of" not in line


def test_joining_two_printed_names_is_written_down_as_a_count(tmp_path: Path):
    """A claim about the identity of a human being, made by hand, that nothing rebuilds."""
    data_dir, first, _ = two_archives(tmp_path)

    people.join(data_dir, first, "doctor", [ONE, OTHER], OTHER)

    line = events(data_dir, "names were joined into one")[0]
    assert line["archive"] == first and line["about"] == "doctor" and line["names"] == 2
    # The spellings are the names of a doctor printed on somebody's documents. A journal holding
    # them is a list of the doctors one person has seen.
    written = journal.path(data_dir).read_text(encoding="utf-8")
    assert ONE not in written and OTHER not in written


def test_undoing_a_join_saying_no_and_taking_that_back_are_written_down_too(tmp_path: Path):
    """Four acts now, because a refusal is remembered rather than forgotten, and is undone by hand.

    Each is a claim about the identity of human beings that nothing rebuilds, and the file holds
    only the answer: a pair refused on Tuesday and asked for again on Wednesday leaves a file
    saying neither happened.
    """
    data_dir, first, _ = two_archives(tmp_path)
    people.join(data_dir, first, "institution", [ONE, OTHER], OTHER)
    people.propose(data_dir, first, "doctor", list(ANOTHER))

    people.split(data_dir, first, "institution", OTHER)
    people.decline(data_dir, first, "doctor", list(ANOTHER))
    people.reconsider(data_dir, first, "doctor", list(ANOTHER))

    undone = events(data_dir, "a join of names was undone")[0]
    assert undone["about"] == "institution" and undone["names"] == 2
    said_no = events(data_dir, "names were said not to be one")[0]
    assert said_no["about"] == "doctor" and said_no["names"] == 2
    taken_back = events(data_dir, "a refusal about names was taken back")[0]
    assert taken_back["about"] == "doctor" and taken_back["names"] == 2
    written = journal.path(data_dir).read_text(encoding="utf-8")
    assert not any(name in written for name in ANOTHER)


def test_a_join_that_settled_nothing_is_not_written_down(tmp_path: Path):
    """A line saying something happened when nothing did is worse than no line."""
    data_dir, first, _ = two_archives(tmp_path)

    for asking in (lambda: people.join(data_dir, first, "doctor", [ONE]),  # one name is not a join
                   lambda: people.join(data_dir, first, "not-a-kind", [ONE, OTHER]),
                   lambda: people.decline(data_dir, first, "doctor", [ONE])):
        with pytest.raises(ValueError):  # NotAJoin is one; nothing here returns in silence
            asking()
    people.split(data_dir, first, "doctor", "a label nothing is under")
    people.reconsider(data_dir, first, "doctor", [ONE, OTHER])  # no such refusal

    assert journal.entries(data_dir) == []


def test_approving_a_group_of_spellings_is_written_down_as_a_count(tmp_path: Path):
    """Five hundred groups of the vocabulary, one press at a time, and nothing said they happened."""
    data_dir, _, _ = two_archives(tmp_path)

    dashboard(data_dir).post("/indicators", data={"action": "save", "label": "Zhabborin",
                                                  "names": "Zhabborin\nZHB\nzhabborin total",
                                                  "status": "approved"})  # fmt: skip

    line = events(data_dir, "a group of spellings was settled by hand")[0]
    assert line["action"] == "save" and line["status"] == "approved" and line["names"] == 3
    # The label and the spellings are the printed names of tests, and a journal that holds them
    # says which tests this person has had.
    written = journal.path(data_dir).read_text(encoding="utf-8")
    assert "Zhabborin" not in written and "ZHB" not in written and "zhabborin" not in written


def test_a_form_that_asked_for_nothing_this_page_does_is_not_written_down(tmp_path: Path):
    data_dir, _, _ = two_archives(tmp_path)

    dashboard(data_dir).post("/indicators", data={"action": "nothing-of-the-sort"})

    assert events(data_dir, "a group of spellings was settled by hand") == []


def test_what_is_already_recorded_somewhere_is_not_recorded_twice(tmp_path: Path):
    """A correction by hand is in corrections.jsonl and in no line of the journal.

    Two lists of one thing can disagree, and then there is no way to tell which is right. The
    journal holds what nothing else holds, and that is the whole of what it holds.
    """
    data_dir, first, _ = two_archives(tmp_path)
    from epicrisis import judgements
    from epicrisis.sources import source_output_dir

    output = source_output_dir(data_dir, first)
    judgements.record(output, "a-rule", "b" * 64, [1], "noise")

    assert journal.entries(data_dir) == []
    said = json.loads(judgements.path_for(output).read_text(encoding="utf-8").splitlines()[0])
    assert said["verdict"] == "noise"


def a_rule_with_thresholds(data_dir: Path):
    """One shipped rule that is on and has numbers to change, so these tests say what they mean."""
    from epicrisis import rules

    return next(one for one in rules.load(data_dir) if one.settings and one.on_by_default)


def test_switching_two_rules_off_is_written_down_by_their_ids(tmp_path: Path):
    """The press this entry was written for: two noisy rules turned off, and nothing said so.

    What a rule checks is what the program looks at on somebody's documents, and the switch is a
    line in settings.json that holds the answer and overwrites the one before it. Asked a month
    later, "when did this stop being checked?" had no answer anywhere on the machine.
    """
    from epicrisis import rules
    from epicrisis.settings import set_rule_on

    data_dir, _, _ = two_archives(tmp_path)
    two = [one for one in rules.load(data_dir) if one.on_by_default][:2]

    for rule in two:
        set_rule_on(data_dir, rule.id, False)

    switched = events(data_dir, "a rule was switched off")
    assert [line["rule"] for line in switched] == [rule.id for rule in two]
    # Each of them had never been answered on this instance, so what it stood at before is what
    # the rule file ships — which this line does not claim to know. See _first_answer.
    assert all(line["first_answer"] for line in switched)
    assert events(data_dir, "a rule was switched on") == []

    set_rule_on(data_dir, two[0].id, True)
    back_on = events(data_dir, "a rule was switched on")
    assert len(back_on) == 1 and back_on[0]["rule"] == two[0].id
    assert "first_answer" not in back_on[0]  # this one had an answer before, and it was false


def test_a_threshold_that_moved_says_which_rule_which_name_and_which_number(tmp_path: Path):
    """A rule's numbers decide how much it marks, so changing one changes what a person is shown."""
    from epicrisis.settings import set_rule_settings

    data_dir, _, _ = two_archives(tmp_path)
    rule = a_rule_with_thresholds(data_dir)
    name, shipped = next(iter(rule.settings.items()))

    set_rule_settings(data_dir, rule, {name: shipped + 1})

    line = events(data_dir, "a rule's thresholds were changed")[0]
    assert line["rule"] == rule.id and line["thresholds"] == {name: shipped + 1}
    assert "as_shipped" not in line and "not_said" not in line

    set_rule_settings(data_dir, rule, {name: shipped})  # typed back: the rule's own number again

    back = events(data_dir, "a rule's thresholds were changed")[1]
    assert back["as_shipped"] == [name] and "thresholds" not in back


def test_a_threshold_that_is_not_a_number_is_named_and_never_written_down(tmp_path: Path):
    """The one shape of threshold that could carry a string off somebody's form.

    Every kind ships numbers today and the writer takes a word or a list as well, so a rule
    written next month could hold a printed spelling as a threshold — the name of a test, the
    name of a laboratory. The line says which threshold of which rule moved and stops there.
    """
    from dataclasses import replace

    from epicrisis.settings import set_rule_settings

    data_dir, _, _ = two_archives(tmp_path)
    as_if_it_shipped_a_word = replace(a_rule_with_thresholds(data_dir), settings={"spelling": "whatever"})

    set_rule_settings(data_dir, as_if_it_shipped_a_word, {"spelling": "Zhabborin total"})

    line = events(data_dir, "a rule's thresholds were changed")[0]
    assert line["not_said"] == ["spelling"] and "thresholds" not in line
    assert "Zhabborin" not in journal.path(data_dir).read_text(encoding="utf-8")


def test_the_answer_mode_the_lock_and_the_window_say_what_they_became(tmp_path: Path):
    """Three settings of this program's own words, each written down with its value."""
    from epicrisis.settings import set_answer_mode, set_mcp_lock_minutes, set_mcp_lock_scope

    data_dir, _, _ = two_archives(tmp_path)

    set_answer_mode(data_dir, "direct")
    set_mcp_lock_scope(data_dir, "server")
    set_mcp_lock_minutes(data_dir, 15)

    said = {line["setting"]: line.get("became") for line in events(data_dir, "a setting was changed")}
    assert said == {"answer_mode": "direct", "mcp_lock_scope": "server", "mcp_lock_minutes": 15}


def test_a_model_this_program_names_is_written_down_and_one_it_does_not_is_not(tmp_path: Path):
    """A pass is one of three words of this program's own; a typed model name is a typed string."""
    from epicrisis.models import KNOWN_MODELS, PASSES
    from epicrisis.settings import set_chosen_models

    data_dir, _, _ = two_archives(tmp_path)
    known = next(name for name, _ in KNOWN_MODELS if name != PASSES["strong"]["default"])

    set_chosen_models(data_dir, {"strong": known, "second_reader": "Zhabborin-model-7"})

    lines = {line["pass"]: line for line in events(data_dir, "a model was chosen for a pass")}
    assert lines["strong"]["model"] == known and "known" not in lines["strong"]
    assert lines["second_reader"]["known"] is False and "model" not in lines["second_reader"]
    assert "Zhabborin" not in journal.path(data_dir).read_text(encoding="utf-8")


def test_a_setting_written_with_the_value_it_already_had_is_not_written_down(tmp_path: Path):
    """A line saying something changed when nothing did is worse than no line.

    One press of Save calls a dozen writers in turn, and a journal keeping five thousand lines
    must not be filled with the settings nobody touched until the failures fall out of the far
    end of it.
    """
    from epicrisis.models import PASSES
    from epicrisis.settings import (set_answer_mode, set_chosen_models, set_rule_on,
                                    set_rule_settings)

    data_dir, _, _ = two_archives(tmp_path)
    rule = a_rule_with_thresholds(data_dir)
    set_answer_mode(data_dir, "direct")
    set_rule_on(data_dir, rule.id, False)
    set_rule_settings(data_dir, rule, {name: value + 1 for name, value in rule.settings.items()})
    written = len(journal.entries(data_dir))
    assert written == 3

    set_answer_mode(data_dir, "direct")
    set_rule_on(data_dir, rule.id, False)
    set_rule_settings(data_dir, rule, {name: value + 1 for name, value in rule.settings.items()})
    # The models the three passes already run with, which is what the settings page sends on
    # every press whether anybody touched the fields or not.
    set_chosen_models(data_dir, {name: PASSES[name]["default"] for name in PASSES})

    assert len(journal.entries(data_dir)) == written


def test_a_press_that_never_reached_the_disk_is_not_written_down(tmp_path: Path):
    """The journal sits beside settings.json and may not disagree with it.

    One press is one write, at the end of the change: a writer that ran and then a refusal
    further down the same press leaves the file exactly as it was, and a line saying the setting
    changed would be the journal remembering something that never happened.
    """
    from epicrisis.settings import answer_mode, editing, set_answer_mode

    data_dir, _, _ = two_archives(tmp_path)

    with pytest.raises(RuntimeError):
        with editing(data_dir):
            set_answer_mode(data_dir, "direct")
            raise RuntimeError("something further down the same press")

    assert answer_mode(data_dir) == "as_printed"
    assert journal.entries(data_dir) == []
