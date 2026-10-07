"""The record of calls says which archive each one was about, and nothing else of the question.

Without it the log says that a link read something and not whose — and "which link read whose, and
when" is the question somebody asks when they are deciding whether to take a link back.
"""

import json

import pytest
from fastapi.testclient import TestClient

from epicrisis import connectors, mcp_access
from epicrisis.mcp_server import http_app
from epicrisis.sources import SourceRegistry

HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


@pytest.fixture(autouse=True)
def secrets_go_nowhere_near_the_machine(tmp_path, monkeypatch):
    monkeypatch.setattr(connectors, "SECRETS_FOLDER", tmp_path / "connector-secrets")


def an_instance(tmp_path):
    from epicrisis.index.build import build_index

    registry = SourceRegistry(tmp_path)
    ids = []
    for owner in ("Vasylyna Prokopchuk", "Somebody Else"):
        folder = tmp_path / owner.split()[0]
        folder.mkdir()
        source = registry.add(str(folder), owner=owner)
        ids.append(source.id)
        build_index(tmp_path, [source])
    registry.set_active(ids[0])
    link, _code = connectors.issue(tmp_path, name="two", archives=tuple(ids))
    return ids, link


def lines(tmp_path):
    return [json.loads(line) for line in mcp_access.path(tmp_path).read_text(encoding="utf-8").splitlines()]


def test_the_line_says_which_archive_the_call_was_about(tmp_path):
    ids, link = an_instance(tmp_path)

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        client.post(f"/mcp/{link.path}", headers=HEADERS, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "archive_overview", "arguments": {"archive": ids[1]}},
        })  # fmt: skip

    answered = lines(tmp_path)[-1]
    assert answered["about"] == ids[1]
    assert answered["connector"] == connectors.load(tmp_path)[0].id
    assert answered["tool"] == "archive_overview"


def test_no_other_argument_reaches_the_log(tmp_path):
    """The rule this file is written under: a log of this archive holding the questions would be
    a second copy of it. A search term is a line off somebody's form, or the name of a disease."""
    ids, link = an_instance(tmp_path)

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        client.post(f"/mcp/{link.path}", headers=HEADERS, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "search_documents",
                       "arguments": {"query_text": "Квазитрофин", "archive": ids[0]}},
        })  # fmt: skip

    written = mcp_access.path(tmp_path).read_text(encoding="utf-8")
    assert ids[0] in written
    assert "Квазитрофин" not in written
    assert "query_text" not in written


def test_a_sentence_sent_as_the_archive_does_not_reach_the_log(tmp_path):
    """A caller could otherwise put a line of somebody's document into this file by naming it
    `archive`. Written only when it has the shape an id has, which is four random bytes."""
    ids, link = an_instance(tmp_path)

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        client.post(f"/mcp/{link.path}", headers=HEADERS, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "archive_overview",
                       "arguments": {"archive": "Хронический пиелонефрит в стадии ремиссии"}},
        })  # fmt: skip

    written = mcp_access.path(tmp_path).read_text(encoding="utf-8")
    assert "пиелонефрит" not in written
    assert '"about"' not in written


def test_a_call_that_names_no_archive_says_nothing_about_one(tmp_path):
    """A field that was there and empty would read as "about nothing" rather than "not said"."""
    ids, link = an_instance(tmp_path)

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        client.post(f"/mcp/{link.path}", headers=HEADERS, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
        })  # fmt: skip

    assert "about" not in lines(tmp_path)[-1]
