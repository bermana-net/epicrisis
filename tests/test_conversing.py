"""The tool loop: a question answered through the API, with the archive's own tools."""

import json
from types import SimpleNamespace

import pytest

from epicrisis import ask, conversing
from test_ask import archive_index  # noqa: F401
from test_extract import FakeExtractBackend, setup  # noqa: F401


class FakeProvider:
    """The provider, saying what a provider says. Records every request it was sent."""

    def __init__(self, *replies):
        self.replies, self.sent = list(replies), []

    def post(self, address, json=None, headers=None, timeout=None):
        self.sent.append(json)
        said = self.replies[min(len(self.sent), len(self.replies)) - 1]
        return SimpleNamespace(status_code=200, json=lambda: said)


def uses(name, arguments, block_id="t1"):
    return {"stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": block_id, "name": name, "input": arguments}]}  # fmt: skip


def says(text):
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}


@pytest.fixture
def a_call():
    return SimpleNamespace(model="claude-opus-5", key="sk-ant-not-a-real-key", timeout_seconds=30,
                           ADDRESS="https://api.anthropic.com/v1/messages", VERSION="2023-06-01")  # fmt: skip


def run(monkeypatch, data_dir, provider, call, prompt="How many documents are there?", mode="as_printed"):
    monkeypatch.setitem(__import__("sys").modules, "httpx", SimpleNamespace(
        post=provider.post, TimeoutException=TimeoutError, HTTPError=OSError))  # fmt: skip
    return list(conversing.through_the_api(data_dir, prompt, ask.system_prompt(mode), call))


def test_the_model_asks_for_a_tool_and_the_archive_answers_it(monkeypatch, archive_index, a_call):  # noqa: F811
    """The tool runs in this process, against this archive, and its own words go back."""
    data_dir, _source, _labs = archive_index
    provider = FakeProvider(uses("archive_overview", {}), says("There are 3 documents."))

    events = run(monkeypatch, data_dir, provider, a_call)

    assert events[0] == {"kind": "tool", "step": {"tool": "archive_overview", "input": {}}}
    assert events[-1] == {"kind": "answer", "text": "There are 3 documents."}
    # The second request carries what the archive itself answered, not something invented.
    carried = provider.sent[1]["messages"][-1]["content"][0]
    assert carried["type"] == "tool_result" and carried["tool_use_id"] == "t1"
    assert json.loads(carried["content"])["documents"] >= 1


def test_the_task_given_to_the_model_is_the_one_the_instance_set(monkeypatch, archive_index, a_call):  # noqa: F811
    """Moving to another engine is not a place to redecide what may be said about a value.

    And not a place to lose what the archive says about itself either. The other engine is handed
    the server's instructions by its MCP client; over the API nobody hands them to anybody, so
    they go in front of the task here. They are where the boundary is written — that an empty
    answer is not an absence, that one printed name can be two tests, that laboratories differ —
    and one engine enforcing that in words while the other does not is the thing this file exists
    to prevent.
    """
    from epicrisis.mcp_server import build_server

    data_dir, _source, _labs = archive_index
    says_of_itself = build_server(data_dir).instructions
    assert "empty result never means" in says_of_itself, "the instructions are the boundary"

    for mode in ("as_printed", "with_meaning", "direct"):
        provider = FakeProvider(says("Answered."))
        run(monkeypatch, data_dir, provider, a_call, mode=mode)
        sent = provider.sent[0]["system"]
        assert sent.endswith(ask.system_prompt(mode))
        assert says_of_itself in sent


def test_the_lock_is_not_offered_where_there_is_nothing_to_reach(monkeypatch, archive_index, a_call):  # noqa: F811
    """In this process there is no address, so a pass would have nowhere to come from."""
    data_dir, _source, _labs = archive_index
    provider = FakeProvider(says("Answered."))
    run(monkeypatch, data_dir, provider, a_call)

    offered = {tool["name"] for tool in provider.sent[0]["tools"]}
    assert offered and not offered & set(conversing.NOT_IN_HERE)
    assert "value_history" in offered and all(tool["description"] for tool in provider.sent[0]["tools"])


def test_a_tool_that_fails_is_told_to_the_model_and_not_raised_at_the_page(monkeypatch, archive_index, a_call):  # noqa: F811
    """It can ask another way. A conversation ending on one bad call is worse for the person."""
    data_dir, _source, _labs = archive_index
    provider = FakeProvider(uses("get_document", {"file_id": "nothing at all"}), says("I could not find it."))

    events = run(monkeypatch, data_dir, provider, a_call)

    assert events[-1]["kind"] == "answer"
    said = provider.sent[1]["messages"][-1]["content"][0]
    assert said["type"] == "tool_result"


def test_a_loop_that_will_not_stop_is_stopped(monkeypatch, archive_index, a_call):  # noqa: F811
    """A loop is a bill as well as a wait."""
    data_dir, _source, _labs = archive_index
    provider = FakeProvider(uses("archive_overview", {}))  # asks for a tool, for ever

    events = run(monkeypatch, data_dir, provider, a_call)

    assert len(provider.sent) == conversing.MOST_TURNS
    assert events[-1]["kind"] == "error" and "turns" in events[-1]["text"]


def test_an_answer_with_nothing_in_it_is_a_failure_and_not_an_empty_answer(monkeypatch, archive_index, a_call):  # noqa: F811
    data_dir, _source, _labs = archive_index
    events = run(monkeypatch, data_dir, FakeProvider(says("   ")), a_call)
    assert events == [{"kind": "error", "text": "no answer"}]


@pytest.fixture
def a_key_this_test_brought_itself(monkeypatch):
    """A key in the environment, so that choosing the API engine does not depend on this machine.

    Both tests below need an instance where the API engine is ready, and readiness means a key.
    They had none, and passed anyway — because `key_for` falls back to a .env beside the program,
    and on the machine this was written on that file holds the author's real key. So they were
    green here and red in every worktree and every fresh clone: two failures about a missing key,
    on a change that had nothing to do with keys, in the middle of every report. CLAUDE.md promises
    the suite needs no network and no model, and a test that needs somebody's key is that promise
    broken rather than a key missing.

    The value is nonsense on purpose. Nothing here calls Anthropic — the provider is a fake and
    `a_call` is replaced — so what the key says never leaves the process, and a key that could
    work would mean a test that could spend money.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-key-nothing-here-calls-anybody")


def test_the_api_engine_starts_no_process_at_all(monkeypatch, archive_index, a_call, a_key_this_test_brought_itself):  # noqa: F811
    """The point of this loop: an instance with a key and no Claude Code can still answer."""
    import subprocess

    from epicrisis import engines

    data_dir, _source, _labs = archive_index
    engines.set_engine(data_dir, engines.ANTHROPIC_API)
    monkeypatch.setattr(engines, "a_call", lambda *rest, **more: a_call)
    monkeypatch.setattr(subprocess, "Popen", lambda *rest, **more: pytest.fail("a process was started"))
    provider = FakeProvider(uses("archive_overview", {}), says("Three documents."))
    monkeypatch.setitem(__import__("sys").modules, "httpx", SimpleNamespace(
        post=provider.post, TimeoutException=TimeoutError, HTTPError=OSError))  # fmt: skip

    events = list(ask._stream(data_dir, "How many documents?", "as_printed"))
    assert events[-1] == {"kind": "answer", "text": "Three documents."}


def test_the_pass_that_asks_the_web_follows_the_engine_too(tmp_path, monkeypatch, a_key_this_test_brought_itself):
    """The one place that talks to anything but Anthropic, on either engine.

    And the destination changes with it, which is what the consent is recorded against.
    """
    from epicrisis import engines
    from epicrisis.indicator_web_check import ApiWebCheckBackend, WebCheckBackend, web_backend

    data = tmp_path / "data"
    data.mkdir()
    engines.set_engine(data, engines.CLAUDE_CODE)
    assert isinstance(web_backend(data), WebCheckBackend)

    engines.set_engine(data, engines.ANTHROPIC_API)
    monkeypatch.setattr(engines, "a_call", lambda *rest, **more: SimpleNamespace(model="claude-opus-5"))
    chosen = web_backend(data)
    assert isinstance(chosen, ApiWebCheckBackend) and chosen.name != WebCheckBackend.name


def test_the_web_search_runs_on_the_providers_side_and_the_answer_has_a_shape(monkeypatch, a_call):
    """Nothing of ours runs for the search, and the answer comes back through our own tool."""
    from epicrisis import conversing

    searched = {"stop_reason": "end_turn", "content": [
        {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "Oxalates urine"}},
        {"type": "text", "text": "I looked it up."},
    ]}  # fmt: skip
    answered = {"stop_reason": "tool_use", "content": [
        {"type": "tool_use", "id": "a1", "name": "answer", "input": {"names": [{"ref": "1", "verdict": "a test"}]}},
    ]}  # fmt: skip
    provider = FakeProvider(searched, answered)
    monkeypatch.setitem(__import__("sys").modules, "httpx", SimpleNamespace(
        post=provider.post, TimeoutException=TimeoutError, HTTPError=OSError))  # fmt: skip

    got = conversing.with_the_web(a_call, "Say whether these are tests.", {"type": "object"}, "one name")

    assert got == {"names": [{"ref": "1", "verdict": "a test"}]}
    offered = provider.sent[0]["tools"]
    assert offered[0] == conversing.SEARCH_TOOL and offered[1]["name"] == "answer"
    # It said words and no shape, so it was asked again with what it had already found in front of it.
    assert len(provider.sent) == 2 and provider.sent[1]["messages"][-1]["role"] == "user"


def test_a_search_that_never_gives_a_shape_stops(monkeypatch, a_call):
    from epicrisis.classify.backend import BackendError
    from epicrisis import conversing

    provider = FakeProvider({"stop_reason": "end_turn", "content": [{"type": "text", "text": "Still looking."}]})
    monkeypatch.setitem(__import__("sys").modules, "httpx", SimpleNamespace(
        post=provider.post, TimeoutException=TimeoutError, HTTPError=OSError))  # fmt: skip

    with pytest.raises(BackendError):
        conversing.with_the_web(a_call, "system", {"type": "object"}, "request")
    assert len(provider.sent) == conversing.MOST_TURNS
