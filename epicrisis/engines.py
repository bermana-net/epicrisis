"""Which program talks to the model, chosen once and read everywhere.

Two things have to be chosen before a page can be read: **which model** does a pass, and **which
program carries the request to it**. The first has lived in one place for a while — models.py,
with the person's choice in settings. The second was written into ten: three commands in the
command line, three steps of `update`, four small readers that each built a command line of their
own. Adding a second way to reach a model would have meant finding all ten and remembering the
eleventh.

So the engine is chosen here, and here only. Everything else asks this module for something that
can answer a question, and never learns how the answer was fetched.

What an engine is, precisely: a way to send one isolated request — a system prompt, a schema the
answer must fit, and the request itself — and get back structured fields and the name of the model
that answered. That is the whole contract, and it is the same whether the request goes to a
program on this machine or to an address on the internet.

An engine that is not built yet is listed and cannot be chosen. A settings page that offers a
choice which does nothing is worse than a page that says the choice is coming.
"""

import base64
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT = "claude-code"


@dataclass(frozen=True)
class Engine:
    """One way of reaching a model, as the settings page shows it."""

    name: str
    label: str
    about: str
    built: bool
    needs: str


ENGINES = (
    Engine(
        name="claude-code",
        label="Claude Code on this machine",
        about="The program is installed on this server and answers under whatever account it is "
              "signed in to. Nothing else is configured, no key is stored, and a page never "
              "leaves this machine except in the model call itself.",
        built=True,
        needs="the `claude` command installed for the account this server runs as",
    ),
    Engine(
        name="anthropic-api",
        label="Anthropic API with a key of your own",
        about="The same models, reached directly with an API key that belongs to whoever runs "
              "this instance: its own account, its own bill, its own agreement with the provider. "
              "The key is read from .env and never stored in these settings, and it is kept out "
              "of the other engine's environment, so putting a key on this machine does not "
              "quietly change how the subscription is billed.",
        built=True,
        needs="ANTHROPIC_API_KEY in .env, or in the environment this server runs in",
    ),
)

BY_NAME = {engine.name: engine for engine in ENGINES}


def chosen_engine(data_dir: Path | None) -> str:
    """The engine this instance uses. Claude Code unless somebody chose otherwise."""
    from epicrisis.settings import _settings

    if data_dir is None:
        return DEFAULT
    name = str(_settings(data_dir).get("engine") or DEFAULT).strip()
    engine = BY_NAME.get(name)
    if engine is None or not engine.built:
        return DEFAULT
    if engine.name == "anthropic-api" and not key_for(data_dir):
        return DEFAULT  # the key was taken away; the instance falls back rather than failing on every page
    return name


def set_engine(data_dir: Path, name: str) -> None:
    """Remember the engine. An unknown one, or one not built yet, is refused rather than stored."""
    from epicrisis.settings import _write_settings

    engine = BY_NAME.get((name or "").strip())
    if engine is None:
        raise ValueError(f"no such engine: {name}")
    missing = what_it_needs(engine.name, data_dir)
    if missing:
        raise ValueError(f"{engine.label} cannot answer yet: {missing}")
    _write_settings(data_dir, {"engine": engine.name})


def what_it_needs(name: str, data_dir: Path | None = None) -> str | None:
    """What is missing before this engine could answer, in words, or nothing if it is ready."""
    from epicrisis.classify.backend import backend_installed

    engine = BY_NAME.get(name)
    if engine is None:
        return f"no such engine: {name}"
    if not engine.built:
        return "this engine is not written yet; every pass runs on Claude Code"
    if engine.name == "claude-code" and not backend_installed():
        return ("the program that talks to the model is not on this server, or not on the PATH "
                "of the account it runs as")  # fmt: skip
    if engine.name == "anthropic-api" and not key_for(data_dir):
        return "ANTHROPIC_API_KEY, in .env beside the data directory or in this server's environment"
    return None


KEY_NAME = "ANTHROPIC_API_KEY"
# Where a key is looked for, after the environment: beside the archive, then beside the program.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Names that make Claude Code bill an API key instead of the subscription it is signed in to.
# They are taken out of its environment, always: which engine answers is a choice on the settings
# page, never a consequence of a file appearing on the machine.
KEYS_THE_OTHER_ENGINE_USES = (KEY_NAME, "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL")


def env_file_values(path: Path) -> dict[str, str]:
    """A .env file as a dictionary. Not a parser of the whole format — names and values."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip("\'\"")
    return values


def key_for(data_dir: Path | None) -> str | None:
    """The API key, from this server's environment or from a .env file. Never from settings.

    A settings file is read by every page and copied into backups; a key does not belong there.
    """
    from_environment = os.environ.get(KEY_NAME, "").strip()
    if from_environment:
        return from_environment
    for candidate in ([Path(data_dir) / ".env"] if data_dir else []) + [PROJECT_ROOT / ".env"]:
        value = env_file_values(candidate).get(KEY_NAME, "").strip()
        if value:
            return value
    return None


class ClaudeCodeCall:
    """One isolated request carried by the program on this machine, under its own account.

    Every small reader in this program does exactly this and nothing more — the material a table
    was measured in, the grouping of printed names, a date hidden in a document. They used to
    build a Claude Code command line each; now they ask for one of these.

    Images are not sent: the command is allowed to read files, and the request names them.
    """

    backend_name = "claude-code-subscription"

    def __init__(self, model: str, executable: str = "claude", timeout_seconds: int = 300,
                 read_files: bool = False, **rest):  # fmt: skip
        self.model = model
        self.executable = executable
        self.timeout_seconds = timeout_seconds
        self.read_files = read_files
        self.name = f"claude-code:{model}"

    def ask(self, system_prompt: str, schema: dict, request: str, workdir: Path,
            images: tuple[Path, ...] = ()) -> tuple[dict, str]:  # fmt: skip
        from epicrisis.classify.backend import claude_command, run_claude

        read_files = self.read_files or bool(images)
        command = claude_command(self.executable, self.model, system_prompt, schema, read_files)
        return run_claude(command, request, workdir, self.timeout_seconds)


class AnthropicApiCall:
    """The same request, carried to the provider's own address with a key of the owner's.

    The answer comes back through a tool the model is made to use: a schema given as the tool's
    input is the provider's way of saying "the answer must have this shape", and it is the same
    schema the other engine passes on its command line.
    """

    backend_name = "anthropic-api-key"
    ADDRESS = "https://api.anthropic.com/v1/messages"
    VERSION = "2023-06-01"
    ANSWER = "answer"
    MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}

    def __init__(self, model: str, key: str, timeout_seconds: int = 300, most_tokens: int = 8192, **rest):
        self.model = model
        self.key = key
        self.timeout_seconds = timeout_seconds
        self.most_tokens = most_tokens
        self.name = f"anthropic-api:{model}"

    def _picture(self, path: Path) -> dict:
        media = self.MEDIA.get(path.suffix.lower())
        if media is None:
            raise BackendErrorFromEngine(f"a page in a format the provider is not sent: {path.suffix}")
        return {"type": "image", "source": {"type": "base64", "media_type": media,
                                            "data": base64.standard_b64encode(path.read_bytes()).decode()}}  # fmt: skip

    def ask(self, system_prompt: str, schema: dict, request: str, workdir: Path,
            images: tuple[Path, ...] = ()) -> tuple[dict, str]:  # fmt: skip
        import httpx

        from epicrisis.classify.backend import BackendError, UsageLimitReached

        content = [self._picture(Path(path)) for path in images] + [{"type": "text", "text": request}]
        body = {
            "model": self.model,
            "max_tokens": self.most_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": content}],
            "tools": [{"name": self.ANSWER, "description": "The answer, in the shape given here.",
                       "input_schema": schema}],  # fmt: skip
            "tool_choice": {"type": "tool", "name": self.ANSWER},
        }
        headers = {"x-api-key": self.key, "anthropic-version": self.VERSION, "content-type": "application/json"}
        try:
            answer = httpx.post(self.ADDRESS, json=body, headers=headers, timeout=self.timeout_seconds)
        except httpx.TimeoutException as slow:
            raise BackendError("timeout") from slow
        except httpx.HTTPError as trouble:
            raise BackendError(f"the provider could not be reached: {type(trouble).__name__}") from trouble
        if answer.status_code == 429:
            raise UsageLimitReached("the key has run into its rate or spend limit")
        if answer.status_code == 401:
            raise BackendError("the key was refused by the provider")
        if answer.status_code >= 400:
            raise BackendError(f"the provider answered {answer.status_code}")
        return self._fields(answer.json())

    def _fields(self, said: dict) -> tuple[dict, str]:
        from epicrisis.classify.backend import BackendError

        for block in said.get("content") or []:
            if block.get("type") == "tool_use" and block.get("name") == self.ANSWER:
                fields = block.get("input")
                if isinstance(fields, dict):
                    return fields, said.get("model") or self.model
        if said.get("stop_reason") == "max_tokens":
            raise BackendError("the answer was cut off before it was complete")
        raise BackendError("no valid structured output")


class BackendErrorFromEngine(Exception):
    """Raised before a request is built, where importing the backend's own error would be a cycle."""


OneCall = ClaudeCodeCall  # the name the readers knew it by


def a_call(data_dir: Path | None, pass_name: str = "strong", *, read_files: bool = False,
           timeout_seconds: int = 300, model: str | None = None, most_tokens: int = 8192):  # fmt: skip
    """Something that can answer one question, with the model chosen for that pass."""
    name = chosen_engine(data_dir)
    chosen = model or _model(data_dir, pass_name)
    if name == "anthropic-api":
        key = key_for(data_dir)
        if not key:
            from epicrisis.classify.backend import BackendError

            raise BackendError("this instance is set to the Anthropic API and no key is configured")
        return AnthropicApiCall(model=chosen, key=key, timeout_seconds=timeout_seconds, most_tokens=most_tokens)
    return ClaudeCodeCall(model=chosen, timeout_seconds=timeout_seconds, read_files=read_files)


def engine_name(data_dir: Path | None) -> str:
    """Where a page goes when this instance reads it, as consent and the ledger name it.

    Consent is given for a destination, not for a program: an instance that starts sending pages
    to a different address has to be allowed to, again.
    """
    from epicrisis.classify.backend import BackendError

    try:
        return a_call(data_dir, "first").backend_name
    except BackendError:
        return ClaudeCodeCall.backend_name


def _model(data_dir: Path | None, pass_name: str) -> str:
    """The model for a pass — the person's choice where there is an instance to ask, else the
    one this program ships with. A command run with no data directory still has to work."""
    from epicrisis.models import PASSES, model_for

    return model_for(data_dir, pass_name) if data_dir is not None else PASSES[pass_name]["default"]


def classifier(data_dir: Path | None):
    """The first reading of every page, with the expert reading behind it where a check fails."""
    from epicrisis.classify.backend import ClaudeCodeBackend, ModelLadder

    return ModelLadder(*(ClaudeCodeBackend(model=_model(data_dir, which),
                                           call=a_call(data_dir, which, read_files=True))
                         for which in ("first", "strong")))  # fmt: skip


def extractor(data_dir: Path | None):
    """The two passes that read the values out of a page, as the person chose them."""
    from epicrisis.extract.backend import ClaudeCodeExtractBackend, ExtractLadder

    def stage(which: str) -> ClaudeCodeExtractBackend:
        model = _model(data_dir, which)
        return ClaudeCodeExtractBackend(
            model=model, timeout_seconds=900,
            call=a_call(data_dir, which, read_files=True, timeout_seconds=900,
                        most_tokens=ClaudeCodeExtractBackend.MOST_TOKENS),  # fmt: skip
        )

    return ExtractLadder(stage("first"), stage("strong"))


def date_search(data_dir: Path | None):
    """The reader that looks for a date inside a document that printed none where it should."""
    from epicrisis.datesearch import ClaudeCodeDateSearch

    return ClaudeCodeDateSearch(model=_model(data_dir, "strong"),
                                call=a_call(data_dir, "strong", read_files=True, timeout_seconds=600))  # fmt: skip


def second_reader(data_dir: Path | None, model: str | None = None):
    """The other model, for reading a document a second time and comparing."""
    from epicrisis.extract.backend import ClaudeCodeExtractBackend

    model = model or _model(data_dir, "second_reader")
    return ClaudeCodeExtractBackend(
        model=model, timeout_seconds=900,
        call=a_call(data_dir, "second_reader", read_files=True, timeout_seconds=900,
                    model=model, most_tokens=ClaudeCodeExtractBackend.MOST_TOKENS),  # fmt: skip
    )
