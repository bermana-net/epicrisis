"""Dashboard tests. All folders and files are synthetic."""

import asyncio
import json
import sqlite3
from contextlib import closing
from html.parser import HTMLParser
import os
import re
from datetime import date
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from epicrisis import doc_types
from epicrisis import indicators
from epicrisis.index.build import build_index, index_path
from epicrisis.web.app import create_app
from epicrisis.web.jobs import InventoryJobs
from conftest import A_DAY_FOR_AN_ILLUSTRATION
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
    assert data["crumbs"][0] == {"name": "/", "path": "/", "inside": False}
    assert data["crumbs"][-1] == {"name": "browse", "path": str(root), "inside": True}
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
    assert '<button type="button" class="browse" id="open-picker">' in page
    assert '<dialog class="picker" id="picker"' in page
    assert ".innerHTML" not in page


def test_browse_stays_at_the_end_of_the_path_line_on_a_phone():
    """Everything else in that bar takes a row of its own on a narrow screen; Browse does not.

    It is what fills the path field in, so it belongs to that line. A row of its own put it
    between the path and the name, where it read as a step between them.
    """
    import epicrisis.web.app as web

    style = Path(web.__file__).parent / "static" / "app.css"
    narrow = style.read_text().split("@media (max-width:")[1]

    assert "form.add #path { flex: 1 1 0; }" in narrow
    assert "form.add button.browse { flex: 0 0 auto;" in narrow


def test_choosing_a_folder_fills_the_path_in_and_adding_is_a_step_of_its_own(client):
    """Browse, then the name, then Add. Choosing a folder in the picker adds nothing by itself.

    It used to post the form from script the moment a folder was chosen. That skipped the name —
    a form submitted by script runs none of the browser's own checks — and took the decision
    away from the person at the one point where it is theirs.
    """
    page = client.get("/status").text

    assert ">Browse<" in page and ">Choose this folder<" in page
    assert '<button type="submit" id="add-source">' in page
    picking = page[page.index("choose.addEventListener") :]
    assert "form.submit()" not in picking  # the picker fills the path in; Add is what posts
    assert "picker.close()" in picking
    assert page.index('id="path"') < page.index('id="open-picker"') < page.index('id="owner"')


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
    """The number here is what a run would send, and it was what the archives hold.

    An instance where everything has been read said "This run will send 138 pages from 138 files"
    over a run that sends nothing at all — 0 calls, measured. This is the one number a person
    reads in the place where they decide whether their pages leave the machine.
    """
    add(client, archive)
    page = client.get("/consent").text
    assert "A run now would send <b>4 pages</b> from 2 files" in page
    assert "out of 4 pages in all" in page
    # And that a page goes more than once, which is true of what is sent as well as of what it
    # costs: once to say what kind of document it is, once to be read, and again by a stronger
    # model where a check did not agree with the reading.
    assert "at least twice over the whole reading" in page and "read again by a stronger model" in page

    # With every page classified and every document read, the page says so rather than offering
    # the archive's own size as the size of the next run.
    source_id = json.loads((data_dir / "sources.json").read_text())[0]["id"]
    output = data_dir / "sources" / source_id
    # Off the same page list the page itself counts, so the test cannot claim a page the
    # inventory does not hold.
    from epicrisis.classify.run import all_refs
    from epicrisis.records import read_records

    records = list(read_records(output / "inventory.jsonl"))
    classified = [{"file_sha256": ref.file_sha256, "page": ref.page, "route": ref.route,
                   "doc_type": "other", "page_role": "first"} for ref in all_refs(records)]  # fmt: skip
    (output / "classify.jsonl").write_text("".join(json.dumps(line) + "\n" for line in classified))

    # Classified but not read: what is left to send is the pages of the documents, not the whole
    # archive twice.
    half_way = client.get("/consent").text
    assert "A run now would send <b>4 pages</b>" in half_way

    # And read as well, by the ledger the extract step itself skips documents by.
    from epicrisis.classify.report import group_documents

    (output / "ledger.jsonl").write_text("".join(json.dumps({
        "step": "extract", "status": "done", "file_sha256": pages[0]["file_sha256"],
        "pages": [page["page"] for page in pages], "model": "m", "prompt_version": 1,
    }) + "\n" for pages in group_documents(classified)))  # fmt: skip

    nothing_waiting = client.get("/consent").text

    assert "Nothing is waiting" in nothing_waiting and "all 4 pages here have been read" in nothing_waiting
    assert "A run now would send" not in nothing_waiting

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


def test_a_page_that_is_text_shows_the_text_and_not_a_broken_image(client, archive, data_dir):
    """A document can arrive as plain text, and then there is no picture of it anywhere.

    The page of a value drew an <img> at an address that answers 409 for such a page — a broken
    image in the middle of the one page this program promises is always one click away from a
    number. The text the values were read from is what stands there instead.
    """
    lines = "Гемоглобин 134 г/л (130 - 160)\nЗаключение: отклонений не выявлено.\n"
    (archive / "2004" / "blood.txt").write_bytes(lines.encode("cp1251"))
    add(client, archive)
    source_id = json.loads((data_dir / "sources.json").read_text())[0]["id"]
    output = data_dir / "sources" / source_id
    inventory = {record["name"]: record for record in map(json.loads, (output / "inventory.jsonl").read_text().splitlines())}
    text_file = inventory["blood.txt"]

    assert text_file["category"] == "text" and text_file["text"]["pages"] == 1

    page = client.get(f"/sources/{source_id}/files/{text_file['sha256']}/pages/1")

    assert page.status_code == 200
    assert "Гемоглобин 134 г/л" in page.text  # read with the coding the inventory settled on
    assert "<img" not in page.text
    assert "the image on its own" not in page.text
    assert "the text as it stands in the file" in page.text


@pytest.mark.parametrize(("url", "current"), [("/status", "/status"), ("/documents", "/documents"), ("/consent", "/consent")])
def test_menu_on_every_page_marks_current(client, url, current):
    page = client.get(url).text
    assert 'id="menu-button"' in page and 'aria-expanded="false"' in page
    assert 'id="menu-panel" aria-label="Pages" hidden' in page
    # The menu holds what this instance can answer; the page asked for marks itself in it.
    assert f'<a href="{current}" aria-current="page">' in page
    assert page.count('aria-current="page"') == 1
    assert "Not a medical device" in page


VOID_ELEMENTS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
                           "meta", "source", "track", "wbr"})  # fmt: skip
# The one row of links in this interface that is not a row of tabs, named here because the sweep
# below cannot tell the two apart by looking. It is the row of document types over the feed: a
# line of counts that narrow the list under it, drawn as text with the chosen one in red and never
# as a box. Taking this name out is how somebody says it has become a row of tabs, and the sweep
# then holds it to the same rule as the rest.
NOT_A_ROW_OF_TABS = frozenset({"types"})


def css_rules(style: str) -> list[tuple[str, str]]:
    """Every rule of a stylesheet as (what it is over, what it sets), at-rules descended into.

    Written because the test below used to read that file a line at a time: in this stylesheet a
    rule's selectors and its declarations stand on separate lines, so `line.split("{")[1]` was the
    empty string, the set of properties made from it was empty, and the loop reached its assertion
    on none of the rules it was written to check. It passed over a fifth row of tabs added with a
    rule of its own, which is the one thing it was there to catch.
    """
    without_comments = re.sub(r"/\*.*?\*/", "", style, flags=re.DOTALL)
    rules, piled, depth, heading = [], "", 0, ""
    for piece in re.split(r"([{}])", without_comments):
        if piece == "{":
            depth += 1
            if depth == 1:
                heading = piled
            piled = ""
        elif piece == "}":
            depth -= 1
            if depth == 0 and not heading.strip().startswith("@"):
                rules.append((" ".join(heading.split()), " ".join(piled.split())))
            piled = ""
        else:
            piled += piece
    return rules


class RowsOfTabs(HTMLParser):
    """The rows of tabs in a served page, found by their shape rather than by their class.

    A row of tabs here is a row of captions with one of them the one you are standing on: two or
    more links or labels under one element, in the small uppercase this interface writes captions
    in, exactly one of them marked `aria-current` — or, where the switching is a hidden radio and
    not a page, every one of them a label for one. Found by shape and not by looking for a class
    this test already knows, because a class it already knows is a class a fifth row would not
    have.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.open = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if self.open:
            self.open[-1][2].append((tag, dict(attrs)))
        if tag not in VOID_ELEMENTS:
            self.open.append([tag, dict(attrs), []])

    def handle_startendtag(self, tag, attrs):
        if self.open:
            self.open[-1][2].append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        for depth in range(len(self.open) - 1, -1, -1):
            if self.open[depth][0] != tag:
                continue
            _tag, attributes, children = self.open.pop(depth)
            del self.open[depth:]
            classes = frozenset(attributes.get("class", "").split())
            if "caps" in classes and self._a_row_of_tabs(children):
                self.rows.append(classes)
            return

    @staticmethod
    def _a_row_of_tabs(children) -> bool:
        if len(children) < 2 or any(tag not in ("a", "label", "span") for tag, _ in children):
            return False
        standing_on = [tag for tag, attributes in children if "aria-current" in attributes]
        radios = [tag for tag, attributes in children if tag == "label" and attributes.get("for")]
        return len(standing_on) == 1 or len(radios) == len(children)


def rows_of_tabs(client: TestClient, standing_in: dict) -> dict[str, list[frozenset]]:
    """Every row of tabs on every page this program serves, by the address it was found on.

    The addresses come from the application, as in test_the_wall_between_people, so a page added
    next month is swept without anybody adding it to a list here. The three written out at the end
    are the other cuts of the timeline: one address, and a row of tabs drawn differently on each.
    """
    found = {}
    addresses = []
    for route in client.app.routes:
        path = getattr(route, "path", "")
        if "GET" not in getattr(route, "methods", set()) or path.startswith("/static"):
            continue
        for name, value in standing_in.items():
            path = path.replace("{" + name + "}", value)
        if "{" not in path:
            addresses.append(path)
    for address in (*addresses, "/?view=lanes", "/?view=indicators", "/?cut=doctor"):
        page = client.get(address, follow_redirects=True)
        parser = RowsOfTabs()
        parser.feed(page.text)
        if parser.rows:
            found[address] = [classes for classes in parser.rows if not classes & NOT_A_ROW_OF_TABS]
    return {address: rows for address, rows in found.items() if rows}


def test_every_row_of_tabs_in_this_interface_is_drawn_by_one_rule(archive_index):  # noqa: F811
    """For one afternoon this program had three different tab controls, and the owner found them.

    The settings had the oldest; a boxed one was invented for the page of doctors that morning and
    copied from there to the patient card before anybody saw the two side by side; the cuts of the
    timeline had a third. Three places to change, and changing one of them is how it happened. The
    owner asked for one thing: every row of tabs in this interface regulated in one place.

    So it is asked of the pages and of the stylesheet together, because either side alone can be
    told a lie. From the pages: every row of tabs this program serves carries a class that the one
    rule names, so a fifth row written with a rule of its own fails here. From the stylesheet: the
    look of a tab is declared in that rule and nowhere else, so copying those declarations under
    another selector fails too.

    What this replaces read the stylesheet a line at a time and reached its assertion on no line
    at all — see css_rules. The one live thing left in it was that an exact string of three
    declarations appeared twice, which any reformatting of the file broke and a fifth row of tabs
    did not.
    """
    data_dir, source, labs = archive_index
    style = (Path(__file__).resolve().parent.parent / "epicrisis" / "web" / "static" / "app.css").read_text(encoding="utf-8")
    rules = css_rules(style)
    assert len(rules) > 100, "the stylesheet did not parse into rules, so this test reads nothing"

    # The look of a tab: a caption along a rule, carrying a three-pixel underline that is
    # transparent until it is wanted, which is what makes a row of them read as tabs and the one
    # under you as the one you are on. The frame this replaced was the boxed control the owner
    # asked to have taken back out.
    draws_a_tab = [selectors for selectors, sets in rules
                   if "border-bottom: 3px solid transparent" in sets]  # fmt: skip
    assert len(draws_a_tab) == 1, f"a tab is drawn by {len(draws_a_tab)} rules and not one: {draws_a_tab}"
    # Which rows that rule reaches. Each of its selectors names a tab inside a row — "nav.tabs a",
    # ".settings-form .tabs label" — so the row is the step of the selector before the last one.
    reached = set()
    for selector in draws_a_tab[0].split(","):
        steps = selector.split()
        reached |= set(re.findall(r"\.([\w-]+)", steps[-2] if len(steps) > 1 else ""))
    assert reached, f"no row of tabs is named in {draws_a_tab[0]}"
    # The tab you are standing on carries the red underline, and that is said twice rather than
    # once: on the settings page the tab is a checked radio and not a page you are on, so it
    # cannot be named in the selector that says it for the rest. Twice, and over rows of the same
    # one rule — a third place saying it is a third tab control, whatever its selector is called.
    #
    # Counted among the rows this rule draws and not across the whole stylesheet, because the red
    # underline is how this interface marks a thing in several places that are not tabs at all.
    underlined = [selectors for selectors, sets in rules
                  if "border-bottom-color: var(--signal)" in sets
                  and set(re.findall(r"\.([\w-]+)", selectors)) & reached]  # fmt: skip
    assert len(underlined) == 2, (
        f"the tab you are on is underlined in {len(underlined)} places: {underlined}")

    # One test under a name, and one of its two values measured in another specimen, so that the
    # row of material tabs is drawn and swept with the rest: it is one of the four rows, and it is
    # the one an archive of a single specimen never shows. The second specimen is written into the
    # index rather than read off a form, because what is under test here is the row and not the
    # reading that fills it.
    indicators.upsert(data_dir, None, "Analyte 2", ["Analyte 2"], "approved")
    build_index(data_dir, [source])
    with closing(sqlite3.connect(index_path(data_dir, source.id))) as index:
        with index:
            index.execute("UPDATE observations SET material = 'urine' WHERE rowid = "
                          "(SELECT min(rowid) FROM observations WHERE name = 'Analyte 2')")  # fmt: skip

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050",
                        raise_server_exceptions=False)  # fmt: skip
    found = rows_of_tabs(client, {"source_id": source.id, "sha256": labs, "first_page": "1",
                                  "page": "1", "chat_id": "none", "indicator_id": "analyte-2"})  # fmt: skip
    rows = [(address, classes) for address, drawn in found.items() for classes in drawn]
    assert rows, "the sweep found no rows of tabs at all, so it is testing nothing"
    # And it found every row the rule names. Without this the sweep could go blind to one of them
    # — a row drawn only for an archive this fixture does not hold — and say nothing about it,
    # which is how the test this replaces came to say nothing about any of them.
    seen = set().union(*(classes for _address, classes in rows))
    assert reached <= seen, (
        f"the one rule draws {sorted(reached - seen)}, and the sweep never met a row of it: either "
        f"the row is gone from the pages or this fixture does not hold the archive that shows it"
    )

    # Every row under that one rule — the spacing above and below included, which is in the same
    # rule because it was not: the four rows had four gaps, 26 pixels, 4, 18 and 26, and on the
    # page of doctors the tabs sat so close under the heading that they read as part of it.
    for address, classes in rows:
        assert classes & reached, (
            f"a row of tabs on {address} carries {sorted(classes)}, and the one rule that draws a "
            f"tab reaches {sorted(reached)}: that row is drawn somewhere else"
        )


def test_the_pages_about_the_reading_stand_in_a_drawer_of_their_own(client, archive):
    """Eleven entries in one column ran off the bottom of the screen, and a menu you scroll is
    not a map any more. Four of them are not about the records: they are about the reading.

    Folded — except on the page a person is standing on. Arriving at "To check" and finding the
    menu claiming it is somewhere else is the interface telling them they are lost.
    """
    add(client, archive)
    page = client.get("/").text
    menu = page.split('id="menu-panel"')[1]
    top, drawer = menu.split('class="menu-more"')

    assert "Housekeeping" in drawer
    for about_the_reading in ("/documents", "/review", "/status", "/consent"):
        assert f'href="{about_the_reading}"' in drawer
        assert f'href="{about_the_reading}"' not in top, f"{about_the_reading} is still in the top of the menu"
    # What the program is for stays where it was, in one screenful.
    for its_own in ("/", "/search", "/ask", "/card", "/indicators", "/who", "/settings"):
        assert f'href="{its_own}"' in top
    assert "<details class=\"menu-more\">" in page  # shut

    standing_there = client.get("/review").text
    assert "<details class=\"menu-more\" open>" in standing_there
    assert standing_there.count('aria-current="page"') == 1


def test_the_page_of_names_is_named_for_what_it_holds(client, archive):
    """"Who made them" is a question, and a question in a menu has to be opened to be answered.

    It sits beside the indicators now, and is worded as what it is: the same act as grouping the
    printed names of one test, done for the people and the places instead.
    """
    add(client, archive)
    menu = client.get("/").text.split('id="menu-panel"')[1]

    assert "Doctors and clinics" in menu and "Who made them" not in menu
    assert menu.index("Indicators") < menu.index("Doctors and clinics")
    assert "Doctors and clinics" in client.get("/who").text


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
    # Named rather than numbered, 7 Oct 2026: there are five bars and three of them need no
    # model — Inventory as much as Validate and Index, which the page says of Inventory itself
    # two blocks further up. "04–05 of five" read as "only two of these are free".
    assert "Inventory, Validate and Index run without a model." in running
    # And the two steps that have no bar and do call a model are named, 7 Oct 2026: a person
    # reading five bars had no way to know that two more things were sending pages anywhere.
    assert "the search for a date where a document printed none" in running
    # Nothing offers to send pages to a model before a person has allowed it.
    assert "Allow model processing first" in running and "Read new documents" not in running

    from epicrisis.classify.backend import ClaudeCodeBackend
    from epicrisis.consent import record_consent

    record_consent(data_dir, ClaudeCodeBackend.name)
    allowed = client.get("/status").text
    assert ("Read new documents" in allowed) or ("not installed on this server" in allowed)


def test_the_button_that_deletes_nothing_says_so_where_it_stands(client, archive):
    """"Take off the list" sits beside "Start again" and reads as the harsher of the two.

    The only words saying it deletes nothing were in a title= on the button, which a phone and a
    keyboard never show — so on a phone the one button of that pair that is safe looked like the
    one that is not. The row below it has said what it does, in a line of its own, since it was
    written; this is the same thing in the same place.
    """
    add(client, archive)

    page = client.get("/status").text

    assert "Take off the list" in page
    assert "Nothing is deleted: the folder of scans, the transcriptions and your corrections" in page
    assert 'title="Takes this archive off the list' not in page


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


def test_the_day_as_the_form_printed_it_is_on_the_page_and_not_in_a_tooltip(client, archive, data_dir):
    """It lived in a title= on the date, under a lead reading "hover a date to see it as printed".

    A phone has no hovering and neither has a keyboard, and the readme offers this very page for
    showing a doctor from a phone — so on the screen it is read on, the date as printed was not
    on the page at all. The seventh entry of the constitution is about saying out loud what the
    program did, and reading "«12» 03 2011 г." as 12.03.2011 is something it did.
    """
    add(client, archive)
    source_id = json.loads((data_dir / "sources.json").read_text())[0]["id"]
    output = data_dir / "sources" / source_id
    inventory = {record["name"]: record for record in map(json.loads, (output / "inventory.jsonl").read_text().splitlines())}
    line = {"file_sha256": inventory["scan.pdf"]["sha256"], "page": 1, "route": "vision", "doc_type": "lab_panel",
            "page_role": "first", "language": "ru", "date_on_page": "«12» 03 2011 г.", "provider_on_page": None,
            "has_tabular_results": False, "legible": True, "confidence": 0.9}  # fmt: skip
    (output / "classify.jsonl").write_text(json.dumps(line) + "\n")

    page = client.get("/documents").text

    assert "12.03.2011" in page
    assert '<span class="mono muted date-printed">«12» 03 2011 г.</span>' in page
    assert "Hover a date" not in page  # and the lead names the line instead of a gesture
    assert "the day as the form itself printed it" in page
    # Not said twice where the form printed exactly what was read: that is noise on every row.
    assert 'title="As printed' not in page


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
    # The example the first of those three shows is a day off no form in any archive here, and the
    # same day the tests illustrate with — it used to be a day one of these forms prints as the
    # hour a sample was taken, published on a page with every release since the first.
    assert A_DAY_FOR_AN_ILLUSTRATION.isoformat() in client.post(url, data={"value": "not-a-date"}).text
    # And both limits are in the field itself, so the picker says so as a person types.
    field = client.get(f"/documents/{source_id}/{labs}/1").text
    assert 'min="1900-01-01"' in field and f'max="{date.today().isoformat()}"' in field
    assert client.post(url, data={"value": A_DAY_FOR_AN_ILLUSTRATION.isoformat()}, follow_redirects=False).status_code == 303
    assert A_DAY_FOR_AN_ILLUSTRATION.isoformat() in (output / "corrections.jsonl").read_text()


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


def test_the_pages_kept_are_of_the_archive_being_looked_at_and_of_no_other(client, archive, data_dir, tmp_path):
    """What is kept between requests had no bound of any kind, and now has one that can be stated.

    Not a leak, and it must not be read as one: the key is the archive's own output folder, so
    nothing of one archive was ever answered out of another's. What there was instead was nothing
    that would ever take an entry out again — one per view per archive, arriving as somebody
    clicked and staying for the life of `serve`. An instance that had drawn both of these pages of
    the three live archives held six of them: 1,554,435 bytes and 128,757 characters of text
    printed on the documents of three different people, because somebody once looked there.

    The dashboard shows one archive at a time and no page of it is about two, so the bound is the
    archive being looked at: two entries, whatever is clicked and however long the server runs.
    """
    from epicrisis.sources import SourceRegistry, source_output_dir
    from epicrisis.validate import validate_source
    from epicrisis.web import documents as views

    theirs = tmp_path / "Another archive"
    (theirs / "2011").mkdir(parents=True)
    make_text_pdf(theirs / "2011" / "labs.pdf", [SYNTHETIC_TEXT])
    add(client, archive, "Vera Lindqvist")
    add(client, theirs, "Anders Lindqvist")
    mine, others = SourceRegistry(data_dir).list()

    views._VIEWS.clear()
    for source in (mine, others):
        output = source_output_dir(data_dir, source.id)
        validate_source(output)  # so that the findings page has a view of its own to keep
        assert views.source_documents(source, output) is not None
        assert views.review_view(source, output) is not None

    assert {folder for _kind, folder in views._VIEWS} == {str(source_output_dir(data_dir, others.id))}
    assert len(views._VIEWS) == 2, "the two pages of one archive is the whole of what is kept"
    # And the archive nobody is looking at is gathered again when they go back to it, which is
    # what this costs: 0.05 s, 0.26 s and 0.63 s on the three live archives, once per switch.
    assert views._kept("documents", mine, source_output_dir(data_dir, mine.id)) is None


def test_two_archives_gathered_at_the_same_moment_never_hold_both(client, archive, data_dir, tmp_path):
    """The bound above holds when the two gathers are running at once, which is measured here.

    The sibling test switches one archive for another, a request at a time, and that is how the
    dashboard was used when the bound was written. Two at once is what the registry of connectors
    made thinkable, and though no MCP call reaches this cache — the path that answers a connector
    imports no module of `epicrisis.web` at all — two browser tabs on one machine reach it, and
    `serve` answers each request on a thread of its own.

    So the claim beside `_keep` is the one under test: the whole dictionary is built and put in
    place rather than emptied where it stands, each gather filtering to its **own** archive, so
    whatever order two of them finish in, what is published holds the views of one archive and
    never of two. A watcher samples the dictionary throughout and every sample is checked.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from epicrisis.records import read_records
    from epicrisis.sources import SourceRegistry, source_output_dir
    from epicrisis.validate import validate_source
    from epicrisis.web import documents as views

    theirs = tmp_path / "Another archive"
    (theirs / "2011").mkdir(parents=True)
    make_text_pdf(theirs / "2011" / "labs.pdf", [SYNTHETIC_TEXT])
    add(client, archive, "Vera Lindqvist")
    add(client, theirs, "Anders Lindqvist")
    both = SourceRegistry(data_dir).list()
    folders = {source.id: source_output_dir(data_dir, source.id) for source in both}
    for source in both:
        output = folders[source.id]
        # Each archive's own pages classified as documents, because a page of no documents is a
        # page whose file list is empty and two empty sets cross invisibly.
        (output / "classify.jsonl").write_text("".join(
            json.dumps({"file_sha256": record["sha256"], "page": page, "route": "text",
                        "doc_type": "lab_panel", "page_role": "first" if page == 1 else "continuation",
                        "language": "uk", "date_on_page": None, "provider_on_page": None,
                        "has_tabular_results": True, "legible": True, "confidence": 0.9}) + "\n"
            for record in read_records(output / "inventory.jsonl") if "sha256" in record
            for page in (1,)), encoding="utf-8")  # fmt: skip
        validate_source(output)

    # Both archives' files are given the same instant, which is what `demo` building three of them
    # at once leaves behind, and an import of two folders on one evening. Without it the only thing
    # keeping one archive's view out of the other's answer is that their files changed at different
    # times, and that is luck rather than design: with the folder taken out of `_kept`'s key, equal
    # instants make a crossed answer reachable, and the file sets below are what sees it.
    one_instant = 1_700_000_000.0
    for source in both:
        for file in folders[source.id].iterdir():
            if file.is_file():
                os.utime(file, (one_instant, one_instant))

    def files_in(view):
        # By the files listed and not by `whose`, which is read off `sources.json` and would be
        # right on a view gathered out of the wrong folder. These come out of the archive's own
        # inventory, so a crossed answer cannot have them.
        return {row["file"]["path"] for year in view["years"] for row in year["documents"]}

    # What each archive's page says when nothing else is running, to compare every answer from the
    # storm against. Gathered one at a time and on purpose: the comparison has to come from a
    # reading that cannot itself have crossed.
    views._VIEWS.clear()
    alone = {source.id: files_in(views.source_documents(source, folders[source.id])) for source in both}
    assert all(alone.values()), "neither page listed a file; the two sets below would prove nothing"
    assert not alone[both[0].id] & alone[both[1].id], "the two archives share a file; pick another shape"

    views._VIEWS.clear()
    seen: list[set[str]] = []
    done = threading.Event()

    def watch():
        while not done.is_set():
            seen.append({folder for _kind, folder in dict(views._VIEWS)})

    def gather(source):
        output = folders[source.id]
        assert files_in(views.source_documents(source, output)) == alone[source.id]
        assert views.review_view(source, output) is not None
        return source.id

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            asked = [both[turn % 2] for turn in range(24)]
            assert sorted(pool.map(gather, asked)) == sorted(source.id for source in asked)
    finally:
        done.set()
        watcher.join(timeout=5)

    assert len(seen) > 1, f"the watcher took {len(seen)} samples; it was not watching"
    crossed = [sample for sample in seen if len(sample) > 1]
    assert not crossed, f"{len(crossed)} of {len(seen)} samples held two archives at once: {crossed[:3]}"
    assert len({folder for _kind, folder in views._VIEWS}) == 1
    assert len(views._VIEWS) <= 2, "two pages of one archive is the whole of what is kept"


def test_one_gather_reads_each_transcription_once(setup, monkeypatch):  # noqa: F811
    """The second these pages save, and why it was a second at all.

    One file cut into many documents is the shape that makes it hurt, and the live archive of that
    shape holds 257 documents in one text export. The page asked for that one file once per
    document, to see how the archive writes its dates, and then once per file for everything else:
    258 readings of it and 3.4 s of json to draw one card. The reading cannot differ — same bytes,
    same file, same parse — so it is read once, and that card now takes 0.03 s.

    Invented here rather than measured only on that archive: ten pages classified as five
    documents, which is a shape no synthetic archive in this suite had.
    """
    from epicrisis import document_dates
    from epicrisis.extract.run import extract_source
    from epicrisis.web import documents as views
    from test_extract import classify_line

    data_dir, source, output, records = setup
    lines = [classify_line(records["long_scan.pdf"], page, "first" if page % 2 else "continuation", "discharge")
             for page in range(1, 11)]  # fmt: skip
    lines += [classify_line(records["labs.pdf"], 1, "first", "lab_panel"),
              classify_line(records["labs.pdf"], 2, "continuation", "lab_panel")]  # fmt: skip
    lines += [classify_line(records["invoice.pdf"], 1, "first", "insurance")]
    (output / "classify.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    extract_source(data_dir, source, FakeExtractBackend())

    read = []
    for module in (views, document_dates):
        asked = module.load_extracted
        monkeypatch.setattr(module, "load_extracted",
                            lambda folder, sha256, asked=asked: read.append(sha256) or asked(folder, sha256))  # fmt: skip

    views._VIEWS.clear()
    view = views.source_documents(source, output)
    assert view["document_count"] == 7, "the shape is seven documents in three files; it did not land"
    assert read and len(read) == len(set(read)), f"{len(read)} readings of {len(set(read))} files"

    read.clear()
    card = views.document_card(source, output, records["long_scan.pdf"]["sha256"], 1)
    assert card is not None
    assert read and len(read) == len(set(read)), f"{len(read)} readings of {len(set(read))} files for one card"


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
    for path, data in ((f"{card}/date", {"value": A_DAY_FOR_AN_ILLUSTRATION.isoformat()}),
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


def a_whole_press(data_dir: Path) -> dict:
    """The settings form as the page writes it, with every switch flipped and every panel changed.

    Built out of the rules this program ships rather than written out, so a rule added next month
    is in the press without anybody remembering to put it there.
    """
    from epicrisis import rules, settings

    shown, knob_name, knob_value, turning_on = [], [], [], []
    for rule in rules.load(data_dir):
        shown.append(rule.id)
        if not settings.rule_on(data_dir, rule):
            turning_on.append(rule.id)
        chosen = settings.rule_settings(data_dir, rule)
        for name, default in rule.settings.items():
            knob_name.append(f"{rule.id}:{name}")
            value = chosen[name]
            if isinstance(default, int | float) and not isinstance(default, bool):
                value = value + 1
            knob_value.append(str(value))
    return {"mode": "with_meaning", "tab": "rules", "rule_on": turning_on,
            "shown": shown + ["ask_page", "models", "read_materials", "mcp_lock"],
            "confirm_rule": shown, "knob_name": knob_name, "knob_value": knob_value,
            "ask_page": "on", "read_materials": "on", "mcp_lock_minutes": 120,
            "mcp_lock_scope": "server", "model_first": "zzz-one", "model_strong": "zzz-two",
            "model_second_reader": "zzz-three"}  # fmt: skip


def test_one_press_of_save_writes_the_settings_once_and_keeps_the_version_before_it(client, data_dir):
    """One press, forty-four presses' worth of writing, and .previous holding half of the press.

    Every writer in settings.py wrote the whole file and copied the whole file to
    settings.json.previous, and one press of Save calls a dozen of them: measured over the 26
    rules and 25 thresholds this program ships, with every switch flipped and every threshold
    nudged, one press wrote settings.json 44 times and made 44 copies.

    The cost is not the writing. The refusal this program prints over an unreadable settings file
    offers that copy in so many words — "copy back settings.json.previous beside it, the version
    before the last change" — and promises the engine, the three models, the answer mode, the
    switches and the lock back with it. After 44 writes the copy is the file as the 44th of them
    found it: the middle of the press a person had just made, a state nobody ever chose. Following
    the written advice handed them half of their own last press. Measured on a smaller press,
    changing one threshold of each of two rules: the two stood at 99 and 7 before and at 11 and 3
    after, and .previous afterwards held 11 — already the new one — beside the old 7.
    """
    import json

    from epicrisis import settings

    settings.set_answer_mode(data_dir, "as_printed")
    before = json.loads(settings.settings_path(data_dir).read_text(encoding="utf-8"))

    writes, copies = [], []
    whole, copied = settings.write_whole, settings.copy_whole
    settings.write_whole = lambda path, text: (writes.append(text), whole(path, text))[1]
    settings.copy_whole = lambda source, target: (copies.append(str(target)), copied(source, target))[1]
    try:
        saved = client.post("/settings", data=a_whole_press(data_dir), follow_redirects=False)
    finally:
        settings.write_whole, settings.copy_whole = whole, copied

    assert saved.status_code == 303
    assert len(writes) == 1, f"one press, {len(writes)} writes of settings.json"
    assert len(copies) == 1, f"one press, {len(copies)} copies into settings.json.previous"

    # And the one copy is the file as it stood before the press, not a moment inside it. Every
    # choice the press changed reads in .previous the way it read before Save was pressed.
    kept = json.loads((settings.settings_path(data_dir).with_name("settings.json.previous")).read_text(encoding="utf-8"))
    assert kept == before, "settings.json.previous is not the version before the press"
    now = json.loads(settings.settings_path(data_dir).read_text(encoding="utf-8"))
    assert now != before, "the press stored nothing, so there is nothing to have kept"
    assert settings.answer_mode(data_dir) == "with_meaning"  # the press did land


def test_two_threads_changing_the_settings_do_not_lose_one_another_s_work(tmp_path, monkeypatch):
    """The third file of a person's own choices, and the only one without a lock.

    indicators.json and people.json each hold what somebody decided and each have had their own
    lock since the day two writers lost one another's work. settings.json holds the engine, three
    models, the answer mode, the threshold of every rule and the lock over the network, is written
    the same read-modify-write way, and had none — and the dashboard is a FastAPI application
    whose plain handlers run in a pool of threads, so two writers at once is not a theory.

    What is asserted is not that both writers won — the lock refuses rather than queues — but that
    nothing was lost in silence: each writer either wrote and its choice is in the file, or was
    told Busy and knows it did not. Without the lock both are told they wrote and one choice is
    gone, which is the assertion that fails.

    The waits are what make this a test rather than a coin toss: the second writer reads after the
    first has read and writes after the first has written, which without a lock loses the first
    choice every time.
    """
    import threading
    import time

    from epicrisis import settings
    from epicrisis.runs import Busy

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    settings.set_answer_mode(data_dir, "as_printed")

    # Every writer works this out after it has read the file and before it writes, so a wait here
    # is exactly the window between one writer's read and its write — the window a lock has to
    # cover. The first reads early and writes early, the second reads early and writes late, so
    # without a lock the second's write is built on what it read before the first wrote.
    noted = settings._noted
    windows = {"first": 0.1, "second": 0.3}

    def slowly(before, after):
        time.sleep(windows.get(threading.current_thread().name, 0))
        return noted(before, after)

    monkeypatch.setattr(settings, "_noted", slowly)
    wrote, told = [], []

    def choosing(which, choose):
        try:
            choose()
            wrote.append(which)
        except Busy:
            told.append(which)

    threads = [threading.Thread(target=choosing, name="first",
                                args=("first", lambda: settings.set_ask_enabled(data_dir, True))),
               threading.Thread(target=choosing, name="second",
                                args=("second", lambda: settings.set_mcp_lock_minutes(data_dir, 120)))]  # fmt: skip
    threads[0].start()
    time.sleep(0.05)  # long enough for the first to hold the lock and to have read the file
    threads[1].start()
    for thread in threads:
        thread.join()

    assert len(wrote) + len(told) == 2  # neither thread failed in some other way
    monkeypatch.setattr(settings, "_noted", noted)
    kept = {"first": settings.ask_enabled(data_dir), "second": settings.mcp_lock_minutes(data_dir) == 120}
    for which in wrote:
        assert kept[which], f"{which} was told it wrote, and its choice is not in the file"
    for which in told:
        assert not kept[which], f"{which} was told it wrote nothing, and its choice is there"
    assert not (data_dir / "settings.lock").exists()  # taken off after


def test_a_threshold_that_cannot_be_read_is_said_out_loud_and_keeps_the_others(client, data_dir):
    """"Saved. Nothing on the page was different from what was already stored", over a refusal.

    The page was different, the write was refused, and the reason for the refusal was written in
    settings.py for a person to read — "times_away should be a whole number". It went into a
    suppress(ValueError) and reached nobody. Measured on one threshold: 90 stored and said so,
    "not a number" answered "Nothing on the page was different" with 90 still stored, 120 stored
    and said so again. The middle answer is false about the page and about the storing both.

    And worse for a rule with more than one threshold. The write replaces every threshold of a
    rule at once, and settings.py refuses the whole rule on the first value it cannot read, so
    one mistyped number lost the others as well: of weight 5 -> 1, least_history 7 -> 9 and
    times_away 20 -> "not a number", all three were dropped and nothing was said.
    """
    from epicrisis import rules, settings

    def press(rule, typed: dict) -> tuple[str, dict]:
        chosen = settings.rule_settings(data_dir, rule)
        answer = client.post("/settings", data={
            "mode": "as_printed", "tab": "rules", "shown": [rule.id],
            "rule_on": [one.id for one in rules.load(data_dir) if settings.rule_on(data_dir, one)],
            "knob_name": [f"{rule.id}:{name}" for name in rule.settings],
            "knob_value": [str(typed.get(name, chosen[name])) for name in rule.settings],
        }, follow_redirects=False)  # fmt: skip
        assert answer.status_code == 303
        page = client.get(answer.headers["location"]).text
        return page, settings.rule_settings(data_dir, rules.load(data_dir).get(rule.id))

    one = rules.load(data_dir).get("dates_far_apart")
    page, kept = press(one, {"apart_by_days": 90})
    assert "Saved: thresholds of 1 rule" in page and kept["apart_by_days"] == 90

    page, kept = press(one, {"apart_by_days": "not a number"})
    assert kept["apart_by_days"] == 90, "a word was stored as a threshold"
    # The reason reaches the page, names the threshold and the rule, and says what it wanted.
    assert "apart by days" in page and one.name in page and "wants a whole number" in page
    # And the page does not say the opposite in the same breath.
    assert "Nothing on the page was different" not in page

    page, kept = press(one, {"apart_by_days": 120})
    assert "Saved: thresholds of 1 rule" in page and kept["apart_by_days"] == 120

    # A rule of three thresholds with one of the three mistyped: the two good ones are stored,
    # the one that could not be read stands where it stood, and only that one is spoken of.
    many = rules.load(data_dir).get("number_far_from_the_others")
    _page, was = press(many, {"weight": 5, "least_history": 7, "times_away": 20})
    assert (was["weight"], was["least_history"], was["times_away"]) == (5, 7, 20)

    page, kept = press(many, {"weight": 1, "least_history": 9, "times_away": "not a number"})
    assert (kept["weight"], kept["least_history"]) == (1, 9), "a good threshold went with a bad one"
    assert kept["times_away"] == 20, "the one that could not be read did not stay as it was"
    assert "times away" in page and "wants a whole number" in page
    assert "Saved: thresholds of 1 rule" in page  # both halves of the press said, not one


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
    with open_index(data_dir, None) as connection:
        _rows, counts, _how_many = query.flagged_values(
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
    with open_index(data_dir, None) as connection:
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


@pytest.mark.parametrize("asked", [
    "витамин в12",        # a word of look-alike letters beside an ordinary one
    "vitamin b12",        # the same question typed the other way round
    "гемоглобін а1с",
    "psa свободный",
    "са 125",
    "a-b",                # how it was first seen: a hyphen, which is not even a word
    'x"y',                # and a quotation mark, which FTS5 would read as syntax
])
def test_a_question_of_two_words_is_answered_and_not_an_internal_server_error(archive_index, asked):  # noqa: F811
    """Seven of twelve ordinary questions answered 500, and nothing anywhere recorded that.

    A space between two bare terms is an AND in FTS5 and reads better, which is why the question
    was built that way. A space in front of a bracket is a syntax error — and the moment a word got
    a second spelling, because every letter of it is drawn alike in two alphabets, it came in
    brackets. So any question of two words where either of them was that shape died in sqlite with
    "fts5: syntax error near (" and reached the person as the words Internal Server Error.

    This is the first defect the journal found, on the day it was written, from one line of it. It
    is parametrised with the questions a person actually types rather than with the hyphen it was
    noticed through, because the hyphen was never the point.
    """
    data_dir, source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    answer = client.post("/search", data={"q": asked}, follow_redirects=True)

    assert answer.status_code == 200, f"{asked!r} answered {answer.status_code}"
    # And an empty result is still an answer, with the sentence that says what empty means here.
    assert "Internal Server Error" not in answer.text


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
    # The name a lane is captioned with is the one a person reads; the one an address carries is
    # the one the index stores. Asked for by the second and read back by the first.
    with open_index(data_dir, None) as connection:
        types = [kind for kind, count in query_index.overview(connection)["types"].items() if count]
    assert len(set(re.findall(r'class="name">([^<]+)<', lanes))) > 1, "one lane only: this archive cannot show the defect"

    for kind in sorted(types):
        page = client.get(f"/?view=lanes&doc_type={kind}").text
        if "Nothing in this archive answers that address" in page:
            continue  # A type whose only document carries no date draws no lane here.
        # One lane, because that is what was asked for, and every point inside the axis.
        assert set(re.findall(r'class="name">([^<]+)<', page)) == {doc_types.in_words(kind)}
        places = [float(one) for one in re.findall(r'class="dot" style="left: ([-\d.]+)%', page)]
        assert places, f"{kind}: no points drawn"
        assert all(-0.01 <= one <= 100.01 for one in places), f"{kind}: points at {places}"
        # And the filter says it is on, with something to press to take it off. That used to be a
        # line of prose under the tabs, "<type> only · every type"; it is the chooser now, which
        # stands on the chosen type and offers all of them on its first line.
        assert f'<option value="{kind}" selected>' in page and "All of them" in page
        assert f"{kind} only" not in page, "the box says it; a line repeating it is a second control"


def test_the_by_type_cut_chooses_one_type_or_all_of_them_like_the_cuts_beside_it(archive_index):  # noqa: F811
    """"By type тоже нужен combo-box": one cut of three had no way to say which one, or all of them.

    By doctor and By institution each stand over a single box whose first line is "All of them",
    and choosing is the whole act. By type had nothing: it broke the documents into types and drew
    them all, the way to a single type ran through a type tab in the By year view beside it, and
    the way back was a line of prose under the tabs. Every state is an address here as it is there,
    the button beside the box works with nothing running in the browser, and there is one box to a
    page — the markup is shared by the three cuts, and two sections would write id="whose" twice.
    """
    data_dir, _source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    with open_index(data_dir, None) as connection:
        held = list(query_index.overview(connection)["types"])
    assert len(held) > 1, "one type only: this archive cannot show the defect"

    whole = client.get("/?view=lanes").text
    box = whole.split('cut-chooser">')[1].split("</section>")[0]
    # The view is carried by the form, or choosing a type would answer in another cut altogether.
    assert 'name="doc_type"' in box and '<input type="hidden" name="view" value="lanes">' in box
    # Every type the archive holds, and all of them is where the cut opens — an address a person
    # can keep, not a state they can only leave.
    assert re.findall(r'<option value="([^"]*)"', box) == ["", *held]
    assert '<option value="" selected>All of them' in box
    # A form that is posted, not a script: the button stands in the page for anyone without the two
    # lines that submit the moment a type is chosen.
    assert 'method="get" action="/"' in box and 'id="whose-go" type="submit"' in box
    assert 'id="whose"' in box and 'for="whose"' in box, "an unlabelled select says nothing aloud"

    for kind in held:
        chosen = client.get(f"/?view=lanes&doc_type={kind}").text.split('cut-chooser">')[1]
        assert f'<option value="{kind}" selected>' in chosen, kind
        assert '<option value="">All of them' in chosen, f"{kind}: no way back to all of them"
        # The year a person chose before is carried by hand: a GET form sends its own fields and
        # nothing else, and a filter dropped on the way is one that vanished in silence.
        with_year = client.get(f"/?view=lanes&year=2003&doc_type={kind}").text
        assert '<input type="hidden" name="year" value="2003">' in with_year, kind

    # One box to a page. Asked for a cut by a name and the By type view in the same address, the
    # name's box is the one drawn: a name narrows a list of documents, and this view lists none.
    both = client.get("/?view=lanes&cut=institution").text
    assert both.count('id="whose"') == 1 and 'name="provider"' in both


def test_the_type_chooser_promises_no_count_and_the_lanes_keep_theirs(archive_index):  # noqa: F811
    """A number in the box would be of one set and the page it leads to of another.

    The row of type tabs in the By year view was counted over the whole archive while every one of
    its links carried the year in force, so a tab read "consultation 3" in a year that holds none
    and pressing it gave "Showing 0 of 0". The By type view draws only documents that carry a date:
    in this archive the insurance letter carries none, so a line of the box reading "insurance 1"
    would promise a document and then draw an empty axis. The counts that stay are the ones at the
    end of each lane, which count the very points drawn beside them.
    """
    data_dir, _source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    page = client.get("/?view=lanes").text
    box = page.split('cut-chooser">')[1].split("</section>")[0]
    offered = re.findall(r"<option [^>]*>([^<]*)<", box)
    assert offered and not any(re.search(r"\d", one) for one in offered), offered
    assert "muted" not in box, "the grey a count is printed in: a count here is of another set"

    # The type whose one document carries no date is offered all the same — a list made of the
    # lanes would have hidden a type the archive holds — and the address it leads to is answered as
    # an address, not as the archive being empty of that type.
    empty = client.get("/?view=lanes&doc_type=insurance").text
    assert "Nothing in this archive answers that address" in empty
    assert '<option value="insurance" selected>' in empty, "and the box is still there to come back"

    # What a lane says it holds is what it drew.
    for lane in page.split('<div class="lane">')[1:]:
        assert lane.count('class="dot"') == int(re.search(r'class="mono count">(\d+)<', lane).group(1)), lane


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

    # Said where the choice is made: the By type view has a chooser now, and it stands on the type
    # it is drawing. The line of prose that used to say it is gone with the second link to undo it.
    lanes = client.get("/?view=lanes&doc_type=lab_panel").text
    assert '<option value="lab_panel" selected>' in lanes, "the view that does filter says so"

    tests = client.get("/?view=indicators&doc_type=lab_panel").text
    assert 'name="doc_type"' not in tests, "no chooser for a type this view does not apply"
    assert "lab_panel only" not in tests
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


def test_the_labels_under_the_year_strip_do_not_run_into_one_another(archive_index):  # noqa: F811
    """Reported from a phone: on an archive reaching back before 2000 the early labels collided.

    The slot a year stands in is eighteen pixels and a four-digit label at that size is nearly
    twenty-two, so "1989" and "1992" overlapped while "01" and "02" sat fine. Four digits were
    printed before 2000 so that "89" beside "01" could not be read as 2089 — a fear, not a
    condition: it takes an archive spanning a hundred years before two years can share a two-digit
    label, and under that the order of the strip, the title on each bar and the year printed in
    full underneath all say which is which.

    So the rule is the condition now. This asserts both sides, because a guard that only ever takes
    one branch is the kind that rots.
    """
    data_dir, _source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    page = client.get("/").text
    labels = re.findall(r'class="label caps">([^<]+)<', page)
    assert labels, "no year labels on the strip at all"
    assert all(len(one) == 2 for one in labels), f"four digits inside one century: {labels}"
    assert "by-the-century" not in page  # and the wider slot is not asked for

    # And a century apart, where two digits really would say two things, it says four.
    import sqlite3

    from epicrisis.index.build import index_path

    with sqlite3.connect(index_path(data_dir, _source.id)) as connection:
        first = connection.execute("SELECT id FROM documents WHERE date IS NOT NULL LIMIT 1").fetchone()[0]
        # A hundred years before the day the illustrations carry, so that the strip really does
        # span two centuries: the condition under test is the span and not the year.
        a_century_back = A_DAY_FOR_AN_ILLUSTRATION.replace(year=A_DAY_FOR_AN_ILLUSTRATION.year - 100)
        connection.execute("UPDATE documents SET date = ? WHERE id = ?", (a_century_back.isoformat(), first))
        connection.commit()

    far = client.get("/").text
    labels = re.findall(r'class="label caps">([^<]+)<', far)
    assert all(len(one) == 4 for one in labels), f"two digits across a century: {labels}"
    assert "by-the-century" in far  # which is what gives them the room


def test_a_mark_on_the_axis_names_a_year_the_page_holds(archive_index):  # noqa: F811
    """The axis ran one year past the newest document, and a mark was allowed to stand on its edge.

    With a single year chosen, the only label on the By type axis was the year after it, printed at
    the full width — a page whose one date is 2019 labelled 2020. A mark belongs inside the span the
    page draws, and where no fifth year falls inside it, the span's own first year is the mark.
    """
    data_dir, _source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    page = client.get(f"/?view=lanes&year={A_DAY_FOR_AN_ILLUSTRATION.year}").text
    marks = re.findall(r'class="tick caps" style="left: [^"]*">(\d{4})<', page)
    assert marks == [str(A_DAY_FOR_AN_ILLUSTRATION.year)], f"marks on the axis: {marks}"


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
    # A photograph in a format this build cannot open. It was a .txt here until plain text
    # became a document like any other, and then this folder had something to read after all.
    (empty / "notes" / "photo.heic").write_bytes(b"\0\0\0\x18ftypheic" + b"\0" * 64)
    assert add(client, empty).status_code == 303

    for page in ("/", "/documents", "/search", "/review", "/indicators", "/ask", "/card"):
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


def test_who_made_the_documents_is_a_cut_of_the_archive(archive_index):
    """Institutions and doctors, as each document prints them, and a way into each one's work.

    A cut nobody could take until the doctor had a field of their own: before that a person's name
    sat where the institution goes and the two could not be told apart.
    """
    import sqlite3

    from epicrisis.index.build import index_path

    data_dir, source, labs = archive_index
    with sqlite3.connect(index_path(data_dir, source.id)) as connection:
        connection.execute("UPDATE documents SET provider = 'Synthetic Laboratory', doctor = 'Нетудихата І.В'")
        connection.commit()

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    doctors = client.get("/who")
    institutions = client.get("/who", params={"kind": "institution"})

    assert doctors.status_code == 200 and institutions.status_code == 200
    assert "Нетудихата І.В" in doctors.text and "Synthetic Laboratory" not in doctors.text
    assert "Synthetic Laboratory" in institutions.text
    assert "nothing is joined for you" in doctors.text  # one person is written several ways
    assert "/?doctor=" in doctors.text and "/?provider=" in institutions.text

    # And the link leads to that one's work, and to nobody else's.
    theirs = client.get("/", params={"doctor": "Нетудихата І.В"})
    nobody = client.get("/", params={"doctor": "Somebody Else"})
    assert theirs.status_code == 200 and nobody.status_code == 200
    assert theirs.text.count("/documents/") > nobody.text.count("/documents/")


def test_the_consent_page_says_what_a_page_is_for_each_kind_of_file(client):
    """How many pages will be sent is the number on that page, and a person could not find out why.

    One text file became 261 pages here, and nothing in the program said how a file becomes pages:
    a PDF by what was printed, a photograph by its frames, a workbook by its sheets, a text file by
    the lines its own export draws between documents.
    """
    page = client.get("/consent").text

    assert "What a page is, for each kind of file" in page
    for kind in ("A PDF", "A photograph or a scan", "A Word document", "A spreadsheet", "A plain text file"):
        assert kind in page, kind
    assert "never sent anywhere" in page  # a format this program does not read


def test_the_card_puts_the_newest_line_first_and_not_the_commonest(archive_index):
    """The owner of an archive read the top of his medications and asked why they stopped in 2014.

    They had not. The roll was ordered by how many documents carried a line, with the date only
    breaking a tie, so a drug prescribed to him this year stood on one document underneath one
    prescribed in 1992 that had been copied into four. On a page whose question is what this
    person is on, the count is a remark and the date is the answer.
    """
    import sqlite3

    from epicrisis import query as query_index
    from epicrisis.index.build import index_path

    data_dir, source, _labs = archive_index
    with sqlite3.connect(index_path(data_dir, source.id)) as connection:
        documents = [row[0] for row in connection.execute(
            "SELECT id FROM documents WHERE primary_copy = 1 ORDER BY date LIMIT 2")]
        assert len(documents) == 2
        connection.execute("DELETE FROM medications")
        # One prescribed long ago and copied about, one prescribed since and standing alone.
        connection.execute("UPDATE documents SET date = '1992-08-14' WHERE id = ?", (documents[0],))
        connection.execute("UPDATE documents SET date = '2026-07-21' WHERE id = ?", (documents[1],))
        for _ in range(4):
            connection.execute("INSERT INTO medications (document_id, text) VALUES (?, ?)",
                               (documents[0], "Invented tablets 1 mg"))  # fmt: skip
        connection.execute("INSERT INTO medications (document_id, text) VALUES (?, ?)",
                           (documents[1], "Invented drops 2 mg"))  # fmt: skip
        connection.commit()

    with sqlite3.connect(f"file:{index_path(data_dir, source.id)}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        card = query_index.patient_card(connection)

    lines = card["medications"]
    assert [row["text"] for row in lines] == ["Invented drops 2 mg", "Invented tablets 1 mg"]
    # And the count is still printed beside it, because it was never the wrong thing to know.
    assert lines[0]["documents"] == 1 and lines[1]["documents"] == 4


def test_the_patient_card_says_what_is_printed_and_not_what_is_taken(archive_index):
    """A list of medications under a person's name reads as "what they take", and that is a
    judgement no page can make: a drug printed in 2019 may have been stopped the month after."""
    import sqlite3

    from epicrisis.index.build import index_path

    data_dir, source, labs = archive_index
    with sqlite3.connect(index_path(data_dir, source.id)) as connection:
        document = connection.execute("SELECT id FROM documents LIMIT 1").fetchone()[0]
        connection.execute("INSERT INTO diagnoses VALUES (?, ?)", (document, "Synthetic diagnosis"))
        connection.execute("INSERT INTO medications VALUES (?, ?)", (document, "Synthetic tablets 5 mg"))
        connection.execute(
            "INSERT INTO observations (document_id, page, name, value, unit) VALUES (?, 1, ?, ?, NULL)",
            (document, "Група крові", "0 (І)"),
        )
        connection.commit()

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = client.get("/card")
    diagnoses = client.get("/card", params={"tab": "diagnoses"})
    medications = client.get("/card", params={"tab": "medications"})

    assert page.status_code == 200
    assert "Synthetic diagnosis" in diagnoses.text and "Synthetic tablets 5 mg" in medications.text
    assert "Група крові" in page.text and "0 (І)" in page.text  # the one measurement about the person
    # The whole honesty of the page is one paragraph, and it has to be there — on each of the four
    # tabs, because a person who arrived at one of them by its own address has read no other.
    for tab in (page, diagnoses, medications):
        assert "what the documents print" in tab.text
        assert "not what is taken\n      or true today" in tab.text
    assert "/documents/" in page.text  # and every line leads back to the page it was printed on


def test_the_card_says_one_thing_may_stand_on_it_twice_under_two_spellings(archive_index):
    """Four lines for two medications, and a doctor reading the page in a minute and a half.

    The card is the page README offers to hold up at an appointment, and the one place in this
    program where a list of names is read as a list of things rather than a list of spellings. Two
    forms writing one drug in two languages put it on the card twice, each with its own count of
    documents — which is right, because joining them is a claim this program must not make, and
    which reads as two drugs unless the page says so. /who had carried that sentence since the day
    it was needed there; this tab had not.
    """
    import sqlite3

    from epicrisis.index.build import index_path

    data_dir, source, labs = archive_index
    with sqlite3.connect(index_path(data_dir, source.id)) as connection:
        document = connection.execute("SELECT id FROM documents LIMIT 1").fetchone()[0]
        for one in ("Квазитрофин-форте 11 мг", "Quasitrophine forte 11 mg"):
            connection.execute("INSERT INTO medications VALUES (?, ?)", (document, one))
        for one in ("Квазитрофиновая недостаточность", "Quasitrophine deficiency"):
            connection.execute("INSERT INTO diagnoses VALUES (?, ?)", (document, one))
        connection.commit()

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    medications = client.get("/card", params={"tab": "medications"}).text
    diagnoses = client.get("/card", params={"tab": "diagnoses"}).text

    # Both spellings stand, because choosing between them is the thing that must not happen here.
    assert "Квазитрофин-форте 11 мг" in medications and "Quasitrophine forte 11 mg" in medications
    assert "Квазитрофиновая недостаточность" in diagnoses and "Quasitrophine deficiency" in diagnoses
    # And each tab says why there are two, in the words the page about doctors already uses.
    assert "stand here more\n      than once where the forms write its name differently" in medications
    assert "stand here more\n      than once where the forms word it differently" in diagnoses
    # The count beside a line is of documents, and the page says that too rather than leaving a
    # reader to read it as a number of prescriptions.
    assert "of documents carrying" in medications


def test_the_card_names_the_questions_the_documents_answer_two_ways(archive_index):
    """Not every difference is a conflict: leucocytes differ between two days and that is a person
    living. A blood group does not change, and neither does the answer to "sex"."""
    import sqlite3

    from epicrisis.index.build import index_path

    data_dir, source, labs = archive_index
    with sqlite3.connect(index_path(data_dir, source.id)) as connection:
        documents = [row[0] for row in connection.execute("SELECT id FROM documents ORDER BY id")]
        for document, value in zip(documents, ("позитивна", "негативна"), strict=False):
            connection.execute(
                "INSERT INTO observations (document_id, page, name, value) VALUES (?, 1, 'Rh', ?)",
                (document, value),
            )
        # The same group written with a nought and with a letter is not a disagreement.
        for document, value in zip(documents, ("0 (І)", "O (I)"), strict=False):
            connection.execute(
                "INSERT INTO observations (document_id, page, name, value) VALUES (?, 1, 'Група крові', ?)",
                (document, value),
            )
        connection.commit()

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = client.get("/card", params={"tab": "conflicts"}).text

    assert "Where the documents disagree" in page
    assert "negative / positive" in page  # the Rh, answered two ways
    assert "blood group" not in page  # a nought and a letter O are one group, not a disagreement
    assert "One of them is wrong about this person" in page


def test_two_letters_inside_a_printed_name_are_not_the_rh_of_the_person(archive_index):
    """"Rh" is two letters, and read as a substring it stood inside names that are no Rh at all.

    A laboratory prints names this program has no list of, and any of them holding those two
    letters — a rheumatoid factor, an arrhythmia, a cirrhosis, a diarrhoea — was read as the Rh of
    the person. The card printed such a line on its first tab as "Rh negative", and the tab that
    names disagreements then put it against the real Rh and said the documents fell out about this
    person's resus factor. Both the line and the disagreement were invented out of a printed name.

    The names below are nonsense on purpose: the point is the two letters and where they stand, and
    one holds them inside a word while the other begins with them, which is the case a match on the
    start of the name alone does not catch.
    """
    import sqlite3

    from epicrisis.index.build import index_path

    data_dir, source, labs = archive_index
    with sqlite3.connect(index_path(data_dir, source.id)) as connection:
        documents = [row[0] for row in connection.execute("SELECT id FROM documents ORDER BY id")]
        assert len(documents) > 1
        connection.execute(
            "INSERT INTO observations (document_id, page, name, value) VALUES (?, 1, 'Rh', 'позитивна')",
            (documents[0],),
        )
        for name in ("Vurrhadol index", "Rhembalic factor"):
            connection.execute(
                "INSERT INTO observations (document_id, page, name, value) VALUES (?, 1, ?, 'негативна')",
                (documents[1], name),
            )
        connection.commit()

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    person = client.get("/card", params={"tab": "person"}).text
    conflicts = client.get("/card", params={"tab": "conflicts"}).text

    # The Rh of the person is the line a form printed as an Rh, and it is the only one.
    assert "позитивна" in person
    assert "негативна" not in person
    for invented in ("Vurrhadol", "Rhembalic"):
        assert invented not in person, invented
    # And nothing disagrees, because nothing here ever answered the same question twice.
    assert "Nothing here is answered two ways." in conflicts
    assert "negative / positive" not in conflicts


def test_one_answer_printed_on_many_forms_does_not_push_the_fact_beside_it_off_the_card(archive_index):
    """The card showed at most eight of these lines, and counted them before folding them together.

    One per document is what it counted, and an archive carries one blood group on every form that
    ever asked for one: nine forms printing the same group used the whole of the limit, and the Rh
    printed beside it on older forms never reached the first tab, nor the tab that names
    disagreements — where those forms disagreed. Nothing on either tab said a line had been left
    out, which is what makes it a defect and not a short page.

    The shape is invented, because no archive in front of us has it: nine forms of one group and
    two older ones that print an Rh, and print it two ways.
    """
    import sqlite3

    from epicrisis import query as query_index
    from epicrisis.index.build import index_path

    data_dir, source, _labs = archive_index
    path = index_path(data_dir, source.id)
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM observations")
        printed = [(2020 + year, "Група крові", "0 (І)") for year in range(9)]
        printed += [(2011, "Rh", "позитивна"), (2010, "Rh", "негативна")]
        for year, name, value in printed:
            document = connection.execute(
                """INSERT INTO documents (source_id, file_sha256, first_page, date, primary_copy)
                   VALUES (?, ?, 1, ?, 1)""", (source.id, f"{year:064d}", f"{year}-05-06")).lastrowid  # fmt: skip
            connection.execute(
                "INSERT INTO observations (document_id, page, name, value) VALUES (?, 1, ?, ?)",
                (document, name, value),
            )
        connection.commit()

    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        card = query_index.patient_card(connection)

    # The group stands once however many forms carry it, and the Rh beside it is still on the tab.
    assert [one["value"] for one in card["personal"] if one["about"] == "Blood group"] == ["0 (І)"]
    assert sorted(one["value"] for one in card["personal"] if one["about"] == "Rh") == ["негативна", "позитивна"]
    # And so is the disagreement, which went off the page together with the lines it was read from.
    assert [one["about"] for one in card["conflicts"]] == ["Rh"]
    assert card["conflicts"][0]["answers"] == ["negative", "positive"]
    # One page for each side of it, and a page for each side before any side is shown twice.
    assert len(card["conflicts"][0]["lines"]) == 2


def test_the_patient_card_is_four_tabs_and_each_of_them_has_its_own_address(archive_index):
    """In one column a person opening the card for a blood group scrolled past every medication
    the archive prints to reach the disagreements, which are the thing the page exists for."""
    import sqlite3

    from epicrisis.index.build import index_path

    data_dir, source, labs = archive_index
    with sqlite3.connect(index_path(data_dir, source.id)) as connection:
        document = connection.execute("SELECT id FROM documents LIMIT 1").fetchone()[0]
        connection.execute("INSERT INTO diagnoses VALUES (?, ?)", (document, "Synthetic diagnosis"))
        connection.execute("INSERT INTO medications VALUES (?, ?)", (document, "Synthetic tablets 5 mg"))
        connection.execute(
            "INSERT INTO observations (document_id, page, name, value, unit) VALUES (?, 1, ?, ?, NULL)",
            (document, "Група крові", "0 (І)"),
        )
        connection.commit()

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    pages = {tab: client.get("/card", params={"tab": tab} if tab else None)
             for tab in ("", "person", "medications", "diagnoses", "conflicts", "what a tab is not")}  # fmt: skip

    assert all(page.status_code == 200 for page in pages.values())
    # Every tab is listed on every tab, and the one being read is the one marked.
    for tab, page in pages.items():
        for link in ("person", "medications", "diagnoses", "conflicts"):
            assert f'href="/card?tab={link}"' in page.text, (tab, link)
    assert '/card?tab=medications" aria-current="page"' in pages["medications"].text
    assert '/card?tab=conflicts" aria-current="page"' in pages["conflicts"].text

    # Each tab carries its own content and nobody else's.
    assert "Група крові" in pages["person"].text and "Synthetic tablets 5 mg" not in pages["person"].text
    assert "Synthetic tablets 5 mg" in pages["medications"].text
    assert "Synthetic diagnosis" not in pages["medications"].text
    assert "Synthetic diagnosis" in pages["diagnoses"].text
    assert "One of them is wrong about this person" not in pages["diagnoses"].text

    # An address naming no tab, and one naming a tab that is not here, both arrive at the first.
    for asked in ("", "what a tab is not"):
        assert '/card?tab=person" aria-current="page"' in pages[asked].text, asked
        assert "Personal data, as printed" in pages[asked].text, asked


def test_a_card_tab_with_nothing_on_it_is_still_listed_and_says_so(archive_index):
    """A control that disappears when its tab is empty reads as the interface breaking, and an
    archive of laboratory reports alone genuinely prints no diagnosis and no medication."""
    import sqlite3

    from epicrisis.index.build import index_path

    data_dir, source, labs = archive_index
    with sqlite3.connect(index_path(data_dir, source.id)) as connection:
        connection.execute("DELETE FROM diagnoses")
        connection.execute("DELETE FROM medications")
        connection.commit()

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    empty = {tab: client.get("/card", params={"tab": tab}).text
             for tab in ("person", "medications", "diagnoses", "conflicts")}  # fmt: skip

    for tab, page in empty.items():
        assert f'/card?tab={tab}" aria-current="page"' in page, tab
    assert "No document here prints the sex, the date of birth" in empty["person"]
    assert "No document here prints a medication." in empty["medications"]
    assert "No document here prints a diagnosis." in empty["diagnoses"]
    assert "Nothing here is answered two ways." in empty["conflicts"]
    # And it says so of what it compares and not of the archive: four fields have one answer for a
    # person and are weighed against each other, and a medication printed two ways is not one of
    # them. "Every question these documents answer about the person" covered all of it.
    assert "the four this tab compares" in empty["conflicts"]
    assert "they answer the same" not in empty["conflicts"]
    # Read, and nowhere printed, is the state these four sentences are for. The other side of that
    # line is the test below: not read at all says so instead, and says none of these.
    for tab, page in empty.items():
        assert "have not been read yet" not in page, tab


def test_the_card_does_not_answer_about_documents_it_has_not_read(client, archive):
    """An instance that had read nothing was told that nothing about the person disagreed.

    "Every question these documents answer about the person, they answer the same" over an archive
    no model had looked at reads as a check that ran and found nothing. It was an empty field of
    this program's own, and the page is the only place that can tell the two apart: the seven other
    pages of this interface say "have not been read yet", and the card alone said this instead.
    """
    assert add(client, archive).status_code == 303

    tabs = {tab: client.get("/card", params={"tab": tab}).text
            for tab in ("person", "medications", "diagnoses", "conflicts")}  # fmt: skip

    for tab, page in tabs.items():
        assert "The documents of" in page and "have not been read yet" in page, tab
        # Not one of the four sentences that claim to have looked, and above all not the one that
        # claimed the answers agreed.
        for said in ("No document here prints the sex", "No document here prints a medication.",
                     "No document here prints a diagnosis.", "Nothing here is answered two ways.",
                     "they answer the same"):  # fmt: skip
            assert said not in page, (tab, said)


def test_the_personal_tab_shows_what_a_form_states_about_the_person(archive_index):
    """The sex and the date of birth were read only to be compared, so the two things a form says
    most plainly about a person could be seen on the card only where the documents fell out."""
    import sqlite3

    from epicrisis.index.build import index_path

    data_dir, source, labs = archive_index
    with sqlite3.connect(index_path(data_dir, source.id)) as connection:
        document = connection.execute("SELECT id FROM documents LIMIT 1").fetchone()[0]
        connection.execute(
            "INSERT INTO page_texts VALUES (?, 1, ?)", (document, "Стать: ж\nДата народження: 01.01.1970")
        )
        for name, value, unit in (("Група крові", "0 (І)", None), ("Rh", "позитивна", None),
                                  ("Зріст", "100", "см")):  # fmt: skip
            connection.execute(
                "INSERT INTO observations (document_id, page, name, value, unit) VALUES (?, 1, ?, ?, ?)",
                (document, name, value, unit),
            )
        connection.commit()

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = client.get("/card", params={"tab": "person"}).text

    assert "Sex" in page and "female" in page
    assert "Date of birth" in page and "1970-01-01" in page
    assert "Blood group" in page and "0 (І)" in page
    assert "Rh" in page and "позитивна" in page
    # A height is about the person and not about the day, and it is the one of these the index had
    # to be asked for by itself.
    assert "Height" in page and "<b>100</b>" in page and "см" in page
    # The form's own word for the fact, because "Blood group" is not what is printed on the page a
    # person is about to open to check it.
    assert "printed &ldquo;Зріст&rdquo;" in page
    assert page.count("/documents/") >= 5  # every line leads back to the page it was printed on

    # One answer is not a disagreement: these facts stand on the first tab and nothing is flagged.
    assert "Nothing here is answered two ways." in client.get("/card", params={"tab": "conflicts"}).text


def test_two_spellings_of_one_doctor_are_joined_by_a_person_and_never_by_the_program(archive_index):
    """A speciality in front of a name is not another doctor — and two doctors of one surname and
    one initial work in two clinics of every city, so the program proposes and a person decides."""
    import sqlite3

    from epicrisis.index.build import index_path

    data_dir, source, labs = archive_index
    with sqlite3.connect(index_path(data_dir, source.id)) as connection:
        documents = [row[0] for row in connection.execute("SELECT id FROM documents ORDER BY id")]
        for document, name in zip(documents, ("Нетудихата І.В", "Уролог Нетудихата І.В"), strict=False):
            connection.execute("UPDATE documents SET doctor = ? WHERE id = ?", (name, document))
        connection.commit()

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    before = client.get("/who")

    assert "Look like one and the same" in before.text  # proposed, and standing apart until joined
    assert before.text.count("Нетудихата І.В") >= 3

    joined = client.post(f"/who/{source.id}/join", data={"kind": "doctor", "one": "Нетудихата І.В",
                                            "other": "Уролог Нетудихата І.В", "label": "Нетудихата І.В"},
                         follow_redirects=True)  # fmt: skip
    assert "Joined by you" in joined.text
    assert "Look like one and the same" not in joined.text  # no longer a question

    # And the one name now answers for both spellings, wherever the archive is asked about them.
    from epicrisis.people import load, names_under
    from epicrisis.query import count_documents, open_index

    both = names_under(load(data_dir, source.id), "doctor", "Нетудихата І.В")
    assert both == ["Нетудихата І.В", "Уролог Нетудихата І.В"]
    with open_index(data_dir, source.id) as connection:
        assert count_documents(connection, doctor=both) == 2
        assert count_documents(connection, doctor=["Нетудихата І.В"]) == 1

    separated = client.post(f"/who/{source.id}/split", data={"kind": "doctor", "label": "Нетудихата І.В"},
                            follow_redirects=True)  # fmt: skip
    assert "Joined by you" not in separated.text and "Look like one and the same" in separated.text


def test_the_timeline_is_cut_by_doctor_and_by_institution_and_offers_all_or_one(archive_index):  # noqa: F811
    """Two cuts after By year, By type and By test, and inside each of them all of them or one.

    The archive has answered "/?doctor=…" since the doctor got a field of their own, and nothing on
    the timeline asked the question: the only way in was a link on the Doctors and clinics page, so
    a cut the program could take was one a person could not find. Every state of the cut is an
    address of its own, and the names offered are one line per group a person joined rather than one
    per printed spelling, because the forms write one doctor five ways.
    """
    import sqlite3

    from epicrisis.index.build import index_path

    data_dir, source, _labs = archive_index
    with sqlite3.connect(index_path(data_dir, source.id)) as connection:
        # The two that are records, one spelling each. Not by the order of the rows: which document
        # is first here is the order the folder was walked in, and the third of them is paperwork,
        # which a list of records leaves out — so the same test counted two documents on one machine
        # and one on another.
        for doc_type, name in (("lab_panel", "Нетудихата І.В"), ("discharge", "Уролог Нетудихата І.В")):
            connection.execute("UPDATE documents SET doctor = ? WHERE doc_type = ?", (name, doc_type))
        connection.commit()

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    row = client.get("/").text.split('class="views caps"')[1].split("</nav>")[0]
    places = [row.find(label) for label in ("By year", "By type", "By test", "By doctor", "By institution")]
    assert all(place > 0 for place in places), row
    assert places == sorted(places), "the two new cuts come after the three that were there"

    # The cut opens on all of them, which is the archive as it was, and that is an address a person
    # can come back to rather than a state they can only leave.
    whole = client.get("/").text
    everybody = client.get("/", params={"cut": "doctor"}).text
    assert 'name="doctor"' in everybody and "All of them" in everybody
    assert everybody.count('class="feed-row"') == whole.count('class="feed-row"')

    # And one of them narrows the documents, the footer says whose they are, and the control itself
    # stands on what the address says — the page works with nothing running in the browser.
    one = client.get("/", params={"cut": "doctor", "doctor": "Нетудихата І.В"})
    assert one.status_code == 200
    assert one.text.count('class="feed-row"') == 1
    assert 'value="Нетудихата І.В" selected' in one.text
    assert "under Нетудихата І.В" in one.text
    nobody = client.get("/", params={"cut": "doctor", "doctor": "Кривопишин В.Г"})
    assert "no documents under the name" in nobody.text  # an address nothing answers, said as that

    # Two spellings joined by a person are one line of the list, under the label they chose, and
    # that one line answers for both of them.
    joined = client.post(f"/who/{source.id}/join", data={"kind": "doctor", "one": "Нетудихата І.В",
                                            "other": "Уролог Нетудихата І.В", "label": "Нетудихата І.В"},
                         follow_redirects=True)  # fmt: skip
    assert "Joined by you" in joined.text
    offered = re.findall(r'<option value="([^"]*)"', client.get("/", params={"cut": "doctor"}).text)
    assert offered == ["", "Нетудихата І.В"], offered
    both = client.get("/", params={"cut": "doctor", "doctor": "Нетудихата І.В"}).text
    assert both.count('class="feed-row"') == 2

    # The cut beside it, by the institution the forms name. And the row of type tabs counts what the
    # cut will show rather than what the whole archive holds: every one of those links carries the
    # chosen name on, the way it carries the year.
    institutions = client.get("/", params={"cut": "institution"}).text
    assert 'name="provider"' in institutions and "Synthetic Lab" in institutions
    tabs = re.findall(r'<a href="([^"]+)"[^>]*>([^<]*?)\s*<span class="muted">\+?(\d+)</span>',
                      both.split('class="types caps"')[1].split("</div>")[0])  # fmt: skip
    for href, label, promised in tabs:
        if "paperwork" in label:  # the one tab that means "add this many", and says so with a plus
            continue
        shown = re.search(r"Showing \d+ of (\d+)", client.get(href.replace("&amp;", "&")).text)
        assert shown and int(shown.group(1)) == int(promised), f"the {label} tab promises {promised}"


def test_a_cut_the_archive_has_no_names_for_is_offered_and_inactive(archive_index):  # noqa: F811
    """"There is no institution at all here, so this should be inactive. But the option has to be
    there." A control that vanishes reads as the interface breaking; a quiet one tells the truth.

    These documents name the laboratory and not one of them names the person who signed, which is
    the ordinary shape of a folder of lab printouts — and in a real archive it is the other way
    round, every form carrying the doctor and none of them a clinic.
    """
    data_dir, _source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = client.get("/").text
    row = page.split('class="views caps"')[1].split("</nav>")[0]

    assert "By doctor" in row, "the cut is offered even where no document answers it"
    assert '<span aria-disabled="true"' in row and "By doctor</span>" in row
    assert "cut=doctor" not in row, "an inactive cut is not a link"
    assert "No document of this archive names a doctor" in page  # and one line says why it is empty
    assert "cut=institution" in row, "the cut that has names is a link"

    # Asked for by hand, it is still not a control: there is nothing in this archive to choose from.
    typed = client.get("/", params={"cut": "doctor"})
    assert typed.status_code == 200 and 'name="doctor"' not in typed.text


def test_the_timeline_heading_counts_the_documents_under_it_and_not_the_archive(archive_index):  # noqa: F811
    """The archive's own count and span stood at the top whatever narrowed the page.

    A cut to one laboratory read "41 documents · 2013-03-06 – 2025-09-21" above ten documents of
    2019 to 2021, and not one date in the heading belonged to anything on the page. The footer
    said "Showing 10 of 10 records under …", in small print at the other end — which is the
    seventh entry of the constitution the wrong way round: of the two counts that disagreed, the
    large one at the top of the page was the untrue one.
    """
    import html
    import re

    data_dir, source, _labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    def heading(**params):
        page = client.get("/", params=params).text
        head = re.search(r'<div class="timeline-head">(.*?)</p>', page, re.S).group(1)
        foot = re.search(r'class="caps muted">Showing (.*?)</span>', page, re.S)
        return (re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", head))).strip(),
                re.sub(r"\s+", " ", html.unescape(foot.group(1))).strip() if foot else "")  # fmt: skip

    # One year of the three documents: the count and both dates are of that year.
    head, foot = heading(year=A_DAY_FOR_AN_ILLUSTRATION.year)
    assert "1 document · 2011-07-09 – 2011-07-09" in head and foot.startswith("1 of 1")
    # And the archive's own numbers are not dropped — a heading that quietly follows a filter is a
    # second way to be wrong about the same thing. They are said in the line under it.
    assert "this archive holds 3 in all, 2003-03-12 – 2011-07-09" in head

    # The one kind of document the feed leaves out of "records" was the same defect standing
    # still: with nothing chosen at all the page shows two and the heading said three.
    head, foot = heading()
    assert "2 documents · 2003-03-12 – 2011-07-09" in head and foot.startswith("2 of 2 records")
    assert "this archive holds 3 in all" in head
    # Added back, the two agree and there is nothing left to name.
    head, foot = heading(paperwork="1")
    assert "3 documents" in head and foot.startswith("3 of 3 records and paperwork")
    assert "this archive holds" not in head

    # The documents with no date are the one page where the span is not a span.
    head, _ = heading(undated="1")
    assert "0 documents" in head and "none of these carries a date at all" in head

    # By type draws only the documents that carry a date, and counts those.
    head, _ = heading(view="lanes")
    assert "2 documents · 2003-03-12 – 2011-07-09" in head and "this archive holds 3 in all" in head

    # By test narrows no documents at all — the notice above it says so in words — so the heading
    # keeps the archive's own, and names no difference, because there is none.
    head, _ = heading(view="indicators")
    assert "3 documents · 2003-03-12 – 2011-07-09" in head and "this archive holds" not in head


def test_the_empty_tab_of_who_says_where_the_names_are(archive_index):
    """The menu item reads "Doctors and clinics" and opens on the doctors, which can be nought.

    A folder of laboratory printouts names the laboratory on every page and the person who signed
    on none — all three demo archives are that shape, and so was the archive this was found on. A
    person pressing the menu landed on "No field of any document here names a doctor yet" over an empty list,
    with every name in the archive one tab away and nothing on the page saying so.

    Said rather than mended by opening whichever tab has something: /who?kind=doctor has to go on
    meaning the doctors, and that explicit address is the one a bookmark, the timeline's
    "Spellings" link and this page's own redirect after a join all use.
    """
    import sqlite3

    from epicrisis.index.build import index_path

    data_dir, source, labs = archive_index

    def name_them(provider, doctor):
        with sqlite3.connect(index_path(data_dir, source.id)) as connection:
            connection.execute("UPDATE documents SET provider = ?, doctor = ?", (provider, doctor))

    name_them("Synthetic Laboratory", None)
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    empty = client.get("/who")

    assert empty.status_code == 200
    assert "No field of any document here names a doctor yet." in empty.text
    assert "Every name on these documents is an institution" in empty.text
    assert '<a href="/who?kind=institution">Institutions</a>' in empty.text
    # The address asked for is the tab drawn: the way out is a sentence, not a different page.
    assert '<a href="/who?kind=doctor" aria-current="page">' in empty.text

    # And the sentence stands nowhere it would not be true: not on the tab that holds the names,
    # and not on a page where neither tab holds any.
    full = client.get("/who", params={"kind": "institution"})
    assert "Synthetic Laboratory" in full.text
    assert "Every name on these documents is" not in full.text

    name_them(None, None)
    neither = client.get("/who")
    assert "No field of any document here names a doctor yet." in neither.text
    assert "Every name on these documents is" not in neither.text


def test_a_cut_with_one_name_in_it_says_what_the_two_sides_of_it_are(archive_index):
    """It read "1 name on these documents: all of them, or one of them", which is one thing twice.

    Over a box holding one real option, and an archive with one polyclinic in it is an ordinary
    archive. The cut does something there: every document of the archive, against only the ones
    that carry the name — not the same set unless every document names it — so the tab stays live
    and the line says which two sides those are. With two names the old line was right and stands.
    """
    import sqlite3

    from epicrisis.index.build import index_path

    data_dir, source, labs = archive_index

    def institutions(*named):
        with sqlite3.connect(index_path(data_dir, source.id)) as connection:
            for row, name in enumerate(named):
                connection.execute("UPDATE documents SET provider = ? WHERE rowid = ?", (name, row + 1))

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    institutions("Synthetic Laboratory", None, None)
    alone = client.get("/", params={"cut": "institution"}).text
    assert "1 name on these documents: every document, or only the ones that name it" in alone
    assert "all of them, or one of them" not in alone, "the line that says the same thing twice"
    # Live, not disabled: there is a cut to make, and the box is the place it is made.
    assert 'aria-disabled="true" title="Nothing to choose from in this archive">By institution' not in alone
    assert '<select id="whose" name="provider">' in alone

    institutions("Synthetic Laboratory", "Second Synthetic Laboratory", None)
    two = client.get("/", params={"cut": "institution"}).text
    assert "2 names on these documents: all of them, or one of them" in two


def test_the_crumbs_of_the_picker_do_not_offer_a_press_that_can_only_be_refused(client, tmp_path, monkeypatch):
    """Every crumb was a button up to "/", and every one above the roots answered with a refusal.

    The refusal is a good one — it names the boundary and prints the command that adds a disk of
    scans — but a row in which all but the last two or three presses fail is a trail of broken
    links, and "Up one level" on the topmost allowed folder was the same press again. Out of
    bounds is now not a button at all, and the parent that cannot be opened is not offered.

    What this must not do is take the refusal away: it is what somebody who types a path into the
    box reads, and the dialog reaches it that way, so the last part of this holds that it is still
    there, in full, with the command in it.
    """
    from epicrisis.sources import SourceRegistry
    from epicrisis.web.browse import BrowseError, list_folder

    monkeypatch.delenv("EPICRISIS_ARCHIVE_ROOT", raising=False)
    home = tmp_path / "home"
    (home / "scans" / "2004").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    registry = SourceRegistry(home / "instance" / "data")
    roots = registry.roots()
    assert home.resolve() in roots

    deep = list_folder(str(home / "scans" / "2004"), added_paths=set(), roots=roots,
                       data_dir=registry.data_dir)  # fmt: skip
    offered = {crumb["name"]: crumb["inside"] for crumb in deep["crumbs"]}
    assert offered["/"] is False and offered[home.name] is True
    assert offered["scans"] is True and offered["2004"] is True
    # Every crumb that is offered leads somewhere this picker will actually open.
    for crumb in deep["crumbs"]:
        if crumb["inside"]:
            assert list_folder(crumb["path"], added_paths=set(), roots=roots)["path"] == crumb["path"]

    # And "Up one level" stops at the top of what is allowed rather than pointing out of it.
    assert deep["parent"] == str(home / "scans")
    top = list_folder(str(home), added_paths=set(), roots=roots, data_dir=registry.data_dir)
    assert top["parent"] is None, "the folder above the root is not a place to go"

    # The refusal itself, reached the way a person reaches it: by typing a path out.
    with pytest.raises(BrowseError) as refused:
        list_folder(str(tmp_path), added_paths=set(), roots=roots, data_dir=registry.data_dir)
    assert "Folders are chosen from" in str(refused.value) and "sources add" in str(refused.value)

    # And the dialog draws such a crumb as text rather than as a button. The drawing is in the
    # page's own script, so it is held here as the two lines that do it, and the rule that keeps
    # the row from moving when one of its buttons stops being one.
    page = client.get("/status").text
    assert "if (!crumb.inside) {" in page
    assert 'crumbs.append(el("span", "outside", crumb.name));' in page
    style = (Path(__file__).resolve().parent.parent / "epicrisis" / "web" / "static" / "app.css").read_text(encoding="utf-8")
    assert ".crumbs .outside {" in style


def test_every_kind_of_document_has_words_of_its_own():
    """A kind offered to the model and nowhere worded would reach a page as it left the model.

    The list and the words lived in two files and only one page asked for the words, so this is
    the guard that keeps them one thing: a kind added to the list without a line beside it fails
    here rather than appearing on somebody's timeline as `id_document`.
    """
    assert sorted(doc_types.IN_WORDS) == sorted(doc_types.DOC_TYPES)
    assert all(doc_types.in_words(kind) != kind for kind in doc_types.DOC_TYPES)
    # An index built by an older version can hold a kind this one never heard of. The page prints
    # what is stored, because a readable surprise beats an empty cell.
    assert doc_types.in_words("a_kind_from_another_year") == "a_kind_from_another_year"
    assert doc_types.in_words(None) is None and doc_types.in_words("") == ""
    # And one place holds them. They were a second dictionary in the web module, `DOC_TYPE_LABELS`,
    # which the templates knew nothing about: a page that did not import it printed the name the
    # model returned, and six of seven did not.
    from epicrisis.web import documents as documents_page

    assert not hasattr(documents_page, "DOC_TYPE_LABELS"), "two dictionaries of words again"


def test_no_page_captions_a_document_with_the_name_a_model_returned(archive_index):  # noqa: F811
    """One path through the dashboard spoke two languages, and the words existed all along.

    `DOC_TYPE_LABELS` sat in web/documents.py and was asked for in exactly one place, so the feed
    said `lab_panel`, the card it led to said "Lab results", the link back from a scan said "back
    to Lab results", and the search results said `lab_panel` twenty-two times on one page. A
    person looking for a blood test could not tell that any of those named the same thing.

    Every place a kind of document is captioned is read here. Addresses, form fields and the
    tools over the network are left out on purpose: there the name the model returned is the
    right answer, and a search-and-replace that changed those would have broken every link.
    """
    import sqlite3

    from epicrisis.index.build import index_path

    data_dir, source, labs = archive_index
    # Two documents made copies of one another by hand: the block of copies on To check is one of
    # the places that printed the raw name, and the checks of this archive find no copy of itself.
    writable = sqlite3.connect(index_path(data_dir, source.id))
    writable.row_factory = sqlite3.Row
    with writable:
        two = writable.execute("SELECT id FROM documents ORDER BY id LIMIT 2").fetchall()
        writable.execute("UPDATE documents SET copy_group = 1, primary_copy = (id = ?) WHERE id IN (?, ?)",
                         (two[0]["id"], two[0]["id"], two[1]["id"]))  # fmt: skip
    writable.close()

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    with open_index(data_dir, source.id) as connection:
        held = list(query_index.overview(connection)["types"])
    assert held, "no documents: this archive cannot show the defect"
    one = held[0]

    # Address, and the pattern that captures every caption of a kind of document on it.
    captions = [
        ("/", r'class="what"><b>([^<]*)</b><span class="caps muted">([^<&]*)'),  # a row of the feed
        ("/", r'class="types caps">(.*?)</div>'),  # the row of type tabs, read whole below
        ("/?paperwork=1", r'class="what"><b>([^<]*)</b><span class="caps muted">([^<&]*)'),
        (f"/?doc_type={one}", r'class="caps muted">Showing \d+ of \d+ ([^<]*?)(?:</span>| in )'),
        ("/?doc_type=blank", r'no documents of the kind <span class="mono">([^<]*)<'),
        ("/?view=lanes", r'class="name">([^<]*)<'),  # a lane
        ("/?view=lanes", r'<option value="[^"]+"[^>]*>([^<]*)<'),  # the chooser
        ("/?view=lanes&doc_type=blank", r'no documents of the kind <span class="mono">([^<]*)<'),
        ("/documents", r'class="doc-link" href="[^"]*">([^<]*)<'),
        (f"/search?q={quote(SYNTHETIC_TEXT.split()[0])}", r'<b>([^<]*)</b>\s*<span class="caps muted">([^<&]*)'),
        ("/review", r'class="copy-why caps muted">([^<&]*)'),  # the block of copies
        ("/review", r'class="doc-link" href="[^"]*">([^<]*)<'),
        (f"/documents/{source.id}/{labs}/1", r'<dt class="caps">Type</dt><dd>([^<]*)<'),  # the card
        (f"/sources/{source.id}/files/{labs}/pages/1", r"back to ([^<,]*)"),  # the way back from a scan
    ]
    worded = set(doc_types.IN_WORDS.values())
    seen = set()
    for address, pattern in captions:
        answered = client.get(address)
        assert answered.status_code == 200, address
        found = re.findall(pattern, answered.text, flags=re.S)
        assert found, f"{address}: nothing captioned, the pattern no longer reads this page"
        for caught in found:
            for caption in (caught,) if isinstance(caught, str) else caught:
                for word in re.split(r"\s{2,}|\n|&middot;|<[^>]*>", caption):
                    word = word.strip()
                    assert word not in doc_types.DOC_TYPES, f"{address}: {word!r}"
                    seen |= {word} & worded
    # And the words are the ones from the one place that holds them, not an empty cell where a
    # caption used to be: the kinds this archive holds are all accounted for.
    assert seen >= {doc_types.in_words(kind) for kind in held}, seen

    # The name the model returned is still what a page links and posts with. A kind reworded must
    # not move a document, so the address of a narrowed page carries the stored name unchanged.
    narrowed = client.get(f"/?view=lanes&doc_type={one}").text
    assert f'<option value="{one}" selected>' in narrowed and f"doc_type={one}" in client.get("/").text


def test_the_indicators_page_and_its_list_read_in_the_order_a_person_looks(tmp_path):
    """Every label of the archive, in the list under the Find box and in the groups beside it.

    Ordered by a casefold, every label beginning with і, ї, є, ґ or ё stood below every label
    beginning with я — the bottom of a list five hundred groups long. Both orders are on this one
    page, so both are read here. The four labels are invented, in meaningless syllables, and were
    looked for in each archive's index first.
    """
    from epicrisis import indicators as store
    from epicrisis.index.build import build_index
    from epicrisis.sources import SourceRegistry

    data_dir = tmp_path / "data"
    folder = tmp_path / "archive"
    folder.mkdir()
    registry = SourceRegistry(data_dir)
    source = registry.add(str(folder), "Vera Lindqvist")
    for label in ("Яшмірелін", "Іврамелін", "Ґормелін", "Авмурелін"):
        store.upsert(data_dir, None, label, [label.casefold()], "approved")
    build_index(data_dir, [source])
    page = TestClient(create_app(data_dir, background_jobs=False),
                      base_url="http://localhost:8050").get("/indicators").text  # fmt: skip

    in_order = ["Авмурелін", "Ґормелін", "Іврамелін", "Яшмірелін"]
    listed = re.search(r'<datalist id="every-indicator">(.*?)</datalist>', page, re.S).group(1)
    assert re.findall(r">([^<>]+)</option>", listed) == in_order
    # And the groups themselves, where none of them has more values than another: each label
    # stands several times in its own row, so it is the first standing of each that is the order.
    rows = page[:page.index('<datalist id="every-indicator">')]
    assert list(dict.fromkeys(re.findall(r"|".join(in_order), rows))) == in_order


def test_a_page_in_english_says_what_tongue_its_content_is_printed_in(archive_index):  # noqa: F811
    """<html lang="en"> was the whole of what this interface said about language.

    It is true of the page and false of what stands in it: most of this archive is Russian,
    Ukrainian and Greek. A browser reads lang to choose a fallback face for a character the
    page's own font has not got, and to decide how to read a line aloud, so every printed name,
    institution and paragraph of text was being offered to both as English.

    The shell stays lang="en" — the headings and the sentences this program writes are English.
    The language goes on the elements carrying one document's printed text, where classify read
    one off the page, and nowhere else: a wrong lang is worse than none, because a browser acts
    on it.
    """
    from epicrisis import indicators

    data_dir, source, labs = archive_index
    indicators.upsert(data_dir, None, "Cystatin C", ["Цистатин С"], status="approved")
    build_index(data_dir, [source])
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    card = client.get(f"/documents/{source.id}/{labs}/1").text
    assert '<html lang="en">' in card  # the page is in English and goes on saying so
    assert card.count('lang="uk"') >= 5  # the title, the printed meta fields, the rows, the text
    assert '<pre class="full-text" lang="uk">' in card
    assert 'Institution as printed</dt><dd lang="uk">' in card

    # The listing's institution column is the one classify read off the page, so give it one.
    classified = data_dir / "sources" / source.id / "classify.jsonl"
    classified.write_text("".join(
        json.dumps({**json.loads(line), "provider_on_page": "Synthetic Lab"}) + "\n"
        for line in classified.read_text(encoding="utf-8").splitlines()
    ), encoding="utf-8")  # fmt: skip
    listing = client.get("/documents").text
    assert '<span lang="uk">Synthetic Lab</span>' in listing

    chart = client.get(f"/tests/{card.split('href=\"/tests/')[1].split('\"')[0]}").text
    assert '<span lang="uk">Цистатин С</span>' in chart

    # And nothing is invented where the page never said. Classify writes a two-letter code; a
    # document whose language is missing or is not one gets no attribute at all.
    from epicrisis.web.documents import said_in

    assert said_in("uk") == ' lang="uk"' and said_in("el") == ' lang="el"'
    for nothing in (None, "", "ukrainian", "UK", "u", "uk-UA", 7, '"><script>'):
        assert said_in(nothing) == "", nothing


def test_what_the_model_had_read_stands_on_the_row_a_person_corrected(archive_index):  # noqa: F811
    """It stood inside the form, behind a summary reading "Correct this line".

    So a row said "corrected" and nothing on the page said what it had been, nor that the reading
    it replaced was kept at all, nor where the way back to it was. The eighth entry of the
    constitution keeps the version a write replaces; keeping it where the page never mentions it
    is keeping it for nobody — and on a phone the row's own title=, which carries the model's
    snippet, is not shown either.
    """
    data_dir, source, labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    where = f"/documents/{source.id}/{labs}/1"
    before = client.get(where).text
    key = before.split('name="key" value="')[1].split('"')[0]
    typed = {"key": key, "name": "Цистатин С", "value": "8,5", "unit": "мг/л", "reference": "0,5-1,0", "flag": ""}

    assert client.post(f"{where}/value", data=typed, follow_redirects=False).status_code == 303

    page = client.get(where).text

    # The value a person typed, the badge, and what the model had read: all three on the page, and
    # the field named, because "0,85" on its own does not say which of five columns it stood in.
    assert "8,5" in page and '<span class="caps signal">corrected</span>' in page
    assert 'class="caps was-read-as">As the model read it: value <b>0,85</b>' in page
    assert "Correct this line" in page and "puts it back" in page
    assert page.count("was-read-as") == 1  # one corrected row, one line, not a column on every row
    # And only the fields that differ. The form posts all five whichever one was retyped, so
    # naming every one of them would say "as the model read it" over four nobody touched.
    assert "name <b>" not in page and "range <b>" not in page

    # Only the printed fields a correction touched. The same form carries the material a person
    # set by hand, which is nothing a model ever read, and it used to render as "— ".
    with_material = client.post(f"{where}/value", data={**typed, "material": "blood"}, follow_redirects=False)
    assert with_material.status_code == 303
    again = client.get(where).text
    assert "As the model read it: value <b>0,85</b>" in again and "<b>nothing</b>" not in again


def test_a_choice_of_the_lock_this_program_cannot_use_is_refused_by_name(client, data_dir):
    """The two choices of the lock, refused in silence under a page saying it had saved.

    Both refusals are sentences written for a person — "a lock opens a conversation or the server",
    "a window runs from a minute to a week" — and both sat inside a suppress(ValueError), after
    which this page went on to say "Saved. Nothing on the page was different from what was already
    stored". That is false about the page and false about the storing, with the cause in hand and
    thrown away: the seventh entry of the constitution says an error with no cause is a defect, and
    that a refusal names what is safe and what puts it right.

    Neither is reachable from the page as it is drawn: what a code opens is a select of two values,
    and how long it lasts is an input carrying min and max. That is exactly why it is tested here
    rather than left alone — what a browser will not send is not what this server will not be sent,
    and the same press carries the thresholds, which are reachable and were refused the same way.
    """
    from epicrisis import settings

    def press(**typed) -> str:
        answer = client.post("/settings", data={
            "mode": "as_printed", "tab": "lock", "shown": ["mcp_lock"],
            "mcp_lock_scope": typed.get("scope", settings.mcp_lock_scope(data_dir)),
            "mcp_lock_minutes": typed.get("minutes", settings.mcp_lock_minutes(data_dir)),
        }, follow_redirects=False)  # fmt: skip
        assert answer.status_code == 303
        return client.get(answer.headers["location"]).text

    stood_at = settings.mcp_lock_minutes(data_dir)
    page = press(minutes=0)
    assert "Nothing on the page was different" not in page, "the page was different and was refused"
    assert "a window runs from a minute to a week" in page, "the reason the write was refused"
    assert f"still stands at {stood_at} minutes" in page, "and what it stands at instead"
    assert settings.mcp_lock_minutes(data_dir) == stood_at, "nothing was stored, as the page says"

    opens = settings.mcp_lock_scope(data_dir)
    page = press(scope="everything that is open anywhere")
    assert "Nothing on the page was different" not in page
    assert "a lock opens a conversation or the server" in page
    assert settings.mcp_lock_scope(data_dir) == opens

    # And a choice this program can use is still stored, and still said, in the same press.
    page = press(minutes=stood_at + 30)
    assert "how long a code lasts" in page and settings.mcp_lock_minutes(data_dir) == stood_at + 30


def test_an_engine_this_instance_cannot_use_is_refused_by_name(client, data_dir):
    """The last of the three swallowed refusals on this page, and the same false sentence over it.

    `engines.set_engine` refuses an engine nobody built and one this instance cannot answer with,
    and both refusals are written for a person: "no such engine: X" and "<engine> cannot answer
    yet: <what is missing>". Under a suppress(ValueError) the page replied "Saved. Nothing on the
    page was different from what was already stored" to a press it had just refused.

    The comment over that suppress gave the reason to answer rather than to drop: "a form can
    always be made to say something the page did not". The page does print "Not ready" beside the
    radio it draws disabled, but that is the state of a thing and not an answer to a press.
    """
    from epicrisis import engines

    stood_at = engines.engine_name(data_dir)
    answer = client.post("/settings", data={"mode": "as_printed", "tab": "answers",
                                            "engine": "nothing-of-that-name"},
                         follow_redirects=False)  # fmt: skip
    assert answer.status_code == 303
    page = client.get(answer.headers["location"]).text

    assert "Nothing on the page was different" not in page, "the page was different and was refused"
    assert "no such engine" in page, "the reason the write was refused"
    assert engines.engine_name(data_dir) == stood_at, "nothing was stored, as the page says"


def test_one_page_read_twice_is_the_same_page(client, data_dir):
    """Two readings of one address differ in nothing, so a ruler that compares them can be trusted.

    The ids of the controls that point at their own explanation came from a counter made once per
    server, so the same page read twice differed in exactly those numbers and nothing else. No
    person was ever harmed by it: an id has to be unique inside its page, and these were. The cost
    was to the sixth entry of the constitution, which asks a change to prove it moved nothing — and
    the proof is a comparison of pages, byte for byte, which this made noisy by construction. In
    two days it bought three investigations of shifts that were not shifts, the last of them a
    report of two entries swapping places on a page where nothing had swapped.

    Numbered from one on every page now, which is all an id ever had to be.
    """
    import re

    # The settings page, because that is where the explanations are: the macro that asks for an
    # id is imported there and in the bar of every page.
    first = client.get("/settings")
    second = client.get("/settings")

    assert first.status_code == second.status_code == 200
    assert first.text == second.text, "the same page read twice is not the same bytes"
    # And the numbering really is there to be gone wrong about: a page with no ids at all would
    # pass the line above while proving nothing.
    ids = re.findall(r'id="(explains-\d+)"', first.text)
    assert ids, "no numbered ids on this page, so this test is about nothing"
    assert len(ids) == len(set(ids)), "two controls of one page share an id"
    assert "explains-1" in ids, f"numbering does not start at one: {sorted(ids)[:3]}"


def test_the_count_of_things_to_check_is_of_the_blocks_under_it():
    """"N of M documents to check" is of what the page draws, and it was of the file of findings.

    The decision asked on its own, because it is one answer with two callers: `review_view` makes
    the blocks and `_from_the_index` in app.py then changes them, and the number has to come from
    whichever of the two spoke last. Three things it has to get right, and each was wrong in its
    own way — two findings on one document are one document, a document the page cannot draw is
    not on it, and a copy group drawn in its own block is work on this page even where nothing
    else was found about its members.
    """
    from epicrisis.web.documents import how_many_documents_to_check

    two_checks_one_document = {"checks": [
        {"code": "number_differs", "entries": [{"sha256": "a" * 64, "pages": "1"}]},
        {"code": "comparator_missing", "entries": [{"sha256": "a" * 64, "pages": "1"}]},
    ]}  # fmt: skip
    assert how_many_documents_to_check(two_checks_one_document) == 1
    # The back of a two-sheet form is another document of the same file, and counted apart.
    two_documents_one_file = {"checks": [{"code": "number_differs", "entries": [
        {"sha256": "a" * 64, "pages": "1"}, {"sha256": "a" * 64, "pages": "2,3"},
    ]}]}  # fmt: skip
    assert how_many_documents_to_check(two_documents_one_file) == 2
    # And the copies block, whose members the check blocks no longer hold: possible_copy is taken
    # out of them once the index has grouped the copies, and nine documents of one real archive
    # carry no other finding at all. Counted off the block that does draw them.
    with_a_group = {"checks": [{"code": "number_differs", "entries": [{"sha256": "a" * 64, "pages": "1"}]}],
                    "copy_groups": [{"members": [{"file_sha256": "b" * 64, "pages": [4]},
                                                 {"file_sha256": "c" * 64, "pages": [7, 8]}]}]}  # fmt: skip
    assert how_many_documents_to_check(with_a_group) == 3
    # One document in both is one document: a copy with a finding of its own is not two.
    assert how_many_documents_to_check({**with_a_group, "copy_groups": [
        {"members": [{"file_sha256": "a" * 64, "pages": [1]}]}]}) == 1  # fmt: skip


def test_a_finding_the_page_cannot_draw_is_not_counted_in_its_heading(archive_index):  # noqa: F811
    """A finding whose document has no row is dropped on `and row`, and was counted anyway.

    The shape has to be invented: nothing is dropped on the three archives read on 4 October
    2026, because their findings were written against the grouping they still have. It arises
    whenever they were not — the checks are a file on disk and the classification moves under it,
    which the page itself reports as "Data changed since" — and then the heading promises
    documents that are nowhere on the page.
    """
    import html as html_module

    from epicrisis import layout
    from epicrisis.validate import load_validation
    from epicrisis.web.documents import review_view

    data_dir, source, _labs = archive_index
    output = data_dir / "sources" / source.id
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    before = review_view(source, output)["documents_with_findings"]
    checked = review_view(source, output)["documents_checked"]
    assert before and checked, "this archive has no findings, so this test is about nothing"

    # A finding against pages nothing here groups that way: the checks were run before the
    # classification was read again, which is the one state the page already has a word for.
    stored = load_validation(output)
    stored["documents"].append({"file_sha256": "d" * 64, "pages": [41, 42],
                                "findings": {"number_differs": 2}, "copies": []})  # fmt: skip
    (output / layout.VALIDATION).write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")

    assert len(load_validation(output)["documents"]) == before + 1, "the shape did not land"
    assert review_view(source, output)["documents_with_findings"] == before
    page = re.sub(r"\s+", " ", html_module.unescape(re.sub(r"<[^>]+>", " ", client.get("/review").text)))
    assert f"{before} of {checked} documents to check" in page
    assert f"{before + 1} of {checked} documents to check" not in page


def test_a_rule_with_no_switch_is_described_by_its_own_line_and_not_by_the_shared_one(client, archive, data_dir):
    """Five rules share one sentence about why there is no switch, and it said what four find.

    "What this finds is a page of a document that came back with nothing on it" is true of the
    four that report an empty page and false of the fifth, which is about a stored value that is
    nowhere in the text of the page it came from. A person reading the fifth was told a page came
    back empty where that is not what happened.

    So the shared sentence says only what they have in common — this program reporting on its own
    reading — and what each one finds is its own summary, drawn right above it, out of its own
    file. One description, one place.
    """
    add(client, archive)
    from epicrisis import rules

    stays_on = [rule for rule in rules.load(data_dir) if rule.stays_on]
    assert len(stays_on) == 5, "the set changed; this test is about the sentence they share"

    page = client.get("/settings?tab=rules").text

    assert "came back with nothing on it" not in page, (
        "the shared sentence describes what four of the five find, over a fifth that finds "
        "something else")  # fmt: skip
    assert page.count("Always on.") == len(stays_on), "one such line per rule with no switch"
    for rule in stays_on:
        # Each one's own words about what it looks at, which is where that belongs.
        assert rule.summary.split(".")[0][:40] in page, f"{rule.id} is drawn without its own line"
        assert f'name="rule_on" value="{rule.id}"' not in page, f"{rule.id} still has a box"
