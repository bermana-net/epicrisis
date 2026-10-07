"""What a link is told about the people within its reach, and when.

The names are the program's to give — they are in `sources.json`, typed by their owner, and
`archive_of` carries one on every answer about an archive being read. What is controlled is the
timing: a conversation that opened a link and went no further has been told how many people it
can reach and not who they are, and each name after that is a thing somebody asked for.
"""

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from epicrisis import connectors, mcp_lock, settings
from epicrisis.mcp_server import build_server, http_app
from epicrisis.sources import SourceRegistry

HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


@pytest.fixture(autouse=True)
def secrets_go_nowhere_near_the_machine(tmp_path, monkeypatch):
    monkeypatch.setattr(connectors, "SECRETS_FOLDER", tmp_path / "connector-secrets")


def three_archives(tmp_path):
    """Three archives of three people, and the ids they are known by."""
    registry = SourceRegistry(tmp_path)
    ids = []
    for number, owner in enumerate(("Vasylyna Prokopchuk", "Somebody Else", "A Third Person")):
        folder = tmp_path / f"scans{number}"
        folder.mkdir()
        ids.append(registry.add(str(folder), owner=owner).id)
    registry.set_active(ids[0])
    return ids


def call(client, link, name, arguments=None):
    answer = client.post(f"/mcp/{link.path}", headers=HEADERS, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    })  # fmt: skip
    return answer.text


def test_unlock_says_how_many_and_which_signatures_and_no_names(tmp_path):
    """The §5 decision of this step, in one assertion: counts and signatures, and not a name.

    Naming them here would be telling an assistant who three people are before anybody asked
    about one of them.
    """
    ids = three_archives(tmp_path)
    settings.set_mcp_lock(tmp_path, True)
    link, code = connectors.issue(tmp_path, name="two of three", archives=(ids[1], ids[2]))

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        answer = call(client, link, "unlock", {"code": mcp_lock.code_at(code, time.time())})

    assert '"archives_within_reach":2' in answer.replace(" ", "")
    assert ids[1] in answer and ids[2] in answer
    # **Not one name.** This opens the lock and reads nothing, so there is no archive for it to
    # be about: it used to carry the owner of whatever the dashboard had open, which was right
    # while that was the archive the next call would answer out of, and is not now.
    for name in ("Somebody Else", "A Third Person", "Vasylyna Prokopchuk"):
        assert name not in answer, name
    # And how to say which one a call is about, in one line, because an assistant that has to
    # work it out will work it out wrongly once.
    assert "as `archive` on every call" in answer and "required" in answer


def test_a_name_comes_back_for_one_signature_at_a_time(tmp_path):
    """So that the person being talked to can say which of them to work with, by number or name."""
    ids = three_archives(tmp_path)
    link, _code = connectors.issue(tmp_path, archives=(ids[1],))

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        answer = call(client, link, "archive_name", {"signature": ids[1]})

    assert "Somebody Else" in answer and ids[1] in answer


def test_a_signature_out_of_reach_and_one_of_no_archive_answer_the_same(tmp_path):
    """One refusal, because an answer that told them apart would let somebody walk the signatures
    and learn how many archives this machine holds and which they are nearly allowed."""
    ids = three_archives(tmp_path)
    link, _code = connectors.issue(tmp_path, archives=(ids[1],))

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        somebody_elses = call(client, link, "archive_name", {"signature": ids[0]})
        invented = call(client, link, "archive_name", {"signature": "ffffffff"})

    assert "no_such_access" in somebody_elses and "no_such_access" in invented
    assert json.loads(_structured(somebody_elses)) == json.loads(_structured(invented))
    assert "Vasylyna" not in somebody_elses


def client_again(tmp_path):
    """A second client over the same data directory, for a call outside the `with` above."""
    return TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)).__enter__()


def _structured(answer: str) -> str:
    """The structured half of one streamed MCP answer, for comparing two of them."""
    import re

    found = re.search(r'"structuredContent":(\{.*?\})\}\}', answer)
    assert found, answer[:300]
    return found.group(1)


def test_a_link_that_reaches_nobody_is_told_nothing_about_anybody(tmp_path):
    """A link issued and not yet given anybody: no signature, no count above nought, no name."""
    ids = three_archives(tmp_path)
    settings.set_mcp_lock(tmp_path, True)
    link, code = connectors.issue(tmp_path, archives=())

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        answer = call(client, link, "unlock", {"code": mcp_lock.code_at(code, time.time())})
        # With the lock on, the pass goes on every call after it — the refusal that comes back
        # without one is the lock's and arrives before this tool is reached at all.
        pass_given = json.loads(_structured(answer))["pass"]
        named = call(client, link, "archive_name", {"signature": ids[0], "ticket": pass_given})

    assert '"archives_within_reach":0' in answer.replace(" ", "")
    assert ids[1] not in answer and ids[2] not in answer
    assert "no_such_access" in named
    # And the refusal says the truth, which took a fix: a link that reaches **none** was being
    # told "this reaches more than one, say which" — a sentence that reads as the caller's
    # mistake when it is a half-finished state nobody has finished yet.
    assert "has not been given any archive" in named
    assert "more than one" not in named


def test_over_stdio_every_archive_is_within_reach(tmp_path):
    """There is no link over stdio and nothing to be allowed: it is the owner at their own
    machine, and the console has never asked them to prove anything."""
    ids = three_archives(tmp_path)
    server = build_server(tmp_path)

    answer = asyncio.run(server.call_tool("archive_name", {"signature": ids[2]}))

    assert "A Third Person" in str(answer)


def test_a_signature_out_of_reach_reads_nothing_at_all(tmp_path):
    """The refusal is returned before the registry of archives is asked for a name, so a
    signature somebody guessed does not even reach the file that holds the names."""
    import inspect

    from epicrisis.mcp_server import build_server

    source = inspect.getsource(build_server)
    at_refusal = source.index("no_such_access")
    at_reading = source.index("SourceRegistry(Path(data_dir)).list() if one.id == signature")

    assert at_refusal < at_reading, "the refusal comes before the names are read"


def test_an_archive_a_link_names_that_is_no_longer_here_reaches_nothing(tmp_path):
    """Which archives exist is `sources.json`'s answer, and the link's list is read against it.

    A folder forgotten leaves its id on every link that named it, and a second answerer to "which
    archives are there" is the defect this project spends its weeks removing. Found by a mutation
    that returned the link's own list instead: every other test here names only archives that
    exist, so nothing noticed.
    """
    ids = three_archives(tmp_path)
    link, _code = connectors.issue(tmp_path, archives=(ids[1], "ffffffff"))

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        reaching = call(client, link, "archive_name", {"signature": "ffffffff"})

    assert "no_such_access" in reaching
    # And the one that does exist is still reached, so this is not the whole list going empty.
    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        assert "Somebody Else" in call(client, link, "archive_name", {"signature": ids[1]})


def test_a_name_is_not_given_out_while_the_archive_is_locked(tmp_path):
    """The lock comes first, as it does for every other tool: a name is a thing of the archive.

    Found by a mutation that moved the lock's question below the permission's. Every other test
    of this tool either has the lock off or hands over a pass, so none of them noticed that a
    stranger with the address could have asked who these people are without a code.
    """
    ids = three_archives(tmp_path)
    settings.set_mcp_lock(tmp_path, True)
    link, _code = connectors.issue(tmp_path, archives=(ids[1],))

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        without_a_pass = call(client, link, "archive_name", {"signature": ids[1]})

    assert '"locked":true' in without_a_pass.replace(" ", "")
    assert "Somebody Else" not in without_a_pass
