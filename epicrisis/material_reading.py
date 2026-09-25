"""What was measured, where the form did not print it: read by a model, kept apart from the form.

The word a form prints always wins. This is for the rest — 1,691 values in the archive this was
written against, most of them blood and some of them not. Two things made that a problem worth
a model: a chart of blood that quietly leaves out a third of its values is misleading, and a
urine value that slips into blood is worse.

What is sent is a panel, never a person: the heading of the document, the heading of the table
and the names of the values printed under it, with no numbers, no dates and no file names. A
panel is the right unit because a specimen is: one tube goes into one machine and comes back as
one table. Deciding per value would let one table answer two ways.

What comes back is kept in data/sources/<id>/materials.jsonl, beside the corrections and never
inside the transcription, and every value it settles is marked as read by a model rather than
printed, so that a page can say which it is and a person can disagree.

"none" is an answer here, and a common one: a keratometry reading, the width of a ventricle, a
dose of radiation. Those are measured on a person, not in a sample, and calling them blood
would be worse than leaving them alone.
"""

import hashlib
import json
from pathlib import Path

from epicrisis.classify.backend import SMALL_MODEL, BackendError, claude_command, run_claude
from epicrisis.records import append_line, now, read_records
from epicrisis.runs import one_at_a_time

FILE_NAME = "materials.jsonl"
BATCH = 25
TIMEOUT_SECONDS = 600
MATERIALS = ("blood", "urine", "stool", "semen", "swab", "csf", "saliva", "sputum", "none", "unclear")

SYSTEM_PROMPT = """You read the headings of medical laboratory and report tables, in Russian, Ukrainian, English, Spanish and Greek, and say what was measured: which specimen the table's values came from.

Answer for the table as a whole. One table is one specimen.

- blood: anything drawn from a vein or a finger, including serum, plasma, a blood count, biochemistry, coagulation, hormones, serology, tumour markers, vitamins and drug levels. A Spanish "suero" or "Pla-" prefix is blood. A hemogram is blood.
- urine: a general urinalysis, its sediment and its microscopy, a 24-hour collection, a urine culture, an albumin-to-creatinine ratio.
- stool, semen, swab, csf, saliva, sputum: when the table is of that specimen.
- none: the table is not of a specimen at all. Measurements made on the person or on an image belong here: blood pressure, an ultrasound or echocardiogram measurement, keratometry and other eye measurements, a radiation dose, the size of an organ, a scintigraphy curve, a questionnaire score.
- unclear: you cannot tell from what you are given.

Judge from the headings and the names of the values together. Names decide when a heading says nothing: casts, urinary sediment, epithelium, nitrite and specific gravity belong to urine; MCV, MCH, RDW, a leucocyte formula, ALT, AST, creatinine, cholesterol and HbA1c belong to blood.

Beware of names that mention a material without being of it: "Реакція на приховану кров" and "Occult Blood" are printed on a form for stool; "Кров" on a urine strip is a test of urine; urea and uric acid are blood tests whose Russian names contain the word for urine.

sure: true when the table is plain from what you are given. false when you are guessing. Say unclear rather than guessing at a material you cannot see."""

SCHEMA = {
    "type": "object",
    "properties": {
        "panels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string"},
                    "material": {"type": "string", "enum": list(MATERIALS)},
                    "sure": {"type": "boolean"},
                    "why": {"type": "string"},
                },
                "required": ["ref", "material", "sure", "why"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["panels"],
    "additionalProperties": False,
}

REQUEST = """Tables to read. One block each, starting with its ref.

{panels}"""

PROMPT_VERSION = hashlib.sha256("\n".join([SYSTEM_PROMPT, json.dumps(SCHEMA, sort_keys=True), REQUEST]).encode()).hexdigest()[:12]


class MaterialBackend:
    name = "claude-code-subscription"

    def __init__(self, model: str = SMALL_MODEL, executable: str = "claude", timeout_seconds: int = TIMEOUT_SECONDS):
        self.model, self.executable, self.timeout_seconds = model, executable, timeout_seconds

    def read(self, panels: str, workdir: Path) -> dict:
        command = claude_command(self.executable, self.model, SYSTEM_PROMPT, SCHEMA, read_files=False)
        fields, _ = run_claude(command, REQUEST.format(panels=panels), workdir, self.timeout_seconds)
        if not isinstance(fields.get("panels"), list):
            raise BackendError("no valid structured output")
        return fields


def panel_key(file_sha256: str, pages: list[int], table_heading: str | None) -> str:
    """A panel is one table on one document: its values share a specimen and answer together."""
    return "|".join((file_sha256, ",".join(str(page) for page in pages), (table_heading or "").strip().casefold()))


def load_materials(output: Path, sure_only: bool = True) -> dict[str, dict]:
    """What a model has already said about each panel. The last word for a panel wins.

    Only what it was sure of is handed to the index, as with the indicators a model proposes: a
    guess about a specimen would be indistinguishable on the page from the word on a form.
    """
    path = Path(output) / FILE_NAME
    if not path.exists():
        return {}
    latest = {line["panel"]: line for line in read_records(path) if line.get("panel")}
    return {
        key: line
        for key, line in latest.items()
        if line.get("material") not in (None, "unclear", "none") and (line.get("sure") or not sure_only)
    }


def answered(output: Path) -> set[str]:
    """Panels a model has already been asked about, whatever it replied, so none is asked twice."""
    path = Path(output) / FILE_NAME
    return {line["panel"] for line in read_records(path) if line.get("panel")} if path.exists() else set()


def panels_to_read(documents: list[dict]) -> list[dict]:
    """Every table with values whose form printed no material, with what the model is shown."""
    from epicrisis.index.build import material_of

    found: dict[str, dict] = {}
    for document in documents:
        for observation in document.get("observations", []):
            if material_of(observation, document) is not None:
                continue
            key = panel_key(document["file_sha256"], document["pages"], observation.get("table_as_printed"))
            panel = found.setdefault(key, {
                "panel": key,
                "file_sha256": document["file_sha256"],
                "pages": document["pages"],
                "title": document.get("title_as_printed"),
                "table": observation.get("table_as_printed"),
                "names": [],
                "values": 0,
            })  # fmt: skip
            panel["values"] += 1
            name = observation.get("name_as_printed")
            if name and name not in panel["names"]:
                panel["names"].append(name)
    return list(found.values())


def _block(number: int, panel: dict) -> str:
    return "\n".join([
        f"ref: {number}",
        f"document heading: {panel['title'] or '(none printed)'}",
        f"table heading: {panel['table'] or '(none printed)'}",
        f"value names: {', '.join(panel['names'][:40]) or '(none)'}",
    ])  # fmt: skip


def read_materials(output: Path, documents: list[dict], backend: MaterialBackend, workdir: Path,
                   say=lambda text: None, limit: int | None = None) -> dict:  # fmt: skip
    """Ask a model what each unprinted panel was measured in. Writes decisions; changes no values."""
    with one_at_a_time(output / "read-materials.lock", "Reading what these tables measured"):
        return _read_materials(output, documents, backend, workdir, say=say, limit=limit)


def _read_materials(output: Path, documents: list[dict], backend: MaterialBackend, workdir: Path,
                    say=lambda text: None, limit: int | None = None) -> dict:  # fmt: skip
    already = answered(output)
    todo = [panel for panel in panels_to_read(documents) if panel["panel"] not in already]
    if limit is not None:
        todo = todo[:limit]
    counts = {"panels": len(todo), "decided": 0, "waiting": 0, "unclear": 0, "values": 0, "batches": 0}
    for start in range(0, len(todo), BATCH):
        batch = todo[start : start + BATCH]
        by_ref = {str(number): panel for number, panel in enumerate(batch, start + 1)}
        blocks = "\n\n".join(_block(number, panel) for number, panel in enumerate(batch, start + 1))
        fields = backend.read(blocks, workdir)
        counts["batches"] += 1
        for answer in fields["panels"]:
            panel = by_ref.get(str(answer.get("ref")))
            if panel is None or answer.get("material") not in MATERIALS:
                continue
            append_line(Path(output) / FILE_NAME, {
                "panel": panel["panel"],
                "file_sha256": panel["file_sha256"],
                "pages": panel["pages"],
                "table": panel["table"],
                "material": answer["material"],
                "sure": bool(answer.get("sure")),
                "why": (answer.get("why") or "")[:200],
                "values": panel["values"],
                "by": backend.model,
                "prompt_version": PROMPT_VERSION,
                "at": now(),
            })  # fmt: skip
            if answer["material"] == "unclear":
                counts["unclear"] += 1
            elif answer.get("sure"):
                counts["decided"] += 1
                counts["values"] += panel["values"]
            else:
                counts["waiting"] += 1
        say(f"  panels {min(start + BATCH, len(todo))} of {len(todo)}")
    return counts
