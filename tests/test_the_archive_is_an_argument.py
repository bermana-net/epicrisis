"""Which archive a call is about is the call's own argument, and the last of the four doors.

`ARCHITECTURE.md` names four doors that decide whose archive an answer comes from, and says of
all of them: every door takes the archive, no default. The MCP server was the one that still
read a global — whatever the dashboard had open — so a link allowed one person could be answered
about another, and pressing Show in a browser moved what a connector was reading.
"""

import time

import pytest
from fastapi.testclient import TestClient

from epicrisis import connectors, mcp_lock, settings
from epicrisis.mcp_server import http_app
from epicrisis.sources import SourceRegistry

HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


@pytest.fixture(autouse=True)
def secrets_go_nowhere_near_the_machine(tmp_path, monkeypatch):
    monkeypatch.setattr(connectors, "SECRETS_FOLDER", tmp_path / "connector-secrets")


def two_people(tmp_path):
    """Two archives of two people, each with an index of its own and nothing in it.

    Empty on purpose. What these tests are about is **which archive answers**, and the field that
    says so is `archive_of` — the one the server instructions tell a model to trust and to quote.
    Filling the two indexes with a value each would prove the same thing one layer further away
    and tie this file to the shape of a transcription.
    """
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
    return ids


def call(client, link, name, arguments):
    return client.post(f"/mcp/{link.path}", headers=HEADERS, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments},
    }).text  # fmt: skip


def answered(said: str) -> dict:
    """The structured half of one streamed answer, as a dict.

    Asserted on rather than on the text, because the JSON inside the stream is escaped: a test
    looking for `"archive_of": "…"` in the raw body finds `\"archive_of\"` and fails while the
    server is right, which cost three runs here.
    """
    import json
    import re

    found = re.search(r'"structuredContent":(\{.*\})\}\}', said)
    assert found, said[:300]
    return json.loads(found.group(1))


def a_pass(client, link, code):
    """The pass one conversation holds. A link that reaches more than one person needs the lock,
    because one active patient to a conversation is a rule a pass is what keeps."""
    opened = call(client, link, "unlock", {"code": mcp_lock.code_at(code, time.time())})
    return answered(opened)["pass"]


def test_the_argument_decides_and_not_what_the_dashboard_has_open(tmp_path):
    """The whole step. The archive open on the dashboard is the first; the call asks for the second."""
    ids = two_people(tmp_path)
    settings.set_mcp_lock(tmp_path, True)
    link, code = connectors.issue(tmp_path, archives=tuple(ids))

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        said = call(client, link, "value_names", {"archive": ids[1], "ticket": a_pass(client, link, code)})

    assert answered(said)["archive_of"] == "Somebody Else", said[:300]
    assert "Vasylyna Prokopchuk" not in said


def test_pressing_show_on_the_dashboard_moves_nothing_a_connector_reads(tmp_path):
    """What the pass used to be torn up for, and what no longer happens at all.

    A pass written over an archive existed so that switching the dashboard ended the session
    rather than quietly continuing over somebody else's records. The dashboard cannot reach what
    a connector answers about any more, so there is nothing to end.
    """
    ids = two_people(tmp_path)
    settings.set_mcp_lock(tmp_path, True)
    link, code = connectors.issue(tmp_path, archives=tuple(ids))

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        import json

        import re
        opened = call(client, link, "unlock", {"code": mcp_lock.code_at(code, time.time())})
        given = json.loads(re.search(r'"structuredContent":(\{.*\})\}\}', opened).group(1))["pass"]
        before = call(client, link, "value_names", {"archive": ids[0], "ticket": given})
        SourceRegistry(tmp_path).set_active(ids[1])  # the other tab
        after = call(client, link, "value_names", {"archive": ids[0], "ticket": given})

    assert answered(before)["archive_of"] == "Vasylyna Prokopchuk"
    assert answered(after)["archive_of"] == "Vasylyna Prokopchuk", "the switch moved what the link reads"
    assert "was changed to somebody else" not in after, "the pass was torn up over a switch again"
    assert "Somebody Else" not in after


def test_a_call_that_forgets_is_refused_and_not_guessed_at(tmp_path):
    """The deciding argument for the whole design: forgotten here is a refusal.

    Kept in the pass instead, a forgotten archive would have been a confident answer about
    whichever person the pass happened to be opened over. Picking one of several would be this
    server deciding which person a question was about.
    """
    ids = two_people(tmp_path)
    settings.set_mcp_lock(tmp_path, True)
    link, code = connectors.issue(tmp_path, archives=tuple(ids))

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        said = call(client, link, "value_names", {"ticket": a_pass(client, link, code)})

    assert answered(said)["which_archive"]
    assert ids[0] in said and ids[1] in said
    # Nothing was read, and neither person is named in the refusal.
    assert "Vasylyna" not in said and "Somebody Else" not in said


def test_a_link_that_reaches_one_person_never_has_to_name_them(tmp_path):
    """Nothing to be ambiguous about, so the argument may be left out — which is what makes the
    common case, one link for one patient, as simple as it was before any of this."""
    ids = two_people(tmp_path)
    link, _code = connectors.issue(tmp_path, archives=(ids[1],))

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        said = call(client, link, "value_names", {})

    assert answered(said)["archive_of"] == "Somebody Else"
    assert "Vasylyna Prokopchuk" not in said


def test_an_archive_out_of_reach_is_refused_by_every_tool_and_not_only_by_one(tmp_path):
    """The permission is checked in the one door every tool goes through, not per tool.

    Checked per tool it would be eleven places to forget, and the eleventh is the leak.
    """
    ids = two_people(tmp_path)
    link, _code = connectors.issue(tmp_path, archives=(ids[1],))

    # One archive to this link, so no lock is needed: there is nobody to drift to.
    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        for tool, arguments in (("value_names", {}), ("archive_overview", {}), ("list_documents", {}),
                                ("list_indicators", {}), ("flagged_values", {}),
                                ("documents_to_check", {}), ("search_documents", {"query_text": "кров"})):  # fmt: skip
            said = call(client, link, tool, {**arguments, "archive": ids[0]})
            assert "no_such_access" in said, tool
            assert "Vasylyna" not in said, tool
