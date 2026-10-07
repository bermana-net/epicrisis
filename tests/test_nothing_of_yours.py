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

from epicrisis import connectors

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
    # Whoever this instance is for, by the signature they are known by, and which archives they
    # keep. Nobody's name is in this file: a signature and an archive's id are four random bytes
    # each, so there is nothing in here to look for, and what this guard checks instead is that
    # nothing has appeared in it since anybody last asked.
    (data_dir / "keepers.json").write_text(json.dumps([
        {"id": "7b3f1c04", "issued_at": "2026-01-01T00:00:00+00:00", "archives": ["aa11bb22"]},
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


def a_torn_list_of_keepers(data_dir: Path) -> str:
    """keepers.json, cut off mid-write: the second read here that is not an index.

    No door in the program opens an archive by a signature, which is exactly why this file has to
    be read here and read loudly. A file nobody looks at is the file whose contents walk into a
    fixture, a docstring or a commit message with nobody noticing where they came from.
    """
    (data_dir / "keepers.json").write_text('[{"id": "7b3f1c04",', encoding="utf-8")
    return "the name of a person"


def an_index_copied_halfway(data_dir: Path) -> str:
    """A file sqlite opens and then refuses — "file is not a database" from inside the walk."""
    (data_dir / "index-aa11bb22.sqlite").write_bytes(b"SQLite format 3\x00" + bytes(40))
    return "anything printed on the documents of this archive"


@pytest.mark.parametrize("break_it", [a_table_the_index_has_not_got, a_torn_list_of_archives,
                                      a_torn_list_of_keepers, an_index_copied_halfway],
                         ids=lambda it: it.__name__)  # fmt: skip
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


def a_connector(data_dir: Path, **fields) -> None:
    """One line in the registry of connectors, as `connectors.issue` writes one."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "connectors.json").write_text(json.dumps([{
        "id": "7a1b2c3d", "path": "p" * 48, "name": "", "archives": ["aa11bb22"],
        "keeper": "", "issued_at": "2026-01-01T00:00:00+00:00", "revoked_at": "", **fields,
    }]), encoding="utf-8")  # fmt: skip


def test_the_name_this_instance_answers_on_is_looked_for(tmp_path: Path):
    """A new value in the data directory, and this one is an address rather than a name.

    Not a secret: the secret is the path, and a tunnel answers on this name publicly. But it is
    what somebody knocks on to reach these archives, and the convention it arrives into is already
    written down — README.md writes it as `<name.ts.net>` and this repository holds no real one.
    Until this setting existed the name lived on a command line and in no file at all, so there
    was nothing to look for; the day it is stored is the day it can be pasted.

    Measured on the live instance when it was added: the count of phrases went from 5936 to 5937,
    and planting the name in a tracked file refused the push.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    (data_dir / "settings.json").write_text(json.dumps({"public_host": "somewhere.example.ts.net"}),
                                            encoding="utf-8")  # fmt: skip

    trouble, _counted = guard().look(
        a_repository(tmp_path, holding="# reachable at somewhere.example.ts.net\n"), data_dir)  # fmt: skip

    assert any("the name this instance answers on" in line for line in trouble), trouble
    # Compared whole, as every phrase here is, so the word inside it matches nothing on its own.
    clean, _counted = guard().look(
        a_repository(tmp_path / "second", holding="# Epicrisis reads scanned forms\n"), data_dir)  # fmt: skip
    assert not any("answers on" in line for line in clean), clean


def test_the_name_somebody_gave_a_connector_is_looked_for(tmp_path: Path):
    """A link is labelled by hand, and what somebody writes on it is often a person.

    The field exists because the page needs something to call a link. It is the one field of that
    file a person types, and the first draft of the comment that says so carried a real surname
    out of the archive into this repository — which this check refused the push over, two minutes
    after being taught to look. That is the whole argument for this test.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    a_connector(data_dir, name="Джулай І.С.")

    trouble, _counted = guard().look(
        a_repository(tmp_path, holding='"""The link I made for Джулай."""\n'), data_dir)  # fmt: skip

    assert any("connector" in line for line in trouble), trouble
    assert not any("жулай" in line for line in trouble), trouble


def test_an_ordinary_word_on_a_connector_does_not_refuse_the_push(tmp_path: Path):
    """Measured, and it decided the rule: the words of this field are read as the doctor column.

    Against ten names somebody might plausibly type for a link, taking every word of five letters
    or more refused **seven**, every one of them on an ordinary word — urologist, cardiologist,
    laboratory, underwriter, and the Russian and Ukrainian for the first two. A gate that is red
    whatever anybody does is the thing people pass with --no-verify on the day it is right, which
    this file says three times in its own words. Taking only the words standing beside initials
    refused one, and that one was a real finding.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    a_connector(data_dir, name="the urologist in Kremenchuk")

    trouble, _counted = guard().look(
        a_repository(tmp_path, holding="# a urologist reads this kind of form\n"), data_dir)  # fmt: skip

    assert not any("connector" in line for line in trouble), trouble


def test_a_speciality_beside_initials_on_a_connector_is_not_a_name(tmp_path: Path):
    """The commonest shape a person types, and the one my ten examples did not cover.

    "Nezhurenko H.P., urologist" puts the speciality **beside initials**, so the doctor column's
    rule takes it as a word of the name — right for a signature on a form, wrong for a label
    somebody gave a credential. Found by running the real check against the real instance with a
    link named that way: it refused the push twice, once on the surname and once on the word for
    "urologist" in Russian. The words the program keeps in order to recognise a kind of person are
    waved through for this field as they already are for the two that name somebody.

    What is still left over is written down beside the code: a speciality the program does not
    keep is still taken, and `published-on-purpose.txt` is the way out.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    # The word for "clinic" is one of the fifty-eight, and it is in this repository many times.
    a_connector(data_dir, name="Лабораторія Нетудихата")

    trouble, _counted = guard().look(a_repository(tmp_path), data_dir)

    assert not any("connector" in line for line in trouble), trouble


def test_a_field_on_a_connector_this_check_has_never_heard_of_is_not_cleared(tmp_path: Path):
    """The twin of the keeper's, and the same failure it guards against.

    A line of that file carries no name by construction except the one a person typed. The day
    somebody adds a twelfth field, whatever is in it has never been looked for anywhere, and a
    check that says "Clean" about a file it does not understand is the one shape of failure this
    tool is written against.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    a_connector(data_dir, who_it_was_made_for="Nezhurenko H.P")

    trouble, _counted = guard().look(a_repository(tmp_path), data_dir)

    assert any("who_it_was_made_for" in line for line in trouble), trouble
    assert any("never heard of" in line for line in trouble), trouble
    # And it names what to do about it, because a finding nobody can act on is noise.
    assert any("before publishing" in line for line in trouble), trouble


def test_the_code_secret_of_a_connector_is_looked_for_by_name_off_the_disk(tmp_path: Path):
    """One file per link, named by whatever the registry issued, so the names are read and not written.

    Before this, the two secrets written out in `SECRET_FILES` were the whole of what was looked
    for. The day the registry issues its first link, every secret after those two is one nothing
    compares — which is the shape of the hole the doctor column was, in the half of this tool that
    is about secrets rather than about the archive.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    secrets_folder = tmp_path / "connector-secrets"
    secrets_folder.mkdir()
    (secrets_folder / "7a1b2c3d").write_text("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP\n", encoding="utf-8")
    a_connector(data_dir)

    module = guard()
    # The shipped constant names the folder the registry actually writes to, asserted before it is
    # pointed elsewhere: a test that only exercises the mechanism through its own folder passed a
    # mutation that emptied this tuple, which would have left the real secrets looked for by
    # nothing while every test stayed green.
    assert [folder for _what, folder in module.SECRET_FOLDERS] == [str(connectors.SECRETS_FOLDER)]
    module.SECRET_FOLDERS = (("a connector's code secret", str(secrets_folder)),)
    trouble, _counted = module.look(
        a_repository(tmp_path, holding="SECRET = 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP'\n"), data_dir)  # fmt: skip

    assert any("code secret" in line for line in trouble), trouble
    # The id of the link is named, because without it the person is told a secret escaped and not
    # which link to revoke. It carries no part of anybody's name, and is already in two logs.
    assert any("7a1b2c3d" in line for line in trouble), trouble
    # And nothing of the secret itself is printed, here as everywhere.
    assert not any("JBSWY3DP" in line for line in trouble), trouble


def test_a_field_on_a_keeper_this_check_has_never_heard_of_is_not_cleared(tmp_path: Path):
    """There is nothing of anybody's in keepers.json, and this is how that stays true.

    A keeper is a signature and a list of archive ids, all of them random bytes. So this guard has
    nothing to look for in that file — and a guard with nothing to look for is a guard that stops
    noticing the file. What it does instead is refuse to clear a line of it that has grown a field
    nobody has told it about: the step before this one kept the owner's name there, the step after
    may want something else, and a name in a file nobody reads is a name that walks into a
    fixture. The repository here is clean; the finding is about the field alone.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    (data_dir / "keepers.json").write_text(json.dumps([
        {"id": "7b3f1c04", "issued_at": "2026-01-01T00:00:00+00:00", "archives": [],
         "signed_in_as": "whoever this is"},
    ]), encoding="utf-8")  # fmt: skip

    trouble, _counted = guard().look(a_repository(tmp_path), data_dir)

    assert any("signed_in_as" in line for line in trouble), trouble
    assert any("may hold somebody's name" in line for line in trouble)
    # And the contents of the field are not printed in the report: that is the whole discipline.
    assert not any("whoever this is" in line for line in trouble)


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


def test_a_surname_pasted_without_its_initials_is_caught(tmp_path: Path):
    """The hole this guard had, stated as a test: a signature compared whole matches no paste.

    A form prints "Джулай І.С." and a person debugging pastes "Джулай", because the initials are
    not what puzzled them. Compared whole, "джулай і.с." is in no file of any repository ever, so
    the guard read the one column that names a person and said "Clean" about a surname standing
    in a docstring. Six characters, which is also why SHORTEST has an exception: of the words this
    now reads out of the doctor column of the archives on this machine, two in three are shorter
    than nine characters.

    The name is invented and was looked for in all three archives here — in `provider`, `doctor`,
    `title`, the observations, the page texts, the sections, the diagnoses and the medications —
    before it was written down. §5: "A plausible surname in the right language is usually a real
    one."
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    index = sqlite3.connect(data_dir / "index-aa11bb22.sqlite")
    with index:
        index.execute("INSERT INTO documents VALUES (NULL, 'Джулай І.С.', NULL, NULL)")
    index.close()

    trouble, _counted = guard().look(
        a_repository(tmp_path, holding='"""The signature on that form reads Джулай."""\n'), data_dir)  # fmt: skip

    assert any("the name of a doctor" in line for line in trouble), trouble
    # And the report never prints the name it found: that is the whole discipline.
    assert not any("жулай" in line for line in trouble), trouble


def test_a_surname_written_in_the_other_alphabet_is_the_same_surname(tmp_path: Path):
    """The second half of the hole the accents were the first half of, and it stood open a day.

    A laboratory in Ukraine prints "Ніконенко І.С." and the same doctor on a Russian form is
    "Никоненко И.С."; a person debugging pastes whichever of the two was in front of them. To
    every search in this program those are one name — printed_values.fold pairs і with и — and to
    this guard they were two, so it looked straight at a surname in a docstring and said "Clean".

    The proof that this was not hypothetical: both collisions mended the day before this test was
    written — an invented clinic in a rule file and an invented patient in a test — were found by
    the program's fold and not by this guard.

    The name is invented and both spellings were looked for in all three archives on this machine
    — in `provider`, `doctor`, the diagnoses, the medications, the sections, the page texts and
    the file paths, under the fold that pairs the letters, so a collision could not hide in the
    other alphabet either — before either was written down.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    index = sqlite3.connect(data_dir / "index-aa11bb22.sqlite")
    with index:
        index.execute("INSERT INTO documents VALUES (NULL, 'Ніконенко І.С.', NULL, NULL)")
    index.close()

    trouble, _counted = guard().look(
        a_repository(tmp_path, holding='"""The form was signed Никоненко."""\n'), data_dir)  # fmt: skip

    assert any("the name of a doctor" in line for line in trouble), trouble
    assert not any("иконенко" in line or "іконенко" in line for line in trouble), trouble


def test_the_fold_of_this_guard_and_the_fold_of_the_program_are_one_fold(tmp_path: Path):
    """Two tables of the same letters in two files, held in step by this rather than by memory.

    The guard writes its own fold out instead of importing the program's, because it is run
    against repositories that are not this program and a guard that folds less where it cannot
    import would report "Clean" about an archive it compared half of. The cost of that decision
    is a second copy of one list, and this is what pays it: every letter of both alphabets, the
    signs that are not a sound, the apostrophes, and the accented letters of the other three
    languages, asked of both folds. A letter added to printed_values._FOLD and not to PAIRED
    fails here, on the commit that adds it.

    The one difference is deliberate and is not a letter: this guard collapses runs of whitespace,
    because it compares phrases against whole files, and the program does not, because it compares
    a value against a value. So the program's answer is collapsed before the two are set equal.

    Which is why the standing marks are in the corpus below, and they were put there by a mutation
    that this test let through: ¨ and its four companions decompose into a space and a mark, so a
    guard that collapses its whitespace *before* the decomposing leaves behind runs of spaces that
    were never in the text. Nothing in the first corpus here had one, and the mutation passed.
    """
    import re

    from epicrisis import printed_values

    letters = ("абвгґдеєжзиіїйклмнопрстуфхцчшщьюяъыэё"
               "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩαβγδεζηθικλμνξοπρςστυφχψω"
               "áéíóúñüàèìòùäöâêîôûçãõåøæœßÁÉÍÓÚÑ"
               "'’‘ʼʻʽˈ`´′"
               # The marks that stand on their own, each of which decomposes into a space and a
               # combining mark, and the space that is not one.
               "¨ˆ˜¯¸\u00a0")
    pieces = [*letters, *(letter.upper() for letter in letters),
              "Ніконенко", "Никоненко", "Дем'яненко", "Демьяненко", "Ольга", "Олга",
              "José", "Jose", "Ευαγγελία", "Quintanábra", " двоє  слів ", "",
              "a¨¨b", "дво\u00a0\u00a0є", "a´´b"]  # fmt: skip

    the_guards = guard().fold
    for piece in pieces:
        mine = the_guards(piece)
        theirs = re.sub(r"\s+", " ", printed_values.fold(piece)).strip()
        assert mine == theirs, (repr(piece), repr(mine), repr(theirs))


def test_a_line_the_fold_shortens_is_still_a_line_of_somebody_s_document(tmp_path: Path):
    """The failure the pairing of the alphabets nearly bought, and the reason the gate asks print.

    The fold takes characters out as well as pairing them — the soft sign, the hard sign, the
    apostrophe — so a line of forty-one characters can be compared as a spelling of thirty-eight.
    Measured on the three archives here the day the letters were paired: **165 lines** cleared
    A_LINE_OF_A_DOCUMENT and WORDS_OF_A_LINE as printed and fell under one of them once folded,
    and stopped being looked for in this repository at all. A change made to find more that
    quietly finds less is the worse of the two failures, and no count of new matches shows it.

    The line below is somebody's sentence with soft signs enough to cross the gate one way and not
    the other, and it is in no archive: invented Russian about a shoulder, with the two spellings
    of nobody's name nowhere in it.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    a_line = "Больной жалуется на сильную боль в плече."
    assert len(a_line) >= 40 and sum(1 for c in a_line if c.isalpha()) >= 25
    index = sqlite3.connect(data_dir / "index-aa11bb22.sqlite")
    with index:
        index.execute("INSERT INTO sections VALUES (?)", (a_line,))
    index.close()
    folded = guard().fold(a_line)
    # The whole point of the test: as printed it clears the gate, as folded it would not. Forty
    # one characters become thirty eight, because three soft signs come out of it.
    assert len(folded) < 40, (len(folded), folded)

    trouble, _counted = guard().look(
        a_repository(tmp_path, holding=f"# the line that puzzled me: {a_line}\n"), data_dir)  # fmt: skip

    assert any("a line of a document" in line for line in trouble), trouble


def test_the_word_read_out_of_a_signature_is_the_name_and_not_the_speciality(tmp_path: Path):
    """What tells one from the other is the initials, and nothing else does.

    The doctor column holds the name with everything a form prints round it — a speciality, a
    degree, a department. Measured on the three archives here: every word of that column is 103
    words of five letters or more, and this repository holds 11 of them — a speciality, a title,
    and "medica" sitting inside the English word "medical" in 63 files. Not one is a surname. A
    guard that is red over the word for "surgeon" in a test about reading doctors out of text is
    red whatever anybody does, and that is the gate people learn to pass with --no-verify.

    The words standing beside initials are 69 on the same archives and this repository holds none
    of them. One value holds both halves here, so the two assertions are about one string.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    index = sqlite3.connect(data_dir / "index-aa11bb22.sqlite")
    with index:
        index.execute("INSERT INTO documents VALUES (NULL, 'хірург Джулай І.С.', NULL, NULL)")
    index.close()

    speciality, _counted = guard().look(
        a_repository(tmp_path, holding="# the word a form prints for a surgeon is хірург\n"), data_dir)  # fmt: skip
    assert speciality == []

    surname, _counted = guard().look(
        a_repository(tmp_path / "second", holding="# signed by Джулай\n"), data_dir)
    assert any("the name of a doctor" in line for line in surname), surname


def test_an_institution_is_read_in_words_only_where_it_holds_a_signature(tmp_path: Path):
    """A laboratory's field filled in with a signature is a name; the rest of them are places.

    `suspects.provider_looks_like_a_person` exists because that field is filled in with a
    signature on real forms — 24 of the 179 provider values here carry initials. Those are read
    as words, like a doctor's. The other 155 are the name of a place, and a place is written in
    common nouns: measured on the three archives, every word of the provider column is 307 words,
    this repository holds 50 of them, and 35 of those 50 are in no vocabulary this program keeps —
    "calle", "decision", "machine", "здравоохранения", a city, a street, a country. Nothing a
    reader of that report could do anything about.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    index = sqlite3.connect(data_dir / "index-aa11bb22.sqlite")
    with index:
        index.execute("INSERT INTO documents VALUES ('Загуменна В.П.', NULL, NULL, NULL)")
    index.close()

    # The town in the name of the laboratory that printed half this archive, on its own.
    a_place, _counted = guard().look(a_repository(tmp_path, holding="# a town called Kremenchuk\n"), data_dir)
    assert a_place == []

    signed, _counted = guard().look(
        a_repository(tmp_path / "second", holding="# the form was stamped by Загуменна\n"), data_dir)
    assert any("the name of an institution" in line for line in signed), signed


def test_a_line_of_diagnosis_and_the_name_of_a_drug_are_not_read_in_words(tmp_path: Path):
    """Two columns that were asked to be split and measured their way out of it.

    A diagnosis names an illness and a prescription names a drug; neither names a person, and
    both are sentences. Measured on the three archives here: the diagnoses hold 1163 words of
    five letters or more and this repository holds 83 of them, the medications hold 438 and this
    repository holds 20 — "after", "history", "level", "treatment", "forma", "почки", "скарг",
    "утром", the words any form of that kind prints and any program that reads such forms has to
    be free to write. Whole, which is how a sentence is pasted, both are still looked for, and
    `test_every_kind_of_phrase_is_looked_for` holds that half.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    holding = ("# every morning is when a dose is taken, and remission is a state of an illness\n")

    trouble, _counted = guard().look(a_repository(tmp_path, holding=holding), data_dir)

    assert trouble == []


def test_a_name_published_on_purpose_is_published_in_words_too(tmp_path: Path):
    """The list of what its owner meant to publish is read the way the archive is read.

    An author's own name stands in the licence of this project, in its copyright line and on its
    page, and `published-on-purpose.txt` is where that decision is written down. The moment a
    name is read as words, a list read only as whole phrases refuses the push over the surname in
    a licence file — half of a decision somebody has already made, with nothing to do about it
    but delete the licence.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    # Beside the data directory, which is one of the three places an instance keeps that list.
    (data_dir / "published-on-purpose.txt").write_text(
        "# the name of whoever keeps this archive, in its own licence\nVasylyna Prokopchuk\n",
        encoding="utf-8")  # fmt: skip
    repo = a_repository(tmp_path, holding="Kept and read by Vasylyna, who does not exist.\n")

    trouble, _counted = guard().look(repo, data_dir)

    assert trouble == []


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


def test_the_journal_is_compared_with_the_secrets_this_machine_holds(tmp_path: Path):
    """What this check was named for and never did, and the noise it made instead.

    It asked `_secrets_in` — any run of sixteen characters — which refused a push over
    `TemplateSyntaxError` and the path of a template, found in the live journal of this instance
    minutes after a 500 it had correctly recorded. That is exactly what the journal is written to
    hold: the type of the fault and the place in the source. Meanwhile the secrets on the machine
    were compared against the journal by nothing at all, so the one thing the line was named for
    could have been sitting in there.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    secrets_folder = tmp_path / "connector-secrets"
    secrets_folder.mkdir()
    (secrets_folder / "7a1b2c3d").write_text("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP\n", encoding="utf-8")
    module = guard()
    module.SECRET_FOLDERS = (("a connector's code secret", str(secrets_folder)),)

    # What the journal is for, and what used to refuse a push.
    (data_dir / "journal.jsonl").write_text(json.dumps({
        "at": "2026-01-01T00:00:00+00:00", "event": "a step failed",
        "because": "TemplateSyntaxError", "at_line": "epicrisis/web/templates/_header.html:34",
    }) + "\n", encoding="utf-8")  # fmt: skip
    trouble, _counted = module.look(a_repository(tmp_path / "first"), data_dir)
    assert not any("journal" in line for line in trouble), trouble

    # And the thing it was named for, which nothing looked for before.
    (data_dir / "journal.jsonl").write_text(json.dumps({
        "at": "2026-01-01T00:00:00+00:00", "event": "a step failed",
        "because": "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
    }) + "\n", encoding="utf-8")  # fmt: skip
    trouble, _counted = module.look(a_repository(tmp_path / "second"), data_dir)
    assert any("code secret" in line and "journal" in line for line in trouble), trouble
    assert not any("JBSWY3DP" in line for line in trouble), trouble


def test_a_key_of_a_shape_that_is_always_a_secret_is_caught_in_the_journal(tmp_path: Path):
    """The other half: a key is a key wherever it turns up, whoever it belongs to.

    Not only this machine's own secrets — an instance that logged somebody else's API key would
    be holding a secret in the one file people paste into questions.

    The key is **put together at run time** and never written out here, which took two goes to
    get right. Spelled out, it is a shaped key in a tracked file and the guard refused the push
    over this very test — correctly. Declared in `NOT_A_SECRET` instead, the guard then ignored
    it and the test could prove nothing. Assembled with `+`, the file holds `"sk-ant-" + "…"` and
    the shape needs its eight characters unbroken, so there is nothing here to find and a real
    one to find in the journal.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    (data_dir / "journal.jsonl").write_text(json.dumps({
        "at": "2026-01-01T00:00:00+00:00", "event": "a call failed",
        "because": "sk-ant-" + "api03-nosuchkey-butshapedlikeone",
    }) + "\n", encoding="utf-8")  # fmt: skip

    trouble, _counted = guard().look(a_repository(tmp_path), data_dir)

    assert any("Anthropic key" in line and "journal" in line for line in trouble), trouble
    # And the fixtures this guard's own tests plant are still not secrets.
    (data_dir / "journal.jsonl").write_text(json.dumps({
        "at": "2026-01-01T00:00:00+00:00", "because": "sk-ant-not-a-real-key",
    }) + "\n", encoding="utf-8")  # fmt: skip
    clean, _counted = guard().look(a_repository(tmp_path / "second"), data_dir)
    assert not any("journal" in line for line in clean), clean


def test_a_secret_this_check_could_not_read_is_never_cleared(tmp_path: Path, monkeypatch):
    """Half a look is not a clearance, which is the rule the archive's own halves are read by.

    A connector's code secret this process cannot read is a secret nothing compared, and "Clean"
    over it says the opposite of what happened. Found by a mutation that dropped the line: every
    other test stayed green, because they all plant secrets this process can read.

    The failure is injected at the one line that reads, rather than by taking the permissions off
    the file. These tests run as root on this machine, and a mode denies root nothing — written
    that way the test would pass here while proving nothing, and prove something only on whatever
    machine happened to run pytest as somebody else. What it stands in for is ordinary: a file
    written by root with the group changed, read by a server that is no longer in that group.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    secrets_folder = tmp_path / "connector-secrets"
    secrets_folder.mkdir()
    shut = secrets_folder / "7a1b2c3d"
    shut.write_text("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP\n", encoding="utf-8")
    module = guard()
    module.SECRET_FOLDERS = (("a connector's code secret", str(secrets_folder)),)
    whole = Path.read_text

    def refusing(self, *args, **kwargs):
        if self == shut:
            raise PermissionError(13, "Permission denied")
        return whole(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", refusing)
    trouble, _counted = module.look(a_repository(tmp_path), data_dir)
    monkeypatch.undo()

    assert any("was not looked for" in line for line in trouble), trouble
    assert any("7a1b2c3d" in line for line in trouble), trouble


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


def test_the_served_path_of_a_live_link_is_looked_for(tmp_path: Path):
    """The half of a link that is meant to be copied, and was looked for nowhere.

    A link has two secrets and they are not alike. The code is shown once and kept in a file, so
    the folder of code secrets finds it. **The address is drawn on the editor page every single
    time** — that page exists for copying it and handing it to somebody — and a thing meant to be
    copied is a thing that ends up in a note, a message, a screenshot, a pasted log. One of those
    in a tracked file is a live credential in a public repository, and a commit is not withdrawn
    by deleting it afterwards.

    It was hidden by an accident: the instance that found this carried in the single secret from
    before the registry, so its path *was* the content of `/etc/epicrisis/mcp-token` and was found
    through that file. The first link issued on the page would have had no such cover.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    a_connector(data_dir, path="q" * 48)

    trouble, _counted = guard().look(
        a_repository(tmp_path, holding="ADDRESS = 'https://box.ts.net/mcp/" + "q" * 48 + "'\n"), data_dir)  # fmt: skip

    assert any("served path" in line for line in trouble), trouble
    # The id, so that a person is told which link to take back and not only that one escaped.
    assert any("7a1b2c3d" in line for line in trouble), trouble
    # And nothing of the secret itself, here as everywhere.
    assert not any("qqqq" in line for line in trouble), trouble


def test_a_revoked_link_s_path_is_not_refused(tmp_path: Path):
    """Because it opens nothing, and a guard that is wrong at every push is one people skip.

    The registry keeps a revoked line on purpose, so that the journal and the access log go on
    naming something. Refusing to publish over a string that no longer opens anything would be
    the guard crying wolf about its own bookkeeping.
    """
    data_dir = tmp_path / "data"
    an_archive(data_dir)
    a_connector(data_dir, path="r" * 48, revoked_at="2026-02-01T00:00:00+00:00")

    trouble, _counted = guard().look(
        a_repository(tmp_path, holding="OLD = '" + "r" * 48 + "'\n"), data_dir)  # fmt: skip

    assert not any("served path" in line for line in trouble), trouble
