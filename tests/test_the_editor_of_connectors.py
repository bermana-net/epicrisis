"""The editor of links: what the page shows, what a press changes, and what it refuses.

Every press here is in force on the next question that assistant asks: the registry is read on
every request now, so a tick taken off, a date brought forward and a link taken back each land
without anything being restarted. When this file was written none of that was true and this
docstring said so, which is why these tests are worth more than they were.
"""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from epicrisis import connectors, layout, settings
from epicrisis.sources import SourceRegistry
from epicrisis.web.app import create_app


@pytest.fixture(autouse=True)
def secrets_go_nowhere_near_the_machine(tmp_path: Path, monkeypatch):
    """Every test in this file writes its code secrets into its own temporary folder.

    Autouse, and that is the point: the press that issues a link runs inside the application, so
    it cannot be handed a folder the way the module can, and the default is
    /etc/epicrisis/connectors — a machine-wide path owned by root. Written per test, the first
    run of this file left four real secret files under /etc, named after links that only ever
    existed in a temporary directory. Written per test, the next test somebody adds forgets.
    """
    monkeypatch.setattr(connectors, "SECRETS_FOLDER", tmp_path / "connector-secrets")


def an_instance(tmp_path: Path, owners=("Vasylyna Prokopchuk", "Somebody Else"), host: str = ""):
    """A data directory with archives, and a client to look at it with."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    registry = SourceRegistry(data_dir)
    ids = []
    for number, owner in enumerate(owners):
        folder = tmp_path / f"scans{number}"
        folder.mkdir()
        ids.append(registry.add(str(folder), owner=owner).id)
    registry.set_active(ids[0])
    if host:
        settings.set_the_name_the_tunnel_answers_on(data_dir, host)
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    return data_dir, ids, client


def days_from_today(days: int) -> str:
    """A day as the registry writes it, counted off this program's own clock.

    Never a date typed into the test: one holding 2027-03-31 passes until that morning and then
    fails for a reason that has nothing to do with the code.
    """
    from datetime import date, timedelta

    from epicrisis import records

    return (date.fromisoformat(records.today()) + timedelta(days=days)).isoformat()


def test_a_link_is_listed_by_what_its_owner_called_it_and_never_by_its_id(tmp_path: Path):
    """A list of random ids is a list nobody can act on, which is the whole reason for the field."""
    data_dir, ids, client = an_instance(tmp_path)
    made, _secret = connectors.issue(data_dir, name="the father's cardiologist",
                                     archives=(ids[0],), secrets_folder=tmp_path / "secrets")  # fmt: skip

    page = client.get("/connectors").text

    assert "the father&#39;s cardiologist" in page or "the father's cardiologist" in page
    # How many of how many, so a link that reaches nobody is visible without opening it.
    assert "1 of 2" in page


def test_the_page_shows_a_name_and_a_tick_and_nothing_out_of_the_archives(tmp_path: Path):
    """The line in this module nobody should delete, held as a test rather than as a paragraph.

    This is the one screen where the names of several people stand side by side. That is what it
    is for. The day a count of documents or a last-read date appears beside those names, it stops
    being a list of permissions and becomes a comparison of three people's records on one screen.

    Every surface of the page is swept and not only the list, because the names moved: they live
    in the sheets now, where the ticks are. A sweep of the list alone would have gone on passing
    while a count of documents was drawn next to each tick, which is the whole of what this test
    is for — and it very nearly did, because the names on the list page are the archive picker's,
    in the bar that every page carries.
    """
    import re

    data_dir, ids, client = an_instance(tmp_path)
    made, _code = connectors.issue(data_dir, name="a link", archives=(ids[0],),
                                   secrets_folder=tmp_path / "secrets")  # fmt: skip

    where = {
        "the list": client.get("/connectors").text,
        "editing": client.get(f"/connectors?editing={made.id}").text,
        "adding": client.get("/connectors?issuing=yes").text,
        "taking it back": client.get(f"/connectors?deleting={made.id}").text,
    }

    # The names stand beside the ticks, which is the page doing its job.
    for drawn in (where["editing"], where["adding"]):
        inside = drawn.split('class="ticks"', 1)[-1].split("</ul>", 1)[0]
        assert "Vasylyna Prokopchuk" in inside and "Somebody Else" in inside

    for which, drawn in where.items():
        # The words a person reads, out of this page's own blocks. Two narrowings, both of them
        # because the first draft of this test asserted about the wrong thing twice: the
        # navigation every page carries links to Documents by name, and `value="…"` is markup
        # rather than a word about anybody. What is left is the text, which is what the rule is
        # about.
        # Everything this page draws for itself: the section and the sheets after it, and not the
        # bar above, whose archive picker names every owner on the instance by design. Written as
        # one cut rather than as a block per piece, because the first draft cut each sheet at its
        # first `</div>` — which is the end of the sheet's heading — and a count of documents
        # planted beside a tick went straight through a test written to catch exactly that.
        ours = drawn.split('<section class="rule"', 1)[-1]
        reads = re.sub(r"<[^>]*>", " ", ours).lower()
        for out_of_an_archive in ("document", "page", "last read", "finding", "value", "diagnos",
                                  "result", "doctor", "clinic"):  # fmt: skip
            assert out_of_an_archive not in reads, f"{out_of_an_archive} — on {which}"


def test_ticking_an_archive_writes_the_whole_set_and_says_what_it_stored(tmp_path: Path):
    """The whole set, because the page draws every archive with a tick beside it.

    An add would make a tick that failed to arrive look like a tick nobody changed.
    """
    data_dir, ids, client = an_instance(tmp_path)
    made, _secret = connectors.issue(data_dir, archives=(ids[0],), secrets_folder=tmp_path / "secrets")

    answer = client.post("/connectors", data={"connector_id": made.id, "shown": "archives",
                                              "archive_ids": [ids[1]]}, follow_redirects=True)  # fmt: skip

    assert connectors.get(data_dir, made.id).archives == (ids[1],)
    assert "1 archive" in answer.text


def test_a_press_that_did_not_draw_the_ticks_does_not_clear_them(tmp_path: Path):
    """The half-sent form, in the place where it would have cost the most.

    Without this a press that saved a name would have taken every archive off the link, and the
    page would have shown that as the truth.
    """
    data_dir, ids, client = an_instance(tmp_path)
    made, _secret = connectors.issue(data_dir, archives=tuple(ids), secrets_folder=tmp_path / "secrets")

    client.post("/connectors", data={"connector_id": made.id, "shown": "name",
                                     "name": "renamed"}, follow_redirects=True)  # fmt: skip

    kept = connectors.get(data_dir, made.id)
    assert kept.name == "renamed"
    assert set(kept.archives) == set(ids), "a tick nobody was asked about is a tick nobody changed"


def test_an_archive_that_is_not_on_this_instance_is_refused_and_nothing_is_written(tmp_path: Path):
    """A page left open while an archive was forgotten, most likely.

    Written, the link would carry an id that opens nothing and the page would go on drawing the
    tick as though it meant something.
    """
    data_dir, ids, client = an_instance(tmp_path)
    made, _secret = connectors.issue(data_dir, archives=(ids[0],), secrets_folder=tmp_path / "secrets")

    answer = client.post("/connectors", data={"connector_id": made.id, "shown": "archives",
                                              "archive_ids": [ids[1], "nosucharchive"]})  # fmt: skip

    assert connectors.get(data_dir, made.id).archives == (ids[0],), "nothing was changed"
    assert "not on this instance any more" in answer.text
    # Drawn again rather than redirected, so the refusal arrives beside the thing it is about.
    assert answer.status_code == 200


def test_revoking_from_the_page_leaves_the_link_listed_and_says_what_happened(tmp_path: Path):
    """The line stays, carrying the day it stopped: an id that names nothing makes the two logs
    that record what a link did unreadable."""
    data_dir, ids, client = an_instance(tmp_path, host="something.ts.net")
    made, _secret = connectors.issue(data_dir, name="a link", archives=(ids[0],),
                                     secrets_folder=connectors.SECRETS_FOLDER
                                     if False else tmp_path / "secrets")  # fmt: skip

    answer = client.post("/connectors", data={"revoke": made.id}, follow_redirects=True)

    assert "revoked" in answer.text
    assert [one.id for one in connectors.load(data_dir)] == [made.id]
    assert not connectors.get(data_dir, made.id).live
    # And a revoked link has no address to copy. Asserted of the view and not only of the page:
    # the template guards on `live` as well, so a mutation that made the view compose an address
    # for a withdrawn link stayed green through the page alone. Two guards are right; a test that
    # can only see one of them is not.
    from epicrisis.web.app import TheArchives
    from epicrisis.web.connectors_page import connectors_view

    drawn = connectors_view(data_dir, TheArchives(tuple(SourceRegistry(data_dir).list()), None),
                            looking_at=made.id)  # fmt: skip
    assert drawn["looking_at"]["link"] == ""
    assert "The address for this link" not in answer.text


def test_with_no_public_name_there_is_no_address_and_the_page_says_what_to_do(tmp_path: Path):
    """Half an address is worse than none in the one place a link is copied to send somebody."""
    data_dir, ids, client = an_instance(tmp_path)
    made, _code = connectors.issue(data_dir, name="a link", archives=(ids[0],),
                                   secrets_folder=tmp_path / "secrets")  # fmt: skip

    page = client.get(f"/connectors?editing={made.id}").text

    assert "no public name yet" in page
    assert "/settings?tab=network" in page
    assert "The address for this link" not in page


def test_the_address_is_shown_every_time_and_the_code_secret_never_is(tmp_path: Path):
    """The two secrets of a link, and only one of them is shy.

    The address is what this page is for: a link that could not be looked at again would be a
    link lost the first time a message was closed. The code for the authenticator is the other
    one, shown in the single answer that creates it and never after.
    """
    data_dir, ids, client = an_instance(tmp_path, host="something.ts.net")
    made, code_secret = connectors.issue(data_dir, name="a link", archives=(ids[0],),
                                         secrets_folder=tmp_path / "secrets")  # fmt: skip

    listed = client.get("/connectors").text
    first = client.get(f"/connectors?editing={made.id}").text
    again = client.get(f"/connectors?editing={made.id}").text

    assert made.path in first and made.path in again
    assert code_secret not in first and code_secret not in again
    # And not on the list behind it. The list is names and presses; an address is a credential to
    # hand one person, and a page that prints every one of them is a page nobody can show anybody
    # over their shoulder.
    assert made.path not in listed and code_secret not in listed


def test_a_registry_that_will_not_read_says_so_and_offers_nothing_to_press(tmp_path: Path):
    """Not an empty list: an empty list reads as "no link has been issued", and somebody would
    make another one over the top of the file that holds the ones they have."""
    data_dir, ids, client = an_instance(tmp_path)
    (data_dir / layout.CONNECTORS).write_text("{ not json", encoding="utf-8")

    page = client.get("/connectors").text

    assert "nothing has been opened" in page
    assert ".previous" in page
    assert 'name="archive_ids"' not in page


def test_the_journal_names_the_link_and_counts_the_archives_and_never_which(tmp_path: Path):
    """A line saying who somebody may now read is a line about three people in a file this
    project says may be shown to anybody."""
    data_dir, ids, client = an_instance(tmp_path)
    made, _secret = connectors.issue(data_dir, archives=(), secrets_folder=tmp_path / "secrets")

    client.post("/connectors", data={"connector_id": made.id, "shown": "archives",
                                     "archive_ids": ids}, follow_redirects=True)  # fmt: skip

    written = (data_dir / layout.JOURNAL).read_text(encoding="utf-8")
    assert made.id in written and "may open was changed" in written
    assert '"archives": 2' in written
    for archive_id in ids:
        assert archive_id not in written
    assert "Vasylyna" not in written


def test_issuing_a_link_shows_the_code_once_and_never_again(tmp_path: Path):
    """The whole discipline of this press, and the reason it is not a redirect.

    A redirect carries what it carries in an address bar and in a browser's history, and this
    answer holds the code secret. So the one time it is shown is the response to the press, and
    there is no second one to be had: nothing in the module will hand it back, and a reload of
    the page is a page with no code on it.
    """
    data_dir, ids, client = an_instance(tmp_path, host="something.ts.net")

    answer = client.post("/connectors/new", data={"name": "for the urologist", "understood": "yes",
                                                  "archive_ids": [ids[0]]})  # fmt: skip

    assert answer.status_code == 200, "rendered where it stands, never redirected"
    assert "now and never again" in answer.text
    made = connectors.load(data_dir)[0]
    assert made.name == "for the urologist" and made.archives == (ids[0],)
    # The code is in that one answer...
    secret = re.search(r"secret=([A-Z2-7]+)", answer.text)
    assert secret, answer.text[:400]
    # ...and in nothing the page draws afterwards.
    again = client.get("/connectors").text
    assert secret.group(1) not in again
    assert "otpauth://" not in again
    # Nor in the journal, nor in the registry on disk.
    assert secret.group(1) not in (data_dir / layout.JOURNAL).read_text(encoding="utf-8")
    assert secret.group(1) not in (data_dir / layout.CONNECTORS).read_text(encoding="utf-8")


def test_the_page_says_that_reloading_it_issues_another_link(tmp_path: Path):
    """Said rather than prevented, and the trade is written beside the sentence.

    This answer is rendered where it stands and not redirected, because a redirect would carry
    the code in an address bar and in a history. The price is that a reload sends the form again.
    A nonce would stop it and buy a second kind of state to get wrong; the sentence costs nothing,
    and the extra link is visible on this page and revoked in one press.
    """
    data_dir, ids, client = an_instance(tmp_path)

    first = client.post("/connectors/new", data={"understood": "yes"})

    assert "issues <b>another</b> link" in first.text
    # And it is true, which is why it is said: the same press again makes a second link.
    client.post("/connectors/new", data={"understood": "yes"})
    assert len(connectors.load(data_dir)) == 2


def test_the_press_asks_to_be_understood_first(tmp_path: Path):
    """The way `forget` asks, and for the same reason: this press cannot be undone by pressing it
    again. A link issued and lost is a link to revoke, not a link to look at."""
    data_dir, ids, client = an_instance(tmp_path)

    answer = client.post("/connectors/new", data={"name": "no tick"})

    assert "shown once" in answer.text
    assert connectors.load(data_dir) == []


def test_a_qr_is_drawn_and_a_page_without_one_still_hands_over_the_code(tmp_path: Path):
    """The picture is the convenience; the line of text is what an authenticator needs.

    A page whose job is to hand somebody a credential must not fail because a drawing library is
    missing, so the URI is written out either way and the picture is asked for separately.
    """
    from epicrisis.web.connectors_page import a_qr_of

    data_dir, ids, client = an_instance(tmp_path, host="something.ts.net")

    answer = client.post("/connectors/new", data={"understood": "yes"}).text

    assert "<svg" in answer and "segno" in answer
    # And the two ways out of it, both of which leave the code reachable by a person.
    assert a_qr_of("x" * 8000) == "", "a URI too long for a symbol draws nothing and raises nothing"
    assert "otpauth://" in answer


def test_a_link_issued_with_no_archives_says_so_rather_than_being_refused(tmp_path: Path):
    """Refusing would be this page deciding somebody must describe a credential before having it.

    It is listed at nought of however many, which is visible without opening it.
    """
    data_dir, ids, client = an_instance(tmp_path)

    client.post("/connectors/new", data={"understood": "yes"})

    assert connectors.load(data_dir)[0].archives == ()
    assert "0 of 2" in client.get("/connectors").text


def test_an_archive_that_is_not_here_issues_nothing_at_all(tmp_path: Path):
    """Nothing written, not even a link with one good archive out of two: a page left open while
    an archive was forgotten is a page whose whole answer is stale."""
    data_dir, ids, client = an_instance(tmp_path)

    answer = client.post("/connectors/new", data={"understood": "yes",
                                                  "archive_ids": [ids[0], "nosucharchive"]})  # fmt: skip

    assert "not on this instance any more" in answer.text
    assert connectors.load(data_dir) == []


def test_the_journal_says_a_link_was_issued_and_carries_no_part_of_its_code(tmp_path: Path):
    data_dir, ids, client = an_instance(tmp_path)

    client.post("/connectors/new", data={"understood": "yes", "archive_ids": ids})

    written = (data_dir / layout.JOURNAL).read_text(encoding="utf-8")
    assert "an MCP link was issued" in written
    assert connectors.load(data_dir)[0].id in written
    assert '"archives": 2' in written
    assert "otpauth" not in written and "secret" not in written


def test_the_list_is_a_row_per_link_with_the_two_things_that_can_be_done_to_it(tmp_path: Path):
    """What the owner asked for, in his words: «просто список ключей, напротив каждого ключа
    удалить, редактировать кнопки, есть кнопка добавить».

    The page before this was a two-column editor that drew the right-hand column only after a name
    in the left one was pressed. On a phone — which is where he reads it — the two columns are two
    stacks, so the page opened on a list of names above a form belonging to whichever of them the
    page had chosen for him, with an address running off the side of the screen under it.
    """
    data_dir, ids, client = an_instance(tmp_path, host="something.ts.net")
    first, _code = connectors.issue(data_dir, name="art_key", archives=tuple(ids),
                                    secrets_folder=tmp_path / "secrets")  # fmt: skip
    second, _code = connectors.issue(data_dir, name="for the cardiologist", archives=(ids[0],),
                                     secrets_folder=tmp_path / "secrets")  # fmt: skip

    page = client.get("/connectors").text

    for one in (first, second):
        assert f"/connectors?editing={one.id}" in page, "no way to edit that link"
        assert f"/connectors?deleting={one.id}" in page, "no way to take that link back"
    assert "/connectors?issuing=yes" in page, "no way to add one"
    assert "art_key" in page and "for the cardiologist" in page
    # How many people each reaches, which is the one thing about the archives the list carries.
    assert f"{len(ids)} of {len(ids)}" in page and f"1 of {len(ids)}" in page


def test_editing_opens_a_sheet_holding_the_name_the_address_and_the_ticks(tmp_path: Path):
    """One link at a time, with everything that is said about it in one place.

    And it is an address of its own rather than a state the page keeps: opened by a link, left by
    Back, and reloadable — none of which is true of a panel a script shows and hides.
    """
    data_dir, ids, client = an_instance(tmp_path, host="something.ts.net")
    made, _code = connectors.issue(data_dir, name="art_key", archives=(ids[0],),
                                   secrets_folder=tmp_path / "secrets")  # fmt: skip

    sheet = client.get(f"/connectors?editing={made.id}").text

    assert 'class="sheet-card"' in sheet and 'role="dialog"' in sheet
    assert made.path in sheet, "the address is not in the sheet"
    assert 'value="art_key"' in sheet, "the name cannot be edited here"
    for one in ids:
        assert f'value="{one}"' in sheet, "a person is missing from the ticks"
    # Closed without a script, three ways: the dim behind it, the cross, and Cancel.
    assert sheet.count('href="/connectors"') >= 3
    assert "<script" not in sheet.split('class="sheet"', 1)[-1]


def test_deleting_asks_before_it_does_anything_and_says_why_the_row_stays(tmp_path: Path):
    """A press that cannot be undone by pressing again asks first, as `forget` does.

    The sheet is a question; nothing is written until the form in it is sent. That is why the
    address is `?deleting=` and the revoking is a POST — a link that revoked by being followed
    would be revoked by anything that fetched it.
    """
    data_dir, ids, client = an_instance(tmp_path, host="something.ts.net")
    made, _code = connectors.issue(data_dir, name="art_key", archives=(ids[0],),
                                   secrets_folder=tmp_path / "secrets")  # fmt: skip

    asked = client.get(f"/connectors?deleting={made.id}").text

    assert "Take back" in asked and "art_key" in asked
    assert 'name="revoke"' in asked and f'value="{made.id}"' in asked
    assert "stays in this list with the day it stopped" in asked
    assert connectors.get(data_dir, made.id).live, "looking at the question revoked the link"


def test_a_revoked_link_keeps_its_row_and_offers_nothing_to_press(tmp_path: Path):
    """It is there to answer "what was this one used for", and for nothing else."""
    data_dir, ids, client = an_instance(tmp_path, host="something.ts.net")
    made, _code = connectors.issue(data_dir, name="art_key", archives=(ids[0],),
                                   secrets_folder=tmp_path / "secrets")  # fmt: skip
    client.post("/connectors", data={"revoke": made.id}, follow_redirects=True)

    page = client.get("/connectors").text

    assert "art_key" in page and "revoked" in page
    assert f"/connectors?editing={made.id}" not in page
    assert f"/connectors?deleting={made.id}" not in page
    assert made.path not in page


def test_adding_a_link_is_a_sheet_and_still_asks_to_be_understood(tmp_path: Path):
    """The Add button opens the one press that makes a credential, and the tick stays on it."""
    data_dir, ids, client = an_instance(tmp_path, host="something.ts.net")

    sheet = client.get("/connectors?issuing=yes").text

    assert 'action="/connectors/new"' in sheet
    assert 'name="understood"' in sheet and "required" in sheet
    assert "shown once" in sheet
    for one in ids:
        assert f'value="{one}"' in sheet, "a person is missing from the ticks"


def test_the_page_says_when_no_code_stands_in_front_of_the_links(tmp_path: Path):
    """The one sentence that was missing on the day it mattered.

    The lock is a setting, and this instance had it off for nine days. Nothing said so: not the
    server at startup, not the page where links are handed out. Its owner learnt that his archive
    was answering without a code by watching an assistant answer a question without asking him for
    one, and wrote «система скомпрометирована» — which it was not. It was doing exactly what the
    settings said, in silence, which is what the seventh entry of the constitution is about.

    On the page where a link is given to somebody else, because that is where a person decides
    what they are handing over.
    """
    from epicrisis import settings

    data_dir, ids, client = an_instance(tmp_path, host="something.ts.net")
    connectors.issue(data_dir, name="art_key", archives=(ids[0],), secrets_folder=tmp_path / "secrets")

    settings.set_mcp_lock(data_dir, False)
    without = client.get("/connectors").text
    settings.set_mcp_lock(data_dir, True)
    with_it = client.get("/connectors").text

    assert "six-digit code is <b>off</b>" in without
    assert "/settings?tab=network" in without, "it says what is wrong and not what to do about it"
    assert "six-digit code is <b>off</b>" not in with_it, "it says it while it is not true"


def test_the_server_says_at_startup_when_the_code_is_off(tmp_path: Path, capsys):
    """And the same sentence where the other half of people look: the terminal it was started in.

    It already warns when the address filter is empty. The lock being off is the larger of the
    two and said nothing at all.
    """
    import typer.testing

    from epicrisis import settings
    from epicrisis.cli import app

    data_dir, ids, _client = an_instance(tmp_path, host="something.ts.net")
    connectors.issue(data_dir, name="art_key", archives=(ids[0],), secrets_folder=tmp_path / "secrets")
    settings.set_mcp_lock(data_dir, False)

    # Started and stopped at the line that would serve, so nothing listens on anybody's port.
    import epicrisis.mcp_server as served

    def instead(*args, **kwargs):
        raise SystemExit(0)

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(served, "run_http", instead)
        said = typer.testing.CliRunner().invoke(app, ["mcp", "--http", "--data-dir", str(data_dir)])

    assert "six-digit code is OFF" in said.output, said.output
    assert "Settings -> Over the network" in said.output


def test_the_row_says_which_of_the_three_things_a_link_is(tmp_path: Path):
    """Answering, past its last day, or taken back — and the middle one keeps its buttons.

    Three states and not two. A link whose day has gone by is the only one of the three somebody
    fixes by typing, so it is the one the list must not dim and must not strip of its Edit button,
    and it is the one worth marking: nobody pressed anything to make it stop.
    """
    data_dir, ids, client = an_instance(tmp_path)
    folder = tmp_path / "secrets"
    answering, _ = connectors.issue(data_dir, name="answering now", archives=(ids[0],), secrets_folder=folder)
    ending, _ = connectors.issue(data_dir, name="ends in a week", archives=(ids[0],),
                                 until=days_from_today(7), secrets_folder=folder)  # fmt: skip
    ended, _ = connectors.issue(data_dir, name="ended already", archives=(ids[0],),
                                until=days_from_today(-2), secrets_folder=folder)  # fmt: skip

    page = client.get("/connectors").text

    assert f"until {days_from_today(7)}" in page, "a link with an end says which day"
    assert f"ended {days_from_today(-2)}" in page
    # The one that ended keeps the two buttons, because typing a later day is what brings it back.
    assert f"/connectors?editing={ended.id}" in page
    assert f"/connectors?deleting={ended.id}" in page
    row = page.split(f'href="/connectors?editing={ended.id}"')[0].split('<li class="key')[-1]
    assert "ended" in row and "gone" not in row, "a link past its day is not read as taken back"


def test_typing_a_day_into_the_sheet_stops_the_link_on_it(tmp_path: Path):
    """The press, the stored day, and the sentence back — one path, all three.

    The day the sheet sends is the day the server serves by, which is the half of this that is
    worth a test over the registry's own: a page that wrote it somewhere the path lookup does not
    read would look exactly like this one.
    """
    data_dir, ids, client = an_instance(tmp_path)
    made, _secret = connectors.issue(data_dir, archives=(ids[0],), secrets_folder=tmp_path / "secrets")

    answer = client.post("/connectors", data={"connector_id": made.id, "shown": "until",
                                              "until": days_from_today(30)}, follow_redirects=True)  # fmt: skip

    assert connectors.get(data_dir, made.id).until == days_from_today(30)
    assert days_from_today(30) in answer.text


def test_a_press_that_did_not_draw_the_date_does_not_take_the_end_off(tmp_path: Path):
    """The sharpest form of the half-sent form, and the reason the date is held to `shown`.

    An empty date means "no end" and an absent one means "this form did not ask", and a browser
    sends the two identically. Without this, a press that saved a name would have turned a link
    that ends next week into one that never ends — the quiet direction, and the dangerous one.
    """
    data_dir, ids, client = an_instance(tmp_path)
    made, _secret = connectors.issue(data_dir, archives=(ids[0],), until=days_from_today(7),
                                     secrets_folder=tmp_path / "secrets")  # fmt: skip

    client.post("/connectors", data={"connector_id": made.id, "shown": "name",
                                     "name": "renamed"}, follow_redirects=True)  # fmt: skip

    assert connectors.get(data_dir, made.id).until == days_from_today(7)


def test_an_empty_date_the_form_did_draw_is_a_link_with_no_end(tmp_path: Path):
    """And the other direction: a person who cleared the field meant to clear it."""
    data_dir, ids, client = an_instance(tmp_path)
    made, _secret = connectors.issue(data_dir, archives=(ids[0],), until=days_from_today(7),
                                     secrets_folder=tmp_path / "secrets")  # fmt: skip

    answer = client.post("/connectors", data={"connector_id": made.id, "shown": "until",
                                              "until": ""}, follow_redirects=True)  # fmt: skip

    assert connectors.get(data_dir, made.id).until == ""
    assert "no last day" in answer.text


def test_a_half_typed_date_is_refused_and_the_rest_of_the_form_is_kept(tmp_path: Path):
    """2027-03 is what a date field sends when somebody is halfway through typing it.

    Read as "no end" it would be the opposite of what they meant, and silently. So it is refused
    in a sentence, and the name they typed in the same press is still saved — a refusal that
    threw the whole form away would cost somebody the other thing they came to do.
    """
    data_dir, ids, client = an_instance(tmp_path)
    made, _secret = connectors.issue(data_dir, archives=(ids[0],), until=days_from_today(7),
                                     secrets_folder=tmp_path / "secrets")  # fmt: skip

    answer = client.post("/connectors", data={"connector_id": made.id, "shown": ["name", "until"],
                                              "name": "the urologist", "until": "2027-03"})  # fmt: skip

    kept = connectors.get(data_dir, made.id)
    assert kept.until == days_from_today(7), "the day it had is untouched"
    assert kept.name == "the urologist", "and the rest of the press was saved"
    assert "2027-03-31" in answer.text, "the refusal shows the shape of a day"


def test_the_sheet_of_an_ended_link_says_so_and_offers_the_address(tmp_path: Path):
    """Where a person finds out, since whoever holds the link is told nothing at all.

    And the address is there, because this is where it is extended: a sheet without one would
    have the page say "this instance has no public name yet", which is its sentence for an address
    it cannot build.
    """
    data_dir, ids, client = an_instance(tmp_path, host="something.ts.net")
    made, _secret = connectors.issue(data_dir, name="the urologist", archives=(ids[0],),
                                     until=days_from_today(-2), secrets_folder=tmp_path / "secrets")  # fmt: skip

    sheet = client.get(f"/connectors?editing={made.id}").text

    assert "stopped answering" in sheet and days_from_today(-2) in sheet
    assert made.path in sheet, "the address it comes back on"
    assert "no public name yet" not in sheet


def test_a_new_link_with_a_day_that_is_not_a_day_is_not_issued_at_all(tmp_path: Path):
    """Nothing written and no code shown. A link issued and then refused its date would be a
    credential handed over that this page had not meant to make, with the code already on screen.
    """
    data_dir, ids, client = an_instance(tmp_path)

    answer = client.post("/connectors/new", data={"name": "the urologist", "archive_ids": [ids[0]],
                                                  "until": "next March", "understood": "yes"})  # fmt: skip

    assert connectors.load(data_dir) == []
    assert "Nothing was issued" in answer.text
    assert "otpauth" not in answer.text, "no code was shown"


def test_a_new_link_takes_its_last_day_from_the_sheet(tmp_path: Path):
    """The ordinary path: a doctor abroad, a day the owner knows, one press."""
    data_dir, ids, client = an_instance(tmp_path, host="something.ts.net")

    answer = client.post("/connectors/new", data={"name": "the urologist", "archive_ids": [ids[0]],
                                                  "until": days_from_today(90), "understood": "yes"})  # fmt: skip

    assert connectors.load(data_dir)[0].until == days_from_today(90)
    assert answer.status_code == 200 and "otpauth" in answer.text, "the code is still shown once"
