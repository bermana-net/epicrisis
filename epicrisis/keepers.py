"""Who this instance is for: a keeper, the signature they are known by, and the archives they keep.

An archive has one. `419b84dd` names a folder of somebody's documents, the folder of everything
read out of it, and the index beside it — and it goes on naming them when the folder moves, when
the person's name is spelled another way, and when two archives on one instance carry one name.

The keeper of an archive had none. `Source.owner` is the name as somebody typed it, and a name is
not an identity: two people of one name are one string, and one person written two ways is two.
While an instance is one person's that costs nothing. The day it holds several keepers, each of
those two is one person's records answered to somebody else, which is the first entry of the
constitution and the one failure no apology undoes.

So a keeper is issued a signature of the same shape as an archive's, by the same means: four
random bytes, unique on the list, written down once and never again. **It is never worked out
from the name.** That is the fourth entry's reasoning — a model may settle what names a form and
never what names a person, because identity is a claim and a spelling of it is not the claim. A
signature computed from a name is the name again: it says two people of one name are one, and it
moves the moment somebody corrects a letter. This one cannot do either.

**The archives a keeper keeps live here too, and here is the argument for that side of the line.**
One line per keeper carries a list of archive ids, and that list is the whole of the link. The
first entry of the constitution draws its line at *a string printed on somebody's document*, and
there is no such string on either side of this record: a signature is four random bytes and an
archive's id is four random bytes, which is why `sources.py` made them random in the first place
— folder names carry surnames and diagnoses, and these carry no part of either. Held the other way
round, as half of the link beside each archive — a "kept by" inside each folder — the question
"which archives does this keeper keep" could only be answered by reading every archive in turn:
that is n readings inside one answer where `TheArchives` exists to allow exactly one, and a half
that would not read would make the answer silently short rather than refuse it. One file, one
reading, one answer, and `ARCHITECTURE.md` says the same in a line: nothing else may hold half of
it.

**It answers one question and refuses two.** Whose these archives are — that is all it says.
*Which archives exist* is `sources.json`'s answer and no other file's, so the link is read
**against** that list and never instead of it: an id here that is on no archive names nothing and
is shown nowhere (`the_archives_they_keep`). *Which archive is open* is `sources.json`'s too, and
stays there. And "these archives are kept by that person" is not "that person may open them" —
the second is a claim about permission, nothing in this program makes it yet, and the day it is
made is not the day this file starts meaning it.

**A keeper has no name, and that is how the double ended.** The step before this one wrote the
archive's owner down here as well, as a proposal, and said this step would end the duplication.
It ends by subtraction. A name is a spelling of somebody; `Source.owner` is the one place it is
typed and the one place every page reads it from; and a copy of it here could only ever drift,
because correcting an owner's spelling does not and must not move a signature — so the two were
guaranteed to disagree the first time somebody fixed a letter, and a count that differs from
another count on the same page is the seventh entry's defect waiting to happen. What is left is a
keeper who is a signature and a list of archives. The dilemma the step before had to choose a
side of — two keepers of one spelling, or one keeper over two people — dissolves with the name
that caused it: **a keeper is not either of the people whose records they keep.** Nothing here
says who they are, because nothing here can, which is the fourth entry held in the strongest
form available.

**One keeper to an instance**, and that is the one claim this step does make, so it is named. An
instance of this program has no login and answers only to this machine, so whoever keeps the
archives on it is whoever runs it, and there is one of them. The first name written down on an
instance therefore issues one signature, and every archive named after that is added to that
keeper's list. Where a list somehow holds more than one keeper, this links nothing at all and the
archives show as kept by nobody: which keeper keeps a new archive is then a question about people,
and the fourth entry says who answers those. A second keeper belongs to the step that hands out
permission, and that is not this one.

**What reads it.** One page, and it only shows: the settings page says who this instance is for,
by the owners of the archives each keeper keeps and never by a signature — no signature reaches
the bytes of any page. Nothing else reads it: no door takes one, no filter asks one, no index is
opened by one, nothing is counted or sorted by one, and no press here decides anything.
"""

import functools
import json
import secrets
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from epicrisis import layout, records
from epicrisis.runs import copy_whole, one_at_a_time, write_whole
from epicrisis.state import Unreadable

FILE_NAME = layout.KEEPERS
LOCK_NAME = "keepers.lock"
#: Four random bytes, which is what an archive's id is made of in `SourceRegistry.add`. One shape
#: for the two because they are the same kind of thing — a name for somebody that carries no part
#: of their name — and because a signature ends up where only Latin letters can be carried: a
#: path, a URL, a line of a log.
SIGNATURE_BYTES = 4


@dataclass(frozen=True)
class Keeper:
    """One person this instance is for: the signature they are known by, and what they keep.

    The signature is the keeper, and it is the whole of them — there is no name here, for the
    reason the module says at length. `archives` holds the id of each archive this keeper keeps.
    It is a claim about whose they are and about nothing else, and it is never trusted on its
    own: `the_archives_they_keep` reads it against the list of archives, which is the only
    answer to which archives there are.
    """

    id: str
    issued_at: str
    archives: tuple[str, ...] = ()


def path(data_dir: Path) -> Path:
    return Path(data_dir) / FILE_NAME


def load(data_dir: Path) -> list[Keeper]:
    """Every keeper on the list. Raises where the file is there and will not read.

    Not an empty list, for the reason `people.load` and `indicators.load` give and paid for: every
    writer here is load, change, save, so a reader that answers "there are none" over a torn file
    has the next write put that emptiness back — and a signature written over is an identity that
    cannot be issued again, because the one that comes back is a different string. The archives
    written beside it go the same way, and nothing else on the machine says whose they are.
    """
    file = path(data_dir)
    if not file.exists():
        return []
    try:
        stored = json.loads(file.read_text(encoding="utf-8"))
        keepers = [
            Keeper(id=str(one["id"]), issued_at=str(one.get("issued_at", "")),
                   archives=tuple(str(archive) for archive in _the_archives_on_one_line(one)))
            for one in stored
            if one.get("id")
        ]  # fmt: skip
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as torn:
        raise Unreadable(
            FILE_NAME,
            # What is safe, first, because it is the first thing a person needs: no name is in
            # this file's keeping at all. Each of them is on its own archive in sources.json,
            # where somebody typed it, and every page draws it from there and never from here.
            f"No archive has been touched and no name has been lost: this file holds no name — the "
            f"name on every archive is in {layout.SOURCES} beside it, as its owner typed it, and "
            f"every page draws it from there. What is in here is which archives are kept by whom, "
            f"and one page shows it.",
            f"The copy beside it is the version before the last change. Put it back — "
            f"mv {FILE_NAME}.previous {FILE_NAME} — and every signature issued up to that change, "
            f"and every archive it was linked to, is there again. If there is no copy, this was "
            f"the file's first write: delete it, and the next name written down on an archive "
            f"issues a signature again and links every named archive to it, out of "
            f"{layout.SOURCES} alone. It is a new signature, which costs nothing while no door "
            f"and no filter takes one, and costs whatever has come to take one by the day it "
            f"happens.",
        ) from torn
    return keepers


def _the_archives_on_one_line(one: dict) -> list:
    """The archives one keeper keeps, as the file holds them, refused where that is not a list.

    A file somebody edited by hand saying `"archives": "419b84dd"` would otherwise be read as
    eight archives of one letter each — an answer that is wrong rather than refused, which is the
    shape the eighth entry is written about, and which the next write would put back as the truth.

    A line written before the archives were kept here carries no `archives` at all and keeps none,
    which is exactly what is true of it: the step that wrote it never wrote the link down.
    """
    archives = one.get("archives", [])
    if not isinstance(archives, list):
        raise TypeError(f"the archives of a keeper are {type(archives).__name__} and not a list")
    return archives


def the_archives_they_keep(keeper: Keeper, archives) -> tuple:
    """Which of these archives this keeper keeps — the link, read against the list of archives.

    The list is passed in and never fetched, for the reason `TheArchives` gives: two readings
    inside one answer can be two different lists. Each entry is asked for its `id` and nothing
    else.

    **An id on a keeper's list that is not on the list of archives names no archive and is
    returned by nothing.** That is the first of this step's three borders held in code rather
    than promised: which archives exist is `sources.json`'s answer, and a second answerer is the
    defect this project spends its weeks removing. An archive taken off the list therefore
    disappears from here the moment it is taken off, without this file being written to — and
    nothing in `remove` has to remember to come here, which is the kind of remembering that gets
    forgotten.
    """
    kept = set(keeper.archives)
    return tuple(one for one in archives if one.id in kept)


def kept_by_nobody(keepers, archives) -> tuple:
    """The archives on the list that no keeper on the list keeps.

    Said out loud rather than left out, because an archive kept by nobody is the honest state of
    two ordinary things: a folder added with no name typed on it yet, and a list that holds more
    than one keeper, where this program does not pick one. A page that drew only the kept ones
    would show a shorter list of archives than the archives page does, and a count that differs
    from another count on the same instance is the seventh entry's defect.
    """
    kept = {archive for keeper in keepers for archive in keeper.archives}
    return tuple(one for one in archives if one.id not in kept)


def unreadable(data_dir: Path) -> bool:
    """Whether the file is there and will not read, asked without raising."""
    try:
        load(data_dir)
    except Unreadable:
        return True
    return False


def get(data_dir: Path, keeper_id: str) -> Keeper | None:
    return next((one for one in load(data_dir) if one.id == keeper_id), None)


def save(data_dir: Path, keepers: list[Keeper]) -> None:
    """Write the whole list, keeping the version it replaces beside it.

    Asked again here rather than trusted to load(), as people.save asks: a caller that caught
    Unreadable in the middle of its own work must not reach this write with a list built from
    nothing.
    """
    file = path(data_dir)
    if unreadable(data_dir):
        raise Unreadable(
            FILE_NAME,
            f"Nothing was written. Every signature issued so far is still in that file, and every "
            f"name is in {layout.SOURCES} beside it, as its owner typed it.",
            f"The copy beside it is the version before the last change: mv {FILE_NAME}.previous "
            f"{FILE_NAME}.",
        )
    if file.exists():
        copy_whole(file, file.with_name(file.name + ".previous"))
    write_whole(file, json.dumps([asdict(one) for one in keepers], ensure_ascii=False, indent=2) + "\n")


def editing(data_dir: Path):
    """One writer at a time, for the whole of a change and not only for the write at the end.

    One lock for the instance, because this is one file for the instance. Every writer below reads
    the whole list and writes the whole list back, which is the shape that lost a group of
    spellings in `people.py` before that module held its lock across the read.
    """
    return one_at_a_time(path(data_dir).with_name(LOCK_NAME), "Editing the keepers")


def while_editing(change):
    """Hold the lock for the whole of a change. The twin of people.while_editing, for one file."""

    @functools.wraps(change)
    def guarded(data_dir: Path, *args, **kwargs):
        with editing(data_dir):
            return change(data_dir, *args, **kwargs)

    return guarded


@while_editing
def catch_up(data_dir: Path, before, after) -> list[Keeper]:
    """The keeper of this instance, issued once, and every newly named archive added to what they keep.

    `before` and `after` are the list of archives as it stood and as it has just been written.
    Each entry is asked for two things and nothing else: its `id` and its `owner`. An archive is
    newly named when it is on `after` with an owner and was not on `before` with one — a folder
    added with a name beside it, or a name typed on an archive that had none. What is returned is
    the keeper as it now stands, or nothing at all where nothing changed; the file is not written
    in the second case.

    **Correcting the spelling of an owner is not that, and changes nothing here.** A signature
    does not move when a name does, and neither does the link: that is what both are for. The name
    itself is on the archive, where somebody typed it, and this module never copies it.

    An instance with no keeper at all is the whole of its list being newly named: those owners were
    typed before there was anywhere to put a signature. That happens once per instance, and the
    test for it is "no keeper on the list" rather than a flag written beside it — a flag is a
    second statement of the same fact, and two statements of one fact disagree.

    **One keeper, and the archives are added to them.** The step before this one issued a
    signature per named archive and had to choose between two errors — two keepers where one
    spelling stood for one person, or one keeper standing over two people. That choice was forced
    by the keeper carrying a name. It does not carry one now, so neither error is on the table: a
    keeper is nobody's name, an instance has no login and answers only to this machine, and
    whoever keeps these archives is whoever runs it.

    **Where the list holds more than one keeper, nothing is linked.** It cannot happen by this
    code, and it is written anyway, because the moment a second keeper exists "which of them keeps
    this new archive" is a question about people and the fourth entry says who answers those: the
    person, never the program, and never by matching a spelling. The archive then shows as kept by
    nobody, which is true, is visible on the page, and is the state a press of the step that hands
    out permission will be asked to settle.
    """
    keepers = load(data_dir)
    named_before = {one.id for one in before if one.owner}
    newly_named = [one for one in after if one.owner and (not keepers or one.id not in named_before)]
    if not newly_named or len(keepers) > 1:
        return []
    kept = tuple(dict.fromkeys([*(keepers[0].archives if keepers else ()), *(one.id for one in newly_named)]))
    if keepers:
        # An archive whose name was cleared and typed again is newly named twice and kept once.
        # Written as "nothing to add" rather than as a write of the same bytes, because a write
        # moves the copy beside it: the version before the last change would become a copy of the
        # version it is, and the one thing a person has to put back would be gone.
        if kept == keepers[0].archives:
            return []
        the_keeper = replace(keepers[0], archives=kept)
    else:
        the_keeper = Keeper(id=_a_signature_nobody_has({one.id for one in keepers}),
                            issued_at=records.now(), archives=kept)  # fmt: skip
    # The whole list, which on this branch is the one keeper: the guard above has already turned
    # back anything longer, and writing it out as the whole list rather than as an append is what
    # makes that visible here, where somebody loosening the guard would be standing.
    save(data_dir, [the_keeper])
    return [the_keeper]


def _a_signature_nobody_has(taken: set[str]) -> str:
    """Four random bytes that no keeper on the list already carries.

    The same loop `SourceRegistry.add` draws an archive's id with, and here for the same reason:
    four bytes collide about once in sixty-five thousand, and a signature handed to two keepers
    would be two people under one string — which is the one failure this file exists to prevent.
    """
    signature = secrets.token_hex(SIGNATURE_BYTES)
    while signature in taken:
        signature = secrets.token_hex(SIGNATURE_BYTES)
    return signature
