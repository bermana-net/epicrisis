"""A keeper is known by a signature, the signature is not their name, and it says what they keep.

Every archive here has one — `419b84dd` names a folder of documents, the folder of everything read
out of it, and the index beside it — and it goes on naming them when the folder moves and when the
person is written another way. The keeper of an archive had nothing of the kind: `Source.owner` is
a name as somebody typed it, so two people of one name were one keeper and one person written two
ways were two. On an instance of one person that costs nothing; on one holding several it is one
person's records answered to somebody else, which is the first entry of the constitution.

The step before this one issued the signature and wrote the owner's name down beside it as a
proposal. **This step writes the link — which archives a keeper keeps — and takes the name back
out**, which is the same claim made twice ending as the same claim made once. So the tests here
come in two halves. The first is about the signature and has not changed: it is of the shape an
archive's id is, it is no function of anybody's name, and it does not move when a name does. The
second is about the link: there is one keeper to an instance, the archives are theirs, the list of
archives is still `sources.json`'s answer and the link is read against it, and one page shows it.

The promise measured at the end is the one this step is accepted on: a keeper written down moves
not one byte of any page of the dashboard but the settings page, which is the one place the owner
asked for it to be visible, and no signature reaches the bytes of any page at all.

The people here do not exist. Their names are the ones this project already invents elsewhere, so
that no new surname arrives with this file.
"""

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from epicrisis import journal, keepers, layout
from epicrisis.runs import Busy
from epicrisis.sources import Source, SourceRegistry
from epicrisis.state import Unreadable
from epicrisis.web.app import create_app
from epicrisis.web.settings_page import settings_view, who_this_instance_is_for

# Three people who do not exist, written the way a person writes a name into the owner's field.
VERA = "Vera Lindqvist"
ANDERS = "Anders Lindqvist"
ZOYA = "Zoya Kravets"
# The same person, written differently. One of this step's claims is that nothing here moves
# between these two spellings: not the signature, not the link.
OPANAS = "Opanas Zhuravskyi"
OPANAS_AGAIN = "O. Zhuravskyi"
# Every address of the dashboard that is drawn about somebody's records or about the instance.
EVERY_PAGE = ("/", "/status", "/documents", "/indicators", "/settings", "/who", "/card",
              "/review", "/misread", "/search", "/ask", "/consent", "/browse")  # fmt: skip


def an_instance(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def a_folder(tmp_path: Path, named: str) -> Path:
    folder = tmp_path / named
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def by_hand(data_dir: Path, owners: list[str]) -> list[dict]:
    """An instance as it stands today: archives whose owner was typed before keepers existed.

    Written as the file itself rather than through the registry, because that is the state the
    migration has to meet — a list of archives and no keepers.json beside it.
    """
    entries = [
        {"id": f"aa11bb{number:02d}", "name": f"folder-{number}", "path": f"/scans/folder-{number}",
         "added_at": "2026-01-01T00:00:00+00:00", "owner": owner, "active": number == 0}
        for number, owner in enumerate(owners)
    ]  # fmt: skip
    (data_dir / layout.SOURCES).write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return entries


def as_sources(entries: list[dict]) -> list[Source]:
    return [Source(**entry) for entry in entries]


def test_a_keeper_is_issued_a_signature_of_the_shape_an_archive_has(tmp_path: Path):
    """Four random bytes, as `SourceRegistry.add` issues an archive's id, and not the name again.

    The shape matters because it is the shape everything else here is filed under, and because it
    carries no part of anybody's name: a signature reaches a path, a URL and a line of a log.

    The last assertion is the subtraction this step is for. The file holds the name nowhere at
    all — not as a field, not inside any string of it — so there is no second copy of a person's
    name on this machine to drift away from the one they typed.
    """
    data_dir = an_instance(tmp_path)
    registry = SourceRegistry(data_dir)
    archive = registry.add(str(a_folder(tmp_path, "the-cardboard-box")), owner=VERA)

    issued = keepers.load(data_dir)
    assert len(issued) == 1
    signature = issued[0].id
    assert len(signature) == 2 * keepers.SIGNATURE_BYTES
    assert all(letter in "0123456789abcdef" for letter in signature)
    assert signature != archive.id, "a keeper is not the archive they keep"
    assert issued[0].archives == (archive.id,)
    # Not the name in any shape a program would reach for. This is the whole of "never worked out
    # from the name": a signature that is a function of the spelling moves when the spelling does.
    for shape in (VERA, VERA.lower(), VERA.replace(" ", ""), VERA.replace(" ", "-").lower()):
        assert shape not in signature and signature not in shape
    written = keepers.path(data_dir).read_text(encoding="utf-8")
    for part in (VERA, *VERA.split(), VERA.lower(), VERA.replace(" ", "")):
        assert part not in written, "the owner's name was copied into the keepers"


def test_the_signature_and_the_link_survive_a_change_of_the_owners_name(tmp_path: Path):
    """The claim of the step before, measured at the door a person actually presses.

    A person who marries, who corrects a letter, who writes their name in another alphabet is the
    same person, and every record of theirs stays filed under a string that knows nothing about
    how they are spelled. The step before held this by renaming a copy of the name kept beside the
    signature; there is no copy now, so it is held where it matters instead — `set_owner` is the
    one act that writes a person's name again, it writes it on the archive, and neither the
    signature nor the archives kept under it move when it does.
    """
    data_dir = an_instance(tmp_path)
    registry = SourceRegistry(data_dir)
    archive = registry.add(str(a_folder(tmp_path, "a-box-of-paper")), owner=OPANAS)
    before = keepers.load(data_dir)[0]

    registry.set_owner(archive.id, OPANAS_AGAIN)

    after = keepers.load(data_dir)
    assert [one.id for one in after] == [before.id], "the signature moved when the name did"
    assert after[0].archives == (archive.id,), "the link moved when the name did"
    assert after[0].issued_at == before.issued_at
    # The name every page prints is the archive's, and it is the one that changed.
    assert registry.get(archive.id).owner == OPANAS_AGAIN
    # And back again, which is the same claim from the other side.
    registry.set_owner(archive.id, OPANAS)
    assert [one.id for one in keepers.load(data_dir)] == [before.id]
    assert registry.get(archive.id).owner == OPANAS


def test_two_archives_of_one_spelling_are_one_keeper_and_say_nothing_about_the_two_names(tmp_path: Path):
    """One keeper keeps both, and nothing anywhere says the two owners are one person.

    The step before had to choose between two errors here — two keepers where one spelling stood
    for one person, or one keeper standing over two people — and that choice was forced by the
    keeper carrying a name. It carries none, so neither error is on the table: "these two archives
    are kept by one keeper" is a claim about who keeps them and not about who they are, and the
    two owners stay two strings that this program never compares.
    """
    data_dir = an_instance(tmp_path)
    registry = SourceRegistry(data_dir)
    hers = registry.add(str(a_folder(tmp_path, "her-own-scans")), owner=VERA)
    her_fathers = registry.add(str(a_folder(tmp_path, "the-scans-she-keeps-for-her-father")), owner=VERA)

    held = registry.as_one_reading()
    assert len(held.keepers) == 1, "a second keeper was issued for a second archive"
    assert [one.id for one in held.kept_by(held.keepers[0])] == [hers.id, her_fathers.id]
    assert VERA not in keepers.path(data_dir).read_text(encoding="utf-8")

    # And the same name on an instance of its own, because the assertion above can be had the
    # cheap way. A signature worked out from the name is the same string on every instance that
    # holds that name, and one instance cannot show it: two can.
    elsewhere = an_instance(tmp_path / "another-machine")
    SourceRegistry(elsewhere).add(str(a_folder(tmp_path / "another-machine", "her-own-scans")), owner=VERA)
    alone = keepers.load(elsewhere)

    assert len(alone) == 1
    assert alone[0].id != held.keepers[0].id, "the signature is a function of the name"


def test_the_names_already_typed_by_hand_are_left_exactly_where_they_are(tmp_path: Path):
    """The instance that exists: three archives with an owner typed before keepers were a thing.

    One keeper comes out of it, keeping all three, which is what the owner asked for in so many
    words — one person using this instance, every patient on it theirs to keep. And `sources.json`
    comes out byte for byte as it went in, because the names on it are a person's own work and
    this step has no business touching them, which is the eighth entry read at the end where their
    work is copied rather than at the end where it is read.
    """
    data_dir = an_instance(tmp_path)
    entries = by_hand(data_dir, [VERA, ANDERS, ZOYA])
    was = (data_dir / layout.SOURCES).read_bytes()

    # The migration is the first act that writes a name down on an instance with no keeper at all.
    written = keepers.catch_up(data_dir, as_sources(entries), as_sources(entries))

    assert len(written) == 1, "one instance, one keeper"
    assert written[0].archives == tuple(one["id"] for one in entries)
    assert (data_dir / layout.SOURCES).read_bytes() == was, "the list of archives was written to"
    kept_text = (data_dir / layout.KEEPERS).read_text(encoding="utf-8")
    for name in (VERA, ANDERS, ZOYA):
        assert name not in kept_text
    # Once. Asked again with nothing changed, it writes nothing and leaves the file alone.
    kept = (data_dir / layout.KEEPERS).read_bytes()
    assert keepers.catch_up(data_dir, as_sources(entries), as_sources(entries)) == []
    assert (data_dir / layout.KEEPERS).read_bytes() == kept


def test_an_archive_with_no_owner_is_kept_by_nobody_until_a_name_is_typed_on_it(tmp_path: Path):
    """An archive added with nobody's name beside it stays unkept, and joins when it is named.

    The trigger is the one the step before set and it is left where it is: the two acts that write
    a name down, and nothing else. A folder on the list with nobody's name against it is a folder
    somebody has not finished adding, and what is true of it — that no keeper keeps it — is what
    the page says about it.
    """
    data_dir = an_instance(tmp_path)
    registry = SourceRegistry(data_dir)
    archive = registry.add(str(a_folder(tmp_path, "scans-nobody-has-named-yet")))

    assert archive.owner == ""
    assert keepers.load(data_dir) == []
    assert not keepers.path(data_dir).exists(), "a file was written for a keeper that does not exist"
    assert [one.id for one in registry.as_one_reading().kept_by_nobody] == [archive.id]

    registry.set_owner(archive.id, ZOYA)

    held = registry.as_one_reading()
    assert len(held.keepers) == 1
    assert [one.id for one in held.kept_by(held.keepers[0])] == [archive.id]
    assert held.kept_by_nobody == ()


def test_correcting_the_spelling_of_an_owner_writes_nothing_here(tmp_path: Path):
    """A name typed again over a name is a correction, not a second person and not a new link.

    The archive's own owner is what changes, which is what every page draws, and the keepers' file
    stands exactly as it was — the same bytes, so not even a write of the same content, because a
    write moves the copy beside it and that copy is the one thing a person has to put back.
    """
    data_dir = an_instance(tmp_path)
    registry = SourceRegistry(data_dir)
    archive = registry.add(str(a_folder(tmp_path, "a-box-of-paper")), owner=OPANAS)
    kept = (data_dir / layout.KEEPERS).read_bytes()

    registry.set_owner(archive.id, OPANAS_AGAIN)

    assert registry.get(archive.id).owner == OPANAS_AGAIN
    assert (data_dir / layout.KEEPERS).read_bytes() == kept, "a correction reached the keepers"


def test_a_name_cleared_and_typed_again_writes_nothing_it_already_says(tmp_path: Path):
    """An archive is newly named twice and kept once, and the second time writes no file at all.

    Clearing a name and typing it again is the one way an archive can be newly named while a
    keeper already keeps it. The write that would follow puts the same bytes back — and moves the
    copy beside it, so the version before the last change would become a copy of the version that
    is, and the one thing a person has to put back would be gone. The guard is "nothing to add",
    not "write it anyway".
    """
    data_dir = an_instance(tmp_path)
    registry = SourceRegistry(data_dir)
    archive = registry.add(str(a_folder(tmp_path, "her-own-scans")), owner=VERA)
    kept = (data_dir / layout.KEEPERS).read_bytes()

    registry.set_owner(archive.id, "")
    registry.set_owner(archive.id, VERA)

    assert (data_dir / layout.KEEPERS).read_bytes() == kept
    assert not (data_dir / (layout.KEEPERS + ".previous")).exists(), "the copy to put back was overwritten"
    assert keepers.load(data_dir)[0].archives == (archive.id,)


def test_an_archive_named_later_joins_the_keeper_of_this_instance(tmp_path: Path):
    """A folder added a month after the rest is kept by the same keeper, and no second is issued.

    One keeper to an instance is the claim, and this is the claim on the second day rather than on
    the first: the archives accumulate on the keeper that is there, in the order they were named.
    """
    data_dir = an_instance(tmp_path)
    registry = SourceRegistry(data_dir)
    first = registry.add(str(a_folder(tmp_path, "her-own-scans")), owner=VERA)
    signature = keepers.load(data_dir)[0].id

    later = registry.add(str(a_folder(tmp_path, "his-own-scans")), owner=ANDERS)

    held = registry.as_one_reading()
    assert [one.id for one in held.keepers] == [signature], "a second keeper was issued"
    assert [one.id for one in held.kept_by(held.keepers[0])] == [first.id, later.id]
    assert held.kept_by_nobody == ()


def test_the_link_is_read_against_the_list_of_archives(tmp_path: Path):
    """Which archives exist is `sources.json`'s answer, and the link is never a second one.

    The first of this step's three borders, held in code rather than promised. An archive taken
    off the list leaves its id on the keeper's line — `remove` does not come here, and nothing
    asks it to — and that id names no archive from the moment it goes, so nothing returns it and
    no page can print it. The alternative is a second file answering "which archives are there",
    which is the defect this project spends its weeks removing.
    """
    data_dir = an_instance(tmp_path)
    registry = SourceRegistry(data_dir)
    hers = registry.add(str(a_folder(tmp_path, "her-own-scans")), owner=VERA)
    his = registry.add(str(a_folder(tmp_path, "his-own-scans")), owner=ANDERS)
    kept = (data_dir / layout.KEEPERS).read_bytes()

    registry.remove(his.id)

    held = registry.as_one_reading()
    assert [one.id for one in held.all] == [hers.id]
    assert [one.id for one in held.kept_by(held.keepers[0])] == [hers.id]
    assert (data_dir / layout.KEEPERS).read_bytes() == kept, "taking an archive off the list wrote here"
    assert his.id in keepers.load(data_dir)[0].archives, "the id was deleted rather than simply unused"


def test_the_link_says_nothing_about_which_archive_is_open(tmp_path: Path):
    """The second border: which archive is showing stays exactly where it was.

    One keeper keeping three archives is not three archives open. The answer to "which is open" is
    the field in `sources.json` and the one place that reads it, and writing the link down leaves
    both of them saying what they said.
    """
    data_dir = an_instance(tmp_path)
    registry = SourceRegistry(data_dir)
    hers = registry.add(str(a_folder(tmp_path, "her-own-scans")), owner=VERA)
    registry.add(str(a_folder(tmp_path, "his-own-scans")), owner=ANDERS)
    registry.set_active(hers.id)

    held = registry.as_one_reading()

    assert len(held.kept_by(held.keepers[0])) == 2
    assert held.showing_id == hers.id
    assert [one.id for one in held.open] == [hers.id], "a page would draw two people's archives"


def test_more_than_one_keeper_links_nothing_and_the_archive_shows_as_kept_by_nobody(tmp_path: Path):
    """Which of several keepers keeps a new archive is a question about people, so it is not taken.

    This code issues one keeper and cannot make a second, so the state is built here by hand — and
    the guard is written because the day a second keeper exists is the day a program picking one
    of them would be settling who somebody is. The fourth entry says who answers that, and it is
    not the program. What is left is visible on the page, which is the other half of that entry.
    """
    data_dir = an_instance(tmp_path)
    entries = by_hand(data_dir, [VERA])
    (data_dir / layout.KEEPERS).write_text(json.dumps([
        {"id": "aaaa0001", "issued_at": "2026-01-01T00:00:00+00:00", "archives": []},
        {"id": "aaaa0002", "issued_at": "2026-01-01T00:00:00+00:00", "archives": []},
    ]), encoding="utf-8")  # fmt: skip
    two = (data_dir / layout.KEEPERS).read_bytes()

    assert keepers.catch_up(data_dir, [], as_sources(entries)) == []

    assert (data_dir / layout.KEEPERS).read_bytes() == two, "a keeper was picked for the archive"
    held = SourceRegistry(data_dir).as_one_reading()
    assert [one.id for one in held.kept_by_nobody] == [entries[0]["id"]]
    assert who_this_instance_is_for(held)["keep_nothing"] == 2


def test_a_torn_list_of_keepers_is_refused_rather_than_written_over(tmp_path: Path):
    """The eighth entry: a reader that cannot parse raises, because every writer here is a rewrite.

    A signature is not something a person typed — but it is issued once and the one that comes
    back is a different string, and the archives written beside it are a statement nothing else
    holds, so answering "there are none" over a torn file would write that emptiness back. The
    refusal names the file, what has not been lost, and the one act that mends it.

    The second half is the shape of one line rather than of the whole file, and it is the same
    rule one level down: `"archives": "aa11bb00"` read as a list is eight archives of one letter
    each, which is an answer that is wrong rather than refused.
    """
    data_dir = an_instance(tmp_path)
    entries = by_hand(data_dir, [VERA, ANDERS])
    # Two writes, so that there is a version before the last change for the refusal to point at.
    keepers.catch_up(data_dir, [], as_sources(entries[:1]))
    keepers.catch_up(data_dir, as_sources(entries[:1]), as_sources(entries))
    whole = (data_dir / layout.KEEPERS).read_text(encoding="utf-8")
    (data_dir / layout.KEEPERS).write_text(whole[: len(whole) // 2], encoding="utf-8")
    torn = (data_dir / layout.KEEPERS).read_bytes()

    with pytest.raises(Unreadable) as broken:
        keepers.load(data_dir)
    assert broken.value.file == layout.KEEPERS
    assert "No archive has been touched and no name has been lost" in broken.value.safe
    assert f"mv {layout.KEEPERS}.previous {layout.KEEPERS}" in broken.value.mend

    # And the writer refuses there too, rather than reaching a write with a list built from nothing.
    with pytest.raises(Unreadable):
        keepers.catch_up(data_dir, [], as_sources(entries))
    assert (data_dir / layout.KEEPERS).read_bytes() == torn, "the torn file was written over"

    # A line of it that will not read as a line, which is the same refusal for a smaller reason.
    (data_dir / layout.KEEPERS).write_text(json.dumps([
        {"id": "aaaa0001", "issued_at": "2026-01-01T00:00:00+00:00", "archives": "aa11bb00"},
    ]), encoding="utf-8")  # fmt: skip
    with pytest.raises(Unreadable):
        keepers.load(data_dir)

    # Putting the copy back is the whole of the mending. It is the version before the last change,
    # which is what the refusal calls it: the archive linked by that last change is not on it, and
    # the next name typed links it again.
    (data_dir / (layout.KEEPERS + ".previous")).replace(data_dir / layout.KEEPERS)
    assert [one.archives for one in keepers.load(data_dir)] == [(entries[0]["id"],)]


def test_the_version_before_the_last_change_is_kept_beside_the_keepers(tmp_path: Path):
    """As sources.json and indicators.json keep theirs, and for the reason state.py gives."""
    data_dir = an_instance(tmp_path)
    registry = SourceRegistry(data_dir)
    first = registry.add(str(a_folder(tmp_path, "her-own-scans")), owner=VERA)
    one = (data_dir / layout.KEEPERS).read_text(encoding="utf-8")

    second = registry.add(str(a_folder(tmp_path, "his-own-scans")), owner=ANDERS)

    kept = data_dir / (layout.KEEPERS + ".previous")
    assert kept.exists() and kept.read_text(encoding="utf-8") == one
    assert keepers.load(data_dir)[0].archives == (first.id, second.id)
    assert registry.get(first.id).owner == VERA


def test_a_torn_list_of_keepers_does_not_stop_an_archive_being_added(tmp_path: Path):
    """A file no door opens an archive by may not be the reason a person cannot add documents.

    Adding a folder, and typing a name on it, are acts over the one file that ties somebody's
    folders to everything ever read from them. A keepers.json that will not parse is skipped,
    never written over, and written down in the journal — and the next name typed catches a mended
    file up by itself.
    """
    data_dir = an_instance(tmp_path)
    registry = SourceRegistry(data_dir)
    registry.add(str(a_folder(tmp_path, "her-own-scans")), owner=VERA)
    (data_dir / layout.KEEPERS).write_text('[{"id": "aa11', encoding="utf-8")
    torn = (data_dir / layout.KEEPERS).read_bytes()

    added = registry.add(str(a_folder(tmp_path, "his-own-scans")), owner=ANDERS)

    assert registry.get(added.id) is not None and registry.get(added.id).owner == ANDERS
    assert (data_dir / layout.KEEPERS).read_bytes() == torn, "the torn file was written over"
    said = [line for line in journal.entries(data_dir) if line.get("file") == layout.KEEPERS]
    assert said and said[-1]["event"] == "a keeper could not be given a signature"
    assert "Lindqvist" not in json.dumps(said, ensure_ascii=False), "a name reached the journal"


def test_a_torn_list_of_keepers_does_not_stop_the_archives_being_listed(tmp_path: Path):
    """One reading of the two files, and the one that nothing opens an archive by cannot stop it.

    `None` and "there are no keepers" are two different answers and this is where the difference
    is made: every archive is listed, which is the reading a page is drawn from, and the page that
    shows the keepers is told the file would not read rather than shown an empty list — a switch
    drawn at its default over an unreadable file is the failure the settings page has already had.
    """
    data_dir = an_instance(tmp_path)
    entries = by_hand(data_dir, [VERA, ANDERS])
    (data_dir / layout.KEEPERS).write_text('[{"id": "aa11', encoding="utf-8")

    held = SourceRegistry(data_dir).as_one_reading()

    assert [one.id for one in held.all] == [one["id"] for one in entries]
    assert held.showing_id == entries[0]["id"]
    assert held.keepers is None, "an unreadable file was read as no keepers at all"
    assert who_this_instance_is_for(held)["unreadable"] is True
    assert who_this_instance_is_for(held)["keepers"] == []


def test_the_archives_and_their_keepers_come_out_of_one_reading(tmp_path: Path):
    """The trap the step before named: two files, and no atomic read across them.

    A page that read the list of archives and then the keepers would be two readings inside one
    answer, and the archive is switchable from the bar of every page by an ordinary POST the
    server answers on another thread. `TheArchives` exists to make that impossible by being a
    value, and the keepers are carried in it for that reason and no other.

    Measured by taking both files off the disk afterwards. Whatever the held value still answers,
    it answered out of the one reading; anything that went back to the disk would raise or come
    back empty here.
    """
    data_dir = an_instance(tmp_path)
    registry = SourceRegistry(data_dir)
    hers = registry.add(str(a_folder(tmp_path, "her-own-scans")), owner=VERA)
    his = registry.add(str(a_folder(tmp_path, "his-own-scans")), owner=ANDERS)

    held = registry.as_one_reading()
    (data_dir / layout.SOURCES).unlink()
    (data_dir / layout.KEEPERS).unlink()

    assert [one.id for one in held.all] == [hers.id, his.id]
    assert held.showing_id == hers.id
    assert len(held.keepers) == 1
    assert [one.id for one in held.kept_by(held.keepers[0])] == [hers.id, his.id]
    assert held.kept_by_nobody == ()
    assert who_this_instance_is_for(held)["keepers"] == [{"archives": [VERA, ANDERS]}]


def test_the_settings_page_says_who_this_instance_is_for(tmp_path: Path):
    """The one page that shows the link, in the words it says it, and with no signature in it.

    The owner asked for the link to be visible in a settings window. It shows and it decides
    nothing: the names under it are the owners as they were typed on the archives, which is the
    one place a name is kept, and what the block is for is that a grouping nobody can read is a
    grouping nobody can see is wrong.
    """
    data_dir = an_instance(tmp_path)
    entries = by_hand(data_dir, [VERA, ANDERS, ZOYA])
    keepers.catch_up(data_dir, as_sources(entries), as_sources(entries))
    registry = SourceRegistry(data_dir)

    shown = settings_view(data_dir, registry.as_one_reading())["keeping"]

    assert shown == {"unreadable": False, "written_down": True,
                     "keepers": [{"archives": [VERA, ANDERS, ZOYA]}],
                     "nobody": [], "keep_nothing": 0}  # fmt: skip

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050",
                        raise_server_exceptions=False)  # fmt: skip
    page = client.get("/settings").content.decode("utf-8")

    assert "Who this instance is for" in page
    assert "keeps 3 archives: Vera Lindqvist, Anders Lindqvist, Zoya Kravets" in page
    # Shortened on 7 Oct 2026 and kept: half that paragraph explained what the block is *not*,
    # which is a paragraph about the absence of a thing nobody was promised — but this part of it
    # is the part a reader can get wrong, so it stays as one clause rather than three sentences.
    assert "It is a grouping and nothing else" in page
    assert "it does not say which archive is open" in page
    assert keepers.load(data_dir)[0].id not in page, "the settings page prints a signature"
    # Nothing on it is a press: the window is outside the form and names no field of its own.
    assert 'name="keeper' not in page


def test_the_settings_page_says_nothing_where_no_keeper_has_been_written_down(tmp_path: Path):
    """An instance from before keepers existed reads exactly as it did, which is this step's test.

    On such an instance the link has not been written, and the honest thing to draw about a thing
    that is not written down is nothing. It also means that the day this version is installed, not
    one page of anybody's dashboard says a word it did not say the day before.
    """
    data_dir = an_instance(tmp_path)
    by_hand(data_dir, [VERA, ANDERS, ZOYA])
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050",
                        raise_server_exceptions=False)  # fmt: skip

    page = client.get("/settings").content.decode("utf-8")

    assert not keepers.path(data_dir).exists()
    assert who_this_instance_is_for(SourceRegistry(data_dir).as_one_reading())["written_down"] is False
    assert "Who this instance is for" not in page
    assert "Kept by nobody" not in page


def test_a_keeper_from_before_the_link_keeps_nothing_and_the_page_says_so(tmp_path: Path):
    """A file written by the step that issued signatures and wrote down no link at all.

    No released version of this program ever wrote one, so the only such file is on a machine that
    ran the commit between the two steps. It is not written over and the name on it is not read:
    what the page says is that those keepers keep no archive on the list, that nothing is lost,
    and the one act that starts it again. A dead end with no way out is a defect.
    """
    data_dir = an_instance(tmp_path)
    entries = by_hand(data_dir, [VERA, ANDERS])
    (data_dir / layout.KEEPERS).write_text(json.dumps([
        {"id": "aaaa0001", "name": VERA, "issued_at": "2026-01-01T00:00:00+00:00"},
    ]), encoding="utf-8")  # fmt: skip
    before = (data_dir / layout.KEEPERS).read_bytes()

    held = SourceRegistry(data_dir).as_one_reading()

    assert held.keepers[0].archives == (), "a link was invented for a keeper that has none"
    assert [one.whose for one in held.kept_by_nobody] == [VERA, ANDERS]
    assert (data_dir / layout.KEEPERS).read_bytes() == before

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050",
                        raise_server_exceptions=False)  # fmt: skip
    page = client.get("/settings").content.decode("utf-8")

    assert "1 keeper keeps no archive that is on the list" in page
    # Under a summary now, not gone: the count stays in the open because a page showing fewer
    # keepers than the file holds disagrees with itself, and the way to start the list again is a
    # question, which belongs under the question.
    assert "Why, and how to start that list again" in page
    assert "delete <code>data/keepers.json</code>" in page
    assert f"Kept by nobody: {VERA}, {ANDERS}" in page


def test_a_keeper_is_written_by_one_hand_at_a_time(tmp_path: Path):
    """The lock people.py and indicators.py hold across the read, for the same read-modify-write.

    Held by somebody else, a writer refuses with Busy and touches nothing, rather than reading a
    list that another hand is about to replace.
    """
    data_dir = an_instance(tmp_path)
    entries = by_hand(data_dir, [VERA])

    with keepers.editing(data_dir):
        with pytest.raises(Busy):
            keepers.catch_up(data_dir, [], as_sources(entries))
    assert not keepers.path(data_dir).exists()

    assert keepers.catch_up(data_dir, [], as_sources(entries))[0].archives == (entries[0]["id"],)


def test_no_page_of_the_dashboard_moves_when_a_keeper_is_written_down(tmp_path: Path):
    """The promise of this step, measured where it can be seen: every page, before and after.

    A keeper and the archives they keep are written on this step, and one page shows it. So every
    page of the dashboard but that one has to come back byte for byte as it was with no keeper on
    the list — and not one of them, the settings page included, may carry a signature anywhere in
    its bytes. The step that gives a signature to a door is the step that rewrites this test, and
    it should have to.
    """
    data_dir = an_instance(tmp_path)
    entries = by_hand(data_dir, [VERA, ANDERS, ZOYA])
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050",
                        raise_server_exceptions=False)  # fmt: skip
    before = {address: client.get(address).content for address in EVERY_PAGE}
    assert all(answer for answer in before.values())

    written = keepers.catch_up(data_dir, as_sources(entries), as_sources(entries))

    assert len(written) == 1 and len(written[0].archives) == 3, "nothing was written down, so this says nothing"
    for address in EVERY_PAGE:
        answer = client.get(address).content
        if address == "/settings":
            assert answer != before[address], "the one page that shows it did not change"
            continue
        assert answer == before[address], address
    # Nor is a signature anywhere in the bytes of any of them, the settings page included.
    for address in EVERY_PAGE:
        assert written[0].id.encode() not in client.get(address).content, f"{address} prints a signature"


def test_one_press_of_save_on_the_settings_page_writes_nothing_here(tmp_path: Path):
    """Showing is not deciding, measured at the press that stands on the same page.

    The window is drawn outside the form and has no field of its own, so a press of Save carries
    nothing about a keeper and cannot. What this holds is the stronger thing: the file is not
    written at all, not even with the same bytes, because a write moves the copy beside it.
    """
    data_dir = an_instance(tmp_path)
    entries = by_hand(data_dir, [VERA, ANDERS])
    keepers.catch_up(data_dir, as_sources(entries), as_sources(entries))
    before = (data_dir / layout.KEEPERS).read_bytes()
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050",
                        raise_server_exceptions=False)  # fmt: skip

    pressed = client.post("/settings", data={"tab": "model"}, follow_redirects=False)

    assert pressed.status_code in (200, 303)
    assert (data_dir / layout.KEEPERS).read_bytes() == before, "a press of Save reached the keepers"
    assert not (data_dir / (layout.KEEPERS + ".previous")).exists()
