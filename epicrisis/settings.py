"""What this instance allows, kept in one file beside the archive: data/settings.json.

Every choice a person makes about their own instance lives here — which program talks to the
model and with which models, what an answer may contain, how a chart treats units, whether the
archive answers over the network and for how long. The file is written whole and put in place at
once, because a half-written settings file reads as no settings at all, and that would turn the
lock on the archive off without anybody saying so.

It used to live inside ask.py, the page that asks the model questions. That page owned the choice
of engine, of models, of units and of the lock on the network — none of which it has anything to
do with. A setting added tomorrow would have landed there again.

One writer at a time, and one write per change: every writer here is read-modify-write over a
person's own choices, so each takes this file's lock, and a change that touches a dozen settings
at once — one press of Save on the settings page — puts one file in place and keeps one copy of
the version before it. See `editing` below for what each half of that cost before it was there.

**Adding a setting:** one reader and one writer here, named after what a person would call it,
with the default in the reader, and `@while_editing` over the writer. Nothing else in the program
reads settings.json directly. A change of it is written down in the journal by the one door every
writer goes through, so there is nothing to remember for that — except to say in `SAID_IN_FULL`
whether the value may be written down as well as the name.
"""

import copy
import functools
import json
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from epicrisis import journal, layout, state
from epicrisis.runs import copy_whole, one_at_a_time, write_whole

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

# Which settings a journal line may say the value of.
#
# Everything in this file is the program's own word — a rule id, the name of an answer mode, the
# name of an engine this program ships, a number of minutes — and not one of them is a string off
# anybody's form, so the line says what the setting became and a person reading the journal next
# month can answer "when did this stop being checked?".
#
# A setting whose value could ever carry a string somebody's document printed does not belong in
# this list. Its line then names the setting and not what it became, which is the safe half of
# the seventh entry rather than the first entry broken, and a journal that cannot be pasted into
# a stranger's chat whole is the one thing journal.py is written not to be.
#
# Named here rather than decided where the line is written, and as a list of what may be said
# rather than of what may not: a setting added tomorrow then says that it changed and stays quiet
# about the value until somebody has answered this question about it. The two settings that are
# not plain values — the rules and the models — have their own lines below, for the same reason
# and with the same test.
SAID_IN_FULL = ("answer_mode", "engine", "read_materials", "mcp_lock", "mcp_lock_scope",
                "mcp_lock_minutes", "ask")  # fmt: skip
_NEVER_SET = object()  # a setting this file has never held is not the same as one holding None

# The change open in this thread, if one is: see editing() below. One per folder, because an
# instance can be told to work in two of them in one process and each has a settings file of its
# own; one thread with a change open on each must not take the second one's lock twice.
_being_changed = threading.local()


def _key(data_dir: Path) -> str:
    """One name for one folder, however it was spelled, so a nested change finds its own."""
    return str(Path(data_dir).resolve())


def _changes_open() -> dict:
    open_now = getattr(_being_changed, "by_folder", None)
    if open_now is None:
        open_now = _being_changed.by_folder = {}
    return open_now


def _change_open(data_dir: Path):
    """The change this thread has open over this folder's settings file, if there is one."""
    return _changes_open().get(_key(data_dir))


class _Change:
    """One change of settings.json, open for as long as its lock is held.

    The file is read when the first write arrives and not before, so a change that turns out to
    change nothing reads nothing and writes nothing — and an unreadable file stops a write rather
    than the taking of a lock.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.before: dict | None = None  # the file as this change found it
        self.now: dict | None = None  # and what the writers under it have made of it
        self.to_say: list[dict] = []  # one journal line per setting this change really changes

    def write(self, changes: dict) -> None:
        """Gather one writer's changes. Nothing reaches the disk until the change closes."""
        if self.before is None:
            if unreadable(self.data_dir):
                raise Unreadable(
                    SETTINGS_FILE,
                    "Nothing was changed: writing one setting would have replaced every other one.",
                    # An act, and the same act as for the other two files of choice. This said "repair
                    # that file, or move it aside to start from the defaults", which is a description
                    # of the trouble and an invitation to set nineteen switches again — the engine,
                    # three models, the answer mode, the threshold of every rule, the lock and its
                    # window — while sources.json and indicators.json each named a copy of themselves
                    # and a command.
                    f"Repair it, or copy back {SETTINGS_FILE}.previous beside it — the version before "
                    f"the last change, kept here since this instance last saved anything. Moving the "
                    f"file aside instead starts every switch from its default, and each has to be "
                    f"answered again.",
                )
            self.before = _stored(self.data_dir)
            self.now = dict(self.before)
        # Read against the change as it stands rather than against the file, so that the second
        # writer of one press is compared with what the first one made of it and not with what
        # both of them found. Gathered here and written when the file is in place: a line saying
        # a setting changed over a press that then raised, and never reached the disk, would be
        # the journal disagreeing with the file it sits beside.
        self.to_say += _what_changed(self.now, changes)
        self.now.update(changes)

    def put_in_place(self) -> None:
        """Written whole and put in place at once, like every other file of state this program keeps.

        A half-written settings file is unreadable, and an unreadable one reads as no settings at
        all — which would turn the lock on the archive off without anybody saying so.

        Which is why nothing is written over one. A write builds the whole file from what is
        already there plus what changed, and over an unreadable file "what is already there" comes
        back empty: the one changed setting would be written and every other one — the engine, the
        three models, the answer mode, nineteen switches and the lock — would go, with the page
        saying "Saved." The lock fails closed on reading; it has to fail closed on writing too, or
        the first press of Save undoes that. That is asked in write() above, before the first
        writer of a change is let near the file.
        """
        if self.now is None:
            return
        settings = {**self.now, NOTED_UNDER: _noted(self.before, self.now)}
        path = settings_path(self.data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        # The version this replaces, kept beside it, as the list of archives and the vocabulary have
        # kept theirs all along. Three files hold what somebody chose; two of them could be put back
        # with one command and the third could not, and nothing about how it is written made it safer —
        # a hand editing it, a folder half restored, a file system that lost a write reach all three the
        # same way. What is in it is minutes of answering switches, and the answers are not guessable
        # from anything else on the disk.
        #
        # One copy per change, and so one per press of Save: the whole point of the name is that it
        # is the version before the last change, and a copy per writer made it the middle of one.
        if path.exists():
            copy_whole(path, path.with_name(path.name + ".previous"))
        write_whole(path, json.dumps(settings, indent=1) + "\n")
        # After the write, and only for what really changed. A rule that decides what is checked
        # on somebody's documents could be switched off, the file changed, a copy of the version
        # before it written beside it — and nothing anywhere remembered that it had happened or
        # when. The same held for the model, the answer mode, the lock over the network and every
        # threshold. The seventh entry says the program says out loud everything it does, and this
        # file is where it says the things that are nobody's step and nobody's page.
        #
        # No archive is named: every setting here is this instance's, and journal.jsonl sits in
        # the same folder as settings.json. A per-archive setting added later would name the
        # archive by its id, as "the archive shown was switched" does.
        for line in self.to_say:
            journal.record(self.data_dir, line)


@contextmanager
def editing(data_dir: Path):
    """Hold this file's lock for the whole of a change, and make the whole change one write.

    Two things, because they are one thing.

    **The lock.** settings.json is one file for the whole server and every write to it builds the
    file again out of what it read, so two writers without this each read, each change their own
    copy, and the second rename silently undoes the first. The dashboard is a FastAPI application
    whose plain handlers run in a pool of threads, and the commands take the same path the buttons
    do, so two writers at once is not a theory. The twins of this module — indicators.py and
    people.py, the same read-modify-write over a person's own choices — have each had their lock
    since the day it happened to them. This was the third such file and the only one without one.

    **One write.** A lock alone would have left the other half of it. One press of Save on the
    settings page calls a dozen writers in turn, and each of them wrote the whole file and copied
    the whole file to settings.json.previous: measured on a page of 26 rules and 25 thresholds,
    with every switch flipped and every threshold nudged, one press wrote the file 44 times and
    made 44 copies. The last of those copies is the file as the 44th write found it — the middle
    of that same press — and the refusal this module prints over an unreadable file offers
    .previous in so many words as "the version before the last change". Following that written
    advice handed a person half of their own last press: measured on a press changing a threshold
    of each of two rules, which stood at 99 and 7 before and at 11 and 3 after, .previous held 11
    — already the new one — beside the old 7, a pair nobody had ever chosen.

    So a change opened here gathers every write made under it and puts one file in place when it
    closes, with one copy of the version it began from. Re-entering while a change is already open
    over the same folder in this thread joins that change instead of taking the lock again — which
    is what lets every set_* below both stand on its own and be one line of a press.

    The loser of a race is told: one_at_a_time refuses with Busy rather than queueing, the
    dashboard answers that as a page naming the lock, and a command prints it.
    """
    data_dir = Path(data_dir)
    open_now = _change_open(data_dir)
    if open_now is not None:
        yield open_now
        return
    with one_at_a_time(data_dir / "settings.lock", "Editing the settings"):
        change = _Change(data_dir)
        _changes_open()[_key(data_dir)] = change
        try:
            yield change
            change.put_in_place()
        finally:
            _changes_open().pop(_key(data_dir), None)


def while_editing(change):
    """Hold the lock for the whole of a writer, not only for the write at the end.

    Every writer below reads this file, changes what it read and writes it back. Guarding the
    write alone leaves the read outside, and the window between the two is a window in which
    another writer's whole file disappears — which is exactly the failure people.py describes in
    its own copy of this, where the lock existed and nothing called it.
    """

    @functools.wraps(change)
    def guarded(data_dir: Path, *args, **kwargs):
        with editing(data_dir):
            return change(data_dir, *args, **kwargs)

    return guarded


def _write_settings(data_dir: Path, changes: dict) -> None:
    """One writer's worth of changes, under the lock, into the change this press has open."""
    with editing(data_dir) as change:
        change.write(changes)


def _what_changed(stored: dict, changes: dict) -> list[dict]:
    """A journal line for each setting these changes really change, and none for the rest.

    One door into this file means one place to say what went through it: every writer below calls
    _write_settings, which hands its changes to _Change.write, which asks this. A writer added
    tomorrow is written down by having been written, and not by its author remembering to.

    Nothing is said about a write that changes nothing. One press of Save calls a dozen writers
    in turn and the settings page asks each question before it asks for the write — but a command
    does not have to, and a journal keeping five thousand lines must not be filled with "the lock
    stayed where it was" until the failures have been pushed out of the other end of it. That is
    the trade a_page_would_not_read makes in journal.py, made again here.
    """
    said: list[dict] = []
    for name, value in changes.items():
        if name == "rules":
            said += _rules_changed(stored.get(name) or {}, value or {})
        elif name == "models":
            said += _models_changed(stored.get(name) or {}, value or {})
        elif stored.get(name, _NEVER_SET) != value:
            said.append({"event": "a setting was changed", "setting": name,
                         **({"became": value} if name in SAID_IN_FULL else {}),
                         **_first_answer(stored, name)})  # fmt: skip
    return said


def _first_answer(stored: dict, name: str) -> dict:
    """Whether this file had ever held an answer to this switch before.

    Said because the line is read to answer "when did this stop being checked?", and a line that
    says a setting became false reads as somebody having turned it off. On an instance where the
    file never held it, the setting stood at whatever its reader answers — which is its default,
    written in that reader and reachable from nowhere here — so `epicrisis mcp-lock off` over a
    lock that had never been on would otherwise be written down as the moment somebody turned it
    off. The line says what the file did and marks what it cannot say about what was there before.
    """
    return {} if name in stored else {"first_answer": True}


def _rules_changed(stored: dict, now: dict) -> list[dict]:
    """Which rule was switched, and whose thresholds moved to what.

    A rule id is this program's own word — the name of a file in epicrisis/rules/shipped — and a
    threshold is a number, so both are written down. A threshold of any other shape is named
    without its value: the kinds ship numbers today and the writer below would take a word or a
    list, and a word a rule was given is a word somebody typed.

    Both shapes of a stored rule are read, because a rule answered before the thresholds existed
    is stored as a plain true or false, and a switch that read that as "no entry" would report
    every such rule as having just been switched.
    """
    said = []
    for rule_id, entry in now.items():
        was, became = _as_kept(stored.get(rule_id)), _as_kept(entry)
        if was.get("on") != became.get("on") and "on" in became:
            # Which rules ship on and which ship off is in the rule files, and this module does
            # not load them — see READ_BY_A_STEP, where the same door was shut for the same
            # reason. So a rule whose switch this file had never held is marked as answered for
            # the first time rather than reported as having been changed from its own default.
            said.append({"event": "a rule was switched " + ("on" if became["on"] else "off"),
                         "rule": rule_id, **({} if "on" in was else {"first_answer": True})})  # fmt: skip
        moved = {name: value for name, value in (became.get("settings") or {}).items()
                 if (was.get("settings") or {}).get(name, _NEVER_SET) != value}  # fmt: skip
        shipped = [name for name in (was.get("settings") or {})
                   if name not in (became.get("settings") or {})]  # fmt: skip
        if moved or shipped:
            numbers = {name: value for name, value in moved.items()
                       if isinstance(value, bool | int | float)}  # fmt: skip
            said.append({"event": "a rule's thresholds were changed", "rule": rule_id,
                         **({"thresholds": numbers} if numbers else {}),
                         **({"not_said": sorted(set(moved) - set(numbers))} if len(numbers) < len(moved) else {}),
                         **({"as_shipped": sorted(shipped)} if shipped else {})})  # fmt: skip
    return said


def _as_kept(entry) -> dict:
    """One rule as this file stores it, in either shape it has ever been stored in. See _kept_for."""
    return {"on": entry} if isinstance(entry, bool) else (entry if isinstance(entry, dict) else {})


def _models_changed(stored: dict, now: dict) -> list[dict]:
    """Which pass got another model, and which one — where this program knows the name.

    A pass is one of three words of this program's own. A model name is not: the list in models.py
    is what this program ships knowing, and anything else can be typed into the field, so a name
    that is not in that list is a string somebody typed and is not written down. What the line
    says then is that the pass was given a model this program does not name, which is the half of
    it that is nobody's.

    Compared against the model each pass actually ran with, defaults and all, rather than against
    what the file happened to hold: the page sends all three fields on every press, so a file that
    had never named a model would otherwise report three changes the first time anybody pressed
    Save over a page they had changed nothing on.
    """
    from epicrisis.models import KNOWN_MODELS, PASSES

    known = {name for name, _ in KNOWN_MODELS}
    said = []
    for pass_name in PASSES:
        was, became = _chose(stored, pass_name), _chose(now, pass_name)
        if was != became:
            said.append({"event": "a model was chosen for a pass", "pass": pass_name,
                         **({"model": became} if became in known else {"known": False})})  # fmt: skip
    return said


def _chose(models: dict, pass_name: str) -> str:
    """The model one pass runs with, as model_for reads it. Its own default where nothing was chosen."""
    from epicrisis.models import PASSES

    default = PASSES[pass_name]["default"]
    return (str(models.get(pass_name) or default).strip() or default)


def answer_mode(data_dir: Path) -> str:
    """as_printed: values and printed ranges only. with_meaning: the model may also read them."""
    mode = _settings(data_dir).get("answer_mode", "as_printed")
    return mode if mode in ANSWER_MODES else "as_printed"


@while_editing
def set_answer_mode(data_dir: Path, mode: str) -> None:
    if mode not in ANSWER_MODES:
        raise ValueError("unknown answer mode")
    _write_settings(data_dir, {"answer_mode": mode})


def _settings(data_dir: Path) -> dict:
    """What this file says — or what a change open over it in this thread has made of it so far.

    Every writer below builds the whole file out of this read, so two writers of one press that
    each read from the disk would each write the other one's work away. Inside a change they read
    the change instead, and one file reaches the disk at the end of it holding all of them.

    Readers in other threads go on seeing the file as it is until that one write lands, which is
    the other half of the same thing: nobody is ever shown half of somebody's press.
    """
    open_now = _change_open(data_dir)
    if open_now is not None and open_now.now is not None:
        return copy.deepcopy(open_now.now)
    return _stored(data_dir)


def _stored(data_dir: Path) -> dict:
    """What is written in the file, with no change of this thread's laid over it."""
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


@while_editing
def set_rule_on(data_dir: Path, rule_id: str, enabled: bool) -> None:
    kept = _settings(data_dir).get("rules", {})
    was = kept.get(rule_id)
    was = {"on": was} if isinstance(was, bool) else (was or {})
    _write_settings(data_dir, {"rules": {**kept, rule_id: {**was, "on": enabled}}})


# What a threshold of each shape wants, said the way a person says it rather than the way Python
# names it. These sentences are printed on the settings page beside the field they are about, and
# "times_away should be int" is not a sentence anybody can type a number out of.
IN_WORDS = {int: "a whole number", float: "a number", bool: "true or false", str: "a word",
            list: "a list"}  # fmt: skip


def _as_shipped(default, value):
    """One typed value in the shape the rule ships that threshold in, or what the shape refuses."""
    return list(value) if isinstance(default, list) else type(default)(value)


def what_a_rule_cannot_use(rule, values: dict) -> dict[str, str]:
    """Which of these the rule cannot read as a threshold, and what it wanted instead, in words.

    Asked before the write rather than discovered in the middle of it. set_rule_settings refuses
    the whole rule on the first value it cannot read, and the write it never reaches replaces
    every threshold of that rule at once — so one mistyped number took every other threshold of
    the same rule with it. Which the page then reported as "Saved. Nothing on the page was
    different from what was already stored": the refusal had a cause, the cause was written down
    for a person in this module, and a suppress(ValueError) ate it.
    """
    cannot = {}
    for name, default in rule.settings.items():
        if name not in values:
            continue
        try:
            _as_shipped(default, values[name])
        except (TypeError, ValueError):
            cannot[name] = IN_WORDS.get(type(default), "a value of the shape this rule ships")
    return cannot


@while_editing
def set_rule_settings(data_dir: Path, rule, values: dict) -> None:
    """What this archive chose for one rule, where it differs from what the rule ships with.

    A value equal to the default is not stored: typing the shipped number back in is how a
    person undoes a change, and it should leave nothing behind saying they ever made one.

    Every threshold named in values is written or none of them is. A caller with several in hand
    asks what_a_rule_cannot_use first, so that the good ones are not lost with the bad one.
    """
    wanted = {}
    for name, default in rule.settings.items():
        if name not in values:
            continue
        try:
            wanted[name] = _as_shipped(default, values[name])
        except (TypeError, ValueError):
            raise ValueError(f"{name} should be {IN_WORDS.get(type(default), 'what this rule ships')}") from None
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


@while_editing
def set_trusts_read_materials(data_dir: Path, enabled: bool) -> None:
    _write_settings(data_dir, {"read_materials": enabled})


def chosen_models(data_dir: Path) -> dict[str, str]:
    """Which model the person picked for each pass. Empty means the ones this program ships with."""
    chosen = _settings(data_dir).get("models")
    return chosen if isinstance(chosen, dict) else {}


@while_editing
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


@while_editing
def set_mcp_lock(data_dir: Path, enabled: bool) -> None:
    _write_settings(data_dir, {"mcp_lock": enabled})


def mcp_lock_scope(data_dir: Path) -> str:
    """conversation: a code opens the conversation it was given in. server: it opens everything."""
    from epicrisis.mcp_lock import SCOPES

    scope = _settings(data_dir).get("mcp_lock_scope", "conversation")
    return scope if scope in SCOPES else "conversation"


@while_editing
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


@while_editing
def set_mcp_lock_minutes(data_dir: Path, minutes: int) -> None:
    if not 1 <= int(minutes) <= 7 * 24 * 60:
        raise ValueError("a window runs from a minute to a week")
    _write_settings(data_dir, {"mcp_lock_minutes": int(minutes)})


def ask_enabled(data_dir: Path) -> bool:
    return bool(_settings(data_dir).get("ask"))


@while_editing
def set_ask_enabled(data_dir: Path, enabled: bool) -> None:
    _write_settings(data_dir, {"ask": enabled})
