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

from epicrisis import records
from epicrisis.runs import put_in_place, temporary_name
from epicrisis.settings import ANSWER_MODES, answer_mode, ask_enabled, settings_path  # noqa: F401

CHATS_DIR = "chats"
TIMEOUT_SECONDS = 600
MAX_HISTORY = 12

SHARED_RULES = """You answer questions about one person's own medical archive, using only the epicrisis tools. The person asking is the person the records are about.

- Answer from the tools. Never answer from memory, and say plainly when the archive does not hold something.
- Quote values exactly as printed, with the unit and the reference range printed on the same form. Never convert units silently; if you compare values in different units, say what you did.
- Name the document behind every number: file id and date, for instance `4e772722`, 03.02.2026.
- Watch what the data says about itself: copies of one document, values a lab calculated (derived), parts that could not be read, dates marked to check. Mention it when it affects the answer.
- Answer in the language of the question. Be brief and concrete; a small table beats a paragraph."""

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
    """direct: Claude itself, told only where the archive is. The other two hold it to the records."""
    if mode == "direct":
        return DIRECT_PROMPT
    return SHARED_RULES + (WITH_MEANING_RULES if mode == "with_meaning" else AS_PRINTED_RULES)


def _answering_model(data_dir: Path) -> str:
    """A question is thinking work, so it goes to whichever model does the strong pass."""
    from epicrisis.models import model_for

    return model_for(data_dir, "strong")


def chats_dir(data_dir: Path) -> Path:
    path = Path(data_dir) / CHATS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _the_first_archive(data_dir: Path):
    """The archive added first: the one a chat written before archives had owners was about.

    Such a chat recorded no archive at all. It cannot have been about anybody else — there was
    nobody else — so it belongs to the oldest archive here and to no other. Without this rule an
    unowned chat answers for every owner, which is the leak this file exists to prevent.
    """
    from epicrisis.sources import SourceRegistry

    sources = SourceRegistry(Path(data_dir)).list()
    return sources[0] if sources else None


def _belongs(chat: dict, owner, first) -> bool:
    """Whether this conversation is about that archive.

    The archive is recorded by its id, which is random and never changes. Chats written before
    that recorded the owner's name instead, and a name is neither unique nor fixed: renaming an
    owner orphaned their conversations, and two people with one name shared theirs. Those chats
    are still read by name, because that is all they say about themselves.
    """
    if owner is None:
        return True
    wanted_id = getattr(owner, "id", None)
    wanted_name = getattr(owner, "whose", owner)
    if chat.get("archive_id"):
        return chat["archive_id"] == wanted_id
    if chat.get("archive"):
        return chat["archive"] == wanted_name
    return bool(first) and getattr(first, "id", None) == wanted_id


def list_chats(data_dir: Path, owner: str | None = None) -> list[dict]:
    """Conversations about one archive. Chats about another person's records are another list."""
    first = _the_first_archive(data_dir) if owner is not None else None
    chats = []
    for path in chats_dir(data_dir).glob("*.json"):
        try:
            chat = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        # A chat written before archives had owners belongs to the archive that was there then.
        if not _belongs(chat, owner, first):
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
    try:
        chat = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    # A chat written before archives had owners belongs to the archive that was there then.
    if not _belongs(chat, owner, _the_first_archive(data_dir) if owner is not None else None):
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
    started = datetime.now(UTC)
    try:
        for event in _stream(data_dir, _prompt(chat), chat["messages"][-1].get("mode", "as_printed")):
            chat = load_chat(data_dir, chat_id) or chat
            message = chat["messages"][-1]
            if event["kind"] == "tool":
                message["steps"].append(event["step"])
            elif event["kind"] == "answer":
                message["text"] = event["text"]
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
    message["seconds"] = round((datetime.now(UTC) - started).total_seconds())
    chat["updated_at"] = records.now()
    _save(data_dir, chat)


def _stream(data_dir: Path, prompt: str, mode: str = "as_printed"):
    config = {
        "mcpServers": {
            "epicrisis": {"command": _executable(), "args": ["mcp", "--data-dir", str(Path(data_dir).resolve())]}
        }
    }
    command = [
        "claude", "-p",
        "--model", _answering_model(data_dir),
        "--output-format", "stream-json", "--verbose",
        "--no-session-persistence", "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands",
        "--mcp-config", json.dumps(config),
        "--tools", "", "--allowedTools", "mcp__epicrisis",
        "--system-prompt", system_prompt(mode),
    ]  # fmt: skip
    # This page runs Claude Code, whichever engine the instance is set to, because a question
    # needs a conversation with tools and the API engine has no such loop yet. So a key meant for
    # that other engine is kept out of here too: a question must not quietly bill the key.
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
    if event.get("type") == "assistant":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_use":
                yield {"kind": "tool", "step": {"tool": block["name"].removeprefix("mcp__epicrisis__"), "input": block.get("input", {})}}
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


def _prompt(chat: dict) -> str:
    lines = []
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
    path = chats_dir(data_dir) / f"{_safe(chat['id'])}.json"
    temporary = temporary_name(path)
    temporary.write_text(json.dumps(chat, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    put_in_place(temporary, path)


def _safe(chat_id: str) -> str:
    return re.sub(r"[^a-z0-9]", "", chat_id.lower())[:32] or "chat"

