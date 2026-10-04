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
        index.execute("CREATE TABLE documents (provider TEXT, doctor TEXT, department TEXT, title TEXT)")
        index.execute("CREATE TABLE files (sha256 TEXT, path TEXT)")
        index.execute("CREATE TABLE diagnoses (text TEXT)")
        index.execute("CREATE TABLE medications (text TEXT)")
        index.execute("CREATE TABLE sections (text TEXT)")
        index.execute("CREATE TABLE page_texts (text TEXT)")
        index.execute("INSERT INTO documents VALUES "
                      "('Zorepad Clinic of Kremenchuk', 'Nezhurenko H.P', 'Laboratory', 'Full blood count')")
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


def test_a_kind_of_place_is_not_a_place(tmp_path: Path):
    """One common noun naming a kind of institution is a word, and a word is not a leak.

    An archive turned up whose forms print, where the institution goes, nothing but the kind of
    institution: one common noun, no name. This guard then said "Do not publish" about a word that
    stands in epicrisis/suspects.py because the program needs it to tell a doctor's signature from
    a laboratory's name — red for ever, over a file that was right to hold it.

    The waving-through is narrow on purpose. A laboratory's brand is one word too, and that one
    names the place that printed half an archive.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    index = sqlite3.connect(data_dir / "index-aa11bb22.sqlite")
    with index:
        index.execute("INSERT INTO documents VALUES (?, NULL, NULL, NULL)", ("Лабораторія",))
        index.execute("INSERT INTO documents VALUES (?, NULL, NULL, NULL)", ("Zorepadlab",))
    index.close()

    kind, _ = guard().look(a_repository(tmp_path, holding="Лабораторія"), data_dir)
    assert kind == []

    repo = tmp_path / "second"
    repo.mkdir()
    (tmp_path / "repo").rename(repo / "repo")
    name, _ = guard().look(repo / "repo", data_dir)
    assert name == []  # the brand is not in that repository at all

    brand, _ = guard().look(a_repository(tmp_path / "third", holding="Zorepadlab"), data_dir)
    assert any("the name of an institution" in line for line in brand), brand


def test_a_commit_nobody_will_ever_receive_is_not_published(tmp_path: Path):
    """History is read as far as it travels, and this repository's history does not travel far.

    "A file deleted in the tip is still published in the history" is true of a repository that is
    pushed. This one is not: each release is one squashed commit on the previous release. A name
    put into a local commit and taken out again before any release can reach nobody, and a gate
    that stays red about it whatever anybody does is a gate people learn to pass with --no-verify.

    What was actually published still answers, which is the half that matters: a name reachable
    from the published branch cannot be recalled by editing a file today.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    repo = a_repository(tmp_path)
    away = tmp_path / "away.git"
    subprocess.run(["git", "init", "-q", "--bare", str(away)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(away)], check=True)
    subprocess.run(["git", "-C", str(repo), "push", "-q", "origin", "HEAD:refs/heads/main"], check=True)
    subprocess.run(["git", "-C", str(repo), "fetch", "-q", "origin"], check=True)

    # A name written into a local commit and taken out again, with nothing pushed since.
    held = repo / "notes.md"
    held.write_text("Zorepad Clinic of Kremenchuk sent the panel.\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "a local step"], check=True)  # fmt: skip
    held.unlink()
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "taken out again"], check=True)  # fmt: skip

    trouble, _ = guard().look(repo, data_dir)
    assert trouble == [], trouble

    # And what the published branch does hold is still found, however the tip reads today.
    (repo / "README.md").write_text("Zorepad Clinic of Kremenchuk\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "and into the branch"], check=True)  # fmt: skip
    subprocess.run(["git", "-C", str(repo), "push", "-q", "origin", "HEAD:refs/heads/main"], check=True)
    subprocess.run(["git", "-C", str(repo), "fetch", "-q", "origin"], check=True)
    (repo / "README.md").write_text("A program that reads scanned lab forms.\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "out of the tip, not out of the past"], check=True)  # fmt: skip

    published_once, _ = guard().look(repo, data_dir)
    assert any("the name of an institution" in line for line in published_once), published_once


def test_an_index_of_an_older_shape_gives_a_verdict_and_not_a_traceback(tmp_path: Path, capsys):
    """A guard that answers a traceback is a guard somebody reruns with --no-verify.

    The doctor was added to the list of what this looks for on the day the archive learnt to keep
    it. The next morning an index built the week before made the whole check die with "no such
    column: doctor" instead of giving a verdict. It failed safe — a crash exits non-zero and the
    push is blocked — but nobody can act on a traceback, and this file warns twice that a guard
    which cannot be acted on is the one that gets passed.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    older = sqlite3.connect(data_dir / "index-aa11bb22.sqlite")
    with older:
        older.execute("ALTER TABLE documents RENAME COLUMN doctor TO doctor_old")  # as it was before
    older.close()

    trouble, counted = guard().look(a_repository(tmp_path, holding="Zorepad Clinic of Kremenchuk"), data_dir)

    # It still read everything else and still found what was there.
    assert any("the name of an institution" in line for line in trouble)
    assert counted >= 5
    # And the half it could not ask for is a finding and not a note: a line of the verdict, naming
    # the index, saying which half is missing and what puts it right.
    said = [line for line in trouble if "the name of a doctor" in line]
    assert len(said) == 1, trouble
    assert "index-aa11bb22.sqlite" in said[0]
    assert "doctor" in said[0] and "build the index again" in said[0]
    # Nothing of it was printed while look() was running: every refusal of this file goes to the
    # caller, which prints it to stderr, and the one thing stdout carries is the word "Clean".
    assert capsys.readouterr().out == ""


def test_an_archive_read_in_half_is_never_called_clean(tmp_path: Path, capsys):
    """The morning fix that made this worse, and the reason the gap is a finding and not a note.

    The fence round those four questions was put in to stop a traceback, and it printed a note and
    carried on. So look() returned no line about the hole, main() printed "Clean: N phrases" and
    returned 0, and the hook before a push waved it through — about a repository holding a doctor's
    surname in a tracked file, which that run had not looked for at all.

    This is the reproduction: an index of the older shape, and the surname sitting in the README.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    older = sqlite3.connect(data_dir / "index-aa11bb22.sqlite")
    with older:
        older.execute("ALTER TABLE documents RENAME COLUMN doctor TO doctor_old")  # as it was before
    older.close()
    repo = a_repository(tmp_path, holding="Signed: Nezhurenko H.P\n")

    answered = guard().main(["--repo", str(repo), "--data-dir", str(data_dir)])

    printed = capsys.readouterr()
    assert answered == 1, printed
    assert "Clean" not in printed.out
    assert "index-aa11bb22.sqlite" in printed.err
    # And it is not printed where the good news is. Nothing matched is printed anywhere.
    assert printed.out == ""
    assert "Nezhurenko" not in printed.err


def a_table_the_index_has_not_got(data_dir: Path) -> str:
    """One of the four reads that stood beside the fenced ones with no fence of their own."""
    index = sqlite3.connect(data_dir / "index-aa11bb22.sqlite")
    with index:
        index.execute("DROP TABLE page_texts")
    index.close()
    return "a line of a document"


def a_torn_list_of_archives(data_dir: Path) -> str:
    """sources.json, written over and cut off: the one read here that is not an index."""
    (data_dir / "sources.json").write_text('[{"id": "aa11bb22",', encoding="utf-8")
    return "the name of a person"


def an_index_copied_halfway(data_dir: Path) -> str:
    """A file sqlite opens and then refuses — "file is not a database" from inside the walk."""
    (data_dir / "index-aa11bb22.sqlite").write_bytes(b"SQLite format 3\x00" + bytes(40))
    return "anything printed on the documents of this archive"


@pytest.mark.parametrize("break_it", [a_table_the_index_has_not_got, a_torn_list_of_archives,
                                      an_index_copied_halfway], ids=lambda it: it.__name__)  # fmt: skip
def test_no_half_of_an_archive_is_read_without_a_fence(tmp_path: Path, capsys, break_it):
    """Four reads of an index and one of a list of archives had none, and gave a stack.

    They exit 1, which is the code main() refuses with, so a push was blocked either way and the
    failure fell to the safe side. But the person got a traceback instead of a verdict, and this
    file says twice, fourteen lines above where they stood, that a guard which answers a traceback
    is a guard somebody reruns with --no-verify — the one failure it is written to prevent.

    Three ways in, and one answer to all three: a half that could not be read is a finding, with
    the name of the file, what it was that could not be asked for, and what puts it right.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    what = break_it(data_dir)
    repo = a_repository(tmp_path)

    answered = guard().main(["--repo", str(repo), "--data-dir", str(data_dir)])

    printed = capsys.readouterr()
    assert answered == 1, printed
    # A verdict, in the words of a finding, where every refusal of this file goes.
    assert printed.out == ""
    assert any(what in line and "cannot clear" in line for line in printed.err.splitlines()), printed.err


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
    # The one that was added last and was nearly missed. The archive learnt to keep the doctor
    # beside the institution, this guard was not retold, and on the first working day after that
    # a real surname went into a module's docstring and a second into a test while it said
    # "Clean" about both. A name on a signature line is the plainest "who" an archive holds.
    ("Signed: Nezhurenko H.P", "the name of a doctor"),
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


def test_a_name_that_lost_its_accent_on_the_way_into_a_commit_is_still_caught(tmp_path: Path):
    """The one spelling this guard compares by had promised to drop accents and did not.

    `unicodedata.normalize("NFKD", …)` only pulls a letter apart from its mark; nothing was
    dropping the mark. So a surname standing in an archive as "Quintanábra" and pasted into a
    docstring as "Quintanabra" was two strings to this check and one string to every search in
    the program. This archive is in five languages, two of them Spanish and Greek, and §5 says
    why that matters: "A plausible surname in the right language is usually a real one."

    Measured when it was found: of seven pairs differing only by an accent, this answered "not
    the same" to five that printed_values.fold calls one. The name here is invented and was
    looked for in all three archives on this machine first; the accent is the whole of the test,
    so the two spellings differ in nothing else.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    index = sqlite3.connect(data_dir / "index-aa11bb22.sqlite")
    with index:
        index.execute("INSERT INTO documents VALUES (NULL, 'Dr. Félix Quintanábra', NULL, NULL)")
    index.close()

    trouble, _counted = guard().look(
        a_repository(tmp_path, holding="# read by Dr. Felix Quintanabra, who does not exist\n"), data_dir)  # fmt: skip

    assert any("doctor" in line for line in trouble), trouble
    # And the report never prints what it found, accented or not: that is the whole discipline.
    assert not any("uintan" in line for line in trouble), trouble


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


def a_pushed_copy(repo: Path, of: str = "HEAD") -> None:
    """Give that repository an origin/main holding that commit, as the published one has."""
    away = repo.parent / "away.git"
    if not away.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(away)], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(away)], check=True)
    subprocess.run(["git", "-C", str(repo), "push", "-q", "-f", "origin", f"{of}:refs/heads/main"], check=True)
    subprocess.run(["git", "-C", str(repo), "fetch", "-q", "origin"], check=True)


def test_a_version_of_a_picture_in_a_branch_that_never_travels_is_not_published(tmp_path: Path):
    """The phrases were read as far as they travel and the pictures were read out of `--all`.

    Three places wrote `--all` in by hand while _what_travels stood beside them explaining, in its
    own words, that a gate which is red whatever anybody does is a gate people pass with
    --no-verify. So this half answered "do not publish" over versions of a screenshot held in the
    working branches of agents' worktrees: not ancestors of the published branch, carried out of by
    no squashed release, and impossible to clear from the branch anybody is standing on.

    What was published still answers, which is the half that matters.
    """
    repo = a_repository_of_pictures(tmp_path, [FIRST])
    a_pushed_copy(repo)
    assert guard().pictures_of_nobody(repo) == []

    # A second version of the same picture, committed on a branch of its own and never pushed.
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "a-worktree-of-its-own"], check=True)
    (repo / PICTURES / "01-timeline.png").write_bytes(SECOND)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "taken again, in a worktree"], check=True)  # fmt: skip
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-"], check=True)  # and back to the tip

    assert guard().pictures_of_nobody(repo) == []

    # And the same blob, once the published branch holds it, cannot be recalled by anybody.
    a_pushed_copy(repo, of="a-worktree-of-its-own")

    trouble = guard().pictures_of_nobody(repo)
    assert len(trouble) == 1, trouble
    assert "01-timeline.png" in trouble[0] and sha256(SECOND) in trouble[0]


def test_the_journal_of_a_running_instance_is_looked_at_too(tmp_path: Path):
    """The one file of a live instance this guard could not see, and the one most likely to be read out.

    Every other check here asks about the repository: tracked files and commits. The journal is
    neither — it sits in the data directory, untracked — so it was swept by nothing at all, while
    being the file that exists in order to be pasted into a question about why a step failed. A
    line of somebody's diagnosis in it travels exactly as far as one in a commit.

    The journal is written to hold counts, an archive's random id and a place in the source, so on
    this machine it is clean; that was checked by hand once, which is not a check. This is the
    check, and it is red when a phrase out of the archive reaches that file.
    """
    from epicrisis import layout

    data_dir = tmp_path / "data"
    an_archive(data_dir)
    repo = a_repository(tmp_path)
    phrases, _gaps = guard().out_of_the_archive(data_dir)

    assert guard().look(repo, data_dir)[0] == [], "the instance is clean before anything is written"

    # A refusal recorded with the file's own name in it, which is how it would happen: a writer
    # reaching for "which file" and handing over the line that was in it.
    (data_dir / layout.JOURNAL).write_text(
        '{"at": "2026-10-04T06:00:00+00:00", "event": "a step refused", '
        '"about": "Chronic pyelonephritis in remission, Prokopchuk"}\n', encoding="utf-8")  # fmt: skip
    trouble, _counted = guard().look(repo, data_dir)

    assert any(layout.JOURNAL in line for line in trouble), trouble
    assert any("line of diagnosis" in line for line in trouble), trouble
    # And it is said by kind and counted, never quoted — the same discipline as every line above.
    assert not any("Prokopchuk".casefold() in line.casefold() for line in trouble)


def test_a_journal_that_cannot_be_read_is_never_called_clean(tmp_path: Path):
    """The fail-safe this guard already got wrong once, about a half-read archive.

    "Clean" over a file the check could not open is worse than a crash: it is the one sentence a
    person reads before publishing.
    """
    from epicrisis import layout

    data_dir = tmp_path / "data"
    an_archive(data_dir)
    (data_dir / layout.JOURNAL).write_bytes(b'{"event": "a step refused", "about": "\xff\xfe not text"}\n')

    trouble, _counted = guard().look(a_repository(tmp_path), data_dir)

    assert any("could not be read" in line and layout.JOURNAL in line for line in trouble), trouble
