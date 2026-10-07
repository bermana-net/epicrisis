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

from epicrisis import layout

HERE = pathlib.Path(__file__).resolve().parent.parent
SITE = HERE / "docs" / "index.html"
SHEETS = (HERE / "tools" / "one-pager.html", HERE / "tools" / "one-pager-clinics.html")
README = HERE / "README.md"
CONTRIBUTING = HERE / "CONTRIBUTING.md"
CONSTITUTION = HERE / "CONSTITUTION.md"
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

    Several things under `data/` are nobody's but the person's own: the corrections they typed
    against their own printed lines, the verdicts they gave on findings, the indicators they
    approved one at a time, the doctors and clinics they said were one, the earlier reading kept
    when a later one displaced it, their conversations, and the rules they wrote for their own
    laboratory's forms. No run of this program and no model makes any of that again.
    `epicrisis backup` exists for exactly those, and the README has said so since it was written;
    the site told a person they could delete the lot. `layout.THEIR_OWN_WORK` is the list, and the
    test below holds both pages to it rather than to a number anybody has to remember.
    """
    assert "rebuilt from scratch" not in site
    assert "can be deleted and rebuilt" not in site


# What a page has to call each kind of a person's own work for a reader to know what it means.
# Keyed by the file or folder it is, out of `layout.THEIR_OWN_WORK`, so that a kind added to that
# list fails the test below until the pages name it. That is how the count on the two pages got to
# be wrong in two different ways: the site said five, the README said six, `backup` carried seven,
# and `people.json` — the doctors and clinics somebody joined by hand — was missing from the site
# altogether, which is the one of the seven that would be hardest to notice gone.
IN_THESE_WORDS = {
    layout.CORRECTIONS: "corrections",
    layout.JUDGEMENTS: "verdicts on findings",
    layout.INDICATORS: "indicators you approved",
    layout.PEOPLE: "doctors and clinics you",
    layout.REPLACED: "earlier readings",
    layout.CHATS: "conversations",
    layout.RULES: "rules you wrote",
}
HOW_MANY = ("", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten")


def test_the_two_pages_name_every_kind_of_work_that_nothing_rebuilds():
    """And say how many there are, which is `epicrisis backup`'s list and not anybody's memory.

    The site said "Five things", the README said six and named a sixth the site did not, and
    `layout.THEIR_OWN_WORK` — the list the backup command actually copies — held seven. Three
    numbers for one thing, which is the seventh entry of the constitution on one page and across
    two. The kind the site left out was `people.json`: a person who joined two spellings of their
    cardiologist by hand, read the site, and deleted `data/` would have lost exactly that and
    nothing would have said so.
    """
    assert set(IN_THESE_WORDS) == set(layout.THEIR_OWN_WORK), (
        "layout.THEIR_OWN_WORK has changed. Both published pages say how many kinds of a person's "
        "own work nothing rebuilds and name each one; say the new one there, then here.")
    counted = HOW_MANY[len(layout.THEIR_OWN_WORK)]
    for page, after in ((SITE, "Your archive stays yours"), (README, "Your archive stays yours")):
        said = page.read_text(encoding="utf-8")
        said = said[said.index(after):]
        assert f"{counted.lower()} things under" in said.lower(), (
            f"{page.name} does not say that {counted.lower()} kinds of work nothing rebuilds")
        for name, words in IN_THESE_WORDS.items():
            assert words in said, (page.name, name, words)
        # The command, because a warning with no way to act on it is a warning people read past.
        assert "epicrisis backup" in said, page.name


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


def a_tile(key: str) -> str:
    """The pattern of one number tile of the site or of a sheet, by the words printed under it."""
    return rf'<div class="n">([\d   ,]*\+?)</div><div class="k">{key}</div>'


# Every number the published pages state about the archives this has been run on, and where each
# page states it. The number is a **floor**: the archives are on one machine, no test can read
# them, and every one of these grows as more documents are read, so an exact count is stale within
# the week and nothing in this repository can hold it. The site said "479 documents read" and both
# one-pagers said "500+" — one thing, two published numbers, which the seventh entry of the
# constitution calls a defect — while the archives held more than either.
#
# The patterns sit where the number sits, so a tile that stops saying what it is a tile of fails
# here rather than quietly dropping out of the comparison.
FLOORS = {
    "documents read": ((SITE, a_tile("documents read")),
                       (README, r"\| Documents read \| \*\*([\d   ,]*\+?)\*\* \|"),
                       *((sheet, a_tile("Documents read")) for sheet in SHEETS)),  # fmt: skip
    "values as printed": ((SITE, a_tile("values, as printed")),
                          (README, r"\| Values kept as printed \| \*\*([\d   ,]*\+?)\*\* \|"),
                          *((sheet, a_tile("Values as printed")) for sheet in SHEETS)),  # fmt: skip
    "institution names": ((SITE, a_tile("institution names on the forms")),
                          (README, r"\| Institution names as printed \| ([\d   ,]*\+?) \|"),
                          *((sheet, a_tile(r"Clinic names (?:&middot;|·) 5 languages")) for sheet in SHEETS)),  # fmt: skip
    "approved test groups": ((SITE, a_tile("approved test groups")),
                             (README, r"\| Tests in the vocabulary \| ([\d   ,]*\+?) approved groups")),  # fmt: skip
}


def published(where: tuple[tuple[pathlib.Path, str], ...]) -> dict[pathlib.Path, str]:
    """What each page actually says, with the separators of thousands taken off before comparing.

    The site writes six thousand with a space, a sheet writes it with a comma, and the two are the
    same number on one subject — which is what has to agree. How each page punctuates its own
    numbers is that page's business.
    """
    said = {}
    for page, pattern in where:
        found = re.findall(pattern, page.read_text(encoding="utf-8"))
        assert len(found) == 1, (
            f"{page.name} no longer states this number where it did: {pattern!r} matched {found}")
        said[page] = re.sub(r"[   ,]", "", found[0])
    return said


@pytest.mark.parametrize("claim", sorted(FLOORS), ids=lambda claim: claim.replace(" ", "-"))
def test_every_page_states_the_same_number_about_the_archives(claim: str):
    """Four published pages, one number each, and they have to be the one number.

    This is the test the count of documents never had. It asks nothing of the archives — it cannot,
    and that is the point of publishing a floor — it only holds the pages to each other, which is
    exactly where "500+" and "479" parted company and stayed parted for a release.
    """
    said = published(FLOORS[claim])
    assert len(set(said.values())) == 1, (
        f"the published pages disagree about {claim}: "
        + ", ".join(f"{page.name} says {number}" for page, number in said.items()))


@pytest.mark.parametrize("claim", sorted(FLOORS), ids=lambda claim: claim.replace(" ", "-"))
def test_no_page_states_a_count_off_the_archives_as_an_exact_number(claim: str):
    """A floor, never a count, and the difference is whether it can go stale.

    An exact count of what three real archives hold is true on the day it is measured and wrong by
    the next document read, and nothing in this repository can notice: the archives are not in it
    and the suite needs no data directory. A floor on a quantity that only grows never becomes
    false, so it may be raised by somebody who measured and said so, and it needs nobody to
    remember it in between. The size of the test suite is the one published number that is exact,
    because `pytest` itself answers for it — which is what the test above it does.
    """
    for page, number in published(FLOORS[claim]).items():
        assert number.endswith("+"), (
            f"{page.name} states {claim} as an exact count ({number}). It is measured on somebody's "
            "archives, it grows every time a document is read, and no test here can read them: "
            "publish a floor.")


def test_the_number_of_languages_published_is_the_number_the_readme_names():
    """The one number in that block that is neither a floor nor a count of this repository.

    Five is how many languages these forms are printed in, and it is published as a bare number on
    the site and on both sheets while only the README says which five. A sixth language read one
    day is four pages to change, and this is what notices that three of them were forgotten — the
    same shape as the count of tests, with the README's own list standing in for `pytest`.
    """
    row = re.search(r"\| Languages \| ([^|]+) \|", README.read_text(encoding="utf-8"))
    assert row, "the README no longer names the languages"
    named = [one.strip() for one in row.group(1).split(",") if one.strip()]
    assert len(named) > 1, named
    for page, pattern in ((SITE, a_tile("languages")),
                          *((sheet, r"(\d+) languages</div>") for sheet in SHEETS)):  # fmt: skip
        found = re.findall(pattern, page.read_text(encoding="utf-8"))
        assert len(found) == 1, (page.name, pattern, found)
        assert int(found[0]) == len(named), (
            f"{page.name} says {found[0]} languages; the README names {len(named)}: {named}")


@pytest.mark.parametrize("page", (SITE, README, *SHEETS), ids=lambda page: page.name)
def test_every_page_says_beside_those_numbers_that_they_are_floors(page: pathlib.Path):
    """Written where they are, because the next person to raise one reads that page and not this.

    A rule kept only in a test is a rule somebody breaks in good faith and then argues about. Each
    page says it in the form that page has: the README in a sentence under the table, the site and
    the sheets in a comment beside the tiles, where whoever edits them is already looking.
    """
    said = page.read_text(encoding="utf-8")
    assert "floor" in said, f"{page.name} does not say that its numbers about the archives are floors"
    assert re.search(r"never be written as an exact count|floor, not a count|given as a floor", said), (
        f"{page.name} says 'floor' but no longer says that an exact count is the thing to avoid")


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


def test_every_connector_command_the_readme_gives_is_a_command_there_is():
    """The README is where somebody goes to hand a link to their cardiologist, and it names the
    subcommands they are to type.

    The names were chosen one at a time over the registry's twelve steps — `carry-in` is a verb
    nobody would guess — and a rename here leaves a published page telling a person to type
    something that answers "no such command". The commands are read off the CLI rather than
    written out here, so adding one needs no edit and renaming one fails until the page is edited.
    Only what stands in code on the page is read: the prose says "the connector's own network" and
    that is not an instruction to type anything.
    """
    from epicrisis.cli import connector

    page = README.read_text(encoding="utf-8")
    in_code = re.findall(r"```[a-z]*\n(.*?)```", page, re.S) + re.findall(
        r"`([^`]+)`", re.sub(r"```[a-z]*\n.*?```", "", page, flags=re.S))
    theirs = {found for line in in_code for found in re.findall(r"connector ([a-z][a-z-]*)", line)}
    ours = {command.name or (command.callback and command.callback.__name__.replace("_", "-"))
            for command in connector.registered_commands}  # fmt: skip
    assert len(ours) >= 5, ours
    assert theirs, "the README no longer says how to issue a link at all"
    for named in theirs:
        assert named in ours, f"the README names `epicrisis connector {named}` and there is none"
    # And the other way, which was missing: a subcommand the README has never heard of is a thing
    # this program does and does not say it does. `connector until` landed and went unmentioned,
    # and this test stayed green because it only ever read in one direction.
    for mine in ours:
        assert mine in theirs, (
            f"`epicrisis connector {mine}` exists and the README does not name it: a person "
            "handing somebody a link reads that page and nothing else")  # fmt: skip


def test_the_pages_say_there_is_no_way_in_to_ask_for_and_there_is_none():
    """Every published page says the console has no login, and the constitution now says it twice
    — as the reason there is none and as the thing that will not change.

    So this is the claim most easily broken by somebody being helpful: one form with a password on
    it, added for the best of reasons, makes three published pages and a line of the constitution
    into a lie on the day it is merged. The program is held to its own sentence: nothing this
    dashboard serves asks anybody for a password.
    """
    said = CONSTITUTION.read_text(encoding="utf-8")
    assert "no login" in said, "the constitution no longer says the console has none"
    assert "two people at one keyboard" in said, "nor that two people at one keyboard is refused"

    asked = [page for page in (HERE / "epicrisis" / "web" / "templates").rglob("*.html")
             if 'type="password"' in page.read_text(encoding="utf-8")]  # fmt: skip
    assert asked == [], f"a password is asked for on {[page.name for page in asked]}"


def test_the_units_in_deploy_start_the_commands_this_program_has():
    """A unit file is a command somebody's machine will run unattended, for years.

    It is the one place in this repository where a line is executed by something that will not
    read an error message: if the command in it is renamed, the service fails at a reboot nobody
    was watching, and what the owner sees is an assistant somewhere else saying the archive has
    gone quiet. So the command each unit starts is held to the CLI exactly as the README's
    commands are — and the README is held to naming them at all, because a unit nobody is told
    about is a unit nobody installs.
    """
    import re

    units = sorted((HERE / "deploy").glob("*.service"))
    assert len(units) >= 2, "deploy/ no longer holds the units"

    from epicrisis.cli import app

    named = {command.name or (command.callback and command.callback.__name__.replace("_", "-"))
             for command in app.registered_commands}  # fmt: skip
    for unit in units:
        text = unit.read_text(encoding="utf-8")
        started = re.search(r"^ExecStart=\S*epicrisis\s+([a-z-]+)", text, re.M)
        assert started, f"{unit.name}: no ExecStart running this program"
        assert started.group(1) in named, f"{unit.name} starts `epicrisis {started.group(1)}`, which is not a command"
        # It listens where the README says it listens, and a unit that quietly moved off the
        # loopback would be the whole archive on a public address with no lock in front of it.
        assert "--host 127.0.0.1" in text, f"{unit.name}: not pinned to this machine"
        assert "[Install]" in text and "WantedBy" in text, f"{unit.name}: nothing would start it at boot"

    readme = README.read_text(encoding="utf-8")
    assert "systemctl enable --now" in readme, "the README does not say how to keep them running"
    # Each unit by name, and `or "deploy/*.service"` is gone: the README holds that glob in its
    # install line, so the right-hand side was true for every unit and the loop never once looked
    # at the left. A third unit nobody had written about would have passed.
    for unit in units:
        assert unit.stem in readme, f"{unit.name} is not named anywhere a reader looks"


def test_a_sandboxed_unit_may_write_everything_that_unit_writes():
    """What the code writes and what the unit lets it write, held to each other.

    The MCP unit runs under `ProtectSystem=strict` with the data directory read-only and the paths
    it writes named one by one. A path the code writes and the unit does not name is a write that
    fails — and the two that matter here fail **silently**: the record of calls has its own
    `except OSError`, and the run of wrong codes sets `writes = False` and keeps its count in
    memory, so the growing wait after wrong codes quietly stops outliving a restart. One of those
    two was added to the code and to the unit in the same commit; nothing checked that the pair
    stays a pair, and the test beside this one read `ExecStart` and the address and nothing else.
    """
    from epicrisis import mcp_access, mcp_lock

    unit = (HERE / "deploy" / "epicrisis-mcp.service").read_text(encoding="utf-8")
    allowed = [line.split("=", 1)[1].lstrip("-") for line in unit.splitlines()
               if line.startswith("ReadWritePaths=")]  # fmt: skip

    assert allowed, "the unit names nothing it may write, so it writes nothing"
    for written in (mcp_access.FILE_NAME, mcp_lock.WRONG_CODES_FOLDER):
        assert any(path.endswith(written) for path in allowed), (
            f"the MCP server writes {written} and the unit does not let it: the write fails and "
            f"says nothing, which is the one way this cannot be noticed. {allowed}")  # fmt: skip


def test_no_published_page_says_a_finding_of_the_extract_step_reaches_nobody():
    """One of those five is shown, under its own name, and two published documents said none was.

    `validate.OWN_FINDING_PROBLEMS` surfaces `value_not_on_the_page` with its own label and its
    own words about what to do, and four more are folded into "parts of the document were not
    transcribed". The rule's own file says so in bold — "This one is different from every other
    check of this step: its finding is shown to a person" — while `ARCHITECTURE.md` and
    `rules/README.md` both said, in sentences added the same day, that nobody is ever shown one.

    A published page lives longer than any commit, so a sentence on one that has stopped being
    true is the kind of thing that must not be published. Held to the code rather than to a list,
    so the day the last of those five stops being shown this test says so itself.
    """
    from epicrisis.validate import LEFTOVER, OWN_FINDING_PROBLEMS

    shown = OWN_FINDING_PROBLEMS | set(LEFTOVER)
    assert shown, "nothing of the step reaches a person, so this test is about nothing"

    for page in (HERE / "ARCHITECTURE.md", HERE / "epicrisis" / "rules" / "README.md",
                 README, HERE / "docs" / "index.html"):  # fmt: skip
        said = page.read_text(encoding="utf-8")
        for claim in ("shown to nobody", "nobody is ever handed the finding", "shown to no one"):
            assert claim not in said, (
                f"{page.name} says {claim!r}, and {len(shown)} of that step's findings do reach a "
                f"person: {', '.join(sorted(shown))}")  # fmt: skip


def test_the_pages_that_name_the_pass_window_name_it_as_a_default():
    """It is a setting, from one minute to seven days, and two published pages state the default.

    `mcp_lock.PASS_MINUTES` is four hours and `settings.mcp_lock_minutes` is what the server
    actually reads; the field on the settings page takes 1 to 10080. The status page was changed
    to print the live value, which is what left these two saying a number as a flat fact.
    """
    from epicrisis.mcp_lock import PASS_MINUTES

    assert PASS_MINUTES == 240, "the default moved; these pages say four hours"
    for page in (README, HERE / "docs" / "index.html"):
        said = page.read_text(encoding="utf-8")
        for at, line in enumerate(said.splitlines(), 1):
            if "four hours" not in line:
                continue
            assert "by default" in line, (
                f"{page.name}:{at} gives the pass window as a fact, and it is a setting: "
                "one minute to seven days, and the server reads whatever is stored")  # fmt: skip
