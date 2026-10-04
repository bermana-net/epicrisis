"""A file this program keeps its own state in is there and will not read.

Not the same thing as a file that is missing. A missing one means a new instance, and every
reader of these files answers with its default, which is right. A file that exists and will not
parse means a write was cut off — a disk that filled, a machine that died, a hand that edited it —
and answering with a default there is how a lock gets turned off over an archive whose owner
turned it on, how five hundred approved groups of spellings get written over with one, and how a
page comes to say "Saved."

Every such file used to answer this in its own way, and the ways did not agree: settings.json
refused to be written over and said so in a sentence, consent.json fell back to "nobody has
consented", indicators.json fell back to "there is no vocabulary" and then wrote that emptiness
to disk, sources.json and the index raised, which the dashboard showed as the words Internal
Server Error on every page including the two a person goes to when something is wrong.

So the answer is one thing, said in one sentence, and the sentence carries three things in the
order a person needs them: which file, what has *not* been lost, and the one act that puts it
right. The terminal and the page say the same words because they are built from the same object.
"""

from pathlib import Path

from epicrisis import layout


class Unreadable(RuntimeError):
    """One of this program's own files of state is there and will not parse."""

    def __init__(self, file: str, safe: str = "", mend: str = ""):
        self.file = file  # named as a person would look for it, inside the data directory
        self.safe = safe  # what is still whole, because that is the first thing they need to know
        self.mend = mend  # the one command or act that puts it right
        super().__init__(" ".join(part for part in (f"{file} is there and cannot be read.", safe, mend) if part))


def where(file) -> str:
    """Where a file is, named so that a person can walk to it: relative to the data directory.

    `Unreadable` carries a name, and a bare name was right while every file of state sat directly
    in the data directory. Then the files of a person's own work moved inside the archive they are
    about, and the refusal began naming a place that does not exist: it said people.json, inside
    the data folder of this instance, while the file was at sources/<id>/people.json — and <id> is
    four random bytes whose meaning lives only in sources.json. Somebody following that advice
    opens the data folder, finds no such file, and has nothing left to try. The same was true of a
    torn transcription, named extracted/<sha>.json for a file two folders deeper.

    The path is cut at the archives folder rather than measured against a data directory, because
    the callers deepest in the pipeline do not have one to measure against, and threading it to
    them to make a sentence read correctly would be a worse trade than reading the path.
    """
    parts = Path(file).parts
    if layout.ARCHIVES in parts:
        return "/".join(parts[parts.index(layout.ARCHIVES):])
    return Path(file).name


class NoSpace(RuntimeError):
    """The disk this instance writes to is full.

    Written whole and renamed into place, every file of state here survives a full disk without
    being damaged — that part held when it was tried. What did not hold is what a person was
    told: six buttons of the dashboard answered with the words Internal Server Error, every page
    looked healthy, and the words "no space" appeared nowhere, so the likeliest next act was to
    start deleting the folder that holds their thirty years of reading.
    """


def no_space(error: OSError) -> bool:
    """Whether this is a disk with no room left on it, rather than any other trouble with a file."""
    import errno

    return getattr(error, "errno", None) in (errno.ENOSPC, errno.EDQUOT)
