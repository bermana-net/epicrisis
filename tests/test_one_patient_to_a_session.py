"""One active patient to a conversation, which is the rule the owner asked for from the start.

«При переключении закрывается на ключ сессия, выбирается другой пациент, открывается новая
сессия» — his words when he designed this. A conversation here is a pass: a code opens the lock
and picks nobody, the first question names whom it is about, and after that another means closing
it and taking a new code.

The records of two people never meet. The program's own files and answers have never let them;
a model's context is the one place they could, and this is what stops it.
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


def two_people(tmp_path, lock=True):
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
    settings.set_mcp_lock(tmp_path, lock)
    return ids


def call(client, link, name, arguments):
    return client.post(f"/mcp/{link.path}", headers=HEADERS, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments},
    }).text  # fmt: skip


def answered(said: str) -> dict:
    import json
    import re

    found = re.search(r'"structuredContent":(\{.*\})\}\}', said)
    assert found, said[:300]
    return json.loads(found.group(1))


def test_a_conversation_that_read_one_person_cannot_read_another(tmp_path):
    """The rule, end to end, through the real server.

    And the refusal says what to do rather than only that it will not: close this one and take a
    new code. A refusal nobody can act on is the shape people work around.
    """
    ids = two_people(tmp_path)
    link, code = connectors.issue(tmp_path, archives=tuple(ids))

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        given = answered(call(client, link, "unlock", {"code": mcp_lock.code_at(code, time.time())}))["pass"]
        first = call(client, link, "archive_overview", {"archive": ids[0], "ticket": given})
        second = call(client, link, "archive_overview", {"archive": ids[1], "ticket": given})

    assert answered(first)["archive_of"] == "Vasylyna Prokopchuk"
    assert "one person&#x27;s records" in second or "one person's records" in second, second[:400]
    # The words a person has to act on, and the one they were getting wrong. "Ask for another
    # six-digit code" was read by an assistant as *another authenticator entry* — it told its
    # owner the code had to come from the other patient's own phone, which is false: one code
    # belongs to one link and opens whatever that link reaches. The refusal says so now.
    assert "lock_archive" in second and "fresh" in second and "six-digit code" in second
    assert "same authenticator entry" in second
    # And nothing of the second person came back with the refusal.
    assert "Somebody Else" not in second


def test_the_pass_is_not_bound_until_somebody_is_asked_about(tmp_path):
    """A code opens the lock and picks nobody: who a conversation is about is decided by its
    first question, not by whatever happened to be open when the code was typed."""
    ids = two_people(tmp_path)
    link, code = connectors.issue(tmp_path, archives=tuple(ids))

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        given = answered(call(client, link, "unlock", {"code": mcp_lock.code_at(code, time.time())}))["pass"]
        # A call that names nobody — refused for want of a name, and binding nothing.
        call(client, link, "archive_overview", {"ticket": given})
        # So either of them is still open to this conversation.
        said = call(client, link, "archive_overview", {"archive": ids[1], "ticket": given})

    assert answered(said)["archive_of"] == "Somebody Else"


def test_a_second_code_opens_a_second_conversation(tmp_path):
    """Which is how the owner said it should work: the session closes, another patient is chosen,
    a new session opens. The rule is not a wall around a link; it is a wall around a context."""
    ids = two_people(tmp_path)
    link, code = connectors.issue(tmp_path, archives=tuple(ids))

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        now = time.time()
        first = answered(call(client, link, "unlock", {"code": mcp_lock.code_at(code, now)}))["pass"]
        call(client, link, "archive_overview", {"archive": ids[0], "ticket": first})
        call(client, link, "lock_archive", {"ticket": first})
        # A code of the next step, so it is not the same six digits refused as already used.
        later = now + mcp_lock.STEP_SECONDS
        second = answered(call(client, link, "unlock", {"code": mcp_lock.code_at(code, later)}))["pass"]
        said = call(client, link, "archive_overview", {"archive": ids[1], "ticket": second})

    assert answered(said)["archive_of"] == "Somebody Else"


def test_rights_to_several_people_work_with_no_lock_at_all(tmp_path):
    """Rights are given in the dialog; a session chooses one of the people it has rights to.

    I had made the lock a **precondition** for a link with rights to more than one — which turned
    "grant three, the session picks one" into "grant three and you must also turn the lock on",
    and broke the link this instance was using. That was my addition and not the owner's rule, so
    it is gone: granting three works, and each call names which of the three it is about.

    What the lock adds where it is on is in the tests above: the pass remembers the first person
    asked about, so one conversation cannot walk from one to another. Without a pass there is no
    conversation for the server to hold the rule on — the choice rides on every call instead, and
    the server's part is to default to nobody, which it does.
    """
    ids = two_people(tmp_path, lock=False)
    link, _code = connectors.issue(tmp_path, archives=tuple(ids))

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        first = call(client, link, "archive_overview", {"archive": ids[0]})
        second = call(client, link, "archive_overview", {"archive": ids[1]})
        neither = call(client, link, "archive_overview", {})

    assert answered(first)["archive_of"] == "Vasylyna Prokopchuk"
    assert answered(second)["archive_of"] == "Somebody Else"
    # And it still defaults to nobody, which is the server's half of one active patient.
    assert answered(neither)["which_archive"]


def test_a_link_for_one_person_needs_no_lock_at_all(tmp_path):
    """There is nobody to drift to, so the rule costs that case nothing — which is the common
    one: a link made for one patient."""
    ids = two_people(tmp_path, lock=False)
    link, _code = connectors.issue(tmp_path, archives=(ids[1],))

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        said = call(client, link, "archive_overview", {})

    assert answered(said)["archive_of"] == "Somebody Else"


def test_a_bound_pass_can_still_say_who_the_other_people_are(tmp_path):
    """Naming is not reading, and the choosing cannot happen without it.

    Found by the owner within an hour of the lock being turned on, in a real conversation. The
    server refuses a call that names no archive with "say which one — ask `archive_name` for each
    of the signatures and let the person choose", and `archive_name` then went through the same
    door as every reading tool: with the pass already bound to the first person asked about, it
    refused to give the names. The server was telling an assistant to ask a question it would not
    answer, and the person was offered a choice between three people it could not name.

    What this hands over is a name, of an archive this link already reaches, to a conversation
    that has already given a code. It reads nothing, and the pass stays bound to whoever it was
    bound to — the next reading call is checked exactly as before.
    """
    ids = two_people(tmp_path)
    link, code = connectors.issue(tmp_path, archives=tuple(ids))

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        given = answered(call(client, link, "unlock", {"code": mcp_lock.code_at(code, time.time())}))["pass"]
        read = call(client, link, "archive_overview", {"archive": ids[0], "ticket": given})
        named = answered(call(client, link, "archive_name", {"signature": ids[1], "ticket": given}))
        # And the pass is no looser for it: the other archive still cannot be read on it.
        after = call(client, link, "archive_overview", {"archive": ids[1], "ticket": given})

    assert answered(read)["archive_of"] == "Vasylyna Prokopchuk"
    assert named["archive_of"] == "Somebody Else", named
    assert "locked" in after and "one person&#x27;s records" in after or "one person's records" in after


def test_naming_an_archive_still_needs_the_lock_opened(tmp_path):
    """The exemption is from the pass's archive, not from the pass.

    A way in with the address and no code learns how many people are within reach and not who
    they are — that is deliberate and written beside `unlock`. Taking `archive_name` out of the
    binding must not take it out of the lock as well, which is the easy mistake to make here.
    """
    ids = two_people(tmp_path)
    link, _code = connectors.issue(tmp_path, archives=tuple(ids))

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        said = call(client, link, "archive_name", {"signature": ids[0]})

    assert "locked" in said
    assert "Vasylyna" not in said and "Somebody" not in said


def test_one_person_to_a_conversation_holds_under_both_settings(tmp_path):
    """The rule is not one of the things the lock's scope decides.

    `mcp_lock_scope = server` means a code opens the whole server for a while, which is a question
    about who may call at all. It was also switching off the binding of a pass to the person it
    has been reading — the early return for that setting stood above the check — so the owner who
    chose "easier to live with" silently chose "two people's records may meet in one
    conversation", while the server went on telling the model the opposite in its own
    instructions.

    Found by the security role on 7 Oct 2026, in a round that was told to report nothing but
    first-order findings.
    """
    ids = two_people(tmp_path)
    settings.set_mcp_lock_scope(tmp_path, "server")
    link, code = connectors.issue(tmp_path, archives=tuple(ids))

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        given = answered(call(client, link, "unlock", {"code": mcp_lock.code_at(code, time.time())}))["pass"]
        first = call(client, link, "archive_overview", {"archive": ids[0], "ticket": given})
        second = call(client, link, "archive_overview", {"archive": ids[1], "ticket": given})

    assert answered(first)["archive_of"] == "Vasylyna Prokopchuk"
    assert "one person&#x27;s records" in second or "one person's records" in second, second[:400]


def test_with_the_server_open_a_call_with_no_pass_is_still_let_through(tmp_path):
    """And the half of that setting which is deliberate is untouched: for the length of the
    window, a call carrying no pass at all is answered. There is no conversation there to hold a
    person on, and the settings page says in its own words what this choice gives up."""
    ids = two_people(tmp_path)
    settings.set_mcp_lock_scope(tmp_path, "server")
    link, code = connectors.issue(tmp_path, archives=tuple(ids))

    with TestClient(http_app(tmp_path), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        answered(call(client, link, "unlock", {"code": mcp_lock.code_at(code, time.time())}))
        without = call(client, link, "archive_overview", {"archive": ids[1]})

    assert answered(without)["archive_of"] == "Somebody Else"
