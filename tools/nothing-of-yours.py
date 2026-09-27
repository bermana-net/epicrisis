"""Check that a repository holds nothing out of somebody's archive, before it is published.

    uv run python tools/nothing-of-yours.py --data-dir data

It reads the data directory of a live instance — the names of the people whose archives these are,
the institutions that treated them, the names of their files and the hashes of them, the lines of
diagnosis and the medications printed on their documents, and the text of those documents line by
line — and looks for each of those in this repository: in every tracked file, and in every commit
that has ever been made, because a file deleted in the tip is still published in the history.

What it does not look for is what identifies nobody. The title of a document and the name of a
department are the names of a kind of form and a kind of room: asked for, they matched this
repository twenty-three times, every one of them a phrase the demo of a program that reads such
forms has to be free to print.

It also looks for the things that are secret by nature: the code's own secret, the secret that
stands in the served path, keys and tokens by their shape.

Nothing it finds is printed. A phrase out of an archive is exactly what must not be written into
a terminal, a log or an issue, so the report says what kind of thing matched and where, and the
person who ran it goes and looks. It answers 0 when the repository is clean and 1 when it is not,
which is what makes it usable as a hook before a push.

Whole phrases, not words: a document titled "Full blood count" shares every word with the tests
of this project, and a check that shouts about "blood" is a check nobody runs twice.
"""

import argparse
import hashlib
import json
import pathlib
import re
import sqlite3
import subprocess
import sys
import unicodedata

SHORTEST = 9  # a phrase shorter than this is a word, and a word is not a leak
# How long a line out of a document has to be before it counts as somebody's rather than any
# form's. Short lines are headings and labels that every form of that kind prints; a line this long
# carries a sentence, and a sentence out of a medical record belongs to one person.
A_LINE_OF_A_DOCUMENT = 40
# And how much of it has to be letters. Forms are full of rules, dots and boxes drawn in ASCII.
WORDS_OF_A_LINE = 25
# Phrases a person publishes on purpose — an author's own name in a licence and a copyright line.
# One per line, "#" for a comment. Whoever writes a name in here is saying they mean to publish it.
ALLOWED_FILE = "published-on-purpose.txt"
# Strings that have the shape of a secret and are not one: a fixture in the tests, spelled out
# here in full so that nothing near it passes. A guard that is known to be wrong about the same
# thing at every push is a guard somebody runs with --no-verify on the day it is right.
NOT_A_SECRET = ("sk-ant-not-a-real-key", "sk-ant-no-such-key",
                # The one the tests of this guard plant in a repository of their own, to see whether
                # it is found. Spelled out here in full, as the two above are: a fixture that makes
                # the guard shout at its own test suite teaches the person running it to skim.
                "sk-ant-invented-key-abcdefghijklmnop")  # fmt: skip
NEVER_PUBLISHED = (
    ("an Anthropic key", r"sk-ant-[A-Za-z0-9_-]{8,}"),
    ("a GitHub token", r"gh[pousr]_[A-Za-z0-9]{16,}"),
    ("a private key", r"-----BEGIN [A-Z ]*PRIVATE KEY"),
    ("an AWS key", r"AKIA[0-9A-Z]{16}"),
    ("a password in a URL", r"://[^/\s:@]+:[^/\s:@]+@"),
)
SECRET_FILES = (
    ("the code's secret", "/etc/epicrisis/mcp-totp"),
    ("the secret in the served path", "/etc/epicrisis/mcp-token"),
    ("an environment file", ".env"),
)


def _real_matches(shape: str, text: str) -> bool:
    """Whether anything of that shape is here that is not one of the known fixtures."""
    return any(found.group(0) not in NOT_A_SECRET for found in re.finditer(shape, text, re.IGNORECASE))


def _letters(text: str) -> int:
    """How much of this line is letters rather than the furniture a form is drawn with."""
    return sum(1 for letter in text if letter.isalpha())


def fold(text: str) -> str:
    """One spelling for comparing: no case, no accents, one space where there were several."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", str(text)).casefold()).strip()


def out_of_the_archive(data_dir: pathlib.Path) -> dict[str, str]:
    """Every phrase that points at a person or a place, and what kind of thing it is.

    Not everything written in an archive is somebody's: "Creatinine", "Общий анализ крови" and
    "Full blood count" are the words every form of that kind prints, and they belong in the code
    and in the demo of a program that reads such forms. A check that shouts about those is a
    check nobody runs twice, and a check nobody runs is worth nothing. So what is looked for is
    what identifies: the people, the institutions that treated them, the folders and files their
    scans live in, and the hashes of those files.
    """
    phrases: dict[str, str] = {}
    sources = data_dir / "sources.json"
    if sources.exists():
        for source in json.loads(sources.read_text(encoding="utf-8")):
            for field, what in (("owner", "the name of a person"), ("name", "the name of an archive")):
                whole = fold(source.get(field) or "")
                phrases[whole] = what
                for part in whole.split():
                    if len(part) >= 5:
                        phrases[part] = what  # a surname on its own is the name of a person
            phrases[fold(pathlib.Path(source.get("path") or "").name)] = "the name of an archive's folder"
    for index in sorted(data_dir.glob("index*.sqlite")):
        with sqlite3.connect(f"file:{index}?mode=ro", uri=True) as db:
            # What is printed on somebody's documents and says who they are or what is wrong with
            # them. The first of these was here from the start and the other four were promised by
            # the sentence at the top of this file and never asked for: a department, the title of a
            # report, a line of diagnosis, the name of a drug — pasted into a test or a docstring
            # while debugging, any of them walks straight past a check that then prints "Clean".
            # A line of diagnosis is the plainest statement of an illness a person's archive holds.
            #
            # Not the title of a document and not the department, though the sentence at the top of
            # this file promised both. Neither identifies anybody: a title is the name of a *kind* of
            # form and a department is the name of a kind of room. Asked for, they reported
            # twenty-three matches on this repository, every one of them "Full blood count", "Анализ
            # мочи", "Bioquímica", "Лабораторія", "Consultation" — the words the demo of a program
            # that reads such forms must be free to print. Where a department does name a place, the
            # place is already in this list, from the institution beside it. A guard that shouts at
            # the generic is a guard somebody pushes past with --no-verify on the day it is right,
            # and that is a worse failure than the one it was guarding against.
            for what, sql in (
                ("the name of an institution", "SELECT DISTINCT provider FROM documents WHERE provider IS NOT NULL"),
                ("a line of diagnosis", "SELECT DISTINCT text FROM diagnoses"),
                ("the name of a medication", "SELECT DISTINCT text FROM medications"),
            ):  # fmt: skip
                for (value,) in db.execute(sql):
                    phrases[fold(value)] = what
            # And the text of the documents themselves, line by line, where a line is long enough to
            # be somebody's rather than any form's. This is where a paste comes from: a person
            # debugging copies the line that puzzles them, and that line is a sentence out of a
            # medical record. Whole sections are no use to compare — nobody pastes a page — so it
            # is the lines.
            for table in ("sections", "page_texts"):
                for (value,) in db.execute(f"SELECT text FROM {table} WHERE text IS NOT NULL"):
                    for line in str(value).splitlines():
                        said = fold(line)
                        # Letters, and enough of them. A row of dashes is forty characters long and
                        # is nobody's: two of them matched the font licences of this repository and
                        # one matched its own history, which is a guard being wrong twice in its
                        # first run and teaching the reader to skim the report.
                        if len(said) >= A_LINE_OF_A_DOCUMENT and _letters(said) >= WORDS_OF_A_LINE:
                            phrases.setdefault(said, "a line of a document")
            for (value,) in db.execute("SELECT DISTINCT sha256 FROM files"):
                phrases[fold(value)] = "the hash of a file in an archive"
            for (value,) in db.execute("SELECT DISTINCT path FROM files WHERE path IS NOT NULL"):
                phrases[fold(pathlib.Path(value).name)] = "the name of a file in an archive"
    phrases.pop("", None)
    # What was published on purpose, from wherever it is kept: beside the data directory, as an
    # instance keeps it, and beside this repository, as somebody checking out a copy would. Looked
    # for in one place only, an instance whose data lives elsewhere simply never found the list and
    # reported things its owner had already decided to publish.
    allowed = set()
    for place in (data_dir, data_dir.parent, pathlib.Path.cwd()):
        found = place / ALLOWED_FILE
        if found.exists():
            allowed |= {fold(line) for line in found.read_text(encoding="utf-8").splitlines()
                        if line.strip() and not line.startswith("#")}  # fmt: skip
    return {phrase: what for phrase, what in phrases.items()
            if len(phrase) >= SHORTEST and phrase not in allowed}  # fmt: skip


def published(repo: pathlib.Path) -> tuple[dict[pathlib.Path, str], str]:
    """What this repository shows today, and everything it has ever shown."""
    tracked = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, check=True)
    now = {}
    for name in tracked.stdout.split("\n"):
        file = repo / name
        if not name or not file.is_file() or file.suffix in (".png", ".jpg", ".jpeg", ".ico", ".woff2", ".pdf"):
            continue
        now[file] = fold(file.read_text(encoding="utf-8", errors="replace"))
    # check=True, like the call above it. This one was check=False with its return code unread, so
    # a git that failed for any reason left history empty, nobody looked at a single commit, and the
    # last line of this program still said "in no commit" — the one sentence a person reads before
    # pushing. The asymmetry stood in two lines beside each other.
    history = subprocess.run(["git", "-C", str(repo), "log", "--all", "-p", "--no-color"],
                             capture_output=True, text=True, check=True)  # fmt: skip
    return now, fold(history.stdout)


def _secrets_in(text: str) -> set[str]:
    """What is secret in a file of secrets: the value of a NAME=value line, or the whole of a line.

    Not the name. An environment file is written NAME=value, and a pattern that took a whole line as
    one token compared the wrong thing twice over: the secret itself, which is what somebody would
    paste somewhere by accident, was never looked for at all, and the name — ANTHROPIC_API_KEY,
    which this project prints in its README and on its settings page — matched, so the guard refused
    to publish its own repository over a word it had written itself.
    """
    pieces: set[str] = set()
    for line in text.splitlines():
        said = line.split("=", 1)[1] if "=" in line else line
        pieces |= set(re.findall(r"[A-Za-z0-9+/_-]{16,}", said))
    return pieces


def secrets_of_this_server(repo: pathlib.Path, everything: str, data_dir: pathlib.Path | None = None) -> list[str]:
    """The secrets this machine actually holds, looked for whole and hashed.

    Beside the repository and beside the data directory both. An environment file is read from
    beside the data directory first — engines.key_for looks there, and so do the pages that name it
    — and an instance that keeps its data elsewhere had its key compared against nothing at all.
    """
    trouble = []
    beside = [repo] + ([data_dir, data_dir.parent] if data_dir else [])
    for what, path in SECRET_FILES:
        here = pathlib.Path(path)
        file = next((one for one in ([here] if here.is_absolute() else [place / path for place in beside])
                     if one.exists()), None)  # fmt: skip
        if file is None:
            continue
        for piece in _secrets_in(file.read_text(encoding="utf-8", errors="replace")):
            if fold(piece) in everything or hashlib.sha256(piece.encode()).hexdigest() in everything:
                trouble.append(f"{what} appears in this repository")
    return trouble


PICTURES = "docs/images"
TAKEN_FILE = "taken-from-the-demo.json"
# Where that file lists the versions of a picture that earlier commits hold and the tip does not.
# A picture replaced keeps its name and leaves its bytes in the history; the run that replaced it
# writes the hash it displaced in here, and a version in no list at all is refused below.
EARLIER = "earlier"
# What counts as a picture. A page of somebody's archive is a page of it in any format.
PICTURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".avif", ".heic",
                    # A page of somebody's archive is a page of it in any format, and two formats
                    # fell between the two hands of this tool: cut out of the text check because
                    # they do not read as text, and never named here, so nothing looked at them at
                    # all. One of them is the 96 KB PDF the site offers for download, whose pages
                    # are rasterised images inside it — the very thing this half was written for.
                    ".pdf", ".ico")  # fmt: skip


def pictures_of_nobody(repo: pathlib.Path) -> list[str]:
    """That every published picture was taken of the demo, and not of anybody's own archive.

    This is the hole every other check here leaves open. A picture of a page carries the name at
    its top, the institution, the date and the whole table of results, and none of it is text: the
    phrases out of an archive can all be absent from this repository while a page of it hangs in
    the folder that becomes the site. So the script that takes them refuses an instance whose
    people are real and writes down what it took; anything the repository publishes that it did
    not take is refused here, by its hash, without the file ever being read for content.

    Every image this repository tracks, anywhere in it, and every version of every image any
    commit holds. The first version of this looked at *.png in one folder, which four different
    things walked past: a .jpg beside them, a folder deeper, an image somewhere else in the tree,
    and an image deleted from the tip after it had been published once — the case the whole of
    this tool was written for, since a file removed today is still published in the history.

    And the version in the tip is not the only version published. A picture *replaced* rather
    than deleted leaves the picture it replaced in the history, under the same name, reachable by
    anybody who clones this: twenty such blobs were in here, two of them in commits already
    pushed, and not one of them was ever compared with anything — the tip was hashed, and the
    history was only asked whether a name had disappeared from it. So every version is hashed and
    matched, and a version nothing declares is refused by name, with what to do about it.
    """
    known, earlier, said = _manifest(repo)
    if said:
        return said
    trouble = []
    tracked = set(_tracked_images(repo))
    in_the_tip = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in tracked}
    for name in sorted(tracked):
        # Two lists, because there are two kinds of image here and only one of them is a risk.
        # A picture taken of a page has to come from a run against invented people. A mark — the
        # icon, the logo — is not a picture of anybody's page at all, and is named in the
        # manifest with its hash so that it is still pinned: nothing changes underneath it, and
        # nothing new arrives calling itself a mark.
        if _declared(known, name, in_the_tip[name]):
            continue
        was = "is not one the demo run took, and is not a mark this repository declares" \
            if not _named(known, name) else "has changed since"
        trouble.append(f"the picture {name} {was}")
    # A file whose pages are pictures cannot be read for phrases and cannot be matched against the
    # pictures the demo run took, because it re-encodes them. What it can be is declared: it is
    # made from files in this repository by a script in it, and the hash says nobody has put
    # anything else there since.
    for name, when in _images_ever(repo).items():
        if name not in tracked:
            trouble.append(f"the picture {name} was published in {when} and is not in the tip; "
                           "what a commit showed once stays shown")  # fmt: skip
    for name, blob, hashed in _every_version(repo):
        if _declared(known, name, hashed) or _declared(earlier, name, hashed):
            continue
        if in_the_tip.get(name) == hashed:
            continue  # the version standing today, already answered for above and not twice
        trouble.append(
            f"the picture {name} has a version in the history that nothing declares — the one in "
            f"commit {_a_commit_showing(repo, blob)}, sha256 {hashed}. Look at it — "
            f"git -C {repo} cat-file blob {blob} > /tmp/{pathlib.PurePosixPath(name).name} — and "
            f'if it is a picture of the demo, or one of the files this repository makes of itself, '
            f'add that sha256 to "{EARLIER}" under "{name}" in {PICTURES}/{TAKEN_FILE}. If it is a '
            "page of somebody's archive, this history is not publishable at all: publish the state "
            "and not the history, which is how the public repository was made in the first place."
        )
    return trouble


def _manifest(repo: pathlib.Path) -> tuple[dict, dict, list[str]]:
    """What the demo run wrote down, what earlier runs wrote down, or why none of it can be trusted."""
    taken = repo / PICTURES / TAKEN_FILE
    if not any(_tracked_images(repo)):
        return {}, {}, []
    if not taken.exists():
        return {}, {}, [f"this repository publishes pictures and has no {PICTURES}/{TAKEN_FILE} "
                        "saying they were taken of a demo"]  # fmt: skip
    try:
        written = json.loads(taken.read_text(encoding="utf-8"))
    except ValueError:
        return {}, {}, [f"{TAKEN_FILE} cannot be read"]
    if not written.get("of", {}).get("invented"):
        return {}, {}, [f"{TAKEN_FILE} does not say the instance photographed was a demo"]
    standing = {**written.get("pictures", {}), **written.get("not_of_a_page", {})}
    return standing, written.get(EARLIER, {}), []


def _named(table: dict, name: str) -> bool:
    """Whether the manifest says anything at all about a picture of this name."""
    return name in table or pathlib.PurePosixPath(name).name in table


def _declared(table: dict, name: str, hashed: str) -> bool:
    """Whether this exact version of this picture is one the manifest declares.

    By the path as the repository spells it and by the bare name both, because a picture is
    declared under one or the other: the pictures of the demo by name, the marks and the sheets
    this repository makes of itself by path. A version of one is a string, the versions an earlier
    run left behind are a list, and either answers for a version that matches it.
    """
    for key in (name, pathlib.PurePosixPath(name).name):
        said = table.get(key)
        if said == hashed or (isinstance(said, (list, tuple)) and hashed in said):
            return True
    return False


def _tracked_images(repo: pathlib.Path) -> list[str]:
    """Every image this repository tracks, wherever it is."""
    listed = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, check=True)
    return [name for name in listed.stdout.split("\n")
            if name and pathlib.PurePosixPath(name).suffix.lower() in PICTURE_SUFFIXES
            and (repo / name).is_file()]  # fmt: skip


def _images_ever(repo: pathlib.Path) -> dict[str, str]:
    """Images any commit has ever held, and the commit that first showed each.

    A picture taken off the tip is still in the history and still reachable, which is the whole
    reason this tool reads the history for everything else.
    """
    seen: dict[str, str] = {}
    walked = subprocess.run(
        ["git", "-C", str(repo), "log", "--all", "--name-only", "--pretty=format:%h", "--diff-filter=AM"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    commit = ""
    for line in walked.stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        if " " not in line and "/" not in line and "." not in line:
            commit = line
        elif pathlib.PurePosixPath(line).suffix.lower() in PICTURE_SUFFIXES:
            seen.setdefault(line, commit)
    return seen


def _every_version(repo: pathlib.Path) -> list[tuple[str, str, str]]:
    """Every version of every picture the history holds: its path, its blob, and the hash of it.

    `git rev-list --objects --all` names every object anybody cloning this repository receives,
    each blob beside a path some tree filed it under. That is the list to check, and not the list
    of files in the tip: a picture replaced in a later commit is a blob of its own under the same
    name, published exactly as much as the one standing today.
    """
    listed = subprocess.run(["git", "-C", str(repo), "rev-list", "--objects", "--all"],
                            capture_output=True, text=True, check=True)  # fmt: skip
    versions = []
    for line in listed.stdout.splitlines():
        blob, _, name = line.partition(" ")
        name = name.strip()
        if name and pathlib.PurePosixPath(name).suffix.lower() in PICTURE_SUFFIXES:
            versions.append((name, blob))
    hashed = _hashes_of(repo, [blob for _name, blob in versions])
    return [(name, blob, one) for (name, blob), one in zip(versions, hashed)]


def _hashes_of(repo: pathlib.Path, blobs: list[str]) -> list[str]:
    """The sha256 of each of those objects, read out of the repository in one pass.

    One `git cat-file` for each of them is one process for each version ever published; this is
    the batch form, which answers for all of them down one pipe. Bytes, never text: a picture
    decoded as text and hashed would hash to something no manifest has ever heard of.
    """
    if not blobs:
        return []
    answered = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"],
                              input=("\n".join(blobs) + "\n").encode(), capture_output=True, check=True).stdout  # fmt: skip
    hashes, at = [], 0
    for _blob in blobs:
        end = answered.index(b"\n", at)
        head = answered[at:end].split()
        if len(head) < 3 or head[1] != b"blob":
            hashes.append("")  # "<name> missing": nothing to hash, and nothing declared answers it
            at = end + 1
            continue
        size = int(head[2])
        hashes.append(hashlib.sha256(answered[end + 1:end + 1 + size]).hexdigest())
        at = end + 1 + size + 1
    return hashes


def _a_commit_showing(repo: pathlib.Path, blob: str) -> str:
    """One commit that holds that version, so the person reading the report can go and look at it."""
    found = subprocess.run(["git", "-C", str(repo), "log", "--all", "--format=%h", "--find-object", blob, "-1"],
                           capture_output=True, text=True, check=False)  # fmt: skip
    return found.stdout.strip().split("\n")[0] or "a commit git could not name"


def look(repo: pathlib.Path, data_dir: pathlib.Path) -> list[str]:
    """Everything wrong with publishing this repository, as lines. An empty list is the answer."""
    now, history = published(repo)
    everything = history + " ".join(now.values())
    trouble = secrets_of_this_server(repo, everything, data_dir) + pictures_of_nobody(repo)
    for what, shape in NEVER_PUBLISHED:
        for file, text in now.items():
            if _real_matches(shape, text):
                trouble.append(f"{what} is in {file.relative_to(repo)}")
        if _real_matches(shape, history):
            trouble.append(f"{what} is somewhere in the history")
    phrases = out_of_the_archive(data_dir)
    for phrase, what in phrases.items():
        where = [str(file.relative_to(repo)) for file, text in now.items() if phrase in text]
        if where:
            trouble.append(f"{what} ({len(phrase)} characters) is in {', '.join(sorted(where)[:4])}")
        elif phrase in history:
            trouble.append(f"{what} ({len(phrase)} characters) is in the history but not in any file today")
    return trouble, len(phrases)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=pathlib.Path, default=pathlib.Path("."))
    parser.add_argument("--data-dir", type=pathlib.Path, default=pathlib.Path("data"))
    args = parser.parse_args(argv)
    if not (args.repo / ".git").exists():
        print(f"{args.repo} is not a git repository.", file=sys.stderr)
        return 2
    if not args.data_dir.exists():
        print(f"No data directory at {args.data_dir}: there is nothing to compare against, "
              "so this proves nothing. Point --data-dir at the instance you actually run.", file=sys.stderr)  # fmt: skip
        return 2
    trouble, checked = look(args.repo.resolve(), args.data_dir.resolve())
    if trouble:
        print(f"Do not publish. {len(trouble)} thing(s) out of the archive or secret are in this repository:",
              file=sys.stderr)  # fmt: skip
        for line in trouble:
            print(f"  - {line}", file=sys.stderr)
        print("\nNothing matched is printed here on purpose. Go and look at the files named above.", file=sys.stderr)
        return 1
    print(f"Clean: {checked} phrases out of the archive, and the secrets of this server, "
          "are in no tracked file and in no commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
