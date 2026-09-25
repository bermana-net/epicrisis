"""Dashboard tests. All folders and files are synthetic."""

import json
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from epicrisis.web.app import create_app
from epicrisis.web.jobs import InventoryJobs
from test_inventory import SYNTHETIC_TEXT, make_scan_pdf, make_text_pdf


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


def test_consent_page_shows_volume_and_old_versions_ask_again(client, archive, data_dir):
    add(client, archive)
    assert "This run will send 4 pages from 2 files, one page per request." in client.get("/consent").text

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

    assert "4 of 4 pages classified" in page and "3 documents" in page
    assert page.count('<details class="docs-year">') == 1 and "<details class=\"docs-year\" open" not in page
    assert "3 documents &middot; 0 transcribed" in page
    assert "Discharge summary" in page and "Lab results" in page and "not extracted" in page
    assert "Ukrainian" in page
    assert "Synthetic &lt;b&gt;Hospital&lt;/b&gt;" in page and "<b>Hospital" not in page
    assert f"/sources/{source_id}/files/{scan}/pages/2" in page

    image = client.get(f"/sources/{source_id}/files/{scan}/pages/2")
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    assert image.headers["cache-control"] == "no-store"
    assert client.get(f"/sources/{source_id}/files/{labs}/pages/1").status_code == 200
    assert client.get(f"/sources/{source_id}/files/{scan}/pages/9").status_code == 404
    assert client.get(f"/sources/{source_id}/files/{'0' * 64}/pages/1").status_code == 404
    assert client.get(f"/sources/unknown/files/{scan}/pages/1").status_code == 404
    assert 'href="/documents"' in client.get("/status").text


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

    assert client.post(url, data={"value": "not-a-date"}).status_code == 400
    assert client.post(url, data={"value": "2999-01-01"}).status_code == 400
    assert client.post(url, data={"value": "0001-01-01"}).status_code == 400
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


def test_an_indicator_without_a_label_or_a_name_is_refused(client, data_dir):
    from epicrisis import indicators

    assert client.post("/indicators", data={"action": "save", "label": "", "names": ""}).status_code == 400
    assert indicators.load(data_dir) == []


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
    assert client.get(scan).status_code in (200, 409)  # 409 when the page cannot be rendered here

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
    """Reading a unit from the printed range is on to begin with; reading it from the numbers is not."""
    from epicrisis.ask import places_unit_by_numbers, reads_unit_from_range

    assert reads_unit_from_range(data_dir) is True and places_unit_by_numbers(data_dir) is False
    page = client.get("/settings").text
    assert "Read the unit from the printed range" in page and "place them by their numbers" in page

    client.post("/settings", data={"mode": "as_printed", "unit_by_numbers": "on"}, follow_redirects=False)
    assert places_unit_by_numbers(data_dir) is True and reads_unit_from_range(data_dir) is False

    client.post("/settings", data={"mode": "as_printed", "unit_from_range": "on"}, follow_redirects=False)
    assert reads_unit_from_range(data_dir) is True and places_unit_by_numbers(data_dir) is False
