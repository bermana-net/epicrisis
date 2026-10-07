"""A code belongs to the link it was issued with, and so does the wait after guessing wrong.

Before this one secret and one run of wrong codes stood for the whole server, which meant two
things that are plainly wrong once there is more than one link: a code meant for one person's
connector opened everybody's, and one person guessing badly held every other link shut.
"""

import json
import time

import pytest
from fastapi.testclient import TestClient

from epicrisis import connectors, mcp_lock, settings
from epicrisis.mcp_server import http_app

HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


@pytest.fixture(autouse=True)
def secrets_go_nowhere_near_the_machine(tmp_path, monkeypatch):
    """Every link's code secret is written into this test's own folder, never under /etc."""
    monkeypatch.setattr(connectors, "SECRETS_FOLDER", tmp_path / "connector-secrets")


def two_links(data_dir):
    """Two links, each with a code secret of its own, and the lock turned on."""
    settings.set_mcp_lock(data_dir, True)
    first, first_code = connectors.issue(data_dir, name="one")
    second, second_code = connectors.issue(data_dir, name="two")
    return (first, first_code), (second, second_code)


def call(client, link, name, arguments=None):
    return client.post(f"/mcp/{link.path}", headers=HEADERS, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    })  # fmt: skip


def test_a_code_from_one_link_does_not_open_another(tmp_path):
    """The whole point. One shared secret made every connector the same connector."""
    (first, first_code), (second, _second_code) = two_links(tmp_path)
    now = time.time()

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        for_the_first = mcp_lock.code_at(first_code, now)
        mine = call(client, first, "unlock", {"code": for_the_first})
        theirs = call(client, second, "unlock", {"code": for_the_first})

    assert "\"pass\"" in mine.text, mine.text
    assert "\"pass\"" not in theirs.text, theirs.text


def test_the_answer_says_which_link_the_code_belonged_to(tmp_path):
    """Four random bytes, carrying no part of anybody's name, and what the owner says to revoke
    it. The page and the log of calls print the same thing beside it."""
    (first, first_code), _second = two_links(tmp_path)

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        answer = call(client, first, "unlock", {"code": mcp_lock.code_at(first_code, time.time())})

    assert first.id in answer.text
    # And never the code it was opened with, nor the address it came in on.
    assert first_code not in answer.text and first.path not in answer.text


def test_guessing_at_one_link_does_not_shut_the_others(tmp_path):
    """Counted for the server, one person guessing badly holds somebody else's doctor out.

    That is not a theoretical shape: the wait is what the lock does to whoever is guessing, and a
    stranger who reached the address could put every link on the instance into it.
    """
    (first, _first_code), (second, second_code) = two_links(tmp_path)

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        for _ in range(mcp_lock.WRONG_CODES + 1):
            call(client, first, "unlock", {"code": "000000"})
        guessed_at = call(client, first, "unlock", {"code": "000000"})
        the_other = call(client, second, "unlock", {"code": mcp_lock.code_at(second_code, time.time())})

    assert "wait" in guessed_at.text.lower() or "too many" in guessed_at.text.lower(), guessed_at.text
    assert "\"pass\"" in the_other.text, the_other.text


def test_the_run_of_wrong_codes_is_remembered_per_link(tmp_path):
    """Kept in a file so it survives a restart, and one file per link so it survives correctly.

    One file for the server was the same defect as one secret: the owner's way out of a wait
    somebody else had put them into was to restart, which was also the way out for the guesser.
    """
    (first, _first_code), (second, _second_code) = two_links(tmp_path)

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        call(client, first, "unlock", {"code": "000000"})

    # In a folder of their own, because the server that writes them runs under a unit that may
    # write what is named in it and nothing else — and a folder can be named there, while a file
    # per link, whose name nobody knows in advance, cannot.
    written = [one.name for one in mcp_lock.every_wait_kept(tmp_path)]
    assert written == [f"{first.id}.json"], written
    assert second.id not in " ".join(written)
    assert mcp_lock.where_the_wait_is_kept(tmp_path, first.id).exists()


def test_over_stdio_the_lock_is_the_instance_s_own_as_it_always_was(tmp_path):
    """There is no link over stdio, and there is no tunnel either: it is the owner at their own
    machine, running `claude mcp` against their own data directory."""
    from epicrisis.mcp_server import THE_LINK_ANSWERING, build_server

    mcp_lock.write_secret(mcp_lock.new_secret(), tmp_path / "instance-secret")

    assert THE_LINK_ANSWERING.get() is None
    # Built without the network, which is what `run` does for stdio: the lock is not even asked.
    assert build_server(tmp_path) is not None


def test_a_link_whose_secret_file_is_gone_has_no_lock_rather_than_the_instance_s(tmp_path, monkeypatch):
    """The one place in this program that failed open, found by a round of its own security role.

    `unlock` picks up a secret written after the server started, so that a link issued on the page
    works without a restart. It picked it up from the **instance's** file — which is right for the
    lock of the whole server, where that file is its own, and wrong for the lock of a link: a link
    whose code secret could not be read accepted the code that once opened the whole instance, and
    refused the code it had itself printed for whoever holds it.

    That is reachable without anything exotic: `connector add --secrets-folder` is a documented
    option with no counterpart on the server, so a link issued with it has its secret in a folder
    the server never looks in. And `revoke` takes a link's own secret off the machine while
    leaving the instance's where it is — so the code of a person who has just been shut out was
    the code that opened every link whose file had gone missing.

    Everything else here fails closed. This now does too: no file, no lock.
    """
    import time

    from epicrisis import mcp_lock

    instance = tmp_path / "mcp-totp"
    instance.write_text(mcp_lock.new_secret() + "\n", encoding="utf-8")
    monkeypatch.setattr(mcp_lock, "SECRET_FILE", instance)

    lock = mcp_lock.Lock(secret=None, secret_file=tmp_path / "never-written")

    with pytest.raises(mcp_lock.Locked, match="no lock set up"):
        lock.unlock(mcp_lock.code_at(instance.read_text().strip(), time.time()))
    assert lock.secret is None, "it read somebody else's secret after all"


def test_a_lock_still_picks_up_its_own_secret_written_after_the_server_started(tmp_path):
    """And the thing the fallback was for goes on working: a link issued on the page answers
    without a restart, because its own file is read again when a code arrives."""
    import time

    from epicrisis import mcp_lock

    file = tmp_path / "its-own"
    lock = mcp_lock.Lock(secret=None, secret_file=file)
    secret = mcp_lock.new_secret()
    file.write_text(secret + "\n", encoding="utf-8")

    opened = lock.unlock(mcp_lock.code_at(secret, time.time()))

    assert opened["pass"]


def test_the_documented_way_out_of_a_wait_clears_every_link_s(tmp_path):
    """A person locked out ran the way out that is written down, and nothing happened.

    Each link counts wrong codes on its own — one person guessing badly must not hold the others
    out — so there is a file per link. `mcp-lock clear` knew only the instance's own file: it
    cleared the wait of a lock nobody was knocking on and left every link's standing. The command
    and the server built that path in two different places, which is how the two came apart.
    """
    import typer.testing

    from epicrisis.cli import app

    (first, _code), (second, _second) = two_links(tmp_path)
    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        for _try in range(3):
            call(client, first, "unlock", {"code": "000000"})
        call(client, second, "unlock", {"code": "000000"})

    waits = mcp_lock.every_wait_kept(tmp_path)
    assert sorted(one.name for one in waits) == sorted([f"{first.id}.json", f"{second.id}.json"]), waits

    said = typer.testing.CliRunner().invoke(app, ["mcp-lock", "clear", "--data-dir", str(tmp_path)])

    assert said.exit_code == 0, said.output
    # Three wrong codes and one are not a wait: it takes five. The command takes both files and
    # says what it was — "2 waits cleared" over files holding nobody out told somebody their way
    # out had done something when there had been nothing to do.
    assert "There was no wait to clear" in said.output, said.output
    assert "2 files of wrong codes that were holding nobody out" in said.output, said.output

    # And a real wait, said as one. Five wrong codes on one link is the step that starts the
    # clock, and clearing it is the way out the settings page points at.
    held = mcp_lock.where_the_wait_is_kept(tmp_path, first.id)
    held.parent.mkdir(parents=True, exist_ok=True)
    held.write_text(json.dumps([time.time()] * mcp_lock.WRONG_CODES), encoding="utf-8")

    cleared = typer.testing.CliRunner().invoke(app, ["mcp-lock", "clear", "--data-dir", str(tmp_path)])

    assert "1 wait cleared" in cleared.output, cleared.output
    assert "can try a code again now" in cleared.output
    assert mcp_lock.whoever_is_waiting(tmp_path) == []
    assert mcp_lock.every_wait_kept(tmp_path) == []
