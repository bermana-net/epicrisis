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


class Unreadable(RuntimeError):
    """One of this program's own files of state is there and will not parse."""

    def __init__(self, file: str, safe: str = "", mend: str = ""):
        self.file = file  # named as a person would look for it, inside the data directory
        self.safe = safe  # what is still whole, because that is the first thing they need to know
        self.mend = mend  # the one command or act that puts it right
        super().__init__(" ".join(part for part in (f"{file} is there and cannot be read.", safe, mend) if part))


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
