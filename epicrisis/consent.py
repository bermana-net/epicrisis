"""Confirmation that pages may be sent to a model provider, kept in data/consent.json.

A new CONSENT_VERSION asks again, so changing what the notice says requires a fresh confirmation.

Two things it is about, and the second was missing. A consent is given for a **destination** — an
instance that starts sending pages somewhere else has to be allowed to, again — and it is given for
the **archives** that were on the list when it was given. The second matters because of who is not
in the room: the person whose archive it is need not be the person holding the server. A daughter
agrees for her mother and her father, both named on the page; a year later she adds the folder of a
third person, and the pages of that third person used to go to a provider on the strength of an
agreement that never mentioned them. The machinery for "the notice changed, so ask again" already
existed; it simply did not cover the list of names the notice itself prints.

And a consent given by one press is taken back by one press. There was no way at all: not a button,
not a command, not a line of documentation — only editing this file by hand, which nothing said. A
person whose reason changes (a provider's terms, a diagnosis they think of differently, a machine
passed to somebody else) had nothing to press, and with `update` in a crontab that is the difference
between "it no longer sends" and "it sends every night".
"""

import json

from epicrisis import layout
from epicrisis.runs import write_whole
from datetime import UTC, datetime
from pathlib import Path

# 3: the entry now records which archives were on the list when it was given, and the notice says
# so. Every instance is asked once more, which is what a version is for: the words changed, and so
# did what the agreement covers.
CONSENT_VERSION = 3


def _path(data_dir: Path) -> Path:
    return data_dir / layout.CONSENT


def archives_now(data_dir: Path) -> list[str]:
    """The archives on the list right now, by id. A list that cannot be read is no list."""
    from epicrisis.sources import SourceRegistry
    from epicrisis.state import Unreadable

    try:
        return sorted(source.id for source in SourceRegistry(data_dir).list())
    except Unreadable:
        return []


def not_covered(data_dir: Path, backend: str) -> list[str]:
    """Archives on the list that this consent was not given for, by id.

    Asked by has_consent, and by the page, which names them. Nothing is sent out of an archive
    added since the agreement until the person says so about that archive too.
    """
    entry = _entry(data_dir, backend)
    if not entry:
        return []
    covered = set(entry.get("archives") or ())
    return [source_id for source_id in archives_now(data_dir) if source_id not in covered]


def _entry(data_dir: Path, backend: str) -> dict | None:
    try:
        entries = json.loads(_path(data_dir).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (ValueError, OSError):
        # A file that will not parse is not a consent. It fails in the safe direction — nothing is
        # sent — but it must fail as an answer and not as a traceback: every page of the interface
        # asks this question, so an exception here takes the whole interface down.
        return None
    entry = entries.get(backend) if isinstance(entries, dict) else None
    return entry if isinstance(entry, dict) else None


def has_consent(data_dir: Path, backend: str) -> bool:
    """Whether pages may be sent to this destination, out of every archive on the list now.

    The archives are checked here rather than by the caller, because there are nine callers and a
    parameter one of them forgot would be a page going to a provider unasked.
    """
    entry = _entry(data_dir, backend)
    if not entry or entry.get("version") != CONSENT_VERSION:
        return False
    return not not_covered(data_dir, backend)


def record_consent(data_dir: Path, backend: str) -> None:
    """Write down that this person agreed, for this engine, to this version of the notice.

    A file that will not parse is started again from nothing rather than raised over. The reader
    beside this already refuses to be taken down by one (it answers "nobody has consented", which
    fails in the safe direction), and the writer did not — so a truncated consent.json made the "I
    agree" button answer with the words Internal Server Error, for ever. That button is the one
    door to every reading this program does: behind it, the person could no longer have a single
    document read, and nothing anywhere named the file or said it could be moved aside.

    What is lost by starting again is the date of an earlier agreement, and the agreement of the
    other engine, which will be asked for again before anything is sent. Nothing is lost that
    would let a page go to a model unasked.
    """
    path = _path(data_dir)
    try:
        entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(entries, dict):
            entries = {}
    except (ValueError, OSError):
        entries = {}
    entries[backend] = {"version": CONSENT_VERSION,
                        "accepted_at": datetime.now(UTC).isoformat(timespec="seconds"),
                        # Which archives it was given for. The page prints their names in the
                        # sentence a person reads before pressing, and until now nothing kept them.
                        "archives": archives_now(data_dir)}  # fmt: skip
    path.parent.mkdir(parents=True, exist_ok=True)
    write_whole(path, json.dumps(entries, indent=2) + "\n")


def withdraw_consent(data_dir: Path, backend: str) -> None:
    """Take it back. Given by one press, taken back by one press.

    The entry goes rather than being marked: has_consent is asked by every page, every command and
    every step, and the safe answer to "is there an agreement" is the absence of one. What is kept
    is nothing at all about this destination, so the next agreement is a fresh one with its own date
    and its own list of archives. A record of having once agreed is not worth the risk of a reader
    somewhere treating a withdrawn agreement as an agreement.
    """
    path = _path(data_dir)
    try:
        entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(entries, dict):
            entries = {}
    except (ValueError, OSError):
        entries = {}
    if entries.pop(backend, None) is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_whole(path, json.dumps(entries, indent=2) + "\n")
