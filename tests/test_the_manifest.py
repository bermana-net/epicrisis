"""The manifest of published pictures, and the three scripts that write into it.

docs/images/taken-from-the-demo.json declares by hash every picture and PDF this project
publishes, and tools/nothing-of-yours.py refuses to publish anything that is not in it — reading
every version of every picture the history holds, not only the file in the tree. A hash dropped
out of that file is therefore a picture already published, in every clone, that the guard now
refuses and nobody can unpublish.

Three scripts print such pictures, and each of them used to write the whole file. The page shooter
ended by setting "pictures" to exactly what that run photographed, which crossed out the three
entries the one-pager script keeps there — the two sheet previews and the chart on the clinics
sheet — and left their hashes nowhere, because the loop that fills "earlier" walks only the names
of the run. The hashes had to be put back by hand, 26 of them. Nothing here is run against the
real manifest: every test writes a manifest of its own in a temporary folder.
"""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load(where: str, called: str):
    """One of these scripts, loaded from its path: tools/ is not a package and the names are hyphenated.

    Registered under its name before it runs, because each script imports the one writer by name
    and a second copy of that module would raise a CannotRead this file could not catch: the two
    classes look identical and are not the same class.
    """
    spec = importlib.util.spec_from_file_location(called, ROOT / where)
    module = importlib.util.module_from_spec(spec)
    sys.modules[called] = module
    spec.loader.exec_module(module)
    return module


the_manifest = load("tools/the_manifest.py", "the_manifest")
shooter = load("docs/take-the-pictures.py", "take_the_pictures")
sheets = load("tools/make-one-pager.py", "make_one_pager")
mark = load("tools/make-og-image.py", "make_og_image")
guard = load("tools/nothing-of-yours.py", "nothing_of_yours")

PAGE = b"\x89PNG the timeline of an invented archive\n"
LANES = b"\x89PNG the same archive in lanes\n"
AGAIN = b"\x89PNG the timeline, photographed again\n"
PREVIEW = b"\x89PNG the first page of the sheet for insurers\n"
CHART = b"\x89PNG one test over thirteen years\n"
SHEET = b"%PDF the sheet for insurers\n"
MARK = b"\x89PNG the picture a shared link shows\n"
BEFORE = b"\x89PNG the timeline as it was two releases ago\n"

A_NOTE = ("Written by hand for the set already published, which this check arrived after. "
          "Nobody real was open in the instance these were taken from.")  # fmt: skip


def sha256(bytes_of_it: bytes) -> str:
    return hashlib.sha256(bytes_of_it).hexdigest()


def read(manifest: Path) -> dict:
    return json.loads(manifest.read_text(encoding="utf-8"))


def a_plan(*names: str) -> list[tuple]:
    """Rows of the shape docs/take-the-pictures.py plans its shots in: name, whose, path, height, first."""
    return [(name, "whoever", f"/{name}", 1000, None) for name in names]


@pytest.fixture
def published(tmp_path: Path) -> dict:
    """A folder and a manifest with all three hands in them, as the real ones have.

    Two pictures of demo pages, which the page shooter takes; a sheet, its preview and the chart
    on the other sheet, which the one-pager script and a hand put there; the picture a shared link
    shows, which the third script prints. Plus a version of one page that an earlier run
    displaced, and the note written by hand about the set published before any of this existed.
    """
    repo = tmp_path / "repo"
    images = repo / "docs" / "images"
    images.mkdir(parents=True)
    for where, bytes_of_it in (
        (images / "01-timeline.png", PAGE),
        (images / "02-lanes.png", LANES),
        (images / "one-pager.png", PREVIEW),
        (images / "clinics-chart.png", CHART),
        (repo / "docs" / "epicrisis-for-underwriting.pdf", SHEET),
        (repo / "docs" / "og.png", MARK),
    ):
        where.write_bytes(bytes_of_it)
    manifest = images / "taken-from-the-demo.json"
    manifest.write_text(json.dumps({
        "of": {"invented": True, "lives": ["Vera Lindqvist"]},
        "how": A_NOTE,
        "pictures": {"01-timeline.png": sha256(PAGE), "02-lanes.png": sha256(LANES),
                     "one-pager.png": sha256(PREVIEW), "clinics-chart.png": sha256(CHART)},  # fmt: skip
        "not_of_a_page": {"docs/epicrisis-for-underwriting.pdf": sha256(SHEET),
                          "docs/og.png": sha256(MARK)},  # fmt: skip
        "earlier": {"01-timeline.png": [sha256(BEFORE)]},
    }, indent=1) + "\n", encoding="utf-8")
    return {"repo": repo, "images": images, "manifest": manifest,
            "of": {"invented": True, "lives": ["Vera Lindqvist"]}}  # fmt: skip


def the_sheet(published: dict) -> dict:
    """The row tools/make-one-pager.py hands its writer: the page printed from, the PDF, the preview."""
    return {"insurance": (published["repo"] / "tools" / "one-pager.html",
                          published["repo"] / "docs" / "epicrisis-for-underwriting.pdf",
                          published["images"] / "one-pager.png")}  # fmt: skip


def test_a_run_of_the_page_shooter_leaves_the_other_writers_entries(published: dict):
    """The loss this was written for: 26 hashes restored by hand after one run of the shooter.

    It set "pictures" to what it had just photographed, so the sheet preview and the chart went
    out of the list, and out of "earlier" too — that loop walks only the names of the run.
    """
    shooter.write_down(published["images"], a_plan("01-timeline", "02-lanes"),
                       ["01-timeline.png", "02-lanes.png"], published["of"])  # fmt: skip

    written = read(published["manifest"])
    assert written["pictures"]["one-pager.png"] == sha256(PREVIEW)
    assert written["pictures"]["clinics-chart.png"] == sha256(CHART)
    assert written["not_of_a_page"] == {"docs/epicrisis-for-underwriting.pdf": sha256(SHEET),
                                        "docs/og.png": sha256(MARK)}  # fmt: skip
    # The note about the set published before this check existed is the only record of how that
    # set was accounted for, and a run of the shooter dropped it along with the hashes.
    assert written["how"] == A_NOTE
    assert written["earlier"]["01-timeline.png"] == [sha256(BEFORE)]


def test_a_run_of_the_sheets_leaves_the_pictures_of_the_pages_declared(published: dict):
    """And the other way round, which the one-pager script got right and is now the same code."""
    sheets.write_down(the_sheet(published), manifest=published["manifest"], root=published["repo"])

    written = read(published["manifest"])
    assert written["pictures"]["01-timeline.png"] == sha256(PAGE)
    assert written["pictures"]["02-lanes.png"] == sha256(LANES)
    assert written["pictures"]["clinics-chart.png"] == sha256(CHART)
    assert written["not_of_a_page"]["docs/og.png"] == sha256(MARK)
    assert written["how"] == A_NOTE


def test_a_run_of_the_shared_picture_leaves_everything_else_declared(published: dict):
    """The third writer, which the card about this did not know was there."""
    mark.write_down(picture=published["repo"] / "docs" / "og.png", manifest=published["manifest"])

    written = read(published["manifest"])
    assert written["pictures"]["01-timeline.png"] == sha256(PAGE)
    assert written["pictures"]["one-pager.png"] == sha256(PREVIEW)
    assert written["not_of_a_page"]["docs/epicrisis-for-underwriting.pdf"] == sha256(SHEET)


def test_the_hash_a_new_picture_displaces_is_kept(published: dict):
    """A picture taken again leaves its old bytes in the history, published to everybody."""
    (published["images"] / "01-timeline.png").write_bytes(AGAIN)

    shooter.write_down(published["images"], a_plan("01-timeline"), ["01-timeline.png"], published["of"])

    written = read(published["manifest"])
    assert written["pictures"]["01-timeline.png"] == sha256(AGAIN)
    assert written["earlier"]["01-timeline.png"] == [sha256(BEFORE), sha256(PAGE)]


def test_a_picture_gone_from_the_tree_keeps_its_hash_under_earlier(published: dict):
    """Nothing that goes out of the tree goes out of the manifest.

    The file removed today is still in every commit that held it, and the guard reads every
    version it finds there. A name simply deleted from "pictures" is the published picture the
    guard then refuses, with nothing left anywhere saying what its hash was.
    """
    (published["images"] / "02-lanes.png").unlink()

    said = shooter.write_down(published["images"], a_plan("01-timeline", "02-lanes"),
                              ["01-timeline.png"], published["of"])  # fmt: skip

    written = read(published["manifest"])
    assert "02-lanes.png" not in written["pictures"]
    assert written["earlier"]["02-lanes.png"] == [sha256(LANES)]
    assert any("02-lanes.png" in line and "earlier" in line for line in said), said
    # And in the guard's own terms, which is the only judgement that counts: that version of that
    # name is still declared, so the commits holding it are still publishable.
    assert guard._declared(written["earlier"], "02-lanes.png", sha256(LANES))


def test_a_shot_the_run_could_not_take_keeps_its_declaration(published: dict):
    """A shot missed is not a picture withdrawn, and not a picture blessed either.

    The archive photographed may have no document in one of the languages, and that shot is
    reported and skipped while the picture from the last run stays in the folder and stays
    published. Its hash must stand — and the bytes on disk must not be read, because a page of
    somebody's own archive left there under that name would otherwise be hashed and declared as
    taken from the demo by the very run that skipped it.
    """
    (published["images"] / "02-lanes.png").write_bytes(b"\x89PNG something nobody here photographed\n")

    shooter.write_down(published["images"], a_plan("01-timeline", "02-lanes"),
                       ["01-timeline.png"], published["of"])  # fmt: skip

    written = read(published["manifest"])
    assert written["pictures"]["02-lanes.png"] == sha256(LANES)
    assert "02-lanes.png" not in written.get("earlier", {})


def test_a_png_no_shot_names_is_declared_by_nobody(published: dict):
    """The hole the whole guard exists for: a page of somebody's own archive left in the folder."""
    (published["images"] / "a-page-of-my-own.png").write_bytes(b"\x89PNG not of this demo\n")

    shooter.write_down(published["images"], a_plan("01-timeline"), ["01-timeline.png"], published["of"])

    assert "a-page-of-my-own.png" not in read(published["manifest"])["pictures"]


def test_the_three_writers_in_turn_change_nothing_but_what_changed(published: dict):
    """Run them round twice. Nothing on disk changed, so the second round writes the same file.

    The three wrote the manifest with two different indents between them, so a run of one
    reformatted every line the others had written and the one hash worth reading was buried in a
    diff of the whole file.
    """
    def a_round() -> str:
        shooter.write_down(published["images"], a_plan("01-timeline", "02-lanes"),
                           ["01-timeline.png", "02-lanes.png"], published["of"])  # fmt: skip
        sheets.write_down(the_sheet(published), manifest=published["manifest"], root=published["repo"])
        mark.write_down(picture=published["repo"] / "docs" / "og.png", manifest=published["manifest"])
        return published["manifest"].read_text(encoding="utf-8")

    first = a_round()
    assert a_round() == first
    written = json.loads(first)
    assert written["pictures"] == {"01-timeline.png": sha256(PAGE), "02-lanes.png": sha256(LANES),
                                   "one-pager.png": sha256(PREVIEW), "clinics-chart.png": sha256(CHART)}  # fmt: skip
    assert written["not_of_a_page"] == {"docs/epicrisis-for-underwriting.pdf": sha256(SHEET),
                                        "docs/og.png": sha256(MARK)}  # fmt: skip
    assert written["earlier"] == {"01-timeline.png": [sha256(BEFORE)]}
    assert written["how"] == A_NOTE


def test_a_manifest_that_cannot_be_read_is_not_written_over(published: dict):
    """73 hashes are in that file and in no other place, and a broken one still holds them.

    The page shooter read it under a suppressed error and started from nothing, which would have
    written a manifest of one run's pictures over every hash the file had.
    """
    published["manifest"].write_text('{"of": {"invented": true}, "pictures": {\n', encoding="utf-8")

    with pytest.raises(the_manifest.CannotRead) as refused:
        shooter.write_down(published["images"], a_plan("01-timeline"), ["01-timeline.png"], published["of"])

    assert "cannot be read" in str(refused.value)
    assert published["manifest"].read_text(encoding="utf-8") == '{"of": {"invented": true}, "pictures": {\n'


def test_only_the_run_that_knows_whose_pictures_these_are_may_make_the_manifest(tmp_path: Path):
    """The guard refuses a manifest that does not say the instance photographed was invented.

    So a sheet printed where there is no manifest at all is a sheet declared nowhere, and saying
    so is the whole of what this can do: a file made here without "of" would be a file the guard
    throws out, and the hashes in it would look written down when they were not.
    """
    manifest = tmp_path / "images" / "taken-from-the-demo.json"
    picture = tmp_path / "docs" / "og.png"
    picture.parent.mkdir(parents=True)
    picture.write_bytes(MARK)

    with pytest.raises(the_manifest.CannotRead) as refused:
        mark.write_down(picture=picture, manifest=manifest)

    assert "no " in str(refused.value) and not manifest.exists()

    the_manifest.declare(manifest, pictures={"01-timeline.png": picture}, of={"invented": True})
    assert read(manifest)["of"] == {"invented": True}


def test_a_name_does_not_move_between_the_two_lists(published: dict):
    """The guard reads both lists for the file in the tree, and a hash in two places goes stale in one.

    The mark and the sheets are declared by the path the repository spells them with, among the
    files that are not a picture of anybody's page; the pictures of the demo by their bare name.
    Which list a name lives in is a property of the thing, not of whoever writes next.
    """
    the_manifest.declare(published["manifest"],
                         pictures={"docs/og.png": published["repo"] / "docs" / "og.png"})  # fmt: skip

    written = read(published["manifest"])
    assert "docs/og.png" not in written["pictures"]
    assert written["not_of_a_page"]["docs/og.png"] == sha256(MARK)


def test_the_guard_passes_a_repository_the_writers_kept_the_hashes_of(tmp_path: Path):
    """End to end, against the guard itself: three generations of a picture, all still declared.

    This is the test the manifest exists for. Each commit publishes the picture as it stood, and
    `git rev-list --objects --all` hands the guard every one of those blobs; a hash the writers
    failed to keep is a refusal nobody can clear, because the commit cannot be unpublished.
    """
    repo = tmp_path / "repo"
    images = repo / "docs" / "images"
    images.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    page = images / "01-timeline.png"
    preview = images / "one-pager.png"
    pdf = repo / "docs" / "epicrisis-for-underwriting.pdf"
    of = {"invented": True, "lives": ["Vera Lindqvist"]}

    for number, (taken, printed) in enumerate(((PAGE, SHEET), (AGAIN, SHEET), (AGAIN, b"%PDF again\n")), start=1):
        page.write_bytes(taken)
        preview.write_bytes(PREVIEW if number < 3 else CHART)
        pdf.write_bytes(printed)
        shooter.write_down(images, a_plan("01-timeline"), ["01-timeline.png"], of)
        sheets.write_down({"insurance": (repo / "tools" / "one-pager.html", pdf, preview)},
                          manifest=images / "taken-from-the-demo.json", root=repo)  # fmt: skip
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", f"generation {number}"], check=True)  # fmt: skip

    assert guard.pictures_of_nobody(repo) == []
