"""The record of who reached the MCP server. Synthetic secret, synthetic requests."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from epicrisis import connectors, mcp_access
from epicrisis.mcp_server import http_app

SECRET = "s" * 40


def a_link(tmp_path, path: str = SECRET, name: str = "") -> str:
    """One live connector whose address is that secret, written straight into the registry.

    The registry is what the server serves now — there is no secret it is started with — so a
    test of the paths it answers on needs a link on the list. Written rather than issued, because
    `issue` draws its own secret and these tests are about one they can name.
    """
    connectors.save(tmp_path, [*connectors.load(tmp_path), connectors.Connector(
        id=f"{len(connectors.load(tmp_path)):08x}", path=path, name=name,
        issued_at="2026-01-01T00:00:00+00:00")])  # fmt: skip
    return path


def test_every_call_is_recorded_without_the_secret_or_the_question(tmp_path):
    # As a context manager, so the server's own startup runs as it does under uvicorn.
    a_link(tmp_path)
    app = http_app(tmp_path, "example.ts.net")
    with TestClient(app, base_url="https://example.ts.net", client=("127.0.0.1", 9000)) as client:
        client.post(f"/mcp/{SECRET}", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                        "params": {"name": "value_history", "arguments": {"name": "a secret question"}}},
                    headers={"User-Agent": "Claude/1.0", "Accept": "application/json, text/event-stream"})  # fmt: skip
        client.post("/mcp/wrong-path", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    lines = [json.loads(line) for line in mcp_access.path(tmp_path).read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    asked, refused = lines
    assert asked["allowed"] is True and asked["tool"] == "value_history" and asked["call"] == "tools/call"
    assert asked["agent"] == "Claude/1.0" and asked["method"] == "POST" and "at" in asked
    # A request refused for its path is refused before its body is read, so no call is
    # recorded for it — only that it was turned away, and what it was turned away for.
    assert refused["allowed"] is False and refused["refused"] == "path" and "call" not in refused

    # The secret and the arguments of a call are the two things a log of this archive must not hold.
    written = mcp_access.path(tmp_path).read_text(encoding="utf-8")
    assert SECRET not in written and "a secret question" not in written

    counted = mcp_access.counts(tmp_path)
    assert counted["calls"] == 2 and counted["refused"] == 1 and counted["tools"] == {"value_history": 1}
    # The two doors are counted apart: this one knew the address and asked for the wrong path.
    assert (counted["wrong_path"], counted["wrong_address"]) == (1, 0)
    assert mcp_access.last(tmp_path)["allowed"] is False


def test_a_log_that_cannot_be_written_does_not_stop_the_server(tmp_path):
    missing = tmp_path / "gone"
    mcp_access.record(missing, {"allowed": True})  # no directory: recorded nowhere, raises nothing

    assert mcp_access.last(missing) is None
    assert mcp_access.counts(missing)["calls"] == 0 and mcp_access.counts(missing)["refused"] == 0


def test_only_the_connector_s_own_network_is_let_through_the_tunnel(tmp_path):
    """The tunnel connects from this machine, so the address has to come from what it adds."""
    from epicrisis.mcp_server import ANTHROPIC_OUTBOUND, caller_of

    tunnel = {"Tailscale-Funnel-Request": "?1"}
    a_link(tmp_path)
    with TestClient(http_app(tmp_path, "example.ts.net"), base_url="https://example.ts.net",
                    client=("127.0.0.1", 9000)) as client:  # the tunnel always connects from this machine
        outside = client.post(f"/mcp/{SECRET}", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                              headers={**tunnel, "X-Forwarded-For": "34.52.189.90"})  # fmt: skip
        inside = client.post("/mcp/not-the-secret", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                             headers={**tunnel, "X-Forwarded-For": "160.79.106.173"})  # fmt: skip
        # Anyone may write the header; only the tunnel may add to it, and its entry is the last.
        spoofed = client.post(f"/mcp/{SECRET}", json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
                              headers={**tunnel, "X-Forwarded-For": "160.79.106.173, 34.52.189.90"})  # fmt: skip

    assert outside.status_code == 403 and spoofed.status_code == 403
    # The address from the right network gets past the filter; the path then decides, and it is wrong.
    assert inside.status_code == 404

    # A sweep writes one line a minute: the second refusal from the same address is counted, not written.
    lines = [json.loads(line) for line in mcp_access.path(tmp_path).read_text(encoding="utf-8").splitlines()]
    assert [line.get("refused") for line in lines] == ["source", "path"]
    assert [line["caller"] for line in lines] == ["34.52.189.90", "160.79.106.173"]

    # And a refusal is not a call: the alarm for a burst counts what was let in, never a sweep.
    # Nothing here was actually served: one address was turned away, the other asked for a path
    # that does not exist. Neither counts towards the burst alarm.
    day = mcp_access.activity(tmp_path)
    assert day["calls"] == 0 and day["refused"] == 2 and day["unusual"] is False
    # One was a stranger sweeping, the other knew the address and not the path. Never one number.
    assert (day["wrong_address"], day["wrong_path"]) == (1, 1)

    assert caller_of({"tailscale-funnel-request": "?1", "x-forwarded-for": "1.2.3.4, 160.79.106.1"}, "127.0.0.1") == ("160.79.106.1", True)
    assert caller_of({"x-forwarded-for": "160.79.106.1"}, "203.0.113.9") == ("203.0.113.9", False)
    assert ANTHROPIC_OUTBOUND == "160.79.104.0/21"


def test_a_broken_request_is_refused_without_taking_the_server_down(tmp_path):
    """Whatever arrives on a public address, the answer is an answer, not a crash."""
    a_link(tmp_path)
    with TestClient(http_app(tmp_path, "example.ts.net"), base_url="https://example.ts.net",
                    client=("127.0.0.1", 9000)) as client:  # fmt: skip
        nonsense = client.post(f"/mcp/{SECRET}", content=b"{not json at all", headers={"content-type": "application/json"})
        empty = client.post(f"/mcp/{SECRET}", content=b"", headers={"content-type": "application/json"})
        huge = client.post(f"/mcp/{SECRET}", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                   "params": {"name": "search_documents", "arguments": {"query_text": "x" * 100_000}}})  # fmt: skip
        alive = client.post(f"/mcp/{SECRET}", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                            headers={"accept": "application/json, text/event-stream"})  # fmt: skip

    assert nonsense.status_code < 500 and empty.status_code < 500 and huge.status_code < 500
    assert alive.status_code < 500  # and the server still answers after all of that


def test_the_log_is_trimmed_without_writing_anything_beside_it(tmp_path, monkeypatch):
    """The one file this server may write is this log, and the trim has to live inside that.

    The MCP server runs under a systemd unit whose whole point is that it may write the record of
    who called and nothing else on the machine — no sibling file, no temporary name, not even the
    folder. The trim went through `write_whole`, which writes a temporary file beside the old one
    and renames it, so under that unit it could not run at all; and because a log that cannot be
    written must never stop a server, the failure was swallowed. The log would have grown for ever
    and every page about it would have gone on looking right.

    Measured by **what is opened for writing**, and not by what the folder holds afterwards: the
    first draft of this test compared the folder before and after, which a temporary file renamed
    over the old one passes without a mark — it is gone by the time anybody looks. The suite also
    runs as root here, so permissions cannot be the measurement either; root is never told it may
    not write.
    """
    from epicrisis import mcp_access

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    file = mcp_access.path(data_dir)
    file.write_text("".join(json.dumps({"at": "2026-01-01T00:00:00+00:00", "n": n}) + "\n"
                            for n in range(mcp_access.KEEP_LINES + 500)), encoding="utf-8")  # fmt: skip

    opened: list[Path] = []
    plainly = Path.open

    def watched(self, mode="r", *args, **kwargs):
        if any(letter in mode for letter in "wax+"):
            opened.append(Path(self).resolve())
        return plainly(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", watched)
    mcp_access.record(data_dir, {"from": "127.0.0.1", "tool": "archive_overview"})
    monkeypatch.undo()

    assert set(opened) == {file.resolve()}, f"something else was written: {sorted(set(opened))}"
    lines = file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == mcp_access.KEEP_LINES, len(lines)
    # The newest line is the one just written, and the oldest survivors are the tail of the old
    # file: a trim that kept the head would be a log that stops at the day it filled up.
    assert json.loads(lines[-1])["tool"] == "archive_overview"
    assert json.loads(lines[0])["n"] == 501


def test_a_log_that_cannot_be_written_says_so_once_and_the_server_goes_on(tmp_path, capsys, monkeypatch):
    """Swallowing the failure is right. Swallowing it in silence is what made it invisible.

    For the whole life of this file a log that had stopped being written looked exactly like a
    server nobody had called. It says so now — once per run, because a server answering a question
    a second would write that line a thousand times before anybody read one of them — and on
    stderr, which is what systemd keeps, because the unit may not write the archive's own journal.
    """
    from epicrisis import mcp_access

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(mcp_access, "_ALREADY_SAID", False)

    def refuse(*args, **kwargs):
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(Path, "open", refuse)
    mcp_access.record(data_dir, {"from": "127.0.0.1", "tool": "archive_overview"})
    mcp_access.record(data_dir, {"from": "127.0.0.1", "tool": "list_documents"})

    said = capsys.readouterr().err
    assert said.count("cannot be written") == 1, said
    assert "Read-only file system" in said
    assert "goes on answering" in said
