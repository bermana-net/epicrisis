"""Grouping printed names into indicators, proposed by a model and decided by a person.

Only names go to the model: the printed name, its units and how often it appears. No values, no
dates, no documents. The model suggests which spellings are the same test; nothing it says is
applied until a person approves it on the Indicators page.
"""

import hashlib
import json
from pathlib import Path

from epicrisis import indicators
from epicrisis.indicator_web_check import load_web_names
from epicrisis.engines import engine_name
from epicrisis.classify.backend import STRONG_MODEL, BackendError
from epicrisis.printed_values import fold

BATCH = 60
TIMEOUT_SECONDS = 600

SYSTEM_PROMPT = """You group the names of laboratory and report values as different laboratories printed them, in Russian, Ukrainian, English, Spanish and Greek.

Two names belong together only when they are the same measurement of the same thing:
- The same test in another language or spelling, or with the laboratory's abbreviation, belongs together ("Креатинін", "Creatinina", "CREATININE", "Kreatinin").
- A different test does not, however similar the words: glycated haemoglobin (HbA1c) is not haemoglobin; mean corpuscular haemoglobin (MCH, MCHC) is not haemoglobin; a value in urine is not the same as the value in blood or serum; a calculated rate (eGFR, CKD-EPI) is not the substance it is calculated from; "total" and a fraction of it are different.
- The material matters when the name says it: serum, plasma, urine, stool, saliva.

For every group give a short label in English, in the singular, as a laboratory would name the test.
Assign a name to one of the existing indicators when it is the same test as that indicator; otherwise start a new group.
Leave a name out entirely when you cannot tell what it is; never invent a name that is not in the list.

sure: true when the group is plain from the names themselves, as for a test any laboratory would print the same way. false when you are guessing: an abbreviation that could mean several tests, a row of a table without its heading, a name that could be a different material or fraction. A group marked true is applied to the archive; a group marked false waits for a person."""

SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "existing_indicator": {"type": ["string", "null"]},
                    "names": {"type": "array", "items": {"type": "string"}},
                    "sure": {"type": "boolean"},
                },
                "required": ["label", "existing_indicator", "names", "sure"],
                "additionalProperties": False,
            },
        },
        "unclear": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["groups", "unclear"],
    "additionalProperties": False,
}

REQUEST = """Existing indicators (id, label, example spellings, and where a reference was
consulted, the other names laboratories print for the same test — those are not spellings this
archive holds, they are there so a name you have not seen before can be placed):
{existing}

Names to group, one per line as: name | units | how many times printed
{names}"""

PROMPT_VERSION = hashlib.sha256("\n".join([SYSTEM_PROMPT, json.dumps(SCHEMA, sort_keys=True), REQUEST]).encode()).hexdigest()[:12]


class ProposalBackend:
    def __init__(self, model: str = STRONG_MODEL, executable: str = "claude", timeout_seconds: int = TIMEOUT_SECONDS,
                 data_dir=None):  # fmt: skip
        self.model, self.executable, self.timeout_seconds = model, executable, timeout_seconds
        self.data_dir = data_dir
        self.name = engine_name(data_dir)

    def call(self):
        """Something that can answer one question. What carries it there is chosen in engines."""
        from epicrisis import engines

        return engines.a_call(self.data_dir, model=self.model, timeout_seconds=self.timeout_seconds)

    def group(self, existing: str, names: str, workdir: Path) -> dict:
        fields, _ = self.call().ask(SYSTEM_PROMPT, SCHEMA, REQUEST.format(existing=existing, names=names), workdir)
        if not isinstance(fields.get("groups"), list):
            raise BackendError("no valid structured output")
        return fields


def _also_known_as(looked_up: dict | None) -> str:
    """What a reference says the same test is called, marked as coming from one."""
    names = (looked_up or {}).get("also_printed_as") or []
    return f" | also printed as (from a reference, not from this archive): {', '.join(names[:8])}" if names else ""


def unassigned(data_dir: Path, printed: list[dict]) -> list[dict]:
    known = indicators.assigned_names(data_dir)
    return [item for item in printed if item["folded"] not in known]


def propose_indicators(data_dir: Path, printed: list[dict], backend: ProposalBackend, workdir: Path, say=lambda text: None) -> dict:
    """Group the names no indicator holds yet. Returns counts; nothing is approved here."""
    todo = unassigned(data_dir, printed)
    counts = {"names": len(todo), "added_to_existing": 0, "new_indicators": 0, "waiting": 0, "unclear": 0, "batches": 0}
    for start in range(0, len(todo), BATCH):
        batch = todo[start : start + BATCH]
        # A group is shown with what this archive's own forms printed, and, where a reference was
        # looked up, with the names laboratories are known to print for the same test. The second
        # kind is marked: it is a claim about how a test is written, not a thing any form here
        # printed, and it exists so that a spelling nobody has seen before lands in the right
        # group instead of starting a new one. Nothing from a reference becomes a spelling.
        from_the_web = load_web_names(data_dir)
        existing = "\n".join(
            f"{item.id} | {item.label} | {', '.join(sorted(item.names)[:6])}"
            + _also_known_as(from_the_web.get(item.id))
            for item in indicators.load(data_dir)
        ) or "(none yet)"
        names = "\n".join(f"{item['name']} | {', '.join(item['units']) or 'no unit'} | {item['times']}" for item in batch)
        fields = backend.group(existing, names, workdir)
        counts["batches"] += 1
        counts["unclear"] += len(fields.get("unclear") or [])
        in_batch = {fold(item["name"]): item["name"] for item in batch}
        for group in fields["groups"]:
            wanted = [in_batch[fold(name)] for name in group["names"] if fold(name) in in_batch]
            if not wanted:
                continue
            existing_ids = {item.id for item in indicators.load(data_dir)}
            sure = bool(group.get("sure"))
            if group["existing_indicator"] in existing_ids:
                if sure:
                    indicators.add_names(data_dir, group["existing_indicator"], wanted, reviewed=False)
                    counts["added_to_existing"] += len(wanted)
                else:
                    indicators.propose_names(data_dir, group["existing_indicator"], wanted)
                    counts["waiting"] += len(wanted)
            else:
                indicators.upsert(
                    data_dir, None, group["label"], wanted,
                    status="approved" if sure else "proposed", source="model", reviewed=False,
                )  # fmt: skip
                counts["new_indicators" if sure else "waiting"] += 1
        say(f"  names {min(start + BATCH, len(todo))} of {len(todo)}")
    return counts
