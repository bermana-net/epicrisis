"""The lock on the archive over the network. Synthetic secrets only."""

import pytest
from test_ask import archive_index  # noqa: F401
from test_extract import FakeExtractBackend, setup  # noqa: F401

from epicrisis.mcp_lock import DIGITS, Lock, Locked, code_at, new_secret, uri

# RFC 6238, the vectors everyone implements against: the secret is "12345678901234567890".
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def test_codes_match_the_standard_s_own_vectors():
    assert code_at(RFC_SECRET, 59, digits=8) == "94287082"
    assert code_at(RFC_SECRET, 1111111109, digits=8) == "07081804"
    assert code_at(RFC_SECRET, 1234567890, digits=8) == "89005924"
    assert code_at(RFC_SECRET, 2000000000, digits=8) == "69279037"
    # Six digits are the same number, shorter: what an authenticator shows by default.
    assert code_at(RFC_SECRET, 59) == "287082" and len(code_at(RFC_SECRET, 59)) == DIGITS


def test_a_code_opens_the_archive_once_and_the_pass_carries_it():
    now = 1_700_000_000.0
    lock = Lock(secret=RFC_SECRET)

    with pytest.raises(Locked, match="locked"):
        lock.require(None, enabled=True, now=now)

    given = lock.unlock(code_at(RFC_SECRET, now), now=now)
    lock.require(given["pass"], enabled=True, now=now)  # the pass works

    # Someone else's string does not, and the same code cannot be used a second time.
    with pytest.raises(Locked):
        lock.require("a-pass-of-their-own", enabled=True, now=now)
    with pytest.raises(Locked, match="already been used"):
        lock.unlock(code_at(RFC_SECRET, now), now=now)

    # A clock a step out still fits; a wrong code never does.
    assert lock.unlock(code_at(RFC_SECRET, now - 30), now=now)["pass"]
    with pytest.raises(Locked):
        lock.unlock("000000", now=now)


def test_the_pass_runs_out_and_can_be_thrown_away_early():
    now = 1_700_000_000.0
    lock = Lock(secret=RFC_SECRET, minutes=240)
    ticket = lock.unlock(code_at(RFC_SECRET, now), now=now)["pass"]

    lock.require(ticket, enabled=True, now=now + 3 * 3600)
    with pytest.raises(Locked):
        lock.require(ticket, enabled=True, now=now + 5 * 3600)

    fresh = lock.unlock(code_at(RFC_SECRET, now + 5 * 3600), now=now + 5 * 3600)["pass"]
    assert lock.lock(fresh) == {"locked": True, "passes_closed": 1}
    with pytest.raises(Locked):
        lock.require(fresh, enabled=True, now=now + 5 * 3600)


def test_guessing_is_made_to_wait_longer_every_time():
    """Six digits are guessable in a day at full speed; each run of wrong codes waits longer."""
    now = 1_700_000_000.0
    lock = Lock(secret=RFC_SECRET)
    for _ in range(5):
        with pytest.raises(Locked):
            lock.unlock("000000", now=now)

    # Even the right code is not looked at while the wait runs.
    with pytest.raises(Locked, match="Too many wrong codes"):
        lock.unlock(code_at(RFC_SECRET, now), now=now)

    # Knocking while the wait runs does not push it further away. Counting a knock would let
    # anyone who reached this address keep the owner out for as long as they cared to knock,
    # with the owner's own code refused the whole time.
    for _ in range(10):
        with pytest.raises(Locked, match="Too many wrong codes"):
            lock.unlock("000000", now=now + 30)
    assert lock.unlock(code_at(RFC_SECRET, now + 61), now=now + 61)["pass"]  # a minute, the first time

    # A code that fits ends the run. Ten wrong ones after it, spaced far enough apart that each
    # is looked at, and the wait is five minutes rather than one.
    began = now + 120
    for guess in range(10):
        with pytest.raises(Locked):
            lock.unlock("000000", now=began + guess * 70)
    last = began + 9 * 70
    with pytest.raises(Locked, match="Too many wrong codes"):
        lock.unlock(code_at(RFC_SECRET, last + 70), now=last + 70)
    assert lock.unlock(code_at(RFC_SECRET, last + 301), now=last + 301)["pass"]

    # And the owner can throw the whole thing away from the server, when a stranger made them wait.
    for _ in range(5):
        with pytest.raises(Locked):
            lock.unlock("000000", now=last + 400)
    lock.clear()
    assert lock.unlock(code_at(RFC_SECRET, last + 401), now=last + 401)["pass"]


def test_a_lock_that_is_off_lets_everything_through():
    lock = Lock(secret=RFC_SECRET)
    lock.require(None, enabled=False)  # raises nothing


def test_a_fresh_secret_reads_into_an_authenticator():
    secret = new_secret()
    line = uri(secret)

    assert secret not in ("", None) and len(secret) >= 32
    assert line.startswith("otpauth://totp/Epicrisis:archive?secret=") and "digits=6" in line and "period=30" in line
    assert code_at(secret, 1_700_000_000.0) != code_at(new_secret(), 1_700_000_000.0)


def test_the_tools_are_refused_while_the_archive_is_locked(archive_index, monkeypatch):  # noqa: F811
    """With the lock on, every reading tool wants the pass; unlock is the only way to get one."""
    import asyncio
    import time

    from epicrisis import mcp_lock as lock_module
    from epicrisis.settings import set_mcp_lock
    from epicrisis.mcp_server import build_server

    data_dir, _, _ = archive_index
    monkeypatch.setattr(lock_module, "read_secret", lambda *args: RFC_SECRET)
    server = build_server(data_dir, over_the_network=True)

    # Off by default: nothing changes for anyone, which is how it ships.
    assert asyncio.run(server.call_tool("archive_overview", {})).is_error is False

    # Locked, a call answers with a notice rather than an error: an error is drawn as a failure
    # and read as one, and what is needed here is a step, not a stack trace.
    from mcp.server.mcpserver.exceptions import ToolError

    set_mcp_lock(data_dir, True)
    shut = asyncio.run(server.call_tool("archive_overview", {}))
    assert shut.is_error is False
    assert shut.structured_content["locked"] is True
    assert "not data" in " ".join(shut.structured_content).replace("_", " ")
    assert "authenticator" in shut.structured_content["what_to_do_now"]

    opened = asyncio.run(server.call_tool("unlock", {"code": code_at(RFC_SECRET, time.time())}))
    ticket = opened.structured_content["pass"]
    assert asyncio.run(server.call_tool("archive_overview", {"ticket": ticket})).is_error is False

    # Thrown away on request, and shut again after that.
    asyncio.run(server.call_tool("lock_archive", {"ticket": ticket}))
    assert asyncio.run(server.call_tool("archive_overview", {"ticket": ticket})).structured_content["locked"] is True

    # A wrong code is a real failure, though, and stays one.
    with pytest.raises(ToolError, match="does not fit"):
        asyncio.run(server.call_tool("unlock", {"code": "000000"}))

    set_mcp_lock(data_dir, False)
    assert asyncio.run(server.call_tool("archive_overview", {})).is_error is False


def test_a_code_can_open_the_server_instead_of_one_conversation():
    """The instance chooses. Opening everything is easier and gives away what the lock is for."""
    now = 1_700_000_000.0
    lock = Lock(secret=RFC_SECRET, minutes=60)

    # A code taken for one conversation opens that conversation and nothing else — even if the
    # instance is set to open as a whole afterwards, while the pass is still good.
    lock.unlock(code_at(RFC_SECRET, now), now=now, scope="conversation")
    with pytest.raises(Locked):
        lock.require(None, enabled=True, now=now, scope="server")

    lock.unlock(code_at(RFC_SECRET, now + 31), now=now + 31, scope="server")

    # A caller with no pass of their own: turned away by default, welcomed when the server is open.
    with pytest.raises(Locked):
        lock.require(None, enabled=True, now=now, scope="conversation")
    lock.require(None, enabled=True, now=now, scope="server")

    # The window ends for everyone at once, and locking everywhere ends it early.
    with pytest.raises(Locked):
        lock.require(None, enabled=True, now=now + 61 * 60, scope="server")
    lock.unlock(code_at(RFC_SECRET, now + 61 * 60), now=now + 61 * 60, scope="server")
    lock.lock(everywhere=True)
    with pytest.raises(Locked):
        lock.require(None, enabled=True, now=now + 61 * 60, scope="server")


def test_one_patient_to_a_pass_bound_by_the_first_question_asked():
    """One active patient to a conversation, and a conversation here is a pass.

    A code opens the lock and picks nobody: who the conversation is about is decided by the first
    question asked in it, and after that this pass is for that person. Another means closing it
    and taking a new code — the records of two people never meet, and a model's own context is
    the one place they could.

    Not the rule this test used to hold. The old one wrote the archive at unlock time out of
    whatever the dashboard had open and tore the pass up when somebody pressed Show, which was a
    rule about the dashboard; it reaches no connector now. This binds to what was asked for.
    """
    now = 1_700_000_000.0
    lock = Lock(secret=RFC_SECRET, minutes=60)

    ticket = lock.unlock(code_at(RFC_SECRET, now), now=now)["pass"]

    # Nobody yet, and a call that names nobody does not bind it.
    assert lock.passes[ticket] == (now + 60 * 60, "")
    lock.require(ticket, enabled=True, now=now + 10)
    assert lock.passes[ticket][1] == ""
    # The first question names them, and the pass is for that one from here on.
    lock.require(ticket, enabled=True, now=now + 60, about="vera")
    assert lock.passes[ticket][1] == "vera"
    lock.require(ticket, enabled=True, now=now + 120, about="vera")
    with pytest.raises(Locked, match="one person's records"):
        lock.require(ticket, enabled=True, now=now + 180, about="anders")
    # Refused and not closed: the conversation it was reading goes on working.
    lock.require(ticket, enabled=True, now=now + 240, about="vera")
    # A second code opens a second conversation, for whoever the first question there names.
    second = lock.unlock(code_at(RFC_SECRET, now + 300), now=now + 300)["pass"]
    lock.require(second, enabled=True, now=now + 360, about="anders")
    assert lock.passes[second][1] == "anders"
    # And it still runs out, and it is still only a pass that opens anything.
    with pytest.raises(Locked):
        lock.require(ticket, enabled=True, now=now + 3700, about="vera")
    with pytest.raises(Locked):
        lock.require("not a pass", enabled=True, now=now + 60, about="vera")


def test_a_server_opened_as_a_whole_is_open_to_everyone_who_reaches_it():
    """What that setting gives up, held as a test so nobody has to find out by using it.

    This used to say the wider setting widened who may read and not whose records — true while
    the lock also knew which archive a call was about. It does not any more: a call names its own
    archive, which `mcp_server.answering` checks against what the link reaches, and the lock
    answers only "is it you". So one code set to open the server opens **every call that reaches
    it** until the window runs out, with no pass at all.

    That is what the settings page says in so many words — "Opening everything is easier to live
    with and gives that up for the length of the window" — and what a person choosing it is
    choosing. The narrower setting, which is the default, keeps the opening with whoever made it.
    """
    now = 1_700_000_000.0
    lock = Lock(secret=RFC_SECRET, minutes=60)
    lock.unlock(code_at(RFC_SECRET, now), now=now, scope="server")

    # No pass, and let through, which is the whole of the trade.
    lock.require(None, enabled=True, now=now + 60, scope="server")
    lock.require(None, enabled=True, now=now + 3000, scope="server")
    # And it ends. A window that did not would be a lock that was turned off by using it once.
    with pytest.raises(Locked):
        lock.require(None, enabled=True, now=now + 3700, scope="server")
    # The narrower setting does not let a call with no pass through at any point.
    shut = Lock(secret=RFC_SECRET, minutes=60)
    shut.unlock(code_at(RFC_SECRET, now), now=now, scope="conversation")
    with pytest.raises(Locked):
        shut.require(None, enabled=True, now=now + 60, scope="conversation")


def test_an_index_the_server_cannot_read_is_said_in_words(archive_index, monkeypatch):  # noqa: F811
    """A server that cannot open its own index must not look like an archive with nothing in it.

    This was live: files written by root, a server running as somebody else, and every tool after
    the unlock answering "Error executing tool search_documents" — no reason, nothing to act on.
    """
    import asyncio
    import sqlite3

    from mcp.server.mcpserver.exceptions import ToolError

    from epicrisis import query
    from epicrisis.mcp_server import build_server

    data_dir, _, _ = archive_index
    server = build_server(data_dir)
    assert asyncio.run(server.call_tool("archive_overview", {})).is_error is False

    def shut_out(*args, **kwargs):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(query, "open_index", shut_out)
    with pytest.raises(ToolError, match="cannot be read.*unable to open database file"):
        asyncio.run(server.call_tool("search_documents", {"query_text": "anything"}))
    with pytest.raises(ToolError, match="Nothing was searched"):
        asyncio.run(server.call_tool("archive_overview", {}))


def test_the_code_is_asked_for_over_the_network_and_not_on_this_machine(archive_index, monkeypatch):  # noqa: F811
    """The lock guards an address the internet can reach. Over stdio there is no address.

    The Ask page of a person's own dashboard starts `epicrisis mcp` as a child process, and that
    page shows the same values without a code. Asking there guarded nothing and stopped the page
    from answering at all.
    """
    import asyncio

    from epicrisis import mcp_lock as lock_module
    from epicrisis.settings import set_mcp_lock
    from epicrisis.mcp_server import build_server

    data_dir, _, _ = archive_index
    monkeypatch.setattr(lock_module, "read_secret", lambda *args: RFC_SECRET)
    set_mcp_lock(data_dir, True)

    on_this_machine = asyncio.run(build_server(data_dir).call_tool("archive_overview", {}))
    assert on_this_machine.is_error is False and "locked" not in on_this_machine.structured_content

    over_the_network = build_server(data_dir, over_the_network=True)
    assert asyncio.run(over_the_network.call_tool("archive_overview", {})).structured_content["locked"] is True


def test_a_settings_file_that_cannot_be_read_does_not_open_the_archive(tmp_path, monkeypatch):
    """The one setting that fails closed, because the other direction is silent and permanent.

    Everything in settings.py answers with its default when the file is missing, which is right
    for a new instance and wrong for a file that exists and will not parse: a truncated one read
    as "no lock" over an archive whose owner had turned the lock on, and the page went on drawing
    it as on.
    """
    from epicrisis import mcp_lock, settings

    (tmp_path / "settings.json").write_text('{"mcp_lock": true', encoding="utf-8")  # cut short
    assert settings.unreadable(tmp_path)

    monkeypatch.setattr(mcp_lock, "read_secret", lambda *rest: "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")
    assert settings.mcp_lock_on(tmp_path) is True

    # Where no secret was ever set up there is nothing to fail closed about, and asking for a code
    # nobody can produce would only shut a person out of their own archive over a corrupt file.
    monkeypatch.setattr(mcp_lock, "read_secret", lambda *rest: None)
    assert settings.mcp_lock_on(tmp_path) is False


def test_the_secret_is_never_readable_by_everybody_even_for_an_instant(tmp_path):
    """Written and then chmod-ed, it stands at 0644 for a moment in a directory anyone may enter.

    This is the one secret where a single silent read is permanent: codes made from it look
    exactly like the owner's, for ever, and nothing would ever show that somebody else has them.
    """
    import os

    from epicrisis.mcp_lock import read_secret, write_secret

    # Under the umask the command that writes this sets for itself. A mode handed to os.open is
    # cut down by it; the group the server runs as would then lose the file it has to read.
    was = os.umask(0o077)
    where = write_secret("GEZDGNBVGY3TQOJQ", tmp_path / "etc" / "mcp-totp")
    assert os.stat(where).st_mode & 0o777 == 0o640
    # And again, over a secret that is already there: --force replaces it.
    again = write_secret("MZXW6YTBOI======", tmp_path / "etc" / "mcp-totp")
    os.umask(was)
    assert os.stat(again).st_mode & 0o777 == 0o640 and read_secret(again) == "MZXW6YTBOI======"


def test_the_wait_after_wrong_codes_outlives_the_server(tmp_path):
    """Kept only in memory, the wait was undone by a restart.

    Which made the documented way for the owner to end a wait — restart the service — the same
    way out for whoever had put them into it.
    """
    from epicrisis.mcp_lock import WRONG_CODES, WRONG_CODES_FILE, Lock, Locked

    secret, kept = new_secret(), tmp_path / WRONG_CODES_FILE
    lock = Lock(secret=secret, remembers=kept)
    for _ in range(WRONG_CODES):
        with pytest.raises(Locked):
            lock.unlock("000000")

    restarted = Lock(secret=secret, remembers=kept)
    with pytest.raises(Locked, match="Too many wrong codes"):
        restarted.unlock("000000")

    # The owner ends it from the server, and that is an act rather than a suggestion to restart
    # the very thing that used to reset it.
    kept.unlink()
    with pytest.raises(Locked, match="does not fit"):
        Lock(secret=secret, remembers=kept).unlock("000000")


def test_the_address_filter_applies_behind_every_kind_of_tunnel():
    """`tailscale serve` marks nothing, so a call through it looked like a call from this machine.

    Which made it welcome before --allow-from was so much as consulted: the one setting that says
    "only the connectors may reach this" did nothing at all in that arrangement.
    """
    from epicrisis.mcp_server import caller_of

    assert caller_of({}, "127.0.0.1") == ("127.0.0.1", False)
    assert caller_of({"tailscale-funnel-request": "1", "x-forwarded-for": "203.0.113.9"}, "127.0.0.1") == ("203.0.113.9", True)
    assert caller_of({"x-forwarded-for": "203.0.113.9"}, "127.0.0.1") == ("203.0.113.9", True)
    # Only something on this machine can forward from loopback. The header from anywhere else is
    # what anyone may write, and it is not read.
    assert caller_of({"x-forwarded-for": "127.0.0.1"}, "198.51.100.7") == ("198.51.100.7", False)


def test_the_lock_command_does_not_print_defaults_as_the_owner_s_own_choices(tmp_path, monkeypatch):
    """`mcp-lock status` over a settings file that will not parse, which it read as facts.

    Every reader in this program answers with its own default over such a file, which is right, and
    the lock's reader fails closed, which is righter. What was wrong was the report: a window of 120
    minutes stored in the file, and a calm "for 240 minutes" printed with exit 0 and no word about
    the file at all. The person reading it is the owner working out why the lock is behaving as it is
    — a lost phone, a clock that drifted — and the settings page has said this in full all along.
    """
    import subprocess
    import sys
    from pathlib import Path

    from epicrisis import settings

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    settings.set_mcp_lock_minutes(data_dir, 120)
    whole = (data_dir / "settings.json").read_text(encoding="utf-8")
    assert "120" in whole
    (data_dir / "settings.json").write_text(whole[: len(whole) // 2], encoding="utf-8")  # cut off

    done = subprocess.run([sys.executable, "-m", "epicrisis", "mcp-lock", "status", "--data-dir", str(data_dir)],
                          capture_output=True, text=True, cwd=Path(__file__).parent.parent)  # fmt: skip
    said = done.stdout + done.stderr

    assert done.returncode == 0, said  # the question was answered; the trouble is named, not raised
    assert "settings.json is there and cannot be read" in said
    assert "240 minutes (a default: the file above cannot be read)" in said
    assert "settings.json.previous" in said, "and the way back is an act, as on the page"
    # The lock staying closed over an unreadable file is the safe direction, and now it says so.
    assert "fails closed" in said


def test_a_file_of_wrong_codes_is_not_a_wait(tmp_path):
    """The count on the settings page answered a different question from the one it asked.

    Each link keeps its run of wrong codes in a file of its own, and the page counted the files.
    A run that was answered correctly leaves the file behind holding `[]`; a run from last week
    has aged out of the window the wait can last. Measured on the owner's own machine: one file,
    two bytes, holding nothing — and "1 link is in a wait after wrong codes", with the command to
    clear it underneath.
    """
    import json
    import time as the_clock

    from epicrisis import mcp_lock

    now = the_clock.time()
    answered = mcp_lock.where_the_wait_is_kept(tmp_path, "aaaa1111")
    answered.parent.mkdir(parents=True, exist_ok=True)
    answered.write_text("[]", encoding="utf-8")
    stale = mcp_lock.where_the_wait_is_kept(tmp_path, "bbbb2222")
    old = now - (mcp_lock.WAITS_MINUTES[-1] * 60 + 600)
    stale.write_text(json.dumps([old] * mcp_lock.WRONG_CODES), encoding="utf-8")
    holding = mcp_lock.where_the_wait_is_kept(tmp_path, "cccc3333")
    holding.write_text(json.dumps([now] * mcp_lock.WRONG_CODES), encoding="utf-8")

    assert len(mcp_lock.every_wait_kept(tmp_path)) == 3, "three files"
    assert [file.name for file in mcp_lock.whoever_is_waiting(tmp_path, now)] == ["cccc3333.json"]

    # And the one that is waiting is waiting for the reason the lock itself says it is.
    lock = mcp_lock.Lock(secret=mcp_lock.new_secret(), remembers=holding)
    lock._recall_wrong(now)
    assert lock._wait_over(now) > 0
