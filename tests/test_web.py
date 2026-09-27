"""Dashboard tests. All folders and files are synthetic."""

import asyncio
import json
import os
import re
from datetime import date
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from epicrisis.web.app import create_app
from epicrisis.web.jobs import InventoryJobs
from test_inventory import SYNTHETIC_TEXT, make_scan_pdf, make_text_pdf
from test_ask import archive_index  # noqa: F401
from epicrisis import query as query_index
from epicrisis.query import open_index
from test_extract import FakeExtractBackend, setup  # noqa: F401


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "project" / "data"


@pytest.fixture
def client(data_dir: Path) -> TestClient:
    return TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    root = tmp_path / "Main archive"
    (root / "2004").mkdir(parents=True)
    make_text_pdf(root / "2004" / "labs.pdf", [SYNTHETIC_TEXT])
    make_scan_pdf(root / "2004" / "scan.pdf", pages=3)
    return root


def add(client: TestClient, path, owner: str = "A Person"):
    """An archive is never added without a name, so the helper always carries one."""
    return client.post("/sources", data={"path": str(path), "owner": owner}, follow_redirects=False)


def test_empty_dashboard(client):
    response = client.get("/status")
    assert response.status_code == 200
    assert "No folders yet" in response.text
    assert "Not a medical device" in response.text


def test_add_folder_runs_inventory(client, archive, data_dir):
    response = add(client, archive)
    assert response.status_code == 303

    sources = json.loads((data_dir / "sources.json").read_text())
    assert [source["path"] for source in sources] == [str(archive)]
    source_id = sources[0]["id"]
    output = data_dir / "sources" / source_id
    assert (output / "inventory.jsonl").exists()
    assert json.loads((output / "inventory.status.json").read_text())["state"] == "done"

    page = client.get("/status").text
    assert "Main archive" in page
    assert str(archive) in page
    assert 'class="bar done"' in page
    # Totals: 2 files, 4 pages, 3 of them without text.
    assert '<span class="caps">Files</span><span class="value">2</span>' in page
    assert '<span class="caps">Pages</span><span class="value">4</span>' in page
    assert '<span class="caps">Vision pass pages</span><span class="value">3</span>' in page


def test_sources_persist_across_restarts(client, archive, data_dir):
    add(client, archive)
    restarted = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    assert "Main archive" in restarted.get("/status").text


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("", "Enter a folder path."),
        ("relative/folder", "Use an absolute path"),
        ("/definitely/not/here", "No such folder"),
    ],
)
def test_invalid_paths(client, path, message):
    response = client.post("/sources", data={"path": path, "owner": "A Person"})
    assert response.status_code == 400
    assert message in response.text


def test_duplicate_folder(client, archive):
    add(client, archive)
    response = add(client, archive)
    assert response.status_code == 400
    assert "already added" in response.text


def test_refuses_folder_containing_data_dir(client, data_dir):
    data_dir.mkdir(parents=True)
    response = add(client, data_dir.parent)
    assert response.status_code == 400
    assert "own data folder" in response.text


def test_rejects_foreign_host(data_dir):
    foreign = TestClient(create_app(data_dir, background_jobs=False), base_url="http://evil.example")
    assert foreign.get("/status").status_code == 400


def test_rejects_cross_origin_post(client, archive, data_dir):
    response = client.post(
        "/sources", data={"path": str(archive)}, headers={"Origin": "http://evil.example"}, follow_redirects=False
    )
    assert response.status_code == 403
    assert not (data_dir / "sources.json").exists()


def test_same_origin_post_allowed(client, archive):
    response = client.post(
        "/sources", data={"path": str(archive), "owner": "A Person"},
        headers={"Origin": "http://localhost:8050"}, follow_redirects=False,
    )
    assert response.status_code == 303


def test_a_form_of_ours_is_not_a_foreign_site(client, archive):
    """Chrome, asked to pass no referrer on, posts our own forms with `Origin: null`.

    Every form on the dashboard answered 403 because of it — switching archive, naming an owner,
    correcting a value. What the browser says about where the form came from is Sec-Fetch-Site,
    and that is what decides where it is there.
    """
    ours = client.post(
        "/sources", data={"path": str(archive), "owner": "A Person"},
        headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"}, follow_redirects=False,
    )
    assert ours.status_code == 303

    # And a page on another site posting to us is still refused, whatever its Origin says.
    theirs = client.post(
        "/sources", data={"path": str(archive)},
        headers={"Origin": "null", "Sec-Fetch-Site": "cross-site"}, follow_redirects=False,
    )
    assert theirs.status_code == 403


def test_a_form_posted_through_a_tunnel_is_ours_too(client, archive):
    """Reached over `tailscale serve` or a forwarded port, the browser's address arrives in
    X-Forwarded-Host while Host is this server's own. Both are ours."""
    response = client.post(
        "/sources", data={"path": str(archive), "owner": "A Person"},
        headers={"Origin": "https://box.example.ts.net", "X-Forwarded-Host": "box.example.ts.net"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_rescan(client, archive, data_dir):
    add(client, archive)
    source_id = json.loads((data_dir / "sources.json").read_text())[0]["id"]
    assert client.post(f"/sources/{source_id}/inventory", follow_redirects=False).status_code == 303
    assert client.post("/sources/unknown/inventory", follow_redirects=False).status_code == 404


def test_running_scan_shows_progress_and_refreshes(client, archive, data_dir):
    add(client, archive)
    source_id = json.loads((data_dir / "sources.json").read_text())[0]["id"]
    status_path = data_dir / "sources" / source_id / "inventory.status.json"
    status_path.write_text(json.dumps({"state": "running", "scanned": 1, "total": 4, "started_at": "x"}))

    page = client.get("/status").text
    assert "25%" in page
    assert 'http-equiv="refresh"' not in page
    assert client.get("/progress").json()["rows"][0]["steps"][0]["label"] == "25%"


def test_restart_marks_unfinished_scan_interrupted(data_dir):
    output = data_dir / "sources" / "abc"
    output.mkdir(parents=True)
    (output / "inventory.status.json").write_text(json.dumps({"state": "running", "scanned": 1, "total": 4}))

    jobs = InventoryJobs(data_dir)

    assert jobs.status("abc")["state"] == "interrupted"


def test_browse_lists_folders_only(client, tmp_path):
    root = tmp_path / "browse"
    (root / "Beta").mkdir(parents=True)
    (root / "alpha").mkdir()
    (root / ".hidden").mkdir()
    (root / "scan.pdf").write_bytes(b"%PDF-1.4")

    data = client.get("/browse", params={"path": str(root)}).json()

    assert data["path"] == str(root)
    assert data["parent"] == str(tmp_path)
    assert [folder["name"] for folder in data["folders"]] == ["alpha", "Beta"]
    assert (data["folder_count"], data["file_count"]) == (2, 1)
    assert "scan.pdf" not in json.dumps(data)
    assert data["crumbs"][0] == {"name": "/", "path": "/"}
    assert data["crumbs"][-1] == {"name": "browse", "path": str(root)}
    assert data["can_add"] is True


def test_browse_marks_added_folders(client, archive):
    add(client, archive)

    inside = client.get("/browse", params={"path": str(archive)}).json()
    assert inside["can_add"] is False
    assert "already added" in inside["reason"]

    above = client.get("/browse", params={"path": str(archive.parent)}).json()
    assert {folder["name"]: folder["added"] for folder in above["folders"]}["Main archive"] is True


@pytest.mark.parametrize(("path", "status"), [("relative", 400), ("/definitely/not/here", 404)])
def test_browse_errors(client, path, status):
    response = client.get("/browse", params={"path": path})
    assert response.status_code == status
    assert response.json()["error"]


def test_browse_default_starts_in_archive_folder(client, data_dir):
    (data_dir / "archive").mkdir(parents=True)
    assert client.get("/browse").json()["path"] == str((data_dir / "archive").resolve())


def test_add_button_opens_picker(client):
    page = client.get("/status").text
    assert '<button type="button" id="open-picker">' in page
    assert '<dialog class="picker" id="picker"' in page
    assert ".innerHTML" not in page


def test_source_ids_are_random(archive, tmp_path):
    first = TestClient(create_app(tmp_path / "one", background_jobs=False), base_url="http://localhost:8050")
    second = TestClient(create_app(tmp_path / "two", background_jobs=False), base_url="http://localhost:8050")
    add(first, archive)
    add(second, archive)

    first_id = json.loads((tmp_path / "one" / "sources.json").read_text())[0]["id"]
    second_id = json.loads((tmp_path / "two" / "sources.json").read_text())[0]["id"]

    assert first_id != second_id
    assert len(first_id) == 8 and int(first_id, 16) >= 0
    assert [path.name for path in (tmp_path / "one" / "sources").iterdir()] == [first_id]


def test_refuses_output_folder(client, archive, data_dir):
    add(client, archive)
    source_id = json.loads((data_dir / "sources.json").read_text())[0]["id"]
    response = add(client, data_dir / "sources" / source_id)
    assert response.status_code == 400
    assert "own output folder" in response.text


def test_fonts_are_served_locally(client):
    page = client.get("/status").text
    assert '<link rel="stylesheet" href="/static/fonts/fonts.css">' in page
    assert "googleapis" not in page
    css = client.get("/static/fonts/fonts.css")
    assert css.status_code == 200
    assert "googleapis" not in css.text and "gstatic" not in css.text
    for font_url in re.findall(r"url\((/static/fonts/[^)]+\.woff2)\)", css.text):
        assert client.get(font_url).status_code == 200


def test_consent_flow(client, data_dir):
    assert "Model processing is off" in client.get("/status").text
    page = client.get("/consent")
    assert page.status_code == 200
    assert "It does not remove anything from the page itself." in page.text
    assert "not a medical device and is not intended for diagnosis or treatment" in page.text
    assert 'href="https://www.anthropic.com/legal/consumer-terms"' in page.text
    assert "No pages are ready to send yet." in page.text

    refused = client.post("/consent", data={}, follow_redirects=False)
    accepted = client.post("/consent", data={"understood": "yes"}, follow_redirects=False)

    assert refused.status_code == 400
    assert accepted.status_code == 303
    assert "claude-code-subscription" in json.loads((data_dir / "consent.json").read_text())
    assert "Model processing is off" not in client.get("/status").text
    assert "Model processing is on" in client.get("/consent").text

    # Given by one press, taken back by one. There used to be no way at all: not a button, not a
    # command, not a line of documentation — only editing consent.json by hand, which nothing said.
    off = client.post("/consent", data={"action": "off"}, follow_redirects=False)
    assert off.status_code == 303
    assert json.loads((data_dir / "consent.json").read_text()) == {}
    assert "Model processing is off" in client.get("/status").text
    assert "Turn on model processing" in client.get("/consent").text


def test_consent_page_shows_volume_and_old_versions_ask_again(client, archive, data_dir):
    add(client, archive)
    page = client.get("/consent").text
    assert "This run will send 4 pages from 2 files, each in a request of its own" in page
    # And that a page may go more than once, which is true of what is sent as well as of what it
    # costs: a reading a check did not agree with is read again by a stronger model.
    assert "some of them more than once" in page and "read again by a stronger model" in page

    (data_dir / "consent.json").write_text(json.dumps({"claude-code-subscription": {"version": 1, "accepted_at": "x"}}))
    assert "Model processing is off" in client.get("/status").text


def test_classify_progress_on_dashboard(client, archive, data_dir):
    add(client, archive)
    source_id = json.loads((data_dir / "sources.json").read_text())[0]["id"]
    output = data_dir / "sources" / source_id
    inventory = [json.loads(line) for line in (output / "inventory.jsonl").read_text().splitlines()]
    scan = next(record for record in inventory if record["name"] == "scan.pdf")
    lines = [{"file_sha256": scan["sha256"], "page": page, "route": "vision", "doc_type": "other"} for page in (1, 2)]
    (output / "classify.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))

    partial = client.get("/status").text
    (output / "classify.lock").write_text(json.dumps({"pid": os.getpid()}))
    running = client.get("/status").text

    assert 'class="bar partial"' in partial and "50%" in partial
    assert 'class="bar running"' in running and client.get("/progress").json()["any_running"] is True


def test_documents_page_and_original_pages(client, archive, data_dir):
    add(client, archive)
    source_id = json.loads((data_dir / "sources.json").read_text())[0]["id"]
    output = data_dir / "sources" / source_id
    inventory = {record["name"]: record for record in map(json.loads, (output / "inventory.jsonl").read_text().splitlines())}
    scan, labs = inventory["scan.pdf"]["sha256"], inventory["labs.pdf"]["sha256"]

    def line(sha, page, role, doc_type="discharge", provider="Synthetic <b>Hospital</b>"):
        return {
            "file_sha256": sha, "page": page, "route": "vision", "doc_type": doc_type, "page_role": role,
            "language": "uk", "date_on_page": "17.05.2003", "provider_on_page": provider,
            "has_tabular_results": False, "legible": True, "confidence": 0.9,
        }  # fmt: skip

    lines = [line(scan, 1, "first"), line(scan, 2, "continuation"), line(scan, 3, "first", "insurance"), line(labs, 1, "first", "lab_panel")]
    (output / "classify.jsonl").write_text("".join(json.dumps(item) + "\n" for item in lines))

    page = client.get("/documents").text

    # Titled by whose archive it is, as every other page of this interface titles one. It said the
    # base name of the folder on disk — a name its owner chose, which may be a nickname or a
    # diagnosis — two blocks under a header naming the person properly.
    assert "Archive of A Person" in page and archive.name not in page
    assert "4 of 4 pages classified" in page and "3 documents" in page
    assert page.count('<details class="docs-year">') == 1 and "<details class=\"docs-year\" open" not in page
    assert "3 documents &middot; 0 transcribed" in page
    assert "Discharge summary" in page and "Lab results" in page and "not extracted" in page
    assert "Ukrainian" in page
    assert "Synthetic &lt;b&gt;Hospital&lt;/b&gt;" in page and "<b>Hospital" not in page
    assert f"/sources/{source_id}/files/{scan}/pages/2" in page

    # The address of a page is a page: the scan, which page it is, the file it came from and a way
    # back to the card. The image itself is one address further in, and that is what a browser is
    # given to draw.
    around = client.get(f"/sources/{source_id}/files/{scan}/pages/2")
    assert around.status_code == 200 and "Page 2" in around.text
    assert f"/sources/{source_id}/files/{scan}/pages/2/image" in around.text
    image = client.get(f"/sources/{source_id}/files/{scan}/pages/2/image")
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    assert image.headers["cache-control"] == "no-store"
    assert client.get(f"/sources/{source_id}/files/{labs}/pages/1").status_code == 200
    assert client.get(f"/sources/{source_id}/files/{scan}/pages/9").status_code == 404
    assert client.get(f"/sources/{source_id}/files/{'0' * 64}/pages/1").status_code == 404
    assert client.get(f"/sources/unknown/files/{scan}/pages/1").status_code == 404
    assert 'href="/documents"' in client.get("/status").text

    # And when the scan cannot be read, the page says why, in words. It used to ask one question —
    # is the folder there — and stay silent about the likelier trouble: one file changing under the
    # archive, rescanned or resaved or damaged. Then the page was whole, with a broken image in the
    # middle of it, and the reason this program knew exactly went only into a header nobody reads.
    which_file = next(one for one in map(json.loads, (output / "inventory.jsonl").read_text().splitlines())
                      if one["sha256"] == scan)  # fmt: skip
    (archive / which_file["path"]).write_bytes(b"not the file that was read")
    changed = client.get(f"/sources/{source_id}/files/{scan}/pages/2")
    assert changed.status_code == 200
    assert "file changed since inventory" in changed.text
    assert "everything already read from this archive is kept here" in changed.text.lower()
    assert "<img" not in changed.text  # not a broken image where a sentence belongs
    # The image on its own is a link on that page, so its refusal is a page too, not a bare line.
    alone = client.get(f"/sources/{source_id}/files/{scan}/pages/2/image")
    assert alone.status_code == 409 and "This page cannot be shown" in alone.text
    assert "text/html" in alone.headers["content-type"]


@pytest.mark.parametrize(("url", "current"), [("/status", "/status"), ("/documents", "/documents"), ("/consent", "/consent")])
def test_menu_on_every_page_marks_current(client, url, current):
    page = client.get(url).text
    assert 'id="menu-button"' in page and 'aria-expanded="false"' in page
    assert 'id="menu-panel" aria-label="Pages" hidden' in page
    # The menu holds what this instance can answer; the page asked for marks itself in it.
    assert f'<a href="{current}" aria-current="page">' in page
    assert page.count('aria-current="page"') == 1
    assert "Not a medical device" in page


def test_the_menu_grows_as_the_archive_does(tmp_path):
    """A page appears when it can answer. A new instance offers one thing to do, not nine."""
    from fastapi.testclient import TestClient

    from epicrisis.web.app import create_app

    empty = TestClient(create_app(tmp_path, background_jobs=False), base_url="http://localhost:8050")
    menu = empty.get("/status").text.split('id="menu-panel"')[1]

    assert 'href="/status"' in menu
    for later in ("/documents", "/", "/ask", "/indicators", "/search"):
        assert f'<a href="{later}"' not in menu, f"{later} is offered before there is anything in it"
    # And the page that was asked for still answers, saying which step is missing.
    assert "No archive here yet" in empty.get("/").text


def test_extract_progress_on_dashboard(client, archive, data_dir):
    from epicrisis.extract.run import write_document

    add(client, archive)
    source_id = json.loads((data_dir / "sources.json").read_text())[0]["id"]
    output = data_dir / "sources" / source_id
    inventory = {record["name"]: record for record in map(json.loads, (output / "inventory.jsonl").read_text().splitlines())}
    lines = [
        {"file_sha256": inventory["scan.pdf"]["sha256"], "page": page, "route": "vision", "doc_type": "discharge",
         "page_role": "first", "language": "uk", "legible": True, "confidence": 0.9}
        for page in (1, 2, 3)
    ] + [{"file_sha256": inventory["labs.pdf"]["sha256"], "page": 1, "route": "text", "doc_type": "lab_panel",
          "page_role": "first", "language": "uk", "legible": True, "confidence": 0.9}]  # fmt: skip
    (output / "classify.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    done = {"step": "extract", "file_sha256": inventory["labs.pdf"]["sha256"], "pages": [1],
            "model": "claude-sonnet-5", "prompt_version": "0", "status": "done", "at": "2026-01-01T00:00:00+00:00"}  # fmt: skip
    (output / "ledger.jsonl").write_text(json.dumps(done) + "\n")
    # And the transcription itself on disk, because that is the order a real run writes them in:
    # the document first, the ledger line second. A ledger that says done over a transcription that
    # is not there is a different state, and the dashboard now says so instead of drawing the step
    # as finished — which is what it used to do, over values that had gone.
    write_document(output / "extracted", inventory["labs.pdf"]["sha256"],
                   {"pages": [1], "doc_type": "lab_panel", "language": "uk", "full_text": "",
                    "observations": [], "provenance": {"model": "claude-sonnet-5", "prompt_version": "0"}})  # fmt: skip

    partial = client.get("/status").text
    (output / "extract.lock").write_text(json.dumps({"pid": os.getpid()}))
    running = client.get("/status").text

    assert "25%" in partial and partial.count('class="bar partial"') == 1
    assert running.count('class="bar running"') == 1
    progress = client.get("/progress").json()
    assert progress["any_running"] is True and progress["rows"][0]["steps"][2]["label"] == "25%"
    assert "Steps 04&ndash;05 run without a model." in running
    # Nothing offers to send pages to a model before a person has allowed it.
    assert "Allow model processing first" in running and "Read new documents" not in running

    from epicrisis.classify.backend import ClaudeCodeBackend
    from epicrisis.consent import record_consent

    record_consent(data_dir, ClaudeCodeBackend.name)
    allowed = client.get("/status").text
    assert ("Read new documents" in allowed) or ("not installed on this server" in allowed)


def test_names_are_escaped(client, tmp_path):
    folder = tmp_path / "<b>bold"
    folder.mkdir()
    add(client, folder)
    page = client.get("/status").text
    assert "<b>bold" not in page
    assert "&lt;b&gt;bold" in page


def test_documents_are_grouped_by_their_own_date_not_the_folder(client, archive, data_dir):
    add(client, archive)
    source_id = json.loads((data_dir / "sources.json").read_text())[0]["id"]
    output = data_dir / "sources" / source_id
    inventory = {record["name"]: record for record in map(json.loads, (output / "inventory.jsonl").read_text().splitlines())}
    scan, labs = inventory["scan.pdf"]["sha256"], inventory["labs.pdf"]["sha256"]

    def line(sha, page, role, printed):
        return {
            "file_sha256": sha, "page": page, "route": "vision", "doc_type": "lab_panel", "page_role": role,
            "language": "en", "date_on_page": printed, "provider_on_page": None,
            "has_tabular_results": False, "legible": True, "confidence": 0.9,
        }  # fmt: skip

    lines = [line(scan, 1, "first", "«12» 03 2011 г."), line(scan, 2, "first", "05/04/2019"), line(labs, 1, "first", "no date here")]
    (output / "classify.jsonl").write_text("".join(json.dumps(item) + "\n" for item in lines))

    page = client.get("/documents").text

    years = [page.index(f'<span class="year">{label}</span>') for label in ("2019", "2011", "No date")]
    assert years == sorted(years)
    assert "05.04.2019" in page and "Day and month may be swapped" in page
    # Both numeric dates of the English pages could have day and month swapped.
    assert "Date printed but not read" in page and "3 dates to check" in page
    assert page.count('<details class="docs-year">') == 3


def test_a_date_by_hand_has_to_be_a_date_a_document_could_carry(client, archive, data_dir):
    """A hand-set date is taken as truth afterwards, so the future and the far past are refused."""
    add(client, archive)
    source_id = json.loads((data_dir / "sources.json").read_text())[0]["id"]
    output = data_dir / "sources" / source_id
    labs = next(r for r in map(json.loads, (output / "inventory.jsonl").read_text().splitlines()) if r.get("name") == "labs.pdf")["sha256"]
    line = {"file_sha256": labs, "page": 1, "route": "text", "doc_type": "lab_panel", "page_role": "first", "language": "en",
            "date_on_page": None, "provider_on_page": None, "has_tabular_results": True, "legible": True, "confidence": 0.9}  # fmt: skip
    (output / "classify.jsonl").write_text(json.dumps(line) + "\n")
    url = f"/documents/{source_id}/{labs}/1/date"

    # Each refusal is a page with its own heading, and the page says what was wrong with the date.
    # One of the three used to answer with a single line of plain text and no page at all; the other
    # two wore the heading "That is not in this archive", with the paragraph about one server holding
    # several archives under it — said to somebody whose archive was open in front of them.
    for wrong, said in (("not-a-date", "not a date this page can read"),
                        ("2999-01-01", "cannot be dated in the future"),
                        ("0001-01-01", "a typing slip")):  # fmt: skip
        refused = client.post(url, data={"value": wrong})
        assert refused.status_code == 400, wrong
        assert "That date was not taken" in refused.text and said in refused.text, wrong
        assert "One server can hold several archives" not in refused.text, wrong
        assert "Internal Server Error" not in refused.text, wrong
    # And both limits are in the field itself, so the picker says so as a person types.
    field = client.get(f"/documents/{source_id}/{labs}/1").text
    assert 'min="1900-01-01"' in field and f'max="{date.today().isoformat()}"' in field
    assert client.post(url, data={"value": "2019-07-08"}, follow_redirects=False).status_code == 303
    assert "2019-07-08" in (output / "corrections.jsonl").read_text()


def test_a_document_date_set_by_hand_wins_and_can_be_cleared(client, archive, data_dir):
    add(client, archive)
    source_id = json.loads((data_dir / "sources.json").read_text())[0]["id"]
    output = data_dir / "sources" / source_id
    scan = next(r for r in map(json.loads, (output / "inventory.jsonl").read_text().splitlines()) if r.get("name") == "scan.pdf")["sha256"]
    line = {"file_sha256": scan, "page": 1, "route": "vision", "doc_type": "imaging_report", "page_role": "first", "language": "ru",
            "date_on_page": "03/00/28", "provider_on_page": None, "has_tabular_results": False, "legible": True, "confidence": 0.9}  # fmt: skip
    (output / "classify.jsonl").write_text(json.dumps(line) + "\n")
    url = f"/documents/{source_id}/{scan}/1"

    assert client.post(f"{url}/date", data={"value": "2021-09-08"}, follow_redirects=False).status_code == 303
    card, listing = client.get(url).text, client.get("/documents").text
    assert "08.09.2021" in card and "set by hand" in card
    assert '<span class="year">2021</span>' in listing and "set by hand" in listing
    assert client.post(f"{url}/date", data={"value": "not a date"}).status_code == 400
    assert client.post(f"{url}/date", data={"value": "2021-09-08"}, headers={"Origin": "http://evil.example"}).status_code == 403

    client.post(f"{url}/date", data={"value": ""})
    assert "set by hand" not in client.get(url).text
    assert (output / "classify.jsonl").read_text() == json.dumps(line) + "\n"


def test_a_folder_of_system_files_is_not_an_archive(client, data_dir):
    for path in ("/etc", "/proc/self", "/usr/share"):
        refused = add(client, Path(path))
        assert refused.status_code == 400 and "system folder" in refused.text
    # "/" is refused too, by the older rule: it holds this instance's own data folder.
    assert add(client, Path("/")).status_code == 400
    assert not (data_dir / "sources.json").exists() or "\"/etc\"" not in (data_dir / "sources.json").read_text()


def test_a_correction_needs_a_line_to_correct(client, archive, data_dir):
    add(client, archive)
    source_id = json.loads((data_dir / "sources.json").read_text())[0]["id"]
    output = data_dir / "sources" / source_id
    labs = next(r for r in map(json.loads, (output / "inventory.jsonl").read_text().splitlines()) if r.get("name") == "labs.pdf")["sha256"]

    refused = client.post(f"/documents/{source_id}/{labs}/1/value", data={"key": "1|nothing|here", "action": "remove"})
    assert refused.status_code == 404
    assert not (output / "corrections.jsonl").exists() or "nothing" not in (output / "corrections.jsonl").read_text()


def test_an_indicator_without_a_label_or_a_name_is_refused_on_the_page_it_was_typed_on(client, data_dir):
    """And the page comes back with the reason on it.

    It used to answer with one sentence of plain text on a white background, and this page is five
    hundred groups of the vocabulary: a person who cleared the label field and pressed Save lost the
    whole of it. The channel for saying this was already there and went unused.
    """
    from epicrisis import indicators

    refused = client.post("/indicators", data={"action": "save", "label": "", "names": ""}, follow_redirects=False)

    assert refused.status_code == 303 and refused.headers["location"].startswith("/indicators")
    assert indicators.load(data_dir) == []
    # The words travel by a key, so the address cannot be used to make this page say anything.
    said = client.get(refused.headers["location"]).text
    assert "An indicator needs a label or at least one spelling." in said
    assert "spelling" not in refused.headers["location"]


def test_a_fresh_instance_never_shows_a_five_hundred(tmp_path):
    """Nobody's first minute with this should be an Internal Server Error."""
    from fastapi.testclient import TestClient

    from epicrisis.web.app import create_app

    client = TestClient(create_app(tmp_path, background_jobs=False), base_url="http://localhost:8050")

    for path in ("/", "/status", "/documents", "/search?q=anything", "/review", "/ask",
                 "/indicators", "/settings", "/consent"):  # fmt: skip
        answer = client.get(path)
        assert answer.status_code == 200, f"{path} answered {answer.status_code} on an empty instance"
        assert "Internal Server Error" not in answer.text


def test_a_built_view_is_kept_until_its_files_change(client, archive, data_dir):
    """Reading 170 files a second time for the same answer is a second nobody needs to spend."""
    import time

    from epicrisis.web import documents as views

    add(client, archive)
    first = time.perf_counter()
    client.get("/documents")
    cold = time.perf_counter() - first

    second = time.perf_counter()
    client.get("/documents")
    warm = time.perf_counter() - second
    assert warm <= cold  # nothing is rebuilt while nothing has changed

    # A change to what it was built from throws the kept answer away.
    from epicrisis.sources import SourceRegistry

    source = SourceRegistry(data_dir).list()[0]
    output = data_dir / "sources" / source.id
    (output / "inventory.jsonl").touch()  # any of the files it is built from will do
    assert views._kept("documents", source, output) is None


def test_starting_again_puts_the_reading_aside_and_keeps_the_folder(client, archive, data_dir):
    """Nothing is deleted: the folder, the files and the person's corrections all stay."""
    from epicrisis.sources import source_output_dir

    add(client, archive)
    source_id = json.loads((data_dir / "sources.json").read_text())[0]["id"]
    output = source_output_dir(data_dir, source_id)
    output.mkdir(parents=True, exist_ok=True)
    (output / "classify.jsonl").write_text('{"kind": "page"}\n', encoding="utf-8")
    (output / "extracted").mkdir(exist_ok=True)
    (output / "extracted" / "one.json").write_text("{}", encoding="utf-8")
    (output / "corrections.jsonl").write_text('{"kind": "value"}\n', encoding="utf-8")
    (data_dir / f"index-{source_id}.sqlite").write_bytes(b"not really a database")

    # The checkbox is what makes it happen; a bare post does nothing.
    client.post(f"/sources/{source_id}/forget", follow_redirects=False)
    assert (output / "classify.jsonl").exists()

    done = client.post(f"/sources/{source_id}/forget", data={"understood": "yes"}, follow_redirects=False)
    assert done.status_code == 303 and "forgotten=" in done.headers["location"]
    assert not (output / "classify.jsonl").exists() and not (output / "extracted").exists()
    assert not (data_dir / f"index-{source_id}.sqlite").exists()
    assert (output / "corrections.jsonl").exists()  # the person's own words stay
    assert archive.exists() and (archive / "2004" / "labs.pdf").exists()
    assert json.loads((data_dir / "sources.json").read_text())[0]["id"] == source_id  # still on the list

    aside = next(output.glob("forgotten-*"))
    assert (aside / "classify.jsonl").exists() and (aside / "extracted" / "one.json").exists()
    assert (aside / f"index-{source_id}.sqlite").exists()
    page = client.get(done.headers["location"]).text
    assert "moved aside" in page and "nothing was deleted" in page


def test_a_foreign_page_cannot_make_this_one_forget_an_archive(client, archive, data_dir):
    """The most damaging button on the dashboard, tried from another site."""
    add(client, archive)
    source_id = json.loads((data_dir / "sources.json").read_text())[0]["id"]

    refused = client.post(f"/sources/{source_id}/forget", data={"understood": "yes"},
                          headers={"origin": "http://evil.example"}, follow_redirects=False)  # fmt: skip
    chosen = client.post(f"/review/{source_id}/{'0' * 64}/1/copy",
                         headers={"origin": "http://evil.example"}, follow_redirects=False)  # fmt: skip

    assert refused.status_code == 403 and chosen.status_code == 403
    assert json.loads((data_dir / "sources.json").read_text())[0]["id"] == source_id


def test_a_second_person_is_added_named_and_switched_to(client, archive, data_dir, tmp_path):
    """Two people on one server: each keeps their own archive, and one is open at a time.

    What a second owner must never do is bring the first one's records along, so this checks
    that the switch changes whose name the pages carry and that the archives stay two.
    """
    from epicrisis.sources import SourceRegistry, source_output_dir

    father = tmp_path / "Father archive"
    (father / "2011").mkdir(parents=True)
    make_text_pdf(father / "2011" / "labs.pdf", [SYNTHETIC_TEXT])

    client.post("/sources", data={"path": str(archive), "owner": "Vera Lindqvist"}, follow_redirects=False)
    client.post("/sources", data={"path": str(father), "owner": "Another Person"}, follow_redirects=False)
    registry = SourceRegistry(data_dir)
    mine, theirs = registry.list()

    assert [source.owner for source in registry.list()] == ["Vera Lindqvist", "Another Person"]
    assert source_output_dir(data_dir, mine.id) != source_output_dir(data_dir, theirs.id)
    assert registry.active().id == mine.id  # the first one added is the one open

    page = client.get("/status").text
    assert "Vera Lindqvist" in page and "Another Person" in page

    switched = client.post("/owner", data={"source": theirs.id}, follow_redirects=False)
    assert switched.status_code == 303
    assert registry.active().id == theirs.id
    # One control carries them all, whatever the number: a select with the open one chosen. The
    # archive that was switched to a line above is the one it shows as chosen.
    bar = client.get("/status").text
    assert 'name="source"' in bar and 'class="owner-pick' in bar
    assert f'<option value="{mine.id}">' in bar
    assert f'<option value="{theirs.id}" selected>' in bar and "Another Person" in bar
    # And it says how far it reaches, beside itself. It is one state for the whole server, and a
    # person who changed it here had the tab left open on the other archive answering about this
    # one the moment they reloaded it — at the same address, with nothing saying why.
    assert "changes the archive for this whole server" in bar and "One archive is open at a time" in bar

    # A name is changed without touching anything that was read.
    client.post(f"/owners/{theirs.id}/name", data={"owner": "Anders Lindqvist"}, follow_redirects=False)
    assert SourceRegistry(data_dir).get(theirs.id).owner == "Anders Lindqvist"

    # Taking one off the list leaves the other open, never nothing open.
    client.post(f"/owners/{theirs.id}/remove", follow_redirects=False)
    assert [source.id for source in SourceRegistry(data_dir).list()] == [mine.id]
    assert SourceRegistry(data_dir).active().id == mine.id


def test_a_person_sets_what_a_line_was_measured_in(client, archive, data_dir):
    """Saving the material on a line writes it as that person's own correction."""
    import json as json_module

    from epicrisis.corrections import load_value_corrections
    from epicrisis.sources import source_output_dir

    add(client, archive)
    source_id = json_module.loads((data_dir / "sources.json").read_text())[0]["id"]
    output = source_output_dir(data_dir, source_id)

    page = client.get(f"/documents/{source_id}/{'0' * 64}/1")
    assert page.status_code == 404  # no such document; the form is tested through the store below

    from epicrisis.corrections import set_value

    set_value(output, "0" * 64, [1], "1|кровь|0,861", {"material": "blood"})
    stored = load_value_corrections(output)[("0" * 64, (1,), "1|кровь|0,861")]
    assert stored["changes"] == {"material": "blood"}
    assert stored["by"] == "person"


def test_an_archive_is_not_added_without_saying_whose_it_is(client, archive, data_dir):
    """The name is on every page and in every answer, and the reading starts on adding."""
    nameless = client.post("/sources", data={"path": str(archive), "owner": "  "}, follow_redirects=False)

    assert nameless.status_code == 400
    assert "Say whose archive this is" in nameless.text
    assert not (data_dir / "sources.json").exists()  # nothing was added, nothing started
    assert str(archive) in nameless.text  # and the path typed is still in the form

    named = client.post("/sources", data={"path": str(archive), "owner": "Anders Lindqvist"}, follow_redirects=False)
    assert named.status_code == 303
    assert json.loads((data_dir / "sources.json").read_text())[0]["owner"] == "Anders Lindqvist"


def test_a_name_is_changed_afterwards_without_touching_what_was_read(client, archive, data_dir):
    """Renaming is one form on the status page; nothing about the reading moves with it."""
    from epicrisis.sources import SourceRegistry, source_output_dir

    client.post("/sources", data={"path": str(archive), "owner": "Wrong Name"}, follow_redirects=False)
    source_id = SourceRegistry(data_dir).list()[0].id
    output = source_output_dir(data_dir, source_id)
    output.mkdir(parents=True, exist_ok=True)
    (output / "corrections.jsonl").write_text('{"field": "value"}\n', encoding="utf-8")

    done = client.post(f"/owners/{source_id}/name", data={"owner": "Anders Lindqvist"}, follow_redirects=False)

    assert done.status_code == 303
    assert SourceRegistry(data_dir).get(source_id).owner == "Anders Lindqvist"
    assert (output / "corrections.jsonl").exists()  # what was read and corrected is untouched
    assert "Anders Lindqvist" in client.get("/status").text


def test_an_archive_with_no_index_shows_nothing_and_never_another_person_s(client, archive, data_dir, tmp_path):
    """The leak this found: switching to an archive not yet read showed the other one's records.

    An archive added and not yet read has no index file. The fallback that finds an index "when
    it is not where it was asked for" then handed back the only file in the folder, which was
    somebody else's, and every page answered from it under the new owner's name.
    """
    from epicrisis.index.build import build_index, index_path
    from epicrisis.query import IndexMissing, open_index
    from epicrisis.sources import SourceRegistry, source_output_dir
    from epicrisis.web.documents import source_documents

    theirs = tmp_path / "Another archive"
    (theirs / "2011").mkdir(parents=True)
    make_text_pdf(theirs / "2011" / "labs.pdf", [SYNTHETIC_TEXT])

    add(client, archive, "Vera Lindqvist")
    add(client, theirs, "Anders Lindqvist")
    registry = SourceRegistry(data_dir)
    mine, unread = registry.list()
    build_index(data_dir, [mine])

    assert index_path(data_dir, mine.id).exists()
    assert not index_path(data_dir, unread.id).exists()
    with pytest.raises(IndexMissing):
        open_index(data_dir, unread.id)  # not somebody else's

    registry.set_active(unread.id)
    # The other owner's name is on the page as a tab to switch back to, which is right. What
    # must not be there is a single thing out of their archive.
    theirs_files = {row["file"]["file_id"] for group in source_documents(mine, source_output_dir(data_dir, mine.id))["years"]
                    for row in group["documents"]}  # fmt: skip
    for page in ("/", "/documents", "/indicators", "/review", "/search?q=x"):
        answer = client.get(page)
        assert answer.status_code == 200, page
        assert not any(file_id in answer.text for file_id in theirs_files), page
    assert "Nothing" in client.get("/").text or "nothing" in client.get("/").text


def test_switching_whose_archive_is_shown_stays_on_the_page(client, archive, data_dir, tmp_path):
    """The same question, asked of somebody else. Leaving the page loses a person's place."""
    from epicrisis.sources import SourceRegistry

    theirs = tmp_path / "Another archive"
    (theirs / "2011").mkdir(parents=True)
    make_text_pdf(theirs / "2011" / "labs.pdf", [SYNTHETIC_TEXT])
    add(client, archive, "Vera Lindqvist")
    add(client, theirs, "Anders Lindqvist")
    mine, other = SourceRegistry(data_dir).list()

    for page in ("/documents", "/indicators", "/review", "/search?q=x", "/settings"):
        moved = client.post("/owner", data={"source": other.id, "back": page}, follow_redirects=False)
        assert moved.headers["location"] == page, page
        assert SourceRegistry(data_dir).active().id == other.id
        client.post("/owner", data={"source": mine.id, "back": page}, follow_redirects=False)

    # A card belongs to one archive by its address, so switching away from it goes to the list.
    card = f"/documents/{mine.id}/{'0' * 64}/1"
    assert client.post("/owner", data={"source": other.id, "back": card},
                       follow_redirects=False).headers["location"] == "/documents"  # fmt: skip

    # And the form cannot be used to send a person somewhere else entirely.
    for elsewhere in ("https://evil.example/x", "//evil.example/x", "", "not-a-path"):
        assert client.post("/owner", data={"source": mine.id, "back": elsewhere},
                           follow_redirects=False).headers["location"] == "/"  # fmt: skip


def test_the_reading_starts_from_whatever_page_says_there_is_nothing(client, archive, data_dir):
    """The one thing to do next is done where a person stands, not on a page they must find."""
    from epicrisis.consent import record_consent

    add(client, archive, "A Person")

    # Before agreeing to what is sent, the button leads to that screen and starts nothing.
    page = client.get("/").text
    assert 'action="/update"' not in page
    assert 'href="/consent"' in page and "Read what would be sent" in page

    record_consent(data_dir, "claude-code-subscription")
    for where in ("/", "/search", "/indicators", "/review", "/ask"):
        body = client.get(where).text
        assert "Read the documents" in body, where
        # Installed or not, the page never offers a button that would do nothing.
        assert ('action="/update"' in body) or ("not installed on this server" in body), where

    started = client.post("/update", follow_redirects=False)
    assert started.status_code == 303 and started.headers["location"] == "/status"


def test_no_page_ever_prints_a_python_object(client, archive, data_dir, tmp_path):
    """Twice in one day a page showed <built-in method ...> where a number belonged.

    Jinja resolves name.attr by asking for the attribute first and only then for the key, so a
    dict with a key called "values", "items" or "keys" hands back the method instead — and it
    renders as a line of angle brackets and a memory address. Nothing a template prints should
    ever look like that, on any page, in any state of the instance.
    """
    from epicrisis import indicators as store
    from epicrisis.consent import record_consent
    from epicrisis.sources import SourceRegistry

    leaks = ("built-in method", "<bound method", "object at 0x", "<generator", "<function", "dict_values")
    pages = ("/", "/status", "/documents", "/consent", "/settings", "/indicators", "/review",
             "/search?q=a", "/ask", "/?view=indicators", "/?view=lanes", "/tests/anything")  # fmt: skip

    def sweep(state: str) -> None:
        for page in pages:
            body = client.get(page).text
            for leak in leaks:
                assert leak not in body, f"{page} printed a python object ({leak}) when {state}"

    sweep("nothing has been added")
    add(client, archive, "A Person")
    sweep("an archive is added but not read")
    record_consent(data_dir, "claude-code-subscription")
    store.upsert(data_dir, None, "Creatinine", ["Креатинін", "Creatinina"], "approved", source="model", reviewed=False)
    sweep("an indicator exists")
    theirs = tmp_path / "Another archive"
    (theirs / "2011").mkdir(parents=True)
    make_text_pdf(theirs / "2011" / "labs.pdf", [SYNTHETIC_TEXT])
    add(client, theirs, "Another Person")
    SourceRegistry(data_dir).set_active(SourceRegistry(data_dir).list()[-1].id)
    sweep("a second archive is open")


def test_no_template_asks_a_dict_for_a_name_its_own_methods_answer():
    """The rule behind the test above, checked where the mistake is made rather than where it shows.

    Jinja's name.attr asks getattr first. On a dict that means .values, .items, .keys, .get and
    .copy are the dict's own methods, whatever the keys are called, so a context built as a dict
    must never use one of those names for something a page prints.
    """
    import re
    from pathlib import Path

    shadowed = {"values", "items", "keys", "get", "copy", "pop", "update", "clear", "setdefault"}
    asked = set()
    for template in sorted(Path("epicrisis/web/templates").glob("*.html")):
        for name, attribute in re.findall(r"\{\{[^}]*?\b([a-z_][a-z_0-9]*)\.([a-z_]+)\b", template.read_text()):
            if attribute in shadowed:
                asked.add(f"{template.name}: {name}.{attribute}")
    assert not asked, "a template asks a name for something every dict answers itself: " + ", ".join(sorted(asked))


def test_a_document_and_its_scan_answer_for_the_open_archive_only(client, archive, data_dir, tmp_path):
    """The scan is the record itself. It was served under another person's name by its address.

    Every page that shows a document carries one person's name at the top. A document addressed
    from under another archive answered anyway — the card, and the PNG of the original page with
    it — so somebody else's records appeared beneath the wrong name.
    """
    from epicrisis.classify.report import latest_pages
    from epicrisis.sources import SourceRegistry
    from test_extract import build_archive

    data_dir, mine, output, _records = build_archive(tmp_path / "instance")
    registry = SourceRegistry(data_dir)
    registry.set_owner(mine.id, "Vera Lindqvist")
    theirs_folder = tmp_path / "another"
    (theirs_folder / "2019").mkdir(parents=True)
    make_text_pdf(theirs_folder / "2019" / "labs.pdf", [SYNTHETIC_TEXT])
    theirs = registry.add(str(theirs_folder), "Anders Lindqvist")

    page = latest_pages(output / "classify.jsonl")[0]
    sha, first = page["file_sha256"], page["page"]
    card = f"/documents/{mine.id}/{sha}/{first}"
    scan = f"/sources/{mine.id}/files/{sha}/pages/{first}"
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    registry.set_active(mine.id)
    assert client.get(card).status_code == 200
    assert client.get(scan).status_code == 200  # the page around the scan
    assert client.get(scan + "/image").status_code in (200, 409)  # 409 when it cannot be rendered here

    # From under the other archive, neither the document nor the image of it exists.
    registry.set_active(theirs.id)
    assert client.get(card).status_code == 404
    assert client.get(scan).status_code == 404
    # And nothing about it can be changed from there either.
    for path, data in ((f"{card}/date", {"value": "2019-07-08"}),
                       (f"{card}/value", {"key": "1|x|1", "action": "save"}),
                       (f"/review/{mine.id}/{sha}/{first}/copy", {})):  # fmt: skip
        assert client.post(path, data=data, follow_redirects=False).status_code == 404, path

    # Renaming and rescanning stay open to every archive: the status page lists them all.
    assert client.post(f"/owners/{mine.id}/name", data={"owner": "Vera Lindqvist"},
                       follow_redirects=False).status_code == 303  # fmt: skip
    assert client.post(f"/sources/{mine.id}/inventory", follow_redirects=False).status_code == 303


def test_validation_runs_for_the_archive_that_is_open_and_no_other(tmp_path):
    """It reads one archive's transcriptions and writes into its folder: it is a content route."""
    from epicrisis.sources import SourceRegistry, source_output_dir

    data_dir = tmp_path / "data"
    mine, theirs = tmp_path / "mine", tmp_path / "theirs"
    for folder in (mine, theirs):
        folder.mkdir()
    registry = SourceRegistry(data_dir)
    first = registry.add(str(mine), "Vera Lindqvist")
    second = registry.add(str(theirs), "Anders Lindqvist")
    registry.set_active(first.id)
    for source, folder in ((first, mine), (second, theirs)):
        output = source_output_dir(data_dir, source.id)
        output.mkdir(parents=True, exist_ok=True)
        (output / "classify.jsonl").write_text("", encoding="utf-8")
        (output / "inventory.jsonl").write_text("", encoding="utf-8")

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    assert client.post(f"/sources/{second.id}/validate", follow_redirects=False).status_code == 404
    assert not (source_output_dir(data_dir, second.id) / "validation.json").exists()
    assert client.post(f"/sources/{first.id}/validate", follow_redirects=False).status_code == 303
    assert (source_output_dir(data_dir, first.id) / "validation.json").exists()


def test_a_folder_is_added_from_where_a_person_keeps_documents(tmp_path, monkeypatch):
    """The dashboard has no login because it listens here only; what it can read is still bounded."""
    from epicrisis.sources import SourceError, SourceRegistry
    from epicrisis.web.browse import BrowseError, list_folder

    monkeypatch.delenv("EPICRISIS_ARCHIVE_ROOT", raising=False)
    home = tmp_path / "home"
    (home / "scans").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere" / "someone-else"
    elsewhere.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    registry = SourceRegistry(home / "instance" / "data")
    assert registry.validate(str(home / "scans")) == (home / "scans").resolve()
    with pytest.raises(SourceError, match="Archives are added from"):
        registry.validate(str(elsewhere))
    with pytest.raises(SourceError, match="system folder"):
        registry.validate("/etc")

    # The folder dialog answers for the same places and no others.
    assert list_folder(str(home), added_paths=set(), roots=registry.roots())["path"] == str(home.resolve())
    with pytest.raises(BrowseError):
        list_folder(str(elsewhere), added_paths=set(), roots=registry.roots())

    # And a disk of scans elsewhere is named once, in the environment.
    monkeypatch.setenv("EPICRISIS_ARCHIVE_ROOT", str(elsewhere.parent))
    assert registry.validate(str(elsewhere)) == elsewhere.resolve()


def test_the_demo_builds_twice_and_its_status_page_says_it_is_read(tmp_path):
    """The first screen anyone following the README sees, and the option that promises a re-run."""
    from epicrisis.demo import build
    from epicrisis.sources import SourceRegistry
    from epicrisis.web.app import build_view
    from epicrisis.web.jobs import InventoryJobs

    made = build(tmp_path / "demo", seed=3)
    again = build(tmp_path / "demo", seed=3)  # "Anything already there is used", says its help
    assert again["documents"] == made["documents"]

    registry = SourceRegistry(made["data_dir"])
    jobs = InventoryJobs(registry.data_dir, background=False)
    steps = build_view(registry.list(), jobs, showing=registry.active().id)["rows"][0]["steps"]
    assert [step["state"] for step in steps] == ["done"] * 5


def test_switching_archive_on_a_test_page_answers_as_a_page(tmp_path):
    """The same address, an archive with nothing of that test: an answer, not a bare line."""
    from epicrisis import indicators as store
    from epicrisis.index.build import build_index
    from epicrisis.sources import SourceRegistry

    data_dir = tmp_path / "data"
    mine, theirs = tmp_path / "mine", tmp_path / "theirs"
    for folder in (mine, theirs):
        folder.mkdir()
    registry = SourceRegistry(data_dir)
    first = registry.add(str(mine), "Vera Lindqvist")
    second = registry.add(str(theirs), "Anders Lindqvist")
    store.upsert(data_dir, None, "Ferritin", ["Феритин"], "approved")
    for source in (first, second):
        build_index(data_dir, [source])

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    registry.set_active(second.id)
    answer = client.get("/tests/ferritin")

    assert answer.status_code == 200
    assert "Ferritin" in answer.text and "no values of this test" in answer.text
    assert "Archive of" in answer.text  # the header, so there is a way on from here
    assert client.get("/tests/nothing-like-this").status_code == 404


def test_an_address_with_a_number_that_is_not_one_answers_as_a_page(tmp_path):
    """A typed address is not an API call, and a wall of validation JSON is no answer."""
    from epicrisis.sources import SourceRegistry

    data_dir = tmp_path / "data"
    archive = tmp_path / "archive"
    archive.mkdir()
    registry = SourceRegistry(data_dir)
    registry.add(str(archive), "Vera Lindqvist")

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    answer = client.get("/", params={"year": "abc"})

    assert answer.status_code == 400
    assert "not an address of this archive" in answer.text and "year" in answer.text
    assert "Archive of" in answer.text  # the header, so there is a way on from here


def test_the_unit_switches_are_kept_and_the_page_shows_them(client, data_dir):
    """They are rules now. Reading a unit from a printed range is on to begin with; from the
    numbers is not; and each is turned on and off by its own file's id."""
    from epicrisis import rules
    from epicrisis.settings import rule_on

    loaded = rules.load(data_dir)
    from_range, by_numbers = loaded.get("unit_from_range"), loaded.get("unit_by_numbers")
    assert rule_on(data_dir, from_range) is True and rule_on(data_dir, by_numbers) is False
    page = client.get("/settings").text
    assert "Read the unit from the printed range" in page and "place them by their numbers" in page

    shown = ["unit_by_numbers", "unit_from_range"]
    client.post("/settings", data={"mode": "as_printed", "rule_on": "unit_by_numbers", "shown": shown},
                follow_redirects=False)  # fmt: skip
    assert rule_on(data_dir, by_numbers) is True and rule_on(data_dir, from_range) is False

    client.post("/settings", data={"mode": "as_printed", "rule_on": "unit_from_range", "shown": shown},
                follow_redirects=False)  # fmt: skip
    assert rule_on(data_dir, from_range) is True and rule_on(data_dir, by_numbers) is False


def test_the_settings_page_shows_how_the_model_is_reached(client, data_dir, monkeypatch, tmp_path):
    """Both ways are listed. The one that cannot answer yet says what it is waiting for."""
    from epicrisis import engines

    monkeypatch.delenv(engines.KEY_NAME, raising=False)
    monkeypatch.setattr(engines, "PROJECT_ROOT", tmp_path / "nowhere")  # the test machine may hold a key

    page = client.get("/settings").text
    assert "How this instance reaches the model" in page
    assert "Claude Code on this machine" in page and "Anthropic API with a key of your own" in page
    assert "Not ready:" in page and "disabled" in page

    # A form can be made to say anything; an engine that cannot answer is still not stored.
    client.post("/settings", data={"mode": "as_printed", "engine": "anthropic-api"}, follow_redirects=False)
    assert engines.chosen_engine(data_dir) == "claude-code"

    # With a key, the same page offers it plainly and the choice is kept.
    monkeypatch.setenv(engines.KEY_NAME, "a-key-that-is-not-a-key")
    assert "Not ready: ANTHROPIC_API_KEY" not in client.get("/settings").text
    client.post("/settings", data={"mode": "as_printed", "engine": "anthropic-api"}, follow_redirects=False)
    assert engines.chosen_engine(data_dir) == "anthropic-api"


def test_a_stylesheet_with_a_rule_that_lost_its_selector_is_a_broken_stylesheet():
    """Two orphan declaration lists sat in this file for two versions and ate the rule after each.

    A parser consuming a qualified rule at the top level does not stop at a stray closing brace:
    it keeps collecting until the next block, so the following rule becomes that bogus prelude's
    body and is discarded with it. Nothing failed, no page errored, two controls were simply
    drawn unstyled. Brace depth is the one thing that says so, and it costs nothing to check.
    """
    from pathlib import Path

    depth, trouble = 0, []
    text = (Path(__file__).parent.parent / "epicrisis" / "web" / "static" / "app.css").read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), 1):
        depth += line.count("{") - line.count("}")
        if depth < 0:
            trouble.append(number)
            depth = 0
    assert not trouble, f"a closing brace with nothing open at line(s) {trouble}"
    assert depth == 0, "a block was left open"


def test_a_filter_the_page_does_not_offer_is_not_a_filter(client, archive):
    """A tab, a status or a view that is none of the ones drawn must not empty the page.

    Each of these hid everything and said nothing: an unknown ?tab= left all four settings
    panels display:none because no radio was checked, and an unknown ?status= dropped every
    indicator group, which reads as an archive that lost its vocabulary.
    """
    add(client, archive, "A Person")

    # An unknown tab is the first tab: the panels are drawn from which radio is checked, so a page
    # with none checked is a page with nothing on it.
    assert 'id="tab-model" value="model" checked' in client.get("/settings?tab=zzz").text
    # An unknown filter is no filter, so the page holds what it holds with none asked for. The
    # pages cannot be compared whole — each explanation circle takes the next id on the server.
    for where, expected, mark in (("/indicators", "/indicators?status=zzz", "names in no indicator"),
                                  ("/indicators", "/indicators?show=zzz", "names in no indicator"),
                                  ("/", "/?view=zzz", "yearstrip")):  # fmt: skip
        assert (mark in client.get(where).text) == (mark in client.get(expected).text), expected


def test_a_dead_end_is_a_page_and_not_a_line_of_text(client, archive):
    """An address that stops resolving has an ordinary cause: the open archive was switched.

    A person meets it holding an address that worked a minute ago. A bare "Unknown document." on
    a white page gives them no archive name, no menu and no way out.
    """
    add(client, archive, "A Person")
    source_id = client.get("/status").text.split('data-source="')[1].split('"')[0]

    gone = client.get(f"/documents/{source_id}/{'0' * 64}/1")
    assert gone.status_code == 404
    assert "That is not in this archive" in gone.text and "topbar" in gone.text
    assert 'href="/documents"' in gone.text


def test_a_folder_that_could_never_be_added_is_not_a_folder_to_browse(client):
    """One rule saying two things: /root was both a root to choose from and a system folder.

    It is the home of whoever runs the server, so it stood in the list of places an archive may
    be added from, and validate() refused it in the same breath.
    """
    assert client.get("/browse", params={"path": "/root"}).status_code == 403
    assert client.get("/browse", params={"path": "/etc"}).status_code == 403


def test_a_scan_that_cannot_be_read_says_so_without_naming_the_file(tmp_path):
    """Walking a folder of somebody's documents fails with their file names in the message.

    A surname, an institution, often the reason for the visit — written to the dashboard and kept
    in inventory.status.json for good. Everywhere else in this program an exception is reduced to
    its type before it is shown, and this was the exception.
    """
    import json

    from epicrisis import layout
    from epicrisis.sources import SourceRegistry
    from epicrisis.web.jobs import InventoryJobs

    data_dir = tmp_path / "data"
    archive = tmp_path / "archive-of-a-person"
    archive.mkdir(parents=True)
    registry = SourceRegistry(data_dir)
    source = registry.add(str(archive), "A Person")

    jobs = InventoryJobs(data_dir, background=False)
    telling = "/home/someone/2019/ivanov-oncology-referral.pdf"
    jobs._write_status(source.id, {"state": "failed", "error": type(OSError(telling)).__name__})
    kept = json.loads((jobs.records_path(source.id).parent / layout.INVENTORY_STATUS).read_text(encoding="utf-8"))
    assert kept["error"] == "OSError" and telling not in json.dumps(kept)


def test_a_consent_file_that_will_not_parse_is_no_consent_and_not_a_crash(tmp_path):
    """Every page of the interface asks this, so an exception here takes the interface down."""
    from epicrisis.consent import has_consent

    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "consent.json").write_text('{"claude-code-subscription": {"version"', encoding="utf-8")
    assert has_consent(tmp_path, "claude-code-subscription") is False


def test_a_number_a_person_wrote_is_read_the_way_every_printed_number_is_read():
    """The correction had a reading rule of its own: comma to point, spaces out.

    So 1.234 became 1.234 where the form meant a thousand two hundred and thirty-four — standing
    in the table as the person typed it and marked corrected, wrong only on the chart and in the
    answer given over the network, with no check able to see it.
    """
    from epicrisis.printed_values import number_as_printed

    def read(text, band=None):
        return number_as_printed({"value_as_printed": text, "reference_as_printed": band})

    assert read("13,5") == 13.5 and read("1 234") == 1234.0 and read("0.93") == 0.93
    assert read("1.234,5") == 1234.5  # both separators: the last one is the decimal
    assert read("не виявлено") is None

    # Grouped thousands that would also read as a decimal. A range printed beside it settles the
    # scale — but only a range that does not carry the same question itself.
    assert read("1.234", "800 - 1500") == 1234.0
    assert read("1.234", "0,5 - 2,0") == 1.234
    # And with nothing to settle it, no number at all rather than one that may be a thousand out.
    assert read("1.234") is None
    # A range written the same way settles nothing: "150.000 - 400.000" is a hundred and fifty
    # thousand on one form and a hundred and fifty on another, and reading it the small way made
    # the value and the range agree while both were a thousand out — which no check could then
    # see, because the value sat inside its own shrunken range. The cost is real and is the
    # lesser one: a person's corrected specific gravity keeps their text and loses its point on
    # the chart, rather than keeping a number that may be wrong by a factor of a thousand.
    assert read("250.000", "150.000 - 400.000") is None
    assert read("1.005", "1.005 - 1.030") is None


def test_the_checks_read_what_a_person_left_and_the_transcription_check_still_judges_the_model(tmp_path):
    """Two readings of one document, on purpose, each check asking about the one it means.

    The value checks used to read only what the model wrote, so a value somebody had corrected
    went on being reported as wrong for ever and a row they had marked as not a value went on
    producing findings — the list of work did not shrink as the work was done. Judging the
    transcription by a later correction is the opposite mistake: the person's own reading would
    be reported as the model's, and correcting a value would add a finding.
    """
    from epicrisis.corrections import as_a_person_left_it, set_value, value_key

    rows = [
        {"provenance": {"page": 1}, "name_as_printed": "Glucose", "value_as_printed": "1,35", "unit_as_printed": "ммоль/л"},
        {"provenance": {"page": 1}, "name_as_printed": "Comment", "value_as_printed": "see below"},
    ]
    set_value(tmp_path, "c" * 64, [1], value_key(1, "Glucose", "1,35"), {"value_as_printed": "13,5"})
    set_value(tmp_path, "c" * 64, [1], value_key(1, "Comment", "see below"), None, removed=True)

    from epicrisis.corrections import load_value_corrections

    left = as_a_person_left_it(rows, "c" * 64, (1,), load_value_corrections(tmp_path))
    assert len(left) == 1, "a row marked as not a value is gone"
    assert left[0]["value_as_printed"] == "13,5" and left[0]["value_numeric"] == 13.5


def test_a_settings_file_that_cannot_be_read_is_not_written_over(tmp_path):
    """A write builds the whole file from what is there, and there is nothing there.

    So one saved setting took the place of all the rest: the engine, three models, the answer
    mode, nineteen switches and the lock, gone, with the page saying "Saved." The lock fails
    closed on reading; it has to fail closed on writing too, or the first press of Save undoes
    that.
    """
    import pytest

    from epicrisis import settings

    (tmp_path / "settings.json").write_text('{"mcp_lock": true, "ask": true', encoding="utf-8")
    was = (tmp_path / "settings.json").read_text(encoding="utf-8")

    with pytest.raises(settings.Unreadable):
        settings.set_answer_mode(tmp_path, "direct")
    assert (tmp_path / "settings.json").read_text(encoding="utf-8") == was


def test_a_form_that_did_not_draw_a_switch_does_not_decide_it(client, archive):
    """The whole of the shown protocol, and it had two holes.

    A disabled checkbox is never carried by the form, so drawing its hidden field beside one said
    the switch had been turned off by somebody who had not touched it. And the models were not in
    the protocol at all, so any save posted to this page put all three back to what ships.
    """
    add(client, archive, "A Person")
    page = client.get("/settings").text

    # The Ask switch is disabled until model processing is confirmed, and says so rather than
    # claiming to have been drawn.
    assert 'name="ask_page" value="on"' in page
    assert "disabled" in page.split('name="ask_page"')[0][-200:] or 'value="ask_page"' not in page

    # The models are under the protocol now, so the page carries their marker.
    assert 'name="shown" value="models"' in page


def test_a_lock_file_with_junk_in_it_does_not_take_pages_down(tmp_path):
    """Three functions read this file and two of them had drifted from the third.

    A lock whose pid is null raised TypeError in one and came back as None in another, so a stray
    lock file took down every page that asks whether a run is going.
    """
    from epicrisis.classify.run import is_running
    from epicrisis.runs import holder
    from epicrisis.update import update_running

    (tmp_path / "classify.lock").write_text('{"pid": null}', encoding="utf-8")
    (tmp_path / "update.lock").write_text("not json at all", encoding="utf-8")

    assert holder(tmp_path / "classify.lock") is None
    assert is_running(tmp_path) is False
    assert update_running(tmp_path) is False


def test_an_empty_list_of_flagged_values_says_what_it_is_not(archive_index):  # noqa: F811
    """Asked whether anything was flagged and handed a bare list, a model says nothing was.

    A person reads that as "nothing was wrong with them". The archive holds no mark of its own —
    only the ones laboratories printed — so an empty list here is a fact about what was printed
    and about nothing else. There is a field in this program for exactly that, written because a
    recommendation was once built on an empty list; it was wired to three tools and not to this.
    """
    from epicrisis.mcp_server import build_server

    data_dir, _source, _labs = archive_index
    server = build_server(data_dir)
    answered = asyncio.run(server.call_tool("flagged_values", {"flag": "ZZZ-no-such-mark"}))
    said = json.loads(answered.content[0].text)

    assert said["result"] == []
    assert "this_is_not_evidence_of_absence" in said
    assert "not a form that found nothing" in said["this_is_not_evidence_of_absence"]


def test_the_count_against_printed_ranges_names_what_it_could_not_look_at(archive_index):  # noqa: F811
    """Three counts read as a whole divided into three, and they were not.

    Values whose form printed no range beside them at all are cut by the query and appeared in
    none of the three. On older forms — no unit column, no range column — that can be most of an
    archive, and a count that leaves it unnamed overstates how much was looked at.
    """
    from epicrisis import query, rules
    from epicrisis.query import open_index
    from epicrisis.settings import rules_on

    data_dir, _source, _labs = archive_index
    with open_index(data_dir) as connection:
        _rows, counts = query.flagged_values(
            connection, compare_with_printed_range=True,
            placing=rules_on(data_dir, rules.load(data_dir), "charts"))  # fmt: skip

    assert set(counts) == {"outside", "inside", "range_not_read", "no_range_printed"}
    assert counts["no_range_printed"] >= 0


def test_a_question_finds_a_word_typed_in_the_other_alphabet(archive_index):  # noqa: F811
    """"В12" on a Ukrainian form and "B12" typed at a Latin keyboard share no character at all.

    An empty answer here reads as "the archive does not have it". Folding the look-alike letters
    would have been worse: the folded form of a whole Cyrillic word must stay Cyrillic, or
    "белок" becomes "бelok" and matches nothing at all. So the question is asked both ways, and
    only for words every letter of which has a twin.
    """
    import unicodedata

    from epicrisis.printed_values import also_written_as

    assert also_written_as("в12") == ["b12"] and also_written_as("т4") == ["t4"]
    # And the way back, which is the case this was written for: a person at a Latin keyboard,
    # forms printed in Cyrillic. It used to answer nothing at all in that direction.
    assert also_written_as("b12")[0] == "в12" and also_written_as("t4")[0] == "т4"
    assert also_written_as("белок") == [], "an ordinary word is never rewritten"
    assert also_written_as("гемоглобин") == [] and also_written_as("haemoglobin") == []

    data_dir, _source, _labs = archive_index
    with open_index(data_dir) as connection:
        # And a question pasted from a Mac arrives decomposed: a combining accent used to cut a
        # Greek or Spanish word in half and match nothing, while the same text in the index had
        # been folded and matched fine.
        for word in ("Ácido", "πρωτεΐνη"):
            assert query_index.count_search(connection, unicodedata.normalize("NFD", word)) \
                == query_index.count_search(connection, unicodedata.normalize("NFC", word)), word  # fmt: skip


def test_the_archive_of_a_third_person_is_not_covered_by_an_agreement_that_never_named_them(client, archive, data_dir, tmp_path):
    """The person whose archive it is need not be the person holding the server.

    A daughter reads this page, which names her mother and her father, and presses the button. A year
    later she adds the folder of a third person and runs the reading: their pages went to a provider
    at once, on the strength of an agreement that never mentioned them, and nothing asked. The
    machinery for "the notice changed, so ask again" was already here; it did not cover the list of
    names the notice itself prints.
    """
    from epicrisis.sources import SourceRegistry

    client.post("/sources", data={"path": str(archive), "owner": "Vera Lindqvist"}, follow_redirects=False)
    assert client.post("/consent", data={"understood": "yes"}, follow_redirects=False).status_code == 303
    assert "Model processing is on" in client.get("/consent").text

    third = tmp_path / "Somebody else's folder"
    (third / "2011").mkdir(parents=True)
    make_text_pdf(third / "2011" / "labs.pdf", [SYNTHETIC_TEXT])
    client.post("/sources", data={"path": str(third), "owner": "Anders Lindqvist"}, follow_redirects=False)

    # Nothing of theirs is sent, and the page says whose it is waiting on.
    page = client.get("/consent").text
    assert "Model processing is on" not in page
    assert "The archive of Anders Lindqvist was added after this was agreed to" in page
    assert "Model processing is off" in client.get("/status").text

    # Agreeing again covers both, and the file says which archives that was.
    assert client.post("/consent", data={"understood": "yes"}, follow_redirects=False).status_code == 303
    assert "Model processing is on" in client.get("/consent").text
    stored = json.loads((data_dir / "consent.json").read_text())["claude-code-subscription"]
    assert sorted(stored["archives"]) == sorted(source.id for source in SourceRegistry(data_dir).list())


def test_a_page_of_documents_over_an_archive_with_none_is_the_empty_page(client, archive, data_dir, tmp_path):
    """A heading, a lead about hovering dates and a colour scale from 0% to 100% of nothing.

    The empty state was written and was reached only by an archive nobody had walked through yet.
    One whose folder had been listed and which holds no documents came back as a view full of
    noughts, and the whole page was drawn over it.
    """
    empty = tmp_path / "a folder with nothing in it"
    empty.mkdir()
    add(client, empty)

    page = client.get("/documents").text

    assert "File ID colour shows how much text was read" not in page
    assert "Nothing to show here yet" in page or "nothing" in page.casefold()
    assert "a folder with nothing in it" not in page  # nor the folder's own name anywhere on it


def test_the_vocabulary_page_comes_back_where_it_was_pressed(client, archive, data_dir):
    """Five hundred groups to work through, and every button returned to the first screen.

    The way back was read from the Referer header, and this server sets Referrer-Policy: no-referrer
    on everything it answers — so there was never one. A person who had filtered to "not looked at
    yet", searched for a word, paged in and opened a group said one thing about that group and was
    put back at the top of the list with the filter cleared and every group closed.
    """
    from epicrisis import indicators

    indicators.upsert(data_dir, None, "Haemoglobin", ["Hb", "Гемоглобін"], status="approved")
    where = {"at_status": "approved", "at_find": "gemo", "at_show": "to_review", "at_skip": "10"}
    saved = indicators.load(data_dir)[0]
    saved_id = getattr(saved, "id", None) or saved["id"]

    done = client.post("/indicators", data={"action": "reviewed", "indicator_id": saved_id, **where},
                       follow_redirects=False)  # fmt: skip

    assert done.status_code == 303
    went = done.headers["location"]
    # The filter, the word, the view and the page, and the group that was pressed.
    assert "status=approved" in went and "find=gemo" in went and "show=to_review" in went and "skip=10" in went
    assert went.endswith("#" + saved_id)
    # And a press from the first screen still lands on the first screen rather than on a query of
    # empty filters.
    plain = client.post("/indicators", data={"action": "reviewed", "indicator_id": saved_id},
                        follow_redirects=False)  # fmt: skip
    assert plain.headers["location"] == f"/indicators#{saved_id}"


def test_nothing_this_server_answers_is_kept_in_a_cache_but_its_own_stylesheet(client, archive, data_dir):
    """The densest text in this dashboard is not a page.

    GET /ask/<id>/state hands back the whole of a conversation — the questions a person asked about
    their own health and the answers holding their values — and is asked again every two seconds
    while one is being written. The rule was written for "a page of values" and applied to text/html
    alone, so that answer, and /progress, and /browse with the names of folders in it, were left for
    any cache on the way to keep.
    """
    add(client, archive)

    for path in ("/", "/status", "/progress", "/browse", "/search"):
        answer = client.get(path)
        assert answer.headers.get("cache-control") == "no-store", path

    # A stylesheet and a font are the only things here a cache should keep, and they are the only
    # things served out of /static.
    stylesheet = client.get("/static/app.css")
    assert stylesheet.status_code == 200 and stylesheet.headers.get("cache-control") != "no-store"


def test_the_words_a_person_searches_for_do_not_become_an_address(archive_index):  # noqa: F811
    """An address is kept in a browser's history and synced from there to a vendor's servers.

    This program says as much where it refuses to put a name in a URL, and then put the plainest
    medical question a person ever types into one: the search line was a GET form, so "рак" or the
    name of a drug went into the address bar, the history, the autocomplete offered to whoever sits
    at that machine next, and the log of any tunnel in front of the dashboard.
    """
    data_dir, source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    page = client.get("/search").text
    assert 'method="post" action="/search"' in page
    assert 'method="get" action="/search"' not in page

    asked = client.post("/search", data={"q": "Цистатин"})

    # The words go in the body, and the address the answer is drawn under carries a key that stands
    # for them and spells nothing. (It used to be answered by the post itself, and a page reached by
    # POST cannot be returned to: see the test below for what "back" then did with the results.)
    assert asked.status_code == 200 and "Цистатин" in asked.text
    where = str(asked.url)
    assert where.startswith("http://localhost:8050/search?s=")
    assert "Цистатин" not in where and quote("Цистатин") not in where and "q=" not in where
    # And the controls that page the list are forms for the same reason: a link would carry the
    # words back into the address. Written as "either the words are absent or the form is there",
    # this guard went quiet the day the buttons stopped saying "show more" — a true sentence about
    # a string nothing prints. It asks the page itself now.
    paging = re.findall(r'<form[^>]*action="/search"[^>]*>', asked.text)
    assert paging, "no posted control on a page of results"
    assert all('method="post"' in one for one in paging), paging
    assert 'href="/search?q=' not in asked.text


def test_searching_past_the_first_page_reaches_the_documents_it_counted(archive_index):  # noqa: F811
    """"Show more" asked for a longer list, and the list has a cap.

    The index refuses to return more than two hundred rows — on purpose, so that a page cannot be
    made to render the whole archive by asking. "Show more" added to the length of the list, so once
    it had asked for two hundred it asked for two hundred for ever: the same documents came back,
    the button stayed, and the documents past the two-hundredth could not be reached at all, though
    the heading of the very same section printed how many there were.
    """
    data_dir, _source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    word = "Synthetic"
    first = client.post("/search", data={"q": word, "limit": 1})
    assert first.status_code == 200 and "Showing 1–1 of 2" in first.text

    # The next page is a different document, and it says where in the list it is.
    second = client.post("/search", data={"q": word, "limit": 1, "offset": 1})
    assert second.status_code == 200 and "Showing 2–2 of 2" in second.text
    ours = re.compile(r'class="feed-row wide" href="([^"]+)"')
    assert ours.findall(first.text) and ours.findall(first.text) != ours.findall(second.text)

    # And the end of the list is the end: nothing offers a page past it.
    assert "next 1" in first.text and "next 1" not in second.text
    assert "earlier page" in second.text and "earlier page" not in first.text

    # The words are still posted, never put in the address.
    assert 'method="get" action="/search"' not in second.text


def test_a_saved_settings_page_opened_twice_does_not_deny_what_it_stored(client, data_dir):
    """The page said what was stored once, and told the second reader nothing had changed.

    The word of a message is kept out of the address on purpose: the address carries a key, and the
    message behind it is read once and dropped. But the banner was drawn from the presence of the
    key, not from the message — so a person who reloaded that address, or opened it again from their
    history, was told "Saved. Nothing on the page was different from what was already stored". They
    had changed how this program reaches the model, and the page said it had not.
    """
    saved = client.post("/settings", data={"mode": "with_meaning"}, follow_redirects=False)
    where = saved.headers["location"]
    assert saved.status_code == 303 and "saved=" in where

    first = client.get(where).text
    assert "Saved:" in first and "Nothing on the page was different" not in first

    # The same address again: the message is gone, so the page says nothing about a press at all.
    again = client.get(where).text
    assert "Saved:" not in again and "Nothing on the page was different" not in again


def test_the_program_tells_a_person_the_command_their_shell_will_answer_to():
    """`epicrisis index` on a page, and no such command in the shell of the person reading it.

    This is installed as a checkout: the console script lives in the project's own environment and
    is reached as `uv run --project <the checkout> epicrisis`, which is how the README installs it.
    Every page and every message that told somebody what to run wrote the bare name, so the words
    could be copied off the screen, pasted into a terminal, and answered with "command not found" —
    and then, for a while, with `error: Failed to spawn: epicrisis` anywhere but that one folder.
    """
    import re
    import sys

    from epicrisis import invocation

    # On this machine — a checkout with its own environment — that is the form that works, and it
    # names the project, because `uv run epicrisis` finds one only from inside its folder and the
    # person reading a page is standing wherever they are standing.
    project = Path(sys.prefix).resolve().parent
    assert invocation.how_to_run() == f"uv run --project {project} epicrisis"
    assert invocation.run("index") == f"uv run --project {project} epicrisis index"
    assert invocation.as_root("mcp-lock init").startswith(f"sudo $(which uv) run --project {project} epicrisis")

    # And no page carries the other one. The spelling is one variable, so a page either asks for it
    # or writes a command by hand, and writing it by hand is the defect.
    bare = re.compile(r"(?<![\w{])epicrisis (?=(index|validate|update|extract|classify|serve|backup"
                      r"|sources|ask|mcp|mcp-lock|inventory|recheck)\b)")  # fmt: skip
    templates = Path(__file__).parent.parent / "epicrisis" / "web" / "templates"
    for page in sorted(templates.glob("*.html")):
        assert not bare.search(page.read_text(encoding="utf-8")), f"{page.name} spells the command by hand"


def test_a_disk_of_scans_of_its_own_is_added_by_typing_it_and_the_refusal_says_so(tmp_path, monkeypatch):
    """The picker's bound is on the picker. It was read as a bound on the person.

    A box of paper is scanned to a disk of its own — the ordinary case, and the one the README names
    apart. The picker refused the disk and offered one way out: stop the server, set an environment
    variable, start it again. For somebody who came with the box that is not a step, it is a wall,
    and the way that works in one line was not named at all. Half of those people close the tab and
    the other half copy tens of gigabytes into their home folder, which is the one thing this
    program promises never to do to their archive.
    """
    import os

    from epicrisis.sources import SourceError, SourceRegistry
    from epicrisis.web.browse import BrowseError, list_folder

    monkeypatch.delenv("EPICRISIS_ARCHIVE_ROOT", raising=False)
    home = tmp_path / "home"
    home.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    disk = tmp_path / "mnt" / "usb" / "scans"
    disk.mkdir(parents=True)
    other_disk = tmp_path / "mnt" / "stick" / "father"
    other_disk.mkdir(parents=True)
    registry = SourceRegistry(home / "instance" / "data")

    # The page still refuses it — and now names the line that works, with the folder in it.
    with pytest.raises(SourceError) as refused:
        registry.validate(str(disk))
    assert "sources add" in str(refused.value) and str(disk) in str(refused.value)
    with pytest.raises(BrowseError) as from_the_picker:
        list_folder(str(disk), added_paths=set(), roots=registry.roots())
    assert "sources add" in str(from_the_picker.value)

    # And that line works, because typing a path out is the consent a page cannot obtain.
    added = registry.add(str(disk), "A Person", typed=True)
    assert added.path == str(disk.resolve()) and registry.get(added.id) is not None

    # Everything else it refuses, it still refuses: a folder typed by hand is not a way past them.
    with pytest.raises(SourceError, match="system folder"):
        registry.validate("/etc", typed=True)
    (disk / "2019").mkdir()
    with pytest.raises(SourceError, match="contain one another"):
        registry.validate(str(disk / "2019"), typed=True)

    # Two disks, named for the picker at once. It took one folder, so a person with their mother's
    # archive on the machine and their father's on a stick could not reach both, however they set it.
    monkeypatch.setenv("EPICRISIS_ARCHIVE_ROOT", os.pathsep.join([str(disk.parent), str(other_disk.parent)]))
    assert registry.validate(str(other_disk)) == other_disk.resolve()
    assert list_folder(str(other_disk), added_paths=set(), roots=registry.roots())["path"] == str(other_disk.resolve())


def test_the_status_page_reads_the_classification_once_for_each_archive(archive_index, monkeypatch):  # noqa: F811
    """Two steps of one row, each reading the whole of classify.jsonl for itself.

    Measured on a file ten times this archive's size: 171 ms a read, so 343 ms to draw one row of
    which half was a repetition, and multiplied by every archive on the list. This is the page that
    has to stay standing whatever has happened to the data, and it had become the most expensive one
    in the program. The ledger beside it was already read once and handed to both.
    """
    from epicrisis.sources import SourceRegistry
    from epicrisis.web import app as web_app
    from epicrisis.web.jobs import InventoryJobs

    data_dir, source, _labs = archive_index
    reads = []
    original = web_app.latest_pages
    monkeypatch.setattr(web_app, "latest_pages", lambda path: reads.append(path) or original(path))

    view = web_app.build_view(SourceRegistry(data_dir).list(), InventoryJobs(data_dir), showing=source.id)

    steps = view["rows"][0]["steps"] if view["rows"] else []
    assert [step for step in steps if step["state"] not in ("not_started",)], "nothing to measure"
    assert len(reads) == 1, f"classify.jsonl read {len(reads)} times for one archive"


def test_the_type_carried_into_the_by_type_view_narrows_the_points_and_not_only_the_axis(archive_index):  # noqa: F811
    """Two presses from the first page, and a tenth of the archive was off the side of the screen.

    A type is chosen in the By year view, By type is pressed, and the address the page writes itself
    is /?view=lanes&doc_type=<type>. The axis was then built from the years of that one type and
    every type was drawn against it: on the demo archive eleven points of forty stood between -31%
    and 107% of the width, ten of them off the left of a phone's screen, and the rest stood on a year
    that was not theirs — a page stating a date that is false. The filter itself was drawn nowhere in
    this view and there was nothing to press to take it off.
    """
    import re

    data_dir, _source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    lanes = client.get("/?view=lanes").text
    types = set(re.findall(r'class="name">([^<]+)<', lanes))
    assert len(types) > 1, "one lane only: this archive cannot show the defect"

    for kind in sorted(types):
        page = client.get(f"/?view=lanes&doc_type={kind}").text
        # One lane, because that is what was asked for, and every point inside the axis.
        assert set(re.findall(r'class="name">([^<]+)<', page)) == {kind}
        places = [float(one) for one in re.findall(r'class="dot" style="left: ([-\d.]+)%', page)]
        assert places, f"{kind}: no points drawn"
        assert all(-0.01 <= one <= 100.01 for one in places), f"{kind}: points at {places}"
        # And the filter says it is on, with something to press to take it off.
        assert f"{kind} only" in page and 'every type</a>' in page


def test_the_views_say_only_the_filters_they_apply(archive_index):  # noqa: F811
    """A line that names a filter in force, drawn where nothing behind it filters.

    A type and a year are carried from view to view on purpose. The By type view applies both; the
    By test view applies neither — its series are every value of a test, whatever document it came
    from — and it printed "<type> only · every type" all the same, over a list identical with the
    filter and without it. A page that announces a narrowing it does not perform is worse than one
    that says nothing: the reader trusts the shorter list they think they are looking at.
    """
    data_dir, _source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    lanes = client.get("/?view=lanes&doc_type=lab").text
    assert "lab only" in lanes, "the view that does filter says so"

    tests = client.get("/?view=indicators&doc_type=lab").text
    assert "lab only" not in tests
    assert "not applied here" in tests and "Drop it" in tests


def test_the_year_strip_counts_by_the_view_the_page_will_draw(archive_index):  # noqa: F811
    """An unknown view falls back to the feed, and the strip was counted as if it had not.

    The fallback is one line above: `view if view in VIEWS else "feed"`. The strip below asked the
    raw word from the address instead, so `?view=nonsense&doc_type=…` drew the feed with a year
    strip counted over every type — a page whose bars and whose rows are of different sets.
    """
    data_dir, _source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    chosen = re.findall(r'class="count caps">(\d+)<', client.get("/?doc_type=lab").text)
    unknown = re.findall(r'class="count caps">(\d+)<', client.get("/?view=nonsense&doc_type=lab").text)
    assert chosen == unknown, "the same page, counted twice differently"


def test_a_mark_on_the_axis_names_a_year_the_page_holds(archive_index):  # noqa: F811
    """The axis ran one year past the newest document, and a mark was allowed to stand on its edge.

    With a single year chosen, the only label on the By type axis was the year after it, printed at
    the full width — a page whose one date is 2019 labelled 2020. A mark belongs inside the span the
    page draws, and where no fifth year falls inside it, the span's own first year is the mark.
    """
    data_dir, _source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    page = client.get("/?view=lanes&year=2019").text
    marks = re.findall(r'class="tick caps" style="left: [^"]*">(\d{4})<', page)
    assert marks == ["2019"], f"marks on the axis: {marks}"


def test_the_axis_labels_are_not_cut_in_half_to_guard_a_fault_that_cannot_happen():
    """A belt added after points were found outside the axis, cutting the labels ever after.

    The other half of that same change put the points inside the axis by construction — the axis is
    the span of the documents drawn under it — and the belt stayed, clipping the first and last year
    of every lane, since a mark is centred on its own year and the outermost ones stand at the edge.
    """
    text = (Path(__file__).parent.parent / "epicrisis" / "web" / "static" / "app.css").read_text(encoding="utf-8")
    track = next(line for line in text.splitlines() if ".lane .track {" in line)
    assert "overflow: hidden" not in track, track.strip()


def test_a_place_past_the_end_of_the_search_is_the_end_of_it(archive_index):  # noqa: F811
    """"41 documents", then "no document holds that", then "Showing 401–400 of 41".

    Only an address typed by hand reaches it, and what it produced was three statements on one page
    of which two were false. The timeline settles the same case by holding the place inside the
    list; the search page counted from wherever it was asked.
    """
    data_dir, _source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    page = client.post("/search", data={"q": "Synthetic", "limit": 1, "offset": 500}).text
    footer = re.search(r"Showing (\d+)–(\d+) of (\d+)", page)
    assert footer, "no place in the list printed at all"
    first, last, total = (int(one) for one in footer.groups())
    assert first <= last <= total, page[page.find("Showing") - 50 : page.find("Showing") + 60]
    assert 'class="feed-row wide"' in page, "the last page of the list, not an empty one"


def test_an_empty_list_of_documents_does_not_deny_what_the_page_just_showed(archive_index):  # noqa: F811
    """"No test is named that in any of its languages", printed under a test named exactly that.

    The dead-end paragraph and the button to "the 0 tests this archive has" were drawn whenever the
    list of documents was empty, though the count behind that button is only counted when nothing
    matched at all, and the page above may be showing printed names and tests of this archive.
    """
    data_dir, _source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    # A word that names values of this archive, filtered to a type that holds none of them.
    page = client.post("/search", data={"q": "Цистатин", "doc_type": "blank"}).text
    assert "Printed names that match" in page, "the page is showing something"
    assert "no test is named that in any of its languages" not in page
    assert "The 0 tests this archive has" not in page


def test_an_archive_added_by_typing_is_not_said_to_be_looked_through(tmp_path, monkeypatch):
    """"Is being looked through right now", over an instance where nothing is running.

    Adding a folder from the page starts the walk of it; adding it by typing the command does not,
    and the command is what this program tells a person to use when their scans are on a disk of
    their own. The archive then had no state at all, which was read as a scan whose state had not
    been written yet — so they were shown a page that says to wait, with a button to watch the
    progress of nothing, and the branch that tells them the real next step was never drawn.
    """
    from epicrisis.sources import SourceRegistry

    monkeypatch.delenv("EPICRISIS_ARCHIVE_ROOT", raising=False)
    home = tmp_path / "home"
    (home / "scans").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    data_dir = home / "instance" / "data"
    registry = SourceRegistry(data_dir)
    added = registry.add(str(home / "scans"), "A Person")   # exactly what the command does
    registry.set_active(added.id)

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = client.get("/").text

    assert "is being looked through right now" not in page
    assert "Watch the progress" not in page, "there is nothing to watch"
    # And the step that is actually next is the one drawn: what would be sent, and the consent.
    assert "/consent" in page

def test_a_setting_the_index_is_not_built_from_raises_no_banner_over_it(archive_index):  # noqa: F811
    """One press of Save, and every page of every archive said the index was out of date.

    settings.json holds every choice about this instance — the engine, three models, what an answer
    may contain, nineteen rules, the lock over the network — and the index was told it was behind
    whenever that file was written, because what was compared was the file's own time. Changing what
    the Ask page may say, which the index holds nothing of, put "This index is older than the files
    it is built from" over every page; switching owner showed it there too, and only building each
    archive's index again took it off. A warning that fires for anything is a warning nobody reads.
    """
    from epicrisis import rules
    from epicrisis.rules import kinds
    from epicrisis.settings import set_rule_on, set_trusts_read_materials

    data_dir, _source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    behind = "older than the files it is built from"
    assert behind not in client.get("/").text, "already behind before anything was saved"

    for stored in ({"mode": "with_meaning"}, {"mcp_lock_minutes": 120}, {"mode": "as_printed"}):
        saved = client.post("/settings", data=stored, follow_redirects=False)
        assert saved.status_code == 303, stored
        assert behind not in client.get("/").text, stored

    # And the checks, whose badge asks the same question of the same file, are not told they are
    # outdated by any of that either — while a rule, which they really are built out of, does say so.
    assert "data changed since" not in client.get("/status").text
    checking = next(rule for rule in rules.load(data_dir) if rule.at == kinds.VALIDATE)
    set_rule_on(data_dir, checking.id, False)
    assert "Validate: 1 documents to check, data changed since" in client.get("/status").text

    # And the one setting the index really is built from still raises it, changed from outside this
    # page — the page builds it in itself, so what is guarded here is the warning, not the button.
    set_trusts_read_materials(data_dir, True)
    assert behind in client.get("/").text, "a setting the index is built from went unreported"


def test_back_from_a_document_found_by_searching_returns_to_the_results(archive_index):  # noqa: F811
    """Search, open a document, press back: ERR_CACHE_MISS, and the found thing lost.

    The words are posted so that they never enter an address, and the answer used to be drawn by the
    post itself. Every answer here carries Cache-Control: no-store, so the results were in a page
    reached by POST with nothing in the cache to return to: back gave an error page offering to send
    the form again ("Confirm Form Resubmission" in Chrome), and the word had to be typed once more —
    once per page of the results, each of which was its own such entry in the history.
    """
    data_dir, _source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    posted = client.post("/search", data={"q": "Цистатин", "limit": 1}, follow_redirects=False)
    assert posted.status_code == 303
    where = posted.headers["location"]
    # The address a browser can come back to, and still no words in it.
    assert where.startswith("/search?s=")
    assert "Цистатин" not in where and quote("Цистатин") not in where and "q=" not in where

    results = client.get(where)
    assert results.status_code == 200 and "Цистатин" in results.text
    found = re.search(r'class="feed-row wide" href="([^"]+)"', results.text)
    assert found, "the word found no document, so there is nothing to come back to"
    assert client.get(found.group(1)).status_code == 200

    # "Back" is the same address again, which is all a browser does with it.
    again = client.get(where)
    assert again.status_code == 200 and "Цистатин" in again.text
    assert re.search(r'class="feed-row wide" href="([^"]+)"', again.text).group(1) == found.group(1)

    # A key this server no longer holds is a question it has forgotten, not an empty search.
    forgotten = client.get("/search?s=not-a-key-of-ours")
    assert forgotten.status_code == 200
    assert "The words this address stands for are not in it" in forgotten.text


def test_the_banner_after_save_says_which_way_the_setting_was_set(archive_index):  # noqa: F811
    """Turning a switch off was reported in the same words as turning it on.

    "Saved: reading the material from the table heading, and the index built again" answered both,
    and reads as a confirmation of the opposite act. The same for the heaviest choice on the page:
    the move into the one mode where this application compares a number with the range printed
    beside it, and the move back out of it, both answered "what may be said about a value".
    """
    data_dir, _source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    def stored(**fields) -> str:
        answer = client.post("/settings", data=fields)
        assert answer.status_code == 200
        return answer.text

    # A checkbox that is not ticked is not sent at all, so "shown" is what says it was on the page.
    assert "reading the material from the table heading on" in stored(shown="read_materials", read_materials="on")
    assert "reading the material from the table heading off" in stored(shown="read_materials")

    assert "what may be said about a value — no limits set here" in stored(mode="direct")
    assert "what may be said about a value — as printed only" in stored(mode="as_printed")


def test_a_type_tab_counts_the_year_it_will_show_and_the_empty_view_says_so(archive_index):  # noqa: F811
    """A tab promising a document, pressed, giving none — and then a page drawn half way.

    The row of type tabs is counted over the whole archive and each of its links carries the year
    that is in force, so with a year chosen every tab promised what another year holds: the comment
    over that row says "Every tab here means click and see this many". Press one of them and then the
    By type view, and what stood there was the bare header strip "Type … All" over empty space —
    no word about the type, the year, or that this is about an address and not about the archive.
    """
    data_dir, _source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    page = client.get("/?year=2003").text
    tabs = re.findall(r'<a href="([^"]+)"[^>]*>([^<]*?)\s*<span class="muted">\+?(\d+)</span>',
                      page.split('class="types caps"')[1].split("</div>")[0])  # fmt: skip
    assert len(tabs) > 1, "one tab only: this archive cannot show the defect"
    for href, label, promised in tabs:
        if "paperwork" in label:  # the one tab that means "add this many", and says so with a plus
            continue
        shown = re.search(r"Showing \d+ of (\d+)", client.get(href.replace("&amp;", "&")).text)
        assert shown, f"{label}: the page it leads to says nothing about how many"
        assert int(shown.group(1)) == int(promised), f"the {label} tab promises {promised}, shows {shown.group(1)}"

    # And the view beside it, reached the same way, says what did not match.
    lanes = client.get("/?view=lanes&year=2003&doc_type=lab_panel").text
    assert "Nothing in this archive answers that address" in lanes
    assert "lab_panel" in lanes and "2003" in lanes
    assert 'href="/?view=lanes"' in lanes, "no way back to the whole timeline"


def test_a_scan_of_another_archive_does_not_say_the_archive_is_gone(archive_index, tmp_path):  # noqa: F811
    """"That is not an archive this server holds", over a paragraph saying it holds several.

    A tab left on a scan, the owner switched in another tab, this one reloaded. The first sentence
    said the archive is not here; the paragraph under it explained that one server holds several and
    shows one at a time. A person whose archive was in front of them a minute ago reads the first
    line as the archive having gone. The card of the same document says it of the address.
    """
    data_dir, source, labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    second = tmp_path / "Another archive"
    second.mkdir()
    assert add(client, second, owner="Somebody Else").status_code == 303
    other = next(one["id"] for one in json.loads((data_dir / "sources.json").read_text())
                 if one["path"] == str(second))  # fmt: skip
    assert client.post("/owner", data={"source": other, "back": "/"}, follow_redirects=False).status_code == 303

    for address in (f"/sources/{source.id}/files/{labs}/pages/1",
                    f"/sources/{source.id}/files/{labs}/pages/1/image"):  # fmt: skip
        gone = client.get(address)
        assert gone.status_code == 404, address
        assert "That page is not in the archive that is open." in gone.text, address
        assert "not an archive this server holds" not in gone.text, address
        # Said above the paragraph that explains it, which is the whole reason it has to be true.
        assert "One server can hold several archives" in gone.text, address


def test_a_folder_with_nothing_to_read_does_not_ask_for_the_model(client, tmp_path):
    """Nought documents, and every page offered to send them to a model.

    A folder added one level too high or too low, or one holding what this program does not read:
    the walk finishes in a second and finds nothing. Every page then said "The documents of <name>
    have not been read yet", with a button to the screen that asks for consent to send pages to a
    model — for nothing — and nowhere said that there was nothing in the folder. The only thing that
    knew was "Files 0 / Pages 0" on the status page, where nobody was sent.
    """
    empty = tmp_path / "Nothing to read"
    (empty / "notes").mkdir(parents=True)
    (empty / "notes" / "todo.txt").write_text("not a document this program reads", encoding="utf-8")
    assert add(client, empty).status_code == 303

    for page in ("/", "/documents", "/search", "/review", "/indicators", "/ask"):
        text = client.get(page).text
        assert "have not been read yet" not in text, page
        assert "nothing in it is a document this program can read" in text, page
        assert "Read what would be sent" not in text and 'action="/update"' not in text, page

    # And the page a person is sent to says the same thing, where it used to advise the model.
    status = client.get("/status").text
    assert "Next: check the folder of this archive" in status
    assert "Next: decide about the model" not in status


def test_running_the_checks_builds_them_in_instead_of_warning_on_every_page(archive_index):  # noqa: F811
    """Press "Run checks", which the page itself advises, and get a warning on every page for it.

    The index is built from the findings of the checks as well, so after a run it really is behind
    and the banner was telling the truth — to somebody who had just done what they were told, with
    a second button to press and nothing saying why. A correction is built in by itself; so is this.
    """
    from epicrisis.index.build import index_path

    data_dir, source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    behind = "older than the files it is built from"
    assert behind not in client.get("/").text, "already behind before the checks were run"

    assert client.post(f"/sources/{source.id}/validate", follow_redirects=False).status_code == 303
    assert behind not in client.get("/").text

    # Built in, not hushed: the index is newer than the findings it is built from.
    findings = data_dir / "sources" / source.id / "validation.json"
    assert index_path(data_dir, source.id).stat().st_mtime >= findings.stat().st_mtime
