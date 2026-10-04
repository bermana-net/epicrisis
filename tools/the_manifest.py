"""The one writer of docs/images/taken-from-the-demo.json, the manifest of published pictures.

    from the_manifest import declare

That file declares every picture and PDF this project publishes, by hash, and
tools/nothing-of-yours.py refuses to publish anything it cannot find in it — reading every version
of every picture the history holds and not only the file standing in the tree. So a hash dropped
out of this file is not a note mislaid: it is a picture already published, in every clone of this
repository, that the guard now refuses and nobody can unpublish, and no later run can work out
what the hash was. Putting one such loss right meant restoring 26 hashes by hand.

Three scripts print pictures that are published, and each of them wrote the whole file itself:

  * docs/take-the-pictures.py ended by setting "pictures" to exactly what that run photographed,
    which crossed out the three entries the one-pager script writes into the same list — the two
    sheet previews and the chart on the clinics sheet — and did not keep their hashes under
    "earlier" either, because that loop walks only the names the run took. It dropped "how", the
    note written by hand about the set published before this check existed, for the same reason.
  * tools/make-one-pager.py and tools/make-og-image.py each carried their own copy of the rule
    about a displaced hash, and wrote the file with a different indent from the page shooter, so a
    run of one reformatted everything the others had written.

This is the only writer now. A caller says which names it answers for, where each of them lives,
and which of them it wrote this time; everything else in the file — another writer's entries and
their hashes, the notes written by hand, every version listed under "earlier" — is carried through
exactly as it stands. Nothing here ever removes a hash: a name leaving the tree takes its hash
into "earlier" instead, because the bytes stay in the history and stay published.
"""

import hashlib
import json
import pathlib

# Where the manifest lives, so that the three callers cannot disagree about it.
MANIFEST = pathlib.Path(__file__).resolve().parent.parent / "docs" / "images" / "taken-from-the-demo.json"

PICTURES = "pictures"
NOT_OF_A_PAGE = "not_of_a_page"
EARLIER = "earlier"


class CannotRead(ValueError):
    """Why the manifest must not be written: it cannot be read first, so a write would lose it."""


def declare(
    manifest: pathlib.Path = MANIFEST,
    *,
    pictures: dict[str, pathlib.Path] | None = None,
    not_of_a_page: dict[str, pathlib.Path] | None = None,
    made: set[str] | None = None,
    of: dict | None = None,
) -> list[str]:
    """Declare what one run printed, and leave everything else in the manifest alone.

    `pictures` and `not_of_a_page` are everything this caller answers for: the name each file is
    declared under — a bare name for a picture of a page, the path the repository spells it with
    for a file that is not one — against the file on disk it is the hash of. `made` is the names
    this run actually wrote; leave it out when that is all of them.

    A name handed over and written this run is hashed and declared. A name handed over whose file
    this run did not write is left exactly as the manifest has it: its bytes are deliberately not
    read, because a page of somebody's own archive dropped into docs/images under the name of a
    shot that could not be taken would otherwise be hashed and blessed by the run that skipped it.
    A name handed over whose file is gone from the tree keeps its hash under "earlier" and leaves
    the list it was in. A name nobody handed over is not touched at all.

    `of` says of whom the pictures are and is what the guard checks before it trusts any of this,
    so only a caller that can say it — the page shooter, which reads the demo's own marker — may
    bring the file into being. Returns the lines worth printing about what changed.
    """
    standing = _read(manifest, may_create=of is not None)
    if of is not None:
        standing["of"] = of
    scope = [(name, path, PICTURES) for name, path in (pictures or {}).items()]
    scope += [(name, path, NOT_OF_A_PAGE) for name, path in (not_of_a_page or {}).items()]

    said = []
    for name, path, asked in scope:
        table = standing.setdefault(_home(standing, name, asked), {})
        was = table.get(name)
        if not path.exists():
            if was is None:
                continue
            _remember(standing, name, was)
            del table[name]
            said.append(f'{name} is gone from the tree; its hash is now declared under "{EARLIER}", '
                        "because the version published before it stays in the history")  # fmt: skip
            continue
        if made is not None and name not in made:
            continue
        hashed = hashlib.sha256(path.read_bytes()).hexdigest()
        if hashed == was:
            continue
        if was is None:
            said.append(f"{name} is declared for the first time")
        else:
            _remember(standing, name, was)
            said.append(f'{name} has changed; the version it displaces is now declared under "{EARLIER}"')
        table[name] = hashed

    # One shape for the file, whoever wrote last. The three writers used two different indents
    # between them, so a run of one reformatted every line the others had written and the change
    # worth reading was buried in a diff of the whole manifest.
    written = json.dumps(standing, indent=1, ensure_ascii=False) + "\n"
    if not manifest.exists() or manifest.read_text(encoding="utf-8") != written:
        _write(manifest, written)
    return said


def _read(manifest: pathlib.Path, *, may_create: bool) -> dict:
    """What the manifest says now, or why nothing may be written over it."""
    if manifest.exists():
        try:
            return json.loads(manifest.read_text(encoding="utf-8"))
        # A manifest half-edited by hand used to be read as nothing at all by the page shooter,
        # which then wrote a file holding one run's pictures and none of the 73 hashes the broken
        # one still had in it. The hashes are here or nowhere, so a file that cannot be read is
        # left where it is for somebody to mend.
        except ValueError as broken:
            raise CannotRead(f"{manifest} cannot be read ({broken}). Every hash this project "
                             "publishes is in that file and nowhere else, so nothing was written "
                             "over it; mend it by hand and run this again.") from broken  # fmt: skip
    if not may_create:
        raise CannotRead(f"There is no {manifest}, and what was printed is declared nowhere. "
                         "Only docs/take-the-pictures.py may make it, because the guard refuses a "
                         "manifest that does not say whose instance the pictures are of.")  # fmt: skip
    return {}


def _home(standing: dict, name: str, asked: str) -> str:
    """Which of the two lists a name belongs in: the one it is already in, or the one asked for.

    The guard reads both lists for the file standing in the tree, but a name that moved from one
    to the other from run to run would leave its old entry behind under the other heading, and a
    hash in two places is a hash that can go stale in one of them.
    """
    for table in (PICTURES, NOT_OF_A_PAGE):
        if name in standing.get(table, {}):
            return table
    return asked


def _remember(standing: dict, name: str, hashed: str) -> None:
    """Keep a hash that is leaving the main list, because the bytes it names stay published."""
    versions = standing.setdefault(EARLIER, {}).setdefault(name, [])
    if hashed not in versions:
        versions.append(hashed)


def _write(manifest: pathlib.Path, written: str) -> None:
    """Replace the file whole, never write into it.

    Every hash this project publishes is in this one file and in no other place: a write that
    fails halfway through would leave a manifest nothing can mend, so the old one stands until the
    new one is complete.
    """
    manifest.parent.mkdir(parents=True, exist_ok=True)
    beside = manifest.with_name(manifest.name + ".writing")
    beside.write_text(written, encoding="utf-8")
    beside.replace(manifest)
