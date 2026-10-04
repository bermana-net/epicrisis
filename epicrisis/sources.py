"""Registry of the archives this server holds, stored in data/sources.json.

One archive is one person's: a folder, and everything under it. Whoever owns the folder owns
every document beneath it, which is a rule nobody can break by mistake, unlike a list of folders
tied to a person by hand. Two owners' folders therefore may not contain one another.

Everything derived from an archive lives under data/sources/<source_id>/, and each has its own
index file, so a question asked of one archive cannot reach another's values. The id is random:
folder names can carry surnames or diagnoses and must not leak into paths on disk or logs.
"""

import json
import os
import secrets
import threading
from epicrisis import layout
from epicrisis.invocation import run
from epicrisis.runs import copy_whole, write_whole
from epicrisis.state import Unreadable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

OUTPUT_DIR_NAME = layout.ARCHIVES  # one name for it, in layout, where a refusal can also read it


# Folders that belong to the server rather than to a person: a scan of them reads thousands of
# files and finds no documents. Their insides count too - /usr/share is as much a system folder
# as /usr. "/" is refused as itself, but not as everyone's parent.
SYSTEM_FOLDERS = {"/etc", "/bin", "/sbin", "/lib", "/lib64", "/usr", "/var", "/boot", "/opt", "/srv", "/root"}
# Where archives may be kept. The dashboard has no login because it listens on this machine only,
# so what a page can be made to read is worth keeping to the places a person keeps documents: their
# home, and the folder this instance already works in. EPICRISIS_ARCHIVE_ROOT adds more, for an
# instance whose scans sit on mounted disks — several of them, separated the way PATH is, because
# one person can keep their mother's archive on the machine and their father's on a stick.
#
# This bound is on the picker, not on the person. A folder typed at the command line is taken as it
# is: typing it out is exactly the consent a page cannot obtain, and somebody with a shell on this
# machine can read the disk anyway. The refusal used to name only the variable, which means stopping
# the server, setting an environment variable and starting it again — a wall, for somebody who came
# with a box of paper — and the way that works in one line was not mentioned at all. Half of those
# people close the tab; the other half copy tens of gigabytes of scans into their home folder, which
# is the one thing this program promises never to do to somebody's archive.
ARCHIVE_ROOT_VARIABLE = "EPICRISIS_ARCHIVE_ROOT"
RUNTIME_FOLDERS = ("/proc", "/sys", "/dev", "/run")

# What a reading of an archive leaves behind, and therefore what starting again puts aside. Worked
# out in layout, where the lists of names live, and only named here — the hand-written copy of it
# that stood here held layout.REPLACED, which layout calls a person's own work: the only copy of a
# reading that a later reading displaced went into forgotten-<when>/, where backup.py does not
# look, and the eighth entry of the constitution is written about exactly that file.
#
# corrections.jsonl is not in it, and that is the same list speaking: a correction is the person's
# own, keyed to the file's whole sha256 and to the line as printed, and it applies again to the
# next reading of the same file.
READING_ARTEFACTS = layout.READING_ARTEFACTS


class SourceError(ValueError):
    """A folder that cannot be added. The message is shown to the user."""


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    path: str
    added_at: str
    owner: str = ""  # whose records these are, as a person would write it
    active: bool = False  # the archive the interface is showing now

    @property
    def whose(self) -> str:
        return self.owner or self.name


def _the_open_one(sources: list[Source]) -> Source | None:
    """Which of these is being shown. With none chosen, the first one added.

    One place, asked by `SourceRegistry.active` and by `as_one_reading` below, because those two
    have to agree about the same list and the rule is not obvious: "none is marked" happens on
    every instance between adding the first archive and anything choosing it.
    """
    return next((source for source in sources if source.active), sources[0] if sources else None)


@dataclass(frozen=True)
class TheArchives:
    """One reading of the list: every archive on it, and which of them is open.

    Reading the file answers both questions at once, and this is what that one answer is carried
    in. `list()` and `active()` each read the file afresh, which is right for a command that asks
    once and exits — and wrong for anything that asks twice, because the archive is switchable
    from the bar of every page, the switch is an ordinary POST that the server answers on another
    thread, and nothing holds a request still. Two readings inside one answer can be two
    different archives, and a page drawn out of two readings is a page of two people: that is the
    first entry of the constitution, and it had already drawn one archive's documents under
    another archive's joined names.

    So it is a value and not a question. Whoever is handed it cannot ask again, and whoever needs
    it has to be given it.
    """

    all: tuple[Source, ...]
    showing: Source | None

    @property
    def showing_id(self) -> str | None:
        """The id of the archive being shown, or None when none is added yet."""
        return self.showing.id if self.showing else None

    @property
    def open(self) -> tuple[Source, ...]:
        """The archive being looked at, as a list, or none at all when none is added yet.

        For the pages that draw one block per archive and must draw it for one person: every page
        but the status page is about one person, and listing everybody's under a heading carrying
        one name is how one archive is read as another's.
        """
        return (self.showing,) if self.showing is not None else ()

    def get(self, source_id: str) -> Source | None:
        """The archive of this id, if it is on the list at all. Whether it is the open one is a
        separate question, and the pages that must ask it ask it of `showing` as well."""
        return next((source for source in self.all if source.id == source_id), None)


#: No archive on the list, for a caller whose reading of it did not come off. A page is still
#: drawn over a torn list of archives — it is the page that says the list is torn — and it is
#: drawn about nobody.
NO_ARCHIVES = TheArchives(all=(), showing=None)


def belongs_to_the_server(path: Path) -> bool:
    """Whether this folder is the server's own rather than a person's, and so never an archive.

    Written once because it was written three times — in validate(), in roots(), and nowhere at all
    in the folder picker, which then told somebody to add /root as an archive in the same sentence
    that refused to show it to them. Any reader of this question that does not ask it here can
    disagree with the two that do, and a person meeting two rules that disagree cannot tell which
    one is the program.
    """
    path = Path(path)
    return str(path) == "/" or any(path.is_relative_to(folder) for folder in SYSTEM_FOLDERS | set(RUNTIME_FOLDERS))


def folder_is_there(path: Path | str) -> bool:
    """Whether an archive's folder is where the list says it is, and can be read through, now.

    One is_dir() and one access(). It is here and not at the point of use because it is asked by
    two doors that have to agree: the status page draws a notice from it, and `sources list` is
    the one command that prints the folders themselves — and printed one that was not there like
    any other, a path to nothing in a column of paths, with nothing beside it. A disk that did
    not mount and a folder renamed are the ordinary reasons, and the ordinary moment somebody
    asks for the list is just after it happened.

    R_OK and X_OK both: a folder that can be listed but not entered is as unreadable as one that
    is gone, and both of them walk empty rather than raising.
    """
    folder = Path(path)
    try:
        return folder.is_dir() and os.access(folder, os.R_OK | os.X_OK)
    except OSError:
        return False


def source_output_dir(data_dir: Path, source_id: str) -> Path:
    return data_dir / OUTPUT_DIR_NAME / source_id


def data_dir_of(output: Path) -> Path:
    """The data directory an archive's output folder sits in: the inverse of source_output_dir.

    A step given an output folder can find what this instance allows without being handed it
    separately by every caller — and the way back is written once, here, beside the way there.
    """
    return output.parent.parent


class SourceRegistry:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()
        self.file = self.data_dir / layout.SOURCES
        self._lock = threading.Lock()

    def list(self) -> list[Source]:
        """The archives on the list, or none at all when there is no list yet.

        A file that is there and will not parse is a third thing, and it used to be neither:
        json.loads raised, and because every page and every command begins by asking this
        question, the whole dashboard answered with the words Internal Server Error and every
        command with a traceback — over a file that is four fields per archive and easy to put
        right, whose name was never said. It is also the file a person is likeliest to edit by
        hand, because until now that was the only way to point an archive at a moved folder.
        """
        if not self.file.exists():
            return []
        try:
            entries = json.loads(self.file.read_text(encoding="utf-8"))
            return [Source(**entry) for entry in entries]
        except (ValueError, TypeError, OSError) as broken:
            raise Unreadable(
                layout.SOURCES,
                "No archive has been touched: everything read from each one is under "
                f"{OUTPUT_DIR_NAME}/<id>/ beside it, and the folders themselves were never written to.",
                # The one action that puts it right, written out. The sentence used to say "repair
                # that file, or move it aside and add the folders again", which is a description and
                # not an action, and it offered the costliest step in the program beside the
                # cheapest as though they were alternatives: adding the folders again gives them new
                # ids, makes a second archive of the same person, and reads every document with a
                # model from nothing. The page about a missing index names its command and is an
                # action because of it.
                #
                # And what that copy is, which this sentence used to leave out. It is the version
                # before the last change, not the list as it stood a moment ago: somebody who had
                # just added an archive, or pointed one at the folder it had moved to, put back a
                # list without that change in it. The archive then went off the list while its
                # folder of work stayed on disk under an id nothing named any more — `sources list`
                # showed one archive fewer, `backup` stopped carrying that folder, and no page said
                # a word about it. What they had been promised, on the way in, was that everything
                # was there again. The file of the indicators calls its own copy the version before
                # the last change; this one now does too, and says where the rest of it is.
                f"The copy beside it is the version before the last change. Put it back — "
                f"mv {layout.SOURCES}.previous {layout.SOURCES} — and every archive that was on the "
                f"list then, everything read from it and every correction on it is there again. What "
                f"that copy does not hold is the last change itself: an archive added, or pointed at "
                f"another folder, since then is not on it. So compare the list that comes back with "
                f"the folders under {OUTPUT_DIR_NAME}/, which "
                f"'{run('sources list', self.data_dir)}' does for you and names what it finds. A "
                f"folder there whose id is not on the list is the work of an archive that has to be "
                f"added again, and what was read from it and the corrections on it are then carried "
                f"into the folder of its new id by hand. Adding the folders again instead of putting "
                f"the copy back is the last resort: they would get new ids, the same person would "
                f"have a second archive, and every document would be read by a model from "
                f"nothing.",
            ) from broken

    def get(self, source_id: str) -> Source | None:
        return next((source for source in self.list() if source.id == source_id), None)

    def add(self, raw_path: str, owner: str = "", typed: bool = False) -> Source:
        with self._lock:
            path = self.validate(raw_path, typed=typed)
            sources = self.list()
            taken = {source.id for source in sources}
            source_id = secrets.token_hex(4)
            while source_id in taken:
                source_id = secrets.token_hex(4)
            source = Source(
                id=source_id,
                name=path.name or str(path),
                path=str(path),
                added_at=datetime.now(UTC).isoformat(timespec="seconds"),
                owner=owner.strip(),
            )
            self._save([*sources, source])
        return source

    def active(self) -> Source | None:
        """The archive being shown. With none chosen, the first one added."""
        return _the_open_one(self.list())

    def as_one_reading(self) -> TheArchives:
        """Every archive and which of them is open, out of a single reading of the file.

        For a caller that needs both, or that needs either more than once: see `TheArchives`.
        """
        sources = self.list()
        return TheArchives(all=tuple(sources), showing=_the_open_one(sources))

    def set_active(self, source_id: str) -> Source | None:
        """Choose whose archive the interface shows. Exactly one is active at a time."""
        with self._lock:
            sources = self.list()
            if not any(source.id == source_id for source in sources):
                return None
            self._save([Source(**{**asdict(source), "active": source.id == source_id}) for source in sources])
        return self.get(source_id)

    def set_owner(self, source_id: str, owner: str) -> None:
        with self._lock:
            sources = [
                Source(**{**asdict(source), "owner": owner.strip()}) if source.id == source_id else source
                for source in self.list()
            ]
            self._save(sources)

    def set_path(self, source_id: str, raw_path: str, typed: bool = False) -> Source | None:
        """Point an archive already on the list at the folder it has moved to.

        A folder moves: a disk is remounted somewhere else, the scans are carried to a bigger
        drive, a machine is rebuilt. Until this existed there was nothing to do about it. Adding
        the folder again made a second archive of the same person, with a new random id, and
        everything read from the first one — hours of a model's reading, the classification, the
        transcriptions, the checks, the index, and the corrections the person typed themselves —
        stayed under the old id where the new archive could not see it. The list then held two
        entries with one name, one of them pointing at nothing and still drawn as healthy.

        Nothing about a reading is tied to where the folder is: a file is identified by the sha256
        of its contents, and its place is stored inside the inventory relative to the root of the
        archive. So this is all that moving one costs, and everything read stays read.
        """
        with self._lock:
            sources = self.list()
            if not any(source.id == source_id for source in sources):
                return None
            path = self.validate(raw_path, moving=source_id, typed=typed)
            self._save([
                Source(**{**asdict(source), "path": str(path), "name": path.name or str(path)})
                if source.id == source_id else source
                for source in sources
            ])  # fmt: skip
        return self.get(source_id)

    def remove(self, source_id: str) -> Source | None:
        """Take an archive off the list. What was read from it stays on disk.

        Hours of a model's reading and a person's own corrections sit behind those files, and
        "remove" is an easy thing to press. Adding the folder again brings all of it back.
        """
        with self._lock:
            sources = self.list()
            going = next((source for source in sources if source.id == source_id), None)
            if going is not None:
                self._save([source for source in sources if source.id != source_id])
        return going

    def forget(self, source_id: str) -> Path | None:
        """Put aside everything read from an archive, so it can be read again from nothing.

        The folder stays on the list and the files in it are not touched. What moves is what the
        models and the checks wrote about them: the inventory, the classification, the
        transcriptions, the materials, the boundaries, the validation and the index — the list is
        layout.READING_ARTEFACTS and is not kept here, because a second copy of it had a file in
        it that nothing on this machine can make again.

        What a person did themselves stays where it is, and so does the only copy of anything.
        Corrections and verdicts are their own words about a printed line, keyed to the file and
        not to any reading of it, and they apply again as soon as the documents are read again.
        replaced/ stays for a harder reason: it is the one copy of each reading that a later
        reading displaced, nothing rebuilds it, and moving it into forgotten-<when>/ took it out
        of sight of the one command that carries such things off the machine.

        Nothing is deleted. The work of hours and of a subscription's worth of reading goes into
        data/sources/<id>/forgotten-<when>/, and a person who pressed this by mistake can carry
        it back by hand. The path it went to is returned so the page can say where it is.
        """
        if self.get(source_id) is None:
            return None
        output = source_output_dir(self.data_dir, source_id)
        if not output.exists():
            return None
        aside = output / f"forgotten-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
        moved = False
        with self._lock:
            for name in READING_ARTEFACTS:
                item = output / name
                if item.exists():
                    aside.mkdir(parents=True, exist_ok=True)
                    item.rename(aside / name)
                    moved = True
            from epicrisis.index.build import index_path  # here, so the registry stays import-light

            index = index_path(self.data_dir, source_id)
            if index.exists():
                aside.mkdir(parents=True, exist_ok=True)
                index.rename(aside / index.name)
                moved = True
        return aside if moved else None

    def roots(self) -> list[Path]:
        """The folders an archive may be added from, resolved.

        The home of whoever runs this, the folder the instance works in, and the folder that
        holds it — an archive kept beside the instance is the usual layout. Anything else is
        named in EPICRISIS_ARCHIVE_ROOT, for scans that live on a disk of their own.
        """
        here = [Path.home(), self.data_dir.parent, self.data_dir.parent.parent]
        named = os.environ.get(ARCHIVE_ROOT_VARIABLE, "").strip()
        # A list, like PATH. It held one folder, so a person with their mother's archive on this
        # machine and their father's on a stick could not reach both through the picker however
        # they set it.
        here += [Path(one).expanduser() for one in named.split(os.pathsep) if one.strip()]
        out: list[Path] = []
        for folder in here:
            try:
                resolved = folder.resolve()
            except OSError:
                continue
            # A folder that could never be added is not a folder to offer for browsing. /root is
            # both the home of whoever runs this and a system folder of the server, so it stood in
            # this list and was refused by validate() at the same time: one rule saying two things.
            if belongs_to_the_server(resolved):
                continue
            if resolved not in out:
                out.append(resolved)
        return out

    def validate(self, raw_path: str, moving: str = "", typed: bool = False) -> Path:
        """The resolved folder path if it can be added; raises SourceError otherwise.

        `moving` is the archive being pointed at a new folder, which is then not compared with
        itself: an archive re-pointed at its own folder, or at one inside the old one, is a person
        saying where their documents are now and not a second archive overlapping the first.

        `typed` says the path came from somebody typing it at the command line rather than from a
        page of this dashboard. Every other check here still applies — a system folder is still a
        system folder, and two archives still may not contain one another — but the list of folders
        a picker may wander in does not: see ARCHIVE_ROOT_VARIABLE above for why that list guards
        the picker and not the person.
        """
        raw_path = raw_path.strip()
        if not raw_path:
            raise SourceError("Enter a folder path.")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            raise SourceError("Use an absolute path, starting with /.")
        path = path.resolve()
        if not path.is_dir():
            raise SourceError("No such folder on this server.")
        if not os.access(path, os.R_OK | os.X_OK):
            raise SourceError("The server cannot read this folder.")
        if self.data_dir.is_relative_to(path):
            raise SourceError("This folder contains Epicrisis's own data folder. Add a folder inside it.")
        if path.is_relative_to(self.data_dir / OUTPUT_DIR_NAME):
            raise SourceError("This is Epicrisis's own output folder.")
        for source in self.list():
            if source.id == moving:
                continue
            other = Path(source.path)
            if other == path:
                raise SourceError("This folder is already added.")
            # One archive inside another would give the same documents two owners.
            if path.is_relative_to(other) or other.is_relative_to(path):
                raise SourceError(
                    f"This folder and the archive of {source.whose} contain one another. "
                    "Each archive needs a folder of its own, beside the others rather than inside them."
                )
        if belongs_to_the_server(path):
            raise SourceError("This is a system folder of the server, not a folder of documents.")
        allowed = self.roots()
        if not typed and not allowed:
            # Nothing on this machine may be added from a page, because there is nowhere this
            # instance would offer: the home of the account it runs as and both folders around its
            # data folder are the server's own. Said as its own sentence, because the one below it
            # reads "Archives are added from ." over an empty list — an instruction with the place
            # missing out of it, given to somebody who has just been refused.
            raise SourceError(
                "No folder of this server can be added from a page: the places this instance would "
                "offer — the home of the account it runs as, and the folders around its data folder "
                "— all belong to the server itself. A folder of documents is added by typing it out: "
                + run('sources add "<the folder of documents>" --owner "<whose records these are>"', self.data_dir)
                + f". It is only ever read. To have this page offer a folder instead, set "
                  f"{ARCHIVE_ROOT_VARIABLE} to it before starting the server; several folders are "
                  f'separated by "{os.pathsep}".'
            )  # fmt: skip
        if not typed and not any(path.is_relative_to(root) for root in allowed):
            # With --data-dir: the line is typed in a shell standing anywhere, and without it
            # "data" means a folder beside the person, which is some other instance or none at
            # all — the archive would be added where no server of theirs reads it.
            by_typing_it = run(f'sources add "{path}" --owner "<whose records these are>"', self.data_dir)
            raise SourceError(
                "Archives are added from " + " or ".join(str(root) for root in allowed)
                + f'. A folder anywhere else — a disk of scans of its own — is added by typing it: '
                  f'{by_typing_it}. '
                  f'It is only ever read, there as here. To have this page offer that disk too, set '
                  f'{ARCHIVE_ROOT_VARIABLE} to it before starting the server; several folders are '
                  f'separated by "{os.pathsep}".'
            )
        return path

    def _save(self, sources: list[Source]) -> None:
        """Written whole and renamed into place, with the one it replaces kept beside it.

        This file is the only thing that ties a person's folders to everything read from them:
        the id in it is what names the output folder and the index. Four fields per archive, and
        losing them costs the hours of reading behind those folders — so the last version that
        was whole stays as sources.json.previous, and a person whose file was cut off mid-write
        has something to copy back rather than a list to reconstruct from folder names.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.file.exists():
            copy_whole(self.file, self.file.with_name(self.file.name + ".previous"))
        write_whole(self.file, json.dumps([asdict(source) for source in sources], ensure_ascii=False, indent=2) + "\n")


def showing(data_dir) -> Source | None:
    """The archive this instance is showing, for callers that hold no registry of their own.

    Which archive is active is decided in one place — SourceRegistry.active — and this is how a
    command line, an MCP call or a page asks it without each building a registry and each
    handling "there is none yet" its own way. The registry is built fresh every time on purpose:
    the archive can be switched on the dashboard while a server is running.
    """
    return SourceRegistry(Path(data_dir)).active()
