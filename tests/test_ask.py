"""Read-only questions to the index, the MCP tools and the Ask page. Synthetic data only."""

import asyncio
import json
import time
from contextlib import closing
from datetime import date

import pytest
from fastapi.testclient import TestClient

from epicrisis import ask as ask_module
from epicrisis import query
from epicrisis.corrections import set_document_date
from epicrisis.extract.run import extract_source, load_extracted, write_document
from epicrisis.index.build import build_index, index_path
from epicrisis.mcp_server import build_server
from epicrisis.validate import validate_source
from epicrisis.web.app import create_app
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
    set_document_date(output, labs, [1, 2], date(2019, 7, 8))
    validate_source(output)
    build_index(data_dir, [source])
    return data_dir, source, labs


def test_queries_answer_with_values_as_printed_and_their_source(archive_index):
    data_dir, source, labs = archive_index
    connection = query.open_index(data_dir)

    assert query.overview(connection)["documents"] == 3
    found = query.search(connection, "ЦИСТАТИН")
    assert [item["file_id"] for item in found] == [labs[:8]] and "Цистатин С 0,85" in found[0]["snippet"]
    history = query.values(connection, "цистатин")
    assert [(item["value"], item["unit"], item["reference"], item["date"]) for item in history] == [("0,85", "мг/л", "0,5-1,0", "2019-07-08")]
    assert query.values(connection, "шкф") == [] and len(query.values(connection, "шкф", include_derived=True)) == 1
    names = query.value_names(connection, "цистат")
    assert (names[0]["name"], names[0]["times"], names[0]["first_date"]) == ("Цистатин С", 1, "2019-07-08")
    document = query.document(connection, file_id=labs[:8])
    assert document["card_url"] == f"/documents/{source.id}/{labs}/1" and len(document["values"]) == 2
    assert document["original_pages_url"][0].endswith(f"/files/{labs}/pages/1")
    assert [item["file_id"] for item in query.timeline(connection, since="2019-01-01")] == [labs[:8]]
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
    from epicrisis.ask import set_answer_mode

    # The middle mode lets the model read the values; the application still does not compare them.
    set_answer_mode(data_dir, "with_meaning")
    assert "does not compare" in str(asyncio.run(server.call_tool("flagged_values", {"compare_with_printed_range": True})))

    set_answer_mode(data_dir, "direct")
    allowed = asyncio.run(server.call_tool("flagged_values", {"compare_with_printed_range": True}))
    assert "does not compare" not in str(allowed)


def test_ask_records_the_question_steps_and_answer(archive_index, monkeypatch, tmp_path):
    data_dir, _, _ = archive_index

    def fake_stream(data_dir, prompt, mode="as_printed"):
        assert "How did cystatin change?" in prompt and mode == "as_printed"
        yield {"kind": "tool", "step": {"tool": "value_history", "input": {"name": "цистатин"}}}
        yield {"kind": "answer", "text": "0,85 мг/л on 08.07.2019, file 43cdf91f."}

    monkeypatch.setattr(ask_module, "_stream", fake_stream)
    chat = ask_module.new_chat(data_dir)
    # The background thread does nothing here; the answer is written in this thread instead.
    ask_module.ask(data_dir, chat["id"], "How did cystatin change?", run=lambda *args: None)
    ask_module.answer(data_dir, chat["id"])

    stored = ask_module.load_chat(data_dir, chat["id"])
    answer = stored["messages"][-1]
    assert (answer["state"], answer["steps"][0]["tool"]) == ("done", "value_history")
    assert "0,85 мг/л" in answer["text"] and stored["title"] == "How did cystatin change?"
    assert [item["id"] for item in ask_module.list_chats(data_dir)] == [chat["id"]]


def test_ask_page_is_off_until_turned_on(archive_index, monkeypatch):
    data_dir, _, _ = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    page = client.get("/ask").text
    assert "Answering questions is turned off" in page
    assert client.post("/ask", data={"question": "hi"}).status_code == 403

    ask_module.set_ask_enabled(data_dir, True)
    assert "Model processing is not confirmed" in client.get("/ask").text
    (data_dir / "consent.json").write_text(json.dumps({"claude-code-subscription": {"version": 2, "at": "now"}}))
    started = client.post("/ask", data={"question": "What is in the archive?"}, follow_redirects=False)
    assert started.status_code == 303 and started.headers["location"].startswith("/ask/")
    chat_id = started.headers["location"].rsplit("/", 1)[1]
    assert client.get(f"/ask/{chat_id}/state").json() == {"running": False, "messages": []}
    assert client.get("/ask/unknown").status_code == 404


def test_settings_switch_what_answers_may_contain(archive_index):
    from epicrisis.ask import answer_mode, system_prompt

    data_dir, _, _ = archive_index
    client = TestClient(create_app(data_dir, background_jobs=False), base_url="http://localhost:8050")

    assert answer_mode(data_dir) == "as_printed"
    assert "never diagnose" in system_prompt("as_printed") and "no diagnosis" in system_prompt("with_meaning")
    assert "whether a value is normal" not in system_prompt("with_meaning")
    assert "sets no limits on that" in system_prompt("direct") and "never diagnose" not in system_prompt("direct")
    # The freest mode still holds the model to the records: quoting, provenance, never from memory.
    assert "exactly as printed" in system_prompt("direct") and "Never answer from memory" in system_prompt("direct")

    saved = client.post("/settings", data={"ask_page": "on", "mode": "with_meaning"}, follow_redirects=False)
    assert saved.status_code == 303
    assert answer_mode(data_dir) == "with_meaning"
    page = client.get("/settings?saved=true").text
    assert "Saved." in page and 'value="with_meaning" checked' in page.replace('" checked', '" checked')
    assert "not a medical device" in page

    # Units on a chart are a separate switch, off unless asked for.
    from epicrisis.ask import converts_units

    assert converts_units(data_dir) is False
    client.post("/settings", data={"ask_page": "on", "mode": "with_meaning", "scale": "on"})
    assert converts_units(data_dir) is True
    assert 'name="scale" value="on" checked' in client.get("/settings").text

    client.post("/settings", data={"ask_page": "on", "mode": "direct"})
    assert answer_mode(data_dir) == "direct" and 'value="direct" checked' in client.get("/settings").text

    client.post("/settings", data={"ask_page": "", "mode": "as_printed"})
    assert answer_mode(data_dir) == "as_printed" and "Answering questions is turned off" in client.get("/ask").text


def test_answers_render_as_markdown_without_raw_html(archive_index, monkeypatch):
    data_dir, _, _ = archive_index

    def fake_stream(data_dir, prompt, mode="as_printed"):
        yield {"kind": "answer", "text": "| Date | Value |\n|---|---|\n| 08.07.2019 | 0,85 |\n\n<script>alert(1)</script>"}

    monkeypatch.setattr(ask_module, "_stream", fake_stream)
    ask_module.set_ask_enabled(data_dir, True)
    (data_dir / "consent.json").write_text(json.dumps({"claude-code-subscription": {"version": 2, "at": "now"}}))
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
    ask_module.set_ask_enabled(data_dir, True)
    (data_dir / "consent.json").write_text(json.dumps({"claude-code-subscription": {"version": 2, "at": "now"}}))
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
    assert "Showing" in feed and "carry no date" in feed
    assert client.get("/", params={"skip": 120}).status_code == 200
    assert client.get("/", params={"undated": 1}).status_code == 200
    # The view by test shows a few tests and offers the rest, rather than everything at once.
    by_test = client.get("/", params={"view": "indicators"}).text
    assert "BY TEST" in by_test.upper()
    assert "every test" not in by_test or "show every test" in by_test.casefold()

    found = client.get("/search", params={"q": "Analyte"})
    assert found.status_code == 200 and labs[:8] in found.text
    assert "Type a word" in client.get("/search").text
    assert "Nothing matched" in client.get("/search", params={"q": "zzzqqq"}).text


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

    data_dir, _, _ = archive_index
    module.set_ask_enabled(data_dir, True)

    def refuse(*args, **kwargs):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(module, "_stream", refuse)
    chat = module.new_chat(data_dir, "Vera Lindqvist")
    # The question is put in a thread in real use; here it is answered on the spot, to be read.
    module.ask(data_dir, chat["id"], "How did cystatin change?", run=lambda *args: None)
    module.answer(data_dir, chat["id"])

    answered = module.load_chat(data_dir, chat["id"])["messages"][-1]
    assert answered["state"] == "failed" and "not found on this server" in answered["error"]
    assert answered["text"] == ""  # nothing invented in place of an answer


def test_a_model_that_stops_halfway_leaves_the_answer_marked_failed(archive_index, monkeypatch):
    from epicrisis import ask as module

    data_dir, _, _ = archive_index
    module.set_ask_enabled(data_dir, True)

    def half(*args, **kwargs):
        yield {"kind": "tool", "step": {"tool": "value_history", "input": {}}}
        yield {"kind": "error", "text": "usage_limit"}

    monkeypatch.setattr(module, "_stream", half)
    chat = module.new_chat(data_dir, "Vera Lindqvist")
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

    from epicrisis.ask import _save, load_chat, new_chat, set_ask_enabled
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
    from epicrisis.ask import list_chats, load_chat, set_ask_enabled
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
