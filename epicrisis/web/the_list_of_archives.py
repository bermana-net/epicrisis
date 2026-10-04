"""The list of archives: adding one, naming whose it is, showing another, reading one again from
nothing, taking one off, and looking through a folder again.

Six presses and no page of their own. The page they stand on is the archive status page, which
`web/app.py` draws, and it is the one page of this program that is about the list itself rather
than about one person's records: renaming, rescanning or taking an archive off the list are acts
on the list. See `_the_open_archive` in `web/app.py`, which says exactly that where it makes the
exception.

Which archive comes in as an argument with no default of its own, as every door into an archive
does — and here that argument is `source_id`, the id out of the address, because these are the
presses that may be about an archive which is not the one open. The one that has to know which
was open is the picker in the bar of every page, and `shown_instead` takes `TheArchives` for it,
with no default either: the journal line it writes is "this archive instead of that one", and
asked a second time the file could answer differently.

Each press hands back a `Pressed` — what was stored and what was refused — as a value rather than
printing or redirecting. Two of them are the reason that is worth anything here. Reading an
archive again from nothing refuses while something holds a lock in its folder, and the sentence it
refuses with names the lock and what to do about it; adding one refuses a folder offered with
nobody's name on it. Both of those could only be read out of a drawn page before.

The two presses that write the list then read it again on purpose, and the comment at each says
why: the reading the request was decided by is the one from before the write.

Nothing here knows about `request`, `templates` or FastAPI. The routes in `web/app.py` are the
shells, and the reading of a folder itself stays there — `web/jobs.py` holds that job, and
starting one is not a decision.

Constitution §8 stands over reading an archive again from nothing: what a person typed, corrected,
approved or joined is moved aside and kept, never deleted. `SourceRegistry.forget` does the
moving, and `moved_aside` below is where it put it.
"""

from dataclasses import dataclass
from pathlib import Path

from epicrisis import journal
from epicrisis.runs import ABANDONED_AFTER_HOURS, holder
from epicrisis.sources import Source, SourceError, SourceRegistry, TheArchives, source_output_dir
from epicrisis.update import update_running

#: Said to a folder offered with nobody's name on it. Whose records these are is not decoration:
#: every page carries the name and every answer the tools give says it. An archive added without
#: one reads as nobody's, and the reading starts the moment it is added, so it is asked for
#: before anything begins.
SAY_WHOSE = "Say whose archive this is. The name is on every page and in every answer."

#: Said while something is reading the archive somebody asked to read again from nothing.
SOMETHING_IS_READING = "Something is reading this archive right now. Wait for it to finish."


@dataclass(frozen=True)
class Pressed:
    """What one press on the list of archives came to: what was stored, and what was refused.

    `refused` is the half this returns for: both of the presses that can refuse here refuse with
    a sentence written for a person — one naming the lock that is in the way and the file to
    delete, the other asking for the name the archive is of — and a press that answers with a
    value can be asked, in a test, whether it said so.

    `code` is the status the page that says it is drawn with, because a refusal here is the
    status page again and not a redirect: 400 for a form that asked for nothing this does, 409
    for an archive something else is holding. It is 0 where the press is over and the route sends
    the person on.

    `started` is the archive whose reading is to begin. The job lives in `web/jobs.py`, so the
    route starts it; what this decides is which archive, and whether there is one at all.

    `moved_aside` is where the reading that was put aside now sits. `nothing_to_move` is the
    other answer, and it is a different one: an archive nothing had been read from yet. The page
    says which of the two it was, which is why they are two fields and not an empty path.
    """

    stored: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()
    code: int = 0
    started: Source | None = None
    moved_aside: Path | None = None
    nothing_to_move: bool = False

    @property
    def said(self) -> str:
        """What was in fact done, in a person's words."""
        return ", ".join(self.stored)

    @property
    def trouble(self) -> str:
        """Why a press did nothing, in a person's words. Empty where it did something."""
        return " ".join(self.refused)


def added(registry: SourceRegistry, *, path: str = "", owner: str = "") -> Pressed:
    """A folder of somebody's scans put on the list, with its reading to begin."""
    # Whose records these are is not decoration: every page carries the name and every answer
    # the tools give says it. An archive added without one reads as nobody's, and the reading
    # starts the moment it is added, so it is asked for before anything begins.
    if not owner.strip():
        return Pressed(refused=(SAY_WHOSE,), code=400)
    try:
        source = registry.add(path, owner)
    except SourceError as exc:
        return Pressed(refused=(str(exc),), code=400)
    # Read again, and it has to be: the list was just written to, and the reading this request
    # was decided by is the one from before the archive was added.
    if len(registry.list()) == 1:
        registry.set_active(source.id)
    return Pressed(stored=("an archive added to the list",), started=source)


def shown_instead(registry: SourceRegistry, archives: TheArchives, source_id: str) -> Pressed:
    """Show another owner's archive, without leaving the page the question was asked on.

    Each archive keeps its own index, so the same page simply answers for somebody else —
    and where they have nothing, it says so where it stands rather than sending a person
    back to the timeline to find their way again.
    """
    # Written down because this is the act the first line of the constitution is about. One
    # archive is open at a time, for the whole instance, and a page that read the open one
    # without asking whose it was is how one person's screen came to show another person's
    # doctors. If that ever happens again, the question will be which archive was open when —
    # and nothing could answer it: the switch left no trace anywhere.
    #
    # Both ids and nothing else. They are random for exactly this reason: the folder names
    # carry surnames, and the name of whoever an archive belongs to is not written here even
    # though every page shows it in the picker.
    was = archives.showing
    registry.set_active(source_id)
    journal.record(registry.data_dir,
                   {"event": "the archive shown was switched", "archive": source_id,
                    **({"instead_of": was.id} if was else {})})  # fmt: skip
    return Pressed(stored=("the archive shown was switched",))


def owner_named(registry: SourceRegistry, source_id: str, *, owner: str = "") -> Pressed:
    """Whose archive this is, said again. An act on the list, so it is about the id in the
    address and not about the archive that happens to be open."""
    registry.set_owner(source_id, owner)
    return Pressed(stored=("whose an archive is",))


def read_again_from_nothing(registry: SourceRegistry, source_id: str, *,
                            understood: str = "") -> Pressed:  # fmt: skip
    """Read this archive again from nothing. The folder stays; the reading is put aside."""
    if understood != "yes":
        return Pressed()
    # A run writing into the folder we are about to move would carry on writing into nowhere.
    # Every lock in the folder, not a list of three by name: the search for dates and the
    # checks write here too and were not among the three, so a run of either was moved out
    # from under itself.
    output = source_output_dir(registry.data_dir, source_id)
    held = [lock for lock in sorted(output.glob("*.lock")) if holder(lock)]
    if update_running(registry.data_dir) or held:
        # Which lock, named. "Wait for it to finish" was the whole of this answer, and over a
        # lock left behind by a run that had died it was advice to wait for ever — under the
        # one button that would have put the archive back in order.
        error = SOMETHING_IS_READING
        if held and not update_running(registry.data_dir):
            error += (" What holds it is the lock "
                      + ", ".join(str(lock.relative_to(registry.data_dir)) for lock in held)
                      + ". If nothing is running — the machine was restarted, or the run died — that "
                      "file is left over, and deleting it lets this archive be read again. A lock "
                      f"older than {ABANDONED_AFTER_HOURS} hours is ignored by itself.")
        return Pressed(refused=(error,), code=409)
    aside = registry.forget(source_id)
    return Pressed(stored=("the reading of an archive put aside",), moved_aside=aside,
                   nothing_to_move=aside is None)  # fmt: skip


def taken_off_the_list(registry: SourceRegistry, source_id: str) -> Pressed:
    """Take an archive off the list. What was read from it stays on disk, as does the folder."""
    going = registry.remove(source_id)
    # Read again, and deliberately: the list was just written to, so anything decided before
    # this press still holds the archive that has gone, and still calls it the open one.
    if going and going.active and registry.list():
        registry.set_active(registry.list()[0].id)
    return Pressed(stored=("an archive taken off the list",) if going else ())


def looked_through_again(registry: SourceRegistry, source_id: str) -> Pressed:
    """Look through the folder again for files this reading has never seen.

    The archive is the one the address names, read off the list afresh, and this is the
    exception the status page makes for itself: it lists every archive, and looking through one
    again is an act on the list. A `Pressed` with nothing started is an address naming no
    archive this server holds.
    """
    source = registry.get(source_id)
    if source is None:
        return Pressed()
    return Pressed(stored=("a folder looked through again",), started=source)
