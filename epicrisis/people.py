"""One doctor, one laboratory, written several ways — joined by a person, never by a program.

The same question as the printed names of one test, and the same answer: a program may notice that
two names look like one, and a person decides. The reason is sharper here than for a test name.
Joining "Кривопишин В.Г" and "Уролог Кривопишин В.Г" is a claim about the identity of a human being, and
two doctors of one surname and one initial work in two clinics of every city.

What is stored is what a person settled: the names that are one, and which of them to show. Nothing
is joined until they say so, and a join is undone by the same hand that made it. The archive's own
documents are never touched — this is a view over them, like the indicators.

The label shown for a group is the commonest of its spellings, because a speciality in front of a
name is not part of the name and the forms print it the other way more often. A person can keep
whichever they like: it is their archive and their doctor.
"""

import functools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from epicrisis import journal, layout, sources
from epicrisis.printed_values import fold, in_name_order
from epicrisis.runs import Busy, copy_whole, one_at_a_time, write_whole
from epicrisis.state import Unreadable, where

FILE_NAME = layout.PEOPLE
KINDS = ("doctor", "institution")
#: The shorter of two names must carry at least two words of its own before the pair is proposed:
#: a hospital's own forms print its initials in the address at their foot, and one word is not a
#: name. What else has to hold is not the same for the two kinds, and worth_joining says why.
LEAST_WORDS = 2


class NotAJoin(ValueError):
    """What was asked for is not a join of two spellings, and nothing was written.

    Raised and not returned, and this is the finding that bought it. join() answered a `kind` it
    did not know by returning the file unchanged, in silence — so a call that left the argument
    out wrote nothing at all, and the test guarding the first line of the constitution asserted
    that a label which had never been created was not on somebody else's page. It passed, and it
    could not have failed.

    A thing a person can do by hand and a thing no caller may do are told apart here. An unknown
    kind is a mistake in the program and raises ValueError plainly. Unticking all but one spelling
    is a person pressing a button, so it is this: refused, with the sentence the page shows them
    and the one that says what puts it right. §7 — the program says out loud everything it does,
    including the times it did nothing.
    """

    def __init__(self, said: str, mend: str = ""):
        self.said, self.mend = said, mend
        super().__init__(" ".join(part for part in (said, mend) if part))


@dataclass
class Group:
    """Printed names that are one doctor, or one institution — settled, only offered, or refused.

    Three states of one claim and not three kinds of thing, which is why they live in one file: a
    proposal becomes a group the moment somebody presses the button and nothing else about it
    changes, and it becomes a refusal the moment they press the other one. What must never blur is
    which of the three is being read, and that is why every reader here goes through `settled`,
    `waiting` or `refused` rather than over the whole list.

    The third state was added late. A refusal used to be forgotten rather than kept, on the
    reasoning that keeping one would need a second file and a second question — and the file had
    since moved inside the archive and was already holding groups nobody had settled, so it needed
    neither. What forgetting cost is written at decline().
    """

    kind: str
    label: str
    names: list[str] = field(default_factory=list)
    #: False while this is only a proposal, and false for a refusal. A proposal answers nothing
    #: and joins nothing: it waits.
    settled: bool = True
    #: Somebody has looked at these spellings and said they are not one. Never settled, never
    #: offered, and taken back by hand.
    refused: bool = False
    #: Why a model thought so, in its own words, for a person to weigh. Empty for the pairs the
    #: word count offers and for anything a person settled themselves — there the reason is visible
    #: in the names.
    why: str = ""

    def as_dict(self) -> dict:
        stored = {"kind": self.kind, "label": self.label, "names": sorted(self.names, key=in_name_order)}
        if not self.settled:
            stored["settled"] = False
        if self.refused:
            stored["refused"] = True
        if self.why:
            stored["why"] = self.why
        return stored


def path(data_dir: Path, source_id: str) -> Path:
    """Inside the archive it is about, never beside the instance.

    It lived beside the instance for one day, and on that day the page of doctors and clinics
    showed one person the doctors of another, and a label chosen in one archive renamed a clinic on
    thirty-four documents of somebody else. The page had simply not asked whose the file was, and
    nothing had made it ask. A file one archive cannot open is a file it cannot leak, which is a
    wall; a filter written at each place that reads it is the thing that was forgotten.

    source_id has no default on purpose, here and in every function below. A caller that does not
    know which archive it is answering about must fail, not answer about somebody.
    """
    return sources.source_output_dir(Path(data_dir), source_id) / FILE_NAME


def unreadable(data_dir: Path, source_id: str) -> bool:
    """A file of settled groups that is there and cannot be read. Not the same as none yet."""
    try:
        json.loads(path(data_dir, source_id).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except (ValueError, OSError):
        return True
    return False


def a_printed_name(name: str) -> str:
    """One name, carrying the line break the document prints and never a carriage return.

    A name printed across two lines of a form is one name with a line feed inside it, and this
    archive holds one: a clinic whose heading runs over two lines. It cannot make the trip through
    the page and back. The url-encoded form serialiser is required to rewrite every lone line feed
    as a carriage return and a line feed, every browser does it, and none has a setting for it —
    so the name goes out as the document prints it and comes back one character longer than any
    name in the archive.

    What that cost, on this archive: a press on Join stored the browser's spelling, which stands on
    no document, so the join took effect over one of the two names and not the other. The page then
    counted the stored spelling and the printed one as two spellings of one clinic and offered them
    again — and the press was refused, every time, with "one name on its own is not a join", for
    having ticked two. Neither sentence was wrong about what it saw, and together they were a
    closed circle a person could not get out of.

    Folding the carriage return out is the exact inverse of what the browser is required to do, and
    it loses nothing: a carriage return is a file's line ending, not anything a form prints. Of the
    182 institutions and 98 doctors read across the three archives here, none carries one.
    """
    return name.replace("\r\n", "\n").replace("\r", "\n")


def load(data_dir: Path, source_id: str) -> list[Group]:
    """Every group, settled and proposed. Raises where the file is there and cannot be read.

    It used to answer an empty list instead, on the reasoning that what this file holds is a view
    and the archive is whole without it. That reasoning is wrong, and it was wrong in the way that
    costs a person their afternoon: every writer here is load, change, save, so one press of Join
    over a torn file wrote that emptiness back and took every group they had settled with it.
    Measured on a torn file: two groups before, one after, and no copy kept.

    indicators.json — the same kind of work, a person's own, one group at a time — has refused
    this since the day it happened to it. This module was written months later and did not inherit
    the lesson, which is the whole argument for the two of them asking one place.
    """
    file = path(data_dir, source_id)
    if not file.exists():
        return []
    try:
        stored = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as torn:
        raise Unreadable(
            where(file),
            "Nothing was changed, and every doctor and institution you joined is still in that file.",
            # The version before the last save, and the advice has to say that there may be none:
            # save() keeps it only where a file was already there, so the very first write of this
            # file leaves no .previous, and a person was being sent to copy back something that
            # had never existed. What to do instead costs them their joins, so it is said plainly
            # rather than implied.
            f"Repair it, or copy back {FILE_NAME}.previous beside it, written every time this file "
            f"is saved. If there is no .previous, this was its first save: delete the file and this "
            f"archive answers exactly as it did before any name was joined, and the joins are made "
            f"again by hand.",
        ) from torn
    # A refusal is never settled, whatever the file says. Both fields are written by this program
    # and read back by it, so the two could only disagree in a file somebody had edited by hand —
    # and of the two readings, "these are one person, nobody checked" is the one that must not be
    # the answer. Refused wins.
    #
    # The spellings of a group are shown in the order they are held in, so they are held in the
    # order a person reads a list in — here as well as in as_dict, because a file written before
    # this was written holds them in the order the code points happened to put them, and the page
    # showing it is the page where somebody is looking for one of the spellings.
    # Read back as the documents print them. A file written before a_printed_name was written
    # holds whatever the browser sent, and a stored spelling that stands on no document joins
    # nothing: it is read here rather than left, so the press that was made takes effect, and the
    # file itself is mended by the next save. Nobody's work is lost doing it — the spelling they
    # ticked is the one that comes back.
    return [Group(kind=one.get("kind", "doctor"), label=a_printed_name(one.get("label", "")),
                  names=sorted(dict.fromkeys(a_printed_name(name) for name in one.get("names", [])),
                               key=in_name_order),
                  settled=bool(one.get("settled", True)) and not one.get("refused"),
                  refused=bool(one.get("refused", False)), why=str(one.get("why", "")))
            for one in stored if one.get("names")]  # fmt: skip


def settled(groups: list[Group], kind: str | None = None) -> list[Group]:
    """The groups a person has settled, and only those.

    Every question the archive is asked about a name goes through here. A proposal is a sentence a
    model wrote; until somebody agrees with it, the cut of the archive by doctor, the cut by
    institution and the timeline must answer exactly as they did before it was written.
    """
    return [one for one in groups if one.settled and (kind is None or one.kind == kind)]


def waiting(groups: list[Group], kind: str | None = None) -> list[Group]:
    """The proposals nobody has decided yet. A refusal is decided, so it is not one of these."""
    return [one for one in groups
            if not one.settled and not one.refused and (kind is None or one.kind == kind)]  # fmt: skip


def refused(groups: list[Group], kind: str | None = None) -> list[Group]:
    """The sets of spellings somebody has said are not one, so that nothing offers them again.

    Read by the page twice: once to leave those families out of what it offers, and once to show
    them under a heading of their own with a way to take the refusal back. A refusal that could
    not be taken back would be the dead end this was written to close, facing the other way.
    """
    return [one for one in groups if one.refused and (kind is None or one.kind == kind)]


def says_no_to(groups: list[Group], kind: str, names: list[str]) -> bool:
    """Whether this exact set of spellings has been refused.

    Exactly this set, and not any set inside it or around it. A smaller family, a pair out of it,
    or the same names with a sixth spelling printed beside them next year are different questions
    about different names, and a person who said no to five spellings has not answered them.
    """
    wanted = frozenset(names)
    return any(frozenset(one.names) == wanted for one in refused(groups, kind))


def already_one(groups: list[Group], kind: str, names: list[str]) -> bool:
    """Whether these names are, between them, one group this person has already settled.

    The question to ask before offering a family, and the page used to ask a different one: whether
    every name of the family stood *somewhere* among the settled groups. The two are the same
    question only while the names are in one group. The moment two of them are the labels of two
    groups, the old question answered "settled" about a pair nobody has ever been asked, and the
    family was dropped in silence — so two groups standing for one doctor stayed apart for ever,
    with nothing on the page even asking. join() has absorbed a settled group holding one of the
    names since the day it was written; what was missing was the offering.
    """
    wanted = set(names)
    return any(wanted <= set(one.names) for one in settled(groups, kind))


def standing_for(groups: list[Group], kind: str, names: list[str]) -> list[Group]:
    """Which of these names are the label of a settled group, and what each group holds.

    What a press over a family would really join, so that the page can say it: a family of two
    names where both are labels is two groups and every spelling under them, which is six or seven
    spellings as often as two. A heading that counted the names and called them spellings was a
    count disagreeing with what the button did.

    Matched on the label alone, because the label is the only name of a group this page ever draws
    — the decision, and why, is written out where the names are gathered: `who.who_view`.
    """
    wanted = set(names)
    return [one for one in settled(groups, kind) if one.label in wanted]


def save(data_dir: Path, source_id: str, groups: list[Group]) -> None:
    """Write the whole file, keeping the version it replaces beside it.

    Asked again here rather than trusted to load(): a caller that caught Unreadable somewhere in
    the middle of its work must not reach the write with a list built from nothing.
    """
    file = path(data_dir, source_id)
    if unreadable(data_dir, source_id):
        raise Unreadable(
            where(file),
            "Nothing was changed, and every doctor and institution you joined is still in that file.",
            # The version before the last save, and the advice has to say that there may be none:
            # save() keeps it only where a file was already there, so the very first write of this
            # file leaves no .previous, and a person was being sent to copy back something that
            # had never existed. What to do instead costs them their joins, so it is said plainly
            # rather than implied.
            f"Repair it, or copy back {FILE_NAME}.previous beside it, written every time this file "
            f"is saved. If there is no .previous, this was its first save: delete the file and this "
            f"archive answers exactly as it did before any name was joined, and the joins are made "
            f"again by hand.",
        )
    if file.exists():
        copy_whole(file, file.with_name(file.name + ".previous"))
    write_whole(file, json.dumps([one.as_dict() for one in groups], ensure_ascii=False, indent=2))


def editing(data_dir: Path, source_id: str):
    """One writer at a time. The page and a command both read, change and write this whole file,
    and without this the second rename silently undoes the first.

    One lock per archive, beside the file it guards: two people's archives are two files and two
    questions, and a person joining names in one must not wait on a command reading the other.
    """
    return one_at_a_time(path(data_dir, source_id).with_name("people.lock"),
                         "Editing the doctors and institutions")  # fmt: skip


def while_editing(change):
    """Hold the archive's lock for the whole of a change, not only for the write at the end.

    This existed, and nothing in the program called it. Every writer below went straight to save,
    and the window between its load and its save was a window in which another writer's whole
    file disappeared: two threads joining names in one archive, with the read slowed to a quarter
    of a second, left one group in the file, the other in people.json.previous, and no error
    anywhere. The twin module — indicators.py, the same read-modify-write over a person's own
    work — has wrapped all seven of its writers in its own lock since the day it happened to it.

    The loser of the race is told, which is the other half of this: one_at_a_time refuses with
    Busy rather than queueing, the dashboard answers that as a page naming the lock, and a command
    prints it. Nothing is written by two hands and nothing is lost in silence.
    """

    @functools.wraps(change)
    def guarded(data_dir: Path, source_id: str, *args, **kwargs):
        with editing(data_dir, source_id):
            return change(data_dir, source_id, *args, **kwargs)

    return guarded


def label_of(groups: list[Group], kind: str, name: str) -> str:
    """What to show for a printed name: the group's label where it is in one, else the name."""
    for group in settled(groups):
        if group.kind == kind and name in group.names:
            return group.label
    return name


def names_under(groups: list[Group], kind: str, label: str) -> list[str]:
    """Every printed spelling a label stands for, so a question about one asks about all of them."""
    for group in settled(groups):
        if group.kind == kind and group.label == label:
            return sorted(group.names, key=in_name_order)
    return [label]


def _settled(data_dir: Path, source_id: str, event: str, kind: str, names: int) -> None:
    """Write down that somebody answered one of these questions, and how many names it was about.

    Which doctors and which institutions a person said were one is in people.json, and that file
    is their own work. What is not anywhere is *that they answered at all, and when*: the file
    holds the answer and overwrites the one before it, so a group joined on Tuesday and split on
    Wednesday leaves a file that says neither happened. These are claims about the identity of
    human beings, made by hand, one at a time, and nothing can rebuild them.

    **The count and never the names.** A spelling here is the name of a doctor or a laboratory
    printed on somebody's documents, and the archive id beside it is random precisely so that a
    line of this journal names nobody. Writing the names would make this file a list of the
    doctors one person has seen, which is a second copy of the part of the archive that matters
    most. `kind` is doctor or institution — a word of this program's own, not of any form.
    """
    journal.record(data_dir, {"event": event, "archive": source_id, "about": kind, "names": names})


@while_editing
def join(data_dir: Path, source_id: str, kind: str, names: list[str], label: str | None = None) -> list[Group]:
    """Say that these printed names are one. Settled groups already holding any of them come in too.

    The label is the one asked for, or the longest-standing of the labels already chosen, or the
    first name given — the page hands over the commonest spelling, which is what it means.

    Only settled groups are absorbed. A proposal that holds one of these names is not: joining it
    in would quietly settle spellings a model guessed at and nobody looked at, which is the one
    thing this whole module exists to prevent. Such a proposal is dropped instead — its question
    has been answered by hand, and if it was right about a third spelling, the next run offers that
    spelling again, by itself.

    A refusal holding one of these names goes the same way, and for the same reason read backwards:
    the person is joining names they once said were not one, which is them changing their mind,
    and a remembered "no" that outlived the "yes" after it would be the file arguing with its
    owner.

    Nothing it does not understand is answered in silence. See NotAJoin: one spelling is not a
    join, a label that is none of the spellings being joined is not a label, and a kind that is
    neither of the two is a mistake in the caller.
    """
    if kind not in KINDS:
        raise ValueError(f"a join is about a doctor or an institution, and not about {kind!r}")
    given = [name for name in names if name and name.strip()]
    if len(set(given)) < 2:
        raise NotAJoin("One name on its own is not a join: there has to be a second spelling for "
                       "it to be the same as.",
                       "Tick at least two of the spellings and press the button again.")  # fmt: skip
    groups = load(data_dir, source_id)
    wanted, kept = set(given), []
    for group in groups:
        touches = group.kind == kind and bool(wanted & set(group.names))
        if touches and group.settled:
            wanted |= set(group.names)
            label = label or group.label
        elif not touches:
            kept.append(group)
    if label and label not in wanted:
        # The spelling to keep has to be one of the spellings being joined. The page offers the
        # whole family in the picker and the family in tick boxes, so unticking the one that is
        # picked asks for a group labelled with a name that is not in it — and a label standing
        # over names it is not one of is how a label chosen in one place renames something
        # somewhere else. Refused whole rather than quietly relabelled: which of five spellings
        # is the name is the one question here that only the person reading them can answer.
        raise NotAJoin("The spelling to keep is not one of the spellings being joined.",
                       "Tick the spelling you chose to keep, or choose one of the ticked ones.")
    kept.append(Group(kind=kind, label=label or given[0], names=sorted(wanted, key=in_name_order)))
    save(data_dir, source_id, kept)
    _settled(data_dir, source_id, "names were joined into one", kind, len(wanted))
    return kept


@while_editing
def split(data_dir: Path, source_id: str, kind: str, label: str) -> list[Group]:
    """Undo a join. The names go back to standing for themselves, exactly as the forms print them."""
    before = load(data_dir, source_id)
    groups = [one for one in before if not (one.kind == kind and one.label == label)]
    save(data_dir, source_id, groups)
    undone = [one for one in before if one.kind == kind and one.label == label]
    if undone:
        _settled(data_dir, source_id, "a join of names was undone", kind,
                 sum(len(one.names) for one in undone))  # fmt: skip
    return groups


@while_editing
def propose(data_dir: Path, source_id: str, kind: str, names: list[str], label: str | None = None,
            why: str = "") -> list[Group]:  # fmt: skip
    """Write down that something thinks these names are one, without joining them.

    Nothing is proposed about a name a person has already settled: they have answered that
    question, and a page that asks it again teaches them to click past it. Nor is the same set of
    names proposed twice, and nor is a set somebody has said no to — that is an answer as much as
    a join is, and paying a model to ask it again is paying for the same page twice.

    A kind this does not know raises, as it does in join: no caller can mean one. Fewer than two
    names does not — a model asked which of forty spellings are one answers with groups of one as
    often as not, and a group of one is simply not a group. Nothing is refused to anybody there:
    it is this program reading an answer about forms, with no person waiting on a sentence.
    """
    if kind not in KINDS:
        raise ValueError(f"a proposal is about a doctor or an institution, and not about {kind!r}")
    if len(names) < 2:
        return load(data_dir, source_id)
    groups = load(data_dir, source_id)
    already = {name for one in settled(groups, kind) for name in one.names}
    wanted = sorted({name for name in names if name not in already})
    if (len(wanted) < 2 or says_no_to(groups, kind, wanted)
            or any(sorted(one.names) == wanted for one in waiting(groups, kind))):  # fmt: skip
        return groups
    groups.append(Group(kind=kind, label=label or wanted[0], names=wanted, settled=False, why=why))
    save(data_dir, source_id, groups)
    return groups


@while_editing
def decline(data_dir: Path, source_id: str, kind: str, names: list[str]) -> list[Group]:
    """Say no: these spellings are not one, and nothing offers them again until that is taken back.

    **This docstring said the opposite, and the reason it gave has expired.** It read: a refusal is
    forgotten, not remembered, because remembering one "would need a second file and a second
    question — what a person meant by 'not these two', which is 'not yet' as often as 'never'".
    What changed is the first half of that. The file moved inside the archive it is about, and it
    already holds groups nobody has settled, so a refusal is a third state of a record in a file
    that is already there: no second file, and nothing new to lock or to carry or to leak. The
    second half is answered by standing beside it on the page — "not yet" and "never" are the same
    record while there is an "Ask me again" under it.

    What forgetting cost was a circle the page could not leave. "Separate them" undoes a join, and
    the next draw of the page offers that family again, because the filter that hides a settled
    family has nothing left to hide by. There was no "not these" on a counted family at all. So a
    person who had looked at five spellings and decided they were two laboratories had no way of
    saying so that lasted longer than one page. §7: a dead end with no way out is a defect — and
    so is a way out that leads back to the same door.

    Nothing about the names themselves is remembered beyond the one fact that somebody said no to
    this one set of spellings, and nothing of what the forms print changes. A different set is a
    different question and is still asked: see says_no_to().
    """
    if kind not in KINDS:
        raise ValueError(f"a refusal is about a doctor or an institution, and not about {kind!r}")
    wanted = sorted({name for name in names if name and name.strip()})
    if len(wanted) < 2:
        raise NotAJoin("One spelling on its own is not a group to say no to.",
                       "Nothing on this page asks whether one name is itself.")  # fmt: skip
    before = load(data_dir, source_id)
    if says_no_to(before, kind, wanted):
        return before  # said once already; there is nothing to write and nothing to say twice
    answered = {id(one) for one in waiting(before, kind) if sorted(one.names) == wanted}
    asked = next((one for one in before if id(one) in answered), None)
    groups = [one for one in before if id(one) not in answered]
    # The label and the reason a model gave are kept, because the page shows the refusal and a
    # person reading it a month later is owed the sentence they said no to.
    groups.append(Group(kind=kind, label=asked.label if asked else wanted[0], names=wanted,
                        settled=False, refused=True, why=asked.why if asked else ""))  # fmt: skip
    save(data_dir, source_id, groups)
    _settled(data_dir, source_id, "names were said not to be one", kind, len(wanted))
    return groups


@while_editing
def reconsider(data_dir: Path, source_id: str, kind: str, names: list[str]) -> list[Group]:
    """Take a refusal back, so that these spellings may be offered again.

    The other half of remembering one. A refusal nothing could undo would be the same dead end
    turned round, and a worse one than the first: the spellings stand in the list below exactly as
    the forms print them, and there is nothing down there to join them by.
    """
    if kind not in KINDS:
        raise ValueError(f"a refusal is about a doctor or an institution, and not about {kind!r}")
    wanted = sorted({name for name in names if name and name.strip()})
    before = load(data_dir, source_id)
    if not says_no_to(before, kind, wanted):
        return before
    groups = [one for one in before
              if not (one.refused and one.kind == kind and sorted(one.names) == wanted)]  # fmt: skip
    save(data_dir, source_id, groups)
    _settled(data_dir, source_id, "a refusal about names was taken back", kind, len(wanted))
    return groups


def words_of(name: str) -> set[str]:
    return set(the_words_in(name))


def the_words_in(name: str) -> tuple[str, ...]:
    """The words of a name in the order they are printed, folded, with the punctuation gone.

    An apostrophe is taken out of a name, not split on, and the taking out is the fold's now. This
    file had a translation table of its own for it, and printed_values.fold did not, so the two
    halves of this program disagreed about what an apostrophe is — which is the one shape
    ARCHITECTURE.md exists to prevent. Both measurements that bought the table still hold, and
    they are why it had to be taken out before folding rather than after: "Аб'ва О.П." came out
    as four words against three for "Абьва О.П.", so the two spellings of one surname were never
    offered as one, and "Д'Абва" came out as two words, which is enough to pass LEAST_WORDS — a
    guard that exists so that one word is never offered as a name — and was offered as the same
    place as a building lettered Д.

    A hyphen between two letters still splits, and that is not an oversight. Measured on the three
    archives on this machine: binding it into one word takes seven pairs away and adds none, and
    every one of the seven is a form printing one compound with a hyphen where another form prints
    it with a space — "Лабораторія Абва-Гдеж" against "Лабораторія Абва Гдеж". That is the shape
    the split is for, and it is the common one here.

    What it cost is written down here because it was written down here before it was closed, and
    closing it did not touch this function. A simple surname comes out a strict subset of a double
    one, so "Гдеж І.В." and "Гдеж-Абва І.В." were offered as one name, and they are two people as
    often as they are one marriage — and the same pair was offered for a Spanish double surname,
    which carries no hyphen at all and no rule about hyphens could have reached. Nothing in the
    words tells a speciality welded in front of a surname from a second surname welded behind it.
    So worth_joining stopped asking the question of a doctor's name in a shape where the answer is
    behind the surname: a pair is offered where the name ends the longer string, which a hyphen in
    the middle of it never does. For an institution the subset stays, and there the hyphen split is
    the shape it is for.
    """
    return tuple(word for word in re.split(r"[^\w]+", fold(name)) if word)


def families(kind: str, names: list[str]) -> list[list[str]]:
    """The names that belong together, each family in one list, commonest spelling first.

    `kind` has no default and is passed straight to worth_joining, where it decides which shapes
    are offered at all: a doctor and an institution are not asked the same question. A caller that
    does not know which of the two it is holding must fail rather than take the looser rule.

    The page used to offer the pairs this finds, one row and one button each. On an archive where
    a laboratory writes itself five ways — its own name, its name with the software, the software
    with a version, the version with a point release, the branch and the city — that is ten rows
    about one laboratory, and pressing one of them leaves the other nine standing. The owner read
    it, fairly, as the joining not having worked.

    A pair says "these two are one". Said of A and B and of B and C, it says all three are one, and
    offering that as three questions is asking the same question three times. So the pairs are
    closed over: every name reachable from another through them is one family, offered once, joined
    by one press.

    Only what the pairs already said. Nothing new is proposed here, and nothing is joined: a family
    is still a question, and a person still answers it.
    """
    family: dict[str, set[str]] = {}
    for one, other in worth_joining(kind, names):
        together = family.get(one, {one}) | family.get(other, {other})
        for name in together:
            family[name] = together
    seen, out = set(), []
    for name in names:
        group = family.get(name)
        if not group or id(group) in seen:
            continue
        seen.add(id(group))
        # The shortest spelling first, which is what the page offers as the label: a version, a
        # branch and a city are what one form adds to a name, not part of it.
        out.append(sorted(group, key=lambda spelling: (len(spelling), spelling)))
    return out


def a_speciality_in_front(shorter: tuple[str, ...], longer: tuple[str, ...]) -> bool:
    """Whether the longer name is the shorter one with words put in front of it, and nothing else.

    What a form does to a doctor's name: "Уролог Кривопишин В.Г", "Лікар-офтальмолог Кривопишин
    В.Г." — made-up names, as everywhere in this file. The name itself ends the string, because
    that is where a form prints it: the title, the speciality and the word for "doctor" go in
    front. Measured over the 19 such pairs the three archives here offer, every one of them is
    this shape, and two of the 19 have both a title and a speciality in front.

    Said as the run of words and not as "the extra words are not part of a name", because nothing
    in the words can tell those apart, and that is the whole reason this function exists.
    """
    return len(shorter) <= len(longer) and longer[len(longer) - len(shorter):] == shorter


def worth_joining(kind: str, names: list[str]) -> list[tuple[str, str]]:
    """Pairs of printed names a person is asked about, the shorter first. Never a verdict.

    Two shapes, and they are not the same shape: a speciality written in front of a doctor's name,
    "Кривопишин В.Г" and "Ортопед-Травматолог Кривопишин В.Г"; a branch or a version of the
    software appended to a laboratory's own name, "Invented Medical Lab" and "Invented Medical Lab,
    Analyser 3". Both pairs are made up; the live ones are nobody's business but the archive's.

    **The two kinds are asked different questions, and the fourth entry is why.** Every word of
    one name standing somewhere in the other is right for a laboratory and wrong for a person. It
    is wrong for a person because a name is made longer by adding to the name — another initial, a
    patronymic written out, a second surname — and two doctors of one surname and one initial work
    in two clinics of every city. Offered that pair, a person cannot answer it: no document
    anywhere says whether two "Петров А.Б." are one, so the mistake cannot be caught by reading
    the screen, and the page would be teaching them to tick a claim nobody can check. §4 lets a
    page put a pair in front of somebody; it does not let it put one there that the person has no
    way of weighing.

    So for a doctor the shorter name must be the run of words the longer one ends with — the shape
    above, and only it. Three invented shapes it now refuses, each of which it offered before:
    "Абва О" inside "Абва О.П" (one initial against two), "Абва Олег" inside "Абва Олег Петрович"
    (the patronymic written out), and "Гдеж І.В" inside "Гдеж-Абва І.В" — the last being the cost
    the_words_in writes down for splitting on a hyphen, which no longer reaches a person's name.
    None of the three stands on these archives, which is exactly why they are invented: the sixth
    entry says an archive is blind to the shapes it does not happen to contain.

    For an institution the subset stays, and the measurement is the reason it has to. A run at the
    end would take 62 of the 86 institution pairs these archives offer and leave 24 — a laboratory
    writes itself as its own name, its name with the software, the software with a version, the
    version with a point release, the branch and the city, and all but the first of those are words
    added behind. The cost of being wrong differs too, and in a way a page can do something about:
    a clinic joined by mistake shows itself, because its forms print the branch and the city beside
    the name, and a person reading two labels side by side can weigh them. That is §4's third
    condition, and it is the one that does not hold for a human being's name.
    """
    if kind not in KINDS:
        raise ValueError(f"not a kind of name this program knows: {kind!r}")
    order = {name: the_words_in(name) for name in names}
    bag = {name: set(words) for name, words in order.items()}
    found = []
    for one in names:
        for other in names:
            if one is other:
                continue
            if order[one] == order[other]:
                # The same words in the same order, printed differently: a trailing period after
                # an initial, a comma, a non-breaking space. There is nothing to weigh here — it is
                # one name typed twice — and it was being thrown away, because a set of words
                # equal to another set looked like the name being compared with itself. A model was
                # asked about it instead and said, correctly and for money, "a punctuation artifact
                # of the form rather than a different person".
                #
                # The order is what makes this safe. Compared as sets, "Петров А.Б" and "Петров Б.А"
                # are the same name, and they are two people as often as they are one typing slip.
                if one < other and len(bag[one]) >= LEAST_WORDS:
                    found.append((one, other))
                continue
            if len(bag[one]) < LEAST_WORDS or not bag[one] < bag[other]:
                continue
            if kind == "doctor" and not a_speciality_in_front(order[one], order[other]):
                continue
            found.append((one, other))
    return sorted(set(found))


def carry_the_old_file_in(data_dir: Path) -> dict[str, int]:
    """Move an instance-wide people.json into the archives whose documents name those people.

    For one day this file sat beside the instance, and what it held was read by whichever archive
    happened to be open. Anybody who ran that version has such a file, and it holds work nothing
    else makes again — so it is carried in rather than left or deleted, and each group goes to the
    archives that actually print one of its spellings. A group naming somebody no archive here
    mentions is carried nowhere and the old file is kept, because losing a person's own work to a
    migration is the failure this whole module is about.

    Called once at startup by the page and once by `epicrisis people`, which is the command this
    file is about. It does nothing on the second call, and nothing at all on an instance that never
    had the old file. The promise of a command line used to be in this sentence and in nothing
    else: no command called it, so somebody who put the old file back and ran `epicrisis people`
    was told "0 joined by you" standing on top of their own work.

    What it carried comes back so that something can say so. It said nothing anywhere — not a
    page, not a command, not a line of the README — and a migration nobody is told about is a
    migration nobody can check. See still_beside_the_instance() for the other half of that
    sentence: what has not been carried in, which is what a person needs in order to act.
    """
    import sqlite3

    from epicrisis.index.build import index_path

    old = Path(data_dir) / FILE_NAME
    if not old.exists():
        return {}
    try:
        stored = json.loads(old.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # a torn file is nobody's to guess at; it stays where it is, to be repaired
    groups = [Group(kind=one.get("kind", "doctor"), label=one.get("label", ""),
                    names=list(one.get("names", [])),
                    settled=bool(one.get("settled", True)) and not one.get("refused"),
                    refused=bool(one.get("refused", False)),
                    why=str(one.get("why", ""))) for one in stored if one.get("names")]  # fmt: skip
    carried: dict[str, int] = {}
    found_a_home = set()
    for index in sorted(Path(data_dir).glob("index-*.sqlite")):
        source_id = index.name[len("index-"):-len(".sqlite")]
        try:
            with sqlite3.connect(f"file:{index}?mode=ro", uri=True) as db:
                printed = {row[0] for row in db.execute(
                    "SELECT provider FROM documents WHERE provider IS NOT NULL")}
                printed |= {row[0] for row in db.execute(
                    "SELECT doctor FROM documents WHERE doctor IS NOT NULL")}
        except sqlite3.Error:
            return carried  # an index this cannot read is an archive whose share cannot be settled
        theirs = [one for one in groups if set(one.names) & printed]
        if not theirs:
            continue
        if path(data_dir, source_id).exists():
            # A group has found a home when it is inside an archive, and not a line earlier. This
            # counted them before looking here at all, so an archive that already had a people.json
            # of its own — a person restoring data/people.json out of an old copy into an instance
            # that had moved on, or a migration that stopped last time on an index it could not
            # open while they went on pressing Join — had its share of the old file written
            # nowhere, while the old file was renamed as though all of it had been carried in.
            # Every byte was still there, the name of the file said the opposite of what had
            # happened, and nothing else pointed at those groups any more. Measured on copies of
            # the demo, three cases: in the third the group went into one archive, was absent from
            # the other, and the old file claimed both.
            #
            # Which of them is really in there is asked rather than assumed, so a second run on an
            # instance this has already carried in still finds every group at home and still puts
            # the old file aside.
            try:
                already = {frozenset(one.names) for one in load(data_dir, source_id)}
            except Unreadable:
                continue  # a file nobody can read is not one to judge a group against
            found_a_home.update(id(one) for one in theirs if frozenset(one.names) in already)
            continue
        try:
            with editing(data_dir, source_id):
                save(data_dir, source_id, theirs)
        except Busy:
            # Somebody is editing that archive's own file at this moment. Its groups are left
            # un-homed, which keeps the old file where it is, and the next start carries them in.
            # This is called as the dashboard starts: refusing to start at all because one
            # archive's file was locked for a second would be a worse failure than carrying that
            # one archive in a minute later. Nothing is lost either way — the old file is the copy
            # of this work, and it stays.
            journal.record(data_dir, {"event": "an archive was busy while the old people.json was "
                                               "being carried in", "archive": source_id})  # fmt: skip
            continue
        found_a_home.update(id(one) for one in theirs)
        carried[source_id] = len(theirs)
    # The old file goes aside only when every group it held is now inside an archive. One group
    # naming somebody no archive here mentions is enough to keep it: losing a person's own work to
    # a migration is the failure this module exists for.
    if groups and len(found_a_home) == len(groups):
        old.rename(old.with_name(old.name + ".carried-into-the-archives"))
    return carried


def still_beside_the_instance(data_dir: Path) -> int:
    """How many groups are still in an instance-wide people.json, waiting to be carried in.

    Nought on every instance that never had one, which is every instance made since the day it
    moved, so this is a number a page may print unconditionally and say nothing for nearly
    everybody. It is here because the migration said nothing anywhere: no page, no command and no
    line of the README mentioned it, so a group that had been carried nowhere — nobody's archive
    printing its names, or an archive that already had a file of its own — waited in that file
    with nothing on the machine saying it was waiting. §7.

    A file that will not parse counts as one group waiting, and it is the most important case to
    count: that is somebody's own work, unreadable, with nothing else pointing at it.
    """
    old = Path(data_dir) / FILE_NAME
    if not old.exists():
        return 0
    try:
        stored = json.loads(old.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 1
    return len([one for one in stored if isinstance(one, dict) and one.get("names")])
