"""Extraction backend: whole documents through the same isolated Claude Code call as classify.

The prompt asks for transcription only. Anything computed on top of what is printed (range
flags, trends, age norms, summaries of a person's condition) is forbidden here and belongs to
nobody: the application stores and shows, it does not interpret.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from epicrisis.classify.backend import STRONG_MODEL, BackendError
from epicrisis.classify.pages import Payload

WHAT_THE_VERSION_WAS_TAKEN_FROM = """You transcribe one document from a person's own medical archive into structured fields. You receive its pages in order, numbered from 1. Copy what is printed. Never interpret, never comment on health or findings, never translate, never convert units, never normalise names, values or dates.

Rules:
- Every field ending in _as_printed is copied exactly as printed: the same characters, decimal commas, abbreviations, spelling and language. Use null when the document does not print it.
- observations: one entry for every measured or reported value in results tables and lists. value_numeric only when the number is unambiguous: a decimal comma becomes a dot; for "<0,5" set comparator "<" and value_numeric 0.5. value_kind is quantitative for numbers, qualitative for words or signs such as "negative", "not detected", "+", "traces", and titer for dilutions such as 1:80. Qualitative and titer values have value_numeric null.
- flag_as_printed: only a mark printed next to the value by the laboratory, such as H, L, * or an arrow. Never decide yourself whether a value is outside its reference range.
- name_as_printed is the name of the row exactly as printed. Never add words to it, such as a column heading.
- Tables: the main task is to tell, for every row, which printed column holds the person's own result for that test and which holds the reference range. Headings differ between laboratories and languages ("Result", "Result - Units", "Normal Values", "Ref. Values", "Absolute"); decide by what the column holds, not by its position.
- One observation per value printed in a row, in the order of the columns, all with the same name_as_printed. value_role "result" is the value in the column with the person's result for that test; "other" is any further value in the same row, such as an absolute count next to a percentage, the same result in other units, or an earlier result. A reference range is never an observation of its own: it goes in reference_as_printed of the value it belongs to. unit_as_printed, reference_as_printed and flag_as_printed are those printed for that value only.
- table_as_printed: the heading of the table or block the row belongs to, such as "WHITE BLOOD CELLS" or "BIOCHEMISTRY TESTS", or null. column_as_printed and reference_column_as_printed: the headings of the column holding the value and of the column holding its reference range, exactly as printed, or null when there is no heading.
- page and snippet: the document page number and a short piece of the original line with the value, so a person can find it on the page.
- sections: the headed parts of reports and letters, with the heading as printed and the text word for word.
- page_texts: the complete text of every page, word for word, without shortening or summarising.
- diagnoses_as_printed and medications_as_printed: only what the document prints. Never derive a diagnosis from results.
- unreadable: everything you cannot read reliably, with the page, what it is and why. Leave it out of the other fields rather than guess.
- Do not assess trends, do not choose age norms, do not summarise the person's condition."""

# A second reading of the printed range, by the one reader that has the page in front of it.
#
# Everything after the reading is done without a model, and the printed range is read by a parser
# in reference.py: a hand-written thing that has to know a decimal comma from a thousands
# separator, a unit carrying a power, a word of direction in five languages, a label before the
# range and a titer that only looks like one. It is wrong sometimes, and when it is wrong there is
# nothing to disagree with it, so the band is simply missing or simply wrong and no page says so.
#
# This asks for the same characters as two numbers, which is what value_numeric and comparator
# already are: transcription, not interpretation. Nothing about the person, no judgement of the
# value, no norm chosen — the range the form printed, written as numbers. What it buys is a second
# opinion: where the two readings disagree, that is a finding a person can look at, instead of
# silence. Which of the two draws the band is not decided here and is not decided by this: see the
# rule range_read_two_ways, which only reports the disagreement.
THE_RANGE_AS_NUMBERS = """- reference_low and reference_high: the reference range printed beside this value, as two numbers, in the unit it is printed in. Copy the numbers, do not convert them. "3,5 - 5,5" is 3.5 and 5.5. "< 5,0" is null and 5.0; "> 60" is 60 and null. Both null where the form prints no range beside this value, or prints something that is not one range for this person: a table of ranges by age or sex, a ratio such as 1:80, a share of another measurement, or words. Never choose a range yourself, never pick the line of a table that seems to fit, and never take a range printed for another row."""

SYSTEM_PROMPT = WHAT_THE_VERSION_WAS_TAKEN_FROM + "\n" + THE_RANGE_AS_NUMBERS

NULLABLE_STRING = {"type": ["string", "null"]}
PAGE = {"type": "integer", "minimum": 1}


def _object(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _observation(read_twice: bool) -> dict:
    """The fields of one printed value. Without the second reading of the range, this is the shape
    the prompt version was taken from, and it must stay that shape: see PROMPT_VERSION below."""
    return _object(
    {
        "name_as_printed": {"type": "string"},
        "value_as_printed": {"type": "string"},
        "value_role": {"type": "string", "enum": ["result", "other"]},
        "table_as_printed": NULLABLE_STRING,
        "column_as_printed": NULLABLE_STRING,
        "reference_column_as_printed": NULLABLE_STRING,
        "value_numeric": {"type": ["number", "null"]},
        "comparator": {"type": ["string", "null"], "enum": ["<", "<=", ">", ">=", None]},
        "value_kind": {"type": "string", "enum": ["quantitative", "qualitative", "titer"]},
        "unit_as_printed": NULLABLE_STRING,
        "reference_as_printed": NULLABLE_STRING,
        "flag_as_printed": NULLABLE_STRING,
        "method_as_printed": NULLABLE_STRING,
        "page": PAGE,
        "snippet": {"type": "string"},
        **({"reference_low": {"type": ["number", "null"]},
            "reference_high": {"type": ["number", "null"]}} if read_twice else {}),  # fmt: skip
    }
)


OBSERVATION = _observation(read_twice=True)


def _document(read_twice: bool) -> dict:
    return _object(
    {
        "title_as_printed": NULLABLE_STRING,
        "date_of_study_as_printed": NULLABLE_STRING,
        "date_of_report_as_printed": NULLABLE_STRING,
        "provider_as_printed": NULLABLE_STRING,
        "department_as_printed": NULLABLE_STRING,
        "language": {"type": "string", "pattern": "^[a-z]{2}$"},
        "observations": {"type": "array", "items": _observation(read_twice)},
        "sections": {
            "type": "array",
            "items": _object({"heading_as_printed": NULLABLE_STRING, "text": {"type": "string"}, "page": PAGE}),
        },
        "page_texts": {"type": "array", "items": _object({"page": PAGE, "text": {"type": "string"}})},
        "medications_as_printed": {"type": "array", "items": {"type": "string"}},
        "diagnoses_as_printed": {"type": "array", "items": {"type": "string"}},
        "unreadable": {
            "type": "array",
            "items": _object({"page": PAGE, "what": {"type": "string"}, "why": {"type": "string"}}),
        },
    }
)


DOCUMENT_SCHEMA = _document(read_twice=True)

REQUEST_HEAD = "Transcribe this document. It has {count} pages. Read every page before answering."
IMAGE_LINE = "Page {number}: the image file {name} in the current directory."
TEXT_LINE = "Page {number}: the text between the markers.\n<<<PAGE {number}\n{text}\nPAGE {number}>>>"

# Left out of PROMPT_VERSION on purpose: the close-up pass is recorded in the document's
# provenance, and adding it must not mark every earlier transcription as out of date.
CLOSE_UP_LINE = (
    "Page {number}: the image file {name} in the current directory, with close-ups of the same page "
    "in {close_ups}: top left, top right, bottom left, bottom right. They overlap; use them to read small print "
    "and transcribe every part once."
)

# What decides whether a document already read has to be read again: the model, and this. So a
# change to the prompt that asks for something *beside* what was already transcribed is left out of
# it, for the same reason the close-up line above is. A document read without the range as numbers
# is not wrongly read; marking four hundred of them out of date would send the whole archive through
# a model again — hours and money — and whether to spend that is the owner's decision, not the side
# effect of a field being added. Until they choose it, the two numbers are null on everything read
# before, and the rule that compares the two readings says nothing where one of them is missing.
PROMPT_VERSION = hashlib.sha256(
    "\n".join([WHAT_THE_VERSION_WAS_TAKEN_FROM, json.dumps(_document(read_twice=False), sort_keys=True),
                REQUEST_HEAD, IMAGE_LINE, TEXT_LINE]).encode()  # fmt: skip
).hexdigest()[:12]

LIST_FIELDS = ("observations", "sections", "page_texts", "medications_as_printed", "diagnoses_as_printed", "unreadable")


@dataclass
class Extraction:
    fields: dict
    model: str


def build_request(payloads: list[Payload]) -> str:
    lines = [REQUEST_HEAD.format(count=len(payloads))]
    for number, payload in enumerate(payloads, 1):
        if payload.close_ups:
            names = ", ".join(path.name for path in payload.close_ups)
            lines.append(CLOSE_UP_LINE.format(number=number, name=payload.image_path.name, close_ups=names))
        elif payload.image_path is not None:
            lines.append(IMAGE_LINE.format(number=number, name=payload.image_path.name))
        else:
            lines.append(TEXT_LINE.format(number=number, text=payload.text or ""))
    return "\n\n".join(lines)


class ClaudeCodeExtractBackend:
    name = "claude-code-subscription"

    """The values of one document, read out of its pages. The carrying is the engine's business."""

    MOST_TOKENS = 16384  # a long panel is a long answer; cut short, it is no answer at all

    def __init__(self, model: str = STRONG_MODEL, executable: str = "claude", timeout_seconds: int = 900,
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

    def extract(self, payloads: list[Payload], workdir: Path) -> Extraction:
        images = tuple(path for payload in payloads
                       for path in ([payload.image_path, *payload.close_ups] if payload.image_path else []))  # fmt: skip
        fields, model = self.call.ask(SYSTEM_PROMPT, DOCUMENT_SCHEMA, build_request(payloads), workdir, images)
        if any(not isinstance(fields.get(name), list) for name in LIST_FIELDS):
            raise BackendError("no valid structured output")
        return Extraction(fields=fields, model=model)


class ExtractLadder:
    """Stages tried in order for a document: each result is checked, a failed check moves on.

    `model` names the ladder in the ledger. Documents done by the last stage alone count as done.
    """

    def __init__(self, *stages):
        self.name = stages[0].name
        self.stages = stages
        self.model = ">".join(stage.model for stage in stages)
        self.accepted_models = {self.model, stages[-1].model}


def default_extract_backend(data_dir=None) -> ExtractLadder:
    """The two passes, as the person chose them. Kept as a name; the choosing lives in engines."""
    from epicrisis import engines

    return engines.extractor(data_dir)
