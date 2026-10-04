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
CONTRIBUTING = HERE / "CONTRIBUTING.md"
HOOK = HERE / ".githooks" / "pre-push"
GUARD = HERE / "tools" / "nothing-of-yours.py"
# The three documents that make the promise about what this program is. The site and the
# one-pagers describe the modes; these three say the program does not interpret, and a
# sentence that says that has to name the one mode in which it does.
PROMISES = (README, HERE / "COMMERCIAL.md", CONTRIBUTING)


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


@pytest.mark.parametrize("page", PROMISES, ids=lambda page: page.name)
def test_every_page_promising_no_interpretation_names_the_one_mode_that_interprets(page: pathlib.Path):
    """The README and COMMERCIAL.md were corrected and CONTRIBUTING.md was left as it was.

    For a release the promise was unconditional in all three while the program had grown one door
    in it, and two of the three were rewritten to name that door in the same breath. The third went
    on telling a reader the program never compares anything, which promises less than the program
    does and so deceives nobody — but three documents saying three things is how the next person
    gets it wrong, and the next person is the one writing the code.
    """
    said = " ".join(page.read_text(encoding="utf-8").split())
    assert "does not interpret" in said, f"{page.name} no longer makes the promise at all"
    # The sentence as it stood in CONTRIBUTING.md: the promise with nothing after it.
    assert "stores and displays and does not interpret" not in said, page.name
    assert "three modes" in said, f"{page.name} does not say there are three"
    assert re.search(r"compares? a number with the range printed beside it", said), (
        f"{page.name} does not say what the last mode computes")


def test_contributing_does_not_promise_a_check_a_fresh_clone_does_not_run():
    """It said the guard "enforces the first paragraph before every push", and nothing does.

    `.githooks/pre-push` holds the check, and git runs a hook out of that folder only after
    somebody has typed `git config core.hooksPath .githooks` — which the README prints beside the
    command for exactly that reason, and which CONTRIBUTING.md left out. A contributor who read
    only this page believed something stood between them and publishing a stranger's medical
    records, and nothing did. That is the one direction a document about this must never err in.

    If the project is ever changed so that a clone really does get the hook, this test is where to
    say so: the sentence may then drop the one-time switch, and this assertion has to go with it.
    """
    said = " ".join(CONTRIBUTING.read_text(encoding="utf-8").split())
    hook = HOOK.read_text(encoding="utf-8")
    assert "core.hooksPath .githooks" in hook, "the hook no longer says how it is turned on"
    assert "git config core.hooksPath .githooks" in said, (
        "CONTRIBUTING.md does not name the one line that turns the push check on")
    assert "enforces the first paragraph before every push" not in said, (
        "CONTRIBUTING.md is back to promising a check that runs by itself")


def test_contributing_names_every_half_of_the_push_check():
    """It described the half that reads a data directory and not the half that reads this machine.

    The guard also looks for this server's own secrets, whole and hashed, for keys and tokens by
    their shape, and for a published picture that nothing accounts for. A contributor is the reader
    who most needs the second half: a key of their own in a file they forgot is what will stop
    their push, and a page that lists only names and hashes leaves them reading the wrong file.
    """
    guard = GUARD.read_text(encoding="utf-8")
    assert "def secrets_of_this_server" in guard and "def pictures_of_nobody" in guard
    assert "an Anthropic key" in guard, "the guard no longer looks for a key by its shape"
    said = " ".join(CONTRIBUTING.read_text(encoding="utf-8").split())
    for half in ("the secrets of this machine", "by their shape", "a published picture"):
        assert half in said, half


def commands_in(page: pathlib.Path) -> list[str]:
    """Every command a published page spells out, in backticks or in a fenced block of shell.

    A comment after `#` is not part of the command, and a span broken over two lines by the wrap
    of a paragraph is one command, so both are flattened away before anything is compared.
    """
    text = page.read_text(encoding="utf-8")
    blocks = re.findall(r"```[a-z]*\n(.*?)```", text, re.S)
    inline = re.findall(r"`([^`]+)`", re.sub(r"```[a-z]*\n.*?```", "", text, flags=re.S))
    said = [" ".join(one.split()) for one in inline]
    for block in blocks:
        said += [" ".join(line.split("#")[0].split()) for line in block.splitlines()]
    return [one for one in said if one.startswith(("uv ", "git ", "epicrisis ", "pytest "))]


def test_every_command_in_contributing_is_a_command_the_readme_gives():
    """It said `uv run pytest`, which runs the suite one test at a time, and `epicrisis demo`,
    which is on nobody's path.

    The README has run them in four cores since the machine had four — `uv run pytest -n 4` — and
    invokes everything through `uv run`, because nothing installs this program's command for you.
    Somebody copying the lines out of CONTRIBUTING.md got a serial suite and a command not found.
    Whole commands are compared, not their beginnings: `uv run pytest` is a prefix of the README's
    line and is still the wrong thing to type.
    """
    theirs = set(commands_in(README))
    ours = commands_in(CONTRIBUTING)
    assert len(theirs) > 5, "the README no longer spells out the project's commands"
    assert ours, "CONTRIBUTING.md no longer tells anybody how to run anything"
    for command in ours:
        assert command in theirs, command


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


def test_the_picture_a_shared_link_shows_is_the_one_drawn_for_it():
    """Pasted into a chat, this page used to be shown as whatever picture a service found first.

    What it found here was a screenshot of test results — invented ones, every picture on this site
    being of the demo, but a page of medical results all the same, enlarged in somebody's message to
    whoever the link was sent to. The picture is now drawn for the purpose and carries no results.
    """
    from pathlib import Path

    docs = Path(__file__).parent.parent / "docs"
    page = (docs / "index.html").read_text(encoding="utf-8")
    for tag in ('property="og:image" content="https://epicrisis.bermana.net/og.png"',
                'property="og:image:width" content="1200"',
                'property="og:image:height" content="630"',
                'name="twitter:card" content="summary_large_image"',
                'property="og:title"', 'property="og:description"', 'property="og:url"'):  # fmt: skip
        assert tag in page, tag

    picture = docs / "og.png"
    assert picture.exists(), "the page points at a picture that is not published"
    width = int.from_bytes(picture.read_bytes()[16:20], "big")
    height = int.from_bytes(picture.read_bytes()[20:24], "big")
    assert (width, height) == (1200, 630), (width, height)


def test_the_picture_of_a_link_is_declared_like_every_other(tmp_path):
    """The guard refuses a published picture nothing accounts for, and this is a published picture."""
    import hashlib
    import json
    from pathlib import Path

    docs = Path(__file__).parent.parent / "docs"
    manifest = json.loads((docs / "images" / "taken-from-the-demo.json").read_text(encoding="utf-8"))
    said = manifest["not_of_a_page"].get("docs/og.png")
    assert said == hashlib.sha256((docs / "og.png").read_bytes()).hexdigest(), "og.png is not declared"


def test_each_one_pager_pdf_was_printed_from_the_sheet_as_it_stands():
    """The two PDFs on the site, held to the sheets their text lives in.

    Five published places carry the size of the test suite and a test above holds every one of them
    to the suite. The two PDFs carry it too and that test cannot read them: nothing in this suite
    can open a PDF, and adding a library to do it would make the whole suite depend on one. So they
    drifted, quietly, and were found saying 1106 tests on a day the suite ran 1381 — a number on a
    page a person downloads before deciding whether to trust this program with their records.

    The sheet is what a person can read, so the sheet is what is hashed: `tools/make-one-pager.py`
    writes down the hash of the page it printed from, and this fails while the sheet has moved on
    without it. Printing again is the whole fix, and the printer says so in those words.
    """
    import hashlib
    import json

    printed_from = HERE / "docs" / "printed-from.json"
    assert printed_from.exists(), (
        f"{printed_from.name} is missing: print the one-pagers again and it is written for you — "
        "uv run --with playwright --with pypdf --with pypdfium2 python tools/make-one-pager.py")

    declared = json.loads(printed_from.read_text(encoding="utf-8"))
    sheets = {"docs/epicrisis-for-underwriting.pdf": HERE / "tools" / "one-pager.html",
              "docs/epicrisis-for-clinics.pdf": HERE / "tools" / "one-pager-clinics.html"}  # fmt: skip
    assert set(declared) == set(sheets), (
        f"every published PDF is declared here and no other: {sorted(declared)}")

    for pdf, sheet in sheets.items():
        assert (HERE / pdf).exists(), pdf
        now = hashlib.sha256(sheet.read_bytes()).hexdigest()
        assert declared[pdf] == now, (
            f"{sheet.name} has changed since {pdf} was printed from it, so the download says "
            "something the sheet no longer says. Print the one-pagers again.")
