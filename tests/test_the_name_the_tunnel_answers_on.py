"""The public name of an instance: one place that answers it, and what happens where nobody has.

Until this, `--public-host` lived on a command line alone and the instance did not know its own
address — so no page could write a link somebody else could use, and the editor of connectors had
nothing to compose one from.
"""

from pathlib import Path

import pytest

from epicrisis import connectors, settings


def test_a_whole_url_pasted_out_of_an_address_bar_is_refused_and_not_tidied(tmp_path: Path):
    """Every one of these is somebody pasting a different thing than was asked for.

    Tidied instead of refused, a link composed from it would be handed to another person as
    though it worked. The refusal says what to delete, which is the only thing anybody can act on.
    """
    for wrong in ("https://something.ts.net", "something.ts.net/mcp", "something.ts.net:8051",
                  "two names.ts.net", "nodots"):  # fmt: skip
        with pytest.raises(ValueError) as refusal:
            settings.set_the_name_the_tunnel_answers_on(tmp_path, wrong)
        assert "host name" in str(refusal.value), wrong
    assert settings.the_name_the_tunnel_answers_on(tmp_path) == ""


def test_the_name_is_kept_and_a_trailing_dot_is_not_a_different_name(tmp_path: Path):
    """A name copied out of a DNS tool arrives with the root dot on it, and it is the same name."""
    settings.set_the_name_the_tunnel_answers_on(tmp_path, "  something.ts.net.  ")

    assert settings.the_name_the_tunnel_answers_on(tmp_path) == "something.ts.net"

    settings.set_the_name_the_tunnel_answers_on(tmp_path, "")
    assert settings.the_name_the_tunnel_answers_on(tmp_path) == ""


def test_a_name_nobody_has_said_composes_no_link_at_all(tmp_path: Path):
    """Empty rather than `/mcp/<secret>`, which looks like an address and is not one.

    The one place a link is read is where somebody copies it to send to another person, so half
    an address is worse than none: it is a thing that looks finished.
    """
    made, _secret = connectors.issue(tmp_path, secrets_folder=tmp_path / "secrets")

    assert connectors.the_link_to(made, "") == ""
    assert connectors.the_link_to(made, "something.ts.net") == f"https://something.ts.net/mcp/{made.path}"


def test_a_revoked_link_has_no_address_either(tmp_path: Path):
    """Said in the one place that composes an address, not at each page that prints one."""
    folder = tmp_path / "secrets"
    made, _secret = connectors.issue(tmp_path, secrets_folder=folder)

    gone = connectors.revoke(tmp_path, made.id, secrets_folder=folder)

    assert connectors.the_link_to(gone, "something.ts.net") == ""


def test_the_journal_says_the_name_changed_and_not_what_it_became(tmp_path: Path):
    """The one setting deliberately left off `SAID_IN_FULL`, and the reason is the journal itself.

    It is not a secret — the secret is the path, and a tunnel answers on this name publicly. But
    the journal is the one file this project says may be shown to anybody, and an address somebody
    can knock on is not a thing to hand out for nothing. README.md keeps the same line: it writes
    the name as `<name.ts.net>` and this repository holds no real one.
    """
    from epicrisis import journal

    settings.set_the_name_the_tunnel_answers_on(tmp_path, "something.ts.net")

    written = (tmp_path / "journal.jsonl").read_text(encoding="utf-8")

    assert "public_host" in written, "a setting changing is a thing the program says out loud"
    assert "something.ts.net" not in written
    assert "public_host" not in settings.SAID_IN_FULL
    assert journal.FILE_NAME == "journal.jsonl"


def test_the_page_draws_the_field_and_says_what_it_is_for(tmp_path: Path):
    """And what it costs to leave empty, which is the half a person cannot work out alone."""
    from fastapi.testclient import TestClient

    from epicrisis.sources import SourceRegistry
    from epicrisis.web.app import create_app

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (tmp_path / "scans").mkdir()
    registry = SourceRegistry(data_dir)
    registry.set_active(registry.add(str(tmp_path / "scans"), owner="Somebody").id)
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    page = client.get("/settings").text

    assert 'name="public_host"' in page
    assert "does not know its own address" in page
    assert "no path, no port" in page


def test_saving_the_name_from_the_page_stores_it_and_says_so(tmp_path: Path):
    """And a press that pastes a URL is turned down in words, with the old answer still standing."""
    from fastapi.testclient import TestClient

    from epicrisis.sources import SourceRegistry
    from epicrisis.web.app import create_app

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (tmp_path / "scans").mkdir()
    registry = SourceRegistry(data_dir)
    registry.set_active(registry.add(str(tmp_path / "scans"), owner="Somebody").id)
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    good = client.post("/settings", data={"shown": "public_host", "public_host": "something.ts.net"},
                       follow_redirects=True)  # fmt: skip

    assert settings.the_name_the_tunnel_answers_on(data_dir) == "something.ts.net"
    assert "the name the tunnel answers on" in good.text

    bad = client.post("/settings", data={"shown": "public_host", "public_host": "https://other.ts.net"},
                      follow_redirects=True)  # fmt: skip

    assert settings.the_name_the_tunnel_answers_on(data_dir) == "something.ts.net", "the old answer stands"
    assert "was not stored" in bad.text

    # And the half-sent form: a press that never drew the field cannot clear what is stored. This
    # is the defect the checkboxes on this page already paid for once.
    half = client.post("/settings", data={"engine": ""}, follow_redirects=True)

    assert settings.the_name_the_tunnel_answers_on(data_dir) == "something.ts.net", "the old answer stands"
    assert "was not stored" in bad.text
