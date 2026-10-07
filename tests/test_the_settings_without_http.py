"""The settings page asked directly: what it shows, and what one press of Save does.

Both halves of this page used to be a route. Nothing could ask it a question without going over
HTTP and reading the answer out of the markup, and the three defects that were mended in it this
week are all of a kind that a question would have caught: a threshold that could not be read, the
two choices of the lock and the engine each went into a `suppress(ValueError)` while the page said
"Saved. Nothing on the page was different from what was already stored", and one press of Save
wrote settings.json seventeen times, leaving `.previous` — which this program's own refusal offers
as "the version before the last change" — holding the middle of that press.

`settings_view` and `settings_pressed` are where those are decided now, and this is them asked as
questions. The press is asked what it refused as well as what it stored, because the answer being
a value is the whole reason a swallowed refusal can now be a failing test.
"""

import ast
import inspect
import json
import textwrap
import time

import pytest

from epicrisis import rules, settings
from epicrisis.rules import kinds
from epicrisis.sources import NO_ARCHIVES, SourceRegistry
from epicrisis.web import settings_page as the_page
from epicrisis.web.settings_page import (Pressed, rules_are_about, settings_pressed,
                                          settings_view)  # fmt: skip

#: The rule the measurements of the bad threshold were taken on: three numbers, so one press can
#: have one of them mistyped and the other two good, which is the shape the swallowed refusal hid.
THREE_NUMBERS = "range_powers_from_the_rest"


@pytest.fixture
def an_instance(tmp_path):
    """A data directory with one archive on its list, and that reading of the list as a value."""
    data_dir = tmp_path / "project" / "data"
    folder = tmp_path / "An archive of nobody"
    folder.mkdir()
    registry = SourceRegistry(data_dir)
    registry.add(str(folder), owner="A Person")
    return data_dir, registry.as_one_reading()


def about(archives, asked: str = "") -> str:
    """Which archive the Rules tab is drawn about, read the way the page reads it.

    The switches are the open archive's answers now, and the counts beside them always were. A
    test harness that drew the instance's answers and submitted them as this page's would be
    writing one answer into the other, which is the defect the tab was written to close.
    """
    return rules_are_about(archives, asked)["in_archive"]


def a_whole_press(data_dir, archives, **asked) -> dict:
    """The page exactly as it is drawn, submitted unchanged, plus whatever is asked for here.

    Built from the rules this instance loads rather than written out, so a rule shipped next
    month is in the press without anybody remembering to put it there. Every value starts at what
    is stored, because a checkbox that is not ticked is not sent at all: a press written out with
    fewer switches than the page draws is a press that turns the missing ones off, which is a
    different press and not a smaller one.

    `archives` because the switches are of one archive: see about(). An `about` asked for here
    is the address of the page, and the switches are then drawn from the answers that address
    shows — a press built from one archive's answers and sent to the other address would be
    writing one of the two answers over the other.
    """
    asking = about(archives, asked.get("about", ""))
    shown, knob_name, knob_value, on = [], [], [], []
    for rule in rules.load(data_dir):
        shown.append(rule.id)
        if settings.rule_on(data_dir, rule, in_archive=asking):
            on.append(rule.id)
        chosen = settings.rule_settings(data_dir, rule, in_archive=asking)
        for name in rule.settings:
            knob_name.append(f"{rule.id}:{name}")
            knob_value.append(str(chosen[name]))
    return {"shown": shown + ["ask_page", "models", "read_materials", "mcp_lock"],
            "confirmed_rules": shown, "knob_name": knob_name, "knob_value": knob_value,
            "rule_on_ids": on, "mode": settings.answer_mode(data_dir),
            "ask_page": "on" if settings.ask_enabled(data_dir) else "",
            "read_materials": "on" if settings.trusts_read_materials(data_dir) else "",
            "mcp_lock": "on" if settings.mcp_lock_on(data_dir) else "",
            "mcp_lock_scope_choice": settings.mcp_lock_scope(data_dir),
            "mcp_lock_minutes_choice": settings.mcp_lock_minutes(data_dir),
            **asked}  # fmt: skip


def also_on(press: dict, rule_id: str) -> dict:
    """The same press with one more rule ticked."""
    return {**press, "rule_on_ids": [*press["rule_on_ids"], rule_id]}


def nudged(press: dict, field: str, value: str) -> dict:
    """One threshold of the press typed over, by the name the form gives it."""
    values = list(press["knob_value"])
    values[press["knob_name"].index(field)] = value
    return {**press, "knob_value": values}


def test_the_settings_page_gathers_what_it_shows(an_instance):
    """The context of the page, asked for without an address and without a template.

    Every switch on it comes from the file, which is why the page asks whether that file can be
    read on the way in and not only on the way out: over a file that cannot be read every switch
    draws at its default, and a person reads the defaults as the truth about their own instance.
    """
    data_dir, archives = an_instance

    shown = settings_view(data_dir, archives)
    assert shown["current"] == "settings"
    assert shown["settings_unreadable"] is False
    assert shown["data_dir"] == str(data_dir), "the commands the page prints name this instance"
    assert shown["mode"] in the_page.ANSWER_MODE_NAMES
    assert [item["key"] for item in shown["passes"]] and shown["known_names"]
    assert [item["name"] for item in shown["engines"]], "no engine is offered at all"

    # One entry per rule, with the thresholds its kind declares and nothing else: the form is
    # built from what the kind says, so a name it does not have cannot be typed.
    three = next(rule for rule in shown["rules"] if rule["id"] == THREE_NUMBERS)
    assert [knob["field"] for knob in three["knobs"]] == [
        f"{THREE_NUMBERS}:{name}" for name in rules.load(data_dir).get(THREE_NUMBERS).settings]  # fmt: skip
    assert all(knob["number"] for knob in three["knobs"]), "three numbers, and the form says so"

    # The tab is a radio button and the panels are drawn by CSS from which one is checked, so a
    # name that is none of the four left every panel hidden and the page empty.
    assert settings_view(data_dir, archives, tab="network")["tab"] == "network"
    assert settings_view(data_dir, archives, tab="nonsense")["tab"] == the_page.SETTINGS_TABS[0]
    assert settings_view(data_dir, archives, tab="")["tab"] == the_page.SETTINGS_TABS[0]


def test_a_bad_threshold_is_named_and_the_good_ones_of_the_same_press_are_stored(an_instance):
    """One mistyped number of three, and the press has two true things to say about itself.

    The write replaces every threshold of a rule at once and settings.py refuses the whole rule on
    the first value it cannot read, so one mistyped number lost every other threshold of that rule
    as well; and the refusal — a sentence written for a person — went into a `suppress(ValueError)`,
    under which the page said "Saved. Nothing on the page was different from what was already
    stored", which is false about the page and about the storing both.
    """
    data_dir, archives = an_instance
    rule = rules.load(data_dir).get(THREE_NUMBERS)
    before = settings.rule_settings(data_dir, rule, in_archive=about(archives))
    mistyped, *good = list(rule.settings)

    press = a_whole_press(data_dir, archives)
    for name in good:
        press = nudged(press, f"{THREE_NUMBERS}:{name}", str(before[name] + 1))
    press = nudged(press, f"{THREE_NUMBERS}:{mistyped}", "not a number")

    pressed = settings_pressed(data_dir, archives, build_indexes=lambda: None, **press)

    # Said out loud, by the name on the form, with what it wants and what it still stands at.
    assert len(pressed.refused) == 1, pressed.refused
    said = pressed.refused[0]
    assert mistyped.replace("_", " ") in said and rule.name in said
    assert f"still stands at {before[mistyped]}" in said
    # And never instead of what was stored: the sentence the page shows carries the refusal too.
    assert said in pressed.trouble
    assert pressed.said, "a press that stored thresholds said it stored nothing"

    now = settings.rule_settings(data_dir, rule, in_archive=about(archives))
    assert now[mistyped] == before[mistyped], "the number that could not be read was stored anyway"
    assert [now[name] for name in good] == [before[name] + 1 for name in good], (
        "the good thresholds of the same press were lost with the bad one")  # fmt: skip


def test_one_press_is_one_write_of_the_settings_and_one_copy_of_the_version_before_it(an_instance):
    """Seventeen writes, and a `.previous` holding the middle of the press. Asked of the press.

    `settings.editing` holds the file's lock for the whole of one press and gathers every writer
    under it into one write, with one copy of the version the press began from. This is that
    counted where the press is decided, so the gathering cannot be lost by a line moving out from
    under the lock — which is the one way this regresses, and would regress in silence.
    """
    data_dir, archives = an_instance
    settings.set_answer_mode(data_dir, "as_printed")
    was = json.loads(settings.settings_path(data_dir).read_text(encoding="utf-8"))

    writes, copies = [], []
    whole, copied = settings.write_whole, settings.copy_whole
    settings.write_whole = lambda path, text: (writes.append(text), whole(path, text))[1]
    settings.copy_whole = lambda source, target: (copies.append(str(target)), copied(source, target))[1]
    builds = []
    try:
        rule = rules.load(data_dir).get(THREE_NUMBERS)
        press = a_whole_press(data_dir, archives, mode="with_meaning", mcp_lock_minutes_choice=120,
                              ask_page="on", read_materials="on",
                              models={"first": "zzz-one", "strong": "zzz-two",
                                      "second_reader": "zzz-three"})  # fmt: skip
        for name, value in settings.rule_settings(data_dir, rule).items():
            press = nudged(press, f"{THREE_NUMBERS}:{name}", str(value + 1))
        pressed = settings_pressed(data_dir, archives,
                                   build_indexes=lambda: builds.append(1) or None, **press)  # fmt: skip
    finally:
        settings.write_whole, settings.copy_whole = whole, copied

    assert pressed.refused == (), pressed.refused
    assert len(writes) == 1, f"one press, {len(writes)} writes of settings.json"
    assert len(copies) == 1, f"one press, {len(copies)} copies into settings.json.previous"
    # Once for the whole press, however many of the things in it asked for it: two of them in one
    # press built every archive's index twice, and the second build's failure quietly replaced the
    # first one's.
    assert len(builds) == 1, f"one press, {len(builds)} builds of every archive's index"

    kept = json.loads(settings.settings_path(data_dir).with_name("settings.json.previous").read_text(encoding="utf-8"))
    assert kept == was, "settings.json.previous is not the version before the press"
    assert settings.answer_mode(data_dir) == "with_meaning", "the press did not land"


def test_the_two_choices_of_the_lock_are_refused_out_loud_and_change_nothing(an_instance):
    """Neither is reachable from the page as it is drawn, and both were swallowed anyway.

    One is a select of two values and the other an input carrying min and max, but what a browser
    will not send is not what this server will not be sent. Measured with a window of 0 minutes:
    the page said it had saved, and the window still stood at 240.
    """
    data_dir, archives = an_instance
    stood_at = settings.mcp_lock_minutes(data_dir)

    pressed = settings_pressed(data_dir, archives, build_indexes=lambda: None,
                               **a_whole_press(data_dir, archives, mcp_lock_minutes_choice=0,
                                               mcp_lock_scope_choice="whatever"))  # fmt: skip

    assert len(pressed.refused) == 2, pressed.refused
    assert any("How long a code lasts was not stored" in said for said in pressed.refused)
    assert any("What a code opens was not stored" in said for said in pressed.refused)
    assert all(said in pressed.trouble for said in pressed.refused)
    assert settings.mcp_lock_minutes(data_dir) == stood_at
    assert settings.mcp_lock_scope(data_dir) in ("conversation", "server")


def test_an_engine_that_cannot_answer_is_refused_in_words_and_not_in_silence(an_instance):
    """"no such engine: X" is a sentence written for a person, and it reached nobody.

    The page does say "Not ready" beside the radio it draws disabled, but that is the state of a
    thing, not an answer to a press.
    """
    data_dir, archives = an_instance
    stood_at = the_page.engines.chosen_engine(data_dir)

    pressed = settings_pressed(data_dir, archives, build_indexes=lambda: None,
                               **a_whole_press(data_dir, archives, engine="no-engine-of-this-name"))  # fmt: skip

    assert len(pressed.refused) == 1 and "The engine was not stored" in pressed.refused[0]
    assert the_page.engines.chosen_engine(data_dir) == stood_at


def test_a_settings_file_that_cannot_be_read_stores_nothing_and_says_which_file(an_instance):
    """Every write builds the whole file from what is there, so one saved setting would take the
    place of all the rest. The seventh entry of the constitution: which file, and what puts it
    right."""
    data_dir, archives = an_instance
    settings.settings_path(data_dir).parent.mkdir(parents=True, exist_ok=True)
    settings.settings_path(data_dir).write_text("{ not json", encoding="utf-8")

    pressed = settings_pressed(data_dir, archives, build_indexes=lambda: None,
                               **a_whole_press(data_dir, archives, mode="direct", tab="network"))  # fmt: skip

    assert pressed.stored == () and pressed.refused == ()
    assert pressed.draw_again is not None and pressed.draw_again["tab"] == "network"
    assert "data/settings.json" in pressed.draw_again["trouble"]
    assert settings.settings_path(data_dir).read_text(encoding="utf-8") == "{ not json"


def test_trying_a_threshold_stores_nothing_and_keeps_the_rest_of_the_page(an_instance):
    """Trying is not saving: a person turning a threshold over in their hands has decided nothing.

    And the page comes back from the submission rather than from storage. Without that, pressing
    "Try it" silently put back whatever had just been changed on the other three tabs — a switch,
    an answer mode, a model — and said nothing about it.
    """
    data_dir, archives = an_instance
    before = settings.rule_settings(data_dir, rules.load(data_dir).get(THREE_NUMBERS),
                                    in_archive=about(archives))

    press = a_whole_press(data_dir, archives, try_rule=THREE_NUMBERS, mode="direct", ask_page="on")
    press = nudged(press, f"{THREE_NUMBERS}:{list(before)[0]}", "99")
    pressed = settings_pressed(data_dir, archives, build_indexes=lambda: None, **press)

    assert pressed.stored == () and pressed.refused == ()
    assert pressed.draw_again["trying"] == (THREE_NUMBERS, dict(zip(press["knob_name"], press["knob_value"])))
    assert settings.rule_settings(data_dir, rules.load(data_dir).get(THREE_NUMBERS),
                                  in_archive=about(archives)) == before
    # The page drawn from that submission shows what was typed, not what is stored.
    shown = settings_view(data_dir, archives, **pressed.draw_again)
    tried = next(rule for rule in shown["rules"] if rule["id"] == THREE_NUMBERS)
    assert tried["knobs"][0]["value"] == "99" and shown["trying"] is True
    assert shown["mode"] == "direct" and shown["enabled"] is True, "the other tabs were put back"


def a_costly_step(monkeypatch) -> None:
    """Make the checks a step that asks first, so a rule of this instance is held back.

    No rule shipped here is costly today — the one step that is runs no rule yet — and a test that
    skips itself guards nothing. What is being asked is the holding back, and that is decided by
    the step a rule runs at, so the step is what this moves.
    """
    monkeypatch.setattr(kinds, "COSTLY", (kinds.VALIDATE,))


def test_a_costly_rule_is_held_back_for_asking_and_the_rest_of_the_press_is_stored(an_instance, monkeypatch):
    """A rule whose step reads documents again is not stored on the strength of a click.

    It is held back, said out loud with what it will cost, and stored on the second answer — and
    everything else in the same press is already stored, so answering yes is one step and not two.
    """
    data_dir, archives = an_instance
    press = a_whole_press(data_dir, archives, mode="direct")
    a_costly_step(monkeypatch)
    costly = next(rule for rule in rules.load(data_dir)
                  if rule.costly and not settings.rule_on(data_dir, rule, in_archive=about(archives)))  # fmt: skip

    held = {**also_on(press, costly.id), "confirmed_rules": []}
    pressed = settings_pressed(data_dir, archives, build_indexes=lambda: None, **held)

    assert pressed.waiting == {costly.id: {"on": True, "switching": True, "thresholds": {}}}
    assert settings.rule_on(data_dir, costly, in_archive=about(archives)) is False, "held back, and stored anyway"
    assert settings.answer_mode(data_dir) == "direct", "the rest of the press was held back with it"
    assert pressed.draw_again["waiting"] == pressed.waiting
    assert pressed.draw_again["stored"] == pressed.said

    # And stored on the second answer, which is one press and not two.
    said_yes = settings_pressed(data_dir, archives, build_indexes=lambda: None,
                                **also_on(press, costly.id))  # fmt: skip
    assert said_yes.waiting == {} and said_yes.draw_again is None
    assert settings.rule_on(data_dir, costly, in_archive=about(archives)) is True


def test_a_threshold_of_a_costly_rule_is_held_back_for_the_same_question(an_instance, monkeypatch):
    """A threshold of such a rule costs exactly what its switch costs, and was stored on a click.

    The check that stands between a person and that cost guarded the switch alone, three lines
    below the write it was supposed to guard. `least_number_share` from 0.9 to 0.5, or
    `least_characters` from 20 to 200, and the next run sends most of an archive to the strongest
    model there is — on one press, with the page saying "thresholds of 1 rule".
    """
    data_dir, archives = an_instance
    a_costly_step(monkeypatch)
    costly = next(rule for rule in rules.load(data_dir) if rule.costly and rule.settings)
    field = f"{costly.id}:{next(iter(costly.settings))}"
    was = settings.rule_settings(data_dir, costly, in_archive=about(archives))
    press = a_whole_press(data_dir, archives)

    typed = {**nudged(press, field, "7"), "confirmed_rules": []}
    pressed = settings_pressed(data_dir, archives, build_indexes=lambda: None, **typed)

    assert pressed.waiting[costly.id]["thresholds"] == {field.split(":", 1)[1]: "7"}
    assert pressed.waiting[costly.id]["switching"] is False, "the switch was not touched"
    assert settings.rule_settings(data_dir, costly, in_archive=about(archives)) == was, "held back, and stored anyway"
    # The question says which half of the press it is about. It said "Turning this on" over a
    # press that turned nothing on.
    drawn = settings_view(data_dir, archives, tab="rules", **{
        name: value for name, value in pressed.draw_again.items() if name != "tab"})  # fmt: skip
    row = next(one for one in drawn["rules"] if one["id"] == costly.id)
    assert row["waiting_about"] == "moving its thresholds"
    # And what was typed is still in the field, so saying yes is one press and not a page of
    # numbers to type again.
    assert str(next(knob["value"] for knob in row["knobs"]
                    if knob["field"] == field)) == "7"  # fmt: skip

    said_yes = settings_pressed(data_dir, archives, build_indexes=lambda: None,
                                **nudged(press, field, "7"))  # fmt: skip
    assert said_yes.waiting == {}
    assert settings.rule_settings(data_dir, costly, in_archive=about(archives))[field.split(":", 1)[1]] == 7


def test_the_rules_tab_says_which_archive_its_switches_are_about(an_instance):
    """The defect this card is about, and it was a mismatch rather than an absence.

    The count beside each switch was already counted on the archive being looked at — "found 255
    on 255 documents" — while the switch itself was one switch for the whole instance. So
    unticking that box turned the rule off on two other archives where it had found 24 and 4
    things worth looking at, with nothing on the page saying the two halves were about different
    things. The tab says which it is asking about now, and both answers are reachable by name.
    """
    data_dir, archives = an_instance
    whose = archives.showing.whose

    shown = settings_view(data_dir, archives, tab="rules")
    assert shown["rules_about"]["in_archive"] == archives.showing.id
    assert shown["rules_about"]["whose"] == whose and shown["rules_about"]["can_choose"] is True
    assert shown["rules_about"]["about"] == "archive"

    wide = settings_view(data_dir, archives, tab="rules", about="instance")
    assert wide["rules_about"]["in_archive"] == settings.THE_WHOLE_INSTANCE
    assert wide["rules_about"]["about"] == "instance"
    # The same archive is still the one the counts are of, and the page says so rather than
    # letting a person read an instance-wide switch and an archive's count as one thing.
    assert wide["rules_about"]["whose"] == whose

    # And the words are on the page itself, with the way to the other answer, and the hidden
    # field that carries which of the two a press was drawn about.
    from pathlib import Path

    from epicrisis import web

    page = (Path(web.__file__).parent / "templates" / "settings.html").read_text(encoding="utf-8")
    assert "Answering for" in page
    assert "every archive on this machine" in page
    assert "about=instance" in page, "and the way to the other one"
    # The field exactly, and not merely a field of that name: the form for writing a rule of
    # one's own has an "about" of its own, and an assertion on the name alone passed over a tab
    # that had stopped carrying which archive its switches were drawn about.
    assert '<input type="hidden" name="about" value="{{ rules_about.about }}">' in page


def test_a_press_on_the_rules_tab_answers_the_archive_it_was_drawn_about(an_instance):
    """One press, one archive, and the sentence it hands back says which.

    "2 rules switched" over a page that can answer for one archive or for every one of them says
    that something happened and not what — and the two presses are a word apart in the form.
    """
    data_dir, archives = an_instance
    rule = next(one for one in rules.load(data_dir) if not one.costly
                and not settings.rule_on(data_dir, one))  # fmt: skip
    only = archives.showing.id

    pressed = settings_pressed(data_dir, archives, build_indexes=lambda: None,
                               **also_on(a_whole_press(data_dir, archives), rule.id))  # fmt: skip

    assert settings.rule_on(data_dir, rule, in_archive=only) is True
    assert settings.rule_on(data_dir, rule) is False, "the instance was not answered"
    assert any("switched for" in said and archives.showing.whose in said for said in pressed.stored), pressed.stored

    # The other address answers for every archive, and says so.
    for_all = settings_pressed(data_dir, archives, build_indexes=lambda: None,
                               **also_on(a_whole_press(data_dir, archives, about="instance"), rule.id))  # fmt: skip
    assert settings.rule_on(data_dir, rule) is True
    assert any("for every archive" in said for said in for_all.stored), for_all.stored


def test_a_press_can_put_one_rule_back_under_the_instance_s_answer(an_instance):
    """A switch set for one archive and no way back is the seventh entry's dead end.

    And the order matters: the box beside it is drawn at whatever this archive answered, so
    reading the box before taking the answer away would write it straight back.
    """
    data_dir, archives = an_instance
    rule = next(one for one in rules.load(data_dir) if not one.costly
                and not settings.rule_on(data_dir, one))  # fmt: skip
    only = archives.showing.id
    settings.set_rule_on(data_dir, rule.id, True, in_archive=only)
    assert settings.answered_about(data_dir, rule.id, only) == {"on": True}

    press = also_on(a_whole_press(data_dir, archives), rule.id)
    pressed = settings_pressed(data_dir, archives, build_indexes=lambda: None,
                               **{**press, "the_instance_answers": [rule.id]})  # fmt: skip

    assert settings.answered_about(data_dir, rule.id, only) == {}
    assert settings.rule_on(data_dir, rule, in_archive=only) is False, "the instance's answer again"
    assert any(rule.name in said for said in pressed.stored), pressed.stored
    # Pressing it again, with nothing of its own left, stores nothing and says nothing.
    again = settings_pressed(data_dir, archives, build_indexes=lambda: None,
                             **{**a_whole_press(data_dir, archives), "the_instance_answers": [rule.id]})  # fmt: skip
    assert again.stored == ()


def test_a_switch_set_for_one_archive_says_so_beside_itself(an_instance):
    """A switch that looks the same whether it was answered here or inherited is a switch nobody
    can tell they have set, and the page has to say which of the two it is drawing."""
    data_dir, archives = an_instance
    rule = next(one for one in rules.load(data_dir) if not settings.rule_on(data_dir, one))
    only = archives.showing.id

    before = next(one for one in settings_view(data_dir, archives, tab="rules")["rules"]
                  if one["id"] == rule.id)  # fmt: skip
    assert before["its_own"] is False and before["on"] is False

    settings.set_rule_on(data_dir, rule.id, True, in_archive=only)

    after = next(one for one in settings_view(data_dir, archives, tab="rules")["rules"]
                 if one["id"] == rule.id)  # fmt: skip
    assert after["its_own"] is True and after["on"] is True
    assert after["instance_wide"] is False, "what every other archive runs by, said beside it"
    # On the instance-wide address nothing is "its own": there is no archive to be its own of.
    wide = next(one for one in settings_view(data_dir, archives, tab="rules", about="instance")["rules"]
                if one["id"] == rule.id)  # fmt: skip
    assert wide["its_own"] is False and wide["on"] is False


def test_the_journal_names_the_archive_a_rule_was_switched_for(an_instance):
    """The journal already records a settings change. A per-archive line names the archive the way
    "the archive shown was switched" already names one: the random id, and never a name."""
    from epicrisis import journal

    data_dir, archives = an_instance
    rule = next(one for one in rules.load(data_dir) if not settings.rule_on(data_dir, one))
    only = archives.showing.id

    settings.set_rule_on(data_dir, rule.id, True, in_archive=only)
    settings.set_rule_settings(data_dir, rule, {name: 7 for name in rule.settings}, in_archive=only)
    settings.let_the_instance_answer(data_dir, rule.id, only)

    said = [line for line in journal.entries(data_dir) if line.get("rule") == rule.id]
    assert [line["event"] for line in said] == [
        "a rule was switched on",
        "a rule's thresholds were changed",
        "an archive stopped answering a rule for itself",
    ]
    assert all(line["archive"] == only for line in said), said
    # And the instance's own answer is still written down without an archive on the line.
    settings.set_rule_on(data_dir, rule.id, True)
    wide = [line for line in journal.entries(data_dir)
            if line.get("rule") == rule.id and "archive" not in line]  # fmt: skip
    assert [line["event"] for line in wide] == ["a rule was switched on"]


def test_neither_half_of_the_page_can_be_asked_without_naming_an_archive(an_instance):
    """The first entry of the constitution: a door into an archive has no default for which one.

    These settings are the instance's, but what the page counts beside each rule is of the archive
    being looked at. Checked as the signature and not only as a call, because the way this goes
    wrong is somebody writing `archives: TheArchives = NO_ARCHIVES` to save a caller the trouble.
    """
    data_dir, _archives = an_instance
    for door in (settings_view, settings_pressed):
        with pytest.raises(TypeError):
            door(data_dir)
        which = inspect.signature(door).parameters["archives"]
        assert which.default is inspect.Parameter.empty, door.__name__
        assert which.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD, door.__name__

    # And named, it answers — including for an instance with nothing on its list at all, which is
    # an answer and not a fault: the settings page is the page a new instance starts on.
    assert settings_view(data_dir, NO_ARCHIVES)["read_materials_known"] == 0


def test_no_refusal_of_a_press_is_swallowed(an_instance):
    """Three of them were, and that is what this whole module was taken apart to stop.

    Read off the source rather than measured, because what is being asserted is that the shape
    cannot come back: every refusal this press catches is turned into a sentence for the person
    who pressed, and nothing here suppresses one. A `suppress(ValueError)` is how all three got
    in, and it reads like housekeeping.
    """
    written = ast.parse(textwrap.dedent(inspect.getsource(settings_pressed)))
    # The code and not the comments: the comments say the word a dozen times, because each of the
    # three refusals is explained where it was swallowed and what the page said instead.
    held = [node for node in ast.walk(written) if isinstance(node, ast.With)
            for item in node.items
            if "suppress" in ast.unparse(item.context_expr)]  # fmt: skip
    assert held == [], "a refusal of this press is being swallowed again"

    caught = [node for node in ast.walk(written)
              if isinstance(node, ast.ExceptHandler)
              and isinstance(node.type, ast.Name) and node.type.id == "ValueError"]  # fmt: skip
    assert caught, "nothing here catches a refusal any more, so this test has stopped guarding it"
    for handler in caught:
        said = ast.unparse(ast.Module(body=handler.body, type_ignores=[]))
        assert "refused.append" in said, f"a ValueError caught in silence at line {handler.lineno}"


def test_what_the_press_hands_back_is_a_value_and_not_a_page(an_instance):
    """The press returns what it stored and what it refused, and renders nothing itself.

    That is the shape the three swallowed refusals were mended by: something that returns what it
    turned down can be asked whether it said so, which is this file. A press that redirected or
    printed could only be asked over HTTP, by reading markup.
    """
    data_dir, archives = an_instance
    pressed = settings_pressed(data_dir, archives, build_indexes=lambda: None,
                               **a_whole_press(data_dir, archives, mode="with_meaning"))  # fmt: skip
    assert isinstance(pressed, Pressed)
    assert pressed.draw_again is None, "a press that is over draws nothing"
    assert pressed.stored and pressed.said == ", ".join(pressed.stored)
    assert the_page.ANSWER_MODE_NAMES["with_meaning"] in pressed.said

    # Which way the answer mode went, and not only which setting moved: the banner named the
    # setting and not the side, so the move into the one mode where this application compares a
    # number with a printed range and the move back out of it read exactly alike.
    back = settings_pressed(data_dir, archives, build_indexes=lambda: None,
                            **a_whole_press(data_dir, archives, mode="as_printed"))  # fmt: skip
    assert the_page.ANSWER_MODE_NAMES["as_printed"] in back.said
    assert back.said != pressed.said


def test_the_press_and_the_page_it_draws_again_speak_one_language(an_instance, monkeypatch):
    """`draw_again` is the page in `settings_view`'s own words, so the two cannot drift apart.

    The route forwards it as keyword arguments. A key the gatherer does not take would be a
    TypeError on a path only one press in three reaches — an unreadable settings file, a threshold
    tried out, a costly rule held back — and each of the three is rare enough to ship broken.
    """
    data_dir, archives = an_instance
    gathers = set(inspect.signature(settings_view).parameters) - {"data_dir", "archives"}
    settings.settings_path(data_dir).parent.mkdir(parents=True, exist_ok=True)

    presses = [a_whole_press(data_dir, archives, try_rule=THREE_NUMBERS)]
    a_costly_step(monkeypatch)
    costly = next(rule for rule in rules.load(data_dir) if rule.costly and not settings.rule_on(data_dir, rule))
    presses.append({**also_on(a_whole_press(data_dir, archives), costly.id), "confirmed_rules": []})
    for press in presses:
        pressed = settings_pressed(data_dir, archives, build_indexes=lambda: None, **press)
        assert pressed.draw_again is not None
        assert set(pressed.draw_again) <= gathers, pressed.draw_again
        settings_view(data_dir, archives, **pressed.draw_again)  # it draws, rather than raising

    settings.settings_path(data_dir).write_text("{ not json", encoding="utf-8")
    torn = settings_pressed(data_dir, archives, build_indexes=lambda: None, **a_whole_press(data_dir, archives))
    assert set(torn.draw_again) <= gathers, torn.draw_again
    assert settings_view(data_dir, archives, **torn.draw_again)["settings_unreadable"] is True


def test_the_press_runs_the_checks_before_it_builds_and_only_when_a_rule_moved(an_instance):
    """Stored first, then built out of it, and not at all where nothing the checks read changed.

    The checks and the index read settings.json off the disk, and the index reads it from threads
    of its own, so neither can run while the choices of a press are still gathered in one thread's
    hands. A rule turned off also has to stop counting now rather than at the next run of the
    checks: the findings of an archive are a file on disk, and leaving it would show a person
    findings from a rule they have just switched off.
    """
    data_dir, archives = an_instance
    validating = next(rule for rule in rules.load(data_dir)
                      if rule.at == kinds.VALIDATE and not rule.costly and not settings.rule_on(data_dir, rule))  # fmt: skip

    builds = []
    quiet = settings_pressed(data_dir, archives, build_indexes=lambda: builds.append(1) or None,
                             **a_whole_press(data_dir, archives))  # fmt: skip
    assert quiet.stored == () and builds == [], "a press that changed nothing built the index"

    moved = settings_pressed(data_dir, archives, build_indexes=lambda: builds.append(1) or None,
                             **also_on(a_whole_press(data_dir, archives), validating.id))  # fmt: skip
    assert builds == [1], "a rule of the checks moved and nothing was built in"
    assert "every archive checked again and built in" in moved.said


def test_a_threshold_typed_for_one_archive_does_not_age_the_others(an_instance, monkeypatch):
    """What a step is built from is per archive, and what was written down was every archive's
    answers in one lump.

    So a threshold typed for one archive of 23 documents put "this index is older than the files
    it is built from" over all three, and two of the three were checked and rebuilt for nothing.
    Measured: 0 badges before the change, 3 after, on archives of 43, 72 and 23 documents.
    """
    from epicrisis.settings import THE_WHOLE_INSTANCE, changed_for

    data_dir, archives = an_instance
    # A second archive, because the defect is one archive's answer reaching another's badge.
    folder = data_dir.parent.parent / "An archive of somebody else"
    folder.mkdir()
    SourceRegistry(data_dir).add(str(folder), owner="Another Person")
    mine, other = archives.showing.id, SourceRegistry(data_dir).list()[-1].id
    assert mine != other
    rule = next(one for one in rules.load(data_dir) if one.settings and not one.costly)
    before = {one: changed_for(data_dir, "validate", in_archive=one) for one in (mine, other)}

    settings.set_rule_settings(data_dir, rule, {next(iter(rule.settings)): "3"}, in_archive=mine)

    after = {one: changed_for(data_dir, "validate", in_archive=one) for one in (mine, other)}
    assert after[mine] > before[mine], "the archive it was typed for is behind, and should be"
    assert after[other] == before[other], "and the other two are not"

    # An answer for the whole instance moves every archive that has not overridden that rule:
    # what each archive reads includes what it inherits.
    settings.set_rule_on(data_dir, rule.id, False, in_archive=THE_WHOLE_INSTANCE)

    everyone = {one: changed_for(data_dir, "validate", in_archive=one) for one in (mine, other)}
    assert everyone[other] > after[other], "an instance-wide answer reaches the archives under it"
    assert everyone[mine] > after[mine]


def test_the_badge_over_one_archive_is_about_that_archive(an_instance):
    """The wiring, which the test above cannot see.

    `changed_for` answers per archive now, and the badge is drawn by `layout.changed_since` — so a
    test of the first alone stayed green with the second still asking the instance-wide question,
    which is the whole defect. Measured by mutation: putting the old call back failed nothing.
    """
    from epicrisis import layout
    from epicrisis.sources import source_output_dir

    data_dir, archives = an_instance
    folder = data_dir.parent.parent / "Another archive of nobody"
    folder.mkdir()
    SourceRegistry(data_dir).add(str(folder), owner="Somebody Else")
    mine, other = archives.showing.id, SourceRegistry(data_dir).list()[-1].id
    rule = next(one for one in rules.load(data_dir) if one.settings and not one.costly)
    outputs = {one: source_output_dir(data_dir, one) for one in (mine, other)}
    for output in outputs.values():
        output.mkdir(parents=True, exist_ok=True)
    before = {one: layout.changed_since(outputs[one], data_dir, "validate") for one in (mine, other)}

    settings.set_rule_settings(data_dir, rule, {next(iter(rule.settings)): "3"}, in_archive=mine)

    after = {one: layout.changed_since(outputs[one], data_dir, "validate") for one in (mine, other)}
    assert after[mine] > before[mine], "the archive it was typed for"
    assert after[other] == before[other], "and not the other, whose owner changed nothing"


def test_the_page_says_a_wait_only_where_somebody_is_being_held_out(an_instance):
    """The count beside the way out, asked of what is in those files rather than of how many.

    Each link keeps its run of wrong codes in a file of its own. A run answered correctly leaves
    the file holding `[]`; a run from last week has aged out of the window the wait can last.
    Counting files, this page said "1 link is in a wait after wrong codes" on the owner's own
    instance — measured, one file of two bytes holding nothing — and offered him the command.

    Of the view and not of the function beside it: a mutation that put the count of files back
    failed nothing, because the only test was of the counting and not of the page.
    """
    from epicrisis import mcp_lock

    data_dir, archives = an_instance
    answered = mcp_lock.where_the_wait_is_kept(data_dir, "aaaa1111")
    answered.parent.mkdir(parents=True, exist_ok=True)
    answered.write_text("[]", encoding="utf-8")

    assert settings_view(data_dir, archives, tab="network")["waits"] == 0

    mcp_lock.where_the_wait_is_kept(data_dir, "bbbb2222").write_text(
        json.dumps([time.time()] * mcp_lock.WRONG_CODES), encoding="utf-8")  # fmt: skip

    assert settings_view(data_dir, archives, tab="network")["waits"] == 1
