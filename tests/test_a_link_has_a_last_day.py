"""The last day a link answers: who it stops for, who it does not, and what it says when it has.

A link used to end one way only — somebody pressing a button. A date ends it with nobody
pressing anything, which is a different kind of thing to get wrong: there is no moment at which a
person is looking at the screen, so every one of these has to hold on its own.

The two that matter most are the two directions the mistake goes in. A link read as having no end
when it has one answers for ever, which is the failure the date exists to prevent. A link read as
ended when it is not goes quiet in the middle of somebody's illness, and the only person who
could tell you is the one holding it, who gets no reason given.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from epicrisis import connectors, layout, records
from epicrisis.mcp_server import http_app
from epicrisis.state import Unreadable

CALL = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


def a_secrets_folder(tmp_path: Path) -> Path:
    return tmp_path / "secrets"


def days_from_today(days: int) -> str:
    """A day written as the registry writes it, counted off the one clock this program has.

    Off `records.today()` and never a date typed into the test: a test holding 2027-03-31 passes
    until that morning and then fails for a reason that has nothing to do with the code.
    """
    return (date.fromisoformat(records.today()) + timedelta(days=days)).isoformat()


class AnArchive:
    def __init__(self, id):
        self.id = id


def test_a_link_is_issued_with_no_end_unless_somebody_names_a_day(tmp_path: Path):
    """The default, and it is a decision rather than a convenience.

    A link this program ended on a day nobody chose would stop answering in the middle of the one
    conversation it was issued for. The owner of this instance asked for exactly this: his own
    link has no end, and a doctor's gets a date when he knows it.
    """
    made, _secret = connectors.issue(tmp_path, name="his own", secrets_folder=a_secrets_folder(tmp_path))

    assert made.until == ""
    assert made.live and not made.expired()
    stored = json.loads((tmp_path / layout.CONNECTORS).read_text(encoding="utf-8"))
    assert stored[0]["until"] == "", "the field is on the line, empty, rather than missing from it"


def test_the_day_named_is_the_last_day_it_answers_and_not_the_first_it_does_not(tmp_path: Path):
    """"Until the 31st" means the 31st works, which is what a person typing a date means by it.

    Off by one here is a link that stops a day early, on a day its owner told somebody it would
    still be working.
    """
    folder = a_secrets_folder(tmp_path)
    today, _ = connectors.issue(tmp_path, until=records.today(), secrets_folder=folder)
    yesterday, _ = connectors.issue(tmp_path, until=days_from_today(-1), secrets_folder=folder)
    tomorrow, _ = connectors.issue(tmp_path, until=days_from_today(1), secrets_folder=folder)

    assert today.live, "the last day is included"
    assert tomorrow.live
    assert not yesterday.live and yesterday.expired()


def test_a_link_past_its_day_opens_nothing_at_all(tmp_path: Path):
    """The permission goes with the day, and not only the row's colour on a page.

    `the_archives_it_may_open` is where every caller asks what a link may reach, so a link whose
    day has gone by has to be empty **here** — a check that lived only in the page would leave the
    MCP server serving it.
    """
    archives = [AnArchive("aa11bb22"), AnArchive("cc33dd44")]
    made, _secret = connectors.issue(tmp_path, archives=("aa11bb22", "cc33dd44"),
                                     until=days_from_today(-3), secrets_folder=a_secrets_folder(tmp_path))  # fmt: skip

    assert connectors.the_archives_it_may_open(made, archives) == ()
    assert made.archives == ("aa11bb22", "cc33dd44"), "what it was allowed is still on the line"


def test_its_address_answers_exactly_as_an_invented_one_does(tmp_path: Path):
    """Somebody who can tell "this has expired" from "there is no such address" has learnt that
    the address was real, and that is what this program refuses to tell them.

    Same status, same body, and the same word in the log of calls. The owner finds out on his own
    page, in words; whoever holds the link finds out nothing, and the test for that is that the
    two answers cannot be told apart.
    """
    folder = a_secrets_folder(tmp_path)
    made, _secret = connectors.issue(tmp_path, until=days_from_today(1), secrets_folder=folder)
    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        answered = client.post(f"/mcp/{made.path}", json=CALL, headers=HEADERS)
        connectors.set_until(tmp_path, made.id, days_from_today(-1))

        ended = client.post(f"/mcp/{made.path}", json=CALL, headers=HEADERS)
        invented = client.post(f"/mcp/{'x' * 48}", json=CALL, headers=HEADERS)

    assert answered.status_code == 200, "it answered while the day had not gone by"
    assert ended.status_code == invented.status_code == 404
    assert ended.text == invented.text
    from epicrisis import mcp_access

    refusals = [json.loads(line) for line in mcp_access.path(tmp_path).read_text(encoding="utf-8").splitlines()
                if not json.loads(line)["allowed"]]  # fmt: skip
    assert {line["refused"] for line in refusals} == {"path"}
    assert all("connector" not in line for line in refusals), refusals


def test_the_day_is_read_again_on_every_request_and_not_once_at_the_start(tmp_path: Path):
    """A server that read the dates when it started would serve a link all the way through the
    night after it ended.

    The registry is read per request for the same reason a link issued on the page works without a
    restart, and this is the half of that nobody would notice was missing: it needs no press.
    """
    made, _secret = connectors.issue(tmp_path, until=days_from_today(2), secrets_folder=a_secrets_folder(tmp_path))
    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        assert client.post(f"/mcp/{made.path}", json=CALL, headers=HEADERS).status_code == 200
        connectors.set_until(tmp_path, made.id, days_from_today(-1))
        assert client.post(f"/mcp/{made.path}", json=CALL, headers=HEADERS).status_code == 404
        # And back again, in the same process: extending it is typing a later day and nothing else.
        connectors.set_until(tmp_path, made.id, days_from_today(30))
        assert client.post(f"/mcp/{made.path}", json=CALL, headers=HEADERS).status_code == 200


def test_extending_it_takes_one_day_and_touches_neither_secret(tmp_path: Path):
    """The whole point of a date rather than a revoke: the address and the phone go on being right.

    A person who had to issue a new link to extend one would be setting up an authenticator again
    with somebody abroad, which is the thing this field exists to avoid.
    """
    folder = a_secrets_folder(tmp_path)
    made, _secret = connectors.issue(tmp_path, name="the urologist", archives=("aa11bb22",),
                                     until=days_from_today(-1), secrets_folder=folder)  # fmt: skip
    before = connectors.secret_file(made.id, folder).read_text(encoding="utf-8")

    moved = connectors.set_until(tmp_path, made.id, days_from_today(60))

    assert moved is not None and moved.live and moved.until == days_from_today(60)
    assert moved.path == made.path, "the address is the same one the doctor already has"
    assert connectors.secret_file(made.id, folder).read_text(encoding="utf-8") == before
    assert moved.archives == made.archives and moved.name == made.name


def test_the_word_forever_is_a_link_with_no_end(tmp_path: Path):
    """Taking the end off is the same writer as setting it, because it is the same fact."""
    made, _secret = connectors.issue(tmp_path, until=days_from_today(-1), secrets_folder=a_secrets_folder(tmp_path))

    moved = connectors.set_until(tmp_path, made.id, "")

    assert moved is not None and moved.until == "" and moved.live


def test_a_link_past_its_day_can_still_be_taken_back(tmp_path: Path):
    """And it has to be, because until it is, its code secret is still in /etc.

    Asking `live` in `revoke` would have refused to take back exactly the links somebody has
    stopped thinking about — the ones that ended months ago — and left every one of their secrets
    on the machine.
    """
    folder = a_secrets_folder(tmp_path)
    made, _secret = connectors.issue(tmp_path, until=days_from_today(-90), secrets_folder=folder)
    assert connectors.secret_file(made.id, folder).exists(), "an ended link keeps its secret"

    gone = connectors.revoke(tmp_path, made.id, secrets_folder=folder)

    assert gone is not None and gone.revoked_at
    assert not connectors.secret_file(made.id, folder).exists()


def test_an_ended_link_keeps_its_address_and_a_revoked_one_does_not(tmp_path: Path):
    """Because one of them comes back and the other cannot.

    The page draws the address next to the field that moves the day: that is where somebody
    extends a link, and an address missing from it would have the page say "this instance has no
    public name yet", which is its sentence for an address it cannot build at all.
    """
    folder = a_secrets_folder(tmp_path)
    ended, _ = connectors.issue(tmp_path, until=days_from_today(-1), secrets_folder=folder)
    taken_back, _ = connectors.issue(tmp_path, secrets_folder=folder)
    connectors.revoke(tmp_path, taken_back.id, secrets_folder=folder)

    assert connectors.the_link_to(ended, "host.ts.net").endswith(ended.path)
    assert connectors.the_link_to(connectors.get(tmp_path, taken_back.id), "host.ts.net") == ""


def test_a_day_that_is_not_a_day_is_refused_and_nothing_is_written(tmp_path: Path):
    """A date nobody could read must not land on a line and quietly become the day a link stops."""
    made, _secret = connectors.issue(tmp_path, until=days_from_today(5), secrets_folder=a_secrets_folder(tmp_path))

    for said in ("next March", "2027-13-01", "2027-02-31", "31/03/2027", "2027"):
        with pytest.raises(ValueError):
            connectors.set_until(tmp_path, made.id, said)

    assert connectors.get(tmp_path, made.id).until == days_from_today(5), "the day it had is untouched"


def test_a_day_written_by_hand_that_will_not_read_shuts_the_links(tmp_path: Path):
    """Refused rather than guessed, in the direction `archives` is refused in and for the reason.

    Guessed either way it is wrong and silent: read as no end, a link somebody meant to expire
    answers for ever; read as ended, a link somebody is using goes quiet with nothing anywhere to
    say why. Refused, the page says the file will not read and names the copy to put back.
    """
    connectors.issue(tmp_path, secrets_folder=a_secrets_folder(tmp_path))
    file = tmp_path / layout.CONNECTORS
    stored = json.loads(file.read_text(encoding="utf-8"))
    stored[0]["until"] = "next March"
    file.write_text(json.dumps(stored), encoding="utf-8")

    with pytest.raises(Unreadable):
        connectors.load(tmp_path)
    assert connectors.unreadable(tmp_path)


def test_the_number_in_the_file_is_refused_too(tmp_path: Path):
    """`"until": 2027` is a line somebody edited by hand, and a year is not a day."""
    connectors.issue(tmp_path, secrets_folder=a_secrets_folder(tmp_path))
    file = tmp_path / layout.CONNECTORS
    stored = json.loads(file.read_text(encoding="utf-8"))
    stored[0]["until"] = 2027
    file.write_text(json.dumps(stored), encoding="utf-8")

    with pytest.raises(Unreadable):
        connectors.load(tmp_path)


def test_the_pair_carried_in_from_before_the_registry_has_no_end(tmp_path: Path):
    """The owner's own link, and the one person who would not be told it had stopped.

    He is the one who gets no page and no notice: his assistant simply stops answering about his
    own records. Whatever this program does by default, it does not do that to him.
    """
    folder = a_secrets_folder(tmp_path)
    (tmp_path / "token").write_text("t" * 48 + "\n", encoding="utf-8")
    (tmp_path / "totp").write_text("ABCDEFGHIJKLMNOP\n", encoding="utf-8")

    made = connectors.carry_the_one_secret_in(tmp_path, ("aa11bb22",), token_file=tmp_path / "token",
                                              totp_file=tmp_path / "totp", secrets_folder=folder)  # fmt: skip

    assert made is not None and made.until == "" and made.live
