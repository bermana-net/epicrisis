"""Questions about the archive, answered by Claude Code through the read-only MCP tools.

A question goes to one isolated Claude Code call with the epicrisis MCP server and nothing else:
no files, no shell, no network. The model reads the index through the tools and answers with
what is printed, naming the documents. Conversations are kept in data/chats/<id>.json.

The feature is off until it is turned on for an instance: an answer written from a person's own
records is a step the application does not take on its own.
"""

import json
import os
import re
import subprocess
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from epicrisis import layout, records
from epicrisis.runs import copy_whole, write_whole
from epicrisis.settings import answer_mode
from epicrisis.state import Unreadable

# layout owns the name, and this one matters more than most: layout.CHATS is in
# THEIR_OWN_WORK, so the name backup looks for a person's conversations under and the name
# this module writes them under have to be one name. Two literals that drift apart would
# leave the backup taking nothing and saying "none of these in this instance yet".
CHATS_DIR = layout.CHATS
TIMEOUT_SECONDS = 600
MAX_HISTORY = 12

SHARED_RULES = """You answer questions about one person's own medical archive, using only the epicrisis tools. The person asking is the person the records are about.

- Answer from the tools. Never answer from memory, and say plainly when the archive does not hold something.
- Quote values exactly as printed, with the unit and the reference range printed on the same form. Never convert units silently; if you compare values in different units, say what you did.
- Name the document behind every number: file id and date, for instance `4e772722`, 03.02.2026.
- Watch what the data says about itself: copies of one document, values a lab calculated (derived), parts that could not be read, dates marked to check. Mention it when it affects the answer.
- Answer in the language of the question."""

# How long an answer is, and what it ends with. Nothing here is about what may be said in one:
# the substance is decided by the three sets of rules around it and a question of length is not a
# reason to go near any of them. A third of the wait on an answer was the writing of it — 23.4 s
# of 37.2 s on one measured question, for 3 836 characters nobody had asked to be that long.
#
# What a short answer should look like is the owner's own answer and not this program's guess at
# it: a short answer, and under it a few named ways to go further. They are plain lines he reads
# and asks for, not links: a link would mean either the model writing an address the page follows
# or the page deciding which of the model's sentences are offers, and that guess is wrong the
# first time a model writes them another way.
HOW_LONG = """
- Answer short. The fewest lines that answer the question asked: no preamble, no restatement of the question, no account of which tools you used, no closing summary. Where numbers are being compared, a small table rather than paragraphs. Short never means dropping the document behind a number, the unit and the printed range beside a value, or anything else these rules ask for — it means fewer words around them.
- Then, under the answer and after a blank line, offer up to three ways to go further: one line each, each either a question the person can ask you next or a subject of this archive that could be opened up, and each one something you actually read while answering this question. Name the subject, the document or the test, in the order you came across them rather than by how notable they look. Nothing else belongs in those lines: no number, no finding, no reading of a value, and nothing the archive has not shown you."""

AS_PRINTED_RULES = """
- Never say whether a value is normal, high or low, never explain what a result means for health, never diagnose, and never advise treatment or tests. A person's doctor does that. If you are asked for it, say that the archive shows the values and their printed ranges, and that their meaning is for a doctor.
- Do not select, rank or highlight values by how notable they look. Return what was asked for, in the order it is printed or by date. Choosing what stands out is already a reading."""

WITH_MEANING_RULES = """
- This instance is turned on for the person's own use, so you may go past what is printed: compare a value with the range printed on its own form, describe how values moved over time, explain in plain words what a test measures, and say what would be worth asking a doctor.
- Keep the two apart in the answer: first what the documents print, then, marked as your reading, anything you add. Never present your reading as a result from a document.
- A printed reference range is the laboratory's general-population range. It may not apply to this person: age, body composition, a long-standing condition or a medication can move what is normal for them. Say so where it matters, and never read "inside the printed range" as "fine".
- Do not tell the person to start, stop or change a medication, and do not tell them whether to seek care now or later. Saying that something is worth raising with a doctor is fine; ranking how urgently is not.
- You are not a doctor and you do not have the person's history beyond these files: no diagnosis, no prescription, no dosage, no urgency ratings. Say plainly when something needs a doctor, and say when the archive is not enough to tell."""

DIRECT_PROMPT = """You are talking with the person whose medical archive this is, and the epicrisis tools read that archive: their own documents, transcribed page by page, with every value as printed.

How you handle the records does not change here:
- Answer from the tools where the answer is in the archive, and say plainly when it is not. Never answer from memory.
- Quote values exactly as printed, with the unit and the reference range printed on the same form. Never convert units silently.
- Name the document behind every number: file id and date.
- Watch what the data says about itself: copies of one document, values a lab calculated, parts that could not be read, dates marked to check.

What you may say about them does change. This instance sets no limits on that: answer as you would anywhere else, in the language of the question."""


def system_prompt(mode: str) -> str:
    """direct: Claude itself, told only where the archive is. The other two hold it to the records.

    How long the answer is comes last and is the same sentence in all three, because the length of
    an answer is not one of the three things the modes differ about.
    """
    if mode == "direct":
        return DIRECT_PROMPT + "\n" + HOW_LONG  # the one prompt that ends in prose, not in a list
    return SHARED_RULES + (WITH_MEANING_RULES if mode == "with_meaning" else AS_PRINTED_RULES) + HOW_LONG


class _TheWait:
    """Where the wait on one answer went, by this program's own clock on the events as they arrive.

    A conversation used to record one number for the whole answer and a list of steps with no
    clock on them, so the only way to learn why an answer took ninety-two seconds was to ask the
    same question over again with every event timestamped — a second run on the owner's own
    subscription, and more of his waiting, to find out about the first. Measured that way once: of
    65.30 s, the thirteen calls to the archive were 0.22 s, about twenty milliseconds each, and
    the model held the other 99 %. The database is not the wait, and a page that cannot say so
    costs a run to prove it.

    Nothing here is a model's word about itself: no model is asked how long it thought. These are
    arrival times of lines this program reads off a subprocess it started itself, which is why
    they may be recorded and shown — `why_it_failed` keeps a model's sentences out of a reason,
    and a clock is not a sentence.
    """

    def __init__(self, started: datetime) -> None:
        self.started = started
        # The model has the question from the start, and has it again from every answer the
        # archive gives back. None while the archive is the one being waited for.
        self.free_at: datetime | None = started
        self.waiting: list[tuple[int, datetime]] = []
        self.after: int | None = None
        self.archive = 0.0
        self.model = 0.0
        self.writing: float | None = None
        self.timed = False

    def ready(self, at: datetime) -> None:
        """The subprocess is up and the tools are handed over, so the model's own time starts here.

        Without this the starting of a process and the MCP handshake would be counted as the model
        thinking: 1.06 s of the 65.30 s, which is small and is not the model's.
        """
        self.free_at = at

    def asked(self, at: datetime, steps: list, step: dict) -> dict:
        """One call going out to the archive, and the step to store for it.

        The index this step is about to take is the length of the list it has not been appended to
        yet, which is what pairs an answer with the call it answers. Calls are paired oldest
        first, so a turn that asks for two tools at once still gets a time each.
        """
        if self.free_at is not None:
            thought = (at - self.free_at).total_seconds()
            if self.after is not None:
                steps[self.after]["then_seconds"] = round(thought, 1)
            self.model += thought
            self.free_at = None
        self.waiting.append((len(steps), at))
        return {**step, "asked_after": round((at - self.started).total_seconds(), 1)}

    def answered(self, at: datetime, steps: list) -> None:
        """The archive has answered the oldest call still out."""
        if not self.waiting:
            return
        index, asked_at = self.waiting.pop(0)
        took = (at - asked_at).total_seconds()
        self.archive += took
        if index < len(steps):
            steps[index]["archive_seconds"] = round(took, 3)
        self.timed = True
        if not self.waiting:
            self.free_at, self.after = at, index

    def wrote(self, at: datetime, steps: list) -> None:
        """The answer arrived. What came before it was the model writing: a third of the wait."""
        if self.free_at is None:
            return
        self.writing = (at - self.free_at).total_seconds()
        self.model += self.writing
        if self.after is not None and self.after < len(steps):
            steps[self.after]["then_seconds"] = round(self.writing, 1)
        self.free_at = None

    def where_it_went(self, waited: float) -> dict:
        """The wait divided into the three things it is spent on, adding up to the whole of it.

        Three measured numbers rounded apart print as a whole that is a tenth of a second short of
        itself, and a count that disagrees with another count on the same page is a defect by the
        seventh entry. So the archive and the model are rounded and the rest — starting the
        process, the handshake, saving the conversation between events — is the remainder of the
        whole wait, which is what it is anyway. The page prints that wait rounded to a second in
        front of the three, as it has since before the three existed.

        Nothing at all where no call to the archive was ever timed: a conversation showing "the
        archive 0.0 s of it" would be stating a measurement nobody made.
        """
        if not self.timed:
            return {}
        archive, model = round(self.archive, 2), round(self.model, 1)
        rest = round(round(waited, 1) - archive - model, 2)
        if rest < 0:
            model, rest = round(round(waited, 1) - archive, 1), 0.0
        where = {"archive_seconds": archive, "model_seconds": model, "rest_seconds": rest}
        if self.writing is not None:
            where["writing_seconds"] = round(self.writing, 1)
        return where


def _answering_model(data_dir: Path) -> str:
    """A question is thinking work, so it goes to whichever model does the strong pass."""
    from epicrisis.models import model_for

    return model_for(data_dir, "strong")


def chats_dir(data_dir: Path) -> Path:
    path = Path(data_dir) / CHATS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _the_archives(data_dir: Path) -> list:
    """The archives this instance holds, in the order they were added."""
    from epicrisis.sources import SourceRegistry

    return SourceRegistry(Path(data_dir)).list()


def _one_archive_or_none(sources: list, chat: dict) -> tuple[str | None, str]:
    """Which archive a conversation is about, and where nothing settles it, why not.

    The one place that decides it. `whose_archive` asks it in order to answer a question out of an
    archive; `_belongs` asks it in order to show the conversation in one. Those are the same
    question from the two sides and they have to give the same answer, and two functions used to
    answer it apart:

    - `answer` read `archive_id`, found it empty on every conversation older than that field, and
      handed the tools no archive at all — after which the server answering them took whichever
      archive was open at that moment, with a question taking tens of seconds and the archive
      switchable from any page in another tab meanwhile. Three of the five conversations on the
      instance this was found on record a name and no id.
    - And a name two archives answer to settled nothing here while showing the conversation in
      both: its title, the questions a person asked about their own health and the answers
      quoting their values, on the page of somebody else's archive. A person keeping the archive
      of a parent and of a child of one name is not an odd case.

    The archive is recorded by its id, which is random and never changes. Chats written before
    that field recorded the owner's name instead, and a name is neither unique nor fixed: renaming
    an owner orphaned their conversations, and two people of one name shared theirs. Those chats
    are still read by name, because that is all they say about themselves — but only where exactly
    one archive answers to it.

    Where the conversation says nothing at all, it was the only archive there when nothing had to
    be written down, so it is the oldest one here and no other. Where what it says names no
    archive on this list, or names a name more than one archive answers to, nothing settles it:
    a guess about whose records these are is the one guess this program never makes.
    """
    if chat.get("archive_id"):
        if any(source.id == chat["archive_id"] for source in sources):
            return chat["archive_id"], ""
        return None, "the archive it was about is not on this list any more"
    if chat.get("archive"):
        named = [source for source in sources if source.whose == chat["archive"]]
        if len(named) == 1:
            return named[0].id, ""
        return None, ("no archive on this list is of that name" if not named
                      else "more than one archive on this list is of that name")  # fmt: skip
    if sources:
        return sources[0].id, ""
    return None, "there is no archive on this list at all"


def _belongs(chat: dict, owner, sources: list) -> bool:
    """Whether this conversation is shown in that archive: the one it is answered from, and no other.

    Asked of `_one_archive_or_none`, so that "shown in" and "answered from" cannot drift apart
    again. A conversation nothing on the list settles is shown nowhere, which is the half of this
    that was wrong: it was shown in every archive of the name it recorded.
    """
    if owner is None:
        return True
    answered_from, _why_not = _one_archive_or_none(sources, chat)
    if answered_from is None:
        return False
    wanted_id = getattr(owner, "id", None)
    if wanted_id is None:
        # An owner given by name rather than as an archive, which this store still allows. The
        # name has to be the name of the archive the conversation is answered from, and that
        # archive has to be the only one of it — which is what the decider above has settled.
        return any(source.id == answered_from and source.whose == owner for source in sources)
    return answered_from == wanted_id


def whose_archive(data_dir: Path, chat: dict) -> tuple[str | None, str]:
    """Which archive a conversation is answered out of, and where nothing settles it, why not."""
    return _one_archive_or_none(_the_archives(data_dir), chat)


def _nobody_to_ask(data_dir: Path, chat: dict, why: str) -> str:
    """Why a conversation cannot be answered: the file it is in, what is safe, what puts it right.

    A conversation nothing on this list settles is not a conversation to answer from the archive
    that happens to be open, and not one to answer from the oldest archive either — that would be
    a guess about whose records these are. So it is refused, and a refusal with no way out of it
    is a defect of its own: this one says where every word of the conversation still is.
    """
    said = chat.get("archive") or ""
    return (
        f"This conversation cannot be answered: {why}"
        + (f' (it names "{said}")' if said else "")
        + f". Nothing in it is lost — every question and answer is in {chats_dir(data_dir) / f'{_safe(chat['id'])}.json'}"
        + ", and no archive was touched. Put that archive back on the Archive status page and ask "
        "again, or ask the question in a new conversation on the Ask page of the archive you mean."
    )


def _read_one(path: Path) -> dict:
    """One conversation off the disk, or a refusal naming it. Never an answer of nothing.

    layout.CHATS is in THEIR_OWN_WORK and this was the one reader there that did not refuse. A
    torn conversation dropped out of the list without a word and `load_chat` answered None, which
    is the shape the eighth entry of the constitution names: `answer` reads, changes and saves on
    every event of a running answer and falls back to the copy it holds where the read gives
    nothing, so the file was written over with whatever happened to be in memory. An empty read
    writing the emptiness back, over the questions a person asked about their own health.

    people.load and indicators.load have refused this since the day it happened to each of them,
    and this module was reached last — which is the argument for the three of them saying one
    thing in one voice.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as torn:
        raise Unreadable(
            f"{CHATS_DIR}/{path.name}",
            "Every question and every answer in it is still in that file, and no archive was touched.",
            # The version before the last save, and the advice has to say there may be none: the
            # copy is kept only where a file was already there, so the very first save of a new
            # conversation leaves none. What to do instead costs that one conversation, so it is
            # said plainly rather than implied.
            f"Repair it, or copy back {path.name}.previous beside it, written every time this "
            f"conversation is saved. If there is no .previous, this was its first save: move the "
            f"file out of the {CHATS_DIR} folder and every other conversation answers as before, "
            f"with that one lost.",
        ) from torn


def list_chats(data_dir: Path, owner: str | None = None) -> list[dict]:
    """Conversations about one archive. Chats about another person's records are another list."""
    sources = _the_archives(data_dir) if owner is not None else []
    chats = []
    for path in sorted(chats_dir(data_dir).glob("*.json")):
        # A torn one refuses here rather than leaving a gap in the list: these are a person's own
        # questions, and a list quietly one conversation short is how nobody notices. See _read_one.
        chat = _read_one(path)
        # Shown in the one archive it is answered out of, which `_one_archive_or_none` settles:
        # a chat from before archives had owners belongs to the archive that was there then.
        if not _belongs(chat, owner, sources):
            continue
        chats.append({"id": chat["id"], "title": chat["title"], "updated_at": chat["updated_at"], "messages": len(chat["messages"])})
    return sorted(chats, key=lambda chat: chat["updated_at"], reverse=True)


def load_chat(data_dir: Path, chat_id: str, owner: str | None = None) -> dict | None:
    """One conversation, and only if it is about the archive being asked for.

    The list of chats is filtered by whose archive they are about; a chat fetched by its own id
    was not, so another person's conversation opened by its address alone and stayed open when
    the archive was switched under it. An owner given here is the only one whose chats come
    back, and a chat about somebody else answers exactly as one that does not exist.
    """
    path = chats_dir(data_dir) / f"{_safe(chat_id)}.json"
    if not path.exists():
        # Missing is not torn. A conversation that was deleted, or an address somebody typed, is
        # not there and that is the whole answer; a file that is there and will not parse is the
        # other thing entirely, and _read_one says so.
        return None
    chat = _read_one(path)
    # A chat written before archives had owners belongs to the archive that was there then.
    if not _belongs(chat, owner, _the_archives(data_dir) if owner is not None else []):
        return None
    return chat


def delete_chat(data_dir: Path, chat_id: str) -> bool:
    """Remove a chat for good. Only the conversation goes; the archive is untouched."""
    path = chats_dir(data_dir) / f"{_safe(chat_id)}.json"
    if not path.is_file():
        return False
    path.unlink()
    return True


def new_chat(data_dir: Path, owner=None) -> dict:
    """A conversation about one archive, recorded by that archive's id as well as its name.

    The name is kept for a person reading the file; the id is what decides whose it is.
    """
    chat = {"id": uuid.uuid4().hex[:12], "title": "New question", "created_at": records.now(), "updated_at": records.now(),
            "messages": [], "archive": getattr(owner, "whose", owner) or "",
            "archive_id": getattr(owner, "id", "") or ""}  # fmt: skip
    _save(data_dir, chat)
    return chat


def carried_questions(chat: dict) -> int:
    """How many earlier questions of this chat a next question would take with it."""
    return sum(1 for message in chat["messages"][-MAX_HISTORY:] if message["role"] == "person")


def running(chat: dict) -> bool:
    return bool(chat["messages"]) and chat["messages"][-1].get("state") == "running"


def ask(data_dir: Path, chat_id: str, question: str, run=None) -> dict | None:
    """Add a question to a chat and start answering it in the background."""
    chat = load_chat(data_dir, chat_id)
    if chat is None or running(chat) or not question.strip():
        return chat
    chat["messages"].append({"role": "person", "text": question.strip(), "at": records.now()})
    chat["messages"].append({"role": "claude", "text": "", "at": records.now(), "state": "running", "steps": [], "mode": answer_mode(data_dir)})
    if chat["title"] == "New question":
        chat["title"] = question.strip()[:80]
    chat["updated_at"] = records.now()
    _save(data_dir, chat)
    worker = threading.Thread(target=run or answer, args=(data_dir, chat["id"]), daemon=True)
    worker.start()
    return chat


def answer(data_dir: Path, chat_id: str) -> None:
    """Run the model for the last question of a chat, recording its steps as they arrive."""
    chat = load_chat(data_dir, chat_id)
    if chat is None:
        return
    # The archive this conversation belongs to, handed to the tools rather than looked up by
    # them. A question takes tens of seconds to answer, and the archive can be switched from
    # any page in another tab meanwhile — after which the rest of the answer was read out of
    # somebody else's records and written into a conversation filed under the first person.
    #
    # Which archive that is, is the same question `_belongs` answers to decide who may read this
    # conversation, and `_one_archive_or_none` is the one place both of them ask. This line used
    # to read the id and stop,
    # so every conversation older than that field — the ones recording the owner's name, and the
    # ones recording nothing because there was nobody else to record — handed the tools no archive
    # and met exactly the failure the paragraph above describes.
    pinned_to, why_not = whose_archive(data_dir, chat)
    if pinned_to is None:
        chat["messages"][-1].update(state="failed", error=_nobody_to_ask(data_dir, chat, why_not))
        chat["updated_at"] = records.now()
        _save(data_dir, chat)
        return
    started = datetime.now(UTC)
    wait = _TheWait(started)
    try:
        for event in _stream(data_dir, _prompt(chat, what_the_archive_holds(data_dir, pinned_to)),
                             chat["messages"][-1].get("mode", "as_printed"), pinned_to=pinned_to):  # fmt: skip
            # Taken here, where every engine's events arrive, rather than inside either of them:
            # one clock over one answer, and a conversation answered over the API records the same
            # three numbers as one answered by Claude Code on this machine.
            at = datetime.now(UTC)
            chat = load_chat(data_dir, chat_id) or chat
            message = chat["messages"][-1]
            if event["kind"] == "ready":
                wait.ready(at)
            elif event["kind"] == "tool":
                message["steps"].append(wait.asked(at, message["steps"], event["step"]))
            elif event["kind"] == "answered":
                # The steps are read back off the disk on every event, so the step a time belongs
                # on is found by its place in the list and never by holding on to the dict.
                wait.answered(at, message["steps"])
            elif event["kind"] == "answer":
                message["text"] = event["text"]
                wait.wrote(at, message["steps"])
            elif event["kind"] == "error":
                message["state"], message["error"] = "failed", event["text"]
            chat["updated_at"] = records.now()
            _save(data_dir, chat)
    except Exception as exc:  # the reason only, never model output
        chat = load_chat(data_dir, chat_id) or chat
        chat["messages"][-1].update(state="failed", error=why_it_failed(exc))
        _save(data_dir, chat)
        return
    chat = load_chat(data_dir, chat_id) or chat
    message = chat["messages"][-1]
    if message.get("state") == "running":
        message["state"] = "done" if message["text"].strip() else "failed"
    waited = (datetime.now(UTC) - started).total_seconds()
    message["seconds"] = round(waited)
    message.update(wait.where_it_went(waited))
    chat["updated_at"] = records.now()
    _save(data_dir, chat)


def _stream(data_dir: Path, prompt: str, mode: str = "as_printed", pinned_to: str | None = None):
    """Whichever engine this instance is set to. Both yield the same events.

    The page that draws a conversation never learns which one answered it, and the task given to
    the model is the same words either way: where a question may be answered, and what may be
    said about a value, is decided in one place.
    """
    from epicrisis import engines

    if engines.chosen_engine(data_dir) == engines.ANTHROPIC_API:
        from epicrisis.conversing import through_the_api

        call = engines.a_call(data_dir, "strong")
        yield from through_the_api(data_dir, prompt, system_prompt(mode), call, pinned_to=pinned_to)
        return
    yield from _through_claude_code(data_dir, prompt, mode, pinned_to=pinned_to)


def _through_claude_code(data_dir: Path, prompt: str, mode: str = "as_printed", pinned_to: str | None = None):
    served = ["mcp", "--data-dir", str(Path(data_dir).resolve())]
    if pinned_to:
        served += ["--source", pinned_to]
    config = {"mcpServers": {"epicrisis": {"command": _executable(), "args": served}}}
    command = [
        "claude", "-p",
        "--model", _answering_model(data_dir),
        "--output-format", "stream-json", "--verbose",
        "--no-session-persistence", "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands",
        "--mcp-config", json.dumps(config),
        "--tools", "", "--allowedTools", "mcp__epicrisis",
        "--system-prompt", system_prompt(mode),
    ]  # fmt: skip
    # A key meant for the other engine is kept out of here: a question asked under a
    # subscription must not quietly bill a key that happens to be on the machine.
    from epicrisis.engines import KEYS_THE_OTHER_ENGINE_USES

    environment = {
        **{name: value for name, value in os.environ.items() if name not in KEYS_THE_OTHER_ENGINE_USES},
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1",
    }  # fmt: skip
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=environment
    )
    try:
        process.stdin.write(prompt)
        process.stdin.close()
        for line in process.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            yield from _events(event)
    finally:
        process.stdout.close()
        try:
            process.wait(timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()


def _events(event: dict):
    """The lines of the stream this program cares about, and the clock is kept by the caller.

    Two of these are nothing but a moment in time. `ready` is the handshake done, which keeps the
    starting of a process out of the model's share of the wait; `answered` is a tool result coming
    back, which is the only way to know what the archive itself took — 0.3 % of it, when it was
    finally measured.
    """
    if event.get("type") == "system" and event.get("subtype") == "init":
        yield {"kind": "ready"}
    elif event.get("type") == "assistant":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_use":
                yield {"kind": "tool", "step": {"tool": block["name"].removeprefix("mcp__epicrisis__"), "input": block.get("input", {})}}
    elif event.get("type") == "user":
        for block in event.get("message", {}).get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                yield {"kind": "answered"}
    elif event.get("type") == "result":
        if event.get("is_error") or event.get("subtype") != "success":
            yield {"kind": "error", "text": str(event.get("subtype") or "failed")}
        else:
            yield {"kind": "answer", "text": event.get("result") or ""}


def why_it_failed(trouble: Exception) -> str:
    """Why a question could not be answered, in words. Never anything the model wrote.

    The name of the class was the whole message: a page that said "FILENOTFOUNDERROR" and left a
    person to guess that the command this server calls is not installed for the account it runs
    as. The ones worth a sentence get one; anything else keeps its name, which is at least a
    thing to look up.
    """
    if isinstance(trouble, FileNotFoundError):
        return (f"The program that talks to the model was not found on this server "
                f"({trouble.filename or 'claude'}). It has to be installed for the account this "
                "server runs as, and on that account's PATH.")
    if isinstance(trouble, PermissionError):
        return (f"This server may not run the program that talks to the model "
                f"({trouble.filename or 'claude'}): the account it runs as cannot reach it.")
    return type(trouble).__name__


def what_the_archive_holds(data_dir: Path, archive_id: str) -> str:
    """The standing picture of one archive, in the words the question carries out with it.

    `archive_overview` was the first call of almost every conversation — 345 characters of counts,
    a round of the model's own time to decide to ask for it and another to read it, measured at
    4.5 s into a 37 s answer before anything about the question had been asked. It never changes
    between one question and the next, so it goes out with the question instead.

    One archive, named by the id the conversation is pinned to, and the index of that id and no
    other: `query.open_index` gives a named archive its own file or nothing, which is the whole
    guard the first entry of the constitution asks for here. The name is the archive's own, so a
    person reading the file can see whose records the question was asked about — and so that a
    sentence beginning "this is the archive of" is wrong rather than quietly about somebody else.

    Counts, dates and the names of kinds and languages. Nothing read, nothing compared, nothing
    said about a value: the overview tool itself says "counts only", and this is that answer.
    """
    from epicrisis import query
    from epicrisis.sources import SourceRegistry

    held = SourceRegistry(Path(data_dir)).get(archive_id)
    try:
        connection = query.open_index(data_dir, archive_id)
    except Exception:  # noqa: BLE001 - an archive with no readable index is answered by the tools
        # Said by the tools themselves, loudly, on the first call: this is an opening sentence and
        # not a place to refuse from, and a question that could be answered without it still can.
        return ""
    try:
        counts = query.overview(connection)
    finally:
        connection.close()
    kinds = ", ".join(f"{name} {number}" for name, number in (counts.get("types") or {}).items())
    languages = ", ".join(f"{name} {number}" for name, number in (counts.get("languages") or {}).items())
    groups = counts["copy_groups"]
    # An archive whose index is built before anything in it has been read has no documents and no
    # dates at all, and "dated None to None" is the shape that invites a model to say the archive
    # begins in 1970. It is a real state: an archive is added, indexed and read afterwards.
    span = (f", dated {counts['first_date']} to {counts['last_date']}"
            if counts["first_date"] and counts["last_date"] else "")  # fmt: skip
    return (
        f"This is the archive of {held.whose if held else archive_id}. "
        f"{counts['documents']} documents, {counts['transcribed'] or 0} transcribed, "
        f"{counts['without_date'] or 0} with no printed date{span}; "
        f"{counts['values']} printed values in {counts['files']} files; "
        f"{groups} group{'' if groups == 1 else 's'} of copies."
        + (f" Kinds: {kinds}." if kinds else "")
        + (f" Languages: {languages}." if languages else "")
        + f" Indexed {str(counts['built_at'])[:10]}."
        " That is what archive_overview answers, so it need not be asked; the rest is in the other tools."
    )


def _prompt(chat: dict, opening: str = "") -> str:
    lines = [opening] if opening else []
    for message in chat["messages"][-MAX_HISTORY:]:
        if message["role"] == "person":
            lines.append(f"Question: {message['text']}")
        elif message.get("text"):
            lines.append(f"Your earlier answer: {message['text']}")
    return "\n\n".join(lines)


def _executable() -> str:
    import sys

    return str(Path(sys.executable).with_name("epicrisis"))


def _save(data_dir: Path, chat: dict) -> None:
    """Write the whole conversation, keeping the version it replaces beside it.

    The eighth entry of the constitution asks for that copy, and this file of a person's own work
    was the one without it: the sentence a torn conversation refuses with had nothing to offer but
    "repair it by hand". It is a few kilobytes beside a few kilobytes.
    """
    path = chats_dir(data_dir) / f"{_safe(chat['id'])}.json"
    if path.exists():
        copy_whole(path, path.with_name(path.name + ".previous"))
    write_whole(path, json.dumps(chat, ensure_ascii=False, indent=1) + "\n")


def _safe(chat_id: str) -> str:
    return re.sub(r"[^a-z0-9]", "", chat_id.lower())[:32] or "chat"

