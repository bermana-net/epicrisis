"""Model backends and the isolated Claude Code call they share.

ClaudeCodeBackend runs Claude Code headless under the user's own Claude subscription. It is a
personal-use mode; the repository default is meant to be an API key backend.

Isolation of every call: no saved session, no MCP servers, no user or project settings, no
skills, and no tools except Read on the rendered pages. Page text goes through stdin, never
the command line, where other local users could see it in the process list.
"""

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from epicrisis.classify.pages import Payload

DOC_TYPES = [
    "lab_panel",
    "imaging_report",
    "consultation",
    "discharge",
    "prescription",
    "referral",
    "admin",
    "insurance",
    "id_document",
    "blank",
    "other",
]

SYSTEM_PROMPT = """You index pages of a person's own medical document archive. You see one page at a time and know nothing about the file it came from. Report only what is visible on this page. Never infer, normalise, translate or complete anything, and never comment on health or findings.

Fields:
- doc_type: lab_panel (laboratory test results), imaging_report (radiology, ultrasound, ECG, endoscopy and similar reports), consultation (notes from a doctor's visit), discharge (hospital discharge summary), prescription, referral, admin (appointments, consent forms, cover letters, other paperwork), insurance (insurance, invoices, billing), id_document (identity documents), blank (no meaningful content), other (anything else, or when unsure).
- page_role: "first" if this page starts a document (letterhead, title, patient header, or a new report heading at the top); "continuation" if it continues a document that started on an earlier page.
- language: ISO 639-1 code of the predominant language on the page.
- date_on_page: the main document date exactly as printed, or null. Do not reformat it.
- provider_on_page: the issuing clinic, laboratory or doctor exactly as printed, or null.
- has_tabular_results: true if the page has a table of measured values.
- legible: false if the page cannot be read reliably.
- confidence: from 0 to 1, how sure you are about doc_type."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "enum": DOC_TYPES},
        "page_role": {"type": "string", "enum": ["first", "continuation"]},
        "language": {"type": "string", "pattern": "^[a-z]{2}$"},
        "date_on_page": {"type": ["string", "null"]},
        "provider_on_page": {"type": ["string", "null"]},
        "has_tabular_results": {"type": "boolean"},
        "legible": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "doc_type",
        "page_role",
        "language",
        "date_on_page",
        "provider_on_page",
        "has_tabular_results",
        "legible",
        "confidence",
    ],
    "additionalProperties": False,
}

TEXT_REQUEST = "Classify the document page whose text is between the markers.\n<<<PAGE\n{text}\nPAGE>>>"
IMAGE_REQUEST = "Read the image file {name} in the current directory. It shows one page of a document. Classify that page."

PROMPT_VERSION = hashlib.sha256(
    "\n".join([SYSTEM_PROMPT, json.dumps(OUTPUT_SCHEMA, sort_keys=True), TEXT_REQUEST, IMAGE_REQUEST]).encode()
).hexdigest()[:12]

LIMIT_MARKERS = ("usage limit", "rate limit", "limit reached", "limit will reset", "overloaded")


class BackendError(Exception):
    """A single call failed. The message never contains model output or page content."""


class UsageLimitReached(BackendError):
    """The subscription limit is hit. The run stops and resumes later from the ledger."""


@dataclass
class Classification:
    fields: dict
    model: str
    escalation: list[str] | None = None  # why the stronger model was asked, when it was


def backend_installed(executable: str = "claude") -> bool:
    """Whether the program that talks to the model is on this machine at all.

    Consent says a person allows their pages to be sent; this says the sending can happen. The
    two fail differently and a person should not have to guess which one they are looking at.
    """
    import shutil

    return shutil.which(executable) is not None


def claude_command(executable: str, model: str, system_prompt: str, schema: dict, read_files: bool) -> list[str]:
    command = [
        executable, "-p",
        "--model", model,
        "--output-format", "json",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--setting-sources", "",
        "--disable-slash-commands",
        "--system-prompt", system_prompt,
        "--json-schema", json.dumps(schema),
    ]  # fmt: skip
    if read_files:
        return [*command, "--tools", "Read", "--allowedTools", "Read"]
    return [*command, "--tools", ""]


def run_claude(command: list[str], request: str, workdir: Path, timeout_seconds: int) -> tuple[dict, str]:
    """Structured output and model name of one isolated Claude Code call."""
    # A key in this server's environment would make Claude Code bill that key instead of the
    # subscription it is signed in to, silently. Which engine answers is a choice on the settings
    # page; it is not decided by a file appearing on the machine, so the names go out of here.
    from epicrisis.engines import KEYS_THE_OTHER_ENGINE_USES

    environment = {
        **{name: value for name, value in os.environ.items() if name not in KEYS_THE_OTHER_ENGINE_USES},
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_TELEMETRY": "1",
        "DISABLE_ERROR_REPORTING": "1",
    }
    try:
        completed = subprocess.run(
            command,
            input=request,
            capture_output=True,
            text=True,
            cwd=workdir,
            env=environment,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise BackendError("timeout") from exc
    requested = command[command.index("--model") + 1] if "--model" in command else None
    return structured_result(completed.returncode, completed.stdout, completed.stderr, requested)


def structured_result(returncode: int, stdout: str, stderr: str, requested: str | None = None) -> tuple[dict, str]:
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        result = {}
    if not isinstance(result, dict):
        result = {}
    diagnostics = f"{result.get('result') or ''} {result.get('subtype') or ''} {stderr}".lower()
    if any(marker in diagnostics for marker in LIMIT_MARKERS):
        raise UsageLimitReached("usage limit reached")
    if returncode != 0 or result.get("is_error"):
        raise BackendError(f"model call failed (exit {returncode}, {result.get('subtype', 'no result')})")
    fields = result.get("structured_output")
    if not isinstance(fields, dict):
        raise BackendError("no valid structured output")
    return fields, answering_model(result.get("modelUsage"), requested)


def answering_model(usage, requested: str | None) -> str:
    """The model that wrote the answer. Claude Code also calls a small model for its own chores."""
    if not isinstance(usage, dict) or not usage:
        return "unknown"
    if requested:
        matching = [name for name in usage if name.startswith(requested)]
        if matching:
            return matching[0]

    def output_tokens(name: str) -> int:
        entry = usage[name]
        return entry.get("outputTokens", 0) if isinstance(entry, dict) else 0

    return max(usage, key=output_tokens)


def parse_result(returncode: int, stdout: str, stderr: str) -> Classification:
    fields, model = structured_result(returncode, stdout, stderr)
    if fields.get("doc_type") not in DOC_TYPES:
        raise BackendError("no valid structured output")
    return Classification(fields=fields, model=model)


SMALL_MODEL = "claude-haiku-4-5-20251001"
STRONG_MODEL = "claude-opus-5"
MIN_CONFIDENCE = 0.8


def classification_problems(fields: dict) -> list[str]:
    """Reasons to ask the stronger model about a page. Codes only, never page content."""
    problems = []
    if fields.get("confidence", 0) < MIN_CONFIDENCE:
        problems.append("low_confidence")
    if not fields.get("legible", True):
        problems.append("not_legible")
    if fields.get("doc_type") == "other":
        problems.append("type_other")
    return problems


class ModelLadder:
    """The small model first; the strong one only when the small one fails or is unsure.

    `model` names the ladder in the ledger. Pages done by the strong model alone count as done.
    """

    def __init__(self, first, second):
        self.name = first.name
        self.first, self.second = first, second
        self.model = f"{first.model}>{second.model}"
        self.accepted_models = {self.model, second.model}

    def classify(self, payload: Payload, workdir: Path) -> Classification:
        try:
            result = self.first.classify(payload, workdir)
            problems = classification_problems(result.fields)
        except UsageLimitReached:
            raise
        except BackendError:
            problems = ["small_model_failed"]
        if not problems:
            return result
        stronger = self.second.classify(payload, workdir)
        stronger.escalation = problems
        return stronger

    def accepts(self, line: dict) -> bool:
        """A page the small model classified alone, before the ladder, with nothing to escalate."""
        return line.get("provenance", {}).get("requested_model") == self.first.model and not classification_problems(line)


class ClaudeCodeBackend:
    name = "claude-code-subscription"

    """One page, read once. What carries the request is given to it; see epicrisis/engines.py.

    The name is the engine's, not the class's: consent is recorded against it and the ledger
    stores it, and both have to say where a page actually went.
    """

    def __init__(self, model: str = SMALL_MODEL, executable: str = "claude", timeout_seconds: int = 300,
                 call=None):  # fmt: skip
        self.model = model
        self.executable = executable
        self.timeout_seconds = timeout_seconds
        self._call = call
        if call is not None:
            self.name = call.backend_name  # the instance says where its pages actually went

    @property
    def call(self):
        if self._call is None:
            from epicrisis.engines import ClaudeCodeCall

            self._call = ClaudeCodeCall(model=self.model, executable=self.executable,
                                        timeout_seconds=self.timeout_seconds)  # fmt: skip
        return self._call

    def command(self, route: str) -> list[str]:
        return claude_command(self.executable, self.model, SYSTEM_PROMPT, OUTPUT_SCHEMA, read_files=route == "vision")

    def classify(self, payload: Payload, workdir: Path) -> Classification:
        images: tuple[Path, ...] = ()
        if payload.image_path is not None:
            request = IMAGE_REQUEST.format(name=payload.image_path.name)
            images = (payload.image_path, *payload.close_ups)
        else:
            request = TEXT_REQUEST.format(text=payload.text or "")
        fields, model = self.call.ask(SYSTEM_PROMPT, OUTPUT_SCHEMA, request, workdir, images)
        if fields.get("doc_type") not in DOC_TYPES:
            raise BackendError("no valid structured output")
        return Classification(fields=fields, model=model)
