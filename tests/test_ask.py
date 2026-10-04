"""Read-only questions to the index, the MCP tools and the Ask page. Synthetic data only."""

import asyncio
import json
import time
from contextlib import closing
from datetime import date

import pytest
from fastapi.testclient import TestClient

from epicrisis import ask as ask_module
from epicrisis import settings as settings_module
from epicrisis import query
from epicrisis.consent import record_consent
from epicrisis.corrections import set_document_date
from epicrisis.extract.run import extract_source, load_extracted, write_document
from epicrisis.index.build import build_index, index_path
from epicrisis.mcp_server import build_server
from epicrisis.validate import validate_source
from epicrisis import layout
from epicrisis.classify.report import latest_pages
from epicrisis.extract.run import document_refs, extracted_path
from epicrisis.records import append_line, now as records_now, read_records
from epicrisis.web.app import create_app
from conftest import AS_A_FORM_PRINTS_IT, A_DAY_FOR_AN_ILLUSTRATION
from test_extract import FakeExtractBackend, setup  # noqa: F401
from test_inventory import make_text_pdf


@pytest.fixture
def archive_index(setup):  # noqa: F811
    data_dir, source, output, records = setup
    extract_source(data_dir, source, FakeExtractBackend())
    labs = records["labs.pdf"]["sha256"]
    document = load_extracted(output / "extracted", labs)["documents"][0]
    template = document["observations"][0]
    document["observations"] = [
        dict(template, name_as_printed="Цистатин С", value_as_printed="0,85", unit_as_printed="мг/л", reference_as_printed="0,5-1,0"),
        dict(template, name_as_printed="ШКФ (CKD-EPI)", value_as_printed="101", unit_as_printed="мл/хв", reference_as_printed=None),
    ]
    document["page_texts"] = [{"page": 1, "text": "Цистатин С 0,85 мг/л 0,5-1,0\nШКФ (CKD-EPI) 101 мл/хв"}]
    write_document(output / "extracted", labs, document)
    set_document_date(output, labs, [1, 2], A_DAY_FOR_AN_ILLUSTRATION)
    validate_source(output)
    build_index(data_dir, [source])
    return data_dir, source, labs


def test_queries_answer_with_values_as_printed_and_their_source(archive_index):
    data_dir, source, labs = archive_index
    connection = query.open_index(data_dir, None)

    assert query.overview(connection)["documents"] == 3
    found = query.search(connection, "ЦИСТАТИН")
    assert [item["file_id"] for item in found] == [labs[:8]] and "Цистатин С 0,85" in found[0]["snippet"]
    history = query.values(connection, "цистатин")
    assert [(item["value"], item["unit"], item["reference"], item["date"]) for item in history] == [("0,85", "мг/л", "0,5-1,0", A_DAY_FOR_AN_ILLUSTRATION.isoformat())]
    assert query.values(connection, "шкф") == [] and len(query.values(connection, "шкф", include_derived=True)) == 1
    names = query.value_names(connection, "цистат")
    assert (names[0]["name"], names[0]["times"], names[0]["first_date"]) == ("Цистатин С", 1, A_DAY_FOR_AN_ILLUSTRATION.isoformat())
    document = query.document(connection, file_id=labs[:8])
    assert document["card_url"] == f"/documents/{source.id}/{labs}/1" and len(document["values"]) == 2
    assert document["original_pages_url"][0].endswith(f"/files/{labs}/pages/1")
    assert [item["file_id"] for item in query.timeline(connection, since=f"{A_DAY_FOR_AN_ILLUSTRATION.year}-01-01")] == [labs[:8]]
    assert query.to_check(connection)[0]["to_check"][0]["code"]
    connection.close()


def test_mcp_tools_are_read_only_and_answer(archive_index):
    data_dir, _, labs = archive_index
    server = build_server(data_dir)

    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    assert names == {
        "archive_overview", "search_documents", "list_documents", "value_names", "value_history",
        "get_document", "documents_to_check", "list_indicators", "flagged_values",
        "unlock", "lock_archive",
    }  # fmt: skip
    result = asyncio.run(server.call_tool("value_history", {"name": "цистатин"}))
    assert "0,85" in str(result) and labs[:8] in str(result)

    # Nothing is cut in silence: a page says how many there are in all and where the next one starts.
    listing = asyncio.run(server.call_tool("list_indicators", {"limit": 1}))
    assert '"total"' in str(listing) and '"offset"' in str(listing)
    # A tool with an output schema has to return structured content too, or a client that checks
    # the schema refuses the answer. The rows ride under "result", where such a client looks.
    assert set(listing.structured_content) >= {"kind", "result", "returned", "offset"}
    assert listing.structured_content["kind"] == "indicators"
    document = asyncio.run(server.call_tool("get_document", {"file_id": labs[:8], "limit": 1}))
    assert '"counts"' in str(document)

    # Comparing a value with its printed range is interpretation, and this instance shows as printed.
    refused = asyncio.run(server.call_tool("flagged_values", {"compare_with_printed_range": True}))
    assert "does not compare" in str(refused)
    from epicrisis.settings import set_answer_mode

    # The middle mode lets the model read the values; the application still does not compare them.
    set_answer_mode(data_dir, "with_meaning")
    assert "does not compare" in str(asyncio.run(server.call_tool("flagged_values", {"compare_with_printed_range": True})))

    set_answer_mode(data_dir, "direct")
    allowed = asyncio.run(server.call_tool("flagged_values", {"compare_with_printed_range": True}))
    assert "does not compare" not in str(allowed)


def test_ask_records_the_question_steps_and_answer(archive_index, monkeypatch, tmp_path):
    data_dir, source, _ = archive_index

    def fake_stream(data_dir, prompt, mode="as_printed", pinned_to=None):
        assert "How did cystatin change?" in prompt and mode == "as_printed"
        # Whose archive the tools are given, rather than left to read whichever is showing: an
        # answer takes tens of seconds, and the dashboard can be switched to somebody else in
        # another tab while it is being written.
        assert pinned_to == source.id
        yield {"kind": "tool", "step": {"tool": "value_history", "input": {"name": "цистатин"}}}
        yield {"kind": "answer", "text": f"0,85 мг/л on {AS_A_FORM_PRINTS_IT}, file 43cdf91f."}

    monkeypatch.setattr(ask_module, "_stream", fake_stream)
    chat = ask_module.new_chat(data_dir, source)
    # The background thread does nothing here; the answer is written in this thread instead.
    ask_module.ask(data_dir, chat["id"], "How did cystatin change?", run=lambda *args: None)
    ask_module.answer(data_dir, chat["id"])

    stored = ask_module.load_chat(data_dir, chat["id"])
    answer = stored["messages"][-1]
    assert (answer["state"], answer["steps"][0]["tool"]) == ("done", "value_history")
    assert "0,85 мг/л" in answer["text"] and stored["title"] == "How did cystatin change?"
    assert [item["id"] for item in ask_module.list_chats(data_dir)] == [chat["id"]]


def test_an_answer_records_and_shows_where_its_wait_went(archive_index, monkeypatch):
    """Ninety-two seconds, and the only number was ninety-two.

    A conversation recorded `seconds` for the whole answer and a list of steps with no clock on
    them, so "why was that so slow" could be answered only by asking the same question over again
    with every event timestamped — a second run on the owner's own subscription, and more of his
    waiting, to find out about the first. That run said it: of 65.30 s, the thirteen calls to the
    archive were 0.22 s, and the model held 99.4 %.

    The stream here is made of sleeps rather than a model, so the three numbers are known before
    they are measured: a tenth of a second in the archive on each call, three tenths of thinking
    between them, four tenths writing the answer. What must not come back is the archive's time
    counted as the model's, which is the whole point of separating them.
    """
    data_dir, source, _ = archive_index

    def fake_stream(data_dir, prompt, mode="as_printed", pinned_to=None):
        yield {"kind": "ready"}
        time.sleep(0.2)  # the model deciding what to ask first
        yield {"kind": "tool", "step": {"tool": "archive_overview", "input": {}}}
        time.sleep(0.1)  # the archive answering
        yield {"kind": "answered"}
        time.sleep(0.3)  # the model thinking between rounds
        yield {"kind": "tool", "step": {"tool": "value_history", "input": {"name": "цистатин"}}}
        time.sleep(0.1)
        yield {"kind": "answered"}
        time.sleep(0.4)  # the model writing the answer
        yield {"kind": "answer", "text": f"0,85 мг/л on {AS_A_FORM_PRINTS_IT}, file 43cdf91f."}

    monkeypatch.setattr(ask_module, "_stream", fake_stream)
    settings_module.set_ask_enabled(data_dir, True)
    record_consent(data_dir, "claude-code-subscription")  # by the one writer of it, so a version bump reaches here
    chat = ask_module.new_chat(data_dir, source)
    ask_module.ask(data_dir, chat["id"], "How did cystatin change?", run=lambda *args: None)
    ask_module.answer(data_dir, chat["id"])

    answer = ask_module.load_chat(data_dir, chat["id"])["messages"][-1]
    first, second = answer["steps"]
    # When the model asked, what the archive took, and what the model spent before the next thing
    # it did. The windows are wide because a loaded machine sleeps longer than it is asked to;
    # what they cannot stand is one of these numbers being another one of them.
    assert 0.15 <= first["asked_after"] <= 1.0 and first["asked_after"] < second["asked_after"]
    assert 0.08 <= first["archive_seconds"] <= 0.25 and 0.08 <= second["archive_seconds"] <= 0.25
    assert 0.25 <= first["then_seconds"] <= 1.0
    assert 0.3 <= answer["writing_seconds"] <= 1.2 and second["then_seconds"] == answer["writing_seconds"]
    # The two tenths the archive spent are not among the nine the model did, and the three parts
    # are a division of the one number printed beside them rather than three roundings of their
    # own: a count that disagrees with another count on the same page is a defect.
    assert 0.16 <= answer["archive_seconds"] <= 0.5
    assert answer["model_seconds"] > 4 * answer["archive_seconds"]
    whole = answer["archive_seconds"] + answer["model_seconds"] + answer["rest_seconds"]
    assert abs(whole - answer["seconds"]) <= 0.5 and answer["rest_seconds"] >= 0

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = client.get(f"/ask/{chat['id']}").text
    assert f"of it the archive {answer['archive_seconds']} s" in page
    assert f"the model {answer['model_seconds']} s" in page
    assert f"{answer['writing_seconds']} s of that writing this answer" in page
    assert f"the archive {first['archive_seconds']} s" in page and f"{first['asked_after']} s in" in page


def test_a_conversation_from_before_the_clock_still_draws(archive_index):
    """The live instance holds one, and a page that needs a number it has not got draws nothing.

    These are a person's own questions about their own health: a conversation written before the
    steps were timed has to open exactly as it did, with the one number it recorded.
    """
    data_dir, source, _ = archive_index
    settings_module.set_ask_enabled(data_dir, True)
    record_consent(data_dir, "claude-code-subscription")
    before = {
        "id": "a1b2c3d4e5f6", "title": "As it was written then", "created_at": records_now(),
        "updated_at": records_now(), "archive": source.whose, "archive_id": source.id,
        "messages": [
            {"role": "person", "text": "What changed?", "at": records_now()},
            {"role": "claude", "text": "0,85 мг/л, file 43cdf91f.", "at": records_now(), "state": "done",
             "mode": "as_printed", "seconds": 92,
             "steps": [{"tool": "archive_overview", "input": {}},
                       {"tool": "get_document", "input": {"file_id": "43cdf91f"}}]},
        ],
    }  # fmt: skip
    (ask_module.chats_dir(data_dir) / "a1b2c3d4e5f6.json").write_text(json.dumps(before), encoding="utf-8")

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = client.get("/ask/a1b2c3d4e5f6")

    assert page.status_code == 200
    assert "Answered in 92 seconds" in page.text
    assert "2 queries to the archive" in page.text and "get_document(file_id=43cdf91f)" in page.text
    # Nothing is invented for it: no breakdown of a wait nobody measured, and no bare "0.0 s".
    assert "of it the archive" not in page.text and "s in &middot;" not in page.text


def test_ask_page_is_off_until_turned_on(archive_index, monkeypatch):
    data_dir, _, _ = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    page = client.get("/ask").text
    assert "Answering questions is turned off" in page
    assert client.post("/ask", data={"question": "hi"}).status_code == 403

    settings_module.set_ask_enabled(data_dir, True)
    assert "Model processing is not confirmed" in client.get("/ask").text
    record_consent(data_dir, "claude-code-subscription")  # by the one writer of it, so a version bump reaches here
    started = client.post("/ask", data={"question": "What is in the archive?"}, follow_redirects=False)
    assert started.status_code == 303 and started.headers["location"].startswith("/ask/")
    chat_id = started.headers["location"].rsplit("/", 1)[1]
    assert client.get(f"/ask/{chat_id}/state").json() == {"running": False, "messages": []}
    assert client.get("/ask/unknown").status_code == 404


def test_settings_switch_what_answers_may_contain(archive_index):
    from epicrisis.ask import system_prompt
    from epicrisis.settings import answer_mode

    data_dir, _, _ = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    assert answer_mode(data_dir) == "as_printed"
    assert "never diagnose" in system_prompt("as_printed") and "no diagnosis" in system_prompt("with_meaning")
    assert "whether a value is normal" not in system_prompt("with_meaning")
    assert "sets no limits on that" in system_prompt("direct") and "never diagnose" not in system_prompt("direct")
    # The freest mode still holds the model to the records: quoting, provenance, never from memory.
    assert "exactly as printed" in system_prompt("direct") and "Never answer from memory" in system_prompt("direct")

    saved = client.post("/settings", data={"ask_page": "on", "mode": "with_meaning", "shown": "ask_page"},
                        follow_redirects=False)  # fmt: skip
    assert saved.status_code == 303
    assert answer_mode(data_dir) == "with_meaning"
    # The address the page itself sends a person to, not an invented one: the message behind that
    # key is read once, so a page asked for with any other word says nothing about a press at all.
    page = client.get(saved.headers["location"]).text
    # And the banner says what was stored. It used to be asked for at an invented address, where the
    # key resolved to nothing and the page answered "Saved. Nothing on the page was different from
    # what was already stored" — which passed this assertion while stating the opposite of the truth.
    assert "Saved:" in page and "Nothing on the page was different" not in page
    assert 'value="with_meaning" checked' in page.replace('" checked', '" checked')
    assert "not a medical device" in page

    # Bringing a test to one scale is a rule of its own, off unless asked for.
    from epicrisis import rules
    from epicrisis.settings import rule_on

    to_scale = rules.load(data_dir).get("one_scale_for_a_test")
    assert rule_on(data_dir, to_scale) is False
    client.post("/settings", data={"ask_page": "on", "mode": "with_meaning", "rule_on": "one_scale_for_a_test",
                                   "shown": ["one_scale_for_a_test", "ask_page"]})  # fmt: skip
    assert rule_on(data_dir, to_scale) is True
    assert 'value="one_scale_for_a_test" checked' in client.get("/settings").text

    client.post("/settings", data={"ask_page": "on", "mode": "direct", "shown": "ask_page"})
    assert answer_mode(data_dir) == "direct" and 'value="direct" checked' in client.get("/settings").text

    client.post("/settings", data={"ask_page": "", "mode": "as_printed", "shown": "ask_page"})
    assert answer_mode(data_dir) == "as_printed" and "Answering questions is turned off" in client.get("/ask").text


def test_answers_render_as_markdown_without_raw_html(archive_index, monkeypatch):
    data_dir, _, _ = archive_index

    def fake_stream(data_dir, prompt, mode="as_printed", pinned_to=None):
        yield {"kind": "answer", "text": f"| Date | Value |\n|---|---|\n| {AS_A_FORM_PRINTS_IT} | 0,85 |\n\n<script>alert(1)</script>"}

    monkeypatch.setattr(ask_module, "_stream", fake_stream)
    settings_module.set_ask_enabled(data_dir, True)
    record_consent(data_dir, "claude-code-subscription")  # by the one writer of it, so a version bump reaches here
    chat = ask_module.new_chat(data_dir)
    ask_module.ask(data_dir, chat["id"], "table please", run=lambda *args: None)
    ask_module.answer(data_dir, chat["id"])

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    page = client.get(f"/ask/{chat['id']}").text

    assert "<table>" in page and "<td>0,85</td>" in page
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    assert "Copy answer" in page and "class=\"btn small copy\"" in page


def test_a_question_carries_the_chat_only_when_the_box_is_ticked(archive_index, monkeypatch):
    data_dir, _, _ = archive_index

    def finish(data_dir, chat_id):  # the model is not called here; the question is simply answered
        chat = ask_module.load_chat(data_dir, chat_id)
        chat["messages"][-1].update(state="done", text="An answer.")
        ask_module._save(data_dir, chat)

    def answered(chat_id: str) -> dict:
        """The chat once the thread that answers it has finished writing.

        A question is answered in a thread, so reading the file the moment the request returns
        is a race with that thread — and one that is lost about one run in three hundred.
        """
        for _ in range(500):
            chat = ask_module.load_chat(data_dir, chat_id)
            if chat and not ask_module.running(chat):
                return chat
            time.sleep(0.01)
        raise AssertionError(f"the answer to {chat_id} never finished")

    monkeypatch.setattr(ask_module, "answer", finish)
    settings_module.set_ask_enabled(data_dir, True)
    record_consent(data_dir, "claude-code-subscription")  # by the one writer of it, so a version bump reaches here
    client = TestClient(create_app(data_dir), base_url="http://localhost:8050")

    started = client.post("/ask", data={"question": "First question"}, follow_redirects=False)
    first = started.headers["location"].rsplit("/", 1)[1]
    answered(first)
    client.post(f"/ask/{first}", data={"question": "And the unit?", "continue": "on"}, follow_redirects=False)
    assert len(answered(first)["messages"]) == 4
    page = client.get(f"/ask/{first}").text
    assert "Continue this conversation" in page and "The 2 earlier questions" in page

    apart = client.post(f"/ask/{first}", data={"question": "Something else"}, follow_redirects=False)
    other = apart.headers["location"].rsplit("/", 1)[1]
    assert other != first
    assert len(answered(first)["messages"]) == 4
    assert answered(other)["messages"][0]["text"] == "Something else"

    assert "Delete chat" in client.get(f"/ask/{other}").text
    removed = client.post(f"/ask/{other}/delete", follow_redirects=False)
    assert removed.status_code == 303 and removed.headers["location"] == "/ask"
    assert [item["id"] for item in ask_module.list_chats(data_dir)] == [first]
    assert client.post(f"/ask/{other}/delete").status_code == 404


def test_over_http_the_archive_answers_only_behind_the_secret(archive_index):
    from epicrisis.mcp_server import http_app, new_path_secret

    data_dir, _, labs = archive_index
    secret = new_path_secret()
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "value_history", "arguments": {"name": "цистатин"}}}  # fmt: skip
    headers = {"accept": "application/json, text/event-stream", "content-type": "application/json"}

    # The app keeps a task group alive, so it is started as a context manager, as a server would.
    with TestClient(http_app(data_dir, secret), base_url="http://localhost:8051", client=("127.0.0.1", 9000)) as client:
        assert client.post("/mcp", json=call, headers=headers).status_code == 404
        assert client.post(f"/mcp/{'0' * 64}", json=call, headers=headers).status_code == 404
        assert client.get("/").status_code == 404

        answer = client.post(f"/mcp/{secret}", json=call, headers=headers)
        assert answer.status_code == 200 and "0,85" in answer.text and labs[:8] in answer.text

    with pytest.raises(ValueError):
        http_app(data_dir, "too-short")


def test_the_timeline_shows_the_archive_four_ways_and_search_finds_a_document(archive_index):
    data_dir, _, labs = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    feed = client.get("/").text
    assert "Timeline" in feed and "2003" in feed and labs[:8] in feed
    assert "/documents/" in feed and "Search" in feed

    strip = client.get("/?year=2003")
    assert strip.status_code == 200 and "show every year" in strip.text

    assert "lab_panel" in client.get("/?view=lanes").text
    by_test = client.get("/?view=indicators")
    assert by_test.status_code == 200
    assert client.get("/?view=indicators&material=urine").status_code == 200

    # The old dashboard keeps working, at its own address.
    assert "Sources" in client.get("/status").text or "source" in client.get("/status").text

    # A page that shows less than it holds says so, and the undated documents are never hidden.
    # "carries" where there is one of them: the line agrees with its number now, as a dozen lines
    # of the same templates already did.
    assert "Showing" in feed and "no date at all" in feed
    assert client.get("/", params={"skip": 120}).status_code == 200
    assert client.get("/", params={"undated": 1}).status_code == 200
    # The view by test shows a few tests and offers the rest, rather than everything at once.
    by_test = client.get("/", params={"view": "indicators"}).text
    assert "BY TEST" in by_test.upper()
    assert "every test" not in by_test or "show every test" in by_test.casefold()

    # Searched for a word of the page itself: what is indexed for a page that went as text is the
    # file's own text, not a copy of it written out by a model.
    found = client.get("/search", params={"q": "hemoglobin"})
    assert found.status_code == 200 and labs[:8] in found.text
    assert "Type a word" in client.get("/search").text
    # An empty answer is not a dead end and is not "the archive does not hold it": it says what was
    # looked through, and points at the tests, the printed names and the page that takes a question
    # in a person's own words. Somebody who typed "sugar" for what a laboratory prints as "Glucose"
    # used to be told "try a shorter word, or another language", did both, and got the same answer.
    nothing = client.get("/search", params={"q": "zzzqqq"}).text
    assert "No document of this archive holds that among the words printed on it" in nothing
    assert "not the same as the archive not holding the thing" in nothing
    assert "tests this archive has" in nothing and 'href="/indicators"' in nothing


def test_a_question_in_one_language_finds_the_spellings_of_another(archive_index):
    """An empty answer once became "the archive lacks this", and a recommendation was built on it."""
    import asyncio
    import json
    import sqlite3

    data_dir, source, _ = archive_index
    writable = sqlite3.connect(index_path(data_dir, source.id))
    with writable:
        # One indicator over two alphabets, as the archive really holds them.
        writable.execute(
            "INSERT INTO indicators (id, label, status, names) VALUES (?, ?, ?, ?)",
            ("cystatin-c", "Cystatin C", "approved", json.dumps(["цистатин с", "cistatina c"])),
        )
        writable.execute("UPDATE observations SET indicator_id = 'cystatin-c' WHERE name LIKE 'Цистатин%'")
    writable.close()
    server = build_server(data_dir)

    spanish = asyncio.run(server.call_tool("value_history", {"name": "cistatina"})).structured_content
    russian = asyncio.run(server.call_tool("value_history", {"name": "цистатин"})).structured_content

    # The Spanish spelling is printed nowhere in this archive, and still it finds the values.
    assert spanish["found"] == russian["found"] >= 1
    assert [row["value"] for row in spanish["result"]] == [row["value"] for row in russian["result"]]
    assert spanish["searched_every_spelling_of"][0]["label"] == "Cystatin C"

    # And nothing found says so, with the shape of the corpus beside it.
    nothing = asyncio.run(server.call_tool("value_history", {"name": "zzzz"})).structured_content
    assert nothing["found"] == 0 and "not evidence" in nothing["this_is_not_evidence_of_absence"]
    assert sum(nothing["documents_by_language"].values()) >= 1


def test_two_archives_never_answer_for_one_another(archive_index, tmp_path):
    """The point of owners: a question about one person cannot reach another person's values."""
    import asyncio

    from epicrisis.index.build import build_index, index_path
    from epicrisis.query import open_index
    from epicrisis.sources import SourceError, SourceRegistry

    data_dir, mine, _ = archive_index
    registry = SourceRegistry(data_dir)
    registry.set_owner(mine.id, "Vera Lindqvist")

    theirs_folder = tmp_path / "archive-of-another"
    (theirs_folder / "2019").mkdir(parents=True)
    make_text_pdf(theirs_folder / "2019" / "labs.pdf", ["Haemoglobin 999 g/L"])
    theirs = registry.add(str(theirs_folder), "Another Person")

    # Each archive has its own index file, and one holds nothing of the other's.
    build_index(data_dir, [theirs])
    assert index_path(data_dir, mine.id) != index_path(data_dir, theirs.id)
    with closing(open_index(data_dir, theirs.id)) as connection:
        assert query.overview(connection)["documents"] == 0  # nothing extracted for them yet
    with closing(open_index(data_dir, mine.id)) as connection:
        assert query.overview(connection)["documents"] >= 1

    # A folder inside another owner's folder would give the same documents two owners.
    with pytest.raises(SourceError, match="contain one another"):
        registry.add(str(theirs_folder / "2019"), "A Third")

    # The tools serve whoever is open, and say whose records they are answering with.
    registry.set_active(theirs.id)
    empty = asyncio.run(build_server(data_dir).call_tool("archive_overview", {})).structured_content
    registry.set_active(mine.id)
    mine_overview = asyncio.run(build_server(data_dir).call_tool("archive_overview", {})).structured_content
    assert empty["archive_of"] == "Another Person" and mine_overview["archive_of"] == "Vera Lindqvist"
    assert empty["documents"] == 0 and mine_overview["documents"] >= 1


def test_an_instance_from_before_owners_still_opens(archive_index):
    """Data written by an older version has to keep working: nobody migrates a personal archive."""
    from epicrisis.index.build import index_path
    from epicrisis.query import open_index
    from epicrisis.sources import SourceRegistry

    data_dir, source, _ = archive_index
    # An index built before archives had owners sat in one file with no id in its name.
    index_path(data_dir, source.id).rename(index_path(data_dir))
    registry = SourceRegistry(data_dir)

    with closing(open_index(data_dir, source.id)) as connection:
        assert query.overview(connection)["documents"] >= 1
    # And chats written then, with no archive named in them, belong to the archive that is open.
    assert registry.active().id == source.id


def test_a_question_that_cannot_reach_the_model_says_so(archive_index, monkeypatch):
    """When the model cannot be reached, the person sees why, not an answer that never arrives."""
    from epicrisis import ask as module

    data_dir, source, _ = archive_index
    settings_module.set_ask_enabled(data_dir, True)

    def refuse(*args, **kwargs):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(module, "_stream", refuse)
    # The archive itself, not a name invented here: a conversation naming an archive this instance
    # does not hold is refused before any model is reached, and then this test would be about that
    # refusal instead of about the one it is named after.
    chat = module.new_chat(data_dir, source)
    # The question is put in a thread in real use; here it is answered on the spot, to be read.
    module.ask(data_dir, chat["id"], "How did cystatin change?", run=lambda *args: None)
    module.answer(data_dir, chat["id"])

    answered = module.load_chat(data_dir, chat["id"])["messages"][-1]
    assert answered["state"] == "failed" and "not found on this server" in answered["error"]
    assert answered["text"] == ""  # nothing invented in place of an answer


def test_a_model_that_stops_halfway_leaves_the_answer_marked_failed(archive_index, monkeypatch):
    from epicrisis import ask as module

    data_dir, source, _ = archive_index
    settings_module.set_ask_enabled(data_dir, True)

    def half(*args, **kwargs):
        yield {"kind": "tool", "step": {"tool": "value_history", "input": {}}}
        yield {"kind": "error", "text": "usage_limit"}

    monkeypatch.setattr(module, "_stream", half)
    chat = module.new_chat(data_dir, source)
    module.ask(data_dir, chat["id"], "How did cystatin change?", run=lambda *args: None)
    module.answer(data_dir, chat["id"])

    answered = module.load_chat(data_dir, chat["id"])["messages"][-1]
    assert answered["state"] == "failed" and answered["error"] == "usage_limit"
    assert len(answered["steps"]) == 1  # what it did before stopping is kept


def test_the_back_of_a_form_keeps_the_material_of_its_front():
    """A urinalysis printed on two sheets: the back is headed only with its section's name."""
    from epicrisis.index.build import material_of

    sediment = {"name_as_printed": "Лейкоцити", "table_as_printed": "Мікроскопічне дослідження",
                "provenance": {"page": 2, "snippet": "Лейкоцити 2-4 в п/з"}}  # fmt: skip
    back = {"title_as_printed": "Мікроскопічне дослідження"}

    assert material_of(sediment, back) is None  # read alone, the back says nothing
    assert material_of(sediment, back, "АНАЛІЗ СЕЧІ ЗАГАЛЬНИЙ") == "urine"

    # Only a section heading borrows. A form headed with a material of its own keeps that one,
    # whatever it follows.
    blood = {"title_as_printed": "БІОХІМІЧНИЙ АНАЛІЗ КРОВІ"}
    assert material_of(sediment, blood, "АНАЛІЗ СЕЧІ ЗАГАЛЬНИЙ") == "blood"
    assert material_of(sediment, {"title_as_printed": "РЕЗУЛЬТАТИ"}, "АНАЛІЗ СЕЧІ ЗАГАЛЬНИЙ") is None
    # And the page before has to say a material at all.
    assert material_of(sediment, back, "РЕЗУЛЬТАТИ ДОСЛІДЖЕНЬ") is None
    # What the observation itself says still comes first.
    stool = {"name_as_printed": "Лейкоцити", "table_as_printed": "Аналіз калу", "provenance": {"page": 2}}
    assert material_of(stool, back, "АНАЛІЗ СЕЧІ ЗАГАЛЬНИЙ") == "stool"


def test_a_heading_printed_in_spaced_letters_still_says_what_it_says():
    """Forms typeset letter by letter: the word is there, only the spaces are in the way."""
    from epicrisis.index.build import material_of, unspaced

    assert unspaced("U R I N E   A N A L Y S I S") == "URINE   ANALYSIS"
    assert unspaced("АНАЛІЗ СЕЧІ ЗАГАЛЬНИЙ") == "АНАЛІЗ СЕЧІ ЗАГАЛЬНИЙ"  # ordinary text is left alone

    observation = {"name_as_printed": "Leucocytes", "provenance": {"page": 1}}
    assert material_of(observation, {"title_as_printed": "U R I N E   A N A L Y S I S"}) == "urine"
    assert material_of(observation, {"title_as_printed": "Γ Ε Ν Ι Κ Η  Ε Ξ Ε Τ Α Σ Η  Ο Υ Ρ Ω Ν"}) == "urine"
    assert material_of(observation, {"title_as_printed": "Full Blood Count (FBC)"}) == "blood"
    assert material_of(observation, {"title_as_printed": "R E S U L T S"}) is None


def test_a_conversation_belongs_to_one_archive_and_opens_for_no_other(archive_index, tmp_path):
    """The leak this closes: a chat stayed open, and readable, when the archive was switched.

    The list of chats was filtered by whose archive they are about. A chat fetched by its own id
    was not, so another person's conversation opened by its address alone — and stayed on the
    screen, with what was said in it, when the archive was switched underneath.
    """
    from fastapi.testclient import TestClient

    from epicrisis.ask import _save, load_chat, new_chat
    from epicrisis.settings import set_ask_enabled
    from epicrisis.consent import record_consent
    from epicrisis.sources import SourceRegistry
    from epicrisis.web.app import create_app

    data_dir, mine, _ = archive_index
    registry = SourceRegistry(data_dir)
    registry.set_owner(mine.id, "Vera Lindqvist")
    theirs_folder = tmp_path / "another-archive"
    (theirs_folder / "2019").mkdir(parents=True)
    make_text_pdf(theirs_folder / "2019" / "labs.pdf", ["Haemoglobin 150 g/L"])
    theirs = registry.add(str(theirs_folder), "Anders Lindqvist")

    chat = new_chat(data_dir, "Vera Lindqvist")
    chat["title"] = "About a creatinine of mine"
    chat["messages"] = [{"role": "user", "text": "a question only I asked", "state": "done"}]
    _save(data_dir, chat)

    set_ask_enabled(data_dir, True)
    record_consent(data_dir, "claude-code-subscription")
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    registry.set_active(mine.id)
    assert client.get(f"/ask/{chat['id']}").status_code == 200
    assert "a question only I asked" in client.get(f"/ask/{chat['id']}").text

    # Under the other archive it is not found, and neither is what was said in it.
    registry.set_active(theirs.id)
    for path in (f"/ask/{chat['id']}", f"/ask/{chat['id']}/state"):
        answer = client.get(path)
        assert answer.status_code == 404, path
        assert "a question only I asked" not in answer.text, path
    assert "About a creatinine of mine" not in client.get("/ask").text

    # It cannot be continued or deleted from there either.
    assert client.post(f"/ask/{chat['id']}/delete", follow_redirects=False).status_code == 404
    assert load_chat(data_dir, chat["id"], "Vera Lindqvist") is not None  # still there, untouched
    assert load_chat(data_dir, chat["id"], "Anders Lindqvist") is None

    # And switching archive while it is open does not carry it along.
    moved = client.post("/owner", data={"source": mine.id, "back": f"/ask/{chat['id']}"}, follow_redirects=False)
    assert moved.headers["location"] == "/ask"


def test_a_chat_started_on_the_web_belongs_to_the_archive_it_was_asked_about(tmp_path, monkeypatch):
    """The route, not only the store: a chat created with no owner answered for every archive."""
    from epicrisis.ask import list_chats, load_chat
    from epicrisis.settings import set_ask_enabled
    from epicrisis.consent import record_consent
    from epicrisis.sources import SourceRegistry

    data_dir = tmp_path / "data"
    mine, theirs = tmp_path / "mine", tmp_path / "theirs"
    for folder in (mine, theirs):
        folder.mkdir()
    registry = SourceRegistry(data_dir)
    first = registry.add(str(mine), "Vera Lindqvist")
    registry.add(str(theirs), "Anders Lindqvist")
    registry.set_active(first.id)
    set_ask_enabled(data_dir, True)
    record_consent(data_dir, "claude-code-subscription")

    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")
    started = client.post("/ask", data={"question": "How is my creatinine?"}, follow_redirects=False)
    chat_id = started.headers["location"].rsplit("/", 1)[-1]

    mine_archive, theirs_archive = registry.list()
    assert [chat["id"] for chat in list_chats(data_dir, mine_archive)] == [chat_id]
    assert list_chats(data_dir, theirs_archive) == []
    assert load_chat(data_dir, chat_id, theirs_archive) is None

    # Renaming the owner does not orphan the conversation: the archive is what it belongs to.
    registry.set_owner(mine_archive.id, "Vera Lindqvist-Morales")
    assert load_chat(data_dir, chat_id, registry.get(mine_archive.id)) is not None

    # And from the other archive the conversation is not there to read, to poll or to delete.
    client.post("/owner", data={"source": registry.list()[1].id, "back": "/ask"}, follow_redirects=False)
    assert client.get(f"/ask/{chat_id}").status_code == 404
    assert client.get(f"/ask/{chat_id}/state").status_code == 404
    assert client.post(f"/ask/{chat_id}/delete", follow_redirects=False).status_code == 404
    assert "How is my creatinine?" not in client.get("/ask").text
    # The page a person is left looking at knows what that 404 means and says the way back. It
    # used to knock on every two seconds for ever, saying "answering" over an answer that was
    # being written for somebody who had walked away from the page.
    page = client.get("/ask").text
    assert "answer.status === 404" in page
    assert "this conversation is not on this page any more" in page
    assert "choose that person again under" in page and "Archive of" in page


def test_a_chat_from_before_owners_belongs_to_the_archive_that_was_there_then(tmp_path):
    """Its archive was never written down, and there was only one archive to write."""
    import json

    from epicrisis.ask import chats_dir, list_chats, load_chat, new_chat
    from epicrisis.sources import SourceRegistry

    data_dir = tmp_path / "data"
    first, second = tmp_path / "first", tmp_path / "second"
    for folder in (first, second):
        folder.mkdir()
    registry = SourceRegistry(data_dir)
    oldest = registry.add(str(first), "Vera Lindqvist")
    newer = registry.add(str(second), "Anders Lindqvist")

    old = new_chat(data_dir)
    path = chats_dir(data_dir) / f"{old['id']}.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "archive": ""}), encoding="utf-8")

    assert load_chat(data_dir, old["id"], oldest) is not None
    assert load_chat(data_dir, old["id"], newer) is None
    assert [chat["id"] for chat in list_chats(data_dir, newer)] == []

    # And a chat that recorded only a name still answers for the archive of that name.
    by_name = new_chat(data_dir)
    path = chats_dir(data_dir) / f"{by_name['id']}.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "archive": "Anders Lindqvist",
                                "archive_id": ""}), encoding="utf-8")  # fmt: skip
    assert load_chat(data_dir, by_name["id"], newer) is not None
    assert load_chat(data_dir, by_name["id"], oldest) is None


def test_a_question_that_cannot_reach_the_model_says_why():
    """"FILENOTFOUNDERROR" on a page is a thing to guess at; a sentence is a thing to fix."""
    from epicrisis.ask import why_it_failed

    said = why_it_failed(FileNotFoundError(2, "No such file or directory", "claude"))
    assert "not found on this server" in said and "claude" in said
    assert "cannot reach it" in why_it_failed(PermissionError(13, "Permission denied", "claude"))
    assert why_it_failed(ValueError("whatever the model said")) == "ValueError"


def test_the_ask_page_says_what_this_instance_actually_allows(tmp_path):
    """It said the strictest of the three modes whichever was chosen.

    So an owner who had deliberately taken the limits off showed this page to somebody, who read
    "it does not say whether a value is normal" above an answer that did exactly that — and
    concluded that this is how the program works, rather than that its owner had allowed it.
    """
    from pathlib import Path

    from jinja2 import Environment, FileSystemLoader

    here = Path(__file__).parent.parent / "epicrisis" / "web" / "templates"
    lead = (here / "ask.html").read_text(encoding="utf-8").split('<p class="lead caps">')[1].split("</p>")[0]
    draw = Environment(loader=FileSystemLoader(str(here))).from_string('<p>' + lead + "</p>")

    strict = draw.render(mode="as_printed")
    assert "does not say whether a value is normal" in strict

    middle = draw.render(mode="with_meaning")
    assert "read the values as well as show them" in middle
    assert "does not say whether a value is normal" not in middle

    off = draw.render(mode="direct")
    assert "limits on what the model may say are off" in off
    assert "does not say whether a value is normal" not in off and "not a medical device" in off


def test_the_three_tools_that_cut_in_silence_now_say_how_many_there_are(archive_index):
    """"found" was the length of the page, not the number of matches.

    Twenty-two matching documents answered as twenty, in an answer shaped exactly like the answer to
    "that is all there is" — and a model then wrote about the archive from part of it, with no way to
    ask for the rest. The count was already in this program's reach: the search page of the dashboard
    has been showing it all along.
    """
    data_dir, source, labs = archive_index
    server = build_server(data_dir)

    def call(tool, **arguments):
        return asyncio.run(server.call_tool(tool, arguments)).structured_content

    # Two documents of this archive hold the word, and a page holding one of them says both that
    # there are two and where the second begins. That is the whole finding: the answer used to be
    # the same either way.
    whole = call("search_documents", query_text="Synthetic", limit=200)
    one = call("search_documents", query_text="Synthetic", limit=1)
    assert whole["total"] == whole["returned"] == 2
    assert one["total"] == 2 and one["returned"] == 1 and one["offset"] == 0 and one["next_offset"] == 1
    # And the next page is the other document, so the offset is real rather than decoration.
    following = call("search_documents", query_text="Synthetic", limit=1, offset=1)
    assert following["result"] != one["result"] and following["offset"] == 1
    assert "next_offset" not in following  # the last page says it is the last

    names = call("value_names", limit=1)
    assert names["kind"] == "printed_names" and names["total"] == 9 and names["returned"] == 1
    assert names["next_offset"] == 1
    assert call("value_names", limit=1, offset=1)["result"] != names["result"]

    to_check = call("documents_to_check", limit=1)
    assert to_check["total"] >= 1 and to_check["returned"] <= to_check["total"]

    # Nothing matching at all is still its own answer, and not a page of nought.
    nothing = asyncio.run(server.call_tool("search_documents", {"query_text": "никогдатакогонебыло"}))
    assert "not evidence" in str(nothing)


def test_every_tool_that_reads_the_archive_says_what_it_does_not_do(archive_index):
    """The settings page promises it of all of them, and one of nine said it.

    "An assistant you open this archive to over the network answers under its own rules, not these —
    what holds there is that its tools only read, and that each one says what it does not do." That
    sentence stands over the three modes, and it was the whole of what holds over the network. A
    negative about its own boundary was in exactly one description of nine: flagged_values.
    """
    import asyncio

    data_dir, _source, _labs = archive_index
    server = build_server(data_dir)

    reading_tools = {"archive_overview", "search_documents", "list_documents", "value_names",
                     "value_history", "get_document", "documents_to_check", "list_indicators",
                     "flagged_values"}  # fmt: skip
    said = {tool.name: tool.description or "" for tool in asyncio.run(server.list_tools())}

    assert reading_tools <= set(said)
    for name in sorted(reading_tools):
        # A sentence about what this tool is not for, in its own words rather than a formula: the
        # point is that a model reading the description learns the boundary, not that a word matches.
        boundary = said[name].lower()
        assert any(word in boundary for word in
                   ("never", "not ", "neither", "nothing", "only:")), f"{name} says nothing it does not do"  # fmt: skip


def test_a_page_of_marked_values_says_how_many_there_are_in_all(archive_index, setup):  # noqa: F811
    """The fourth tool that cut in silence, and this one cut nothing and said it had.

    Six values came back to a caller that had asked for a hundred, under "next_offset": 6 — because
    this answer carried no total and a page with any rows at all was given a next page. A model
    reading that asks the same question again with a larger limit, which is one of the two repeated
    calls in a measured run of ten: a round of its own time and the person's for nothing. The
    number was in reach all along — the query reads every matching row and then cuts a page out of
    them.
    """
    data_dir, source, labs = archive_index
    _data_dir, _source, output, _records = setup
    document = load_extracted(output / "extracted", labs)["documents"][0]
    template = document["observations"][0]
    # Two values the laboratory itself marked, which is the only kind this tool returns.
    document["observations"] = [
        dict(template, name_as_printed="Цистатин С", value_as_printed="0,85", unit_as_printed="мг/л",
             reference_as_printed="0,5-1,0", flag_as_printed="H"),
        dict(template, name_as_printed="Гемоглобін", value_as_printed="131", unit_as_printed="г/л",
             reference_as_printed="130-160", flag_as_printed="*"),
    ]  # fmt: skip
    write_document(output / "extracted", labs, document)
    validate_source(output)
    build_index(data_dir, [source])
    server = build_server(data_dir)

    def call(**arguments):
        return asyncio.run(server.call_tool("flagged_values", arguments)).structured_content

    whole = call(limit=100)
    assert whole["returned"] == whole["total"] == 2
    assert "next_offset" not in whole, "a page holding all of them does not offer another"
    one = call(limit=1)
    assert one["returned"] == 1 and one["total"] == 2 and one["next_offset"] == 1
    assert call(limit=1, offset=1)["result"] != one["result"], "and the next page is the other value"


def test_a_document_cut_into_pages_says_how_to_ask_for_the_rest(archive_index):
    """The same document, the same part, the same page of it, asked for twice.

    "more" names a next_offset under each part that was cut, and offset applies to every part asked
    for at once — so a caller that asks for the cut part by itself and leaves the offset behind is
    handed the page it already has. Nothing in the answer or the description said how the two fit
    together, and two of ten calls in a measured run were a document asked for again.
    """
    data_dir, _source, labs = archive_index
    server = build_server(data_dir)

    cut = asyncio.run(server.call_tool("get_document", {"file_id": labs[:8], "parts": ["values"], "limit": 1})).structured_content["result"]
    assert cut["more"]["values"]["next_offset"] == 1
    assert "offset and limit apply to every part asked for" in cut["how_to_ask_for_the_rest"]
    assert "parts=['sections'], offset=<its next_offset>" in cut["how_to_ask_for_the_rest"]

    whole = asyncio.run(server.call_tool("get_document", {"file_id": labs[:8], "parts": ["values"], "limit": 200})).structured_content["result"]
    assert "more" not in whole and "how_to_ask_for_the_rest" not in whole, "nothing was cut, so there is nothing to say"


def test_a_tool_does_not_offer_what_this_instance_will_refuse(archive_index):
    """"Where the instance allows it" is true of the program and useless to the caller.

    On an instance that does not allow it, a model read that sentence in the description, asked for
    the comparison, was refused and asked again without it: one round of its thinking and one of
    the person's waiting for a parameter that was never going to answer. The refusal inside the
    tool stays where it is; the description no longer invites the call.
    """
    data_dir, _source, _labs = archive_index

    def description(name: str) -> str:
        return {tool.name: tool.description or "" for tool in asyncio.run(build_server(data_dir).list_tools())}[name]

    assert "refused on this instance" in description("flagged_values")
    settings_module.set_answer_mode(data_dir, "with_meaning")
    assert "refused on this instance" in description("flagged_values")

    # And where the owner has taken every limit off, it is offered and it answers.
    settings_module.set_answer_mode(data_dir, "direct")
    said = description("flagged_values")
    assert "refused on this instance" not in said and "instead compares each value" in said
    allowed = asyncio.run(build_server(data_dir).call_tool("flagged_values", {"compare_with_printed_range": True}))
    assert allowed.structured_content["compared_with_printed_range"] is True


def test_the_question_carries_what_this_archive_holds_and_nothing_of_another(archive_index, tmp_path, monkeypatch):
    """archive_overview was the first call of almost every conversation, and it never changes.

    345 characters of counts, a round of the model's time to ask for them and another to read them:
    4.5 s of a measured 37.2 s answer before anything about the question had been asked. So the
    counts go out with the question — of the archive the conversation is pinned to, by its id, and
    of no other. One person's counts in a question about another person's records is the one
    failure that cannot be undone by an apology.
    """
    from epicrisis.index.build import build_index
    from epicrisis.sources import SourceRegistry

    data_dir, mine, _labs = archive_index
    registry = SourceRegistry(data_dir)
    registry.set_owner(mine.id, "Vera Lindqvist")
    theirs_folder = tmp_path / "archive-of-another"
    (theirs_folder / "2019").mkdir(parents=True)
    make_text_pdf(theirs_folder / "2019" / "labs.pdf", ["Haemoglobin 131 g/L"])
    theirs = registry.add(str(theirs_folder), "Anders Lindqvist")
    build_index(data_dir, [theirs])  # added and indexed, and nothing read out of it yet

    hers = ask_module.what_the_archive_holds(data_dir, mine.id)
    his = ask_module.what_the_archive_holds(data_dir, theirs.id)
    assert "Vera Lindqvist" in hers and "Anders Lindqvist" not in hers
    assert "Anders Lindqvist" in his and "Vera Lindqvist" not in his
    assert "0 documents" in his and "0 documents" not in hers
    # An archive indexed before anything in it was read has no dates at all, and "dated None to
    # None" is how a model comes to say an archive begins in 1970.
    assert "dated" not in his and "dated" in hers
    assert "None" not in his

    seen = {}

    def fake_stream(data_dir, prompt, mode="as_printed", pinned_to=None):
        seen["prompt"] = prompt
        yield {"kind": "answer", "text": "Nothing in it yet."}

    monkeypatch.setattr(ask_module, "_stream", fake_stream)
    chat = ask_module.new_chat(data_dir, theirs)
    ask_module.ask(data_dir, chat["id"], "What is in here?", run=lambda *args: None)
    ask_module.answer(data_dir, chat["id"])

    # The question carries his archive's counts, in front of the question, and hers nowhere at all.
    assert his in seen["prompt"] and seen["prompt"].index(his) < seen["prompt"].index("Question:")
    assert "Vera Lindqvist" not in seen["prompt"] and "41 documents" not in seen["prompt"]


def test_an_answer_is_asked_to_be_short_and_to_offer_what_else_there_is():
    """A third of the wait was the typing: 23.4 s of 37.2 s, for 3 836 characters.

    Short, and under it a few named ways to go further — the owner's own answer to what short
    should look like, not this program's guess at it. What may be said about a value is not touched
    by it, which is the half of this that is worth a test: the length of an answer is not a reason
    to go near the substance of one.
    """
    from epicrisis.ask import system_prompt

    for mode in ("as_printed", "with_meaning", "direct"):
        said = system_prompt(mode)
        assert "Answer short" in said and "no closing summary" in said, mode
        assert "offer up to three ways to go further" in said, mode
        # True of this archive and grounded in what was read, and never a second place where
        # something is said about a value.
        assert "each one something you actually read while answering this question" in said, mode
        assert "no finding, no reading of a value" in said, mode
        assert "nothing the archive has not shown you" in said, mode

    strict = system_prompt("as_printed")
    assert "Never say whether a value is normal, high or low" in strict
    assert "Quote values exactly as printed" in strict and "Name the document behind every number" in strict
    assert "Do not select, rank or highlight values by how notable they look" in strict
    reading = system_prompt("with_meaning")
    assert "marked as your reading" in reading and 'never read "inside the printed range" as "fine"' in reading


def test_the_search_tool_counts_what_it_was_asked_for(archive_index):
    """"22 documents", says the answer, over a page holding two of them.

    The count was taken without the dates the page itself was narrowed by, so a search over a year
    answered with the number of matches in the whole archive and offered a next page that came back
    empty. The one reading it is a model writing about somebody's records from what it is told, and
    it was told a number about a different question.
    """
    data_dir, _source, _labs = archive_index
    server = build_server(data_dir)

    whole = asyncio.run(server.call_tool("search_documents", {"query_text": "Synthetic"}))
    narrowed = asyncio.run(server.call_tool("search_documents",
                                            {"query_text": "Synthetic", "since": f"{A_DAY_FOR_AN_ILLUSTRATION.year}-01-01",
                                             "until": f"{A_DAY_FOR_AN_ILLUSTRATION.year}-12-31"}))  # fmt: skip

    inside = narrowed.structured_content
    assert inside["result"], "the narrowed page holds something"
    # However the answer is shaped, the number in it is the number of the narrowed question.
    assert inside["total"] == inside["returned"] == len(inside["result"])
    assert "next_offset" not in inside, "and it does not offer a page that would come back empty"
    assert whole.structured_content["total"] > inside["total"], "the whole archive answers differently"


def test_a_history_says_how_many_match_the_question_it_was_asked(archive_index):
    """"These are the 50 earliest of 89", where 185 matched.

    The rows of a question by printed name are two sets put together: the values whose own name
    holds the words, and the values of every indicator that name matched. The count was a sum taken
    per indicator, which is neither — a value under the name alone was never counted, one under two
    indicators was counted twice — and where the sum came out at or below the page, the note was
    left off and a cut answer looked like a whole history.
    """
    data_dir, _source, _labs = archive_index
    server = build_server(data_dir)

    answer = asyncio.run(server.call_tool("value_history", {"name": "цистатин", "limit": 1}))
    said = answer.structured_content
    assert said["found"] == 1
    # However many there are, the number is of the same question the rows came from.
    with closing(query.open_index(data_dir, None)) as connection:
        held = query.indicators_matching(connection, "цистатин")
        union = query.count_values(connection, name="цистатин", indicators=tuple(item["id"] for item in held))
    assert said.get("values_in_all", said["found"]) == union
    assert union >= said["found"], "a page never holds more than there are"


def test_a_document_the_reading_could_not_make_out_is_not_counted_as_values_lost(archive_index, tmp_path):
    """A page saying values are gone, for ever, on an archive where nothing was lost.

    A document the reading itself declared unreadable is finished with and carries no transcription
    by design. The status page counted it among those that should have one, found none, and drew
    the loudest warning it has — telling a person to read it again with a model, which ends the
    same way, so the warning could never go.
    """
    from epicrisis.web.app import _extract_step
    from epicrisis.web.jobs import InventoryJobs

    data_dir, source, _labs = archive_index
    output = jobs_path = InventoryJobs(data_dir).records_path(source.id).parent
    records = list(read_records(jobs_path / layout.INVENTORY))
    before = _extract_step(records, output)
    assert before["state"] == "done", before

    # One document the model looked at and could not make out: the ledger says so, and there is no
    # transcription of it, which is how such a reading ends — it is never written.
    pages = latest_pages(output / layout.CLASSIFY)
    one = next(item for item in document_refs({r["sha256"]: r for r in records if "sha256" in r}, pages))
    ledger = output / layout.LEDGER
    kept = [entry for entry in read_records(ledger)
            if not (entry.get("step") == "extract" and entry.get("file_sha256") == one.file_sha256)]  # fmt: skip
    ledger.write_text("".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in kept), encoding="utf-8")
    extracted_path(output / layout.EXTRACTED, one.file_sha256).unlink(missing_ok=True)
    append_line(ledger, {"step": "extract", "status": "unreadable", "file_sha256": one.file_sha256,
                         "pages": list(one.pages), "model": "a-model", "prompt_version": "x",
                         "at": records_now()})  # fmt: skip

    after = _extract_step(list(read_records(jobs_path / layout.INVENTORY)), output)
    assert after["state"] != "partial", after
    assert "are gone" not in (after.get("note") or ""), after
