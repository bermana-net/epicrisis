"""What the published pages say about the program, checked against what the program does.

The site, the two one-pagers and the README are read by people deciding whether to trust this
thing with their medical records, and nothing in the suite had ever read them. Three of the QA
round's findings were sentences on those pages: a promise that everything under `data/` could be
deleted and rebuilt, which would have cost somebody every correction and every verdict they ever
typed; two of three licence panels invisible to a browser with no JavaScript, under a comment in
the script promising the opposite; and a count of tests that had been wrong for eighty-two of them.

These are text checks on purpose. A page whose claim about the program can be stated as a string
is a page a test can hold to it, and none of this needs a browser.
"""

import pathlib
import re
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent.parent
SITE = HERE / "docs" / "index.html"
SHEETS = (HERE / "tools" / "one-pager.html", HERE / "tools" / "one-pager-clinics.html")
README = HERE / "README.md"


@pytest.fixture
def site() -> str:
    return SITE.read_text(encoding="utf-8")


def test_the_site_does_not_say_everything_under_data_can_be_rebuilt(site: str):
    """It said so for three versions, and it was never true.

    Five things under `data/` are nobody's but the person's own: the corrections they typed against
    their own printed lines, the verdicts they gave on findings, the indicators they approved one
    at a time, the earlier reading kept when a later one displaced it, and their conversations.
    No run of this program and no model makes any of that again. `epicrisis backup` exists for
    exactly those five, and the README has said so since it was written; the site told a person
    they could delete the lot.
    """
    assert "rebuilt from scratch" not in site
    assert "can be deleted and rebuilt" not in site


def test_the_site_says_which_five_things_nothing_rebuilds_and_what_carries_them(site: str):
    """And says it where the claim was: in "Your archive stays yours", beside the read-only scans."""
    said = site[site.index("Your archive stays yours"):]
    assert "nothing rebuilds them" in said
    for work in ("corrections", "verdicts on findings", "indicators you approved",
                 "earlier readings", "conversations"):  # fmt: skip
        assert work in said, work
    # The command, because a warning with no way to act on it is a warning people read past.
    assert "epicrisis backup" in said


def test_all_three_licence_panels_are_shown_without_javascript(site: str):
    """Two of the three were `hidden` in the markup, and only the script ever took it off.

    The page is published on a public site; a browser with no JavaScript, a reader that strips it,
    or a script that fails to load left the panels for insurers and for clinics unreachable — with
    a comment in that very script promising that a browser without it shows them all.
    """
    for panel in ("panel-mine", "panel-org", "panel-clinic"):
        opening = re.search(rf'<div class="panel" id="{panel}"[^>]*>', site)
        assert opening, panel
        assert "hidden" not in opening.group(0), opening.group(0)


def test_the_script_hides_the_panels_it_is_not_showing(site: str):
    """Which is what makes the tabs work for everybody else: the markup shows all three, the
    script leaves one. `show` is called before anything can be clicked, and it sets `hidden` on
    the other two — so nothing here is a page three panels long once the script has run."""
    assert "document.getElementById(panel).hidden = !on;" in site
    assert 'show("tab-mine");' in site
    # And the comment says what the code does. It said "the script hides one" of "both panels",
    # which was wrong twice over: there are three, and the markup hid two of them itself.
    assert "A browser with no JavaScript shows both" not in site
    assert "shows all three" in site


def how_many_tests() -> int:
    """How many tests there are, asked of pytest rather than remembered.

    Collection only: nothing is run, and the number is the one `pytest -q` prints at the end of a
    run. Asked through this interpreter and not through `uv`, so the check needs no network and no
    second environment.
    """
    counted = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
                             cwd=HERE, capture_output=True, text=True, check=True)  # fmt: skip
    found = re.search(r"(\d+) tests? collected", counted.stdout)
    assert found, counted.stdout[-2000:]
    return int(found.group(1))


def test_every_published_count_of_tests_is_the_number_of_tests_there_are():
    """The site said 649, the sheets and the README said 674, and there were 711.

    A number in a tile beside "479 documents" and "5 355 values" is read as a measurement of this
    project, and this one was the only measurement on those pages that nothing kept true. It is
    published in five places — the site, both one-pagers, and the README twice — and when it moves,
    all five move, and the PDFs are printed again from the sheets.
    """
    there_are = how_many_tests()
    published = {
        SITE: [int(one) for one in re.findall(r'<div class="n">(\d+)</div><div class="k">tests', SITE.read_text(encoding="utf-8"))],
        README: [int(one) for one in re.findall(r"(\d+) tests, no network, no model", README.read_text(encoding="utf-8"))],
    }
    for sheet in SHEETS:
        published[sheet] = [int(one) for one in
                            re.findall(r'<div class="n">(\d+)</div><div class="k">Tests in the suite</div>',
                                       sheet.read_text(encoding="utf-8"))]  # fmt: skip
    for page, numbers in published.items():
        assert numbers, f"{page.name} no longer says how many tests there are"
        assert all(number == there_are for number in numbers), (page.name, numbers, there_are)


def test_the_public_header_does_not_overlap_itself_on_a_phone():
    """The name ran out over the menu on a phone: the mark made the block wider than the room.

    A header told to keep its name and its menu on one line does exactly that, and squeezes the name
    into a box narrower than the letters in it — so "Epicrisis Companion" lay across the buttons and
    both were unreadable. On a narrow screen the two take a line each.
    """
    from pathlib import Path

    page = (Path(__file__).parent.parent / "docs" / "index.html").read_text(encoding="utf-8")
    styles = page.split("</style>")[0]
    assert "@media (max-width: 760px)" in styles, "nothing lets the header stack at all"
    narrow = styles.split("@media (max-width: 760px)")[1]
    assert "flex-wrap: wrap" in narrow and ".brand-block { flex: 1 0 100%" in narrow
    assert "header.top nav { flex: 1 0 100%" in narrow
