"""The six presses on the list of archives, asked directly: what each stored and what it refused.

All six used to be routes, so the two that can refuse could only be read out of a drawn status
page: a folder offered with nobody's name on it, and an archive something else is holding — whose
sentence names the lock in the way and the file to delete, and which was once the whole advice
"wait for it to finish" over a lock left behind by a run that had died.

Two of the six read the list again on purpose after writing it, which is the other thing a test
over HTTP could not tell apart from a reading somebody forgot. Both are asked here.

`epicrisis/web/the_list_of_archives.py` is where those are decided now.
"""

import ast
import inspect
import json
import os

import pytest

from epicrisis import layout
from epicrisis.runs import ABANDONED_AFTER_HOURS
from epicrisis.sources import SourceRegistry, source_output_dir
from epicrisis.web import the_list_of_archives as the_list

#: The owner these tests name. One of the two of the sweep that guards the wall, so no name is
#: invented here at all.
WHOSE = "Zoryana Vdovychenko"


@pytest.fixture
def an_instance(tmp_path):
    """A data directory, and a folder that could be an archive but is not on the list yet."""
    data_dir = tmp_path / "project" / "data"
    folder = tmp_path / "a box of scans"
    folder.mkdir(parents=True)
    (folder / "a page.txt").write_text("a line of this test", encoding="utf-8")
    return SourceRegistry(data_dir), folder


def test_a_folder_offered_with_nobodys_name_on_it_is_refused_out_loud(an_instance):
    """Whose records these are is not decoration: every page carries the name and every answer
    the tools give says it, and the reading starts the moment an archive is added."""
    registry, folder = an_instance

    pressed = the_list.added(registry, path=str(folder), owner="   ")

    assert pressed.stored == () and pressed.started is None
    assert pressed.refused == (the_list.SAY_WHOSE,)
    assert pressed.code == 400, "a refusal is the page again, and says which page it is"
    assert registry.list() == [], "a refused press put an archive on the list"


def test_a_folder_that_is_not_there_is_refused_in_the_registry_own_words(an_instance):
    registry, folder = an_instance

    pressed = the_list.added(registry, path=str(folder / "no such folder"), owner=WHOSE)

    assert pressed.stored == () and pressed.code == 400
    assert len(pressed.refused) == 1 and pressed.refused[0], "the refusal says nothing at all"
    assert registry.list() == []


def test_the_first_archive_added_is_the_one_that_is_open(an_instance):
    """Read again, and it has to be: the list was just written to, and any reading decided before
    the press is the one from before the archive was added."""
    registry, folder = an_instance

    pressed = the_list.added(registry, path=str(folder), owner=WHOSE)

    assert pressed.refused == () and pressed.code == 0
    assert pressed.stored == ("an archive added to the list",)
    assert pressed.started is not None, "the archive whose reading is to begin came back as none"
    assert [one.id for one in registry.list()] == [pressed.started.id]
    assert registry.as_one_reading().showing_id == pressed.started.id


def test_a_second_archive_added_does_not_take_the_page_off_the_first(an_instance):
    registry, folder = an_instance
    first = the_list.added(registry, path=str(folder), owner=WHOSE).started
    beside = folder.parent / "another box of scans"
    beside.mkdir()
    (beside / "a page.txt").write_text("another line of this test", encoding="utf-8")

    second = the_list.added(registry, path=str(beside), owner="Opanas Zhuravskyi").started

    assert registry.as_one_reading().showing_id == first.id
    assert {one.id for one in registry.list()} == {first.id, second.id}


def test_switching_which_archive_is_shown_writes_both_ids_and_no_name(an_instance):
    """The act the first line of the constitution is about, and the switch used to leave no trace
    anywhere — so if one person's screen shows another person's doctors again, nothing could say
    which archive was open when. Ids only: the folder names carry surnames."""
    registry, folder = an_instance
    first = the_list.added(registry, path=str(folder), owner=WHOSE).started
    beside = folder.parent / "another box of scans"
    beside.mkdir()
    (beside / "a page.txt").write_text("another line of this test", encoding="utf-8")
    second = the_list.added(registry, path=str(beside), owner="Opanas Zhuravskyi").started

    pressed = the_list.shown_instead(registry, registry.as_one_reading(), second.id)

    assert pressed.stored == ("the archive shown was switched",) and pressed.refused == ()
    assert registry.as_one_reading().showing_id == second.id
    written = [json.loads(line) for line
               in (registry.data_dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()]  # fmt: skip
    switched = [one for one in written if one["event"] == "the archive shown was switched"]
    assert switched[-1]["archive"] == second.id and switched[-1]["instead_of"] == first.id
    assert WHOSE not in json.dumps(switched, ensure_ascii=False), "the journal holds a person's name"


def test_the_first_switch_of_an_instance_says_there_was_nothing_before_it(an_instance):
    """`instead_of` is left out rather than written empty: an instance with nothing open yet is a
    different thing from one switching away from an archive named by the empty string."""
    registry, folder = an_instance
    added = the_list.added(registry, path=str(folder), owner=WHOSE).started
    (registry.data_dir / "journal.jsonl").unlink(missing_ok=True)

    the_list.shown_instead(registry, SourceRegistry(registry.data_dir).as_one_reading(), added.id)
    line = json.loads((registry.data_dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert line["archive"] == added.id and line["instead_of"] == added.id

    # And with nothing on the list at all, the field is simply not there.
    empty = SourceRegistry(registry.data_dir.parent / "another instance" / "data")
    empty.data_dir.mkdir(parents=True)
    the_list.shown_instead(empty, empty.as_one_reading(), "an archive that is not here")
    said = json.loads((empty.data_dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert "instead_of" not in said


def test_whose_an_archive_is_can_be_said_again(an_instance):
    registry, folder = an_instance
    added = the_list.added(registry, path=str(folder), owner=WHOSE).started

    pressed = the_list.owner_named(registry, added.id, owner="Opanas Zhuravskyi")

    assert pressed.stored == ("whose an archive is",) and pressed.refused == ()
    assert registry.get(added.id).owner == "Opanas Zhuravskyi"


def test_reading_an_archive_again_from_nothing_needs_the_word_asked_for(an_instance):
    """The page asks a person to type it, and a press arriving without it changed nothing — which
    is what it has to go on doing, because what this moves is hours of a model's reading."""
    registry, folder = an_instance
    added = the_list.added(registry, path=str(folder), owner=WHOSE).started
    output = source_output_dir(registry.data_dir, added.id)
    output.mkdir(parents=True, exist_ok=True)
    (output / layout.INVENTORY).write_text('{"sha256": "a", "path": "a page.txt"}\n', encoding="utf-8")

    pressed = the_list.read_again_from_nothing(registry, added.id, understood="")

    assert pressed.stored == () and pressed.refused == () and pressed.moved_aside is None
    assert (output / layout.INVENTORY).exists(), "a press that asked for nothing moved the reading"


def test_a_lock_in_the_way_is_named_and_the_reading_is_not_moved(an_instance):
    """"Wait for it to finish" was the whole of this answer, and over a lock left behind by a run
    that had died it was advice to wait for ever — under the one button that would have put the
    archive back in order. Every lock in the folder, not a list of three by name."""
    registry, folder = an_instance
    added = the_list.added(registry, path=str(folder), owner=WHOSE).started
    output = source_output_dir(registry.data_dir, added.id)
    output.mkdir(parents=True, exist_ok=True)
    (output / layout.INVENTORY).write_text('{"sha256": "a", "path": "a page.txt"}\n', encoding="utf-8")
    # A lock held by this very process, which is alive by definition while the test runs. Named
    # for the step whose absence from the old list of three was the finding: the date search.
    held = output / "datesearch.lock"
    held.write_text(json.dumps({"pid": os.getpid(), "started_at": "2026-10-04T00:00:00+00:00"}),
                    encoding="utf-8")  # fmt: skip

    pressed = the_list.read_again_from_nothing(registry, added.id, understood="yes")

    assert pressed.stored == () and pressed.moved_aside is None
    assert pressed.code == 409, "something else holding the archive is not a form that was wrong"
    assert pressed.trouble.startswith(the_list.SOMETHING_IS_READING)
    assert "datesearch.lock" in pressed.trouble, "the refusal does not name the lock in the way"
    assert "deleting it lets this archive be read again" in pressed.trouble
    assert f"older than {ABANDONED_AFTER_HOURS} hours" in pressed.trouble
    assert (output / layout.INVENTORY).exists(), "the reading was moved out from under a run"


def test_the_reading_is_moved_aside_and_the_press_says_where(an_instance):
    """§8: a person's own work is never overwritten by what could not be read, and the hours
    behind a reading are moved and kept rather than removed. The page says where it went, so the
    press has to hand the path back."""
    registry, folder = an_instance
    added = the_list.added(registry, path=str(folder), owner=WHOSE).started
    output = source_output_dir(registry.data_dir, added.id)
    output.mkdir(parents=True, exist_ok=True)
    (output / layout.INVENTORY).write_text('{"sha256": "a", "path": "a page.txt"}\n', encoding="utf-8")

    pressed = the_list.read_again_from_nothing(registry, added.id, understood="yes")

    assert pressed.stored == ("the reading of an archive put aside",)
    assert pressed.refused == () and pressed.code == 0
    assert pressed.nothing_to_move is False
    assert pressed.moved_aside is not None and pressed.moved_aside.is_dir()
    assert (pressed.moved_aside / layout.INVENTORY).exists(), "the reading was not kept"
    assert not (output / layout.INVENTORY).exists(), "the reading was not put aside"
    assert registry.get(added.id) is not None, "the archive came off the list as well"


def test_an_archive_nothing_has_been_read_from_is_its_own_answer(an_instance):
    """And not an empty path: the page says which of the two it was, so they are two fields."""
    registry, folder = an_instance
    added = the_list.added(registry, path=str(folder), owner=WHOSE).started

    pressed = the_list.read_again_from_nothing(registry, added.id, understood="yes")

    assert pressed.nothing_to_move is True and pressed.moved_aside is None
    assert pressed.stored == ("the reading of an archive put aside",)


def test_taking_the_open_archive_off_the_list_opens_another(an_instance):
    """Read again, and deliberately: the list was just written to, so anything decided before
    this press still holds the archive that has gone and still calls it the open one."""
    registry, folder = an_instance
    first = the_list.added(registry, path=str(folder), owner=WHOSE).started
    beside = folder.parent / "another box of scans"
    beside.mkdir()
    (beside / "a page.txt").write_text("another line of this test", encoding="utf-8")
    second = the_list.added(registry, path=str(beside), owner="Opanas Zhuravskyi").started
    assert registry.as_one_reading().showing_id == first.id

    pressed = the_list.taken_off_the_list(registry, first.id)

    assert pressed.stored == ("an archive taken off the list",)
    assert [one.id for one in registry.list()] == [second.id]
    assert registry.as_one_reading().showing_id == second.id, "nothing was left open"
    # And written down, not answered by the fallback. "None is marked" is a state the list is in
    # between adding the first archive and anything choosing it, and `_the_open_one` answers it
    # with the first on the list — so an instance that never wrote the choice reads the same as
    # one that did, until a second archive is added and the answer silently moves. That is why
    # the press reads the list again after writing it, deliberately, and this is the assertion
    # that holds the second reading: the file itself says which archive is open.
    written = json.loads((registry.data_dir / "sources.json").read_text(encoding="utf-8"))
    assert [one["id"] for one in written if one.get("active")] == [second.id], (
        "the archive left open is not marked open in the list")


def test_taking_the_last_archive_off_the_list_leaves_nothing_open(an_instance):
    registry, folder = an_instance
    only = the_list.added(registry, path=str(folder), owner=WHOSE).started

    pressed = the_list.taken_off_the_list(registry, only.id)

    assert pressed.stored == ("an archive taken off the list",)
    assert registry.list() == [] and registry.as_one_reading().showing_id is None


def test_an_address_naming_no_archive_takes_nothing_off_and_stores_nothing(an_instance):
    registry, folder = an_instance
    the_list.added(registry, path=str(folder), owner=WHOSE)

    pressed = the_list.taken_off_the_list(registry, "no-such-archive-anywhere")

    assert pressed.stored == () and pressed.refused == ()
    assert len(registry.list()) == 1


def test_looking_through_a_folder_again_is_an_act_on_the_list(an_instance):
    """So it is about the id in the address, read off the list afresh, and not about the archive
    that happens to be open: this is the exception the status page makes for itself."""
    registry, folder = an_instance
    first = the_list.added(registry, path=str(folder), owner=WHOSE).started
    beside = folder.parent / "another box of scans"
    beside.mkdir()
    (beside / "a page.txt").write_text("another line of this test", encoding="utf-8")
    second = the_list.added(registry, path=str(beside), owner="Opanas Zhuravskyi").started
    assert registry.as_one_reading().showing_id == first.id

    pressed = the_list.looked_through_again(registry, second.id)

    assert pressed.started is not None and pressed.started.id == second.id
    assert pressed.stored == ("a folder looked through again",)

    nowhere = the_list.looked_through_again(registry, "no-such-archive-anywhere")
    assert nowhere.started is None and nowhere.stored == ()


def test_every_press_names_which_archive_with_no_default(an_instance):
    """The first entry of the constitution, as these six take it: the archive is the id out of the
    address, because these presses may be about an archive that is not the open one — and the one
    that has to know which was open takes that reading, also with no default."""
    registry, _folder = an_instance
    by_id = (the_list.owner_named, the_list.read_again_from_nothing, the_list.taken_off_the_list,
             the_list.looked_through_again)  # fmt: skip
    for press in by_id:
        asked = inspect.signature(press).parameters
        assert asked["source_id"].default is inspect.Parameter.empty, press.__name__
        assert asked["registry"].default is inspect.Parameter.empty, press.__name__
        with pytest.raises(TypeError):
            press(registry)
    switching = inspect.signature(the_list.shown_instead).parameters
    for name in ("registry", "archives", "source_id"):
        assert switching[name].default is inspect.Parameter.empty, name
    with pytest.raises(TypeError):
        the_list.shown_instead(registry)


def test_nothing_in_this_module_knows_about_the_web():
    """The routes are the shells, read off the imports rather than the text."""
    reached = set()
    for node in ast.walk(ast.parse(inspect.getsource(the_list))):
        if isinstance(node, ast.Import):
            reached |= {one.name for one in node.names}
        elif isinstance(node, ast.ImportFrom):
            reached.add(node.module or "")
    assert reached
    for name in sorted(reached):
        assert name.split(".")[0] in ("epicrisis", "dataclasses", "pathlib"), name
