"""Which program talks to the model: chosen in one place, read everywhere."""


import pytest

from epicrisis import engines


def test_the_engine_is_claude_code_until_somebody_chooses_otherwise(data_dir):
    assert engines.chosen_engine(data_dir) == engines.DEFAULT == "claude-code"
    assert engines.chosen_engine(None) == "claude-code"  # a command run with no instance still works


@pytest.fixture(autouse=True)
def no_key_on_the_machine(monkeypatch, tmp_path):
    """The machine running the tests may well have a key of its own; these tests must not see it."""
    monkeypatch.delenv(engines.KEY_NAME, raising=False)
    monkeypatch.setattr(engines, "PROJECT_ROOT", tmp_path / "nowhere")


def test_an_engine_that_cannot_answer_is_refused_with_the_reason(data_dir, monkeypatch):
    """A settings page may offer it; the store only keeps what could actually run."""
    with pytest.raises(ValueError, match=engines.KEY_NAME):
        engines.set_engine(data_dir, "anthropic-api")
    with pytest.raises(ValueError, match="no such engine"):
        engines.set_engine(data_dir, "a-model-in-a-drawer")
    assert engines.chosen_engine(data_dir) == "claude-code"

    monkeypatch.setenv(engines.KEY_NAME, "a-key-that-is-not-a-key")
    engines.set_engine(data_dir, "anthropic-api")
    assert engines.chosen_engine(data_dir) == "anthropic-api"
    assert isinstance(engines.a_call(data_dir, "first"), engines.AnthropicApiCall)

    # The key is taken away: the instance falls back rather than failing on every page.
    monkeypatch.delenv(engines.KEY_NAME)
    assert engines.chosen_engine(data_dir) == "claude-code"


def test_a_key_is_read_from_a_file_and_never_from_the_settings(data_dir, monkeypatch):
    monkeypatch.delenv(engines.KEY_NAME, raising=False)
    assert engines.key_for(data_dir) is None
    (data_dir / ".env").write_text(f"# a comment\n{engines.KEY_NAME}='a-key-kept-in-a-file'\n", encoding="utf-8")
    assert engines.key_for(data_dir) == "a-key-kept-in-a-file"
    assert engines.KEY_NAME not in (data_dir / "settings.json").read_text(encoding="utf-8") \
        if (data_dir / "settings.json").exists() else True  # fmt: skip


def test_a_key_on_this_machine_does_not_change_how_the_subscription_is_billed(monkeypatch, tmp_path):
    """Claude Code bills a key it finds in the environment. It never finds one through us."""
    from epicrisis.classify import backend as backend_module

    seen = {}

    class Done:
        returncode = 0
        stdout = '{"structured_output": {"said": "yes"}, "modelUsage": {}}'
        stderr = ""

    def watch(command, **kwargs):
        seen.update(kwargs.get("env") or {})
        return Done()

    monkeypatch.setenv(engines.KEY_NAME, "a-key-that-is-not-a-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://somewhere.else")
    monkeypatch.setattr(backend_module.subprocess, "run", watch)
    backend_module.run_claude(["claude", "--model", "m"], "a question", tmp_path, 5)

    assert engines.KEY_NAME not in seen and "ANTHROPIC_BASE_URL" not in seen
    assert seen["DISABLE_TELEMETRY"] == "1"  # and the rest of the environment is still there


def test_what_an_engine_is_waiting_for_is_said_in_words(monkeypatch, data_dir):
    from epicrisis.classify import backend as backend_module

    monkeypatch.delenv(engines.KEY_NAME, raising=False)
    assert engines.KEY_NAME in engines.what_it_needs("anthropic-api", data_dir)
    monkeypatch.setenv(engines.KEY_NAME, "a-key-that-is-not-a-key")
    assert engines.what_it_needs("anthropic-api", data_dir) is None

    monkeypatch.setattr(backend_module, "backend_installed", lambda *args: True)
    assert engines.what_it_needs("claude-code", data_dir) is None
    monkeypatch.setattr(backend_module, "backend_installed", lambda *args: False)
    assert "not on this server" in engines.what_it_needs("claude-code", data_dir)


def test_every_step_takes_its_model_from_the_one_place_that_holds_it(data_dir):
    """Ten places used to name the models themselves; now they ask, and a choice reaches them all."""
    from epicrisis.settings import set_chosen_models

    set_chosen_models(data_dir, {"first": "claude-haiku-4-5-20251001", "strong": "claude-sonnet-5",
                                 "second_reader": "claude-fable-5-1"})  # fmt: skip

    assert engines.classifier(data_dir).model == "claude-haiku-4-5-20251001>claude-sonnet-5"
    assert engines.extractor(data_dir).model == "claude-haiku-4-5-20251001>claude-sonnet-5"
    assert engines.date_search(data_dir).model == "claude-sonnet-5"
    assert engines.second_reader(data_dir).model == "claude-fable-5-1"
    assert engines.a_call(data_dir, "first").model == "claude-haiku-4-5-20251001"
    assert engines.a_call(data_dir, "strong").name == "claude-code:claude-sonnet-5"


def test_the_small_readers_go_through_the_factory_rather_than_building_a_command(monkeypatch, data_dir):
    """A reader of one table, of one group of names, of one date — all the same one question."""
    from epicrisis.indicator_check import CheckBackend
    from epicrisis.material_reading import MaterialBackend

    asked = []

    class Answer:
        model = "test-model"
        name = "test:test-model"
        backend_name = "test-engine"

        def ask(self, system_prompt, schema, request, workdir):
            asked.append((system_prompt[:20], sorted(schema), workdir))
            return ({"panels": [], "groups": []}, self.model)

    monkeypatch.setattr(engines, "a_call", lambda *args, **kwargs: Answer())
    MaterialBackend(model="m").read("a panel", data_dir)
    CheckBackend(model="m").check("a group", data_dir)
    assert len(asked) == 2 and all(where == data_dir for _, _, where in asked)


def test_the_api_engine_asks_for_the_answer_in_the_shape_the_schema_gives(monkeypatch, tmp_path):
    """One request, the schema as a tool the model is made to use, the page as a picture beside it."""
    import httpx

    from epicrisis.engines import AnthropicApiCall

    page = tmp_path / "page-1.png"
    page.write_bytes(b"\x89PNG\r\n\x1a\n" + b"not really a picture")
    sent = {}

    class Answered:
        status_code = 200

        @staticmethod
        def json():
            return {"model": "claude-opus-5-20260101",
                    "content": [{"type": "tool_use", "name": "answer", "input": {"doc_type": "lab_panel"}}]}  # fmt: skip

    def post(address, json=None, headers=None, timeout=None):
        sent.update(address=address, body=json, headers=headers, timeout=timeout)
        return Answered()

    monkeypatch.setattr(httpx, "post", post)
    fields, model = AnthropicApiCall(model="claude-opus-5", key="a-key-that-is-not-a-key").ask(
        "you read forms", {"type": "object"}, "read this page", tmp_path, (page,))

    assert fields == {"doc_type": "lab_panel"} and model == "claude-opus-5-20260101"
    assert sent["headers"]["x-api-key"] == "a-key-that-is-not-a-key"
    assert sent["body"]["tool_choice"] == {"type": "tool", "name": "answer"}
    assert sent["body"]["tools"][0]["input_schema"] == {"type": "object"}
    assert sent["body"]["system"] == "you read forms"
    picture, words = sent["body"]["messages"][0]["content"]
    assert picture["type"] == "image" and picture["source"]["media_type"] == "image/png"
    assert words["text"] == "read this page"


def test_the_api_engine_says_which_way_it_failed(monkeypatch, tmp_path):
    """A limit stops the run and is resumed later; a refused key is a thing to go and fix."""
    import httpx

    from epicrisis.classify.backend import BackendError, UsageLimitReached
    from epicrisis.engines import AnthropicApiCall

    call = AnthropicApiCall(model="claude-opus-5", key="a-key-that-is-not-a-key")

    def answering(code, body=None):
        class Answer:
            status_code = code

            @staticmethod
            def json():
                return body or {}

        monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: Answer())

    answering(429)
    with pytest.raises(UsageLimitReached):
        call.ask("s", {}, "q", tmp_path)
    answering(401)
    with pytest.raises(BackendError, match="refused"):
        call.ask("s", {}, "q", tmp_path)
    answering(200, {"content": [{"type": "text", "text": "I would rather not"}], "stop_reason": "end_turn"})
    with pytest.raises(BackendError, match="no valid structured output"):
        call.ask("s", {}, "q", tmp_path)
    answering(200, {"content": [], "stop_reason": "max_tokens"})
    with pytest.raises(BackendError, match="cut off"):
        call.ask("s", {}, "q", tmp_path)


def test_the_question_page_does_not_bill_the_key_either(monkeypatch, tmp_path):
    """The Ask page runs Claude Code whatever the engine is; a key on the machine stays out of it."""
    from epicrisis import ask as ask_module

    seen = {}

    class Talking:
        stdin = stdout = None

        def __init__(self, *args, **kwargs):
            seen.update(kwargs.get("env") or {})
            self.stdin = _Silent()
            self.stdout = _Silent()

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    class _Silent:
        def write(self, text):
            pass

        def close(self):
            pass

        def __iter__(self):
            return iter(())

    monkeypatch.setenv(engines.KEY_NAME, "a-key-that-is-not-a-key")
    monkeypatch.setattr(ask_module.subprocess, "Popen", Talking)
    list(ask_module._stream(tmp_path, "a question", "as_printed"))

    assert engines.KEY_NAME not in seen and "ANTHROPIC_BASE_URL" not in seen
