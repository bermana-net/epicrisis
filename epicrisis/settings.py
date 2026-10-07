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
import re
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

# Asked of a reader or a writer below in place of an archive's id: the answer this instance gives,
# which every archive that has not been answered about separately runs by.
#
# It is the default of `in_archive` because the three-argument call has always meant exactly this
# — "does this instance run this rule" — and goes on meaning it. That is a real answer and the
# page has to be able to show it and change it: it is what a new archive inherits, and it is where
# the two rules this instance's owner switched off by hand already stand. Naming an archive asks
# the other question. The first entry's bullet about doors with no default is about a door into
# **an archive**, which answers about somebody; this one answers about everybody, and a caller
# that forgets gets the widest answer rather than a stranger's.
#
# A word of this program's own and not an empty string, so that a line of the journal and a field
# of this file can hold it without reading as "nothing". No archive id can collide with it: ids
# are eight hexadecimal characters.
THE_WHOLE_INSTANCE = "the whole instance"
# Where a rule's per-archive answers sit inside its entry, beside the instance's own `on` and
# `settings`. One file, beside the instance, keyed by the random id of an archive.
#
# **Why beside the instance and not inside each archive's folder**, which is the first entry's
# usual answer and is not this one. That bullet is about anything holding a string printed on
# somebody's document: a file one archive cannot open is a file it cannot leak. What is held here
# is a rule's id — the name of a file in `epicrisis/rules/shipped` or in this instance's own rules
# folder — an archive's random id, a true or a false, and the numbers a kind ships as thresholds.
# None of those is printed on anybody's form, and every one of them is already in this file today:
# the first entry's own test is "does it name a person, or does it name a form?", and a check for
# whether a column that should hold a clinic holds a person's name instead is a question about how
# forms print things, which is the side that is shared on purpose.
#
# And one positive reason, which is `keepers.py`'s, written out there for the same shape: "which
# archives have this rule off" must not be a question that takes one reading per archive, because
# a half that would not read would **shorten** the answer rather than refuse it — a rule would
# come back on in an archive whose folder was unreadable, silently. One file, one lock, one write
# per change, the version before it kept beside it, and a reader that raises rather than answering
# "empty" (§8). The settings page draws every rule with the instance's answer and this archive's
# side by side, and there is no atomic read across two files.
ARCHIVES = "archives"

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
# `public_host` is deliberately not on that list. It is not a secret — the secret is the path, and
# this name is one a tunnel answers on publicly — but the journal is the one file this project
# says may be shown to anybody, and an address somebody can knock on is not a thing to hand out
# for nothing. The journal says the setting changed and not what to, which is the same shape the
# README already keeps: it writes the name as `<name.ts.net>` and this repository holds the real
# one nowhere.
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
        said += _one_rule_changed(rule_id, was, became)
        # And the same two sentences about each archive answered separately, with the archive
        # named the way "the archive shown was switched" already names one: the random id, which
        # is random exactly so that a line of this file names nobody.
        before, after = was.get(ARCHIVES) or {}, became.get(ARCHIVES) or {}
        for source_id in sorted(before | after):
            if source_id in before and source_id not in after:
                # Its own answer taken away rather than changed. Said as what it is, because the
                # answer it falls back to is this instance's and that moves: a line claiming the
                # rule was switched to whatever the instance says today would be a line that
                # stops being true the next time somebody changes the instance's switch.
                said.append({"event": "an archive stopped answering a rule for itself",
                             "rule": rule_id, "archive": source_id})  # fmt: skip
                continue
            said += [{**line, "archive": source_id} for line in _one_rule_changed(
                rule_id, _as_kept(before.get(source_id)), _as_kept(after.get(source_id)))]  # fmt: skip
    return said


def _one_rule_changed(rule_id: str, was: dict, became: dict) -> list[dict]:
    """The lines for one rule's switch and thresholds, read twice: for the instance and per archive.

    One function because they are one sentence asked of two scopes, and the only difference is the
    `archive` the caller puts on the line. Written out twice, the per-archive half would be the
    place where "a rule was switched off" came to be spelled a second way.
    """
    said = []
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


def _as_one_archive_reads(kept: dict, step: str, in_archive: str) -> dict:
    """What one step reads **for one archive**: the instance's answers with that archive's on top.

    The answer a step is built from is per archive — one check is useful on two archives and noise
    on the third, and so is a threshold — but what was written down as "the settings this step was
    built from" was the whole `rules` table, every archive's answers in one lump. So a threshold
    typed for one archive of 23 documents put the badge "this index is older than the files it is
    built from" over all three, and two of the three were checked and rebuilt for nothing.
    Measured: 0 badges before the change, 3 after, on archives of 43, 72 and 23 documents.

    Each archive's own answers are lifted in and the `archives` table dropped, so this holds
    nothing about anybody else: that is what makes two archives' notes able to differ. An
    instance-wide change still moves every archive that has not overridden it, because what is
    lifted in here is the instance's answer wherever the archive has none of its own.
    """
    read = {}
    for name, value in _read_by(kept, step).items():
        if name != "rules" or not isinstance(value, dict):
            read[name] = value
            continue
        rules = {}
        for rule_id, answer in value.items():
            answer = {"on": answer} if isinstance(answer, bool) else dict(answer or {})
            # The table of other archives' answers comes out in every case, the instance's view
            # included: what the instance answers does not change when one archive overrides it,
            # and a view that carried the table would say it did — for every archive at once,
            # which is the false alarm this is about.
            theirs = answer.pop(ARCHIVES, None) or {}
            its_own = theirs.get(in_archive) if in_archive != THE_WHOLE_INSTANCE else None
            effective = {**answer, **(its_own if isinstance(its_own, dict) else {})}
            # A rule with nothing left after that is a rule this reader was never answered
            # about, and it must read as absent rather than as an empty answer. Otherwise the
            # first answer stored for **another** archive puts an empty entry in every archive's
            # view, which is a change, which is the false alarm this is all about.
            if effective:
                rules[rule_id] = effective
        if rules:
            read[name] = rules
    return read


def _the_archives_named_in(kept: dict, step: str) -> set[str]:
    """Every archive this file holds an answer of its own about, for the step named.

    Only these can differ from the instance, so only these need a note of their own — an archive
    nobody has answered about separately reads the instance's answers and the instance's moment.
    """
    named: set[str] = set()
    for name, value in _read_by(kept, step).items():
        if name != "rules" or not isinstance(value, dict):
            continue
        for answer in value.values():
            if isinstance(answer, dict):
                named |= set((answer.get(ARCHIVES) or {}).keys())
    return named


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
        kept = _note_in(before, step) or {}
        noted[step] = _one_note(before, after, step, THE_WHOLE_INSTANCE, kept)
        # And one note per archive that has an answer of its own, because what a step is built
        # from is per archive: a threshold typed for one archive aged all three without this.
        # Both sides' archives, so that an answer taken away moves the note it belonged to.
        its_own = kept.get(ARCHIVES) if isinstance(kept.get(ARCHIVES), dict) else {}
        for archive in _the_archives_named_in(before, step) | _the_archives_named_in(after, step):
            note = _one_note(before, after, step, archive, its_own.get(archive) or {})
            noted[step].setdefault(ARCHIVES, {})[archive] = note
    return noted


def _one_note(before: dict, after: dict, step: str, in_archive: str, kept: dict) -> dict:
    """What one reader of this file reads now, and when that last changed for them."""
    was = _as_one_archive_reads(before, step, in_archive)
    now = _as_one_archive_reads(after, step, in_archive)
    stood = kept.get("read", was)
    changed = was != now or stood != was
    return {"read": now, "changed_at": time.time() if changed else _moment(kept.get("changed_at"))}


def changed_for(data_dir: Path, step: str, *, in_archive: str = THE_WHOLE_INSTANCE) -> float:
    """When a choice this step is built from last changed here, as a moment to compare against.

    Zero where none ever has — a new instance, or one whose settings have never named anything this
    step reads. Nothing built is behind a choice that was never made.

    `in_archive` because the choice is per archive. Asked about one archive, the answer is that
    archive's own note where it has one, and the instance's where it has not — and never the
    moment somebody answered something about **another** archive, which is what this said before:
    one threshold typed for one archive of 23 documents put "this index is older than the files it
    is built from" over all three.
    """
    stored = _settings(data_dir)
    kept = _note_in(stored, step)
    if kept is None:
        return 0.0
    if in_archive != THE_WHOLE_INSTANCE:
        its_own = (kept.get(ARCHIVES) or {}).get(in_archive)
        if isinstance(its_own, dict):
            kept = its_own
    if kept.get("read") != _as_one_archive_reads(stored, step, in_archive):
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


def answered_about(data_dir: Path, rule_id: str, in_archive: str) -> dict:
    """What one archive stored about one rule **of its own**, which is usually nothing.

    Empty where this archive has never been answered about separately, and that is the answer the
    readers below want: an empty dict falls through to what this instance answers, and a dict with
    an "on" in it is an archive whose owner said something different about one of their three
    boxes of forms. Asked by the page as well, so that a switch can say which of the two it is
    showing rather than drawing both the same.

    THE_WHOLE_INSTANCE is not an archive and has nothing of its own: the instance's own answer is
    `_kept_for`, one function up, and answering it here too would be the one decision in two
    places.
    """
    if in_archive == THE_WHOLE_INSTANCE or not in_archive:
        return {}
    kept = (_kept_for(data_dir, rule_id).get(ARCHIVES) or {}).get(in_archive)
    return kept if isinstance(kept, dict) else {}


def rule_on(data_dir: Path, rule, *, in_archive: str = THE_WHOLE_INSTANCE) -> bool:
    """Whether this rule runs — in one archive, or over this instance. Its own default otherwise.

    One switch per rule, kept by the rule's id, so that a rule added later arrives with its own
    answer and an answer stored for a rule that has since been deleted simply stops mattering.
    And one switch per rule **per archive**, over the top of it, because one check is useful on
    two archives and noise on the third. Measured on the three archives on this machine,
    `institution_looks_like_a_name` finds 24 of 439 documents, 4 of 40 and 255 of 257: the last
    archive is one hospital's export, whose forms print the doctor's name where others print the
    clinic's, and the one switch that would quieten those 255 took the 24 and the 4 with it.

    Three layers, narrowest first, each falling through to the next where it says nothing: what
    this archive was answered, what this instance was answered, what the rule's own file ships.

    Above all three: a check that reports a hole in the archive has no switch, and this is the one
    place that is read — every caller asks here, so an answer stored for such a rule by a hand or
    by an older version of this program cannot put it out. See `Kind.stays_on`.
    """
    if rule.stays_on:
        return True
    its_own = answered_about(data_dir, rule.id, in_archive)
    if "on" in its_own:
        return bool(its_own["on"])
    kept = _kept_for(data_dir, rule.id)
    if "on" in kept:
        return bool(kept["on"])
    # A check that has just become a rule keeps the answer this archive gave its old switch.
    if rule.was_called and rule.was_called in _settings(data_dir):
        return bool(_settings(data_dir)[rule.was_called])
    return rule.on_by_default


def rule_settings(data_dir: Path, rule, *, in_archive: str = THE_WHOLE_INSTANCE) -> dict:
    """The rule's own settings, with what this instance changed and then what this archive did.

    A name the rule does not have is dropped rather than carried: a setting stored under a name
    the kind has since renamed would otherwise travel for ever, doing nothing, looking like a
    thing that works.

    Per archive for the same reason as the switch, and decided with it rather than after it: a
    threshold is how far from the others a number has to be before it is worth looking at, and
    that is a fact about how one archive's forms print, exactly as the switch is. Half of it per
    archive and half of it instance-wide would be the same mismatch this was written to close —
    the count beside a switch was already of the open archive while the switch was not.
    """
    changed = dict(_kept_for(data_dir, rule.id).get("settings") or {})
    changed |= answered_about(data_dir, rule.id, in_archive).get("settings") or {}
    return {**rule.settings, **{name: value for name, value in changed.items() if name in rule.settings}}


def as_chosen(data_dir: Path, rule, *, in_archive: str = THE_WHOLE_INSTANCE):
    """The rule as it is run here: its file, with this instance's settings and this archive's."""
    return replace(rule, settings=rule_settings(data_dir, rule, in_archive=in_archive))


@while_editing
def set_rule_on(data_dir: Path, rule_id: str, enabled: bool, *,
                in_archive: str = THE_WHOLE_INSTANCE) -> None:  # fmt: skip
    """Answer the switch — for one archive, or for the instance, which is every other archive.

    Refused for a rule that has no switch, rather than written and then ignored by the reader
    above: a stored answer nothing reads is the kind of thing somebody finds in a file, believes,
    and spends an afternoon on.
    """
    from epicrisis.rules import load as load_rules

    rule = load_rules(data_dir).get(rule_id)
    if rule is not None and rule.stays_on:
        raise ValueError(f"“{rule.name}” reports a hole in the archive and has no switch: what it "
                         "finds is this program saying it did not finish reading a page, which is "
                         "not something to call noise. Its thresholds are yours to set.")  # fmt: skip
    kept = _settings(data_dir).get("rules", {})
    was = _as_kept(kept.get(rule_id))
    if in_archive == THE_WHOLE_INSTANCE:
        now = {**was, "on": enabled}
    else:
        its_own = dict(was.get(ARCHIVES) or {})
        its_own[in_archive] = {**(its_own.get(in_archive) or {}), "on": enabled}
        now = {**was, ARCHIVES: its_own}
    _write_settings(data_dir, {"rules": {**kept, rule_id: now}})


@while_editing
def let_the_instance_answer(data_dir: Path, rule_id: str, in_archive: str) -> None:
    """Take one archive's own answer about one rule away, so the instance's stands again.

    The other half of answering per archive, and the seventh entry's half: a switch a person can
    set for one archive and never put back is a dead end, and an answer of its own that looks
    identical to the instance's is a thing nobody can tell they still have. Asked for by name
    rather than by storing a third value for "the same as the instance", because what the instance
    answers moves and an archive that said "the same as it was in October" would be saying it
    about a number that has since changed.
    """
    kept = _settings(data_dir).get("rules", {})
    was = _as_kept(kept.get(rule_id))
    its_own = {name: entry for name, entry in (was.get(ARCHIVES) or {}).items() if name != in_archive}
    now = {**was, ARCHIVES: its_own} if its_own else {name: value for name, value in was.items()
                                                      if name != ARCHIVES}  # fmt: skip
    _write_settings(data_dir, {"rules": {**kept, rule_id: now}})


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
            read = _as_shipped(default, values[name])
        except (TypeError, ValueError):
            cannot[name] = IN_WORDS.get(type(default), "a value of the shape this rule ships")
            continue
        # The shape as well as the type, asked of the kind so that the file and this page refuse
        # the same numbers. 0 characters, a share of 0, a count of -5: each is a number the type
        # accepts and the check can never act on, and each was stored in silence.
        refuses = rule.check.refuses(name, read)
        if refuses:
            cannot[name] = refuses
    return cannot


@while_editing
def set_rule_settings(data_dir: Path, rule, values: dict, *,
                      in_archive: str = THE_WHOLE_INSTANCE) -> None:  # fmt: skip
    """What was chosen for one rule here, where it differs from what already stood.

    A value equal to what already stood is not stored: typing the number back in is how a person
    undoes a change, and it should leave nothing behind saying they ever made one. What "already
    stood" is depends on which question is being answered — for the instance it is the rule's own
    file, and for one archive it is what the instance answers, so that typing the instance's
    number into an archive's field puts that archive back under the instance rather than pinning
    it to today's value for ever.

    Every threshold named in values is written or none of them is. A caller with several in hand
    asks what_a_rule_cannot_use first, so that the good ones are not lost with the bad one.
    """
    standing = (rule.settings if in_archive == THE_WHOLE_INSTANCE
                else rule_settings(data_dir, rule))  # fmt: skip
    wanted = {}
    for name, default in rule.settings.items():
        if name not in values:
            continue
        try:
            wanted[name] = _as_shipped(default, values[name])
        except (TypeError, ValueError):
            raise ValueError(f"{name} should be {IN_WORDS.get(type(default), 'what this rule ships')}") from None
        # The last place it could still get in: a caller that did not ask
        # `what_a_rule_cannot_use` first, which is every caller but the settings page.
        refuses = rule.check.refuses(name, wanted[name])
        if refuses:
            raise ValueError(f"{name} wants {refuses}")
        if wanted[name] == standing[name]:
            del wanted[name]
    kept = _settings(data_dir).get("rules", {})
    was = _as_kept(kept.get(rule.id))
    if in_archive == THE_WHOLE_INSTANCE:
        now = {**was, "settings": wanted}
    else:
        its_own = dict(was.get(ARCHIVES) or {})
        its_own[in_archive] = {**(its_own.get(in_archive) or {}), "settings": wanted}
        now = {**was, ARCHIVES: its_own}
    _write_settings(data_dir, {"rules": {**kept, rule.id: now}})


def rules_on(data_dir: Path, loaded, step: str, *, in_archive: str = THE_WHOLE_INSTANCE) -> list:
    """The rules one step runs: its own, as they were answered here, minus the ones turned off.

    `in_archive` is how a step that is about one archive asks, and every one of them has the
    archive in hand already — `validate` has the output folder, the page of findings and the page
    of charts have the archive the route declared, a tool call has the one `showing()` read. The
    default answers about the instance, which is what the settings page shows as the answer every
    archive inherits.

    **One caller still asks the instance's question about an archive**, and it is named here
    rather than left to be found: `cli.py`'s `suspects`, which has `showing` in hand two lines
    above. `tests/test_rules.py` holds that list and fails when it grows, so the next caller
    added is caught by having been added.
    """
    return [as_chosen(data_dir, rule, in_archive=in_archive)
            for rule in loaded.at(step) if rule_on(data_dir, rule, in_archive=in_archive)]  # fmt: skip


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


#: What a name the tunnel answers on may be made of. A host name and nothing else: no scheme, no
#: path, no port, no space. Refused rather than tidied, because every one of those is somebody
#: pasting a different thing than was asked for — a whole URL out of a browser's address bar is
#: the common one — and a link composed from it would be a link that does not work, handed over
#: as though it did.
A_HOST_NAME = re.compile(r"^(?=.{1,253}$)[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
                         r"(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$")  # fmt: skip


def the_name_the_tunnel_answers_on(data_dir: Path) -> str:
    """The public name of this instance, or an empty string where nobody has said one.

    Until now this lived only on a command line — `mcp --http --public-host` — which meant the
    instance did not know its own address and no page could write a link that works. It is kept
    here rather than worked out from the request, because a request through a tunnel carries
    whatever the tunnel was told to send, and a link handed to somebody else has to be the name
    its owner meant.

    Empty is an answer and not a missing value: a page with no name to use says so instead of
    printing half an address. §7.
    """
    said = _settings(data_dir).get("public_host", "")
    return said if isinstance(said, str) and A_HOST_NAME.match(said) else ""


@while_editing
def set_the_name_the_tunnel_answers_on(data_dir: Path, name: str) -> None:
    """Write it down, or clear it with an empty string."""
    said = (name or "").strip().rstrip(".")
    if said and not A_HOST_NAME.match(said):
        raise ValueError("a name the tunnel answers on is a host name: no https://, no path, no port")
    _write_settings(data_dir, {"public_host": said})


def ask_enabled(data_dir: Path) -> bool:
    return bool(_settings(data_dir).get("ask"))


@while_editing
def set_ask_enabled(data_dir: Path, enabled: bool) -> None:
    _write_settings(data_dir, {"ask": enabled})
