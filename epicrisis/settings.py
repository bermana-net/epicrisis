"""What this instance allows, kept in one file beside the archive: data/settings.json.

Every choice a person makes about their own instance lives here — which program talks to the
model and with which models, what an answer may contain, how a chart treats units, whether the
archive answers over the network and for how long. The file is written whole and put in place at
once, because a half-written settings file reads as no settings at all, and that would turn the
lock on the archive off without anybody saying so.

It used to live inside ask.py, the page that asks the model questions. That page owned the choice
of engine, of models, of units and of the lock on the network — none of which it has anything to
do with. A setting added tomorrow would have landed there again.

**Adding a setting:** one reader and one writer here, named after what a person would call it,
with the default in the reader. Nothing else in the program reads settings.json directly.
"""

import json
import time
from dataclasses import replace
from pathlib import Path

from epicrisis import layout, state
from epicrisis.runs import copy_whole, write_whole

# The name of the file, from the one place this program keeps the names of its files. It was
# written out here as well, and the two agreed only because nobody had yet moved one: the whole
# reason layout.py exists is that a name written in two places is a file somebody stops reading.
SETTINGS_FILE = layout.SETTINGS
ANSWER_MODES = ("as_printed", "with_meaning", "direct")

# Which of the choices in this file each built thing is built out of, and the one key of this file
# that is not a choice at all but the note of when those last changed.
#
# The checks and the index each say whether they have run since their inputs changed, and every
# other input of theirs is a file that answers that with its own mtime. This one file holds
# everything, so its mtime answered for everything: choosing another answer mode, or another model,
# or turning the lock on, each told a person on every page of every archive that the index was
# older than the files it is built from — and the banner came off only by building each archive's
# index again. A warning that fires for anything soon means nothing.
#
# So each step names what it reads. The index reads whether a material a model read is trusted,
# because that decides the material of every value in it. The checks read the rules: which are on,
# and with what thresholds. Rules reach the index too, but by way of validation.json — a file, with
# a time of its own, already counted as one. Anything not named here changes nothing that is built.
#
# "The rules" is every rule, not the ones the checks run: which rule belongs to which step is in the
# rule files, and settings.json holds them by id alone. So turning a rule of the charts on or off
# still says the checks are behind, on their badge on the status page, which they are not. That is
# the same kind of error as the one above and a hundredth of the size — one badge on one page, in the
# safe direction — and closing it would mean loading every rule file to read this file. Named here
# rather than left to be discovered.
READ_BY_A_STEP = {"validate": ("rules",), "index": ("read_materials",)}
# Not a setting: what those values were when a step was last told about them, and when that last
# changed. Kept in this file rather than beside it so that one write says both things at once and
# neither can be there without the other. No setting may take this name.
NOTED_UNDER = "built_from"


def answer_mode(data_dir: Path) -> str:
    """as_printed: values and printed ranges only. with_meaning: the model may also read them."""
    mode = _settings(data_dir).get("answer_mode", "as_printed")
    return mode if mode in ANSWER_MODES else "as_printed"


def set_answer_mode(data_dir: Path, mode: str) -> None:
    if mode not in ANSWER_MODES:
        raise ValueError("unknown answer mode")
    _write_settings(data_dir, {"answer_mode": mode})


def _settings(data_dir: Path) -> dict:
    try:
        return json.loads(settings_path(data_dir).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def unreadable(data_dir: Path) -> bool:
    """A settings file that is there and cannot be read. Not the same thing as no file at all.

    Everything here answers with its default when the file is missing, which is right for a new
    instance. For a file that exists and will not parse it is wrong, and for one setting it is
    dangerous: a truncated file would read as "no lock" over an archive whose owner had turned
    the lock on, and the page would go on saying it was on.
    """
    try:
        json.loads(settings_path(data_dir).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except (ValueError, OSError):
        return True
    return False


class Unreadable(state.Unreadable):
    """The settings file is there and will not parse. Nothing was written over it.

    One of a family now: sources.json, indicators.json and the index answer the same way and in
    the same words, because a person meeting any of them needs the same three things — the name
    of the file, what has not been lost, and the one act that puts it right. See state.py.
    """


def _write_settings(data_dir: Path, changes: dict) -> None:
    """Written whole and put in place at once, like every other file of state this program keeps.

    A half-written settings file is unreadable, and an unreadable one reads as no settings at
    all — which would turn the lock on the archive off without anybody saying so.

    Which is why nothing is written over one. A write builds the whole file from what is already
    there plus what changed, and over an unreadable file "what is already there" comes back
    empty: the one changed setting would be written and every other one — the engine, the three
    models, the answer mode, nineteen switches and the lock — would go, with the page saying
    "Saved." The lock fails closed on reading; it has to fail closed on writing too, or the first
    press of Save undoes that.
    """
    if unreadable(data_dir):
        raise Unreadable(
            SETTINGS_FILE,
            "Nothing was changed: writing one setting would have replaced every other one.",
            # An act, and the same act as for the other two files of choice. This said "repair that
            # file, or move it aside to start from the defaults", which is a description of the
            # trouble and an invitation to set nineteen switches again — the engine, three models,
            # the answer mode, the threshold of every rule, the lock and its window — while
            # sources.json and indicators.json each named a copy of themselves and a command.
            f"Repair it, or copy back {SETTINGS_FILE}.previous beside it — the version before the "
            f"last change, kept here since this instance last saved anything. Moving the file aside "
            f"instead starts every switch from its default, and each has to be answered again.",
        )
    before = _settings(data_dir)
    settings = {**before, **changes}
    settings[NOTED_UNDER] = _noted(before, settings)
    path = settings_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The version this replaces, kept beside it, as the list of archives and the vocabulary have
    # kept theirs all along. Three files hold what somebody chose; two of them could be put back
    # with one command and the third could not, and nothing about how it is written made it safer —
    # a hand editing it, a folder half restored, a file system that lost a write reach all three the
    # same way. What is in it is minutes of answering switches, and the answers are not guessable
    # from anything else on the disk.
    if path.exists():
        copy_whole(path, path.with_name(path.name + ".previous"))
    write_whole(path, json.dumps(settings, indent=1) + "\n")


def _read_by(kept: dict, step: str) -> dict:
    """What one step reads out of this file, as it stands. See READ_BY_A_STEP."""
    return {name: kept[name] for name in READ_BY_A_STEP[step] if name in kept}


def _note_in(kept: dict, step: str) -> dict | None:
    """The note one step left in this file, where there is one written in the shape it is written in.

    Anything else — no note, a note by hand, a note of another shape — is no note. A file a person
    has edited must not be able to take a page down, and this is read while every page is drawn.
    """
    notes = kept.get(NOTED_UNDER)
    note = notes.get(step) if isinstance(notes, dict) else None
    return note if isinstance(note, dict) else None


def _moment(value) -> float:
    """A moment as written down, and zero for anything that is not one."""
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _noted(before: dict, after: dict) -> dict:
    """For each built thing: what it reads, as this write leaves it, and when that last changed.

    A write that changes nothing a step reads leaves that step's moment where it was, which is the
    whole point: nothing built goes stale because somebody chose another model.

    A file with no note in it — every instance until this was written, and any file somebody has
    edited by hand — is taken to have been the file the steps were built from. The other reading,
    "no note means everything changed just now", is the false alarm this exists to end, and it
    would fire once on every instance that upgrades.
    """
    noted = {}
    for step in READ_BY_A_STEP:
        was, now = _read_by(before, step), _read_by(after, step)
        kept = _note_in(before, step) or {"read": was, "changed_at": 0.0}
        changed = was != now or kept.get("read") != was
        noted[step] = {"read": now, "changed_at": time.time() if changed else _moment(kept.get("changed_at"))}
    return noted


def changed_for(data_dir: Path, step: str) -> float:
    """When a choice this step is built from last changed here, as a moment to compare against.

    Zero where none ever has — a new instance, or one whose settings have never named anything this
    step reads. Nothing built is behind a choice that was never made.
    """
    stored = _settings(data_dir)
    kept = _note_in(stored, step)
    if kept is None:
        return 0.0
    if kept.get("read") != _read_by(stored, step):
        # The file says something the note does not account for: edited by hand, or restored from a
        # copy of another moment. When that happened is not written down anywhere, so the file's own
        # time is the best there is — the old answer, which cries wolf rather than keeping quiet.
        try:
            return settings_path(data_dir).stat().st_mtime
        except OSError:
            return 0.0
    return _moment(kept.get("changed_at"))


def settings_path(data_dir: Path) -> Path:
    return Path(data_dir) / SETTINGS_FILE


def _kept_for(data_dir: Path, rule_id: str):
    """What this instance stored about one rule, in either shape it has ever been stored in.

    It began as {id: true}. It is {id: {"on": true, "settings": {...}}} now, and the earlier
    shape is still read, because an archive that answered a switch once should not lose the
    answer to a change in how answers are written down.
    """
    kept = _settings(data_dir).get("rules", {}).get(rule_id)
    return {"on": kept} if isinstance(kept, bool) else (kept or {})


def rule_on(data_dir: Path, rule) -> bool:
    """Whether this instance runs this rule. Its own default until somebody says otherwise.

    One switch per rule, kept by the rule's id, so that a rule added later arrives with its own
    answer and an answer stored for a rule that has since been deleted simply stops mattering.
    """
    kept = _kept_for(data_dir, rule.id)
    if "on" in kept:
        return bool(kept["on"])
    # A check that has just become a rule keeps the answer this archive gave its old switch.
    if rule.was_called and rule.was_called in _settings(data_dir):
        return bool(_settings(data_dir)[rule.was_called])
    return rule.on_by_default


def rule_settings(data_dir: Path, rule) -> dict:
    """The rule's own settings, with whatever this instance changed, and nothing else.

    A name the rule does not have is dropped rather than carried: a setting stored under a name
    the kind has since renamed would otherwise travel for ever, doing nothing, looking like a
    thing that works.
    """
    changed = _kept_for(data_dir, rule.id).get("settings") or {}
    return {**rule.settings, **{name: value for name, value in changed.items() if name in rule.settings}}


def as_chosen(data_dir: Path, rule):
    """The rule as this archive runs it: its file, with this archive's settings over the top."""
    return replace(rule, settings=rule_settings(data_dir, rule))


def set_rule_on(data_dir: Path, rule_id: str, enabled: bool) -> None:
    kept = _settings(data_dir).get("rules", {})
    was = kept.get(rule_id)
    was = {"on": was} if isinstance(was, bool) else (was or {})
    _write_settings(data_dir, {"rules": {**kept, rule_id: {**was, "on": enabled}}})


def set_rule_settings(data_dir: Path, rule, values: dict) -> None:
    """What this archive chose for one rule, where it differs from what the rule ships with.

    A value equal to the default is not stored: typing the shipped number back in is how a
    person undoes a change, and it should leave nothing behind saying they ever made one.
    """
    wanted = {}
    for name, default in rule.settings.items():
        if name not in values:
            continue
        try:
            wanted[name] = type(default)(values[name]) if not isinstance(default, list) else list(values[name])
        except (TypeError, ValueError):
            raise ValueError(f"{name} should be {type(default).__name__}") from None
        if wanted[name] == default:
            del wanted[name]
    kept = _settings(data_dir).get("rules", {})
    was = kept.get(rule.id)
    was = {"on": was} if isinstance(was, bool) else (was or {})
    _write_settings(data_dir, {"rules": {**kept, rule.id: {**was, "settings": wanted}}})


def rules_on(data_dir: Path, loaded, step: str) -> list:
    """The rules one step runs here: its own, as this archive set them, minus the ones turned off."""
    return [as_chosen(data_dir, rule) for rule in loaded.at(step) if rule_on(data_dir, rule)]


# What a chart does with units, and what a value with no unit is placed beside, used to be three
# switches here. They are rules now — see epicrisis/rules/shipped — because they are the same
# kind of decision as every other rule: they can be turned off, they can be wrong, and a person
# deciding about one needs to read why.


def trusts_read_materials(data_dir: Path) -> bool:
    """Whether a material a model read is used, where the form printed none.

    Off in the repository, like every other reading this program does not do by itself: with it
    off, a value whose form said nothing stays under "not said", which is what the form says.
    Turned on, the panel a model was sure of settles it, and every such value is marked on the
    page as read rather than printed. What the model was unsure of is never used either way.
    """
    return bool(_settings(data_dir).get("read_materials"))


def set_trusts_read_materials(data_dir: Path, enabled: bool) -> None:
    _write_settings(data_dir, {"read_materials": enabled})


def chosen_models(data_dir: Path) -> dict[str, str]:
    """Which model the person picked for each pass. Empty means the ones this program ships with."""
    chosen = _settings(data_dir).get("models")
    return chosen if isinstance(chosen, dict) else {}


def set_chosen_models(data_dir: Path, models: dict[str, str]) -> None:
    from epicrisis.models import PASSES

    # A name is an argument to a command, never a shell string, so nothing here can run; but a
    # five-hundred-character name would only fail obscurely when that step runs, so it is cut.
    kept = {name: value.strip()[:80] for name, value in models.items() if name in PASSES and value.strip()}
    _write_settings(data_dir, {"models": kept})


def mcp_lock_on(data_dir: Path) -> bool:
    """Whether the tools over the network ask for a code first. Off in the repository by default.

    The one setting that fails closed. If the file cannot be read and a secret has been set up on
    this server, the lock stays on: an unreadable file must not be able to open an archive, and a
    person who armed the lock and sees it drawn as on has to be right. Where no secret was ever
    set up there is nothing to fail closed about, and asking for a code nobody can produce would
    only shut a person out of their own archive over a corrupt file.
    """
    from epicrisis.mcp_lock import read_secret

    if unreadable(data_dir):
        return read_secret() is not None
    return bool(_settings(data_dir).get("mcp_lock"))


def set_mcp_lock(data_dir: Path, enabled: bool) -> None:
    _write_settings(data_dir, {"mcp_lock": enabled})


def mcp_lock_scope(data_dir: Path) -> str:
    """conversation: a code opens the conversation it was given in. server: it opens everything."""
    from epicrisis.mcp_lock import SCOPES

    scope = _settings(data_dir).get("mcp_lock_scope", "conversation")
    return scope if scope in SCOPES else "conversation"


def set_mcp_lock_scope(data_dir: Path, scope: str) -> None:
    from epicrisis.mcp_lock import SCOPES

    if scope not in SCOPES:
        raise ValueError("a lock opens a conversation or the server")
    _write_settings(data_dir, {"mcp_lock_scope": scope})


def mcp_lock_minutes(data_dir: Path) -> int:
    """How long one code keeps the archive open."""
    from epicrisis.mcp_lock import PASS_MINUTES

    minutes = _settings(data_dir).get("mcp_lock_minutes", PASS_MINUTES)
    return minutes if isinstance(minutes, int) and 1 <= minutes <= 7 * 24 * 60 else PASS_MINUTES


def set_mcp_lock_minutes(data_dir: Path, minutes: int) -> None:
    if not 1 <= int(minutes) <= 7 * 24 * 60:
        raise ValueError("a window runs from a minute to a week")
    _write_settings(data_dir, {"mcp_lock_minutes": int(minutes)})


def ask_enabled(data_dir: Path) -> bool:
    return bool(_settings(data_dir).get("ask"))


def set_ask_enabled(data_dir: Path, enabled: bool) -> None:
    _write_settings(data_dir, {"ask": enabled})
