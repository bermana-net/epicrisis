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
from epicrisis.runs import put_in_place, temporary_name
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

OUTPUT_DIR_NAME = "sources"


# Folders that belong to the server rather than to a person: a scan of them reads thousands of
# files and finds no documents. Their insides count too - /usr/share is as much a system folder
# as /usr. "/" is refused as itself, but not as everyone's parent.
SYSTEM_FOLDERS = {"/etc", "/bin", "/sbin", "/lib", "/lib64", "/usr", "/var", "/boot", "/opt", "/srv", "/root"}
# Where archives may be kept. The dashboard has no login because it listens on this machine only,
# so what it can be made to read is worth keeping to the places a person keeps documents: their
# home, and the folder this instance already works in. EPICRISIS_ARCHIVE_ROOT adds another, for
# an instance whose scans sit on a mounted disk.
ARCHIVE_ROOT_VARIABLE = "EPICRISIS_ARCHIVE_ROOT"
RUNTIME_FOLDERS = ("/proc", "/sys", "/dev", "/run")

# What a reading of an archive leaves behind, and therefore what starting again puts aside.
# corrections.jsonl is not here: a correction is the person's own, keyed to the file's whole
# sha256 and to the line as printed, and it applies again to the next reading of the same file.
READING_ARTEFACTS = (
    "inventory.jsonl", "inventory.status.json", "classify.jsonl", "extracted", "rechecked",
    "validation.json", "date_search.jsonl", "ledger.jsonl",
)


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


def source_output_dir(data_dir: Path, source_id: str) -> Path:
    return data_dir / OUTPUT_DIR_NAME / source_id


class SourceRegistry:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()
        self.file = self.data_dir / "sources.json"
        self._lock = threading.Lock()

    def list(self) -> list[Source]:
        if not self.file.exists():
            return []
        return [Source(**entry) for entry in json.loads(self.file.read_text(encoding="utf-8"))]

    def get(self, source_id: str) -> Source | None:
        return next((source for source in self.list() if source.id == source_id), None)

    def add(self, raw_path: str, owner: str = "") -> Source:
        with self._lock:
            path = self.validate(raw_path)
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
        sources = self.list()
        return next((source for source in sources if source.active), sources[0] if sources else None)

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
        transcriptions, the validation and the index. Corrections stay where they are, because
        they are the person's own words about a printed line, keyed to the file and not to any
        reading of it, and they apply again as soon as the documents are read again.

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
        if named:
            here.append(Path(named).expanduser())
        out: list[Path] = []
        for folder in here:
            try:
                resolved = folder.resolve()
            except OSError:
                continue
            if resolved not in out:
                out.append(resolved)
        return out

    def validate(self, raw_path: str) -> Path:
        """The resolved folder path if it can be added; raises SourceError otherwise."""
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
            other = Path(source.path)
            if other == path:
                raise SourceError("This folder is already added.")
            # One archive inside another would give the same documents two owners.
            if path.is_relative_to(other) or other.is_relative_to(path):
                raise SourceError(
                    f"This folder and the archive of {source.whose} contain one another. "
                    "Each archive needs a folder of its own, beside the others rather than inside them."
                )
        if str(path) == "/" or any(path.is_relative_to(folder) for folder in SYSTEM_FOLDERS | set(RUNTIME_FOLDERS)):
            raise SourceError("This is a system folder of the server, not a folder of documents.")
        allowed = self.roots()
        if not any(path.is_relative_to(root) for root in allowed):
            raise SourceError(
                "Archives are added from " + " or ".join(str(root) for root in allowed)
                + f". Set {ARCHIVE_ROOT_VARIABLE} to add one from somewhere else."
            )
        return path

    def _save(self, sources: list[Source]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary = temporary_name(self.file)
        temporary.write_text(
            json.dumps([asdict(source) for source in sources], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        put_in_place(temporary, self.file)
