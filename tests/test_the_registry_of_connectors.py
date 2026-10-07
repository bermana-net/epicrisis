"""The registry of MCP links: what a line holds, what it refuses, and where a secret may not go.

The file and the module alone. What is done with them — which path answers, which archives a link
reaches, which day it stops — is tested where that is decided, in
`test_the_path_is_looked_up.py`, `test_the_editor_of_connectors.py` and
`test_a_link_has_a_last_day.py`.
"""

import json
from pathlib import Path

import pytest

from epicrisis import connectors, layout, mcp_lock
from epicrisis.state import Unreadable


def a_secrets_folder(tmp_path: Path) -> Path:
    """Where a test keeps the code secrets, which is never /etc/epicrisis/connectors."""
    return tmp_path / "secrets"


def test_a_line_holds_no_name_of_anybody_except_the_one_a_person_typed(tmp_path: Path):
    """Four random bytes, an address secret, archive ids and dates — and one typed field.

    The one typed field is the whole of why `tools/nothing-of-yours.py` has to be told about this
    file: everything else on the line carries no part of anybody's name by construction, and
    `name` carries whatever the owner meant it to.
    """
    made, _secret = connectors.issue(tmp_path, name="the urologist", archives=("aa11bb22",),
                                     secrets_folder=a_secrets_folder(tmp_path))  # fmt: skip

    stored = json.loads((tmp_path / layout.CONNECTORS).read_text(encoding="utf-8"))

    assert list(stored[0]) == ["id", "path", "name", "archives", "keeper", "issued_at",
                               "revoked_at", "until"]  # fmt: skip
    assert connectors.TYPED_BY_A_PERSON == ("name",)
    # The id is written into the journal and the access log, so the address must not be derivable
    # from it: a secret worked out from an id is a secret printed in two logs.
    assert made.path != made.id and made.id not in made.path
    assert len(made.id) == connectors.ID_BYTES * 2


def test_the_address_is_long_enough_to_be_an_address(tmp_path: Path):
    """`mcp_server.MIN_SECRET` refuses a served path shorter than this, and it is right to.

    Drawn by the one function that already draws it, so there is one place it is made and one
    place its length is decided.
    """
    from epicrisis import mcp_server

    made, _secret = connectors.issue(tmp_path, secrets_folder=a_secrets_folder(tmp_path))

    assert len(made.path) >= mcp_server.MIN_SECRET
    assert made.path.isascii(), "a path compared with compare_digest must be ASCII"


def test_the_code_secret_is_never_written_into_the_data_directory(tmp_path: Path):
    """The reason is `epicrisis backup`, and it is not tidiness.

    `layout.THEIR_OWN_WORK` is the list a backup carries off the machine. A file of credentials
    riding along in a copy somebody hands to their accountant is a different kind of leak from the
    ones the rest of this program is written against, and the only defence is that the file is not
    in there at all.
    """
    folder = a_secrets_folder(tmp_path)
    made, code_secret = connectors.issue(tmp_path, secrets_folder=folder)

    assert mcp_lock.read_secret(connectors.secret_file(made.id, folder)) == code_secret
    # Nothing under the data directory holds it, by any name.
    for file in tmp_path.rglob("*"):
        if file.is_file() and folder not in file.parents:
            assert code_secret not in file.read_text(encoding="utf-8", errors="replace"), file
    assert layout.CONNECTORS in layout.THEIR_CHOICES


def test_the_code_secret_cannot_be_fetched_a_second_time(tmp_path: Path):
    """It is returned once by `issue` and by nothing else, which is the whole discipline.

    `run_http` keeps no access log because the path carries a secret; a secret a function will
    hand over again is a secret in whatever asks. The page and the command therefore show it in
    the one answer that creates it, and losing it costs a revoke and a new link.
    """
    made, _secret = connectors.issue(tmp_path, secrets_folder=a_secrets_folder(tmp_path))

    read_back = connectors.get(tmp_path, made.id)

    assert read_back == made
    assert not any("secret" in field for field in vars(read_back)), vars(read_back)
    assert not hasattr(connectors, "code_secret_of"), "nothing here may hand the code secret back"


def test_a_revoked_link_may_open_nothing_and_says_when_it_stopped(tmp_path: Path):
    """Said in one place, because a caller that forgot would answer out of a withdrawn link.

    And the line stays: the journal and the access log name ids, so an id that names nothing makes
    the only record of what a link did unreadable.
    """

    class AnArchive:
        def __init__(self, id):
            self.id = id

    archives = [AnArchive("aa11bb22"), AnArchive("cc33dd44")]
    folder = a_secrets_folder(tmp_path)
    made, _secret = connectors.issue(tmp_path, archives=("aa11bb22",), secrets_folder=folder)
    assert len(connectors.the_archives_it_may_open(made, archives)) == 1

    gone = connectors.revoke(tmp_path, made.id, secrets_folder=folder)

    assert gone is not None and gone.revoked_at and not gone.live
    assert connectors.the_archives_it_may_open(gone, archives) == ()
    assert [one.id for one in connectors.load(tmp_path)] == [made.id], "the line stays on the list"
    assert not connectors.secret_file(made.id, folder).exists(), "the secret goes off the machine"


def test_an_archive_a_link_names_that_does_not_exist_opens_nothing(tmp_path: Path):
    """Which archives exist is `sources.json`'s answer, and this file is read against it.

    A second answerer to that question is the defect this project spends its weeks removing, so
    the permission is a claim read against the list and never a list of its own.
    """

    class AnArchive:
        def __init__(self, id):
            self.id = id

    made, _secret = connectors.issue(tmp_path, archives=("aa11bb22", "nosucharchive"),
                                     secrets_folder=a_secrets_folder(tmp_path))  # fmt: skip

    assert [one.id for one in connectors.the_archives_it_may_open(made, [AnArchive("aa11bb22")])] == ["aa11bb22"]


def test_a_file_that_will_not_read_shuts_the_archives_rather_than_opening_them(tmp_path: Path):
    """An empty list over a torn file would un-revoke every link somebody had taken back.

    That is the one direction this file must never move on its own, and it is why `load` raises
    where `people.load` and `keepers.load` raise: every writer here is load, change, save, so a
    reader that answers "there are none" has the next write put that emptiness back.
    """
    (tmp_path / layout.CONNECTORS).write_text("{ not json", encoding="utf-8")

    with pytest.raises(Unreadable) as refusal:
        connectors.load(tmp_path)

    assert "nothing has been opened" in str(refusal.value)
    assert "no code secret is in here" in str(refusal.value).lower()
    with pytest.raises(Unreadable):
        connectors.save(tmp_path, [])


def test_archives_written_by_hand_as_one_string_are_refused_and_not_read_as_letters(tmp_path: Path):
    """`"archives": "aa11bb22"` would otherwise be eight archives of one letter, opening nothing.

    Wrong in the dangerous direction: the link would quietly stop reaching the archive it was
    issued for, and nothing would say so.
    """
    (tmp_path / layout.CONNECTORS).write_text(
        json.dumps([{"id": "0011aabb", "path": "x" * 40, "archives": "aa11bb22"}]), encoding="utf-8")  # fmt: skip

    with pytest.raises(Unreadable):
        connectors.load(tmp_path)


def test_the_secrets_this_machine_already_has_are_carried_in_and_not_replaced(tmp_path: Path):
    """The link somebody is using goes on working, and their authenticator goes on being accepted.

    Carried in with **every** archive, because that is what the pair opens today. Narrowing it
    here would be this code deciding what somebody may see.
    """
    folder = a_secrets_folder(tmp_path)
    token = tmp_path / "mcp-token"
    totp = tmp_path / "mcp-totp"
    mcp_lock.write_secret("p" * 48, token)
    mcp_lock.write_secret(mcp_lock.new_secret(), totp)

    made = connectors.carry_the_one_secret_in(tmp_path, ("aa11bb22", "cc33dd44"), token_file=token,
                                              totp_file=totp, secrets_folder=folder)  # fmt: skip

    assert made is not None
    assert made.path == "p" * 48, "the address already in use is the address it keeps"
    assert made.archives == ("aa11bb22", "cc33dd44")
    assert mcp_lock.read_secret(connectors.secret_file(made.id, folder)) == mcp_lock.read_secret(totp)
    # Run twice it does nothing: the test is whether a connector already carries that path, which
    # is the fact itself rather than a flag written beside it.
    assert connectors.carry_the_one_secret_in(tmp_path, ("aa11bb22",), token_file=token,
                                              totp_file=totp, secrets_folder=folder) is None  # fmt: skip
    assert len(connectors.load(tmp_path)) == 1


def test_half_a_credential_carries_nothing_in(tmp_path: Path):
    """A path secret with no code secret beside it is not a link, and is not written as one.

    Issued with half, it would look live on the page and refuse every code, with nothing to say
    why — so there is nothing to carry and nothing is written.
    """
    token = tmp_path / "mcp-token"
    mcp_lock.write_secret("p" * 48, token)

    carried = connectors.carry_the_one_secret_in(tmp_path, ("aa11bb22",), token_file=token,
                                                 totp_file=tmp_path / "not-there",
                                                 secrets_folder=a_secrets_folder(tmp_path))  # fmt: skip

    assert carried is None
    assert not (tmp_path / layout.CONNECTORS).exists()


def test_the_ticks_on_the_page_are_the_answer_entire(tmp_path: Path):
    """`set_archives` takes the whole set, because the page draws every archive with a tick.

    An add would make a tick that failed to arrive look like a tick nobody changed.
    """
    folder = a_secrets_folder(tmp_path)
    made, _secret = connectors.issue(tmp_path, archives=("aa11bb22", "cc33dd44"), secrets_folder=folder)

    changed = connectors.set_archives(tmp_path, made.id, ("cc33dd44",))

    assert changed is not None and changed.archives == ("cc33dd44",)
    assert connectors.get(tmp_path, made.id).archives == ("cc33dd44",)
    assert connectors.rename(tmp_path, made.id, " the father's doctor ").name == "the father's doctor"


def test_the_folder_of_secrets_is_not_one_anybody_may_list(tmp_path: Path):
    """0750 and not 0755, and the reason is the names rather than the contents.

    Each file in there is named after a link's id, and `mcp_lock.write_secret` already keeps the
    file itself shut. A folder anybody may enter is a folder anybody may list, and that list is
    every link this instance has issued — which is not a secret, and is not theirs either.
    """
    folder = a_secrets_folder(tmp_path)

    connectors.issue(tmp_path, secrets_folder=folder)

    assert folder.stat().st_mode & 0o777 == 0o750, oct(folder.stat().st_mode)
    # And the one answer to who may read a secret of this program lives beside the one function
    # that creates one, rather than in the command that happened to need it first.
    assert hasattr(mcp_lock, "let_the_server_read")


def test_an_id_is_drawn_against_the_folder_of_secrets_and_not_only_this_registry(tmp_path, monkeypatch):
    """Two instances on one machine share the folder of code secrets, and the ordinary path puts
    them there: the README walks a person through the demo first and their own archive second.

    An id was drawn against this instance's own list alone. One time in sixty-five thousand the
    second instance would draw an id the first one is using, write its code secret over the live
    one, and leave that link answering no code at all — with nothing on any page to say why.

    Measured rather than argued: the draw is made to collide by filling the folder, which is what
    a sixty-five-thousandth looks like when you cannot wait for it.
    """
    import itertools

    from epicrisis import connectors

    folder = tmp_path / "secrets"
    folder.mkdir()
    (folder / "aaaaaaaa").write_text("a live link's code secret\n", encoding="utf-8")

    # The id the draw would hand out first, then one nobody holds.
    handing_out = itertools.chain(["aaaaaaaa"], ["bbbbbbbb"])
    monkeypatch.setattr(connectors.secrets, "token_hex", lambda _n: next(handing_out))

    made = connectors._an_id_nobody_has(set(), folder)

    assert made == "bbbbbbbb", "it drew an id whose secret file is already on this machine"
    assert (folder / "aaaaaaaa").read_text(encoding="utf-8") == "a live link's code secret\n"


def test_the_log_naming_an_id_this_registry_does_not_hold_is_reported(tmp_path, monkeypatch):
    """The two files are written for each other, and nothing compared them.

    A revoked link keeps its line **so that** the journal and the record of calls go on naming
    something; the comment on `revoke` says exactly that. Nothing checked the other direction, so
    a registry edited by hand during its own building left calls pointing at ids that name
    nothing, and the only sign of it was a log with strangers in it.

    Read and never repaired. What to do about such a line is a person's business, and the only
    honest repair — when it was issued, when it stopped — comes out of the log and not out of this
    file.
    """
    from epicrisis import connectors, mcp_access

    monkeypatch.setattr(connectors, "SECRETS_FOLDER", tmp_path / "secrets")
    made, _code = connectors.issue(tmp_path, name="the one that stayed")
    for connector_id in (made.id, "0e20daa9", "1c8b9fd3"):
        mcp_access.record(tmp_path, {"from": "127.0.0.1", "connector": connector_id, "tool": "archive_overview"})

    assert connectors.ids_the_log_names_that_are_not_here(tmp_path) == {"0e20daa9", "1c8b9fd3"}

    # And a link taken back the way the program takes one back is not a stranger: its line stays.
    connectors.revoke(tmp_path, made.id, secrets_folder=tmp_path / "secrets")
    assert connectors.ids_the_log_names_that_are_not_here(tmp_path) == {"0e20daa9", "1c8b9fd3"}
