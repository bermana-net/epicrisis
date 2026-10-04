"""Copy out the part of an instance that nothing can make again.

Under `data/` there are three kinds of thing, and for two versions the README called all of them
"derived" and told a person they could delete the lot and have it rebuilt from scratch. The index
and the checks, yes, in seconds. The readings, only by paying a model to read five hundred
documents again — and it will read them differently, and the model that read them may not be
served any more. But the corrections a person typed against their own printed lines, the verdicts
they gave on findings, the five hundred groups of spellings they approved one at a time, the
earlier reading kept when a later one displaced it, and the conversations they had about their own
records: nothing rebuilds any of that. It is small — a few megabytes against an archive of scans —
and there was no command that copied it, and no mention of a backup anywhere in the program or its
documentation.

So this copies exactly those, keeping the shape of the folders they sit in, and says what it took
and what it deliberately left. It is a copy, not an archive format: putting it back is copying the
files back, which needs no version of this program to still exist.
"""

from dataclasses import dataclass, field
from pathlib import Path

from epicrisis import layout
from epicrisis.runs import copy_whole
from epicrisis.sources import OUTPUT_DIR_NAME, SourceRegistry


@dataclass
class Copied:
    """What a backup took, by name, and how much of it."""

    files: int = 0
    bytes: int = 0
    took: list[str] = field(default_factory=list)  # paths inside the data directory, as copied
    missing: list[str] = field(default_factory=list)  # kinds of work this instance holds none of
    # Files of this instance that no longer parse, and what was done with them. A copy is the one
    # way back from a file that has gone wrong, and copying the wrong file over the good copy
    # destroys exactly the thing the command exists for.
    unreadable: list[str] = field(default_factory=list)
    kept_instead: list[str] = field(default_factory=list)  # copies already there that were left alone


def back_up(data_dir: Path, into: Path) -> Copied:
    """Copy this instance's irreplaceable files into a folder, keeping their places.

    Every archive's own folder is walked, plus the two files of the data directory itself. Nothing
    that a rebuild can make is copied: an index is not worth carrying, and carrying it would make a
    backup as large as the thing it is meant to make small enough to keep.
    """
    data_dir = Path(data_dir).resolve()
    into = Path(into).expanduser().resolve()
    if into.is_relative_to(data_dir):
        raise ValueError("The copy would be written inside the folder it is copying. Choose a folder outside it.")
    for archive in _archive_folders(data_dir):
        if into == archive or into.is_relative_to(archive):
            # An archive is read and never written to, which everything else in this program
            # already refuses to break — the walk of the folder, the registry. One mistyped path
            # here would put one person's corrections and conversations inside another person's
            # folder of documents, where the next walk of it would find them.
            raise ValueError(
                "The copy would be written inside a folder of documents this instance reads. "
                "Those folders are only ever read; choose a folder outside every archive."
            )
    copied = Copied()
    for relative in _what_to_take(data_dir):
        source = data_dir / relative
        target = into / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        # Every file through copy_whole: written beside the target and renamed over it, so a disk
        # that fills in the middle leaves the copy that was already there untouched. Copied
        # straight over, a second backup onto a stick with no room left came away holding half of
        # one file and none of the version it had held since the last time — the one state a
        # backup exists to make impossible.
        taken_here = 0
        for item in sorted(source.rglob("*")) if source.is_dir() else [source]:
            if not item.is_file():
                continue
            where = target / item.relative_to(source) if source.is_dir() else target
            # What is carried is read first. A file of this instance that has stopped parsing —
            # a write cut off by a full disk, a line torn by a machine that died — used to be
            # copied over the last whole copy of itself, and the command said "copied" and named
            # it among what it had taken. The one way back from the trouble was destroyed by the
            # command that exists to keep it, in silence, at the moment it was needed.
            if not _parses(item) and where.exists():
                beside = where.with_name(where.name + UNREADABLE_SUFFIX)
                copy_whole(item, beside)
                copied.unreadable.append(str(relative if not source.is_dir() else item.relative_to(data_dir)))
                copied.kept_instead.append(str(beside.relative_to(into)))
                continue
            copy_whole(item, where)
            copied.files += 1
            copied.bytes += item.stat().st_size
            taken_here += 1
            if not _parses(item):  # nothing was there to keep, so it goes, and it is said out loud
                copied.unreadable.append(str(relative if not source.is_dir() else item.relative_to(data_dir)))
        # Named only if something of it was in fact carried. A folder that exists and holds nothing
        # — chats/, before anybody has asked this instance a question — was listed among what went
        # into the copy while the count beside it said one file fewer: "Copied 2 files", three names
        # under it. On the one command whose whole job is to say whether what cannot be rebuilt has
        # left this machine, a count that does not add up to the list costs more than it looks. An
        # empty one belongs in the line below, which says what this instance does not have yet.
        if taken_here:
            copied.took.append(str(relative))
    for name in layout.THEIR_OWN_WORK:
        if not any(Path(taken).name == name for taken in copied.took):
            copied.missing.append(name)
    return copied


# The name a file that will not parse is copied under, so that it is beside the whole copy rather
# than over it. Dated by the person's own clock is not needed: one is enough, and a second run
# replaces it, which is the same file that went wrong.
UNREADABLE_SUFFIX = ".unreadable"


def _parses(item: Path) -> bool:
    """Whether this file still reads as what it is. Only the kinds this program writes."""
    import json

    try:
        if item.suffix == ".json":
            json.loads(item.read_text(encoding="utf-8"))
            return True
        if item.suffix == ".jsonl":
            # One torn line among many is one record lost and the rest is still the archive — the
            # reader of these files says so itself. A copy of it is still worth having; what is
            # refused is putting it over a copy that holds the record this one lost.
            return not any(_torn(line) for line in item.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    return True  # anything else is bytes to this program, and bytes are copied as they are


def _torn(line: str) -> bool:
    import json

    if not line.strip():
        return False
    try:
        json.loads(line)
    except ValueError:
        return True
    return False


def _archive_folders(data_dir: Path) -> list[Path]:
    """The folders of documents this instance reads, resolved. Never written to, by anybody."""
    try:
        return [Path(source.path).resolve() for source in SourceRegistry(data_dir).list()]
    except Exception:
        return []  # a registry that cannot be read refuses nothing here; the copy is still made


def _what_to_take(data_dir: Path) -> list[Path]:
    """Every path of a person's own work in this instance, relative to the data directory.

    The registry is read through SourceRegistry rather than by globbing, so an archive taken off the
    list is not carried; and the folders are walked even where the registry cannot be read, because
    a backup is the one thing that should still work when the instance is in trouble.
    """
    taking: list[Path] = []
    # Their choices as well as their work, from the lists in layout.py. sources.json is the
    # difference between a copy and a copy that can be put back: everything under sources/<id>/ is
    # filed under an id made of four random bytes, and that file is the only place saying which id
    # belongs to which folder. settings.json is nineteen switches, three models, the answer mode
    # and every rule's thresholds — minutes to give again by hand, and gone without a word if
    # nobody carries it. consent.json is deliberately not here: a restored copy should ask.
    # rules/ is here because a rule of this instance's own is a file somebody typed: a TOML header
    # and a body in prose saying what the check looks at and how it can be wrong, written for one
    # laboratory's forms and held by nobody else. Nothing rebuilds that, and the command that
    # reports what it carried reads layout.THEIR_OWN_WORK — so a name in that list and not in this
    # loop would be reported as a kind of work this instance holds none of while it sat on disk.
    for name in (*layout.THEIR_CHOICES, layout.INDICATORS, layout.CHATS, layout.RULES):
        if (data_dir / name).exists():
            taking.append(Path(name))
    output = data_dir / OUTPUT_DIR_NAME
    try:
        folders = [Path(OUTPUT_DIR_NAME) / source.id for source in SourceRegistry(data_dir).list()]
    except Exception:
        folders = [Path(OUTPUT_DIR_NAME) / item.name for item in sorted(output.glob("*")) if item.is_dir()]
    for folder in folders:
        # people.json is here because it lives inside the archive it is about, which it has only
        # done since the day the instance-wide one leaked a person's doctors onto somebody else's
        # page. It was missing from this list before that move and after it, so the one command
        # whose job is to carry off what nothing can rebuild carried four of the six kinds and
        # named this one under "none of these in this instance yet" while it sat on the disk
        # holding somebody's joins. layout.THEIR_OWN_WORK is the list that answers the question;
        # this loop has to ask it rather than keep its own.
        for name in (layout.CORRECTIONS, layout.JUDGEMENTS, layout.REPLACED, layout.PEOPLE):
            if (data_dir / folder / name).exists():
                taking.append(folder / name)
    return taking
