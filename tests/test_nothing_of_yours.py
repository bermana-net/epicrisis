"""The guard that reads a repository before it is pushed, tested on an invented archive.

It had none. It is the one thing standing between a person's medical records and a public
repository, it grew five checks over five weeks, and each of them was verified by running it once
against this project and reading the word "Clean" — which is exactly the way a guard comes to be
wrong about the thing it was written for and to say so in the same words as when it is right.

Everything here is invented: a repository made in a temporary folder, an archive of two people who
do not exist, and secrets of the same kind as the real ones and of no value.
"""

import hashlib
import importlib.util
import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parent.parent / "tools" / "nothing-of-yours.py"


def guard():
    spec = importlib.util.spec_from_file_location("nothing_of_yours", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def an_archive(data_dir: Path) -> None:
    """A data directory of the shape this guard reads: a list of archives and one index."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "sources.json").write_text(json.dumps([
        # The folder is named after nothing: a person's name is then only a person's name, and the
        # kind this reports for it is the one under test rather than whichever source wrote last.
        {"id": "aa11bb22", "name": "the cardboard box", "path": "/scans/the cardboard box",
         "owner": "Vasylyna Prokopchuk", "added_at": "2026-01-01T00:00:00+00:00"},
    ]), encoding="utf-8")  # fmt: skip
    index = sqlite3.connect(data_dir / "index-aa11bb22.sqlite")
    with index:
        index.execute("CREATE TABLE documents (provider TEXT, department TEXT, title TEXT)")
        index.execute("CREATE TABLE files (sha256 TEXT, path TEXT)")
        index.execute("CREATE TABLE diagnoses (text TEXT)")
        index.execute("CREATE TABLE medications (text TEXT)")
        index.execute("CREATE TABLE sections (text TEXT)")
        index.execute("CREATE TABLE page_texts (text TEXT)")
        index.execute("INSERT INTO documents VALUES ('Zorepad Clinic of Kremenchuk', 'Laboratory', 'Full blood count')")
        index.execute("INSERT INTO files VALUES ('c' * 64, '/scans/2019/kremenchuk-panel.pdf')")
        index.execute("INSERT INTO diagnoses VALUES ('Chronic pyelonephritis in remission, Prokopchuk')")
        index.execute("INSERT INTO medications VALUES ('Levothyroxine 88 micrograms every morning')")
        index.execute("INSERT INTO sections VALUES "
                      "('The patient reports no pain in the right side since the operation of 2014.')")
        index.execute("INSERT INTO page_texts VALUES ('------------------------------------------')")
    index.close()


def a_repository(where: Path, holding: str = "") -> Path:
    repo = where / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "README.md").write_text("A program that reads scanned lab forms.\n" + holding, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "first"], check=True)  # fmt: skip
    return repo


def test_a_clean_repository_is_clean(tmp_path: Path):
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    trouble, counted = guard().look(a_repository(tmp_path), data_dir)

    assert trouble == []
    # And it really did look: the phrases are the archive's, not an empty set answering "clean".
    assert counted >= 5


@pytest.mark.parametrize("leak, what", [
    ("Vasylyna Prokopchuk came in on the third", "the name of a person"),
    ("Zorepad Clinic of Kremenchuk", "the name of an institution"),
    ("kremenchuk-panel.pdf", "the name of a file in an archive"),
    ("Chronic pyelonephritis in remission, Prokopchuk", "a line of diagnosis"),
    ("Levothyroxine 88 micrograms every morning", "the name of a medication"),
    ("The patient reports no pain in the right side since the operation of 2014.", "a line of a document"),
])  # fmt: skip
def test_every_kind_of_phrase_is_looked_for(tmp_path: Path, leak: str, what: str):
    """Four of these six were promised by the first line of that file and never asked for.

    A department, a title, a line of diagnosis, the name of a drug, a sentence out of a report — any
    of them pasted into a test or a docstring while debugging walked past a check that then printed
    "Clean: N phrases out of the archive are in no tracked file and in no commit".
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    trouble, _counted = guard().look(a_repository(tmp_path, holding=leak), data_dir)

    assert any(what in line for line in trouble), (what, trouble)
    # And nothing out of the archive is printed in the report: that is the whole discipline.
    assert not any(leak.casefold() in line.casefold() for line in trouble)


def test_the_name_of_a_kind_of_form_is_not_somebody_s(tmp_path: Path):
    """"Full blood count" and "Laboratory" are what every form of that kind prints.

    Asked for, they matched this project twenty-three times over — its demo, which invents its own
    people, and its tests. A guard that shouts at those is a guard somebody pushes past with
    --no-verify on the day it is right.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    holding = "The demo invents a Full blood count in its Laboratory.\n"

    trouble, _counted = guard().look(a_repository(tmp_path, holding=holding), data_dir)

    assert trouble == []


def test_a_row_of_dashes_is_nobody_s_line(tmp_path: Path):
    """A line of a form is forty characters of rule, and it matched the font licences of this repo."""
    data_dir = tmp_path / "data"
    an_archive(data_dir)

    trouble, _counted = guard().look(
        a_repository(tmp_path, holding="------------------------------------------\n"), data_dir)  # fmt: skip

    assert trouble == []


def test_the_secret_beside_the_data_directory_is_compared(tmp_path: Path):
    """An environment file is read from beside the data directory first, and was looked for only
    beside the repository — so the key of an instance that keeps its data elsewhere, which is the
    ordinary arrangement, was compared with nothing at all."""
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    (data_dir / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-invented-key-abcdefghijklmnop\n", encoding="utf-8")

    said, _counted = guard().look(
        a_repository(tmp_path, holding="sk-ant-invented-key-abcdefghijklmnop\n"), data_dir)  # fmt: skip

    assert any("environment file" in line for line in said)
    # And the name of the variable is not the secret: this project prints it in its own README.
    clean, _ = guard().look(a_repository(tmp_path / "second", holding="Set ANTHROPIC_API_KEY in .env\n"), data_dir)
    assert not any("environment file" in line for line in clean)


def test_a_git_that_fails_is_not_a_history_with_nothing_in_it(tmp_path: Path):
    """The history was read with the return code unlooked at, so a git that failed for any reason
    left it empty — and the last line of the report still said "in no commit"."""
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    not_a_repository = tmp_path / "plain"
    not_a_repository.mkdir()

    with pytest.raises(subprocess.CalledProcessError):
        guard().look(not_a_repository, data_dir)


def a_repository_of_pictures(where: Path, pictures: list[bytes], declaring: dict | None = None) -> Path:
    """A repository that published a picture and then replaced it, one commit per version.

    The name never changes and the file is never deleted, which is the case this guard could not
    see: it hashed the file standing in the tip, and asked the history only whether some name had
    disappeared from it. Every version in between is published to everybody who clones this.
    """
    repo = where / "repo"
    (repo / PICTURES).mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    picture = repo / PICTURES / "01-timeline.png"
    manifest = repo / PICTURES / "taken-from-the-demo.json"
    for number, bytes_of_it in enumerate(pictures, start=1):
        picture.write_bytes(bytes_of_it)
        written = {"of": {"invented": True, "lives": ["Vera Lindqvist"]},
                   "pictures": {"01-timeline.png": sha256(bytes_of_it)}}  # fmt: skip
        if number == len(pictures) and declaring is not None:
            written["earlier"] = declaring
        manifest.write_text(json.dumps(written, indent=1), encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", f"picture {number}"], check=True)  # fmt: skip
    return repo


def sha256(bytes_of_it: bytes) -> str:
    return hashlib.sha256(bytes_of_it).hexdigest()


PICTURES = "docs/images"
FIRST = b"\x89PNG a picture of the demo, as it was\n"
SECOND = b"\x89PNG a picture of the demo, taken again\n"


def test_the_version_a_picture_had_before_it_was_replaced_is_checked_too(tmp_path: Path):
    """Twenty blobs in this project's own history had never been compared with anything.

    A picture *deleted* was caught; a picture *replaced* was not, because the check hashed the tip
    and asked the history for missing names only. The blob of the older version is published to
    everybody who clones the repository, and nothing at all said whether it had been taken of
    invented people or of somebody's own page.
    """
    repo = a_repository_of_pictures(tmp_path, [FIRST, SECOND])

    trouble = guard().pictures_of_nobody(repo)

    assert any("01-timeline.png" in line for line in trouble), trouble
    # It is the version in the history that is named, and the one standing today — which the
    # manifest declares — is answered for once and not twice.
    assert len(trouble) == 1, trouble
    said = trouble[0]
    assert sha256(FIRST) in said
    assert sha256(SECOND) not in said
    # And the line says what to do: how to look at that version, where to write it down if it was
    # taken of the demo, and what it means for this history if it was not.
    assert "cat-file blob" in said and "earlier" in said and "taken-from-the-demo.json" in said
    assert "publish the state" in said


def test_an_earlier_version_the_manifest_declares_is_not_trouble(tmp_path: Path):
    """Which is what keeps this guard runnable: a picture taken again is an ordinary day's work.

    The run that replaces one writes the hash it displaced under "earlier", and the repository is
    clean again — without which every push after every new screenshot would be refused, and the
    guard would become the thing people learn to pass with --no-verify.
    """
    repo = a_repository_of_pictures(tmp_path, [FIRST, SECOND], declaring={"01-timeline.png": [sha256(FIRST)]})

    assert guard().pictures_of_nobody(repo) == []


def test_a_picture_no_commit_ever_replaced_is_still_clean(tmp_path: Path):
    """The plain case, lest the walk of the history start shouting at every repository there is."""
    repo = a_repository_of_pictures(tmp_path, [FIRST])

    assert guard().pictures_of_nobody(repo) == []
