"""Where one document ends and the next begins, in a file that is nothing but text.

A scan has pages because somebody printed it on paper. A text file has none: it is a person's
history poured into one file, visit after visit, and this program cuts it into pages itself. Every
cut by a number of characters falls in the middle of something, and then the reader of a page is
asked the one question it cannot answer — is this the first page of a document — with the start of
a visit sitting halfway down. On the first such archive read here, fifteen pages in a row were
called a continuation while each of them carried its own date and its own kind.

So the text is read before it is cut. A small model walks it in windows and names the first line
of every document that begins there; the program finds each of those lines in its own text, and
cuts where they are. A line it cannot find verbatim is not a cut: a boundary this program cannot
point at in the file does not exist. What is left over — a document longer than a page — is cut
at line ends as before, and those pieces stay parts of one document.

What goes to the model is the text of the archive, like every other reading of it, and what comes
back is a list of quotations from that text. Nothing is written into the archive folder.
"""

import hashlib
import json
import re
from pathlib import Path

from epicrisis import layout
from epicrisis.classify.backend import SMALL_MODEL, BackendError
from epicrisis.engines import engine_name
from epicrisis.readers.text import TEXT_PAGE_CHARS, read_text
from epicrisis.parallel import STATE_LOCK, run_parallel
from epicrisis.records import append_line, now, read_records
from epicrisis.runs import put_in_place, temporary_name

FILE_NAME = layout.BOUNDARIES
# Measured on the first text archive: a window of twenty thousand characters took 175 seconds and
# named thirteen documents. The ceiling is the one a reading gets, and a window that reaches it is
# halved and asked twice rather than lost — a window with no answer is not a gap in the markup, it
# is two documents silently joined.
TIMEOUT_SECONDS = 900
SMALLEST_WINDOW_CHARS = 2_500

# How much text one question covers, and how much of the window before it is repeated so that a
# document beginning across a window edge is seen whole by one of the two.
WINDOW_CHARS = 20_000
OVERLAP_CHARS = 1_000
# Two cuts closer than this are one cut: a heading and its own first line, quoted twice.
NEAREST_CUT_CHARS = 200

# A line this many characters of which are one and the same punctuation mark is a rule drawn in
# text: a machine wrote it to fence something off. It may carry words — "====Department====" — and
# that is the most useful kind, because the words say what was fenced.
RULE_RUN = 8
# And a line repeated word for word is a fence of its own, if it is long enough to be a line
# somebody's machine wrote rather than a word standing alone in the middle of a page.
SHORTEST_REPEATED_LINE = 8
# A shape has to happen this often to be the file's own way of separating things, and the pieces it
# makes have to be long enough to be documents rather than lines of a table.
LEAST_TIMES = 3
# Two floors on one question — how long the average piece has to be for the cuts to be documents —
# and they are two numbers because they are asked at two moments. The first keeps a shape out of
# the handful shown to a model at all; the second refuses the shape the model chose. They were one
# named constant and one default argument sitting outside everything that counts the questions
# asked of a file, which is how half of this question could be moved without the step noticing.
LEAST_PIECE_CHARS = 200  # for a shape to be worth putting in front of a model
LEAST_DOCUMENT_CHARS = 1_000  # for the shape it chose to be taken as what divides the documents

# How much of the file is put in front of a model when it is asked which line begins documents:
# this many stretches, of this many characters each. Numbers, and so numbers that decide where the
# file is cut — they are the whole of the evidence the one judgement of this step is made on.
STRETCHES_SHOWN = 3
STRETCH_CHARS = 3_000

SEPARATOR_PROMPT = """A file of a person's medical archive holds many documents one after another. It was written by a machine, and machines fence documents off with a line of their own: a row of signs, sometimes with a word in the middle of it.

You are shown stretches of the file as it stands. Every line that repeats in it as a shape has a letter put in front of it, like [A], and the same letter always means the same shape of line.

Say which letter begins a new document — a new visit, a new report, a new laboratory sheet — rather than dividing one document inside itself.

Read the stretches as a whole before answering. Where two of these lines stand near each other, the one that begins a document is the outer one: a document starts with it, and what follows is its heading, then a line dividing the heading from the body. A line that separates a heading from a body, one section from the next, or one row of a table from another is not an answer — those stand inside a document.

Answer with the letter, or with "none" if none of them begins documents."""

SEPARATOR_SCHEMA = {
    "type": "object",
    "properties": {
        "which": {"type": "string"},
        "why": {"type": "string"},
    },
    "required": ["which", "why"],
    "additionalProperties": False,
}

SEPARATOR_REQUEST = """Stretches of the file, with every repeated line lettered in front of it.

{candidates}"""

SYSTEM_PROMPT = """You are given a stretch of text from one file of a person's own medical archive, in Russian, Ukrainian, English, Spanish or Greek. The file holds many documents one after another, with nothing between them but a line break: discharge summaries, consultations, laboratory sheets, imaging reports, referrals.

Your only task is to say where a document begins. For every document that begins inside this stretch, quote its first line exactly as it stands in the text — the same characters, the same spelling, the same punctuation, no more than one line.

- A document begins at its heading, or at the name of the institution above it, or at the date line that opens it, whichever comes first.
- The stretch you are given starts in the middle of the file. If the text at the very beginning continues a document that began before it, do not report that document: it does not begin here.
- Never invent, shorten, translate or tidy a line. A line that is not in the text word for word is useless, and will be thrown away.
- Say nothing about health, values or findings. You are marking boundaries, not reading results."""

SCHEMA = {
    "type": "object",
    "properties": {
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "first_line": {"type": "string"},
                    "kind": {"type": "string"},
                    "date_as_printed": {"type": ["string", "null"]},
                },
                "required": ["first_line", "kind", "date_as_printed"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["documents"],
    "additionalProperties": False,
}

REQUEST = """The text between the markers. Report every document that begins in it.

<<<TEXT
{text}
TEXT>>>"""

# Every number that decides where a file is cut, named rather than written out again, because
# four of them were not in the version at all. NEAREST_CUT_CHARS merges two cuts into one;
# OVERLAP_CHARS decides whether either of two windows sees a document that begins on their seam;
# SMALLEST_WINDOW_CHARS is the floor under halving a window and asking again; and the floor for
# accepting a separator was a default argument, outside anything that counted the questions.
# Changing any one of them left stored_cuts handing back the old cuts, because the version it
# compares had not moved: a file cut by one threshold, taken as cut by another.
#
# Written as names so that adding a number is one line here rather than a decision to remember,
# and so that a test can move one of them and watch the version move.
CUTTING_NUMBERS = ("WINDOW_CHARS", "OVERLAP_CHARS", "NEAREST_CUT_CHARS", "SMALLEST_WINDOW_CHARS",
                   "RULE_RUN", "SHORTEST_REPEATED_LINE", "LEAST_TIMES", "LEAST_PIECE_CHARS",
                   "LEAST_DOCUMENT_CHARS", "STRETCHES_SHOWN", "STRETCH_CHARS")  # fmt: skip


def prompt_version() -> str:
    """What the questions asked of a file are, as twelve characters: both prompts and every number.

    A markup kept from before is taken as it stands, so what is left out of this is a file cut one
    way and said to have been cut another. The question about the fences was left out of it once,
    and the step answered a file it had never looked at with the walk it had done the day before.

    A function and not only a constant: the constant is read at import and is what the records
    carry, and the function is how a test asks what the version would be if one of these numbers
    moved. The two can never disagree, because the constant is this function's own answer.
    """
    asked = [SYSTEM_PROMPT, json.dumps(SCHEMA, sort_keys=True), REQUEST,
             SEPARATOR_PROMPT, json.dumps(SEPARATOR_SCHEMA, sort_keys=True), SEPARATOR_REQUEST]
    asked += [f"{name}={globals()[name]}" for name in CUTTING_NUMBERS]
    return hashlib.sha256("\n".join(asked).encode()).hexdigest()[:12]


PROMPT_VERSION = prompt_version()

_SPACE = re.compile(r"\s+")


class BoundaryBackend:
    def __init__(self, model: str = SMALL_MODEL, timeout_seconds: int = TIMEOUT_SECONDS, data_dir=None):
        self.model, self.timeout_seconds, self.data_dir = model, timeout_seconds, data_dir
        self.name = engine_name(data_dir)

    def call(self):
        from epicrisis import engines

        return engines.a_call(self.data_dir, model=self.model, timeout_seconds=self.timeout_seconds)

    def read(self, text: str, workdir: Path) -> dict:
        fields, _ = self.call().ask(SYSTEM_PROMPT, SCHEMA, REQUEST.format(text=text), workdir)
        if not isinstance(fields.get("documents"), list):
            raise BackendError("no valid structured output")
        return fields


def separator_shapes(text: str) -> dict[str, list[int]]:
    """Lines that repeat as a shape, and where each of them begins. A file's own fences.

    Two kinds, and the same test for both: did a machine put this line here over and over. A rule
    drawn with one sign repeated — "========" — keeps its sign as its shape, so the same fence with
    a different word in the middle of it counts as one. A line repeated word for word is its own
    shape. Everything else is somebody's sentence and is not a fence.
    """
    shapes: dict[str, list[int]] = {}
    offset = 0
    for line in text.split("\n"):
        drawn = next((mark for mark in "=-_*~#" if mark * RULE_RUN in line), None)
        key = f"a rule of {drawn}" if drawn else (line.strip()
                                                  if len(line.strip()) >= SHORTEST_REPEATED_LINE else None)  # fmt: skip
        if key is not None:
            shapes.setdefault(key, []).append(offset)
        offset += len(line) + 1
    return shapes


def candidate_separators(text: str) -> list[tuple[str, list[int]]]:
    """The shapes that could be what this file separates its documents with, commonest first."""
    found = []
    for shape, places in separator_shapes(text).items():
        if len(places) < LEAST_TIMES:
            continue
        if len(text) / len(places) < LEAST_PIECE_CHARS:
            continue
        found.append((shape, places))
    return sorted(found, key=lambda item: -len(item[1]))


def lettered_stretches(text: str, candidates: list[tuple[str, list[int]]], how_many: int = STRETCHES_SHOWN,
                       length: int = STRETCH_CHARS) -> str:  # fmt: skip
    """Stretches of the file with every candidate line lettered where it stands.

    Shown one at a time, a candidate cannot be told from another: in this archive the rule under a
    record's heading is followed by a dated line in capitals, which reads exactly like the start of
    a document. Shown together, in the text as it stands, the one is plainly inside what the other
    begins. So the evidence is the file, not a page about each candidate.
    """
    where = {at: letter for letter, (_shape, places) in zip("ABCDEFGH", candidates, strict=False) for at in places}
    starts = sorted(candidates[-1][1])  # around the rarest candidate: the others stand near it
    chosen = starts[:: max(1, len(starts) // how_many)][:how_many]
    stretches = []
    for at in chosen:
        start, end = max(0, at - length // 3), at + length
        piece = []
        offset = start
        for line in text[start:end].split("\n"):
            piece.append(f"[{where[offset]}] {line}" if offset in where else line)
            offset += len(line) + 1
        stretches.append("...\n" + "\n".join(piece) + "\n...")
    return "\n\n\n".join(stretches)


def _pieces_look_like_documents(text: str, places: list[int], least: int = LEAST_DOCUMENT_CHARS) -> bool:
    """Whether cutting here leaves pieces that could be documents rather than paragraphs.

    The one judgement in this step is which line begins a document, and it can go wrong: asked
    about this archive, a model first chose the rule that divides a record's heading from its
    body, because a dated line in capitals follows it and reads like the start of something. Four
    hundred and fifty pieces of seven hundred characters are not four hundred and fifty documents.
    """
    return len(text) / max(1, len(places)) >= least


def choose_separator(text: str, candidates: list[tuple[str, list[int]]], backend, workdir: Path) -> int | None:
    """Which candidate begins documents, asked once for the whole file. Nothing is not an answer."""
    lettered = list(zip("ABCDEFGH", candidates, strict=False))
    counted = "\n".join(f"[{letter}] stands {len(places)} times in the file." for letter, (_s, places) in lettered)
    shown = counted + "\n\n" + lettered_stretches(text, candidates)
    fields, _ = backend.call().ask(SEPARATOR_PROMPT, SEPARATOR_SCHEMA,
                                   SEPARATOR_REQUEST.format(candidates=shown), workdir)  # fmt: skip
    said = (fields.get("which") or "").strip().upper()[:1]
    for letter, _ in lettered:
        if letter == said:
            return [letter for letter, _ in lettered].index(letter)
    return None


def windows(text: str, size: int = WINDOW_CHARS, overlap: int = OVERLAP_CHARS) -> list[tuple[int, str]]:
    """The text in overlapping stretches, each with where it starts in the whole."""
    if not text:
        return []
    step = max(1, size - overlap)
    starts = range(0, max(1, len(text) - overlap), step)
    return [(start, text[start : start + size]) for start in starts]


def _loose(text: str) -> str:
    return _SPACE.sub(" ", text).strip().casefold()


def where_it_begins(quoted: str, text: str, window_start: int, window: str) -> int | None:
    """Where a quoted first line stands in the whole text, or nothing where it does not stand.

    Exactly first; then with the spaces of the line treated as one each, which is the one liberty
    a model takes with a line it copies. Anything else is not a boundary: this program will not
    cut a file at a place it cannot point at.
    """
    line = quoted.strip()
    if not line:
        return None
    at = window.find(line)
    if at != -1:
        return window_start + at
    wanted = _loose(line)
    if not wanted:
        return None
    offset = 0
    for piece in window.split("\n"):
        if _loose(piece).startswith(wanted):
            return window_start + offset
        offset += len(piece) + 1
    return None


def cuts_in(text: str, answers: list[tuple[int, str, dict]]) -> tuple[list[int], int]:
    """Where to cut the text, and how many quoted lines were not found in it.

    Always from nought: whatever the first document is, the file begins with it.
    """
    found, lost = {0}, 0
    for window_start, window, fields in answers:
        for item in fields.get("documents", []):
            at = where_it_begins(item.get("first_line", ""), text, window_start, window)
            if at is None:
                lost += 1
            else:
                found.add(at)
    cuts: list[int] = []
    for at in sorted(found):
        if not cuts or at - cuts[-1] >= NEAREST_CUT_CHARS:
            cuts.append(at)
    return cuts, lost


def stored_cuts(output: Path, file_sha256: str) -> list[int] | None:
    """What was read for this file, if it was read with the questions this program asks now."""
    path = Path(output) / FILE_NAME
    if not path.exists():
        return None
    for line in reversed(list(read_records(path))):
        if line.get("file_sha256") == file_sha256 and line.get("prompt_version") == PROMPT_VERSION:
            return line["cuts"]
    return None


def find_boundaries(output: Path, record: dict, archive_root: Path, backend, say=print) -> list[int]:
    """The cuts for one text file: read once, kept, and taken from the store ever after.

    The file is looked at before it is read. A text export is written by a machine, and a machine
    fences its documents off with a line of its own; where such a line is there, the cuts are that
    line, every time it stands, found by counting and not by reading. A model is asked one thing
    only: which of the candidate lines begins documents rather than dividing one inside itself.

    Measured on the first archive this was built for: the file fences its records with
    "====Department====", 256 of them. Walking it in windows and asking a model to quote the first
    line of every document found 67 of those 256, missed 189 and cut 16 times inside a document.
    What a machine wrote down plainly is not worth guessing at.
    """
    file_sha256 = record["sha256"]
    kept = stored_cuts(output, file_sha256)
    if kept is not None:
        return kept

    coding = record.get("text", {}).get("coding")
    data = (archive_root / record["path"]).read_bytes()
    text = data.decode(coding, errors="replace") if coding else read_text(data)[0]

    candidates = candidate_separators(text)
    if candidates:
        which = choose_separator(text, candidates, backend, Path(output))
        if which is not None and _pieces_look_like_documents(text, candidates[which][1]):
            shape, places = candidates[which]
            cuts = sorted({0, *places})
            append_line(Path(output) / FILE_NAME, {
                "file_sha256": file_sha256,
                "cuts": cuts,
                "documents": len(cuts),
                "found_by": "separator",
                "separator": shape,
                "lines_not_found": 0,
                "prompt_version": PROMPT_VERSION,
                "provenance": {"backend": backend.name, "model": backend.model, "at": now()},
            })  # fmt: skip
            say(f"  boundaries: {len(cuts)} documents, cut where the file fences them ({shape}, {len(places)} times)")
            return cuts

    answers: list[tuple[int, str, dict]] = []
    halved = 0

    def ask(start: int, window: str) -> bool:
        """One window, halved and asked again where it does not answer. Never nothing."""
        nonlocal halved
        try:
            fields = backend.read(window, Path(output))
        except BackendError:
            if len(window) <= SMALLEST_WINDOW_CHARS:
                raise
            halved += 1
            middle = window.find("\n", len(window) // 2) + 1 or len(window) // 2
            return ask(start, window[:middle]) and ask(start + middle, window[middle:])
        with STATE_LOCK:
            answers.append((start, window, fields))
        return True

    run_parallel(windows(text), lambda piece: ask(*piece))
    cuts, lost = cuts_in(text, answers)
    append_line(Path(output) / FILE_NAME, {
        "file_sha256": file_sha256,
        "cuts": cuts,
        "documents": len(cuts),
        "found_by": "windows",
        "lines_not_found": lost,
        "windows": len(answers),
        "windows_halved": halved,
        "prompt_version": PROMPT_VERSION,
        "provenance": {"backend": backend.name, "model": backend.model, "at": now()},
    })  # fmt: skip
    say(f"  boundaries: {len(cuts)} documents in one text file, {lost} quoted lines not found in it")
    return cuts


def pages_of(text: str, cuts: list[int]) -> list[tuple[str, int]]:
    """The text as pages, each with the document it belongs to.

    A document is cut further where it is longer than a page: the pieces are pages of that same
    document, and nothing else in the program needs to know that they were ever one.
    """
    from epicrisis.readers.text import text_pages

    pages: list[tuple[str, int]] = []
    edges = list(cuts) + [len(text)]
    for number, (start, end) in enumerate(zip(edges, edges[1:], strict=False)):
        for piece in text_pages(text[start:end]):
            pages.append((piece, number))
    return pages


def put_the_cuts_in_the_inventory(inventory: Path, file_sha256: str, cuts: list[int], pages: list[tuple[str, int]]) -> None:
    """Write the cuts into the record of that file, so every reader of the record sees one file.

    The pages of a file are a fact about the file, and everything downstream asks the inventory
    for them. The record is replaced where it stands, in one write: a half-written inventory is an
    archive that has lost files.
    """
    records = list(read_records(inventory))
    for item in records:
        if item.get("sha256") == file_sha256:
            item["text"] = {**item.get("text", {}), "cuts": cuts, "pages": len(pages),
                            "of_document": [number for _, number in pages]}  # fmt: skip
    # Written the way every file of state here is written, through the one place that does it.
    # This wrote itself instead — a fixed name beside the inventory and a bare rename — and so
    # left out all three things put_in_place is for, on the one file every later step is built
    # from. The contents did not reach the disk before the rename did, which is the failure named
    # in that docstring: a machine losing power in between puts an empty table of the archive's
    # files where the whole one was, atomically. The name was not this process's own, so two
    # writers of the inventory shared one temporary file and the loser's half was what the winner
    # renamed into place. And nothing handed the file back to the person whose archive it is,
    # while this step is started from the dashboard, which runs as root on this machine against
    # data files owned by somebody else: the inventory became root's, and the next command that
    # person ran could not read it. inventory/run.py writes this same file correctly; one writer
    # of it no longer undoes what the other was careful about.
    partial = temporary_name(inventory).with_suffix(".boundaries.partial")
    try:
        with partial.open("w", encoding="utf-8") as fh:
            for item in records:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
        put_in_place(partial, inventory)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def read_boundaries(data_dir: Path, source, backend, say=print) -> int:
    """The boundaries of every text file of an archive. Files of any other kind have their own."""
    from epicrisis.sources import source_output_dir

    output = source_output_dir(data_dir, source.id)
    inventory = output / layout.INVENTORY
    if not inventory.exists():
        return 0
    done = 0
    for record in list(read_records(inventory)):
        if record.get("category") != "text" or "sha256" not in record or "unsupported" in record or "error" in record:
            continue
        if record.get("text", {}).get("cuts") is not None:
            continue
        cuts = find_boundaries(output, record, Path(source.path), backend, say=say)
        data = (Path(source.path) / record["path"]).read_bytes()
        coding = record.get("text", {}).get("coding")
        text = data.decode(coding, errors="replace") if coding else read_text(data)[0]
        put_the_cuts_in_the_inventory(inventory, record["sha256"], cuts, pages_of(text, cuts))
        done += 1
    return done
