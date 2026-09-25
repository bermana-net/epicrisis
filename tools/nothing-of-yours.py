"""Check that a repository holds nothing out of somebody's archive, before it is published.

    uv run python tools/nothing-of-yours.py --data-dir data

It reads the data directory of a live instance — the names of the people whose archives these
are, the institutions, departments and titles printed on their documents, the names of their
files and the hashes of them — and looks for each of those in this repository: in every tracked
file, and in every commit that has ever been made, because a file deleted in the tip is still
published in the history.

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
# Phrases a person publishes on purpose — an author's own name in a licence and a copyright line.
# One per line, "#" for a comment. Whoever writes a name in here is saying they mean to publish it.
ALLOWED_FILE = "published-on-purpose.txt"
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
            for (value,) in db.execute("SELECT DISTINCT provider FROM documents WHERE provider IS NOT NULL"):
                phrases[fold(value)] = "the name of an institution"
            for (value,) in db.execute("SELECT DISTINCT sha256 FROM files"):
                phrases[fold(value)] = "the hash of a file in an archive"
            for (value,) in db.execute("SELECT DISTINCT path FROM files WHERE path IS NOT NULL"):
                phrases[fold(pathlib.Path(value).name)] = "the name of a file in an archive"
    phrases.pop("", None)
    allowed = {fold(line) for line in (data_dir.parent / ALLOWED_FILE).read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.startswith("#")} if (data_dir.parent / ALLOWED_FILE).exists() else set()
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
    history = subprocess.run(["git", "-C", str(repo), "log", "--all", "-p", "--no-color"],
                             capture_output=True, text=True, check=False)  # fmt: skip
    return now, fold(history.stdout)


def secrets_of_this_server(repo: pathlib.Path, everything: str) -> list[str]:
    """The secrets this machine actually holds, looked for whole and hashed."""
    trouble = []
    for what, path in SECRET_FILES:
        file = pathlib.Path(path) if pathlib.Path(path).is_absolute() else repo / path
        if not file.exists():
            continue
        for piece in re.findall(r"[A-Za-z0-9+/=_-]{16,}", file.read_text(encoding="utf-8", errors="replace")):
            if fold(piece) in everything or hashlib.sha256(piece.encode()).hexdigest() in everything:
                trouble.append(f"{what} appears in this repository")
    return trouble


def look(repo: pathlib.Path, data_dir: pathlib.Path) -> list[str]:
    """Everything wrong with publishing this repository, as lines. An empty list is the answer."""
    now, history = published(repo)
    everything = history + " ".join(now.values())
    trouble = secrets_of_this_server(repo, everything)
    for what, shape in NEVER_PUBLISHED:
        for file, text in now.items():
            if re.search(shape, text, re.IGNORECASE):
                trouble.append(f"{what} is in {file.relative_to(repo)}")
        if re.search(shape, history, re.IGNORECASE):
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
