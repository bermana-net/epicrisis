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

import pytest

from epicrisis import rules, settings
from epicrisis.rules import kinds
from epicrisis.sources import NO_ARCHIVES, SourceRegistry
from epicrisis.web import settings_page as the_page
from epicrisis.web.settings_page import Pressed, settings_pressed, settings_view

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


def a_whole_press(data_dir, **asked) -> dict:
    """The page exactly as it is drawn, submitted unchanged, plus whatever is asked for here.

    Built from the rules this instance loads rather than written out, so a rule shipped next
    month is in the press without anybody remembering to put it there. Every value starts at what
    is stored, because a checkbox that is not ticked is not sent at all: a press written out with
    fewer switches than the page draws is a press that turns the missing ones off, which is a
    different press and not a smaller one.
    """
    shown, knob_name, knob_value, on = [], [], [], []
    for rule in rules.load(data_dir):
        shown.append(rule.id)
        if settings.rule_on(data_dir, rule):
            on.append(rule.id)
        chosen = settings.rule_settings(data_dir, rule)
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
    before = settings.rule_settings(data_dir, rule)
    mistyped, *good = list(rule.settings)

    press = a_whole_press(data_dir)
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

    now = settings.rule_settings(data_dir, rule)
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
        press = a_whole_press(data_dir, mode="with_meaning", mcp_lock_minutes_choice=120,
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
                               **a_whole_press(data_dir, mcp_lock_minutes_choice=0,
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
                               **a_whole_press(data_dir, engine="no-engine-of-this-name"))  # fmt: skip

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
                               **a_whole_press(data_dir, mode="direct", tab="network"))  # fmt: skip

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
    before = settings.rule_settings(data_dir, rules.load(data_dir).get(THREE_NUMBERS))

    press = a_whole_press(data_dir, try_rule=THREE_NUMBERS, mode="direct", ask_page="on")
    press = nudged(press, f"{THREE_NUMBERS}:{list(before)[0]}", "99")
    pressed = settings_pressed(data_dir, archives, build_indexes=lambda: None, **press)

    assert pressed.stored == () and pressed.refused == ()
    assert pressed.draw_again["trying"] == (THREE_NUMBERS, dict(zip(press["knob_name"], press["knob_value"])))
    assert settings.rule_settings(data_dir, rules.load(data_dir).get(THREE_NUMBERS)) == before
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
    press = a_whole_press(data_dir, mode="direct")
    a_costly_step(monkeypatch)
    costly = next(rule for rule in rules.load(data_dir) if rule.costly and not settings.rule_on(data_dir, rule))

    held = {**also_on(press, costly.id), "confirmed_rules": []}
    pressed = settings_pressed(data_dir, archives, build_indexes=lambda: None, **held)

    assert pressed.waiting == {costly.id: True}
    assert settings.rule_on(data_dir, costly) is False, "held back, and stored anyway"
    assert settings.answer_mode(data_dir) == "direct", "the rest of the press was held back with it"
    assert pressed.draw_again["waiting"] == pressed.waiting
    assert pressed.draw_again["stored"] == pressed.said

    # And stored on the second answer, which is one press and not two.
    said_yes = settings_pressed(data_dir, archives, build_indexes=lambda: None,
                                **also_on(press, costly.id))  # fmt: skip
    assert said_yes.waiting == {} and said_yes.draw_again is None
    assert settings.rule_on(data_dir, costly) is True


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
                               **a_whole_press(data_dir, mode="with_meaning"))  # fmt: skip
    assert isinstance(pressed, Pressed)
    assert pressed.draw_again is None, "a press that is over draws nothing"
    assert pressed.stored and pressed.said == ", ".join(pressed.stored)
    assert the_page.ANSWER_MODE_NAMES["with_meaning"] in pressed.said

    # Which way the answer mode went, and not only which setting moved: the banner named the
    # setting and not the side, so the move into the one mode where this application compares a
    # number with a printed range and the move back out of it read exactly alike.
    back = settings_pressed(data_dir, archives, build_indexes=lambda: None,
                            **a_whole_press(data_dir, mode="as_printed"))  # fmt: skip
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

    presses = [a_whole_press(data_dir, try_rule=THREE_NUMBERS)]
    a_costly_step(monkeypatch)
    costly = next(rule for rule in rules.load(data_dir) if rule.costly and not settings.rule_on(data_dir, rule))
    presses.append({**also_on(a_whole_press(data_dir), costly.id), "confirmed_rules": []})
    for press in presses:
        pressed = settings_pressed(data_dir, archives, build_indexes=lambda: None, **press)
        assert pressed.draw_again is not None
        assert set(pressed.draw_again) <= gathers, pressed.draw_again
        settings_view(data_dir, archives, **pressed.draw_again)  # it draws, rather than raising

    settings.settings_path(data_dir).write_text("{ not json", encoding="utf-8")
    torn = settings_pressed(data_dir, archives, build_indexes=lambda: None, **a_whole_press(data_dir))
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
                             **a_whole_press(data_dir))  # fmt: skip
    assert quiet.stored == () and builds == [], "a press that changed nothing built the index"

    moved = settings_pressed(data_dir, archives, build_indexes=lambda: builds.append(1) or None,
                             **also_on(a_whole_press(data_dir), validating.id))  # fmt: skip
    assert builds == [1], "a rule of the checks moved and nothing was built in"
    assert "every archive checked again and built in" in moved.said
