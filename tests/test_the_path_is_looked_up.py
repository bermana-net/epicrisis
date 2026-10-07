"""Which paths this server answers on: whatever the registry holds, and nothing else.

Until now one secret was baked into the application when it was built, so a link could only be
added or taken back by restarting. Now the dispatcher in front of it reads the registry on every
request — and the three things that had to survive that are what these tests are about.
"""

import json

import pytest
from fastapi.testclient import TestClient

from epicrisis import connectors, mcp_access
from epicrisis.mcp_server import SERVED_AT, http_app

CALL = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


def a_link(data_dir, path: str, name: str = "") -> str:
    """A live connector whose address is that exact secret, written into the registry."""
    already = connectors.load(data_dir)
    connectors.save(data_dir, [*already, connectors.Connector(
        id=f"{len(already):08x}", path=path, name=name, issued_at="2026-01-01T00:00:00+00:00")])  # fmt: skip
    return path


def test_two_links_both_answer_and_neither_needs_a_restart(tmp_path):
    """The point of the registry: a link issued on the page works without the server moving.

    The application underneath is built once, with one path baked into it, because
    `streamable_http_app` takes exactly one — so what changed is the dispatcher in front, and the
    second link below is added **after** the app was built.
    """
    first = a_link(tmp_path, "f" * 48)
    app = http_app(tmp_path)

    with TestClient(app, base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        assert client.post(f"/mcp/{first}", json=CALL, headers=HEADERS).status_code == 200
        second = a_link(tmp_path, "s" * 48)
        assert client.post(f"/mcp/{second}", json=CALL, headers=HEADERS).status_code == 200


def test_a_revoked_link_is_a_wrong_path_and_says_no_more_than_that(tmp_path):
    """Somebody who could tell "revoked" from "wrong" has learnt that the address was once real.

    Same status, same body, and the line in the log of calls says the same word for both.
    """
    secret = a_link(tmp_path, "r" * 48)
    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        assert client.post(f"/mcp/{secret}", json=CALL, headers=HEADERS).status_code == 200
        connectors.revoke(tmp_path, connectors.load(tmp_path)[0].id, secrets_folder=tmp_path / "secrets")

        taken_back = client.post(f"/mcp/{secret}", json=CALL, headers=HEADERS)
        invented = client.post(f"/mcp/{'x' * 48}", json=CALL, headers=HEADERS)

    assert taken_back.status_code == invented.status_code == 404
    assert taken_back.text == invented.text
    lines = [json.loads(line) for line in mcp_access.path(tmp_path).read_text(encoding="utf-8").splitlines()]
    refusals = [line for line in lines if not line["allowed"]]
    assert len(refusals) == 2
    assert {line["refused"] for line in refusals} == {"path"}
    # And neither refusal says which link it nearly was.
    assert all("connector" not in line for line in refusals), refusals


def test_the_line_in_the_log_says_which_link_answered(tmp_path):
    """So the record of calls can be read per connector, which is the question somebody asks when
    a link goes quiet. The id is four random bytes; the secret never reaches that line."""
    secret = a_link(tmp_path, "a" * 48, name="for the cardiologist")
    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        client.post(f"/mcp/{secret}", json=CALL, headers=HEADERS)

    answered = [json.loads(line) for line in mcp_access.path(tmp_path).read_text(encoding="utf-8").splitlines()]
    assert answered[0]["connector"] == connectors.load(tmp_path)[0].id
    assert secret not in mcp_access.path(tmp_path).read_text(encoding="utf-8")
    assert "cardiologist" not in mcp_access.path(tmp_path).read_text(encoding="utf-8")


def test_the_path_the_application_sits_at_is_not_a_way_in(tmp_path):
    """One application serves every link, so it is mounted somewhere — and that somewhere must not
    be an address. It matches no entry, so it is refused like any other wrong path."""
    a_link(tmp_path, "m" * 48)
    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        assert client.post(SERVED_AT, json=CALL, headers=HEADERS).status_code == 404


def test_a_path_that_is_not_ascii_is_refused_and_written_down(tmp_path):
    """`compare_digest` raises on anything else, and that used to be a 500 to a scanner.

    One accented letter in the address and the server answered with an error, told whoever asked
    that something was there, and kept no record of having been asked at all.
    """
    a_link(tmp_path, "n" * 48)
    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        answer = client.post("/mcp/é" + "n" * 47, json=CALL, headers=HEADERS)

    assert answer.status_code == 404
    lines = [json.loads(line) for line in mcp_access.path(tmp_path).read_text(encoding="utf-8").splitlines()]
    assert lines and lines[-1]["refused"] == "path"


def test_a_registry_that_will_not_read_shuts_every_link(tmp_path):
    """The safe direction for this file to fail in: the archives are shut rather than open.

    And the refusal says no more than a wrong path's, because a stranger is owed no explanation
    of why the server cannot read its own list.
    """
    secret = a_link(tmp_path, "u" * 48)
    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        assert client.post(f"/mcp/{secret}", json=CALL, headers=HEADERS).status_code == 200
        (tmp_path / "connectors.json").write_text("{ not json", encoding="utf-8")

        answer = client.post(f"/mcp/{secret}", json=CALL, headers=HEADERS)

    assert answer.status_code == 404
    assert "connectors" not in answer.text and "json" not in answer.text


def test_a_short_path_in_a_hand_edited_registry_opens_nothing(tmp_path):
    """`MIN_SECRET` used to be checked once, when the server was built, and raised there.

    The registry generates nothing shorter, so the only way to get one is to edit the file —
    and the answer to that is a link that opens nothing, not a server that will not start.
    """
    a_link(tmp_path, "short")
    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        assert client.post("/mcp/short", json=CALL, headers=HEADERS).status_code == 404


def test_every_live_link_is_compared_whether_or_not_one_matches(tmp_path):
    """How long the lookup takes must not say which link matched, or whether one did.

    Asserted on the code rather than on a clock: a timing test on a laptop is noise. What is held
    is that the loop has no early exit, which is the thing a reader would "tidy" away.
    """
    import inspect

    from epicrisis.mcp_server import RecordAccess

    source = inspect.getsource(RecordAccess._whose_path)

    assert "break" not in source and "return one.id" not in source
    assert "compare_digest" in source
    # And it does answer, so the absence of a break is not the absence of the lookup.
    a_link(tmp_path, "e" * 48)
    a_link(tmp_path, "l" * 48)
    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        assert client.post("/mcp/" + "e" * 48, json=CALL, headers=HEADERS).status_code == 200
        assert client.post("/mcp/" + "l" * 48, json=CALL, headers=HEADERS).status_code == 200
