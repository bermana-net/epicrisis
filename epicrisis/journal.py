"""A record of what went wrong here, and of the few decisions nothing else writes down.

Until now a refusal drew a page and vanished. The page said which file, what was safe and what
put it right — and then nothing on this machine remembered that it had ever happened, so the only
way to look into a fault reported an hour later was to ask the person to make it happen again.
This turns "it did that once" into a line with a time on it.

The pipeline already records its own steps (`ledger.jsonl`), the network its own calls
(`mcp-access.jsonl`), a person's corrections and verdicts their own files. None of that is
repeated here. This holds failures, and the acts that no other file would remember — each of them
a file that holds the answer and writes over the one before it, so that the answer survives and
the fact that somebody gave it does not.

What is kept: the time, the event as a short phrase, the random id of the archive it was about,
the type of the exception, the module and line it was raised at, the name of a file **relative to
the data directory**, an exit code, counts, and the name of a setting with the value it was given
— a rule id, the name of an answer mode, a number of minutes, all of them words of this
program's own (`settings.SAID_IN_FULL` is where that is decided, in one place and by name).

What is never kept: the message of an exception, the label or spelling of any test, the name of
any doctor, laboratory or person, the title of a document, a search, a question put to a model or
its answer, a snippet, a secret. **A log of a medical archive that holds the questions is a second
copy of the archive** — and the same is true of a log holding its answers, its file names, or the
sentences its failures quote.

The measure this module is written to is one sentence: **this file must be safe to paste into a
stranger's chat whole.** `tests/test_journal_shows_nothing.py` builds an archive of deliberately
recognisable strings, breaks it in every way this journal records, and asserts that not one of
those strings reaches a line of it. A field that cannot pass that test is not written.

Why the place in the source instead of the message: a message can quote a document. OSError
carries the name of the file it failed on, and in this archive a file name carries a surname and
often the reason for the visit. "epicrisis/people.py:143" carries nothing of anybody's and tells
whoever is debugging more than the sentence does — it names the one raise site out of the nine
that produce the same words.
"""

import json
import os
import threading
import traceback
from pathlib import Path

from epicrisis import layout, records
from epicrisis.runs import belongs_to_the_folder, write_whole

FILE_NAME = layout.JOURNAL  # layout owns the names; two spellings of one is two files
KEEP_LINES = 5000  # as the access log: months of ordinary use, trimmed when it grows past it
ONLY_THE_OWNER = 0o640  # what went wrong in somebody's archive is theirs, as the access log is
PACKAGE = "epicrisis"
# Where this project is on disk, so that a line of it can be named relative to it rather than by a
# path that says which account installed it. Read from this file's own place and not from the
# working directory, which is wherever the person happened to be standing.
_PACKAGE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PACKAGE_DIR.parent


def path(data_dir: Path) -> Path:
    return Path(data_dir) / FILE_NAME


def record(data_dir: Path, entry: dict) -> None:
    """Append one line. A journal that cannot be written must never stop the program.

    This is called from inside the handlers that answer a failure, and from the one that answers a
    full disk. A journal that raised there would turn the page naming the trouble back into the
    words Internal Server Error — which is the defect those handlers exist to undo. So every
    trouble with the file itself is swallowed, including a data directory that is not there.
    """
    try:
        # Written out before the file is opened. The other way round, an entry holding something
        # json cannot write left an empty journal.jsonl behind — created by the open, never
        # written to, and so never given its mode, because the next line to arrive found a file
        # that already existed and left the mode alone. One bad entry handed the journal to every
        # account on the machine for the rest of its life.
        said = json.dumps({"at": records.now(), **entry}, ensure_ascii=False)
        file = path(data_dir)
        existed = file.exists()
        with file.open("a", encoding="utf-8") as lines:
            lines.write(said + "\n")
        if not existed:
            # What went wrong in somebody's archive is nobody else's business on a shared machine.
            # The same mode as the access log, and for the same reason.
            os.chmod(file, ONLY_THE_OWNER)
            belongs_to_the_folder(file)
        _trim(file)
    except OSError:
        pass
    except Exception:
        # An entry holding something json cannot write is a defect in the caller, and it is still
        # not a reason to take down the page that was answering a failure.
        pass


def went_wrong(data_dir: Path, event: str, trouble: BaseException, **facts) -> None:
    """Record a failure: what it was called, its type, and where in this project it came from."""
    record(data_dir, {"event": event, **trouble_facts(trouble), **facts})


def trouble_facts(trouble: BaseException) -> dict:
    """The type of a failure, where it was raised, and what it was raised from. No message.

    `because` is the type of the exception this one was raised *from*, where there was one: an
    Unreadable raised from a JSONDecodeError and one raised from a UnicodeDecodeError are two
    different faults with one sentence between them.

    `__cause__` only, never `__context__`. A cause is this project saying "from" out loud; a
    context is whatever happened to be being handled somewhere up the stack when this was raised,
    and the first thing it reported was `"because": "EndOfStream"` on every fault that reached the
    dashboard's middleware — the web server's own plumbing, named as the reason a page failed.
    """
    facts = {"kind": type(trouble).__name__}
    at = raised_at(trouble)
    if at:
        facts["at_line"] = at
    if trouble.__cause__ is not None:
        facts["because"] = type(trouble.__cause__).__name__
    return facts


def raised_at(trouble: BaseException) -> str:
    """The module and line a failure came from, as "epicrisis/people.py:143".

    Named relative to the package rather than by its full path: the full one says where this
    program is installed, and under a home directory that is a person's name.
    """
    frames = traceback.extract_tb(trouble.__traceback__)
    if not frames:
        return ""
    last = frames[-1]
    return f"{_module(last.filename)}:{last.lineno}"


def _module(filename: str) -> str:
    """One source file, named from the package down: "epicrisis/people.py", "tests/test_x.py".

    Measured against where this module itself is on disk, not by looking for the word "epicrisis"
    in the path. Both of the obvious ways of looking for it are wrong here, and each was tried:
    the first occurrence gives "epicrisis/epicrisis/people.py" because a clone lives in a folder
    of that name too, and the last occurrence gives
    "epicrisis/.claude/worktrees/agent-…/tests/test_journal.py" when the clone sits inside another
    folder of the name. Either way the folder above the clone comes along, and on the machine this
    runs on the folder above it is somebody's home directory.

    Anything outside this project — the standard library, a dependency, a plugin — is named by its
    base name alone, which is a file of code and nobody's data.
    """
    here = Path(filename).resolve()
    for root, prefix in ((_PACKAGE_DIR, PACKAGE + "/"), (_PROJECT_ROOT, "")):
        try:
            return prefix + here.relative_to(root).as_posix()
        except ValueError:
            continue
    return here.name


# Which (step, archive, place) a failure has already been written down for, since this process
# started. See a_page_would_not_read below for why the journal says each of them once.
_already_said: set[tuple[str, str, str, str]] = set()
_saying = threading.Lock()


def a_page_would_not_read(output: Path, source_id: str, trouble: BaseException, step: str) -> None:
    """A page that could not be turned into text or a picture, from a step of the pipeline.

    Said once per place it is raised from, per archive, per step, per run of this process. Nine
    hundred pages of one archive fail at the same line for the same reason — a signature, a photo
    of a wall, a file whose bytes are not what the inventory hashed — and nine hundred identical
    lines would push every other failure out of a journal that keeps five thousand. What the
    journal is for is "this happened, here, at this line"; how often it happened is already in the
    ledger, page by page, and in what the step prints when it finishes.

    What the page *was* is not written down: not its path, not its hash, not its number. The
    ledger holds all three against the document, and they are the three things that would tie a
    line of this journal back to one person's scan.

    Taken as the archive's own output folder because the steps deepest in the pipeline are handed
    that and never the data directory, and threading one down to them to write a line would be a
    worse trade than reading it back off the path.
    """
    from epicrisis.sources import data_dir_of

    facts = trouble_facts(trouble)
    once = (step, source_id, facts.get("at_line", ""), facts.get("because", ""))
    with _saying:
        if once in _already_said:
            return
        _already_said.add(once)
    record(data_dir_of(Path(output)),
           {"event": "a page could not be read", "archive": source_id, "step": step,
            "said_once": True, **facts})  # fmt: skip


def say_everything_again() -> None:
    """Forget what has been said once, so that a test of it is not quietened by the one before."""
    with _saying:
        _already_said.clear()


def entries(data_dir: Path) -> list[dict]:
    """Every line of the journal that parses, oldest first. A torn one is skipped, not raised."""
    found: list[dict] = []
    try:
        lines = path(data_dir).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return found
    for line in lines:
        try:
            found.append(json.loads(line))
        except ValueError:
            continue
    return found


def last(data_dir: Path) -> dict | None:
    """The most recent line, for the status page. None when nothing has been recorded yet."""
    written = entries(data_dir)
    return written[-1] if written else None


def counts(data_dir: Path) -> dict:
    """How many lines the journal holds, and how many of them are failures.

    A failure is a line carrying the type of an exception; the rest are the acts recorded here
    because nothing else records them. The status page says both, so that "nothing has gone
    wrong" is a sentence a person can read rather than a file they have to open.
    """
    written = entries(data_dir)
    return {"lines": len(written), "troubles": sum(1 for one in written if one.get("kind"))}


def _trim(file: Path) -> None:
    """Keep the newest KEEP_LINES and drop the rest, privately.

    The mode is given again after the write. write_whole writes a new file under a temporary name
    and renames it over this one, so the mode of the file that was here does not survive it: on a
    machine whose umask is the ordinary 022 a trim handed the journal to every account on it. The
    commands and the server set umask 0o077 themselves, which is why this was invisible — but a
    privacy that holds only while an unrelated line stays where it is is not one.
    """
    lines = file.read_text(encoding="utf-8").splitlines()
    if len(lines) <= KEEP_LINES:
        return
    write_whole(file, "\n".join(lines[-KEEP_LINES:]) + "\n")
    os.chmod(file, ONLY_THE_OWNER)
    belongs_to_the_folder(file)
