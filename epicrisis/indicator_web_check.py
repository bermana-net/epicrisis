"""Asking the open web whether a printed name is a real test, for the names no reader can judge.

A second reader compares the spellings inside a group and says whether they are one measurement.
It has nothing to say about a group of one spelling: there is no comparison to make. And most
of what waits for a person is exactly that — 46 groups of a single name, where the question is
not "do these belong together" but "is this a test at all, or a fragment, a typo, a row label".

That question is answered by a reference book, so this pass gives a model the web. It settles
the ones a catalogue confirms — "Oxalates urine 24h" is Labcorp 003970 — and marks the rest for
a person rather than guessing.

What leaves this server is a printed name, its units and how often it appears. No value, no
date, no document, no person. A name is the vocabulary of laboratories, not of a patient:
"Креатинін" says nothing about anybody. Even so this is the only part of the program that talks
to anything but Anthropic, so it runs only when a person asks for it by name, never inside the
ordinary run, and the archive's own settings never turn it on by themselves.
"""

import hashlib
import json
from pathlib import Path

from epicrisis.classify.backend import STRONG_MODEL, BackendError, run_claude
from epicrisis.printed_values import fold
from epicrisis.records import append_line, now, read_records

FILE_NAME = "indicator-web-checks.jsonl"
BATCH = 10
TIMEOUT_SECONDS = 900
VERDICTS = ("a test", "not a test", "unclear")

SYSTEM_PROMPT = """You are given names of rows printed on medical laboratory and report forms, in Russian, Ukrainian, English, Spanish and Greek, as a model read them off the page. For each, say whether it names a real measurement that a laboratory or a clinic reports.

Search the web before answering. A name counts as a test when a laboratory catalogue, a clinical reference or a manufacturer's documentation describes that measurement — under that name, its full form, or its usual abbreviation. Give the catalogue or reference you found it in.

"not a test" is for a name that names no measurement: a heading of a table or a section, a label of a row that holds a specimen or a date, a fragment of a sentence, a piece of an address or a stamp, a word broken by the scan, an abbreviation that is a misreading rather than a test.

"unclear" is for a name you cannot settle: an abbreviation that several different tests use, a name too short to search, a name that could be a test or could be a misprint and the web does not decide it.

Judge the name as printed, together with the units beside it: a name with a unit of measurement is more likely a test, and the unit often says which test it is. Do not invent a catalogue entry you did not find. Where you are not sure, say unclear rather than guessing — a name marked unclear waits for a person, and nothing is lost."""

SCHEMA = {
    "type": "object",
    "properties": {
        "names": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string"},
                    "verdict": {"type": "string", "enum": list(VERDICTS)},
                    "usual_name": {"type": ["string", "null"]},
                    "found_in": {"type": ["string", "null"]},
                    "why": {"type": "string"},
                },
                "required": ["ref", "verdict", "usual_name", "found_in", "why"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["names"],
    "additionalProperties": False,
}

REQUEST = """Names to settle, one per line as: ref | name as printed | units | how many times printed

{names}"""

PROMPT_VERSION = hashlib.sha256("\n".join([SYSTEM_PROMPT, json.dumps(SCHEMA, sort_keys=True), REQUEST]).encode()).hexdigest()[:12]


def web_command(executable: str, model: str, system_prompt: str = None, schema: dict = None) -> list[str]:
    """The one command in this program that is allowed to reach past Anthropic, and only the web."""
    return [
        executable, "-p",
        "--model", model,
        "--output-format", "json",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--setting-sources", "",
        "--disable-slash-commands",
        "--system-prompt", system_prompt if system_prompt is not None else SYSTEM_PROMPT,
        "--json-schema", json.dumps(schema if schema is not None else SCHEMA),
        "--tools", "WebSearch",
        "--allowedTools", "WebSearch",
    ]  # fmt: skip


class WebCheckBackend:
    name = "claude-code-subscription"

    def __init__(self, model: str = STRONG_MODEL, executable: str = "claude", timeout_seconds: int = TIMEOUT_SECONDS):
        self.model, self.executable, self.timeout_seconds = model, executable, timeout_seconds

    def settle(self, names: str, workdir: Path) -> dict:
        fields, _ = run_claude(web_command(self.executable, self.model), REQUEST.format(names=names),
                               workdir, self.timeout_seconds)  # fmt: skip
        if not isinstance(fields.get("names"), list):
            raise BackendError("no valid structured output")
        return fields


SYNONYM_FILE = "indicator-web-names.jsonl"

SYNONYM_PROMPT = """You are given tests as one archive of medical documents has them: a label, and the spellings its own forms have printed. For each, say what the test is usually called and which other names laboratories print for it.

Search the web before answering. Give the names a laboratory would actually print: the full name, the usual abbreviation, the name in the languages asked for, and a catalogue's own designation where one exists. Give the catalogue or reference you found them in.

Give only names for the very same measurement. A fraction is not its whole, a calculated rate is not the substance it is calculated from, the same substance in another specimen is another test, and a percentage is not an absolute count. Where the label itself is unclear to you, return no names at all rather than names for a test you guessed at.

Do not repeat a spelling the archive already has. Do not invent a name you did not find."""

SYNONYM_SCHEMA = {
    "type": "object",
    "properties": {
        "tests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string"},
                    "usual_name": {"type": ["string", "null"]},
                    "also_printed_as": {"type": "array", "items": {"type": "string"}},
                    "found_in": {"type": ["string", "null"]},
                },
                "required": ["ref", "usual_name", "also_printed_as", "found_in"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["tests"],
    "additionalProperties": False,
}

SYNONYM_REQUEST = """Tests to look up, one block each.

{tests}"""


def load_web_names(data_dir: Path) -> dict[str, dict]:
    """What the web calls each test, by indicator. Never a mapping by itself; see propose."""
    path = Path(data_dir) / SYNONYM_FILE
    if not path.exists():
        return {}
    return {line["indicator"]: line for line in read_records(path) if line.get("indicator")}


def load_web_checks(data_dir: Path) -> dict[str, dict]:
    """What the web said about each printed name. The last word for a name wins."""
    path = Path(data_dir) / FILE_NAME
    if not path.exists():
        return {}
    return {line["folded"]: line for line in read_records(path) if line.get("folded")}


def names_to_settle(data_dir: Path, printed: list[dict]) -> list[dict]:
    """Printed names whose group holds only them, where no second reader can help.

    A group of two or more spellings is a grouping, and a grouping is judged by comparing the
    spellings with one another, which needs no web at all.
    """
    from epicrisis import indicators

    by_name = {item["folded"]: item for item in printed}
    out = []
    for indicator in indicators.load(data_dir):
        held = [*indicator.names, *indicator.proposed_names]
        if len(held) != 1:
            continue
        folded = held[0]
        item = by_name.get(folded) or {}
        out.append({
            "folded": folded,
            "name": item.get("name", folded),
            "units": item.get("units", []),
            "times": item.get("times", 0),
            "indicator": indicator.id,
            "label": indicator.label,
        })  # fmt: skip
    return out


def settle_names(data_dir: Path, printed: list[dict], backend: WebCheckBackend, workdir: Path,
                 say=lambda text: None, limit: int | None = None) -> dict:  # fmt: skip
    """Ask the web about every single-spelling group. Writes verdicts; changes no indicator."""
    already = set(load_web_checks(data_dir))
    todo = [item for item in names_to_settle(data_dir, printed) if item["folded"] not in already]
    if limit is not None:
        todo = todo[:limit]
    counts = {"names": len(todo), "a test": 0, "not a test": 0, "unclear": 0, "batches": 0}
    for start in range(0, len(todo), BATCH):
        batch = todo[start : start + BATCH]
        by_ref = {str(number): item for number, item in enumerate(batch, start + 1)}
        lines = "\n".join(
            f"{number} | {item['name']} | {', '.join(item['units']) or 'no unit'} | {item['times']}"
            for number, item in enumerate(batch, start + 1)
        )
        fields = backend.settle(lines, workdir)
        counts["batches"] += 1
        for answer in fields["names"]:
            item = by_ref.get(str(answer.get("ref")))
            if item is None or answer.get("verdict") not in VERDICTS:
                continue
            append_line(Path(data_dir) / FILE_NAME, {
                "folded": item["folded"],
                "name": item["name"],
                "indicator": item["indicator"],
                "verdict": answer["verdict"],
                "usual_name": (answer.get("usual_name") or None),
                "found_in": (answer.get("found_in") or "")[:200] or None,
                "why": (answer.get("why") or "")[:300],
                "by": backend.model,
                "prompt_version": PROMPT_VERSION,
                "at": now(),
            })  # fmt: skip
            counts[answer["verdict"]] += 1
        say(f"  names {min(start + BATCH, len(todo))} of {len(todo)}")
    return counts


def tests_to_look_up(data_dir: Path, printed: list[dict]) -> list[dict]:
    """Groups worth asking the web what else they are called: the ones the archive actually uses.

    A group nobody's forms have printed a value for is not worth a search, and a group of a
    single spelling is settled by the other question in this file first.
    """
    from epicrisis import indicators

    by_name = {item["folded"]: item for item in printed}
    out = []
    for indicator in indicators.load(data_dir):
        if indicator.status != "approved" or len(indicator.names) < 1:
            continue
        values = sum((by_name.get(folded) or {}).get("times", 0) for folded in indicator.names)
        if not values:
            continue
        out.append({
            "indicator": indicator.id,
            "label": indicator.label,
            "spellings": [(by_name.get(folded) or {}).get("name", folded) for folded in sorted(indicator.names)],
            "units": sorted({unit for folded in indicator.names for unit in (by_name.get(folded) or {}).get("units", [])}),
            "values": values,
        })  # fmt: skip
    return sorted(out, key=lambda item: -item["values"])


def _test_block(number: int, item: dict) -> str:
    return "\n".join([
        f"ref: {number}",
        f"label: {item['label']}",
        f"printed in this archive as: {', '.join(item['spellings'][:12])}",
        f"units printed: {', '.join(item['units'][:8]) or 'none'}",
    ])  # fmt: skip


def look_up_names(data_dir: Path, printed: list[dict], backend: "WebCheckBackend", workdir: Path,
                  say=lambda text: None, limit: int | None = None) -> dict:  # fmt: skip
    """Ask the web what else each test is called. Writes what it found; changes no indicator.

    Nothing here becomes a spelling the archive uses. A name from a reference is a claim about
    how laboratories write a test, not a thing any form printed, so it is kept apart and shown
    to the model that assigns new printed names — see indicator_proposals — where it helps a
    spelling nobody has seen before land in the right group instead of starting a new one.
    """
    already = set(load_web_names(data_dir))
    todo = [item for item in tests_to_look_up(data_dir, printed) if item["indicator"] not in already]
    if limit is not None:
        todo = todo[:limit]
    counts = {"tests": len(todo), "with_names": 0, "names": 0, "batches": 0}
    for start in range(0, len(todo), BATCH):
        batch = todo[start : start + BATCH]
        by_ref = {str(number): item for number, item in enumerate(batch, start + 1)}
        blocks = "\n\n".join(_test_block(number, item) for number, item in enumerate(batch, start + 1))
        fields, _ = run_claude(
            web_command(backend.executable, backend.model, SYNONYM_PROMPT, SYNONYM_SCHEMA),
            SYNONYM_REQUEST.format(tests=blocks), workdir, backend.timeout_seconds,
        )  # fmt: skip
        if not isinstance(fields.get("tests"), list):
            raise BackendError("no valid structured output")
        counts["batches"] += 1
        for answer in fields["tests"]:
            item = by_ref.get(str(answer.get("ref")))
            if item is None:
                continue
            held = {fold(name) for name in item["spellings"]}
            found = [name for name in (answer.get("also_printed_as") or []) if fold(name) not in held and name.strip()]
            append_line(Path(data_dir) / SYNONYM_FILE, {
                "indicator": item["indicator"],
                "label": item["label"],
                "usual_name": answer.get("usual_name") or None,
                "also_printed_as": found[:20],
                "found_in": (answer.get("found_in") or "")[:200] or None,
                "by": backend.model,
                "prompt_version": PROMPT_VERSION,
                "at": now(),
            })  # fmt: skip
            counts["with_names"] += 1 if found else 0
            counts["names"] += len(found)
        say(f"  tests {min(start + BATCH, len(todo))} of {len(todo)}")
    return counts
