"""A record of who reached the MCP server over HTTP, and what they asked for.

The endpoint is published to the internet behind a secret, and until now nothing said whether it
had ever been used. This does not stop anyone; it turns "I would never know" into "I know".

What is kept: the time, the address the request came from, the user agent, the name of the tool
called, whether the request was let through, and whether a session identifier was present. What
is never kept: the secret, the arguments of a call, and anything the archive answered. A log of
a medical archive that holds the questions is a second copy of the archive.
"""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from epicrisis import records
from epicrisis.runs import belongs_to_the_folder, put_in_place, temporary_name

FILE_NAME = "mcp-access.jsonl"
KEEP_LINES = 5000  # a few months of ordinary use; the file is trimmed when it grows past it
FORWARDED = ("x-forwarded-for", "x-real-ip", "tailscale-user-login", "tailscale-funnel-request")
# Values worth keeping: they say which kind of client called and by which protocol, and none of
# them can carry a question or an answer. Everything else is kept by name only.
SAFE_VALUES = ("x-anthropic-client", "mcp-protocol-version", "x-forwarded-host", "mcp-method")


def path(data_dir: Path) -> Path:
    return Path(data_dir) / FILE_NAME


def record(data_dir: Path, entry: dict) -> None:
    """Append one line. A log that cannot be written must never stop the server."""
    try:
        file = path(data_dir)
        existed = file.exists()
        with file.open("a", encoding="utf-8") as lines:
            lines.write(json.dumps({"at": records.now(), **entry}, ensure_ascii=False) + "\n")
        if not existed:
            # Who reached this archive and when is nobody else's business on a shared machine.
            os.chmod(file, 0o640)
            belongs_to_the_folder(file)
        _trim(file)
    except OSError:
        pass


def request_facts(scope: dict, allowed: bool, door: str | None = None) -> dict:
    """What a request says about itself, minus the secret in its path.

    door says which one it was turned away at, and the two are not the same thing. "address"
    is a stranger sweeping the internet, stopped before the path is even looked at; it learns
    nothing and means nothing. "path" is a caller whose address is one this server answers, that
    asked for a path that is not the secret — rarer, and worth a person's eye.
    """
    headers = {name.decode().lower(): value.decode() for name, value in scope.get("headers", [])}
    client = scope.get("client") or ("", 0)
    facts = {
        "from": client[0],
        "allowed": allowed,
        **({"door": door} if door else {}),
        "method": scope.get("method"),
        "agent": headers.get("user-agent", "")[:200],
        "session": bool(headers.get("mcp-session-id")),
        "has_authorization": bool(headers.get("authorization")),
    }
    for name in FORWARDED:
        if headers.get(name):
            facts[name] = headers[name][:200]
    # The names of every header, without their values. One connector looks like another in the
    # fields above, so the only hope of telling them apart is a header that names the account.
    facts["headers"] = sorted(headers)
    for name in SAFE_VALUES:
        if headers.get(name):
            facts[name] = headers[name][:120]
    # The trace identifier ties the calls of one exchange together; it says nothing about who made it.
    trace = (headers.get("traceparent") or "").split("-")
    if len(trace) >= 3:
        facts["trace"] = trace[1][:32]
    return facts


def last(data_dir: Path) -> dict | None:
    """The most recent line, for the dashboard. None when nothing has ever called."""
    file = path(data_dir)
    try:
        lines = file.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return None
    for line in reversed(lines):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def _door(entry: dict) -> str:
    """Which door a refused call was turned away at. Lines written before this was recorded say so."""
    return {"path": "wrong_path", "address": "wrong_address"}.get(entry.get("door"), "door_unrecorded")


def counts(data_dir: Path) -> dict:
    """How many calls the log holds, and how many were refused, and at which door.

    A stranger stopped by its address is noise. A caller whose address this server answers,
    asking for a path that is not the secret, is not noise, so the two are counted apart.
    """
    found = {"calls": 0, "refused": 0, "wrong_address": 0, "wrong_path": 0, "door_unrecorded": 0, "tools": {}}
    try:
        lines = path(data_dir).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return found
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        found["calls"] += 1
        if not entry.get("allowed", True):
            repeats = 1 + entry.get("repeats", 0)
            found["refused"] += repeats
            found[_door(entry)] += repeats
        if entry.get("tool"):
            found["tools"][entry["tool"]] = found["tools"].get(entry["tool"], 0) + 1
    return found


QUIET_SECONDS = 60  # one line a minute per address is enough to know a sweep is happening
BURST_MINUTES = 10
BURST_CALLS = 60  # a person asking questions does not make sixty calls in ten minutes; a copy does


def activity(data_dir: Path, hours: int = 24) -> dict:
    """What the last day looked like, and the busiest ten minutes in it.

    One connector cannot be told from another by its address: they share a network and an agent.
    What differs is shape. A person asks a question and the model makes a handful of calls; a
    copy of the archive is hundreds in a row. This does not prove anything — it gives a person
    something to notice.
    """
    since = datetime.now(UTC) - timedelta(hours=hours)
    times: list[datetime] = []
    tools: dict[str, int] = {}
    refused = 0
    at_the_door = {"wrong_address": 0, "wrong_path": 0, "door_unrecorded": 0}
    for entry in _entries(data_dir):
        try:
            when = datetime.fromisoformat(entry["at"])
        except (KeyError, ValueError):
            continue
        if when < since:
            continue
        if not entry.get("allowed", True):
            # A sweep from outside is refused at the door and says nothing about the archive.
            # Counting it here would keep the burst alarm ringing at strangers for ever.
            repeats = 1 + entry.get("repeats", 0)
            refused += repeats
            at_the_door[_door(entry)] += repeats
            continue
        times.append(when)
        if entry.get("tool"):
            tools[entry["tool"]] = tools.get(entry["tool"], 0) + 1
    times.sort()
    busiest, start = 0, 0
    for index, when in enumerate(times):
        while when - times[start] > timedelta(minutes=BURST_MINUTES):
            start += 1
        busiest = max(busiest, index - start + 1)
    return {
        "hours": hours, "calls": len(times), "refused": refused, **at_the_door, "tools": tools,
        "busiest": busiest, "busy_minutes": BURST_MINUTES, "unusual": busiest >= BURST_CALLS,
    }  # fmt: skip


def _entries(data_dir: Path):
    try:
        lines = path(data_dir).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return
    for line in lines:
        try:
            yield json.loads(line)
        except ValueError:
            continue


def _trim(file: Path) -> None:
    lines = file.read_text(encoding="utf-8").splitlines()
    if len(lines) <= KEEP_LINES:
        return
    temporary = temporary_name(file)
    temporary.write_text("\n".join(lines[-KEEP_LINES:]) + "\n", encoding="utf-8")
    put_in_place(temporary, file)

