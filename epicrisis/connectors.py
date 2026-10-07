"""The MCP connectors this instance has issued: one link each, and which archives each may open.

An instance of this program has no login and never will. From the console it is one person at
their own machine — the dashboard listens on this machine alone, refuses a non-local `Host`, and
the tunnel in front of it carries the MCP server and not the dashboard. Over MCP it is the other
way round: several connectors at once, each held by somebody else, each allowed its own archives.
That sentence is the whole of where the wall stands, and `CONSTITUTION.md` carries it.

**Why a registry rather than the one secret there was.** Until now a path secret and a code from
an authenticator opened the whole instance, and that pair cannot be taken back from one person:
revoking means writing a new secret and setting up every phone again. One entry per connector
answers that — a line goes, a link stops working, and nobody else notices. Everything else the
registry gives (which archives, whose credential, when it was issued) follows from having a line
to write it on.

**What is on a line, and what each field is not.**

  * `id` — four random bytes, the shape an archive's id and a keeper's signature already have,
    for the reason `keepers.py` states at length: it is a name for something that carries no part
    of anybody's name. It is written in the journal and in the access log, so it must be safe to
    write down.
  * `path` — the secret that stands in the served path, its own and never worked out from the id.
    The id is written down in two logs; a path derived from it would be a secret printed in them.
  * `name` — what the owner typed, for the page to show. **It may well be a person's name**, which
    is why `tools/nothing-of-yours.py` looks for it in this repository the way it looks for the
    name on an archive.
  * `archives` — the ids this link may open, and **the whole of the permission**. Nothing else
    grants anything: not the keeper, not the archive, not the open archive on the dashboard.
  * `keeper` — whose credential this is, which is a different question and is why it is a separate
    field. It answers "revoke everything issued to that person" and names the journal's line; it
    does not decide what may be opened. `ARCHITECTURE.md` forbids two fields answering one
    question, so this one is written down as answering the other.
  * `until` — the last day this link answers, or empty for a link with no end. A day and not a
    moment, because a day is what a person types and what the page can say back to them; and
    inclusive, because "until the 31st" means the 31st works. Empty is the default everywhere a
    link is made, including the pair carried in from before this registry: an end nobody asked
    for is a link that stops working in the middle of somebody's illness.

**One place says whether a link answers, and it is `Connector.live`.** Revoked and past its day
are two different facts about a line — one is a press, the other is a date going by with nobody
pressing anything — and every caller wants the one answer they make from both. So `live` is that
answer, `revoked` and `expired()` are the facts behind it, and nothing outside this file reads
`revoked_at` to decide whether to serve. A path lookup that asked only about `revoked_at` would
have gone on serving every link whose day had passed.

**A link past its day answers exactly what an invented path answers: nothing, with no reason
given.** That is the same rule a revoked link is held to, and for the same reason — somebody who
can tell "this address has expired" from "there is no such address" has learnt that the address
was real. So the end of a link's life is said on the owner's own page, in words, and never to
whoever knocks. What it does **not** do is take the code secret off the machine: an expired link
is one its owner may extend, and the phone it was set up on goes on being the right phone.

**The code from the authenticator is not in here.** One secret per connector, under
`/etc/epicrisis/connectors/<id>`, where only root and the group the server runs as can read it.
Not for tidiness: `layout.THEIR_OWN_WORK` is the list `epicrisis backup` carries off the machine,
and a file of credentials must not ride along in a copy its owner hands to somebody. This file
holds ids, archive ids, dates and one typed name, and all four of those are things a backup may
carry.

**A revoked line stays on the list.** Deleting it would leave the journal and the access log
naming an id that names nothing, and those two are the only record of what a link was used for.
It also lets the page say *when* a link stopped working, which is the question somebody asks when
a connector goes quiet. What a revoked line must never do is answer differently from a path that
was never issued — see `16А-9`: an attacker who can tell "revoked" from "wrong" has learnt that
the address was once real.
"""

import functools
import json
import secrets
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path

from epicrisis import layout, records
from epicrisis.runs import copy_whole, one_at_a_time, write_whole
from epicrisis.state import Unreadable

FILE_NAME = layout.CONNECTORS
LOCK_NAME = "connectors.lock"
#: Four random bytes, as an archive's id and a keeper's signature are. One shape for the three
#: because they are the same kind of thing, and because all three end up where only Latin letters
#: can be carried: a path, a URL, a line of a log.
ID_BYTES = 4
#: Where each connector's own code secret lives. One file per connector, named by its id, outside
#: the data directory for the reason the module says: a backup carries the data directory.
SECRETS_FOLDER = Path("/etc/epicrisis/connectors")
#: The one field that a person types, and so the one field that may hold a name. Named here
#: because the guard reads this list rather than being told the same thing a second time.
TYPED_BY_A_PERSON = ("name",)


@dataclass(frozen=True)
class Connector:
    """One link this instance has issued, and the archives it may open.

    `archives` is the permission and the whole of it. It is never trusted on its own: like a
    keeper's list it is read against the archives that exist, because which archives exist is
    `sources.json`'s answer and a second answerer is the defect this project spends its weeks
    removing. An id here that is on no archive opens nothing and is shown nowhere.
    """

    id: str
    path: str
    name: str = ""
    archives: tuple[str, ...] = ()
    keeper: str = ""
    issued_at: str = ""
    revoked_at: str = ""
    until: str = ""

    @property
    def revoked(self) -> bool:
        """Whether somebody pressed the button. A fact, not the question callers ask."""
        return bool(self.revoked_at)

    def expired(self, today: str = "") -> bool:
        """Whether its last day has gone by. A link with no last day never has one.

        The day is passed in by anything that has one in its hand — a test, a page drawing a date
        a person just typed — and read from `records.today()` otherwise, so there is one clock
        here as everywhere else in this program. Compared as text, which is what an ISO day is
        for: no parsing, no timezone of a reader's, and `load()` has already refused anything that
        is not a day.
        """
        if not self.until:
            return False
        return (today or records.today()) > self.until

    @property
    def live(self) -> bool:
        """Whether this link answers now: not taken back, and not past its last day."""
        return not self.revoked and not self.expired()


def path(data_dir: Path) -> Path:
    return Path(data_dir) / FILE_NAME


def secret_file(connector_id: str, folder: Path | None = None) -> Path:
    """Where this connector's code secret is kept. Resolved on the call, never bound as a default.

    `mcp_lock.read_secret` says why: a default argument binds once, and a server or a test that
    puts the file elsewhere would be ignored.
    """
    return Path(folder or SECRETS_FOLDER) / connector_id


def _keep_a_secret(code_secret: str, connector_id: str, folder: Path | None = None) -> None:
    """Write one connector's code secret where the server, and nobody else, can read it.

    The folder is made shut and then widened to the group the server runs as — 0750 and not 0755,
    because a folder anybody may enter is a folder anybody may list, and the names in it are the
    ids of every link this instance has issued. `mcp_lock.write_secret` sets the mode on the file
    itself, and the chown beside it is that module's too: one answer to who may read a secret.
    """
    from epicrisis import mcp_lock

    where = secret_file(connector_id, folder)
    where.parent.mkdir(parents=True, exist_ok=True)
    try:
        where.parent.chmod(0o750)
    except OSError:
        pass
    mcp_lock.let_the_server_read(where.parent)
    mcp_lock.write_secret(code_secret, where)
    mcp_lock.let_the_server_read(where)


def the_link_to(connector: Connector, host: str) -> str:
    """The address to hand somebody, or an empty string where this instance has no public name.

    The host is passed in and never read here, for the reason every door in this program is
    written that way: a function that fetched it would be a second answer to "what is this
    instance called", and `settings.the_name_the_tunnel_answers_on` is the first.

    Empty rather than a guess. A link with no host in it — `/mcp/<secret>` — looks like an
    address and is not one, and the one place it would be read is the page where somebody copies
    it to send to another person. So the page asks for the name first and says why; §7.

    A revoked link has no address either, said here rather than at each call site: a page that
    went on printing one would be offering somebody a link that answers nothing, and that one is
    gone for good — its code secret is off the machine.

    **A link past its last day does keep its address**, and that is not an oversight. It answers
    nothing today and it answers again the moment somebody extends it, with the same address and
    the same phone; the page that draws it says which of the two it is, in words, next to the
    field that moves the day. Printing nothing there would have the page say "this instance has no
    public name yet", which is the sentence it has for an address it cannot build at all.
    """
    if not host or connector.revoked:
        return ""
    return f"https://{host}/mcp/{connector.path}"


def load(data_dir: Path) -> list[Connector]:
    """Every connector ever issued, revoked ones included. Raises where the file will not read.

    Not an empty list, for the reason `keepers.load` gives and paid for: every writer here is
    load, change, save, so a reader that answers "there are none" over a torn file has the next
    write put that emptiness back. Here that would silently un-revoke every link somebody had
    taken back, which is the one direction this file must never move on its own.
    """
    file = path(data_dir)
    if not file.exists():
        return []
    try:
        stored = json.loads(file.read_text(encoding="utf-8"))
        connectors = [
            Connector(id=str(one["id"]), path=str(one.get("path", "")), name=str(one.get("name", "")),
                      archives=tuple(str(archive) for archive in _the_archives_on_one_line(one)),
                      keeper=str(one.get("keeper", "")), issued_at=str(one.get("issued_at", "")),
                      revoked_at=str(one.get("revoked_at", "")), until=_the_last_day_on_one_line(one))  # fmt: skip
            for one in stored
            if one.get("id")
        ]
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as torn:
        raise Unreadable(
            FILE_NAME,
            # What is safe first, because it is the first thing a person needs to know. No archive
            # is reachable while this will not read: a path that cannot be looked up is a path
            # that refuses, which is the safe direction for this particular file to fail in.
            "No archive has been read and nothing has been opened: a link this file cannot be "
            "read for is a link that refuses, so the archives are shut rather than open. No code "
            "secret is in here either — each one is a file of its own under "
            f"{SECRETS_FOLDER}, and none of them has been touched.",
            f"The copy beside it is the version before the last change. Put it back — "
            f"mv {FILE_NAME}.previous {FILE_NAME} — and every link issued up to that change works "
            f"again. If there is no copy, delete the file and issue the links again: the code "
            f"secrets are still there, so a link reissued with the same id works with the phone "
            f"that is already set up.",
        ) from torn
    return connectors


def _the_archives_on_one_line(one: dict) -> list:
    """The archives one connector may open, refused where the file does not hold a list of them.

    A line edited by hand saying `"archives": "419b84dd"` would otherwise be read as eight
    archives of one letter each — an answer that is wrong rather than refused. Wrong in the
    dangerous direction, too: those eight ids open nothing, so the link would quietly stop
    reaching the archive it was issued for, and the owner would be told nothing.
    """
    archives = one.get("archives", [])
    if not isinstance(archives, list):
        raise TypeError(f"the archives of a connector are {type(archives).__name__} and not a list")
    return archives


def _the_last_day_on_one_line(one: dict) -> str:
    """The last day one connector answers, refused where the file does not hold a day.

    Written the way `_the_archives_on_one_line` is written, and refused in the same direction: a
    line edited by hand saying `"until": "next March"` or `"until": 2027` must stop the file from
    reading rather than be guessed at. Guessed either way it is wrong and silent — read as no end,
    a link somebody meant to expire answers for ever; read as expired, a link somebody is using
    goes quiet with nothing anywhere to say why. Refused, the page says the file will not read and
    names the copy to put back, which is the one outcome a person can act on.

    An end that has a day's shape and is not a real day — the thirty-first of February — is
    refused here too, because `expired()` compares text and would treat it as a day that never
    arrives.
    """
    until = one.get("until", "")
    if until in (None, ""):
        return ""
    if not isinstance(until, str):
        raise TypeError(f"the last day of a connector is {type(until).__name__} and not a day")
    return a_day(until)


def a_day(text: str) -> str:
    """One ISO day, `YYYY-MM-DD`, or ValueError. The one place a typed end is read.

    A page, a command and a stored line all have to agree about what counts as a day, which is
    why they all come here instead of each holding a format of its own.
    """
    said = text.strip()
    try:
        return date.fromisoformat(said).isoformat()
    except (TypeError, ValueError) as not_a_day:
        raise ValueError(f"{said!r} is not a day written as YYYY-MM-DD") from not_a_day


def unreadable(data_dir: Path) -> bool:
    """Whether the file is there and will not read, asked without raising."""
    try:
        load(data_dir)
    except Unreadable:
        return True
    return False


def get(data_dir: Path, connector_id: str) -> Connector | None:
    return next((one for one in load(data_dir) if one.id == connector_id), None)


def the_archives_it_may_open(connector: Connector, archives) -> tuple:
    """Which of these archives this link may open — the permission, read against what exists.

    The list is passed in and never fetched, for the reason `TheArchives` gives: two readings
    inside one answer can be two different lists. A revoked link may open nothing at all, said
    here rather than at each call site, because a caller that forgot would be a caller that
    answered about somebody out of a link its owner had taken back.
    """
    if not connector.live:
        return ()
    allowed = set(connector.archives)
    return tuple(one for one in archives if one.id in allowed)


def save(data_dir: Path, connectors: list[Connector]) -> None:
    """Write the whole list, keeping the version it replaces beside it.

    Asked again here rather than trusted to load(), as `keepers.save` asks: a caller that caught
    Unreadable in the middle of its own work must not reach this write with a list built from
    nothing.
    """
    file = path(data_dir)
    if unreadable(data_dir):
        raise Unreadable(
            FILE_NAME,
            "Nothing was written. Every link issued so far is still in that file, and every code "
            f"secret is still its own file under {SECRETS_FOLDER}.",
            f"The copy beside it is the version before the last change: mv {FILE_NAME}.previous "
            f"{FILE_NAME}.",
        )
    if file.exists():
        copy_whole(file, file.with_name(file.name + ".previous"))
    write_whole(file, json.dumps([asdict(one) for one in connectors], ensure_ascii=False, indent=2) + "\n")


def editing(data_dir: Path):
    """One writer at a time, for the whole of a change and not only for the write at the end.

    The shape `keepers.editing` uses, for the same reason: every writer below reads the whole list
    and writes the whole list back, and that shape lost a group of spellings in `people.py` before
    the lock was held across the read as well.
    """
    return one_at_a_time(path(data_dir).with_name(LOCK_NAME), "Editing the connectors")


def while_editing(change):
    """Hold the lock for the whole of a change."""

    @functools.wraps(change)
    def guarded(data_dir: Path, *args, **kwargs):
        with editing(data_dir):
            return change(data_dir, *args, **kwargs)

    return guarded


def _an_id_nobody_has(taken: set[str], secrets_folder: Path | None = None) -> str:
    """Four random bytes that no connector on the list already carries, and whose secret file does
    not already exist.

    The loop `SourceRegistry.add` and `keepers` both draw with. Four bytes collide about once in
    sixty-five thousand, and two connectors under one id would be two people's permissions read as
    one — the failure this file exists to make impossible.

    **The folder of secrets is asked as well as the list, because the folder is one per machine
    and the list is one per instance.** The README walks a person through the demo first and their
    own archive second, so two instances on one machine is the ordinary path, not an exotic one —
    and they share `/etc/epicrisis/connectors`. Drawing against this instance's own ids alone,
    the second instance would one time in sixty-five thousand write its secret over a live link's
    and leave that link answering no code at all, with nothing anywhere to say why.
    """
    folder = Path(secrets_folder or SECRETS_FOLDER)
    made = secrets.token_hex(ID_BYTES)
    while made in taken or (folder / made).exists():
        made = secrets.token_hex(ID_BYTES)
    return made


@while_editing
def issue(data_dir: Path, name: str = "", archives: tuple[str, ...] = (), keeper: str = "",
          until: str = "", secrets_folder: Path | None = None) -> tuple[Connector, str]:  # fmt: skip
    """A new link, and the code secret to read into an authenticator **once**.

    The secret is returned and not stored anywhere this function can be asked for it again. That
    is the whole of the discipline around it: `run_http` keeps no access log because the path
    carries a secret, and a secret that can be fetched a second time is a secret in whatever
    fetches it. Lost before the phone is set up, the answer is to revoke and issue another — which
    costs nothing, and is why this is affordable.

    The path secret and the code secret are drawn by the two functions that already draw them, so
    there is one place each is made: `mcp_server.new_path_secret` and `mcp_lock.new_secret`.

    `until` is empty by default, and that default is a decision rather than a convenience: a link
    this program ended on its own, on a day nobody chose, would stop answering in the middle of
    the one conversation it was issued for. A link is given a last day when the person issuing it
    says so, and `set_until` moves it afterwards.
    """
    from epicrisis import mcp_lock
    from epicrisis.mcp_server import new_path_secret

    connectors = load(data_dir)
    made = Connector(id=_an_id_nobody_has({one.id for one in connectors}, secrets_folder), path=new_path_secret(),
                     name=name.strip(), archives=tuple(dict.fromkeys(archives)), keeper=keeper,
                     issued_at=records.now(), until=a_day(until) if until.strip() else "")  # fmt: skip
    code_secret = mcp_lock.new_secret()
    # The folder this link's run of wrong codes will live in, made from the side that can: the
    # server reading codes is sandboxed and cannot make it, and without it the growing delay
    # after wrong codes lives in one process's memory and says so nowhere. See
    # `mcp_lock.make_the_place_for_waits`.
    mcp_lock.make_the_place_for_waits(data_dir)
    # The secret is written before the line, so a crash between the two leaves a secret nothing
    # points at rather than a link nothing can answer a code for. The first is litter; the second
    # is a link that looks live and refuses every code, with nothing on the page to say why.
    _keep_a_secret(code_secret, made.id, secrets_folder)
    save(data_dir, [*connectors, made])
    return made, code_secret


def ids_the_log_names_that_are_not_here(data_dir: Path) -> set[str]:
    """Connector ids the record of calls names and this registry does not hold.

    The two files are written for each other: a revoked link keeps its line **so that** the
    journal and the access log go on naming something, and an id naming nothing makes both of them
    unreadable where it appears. Nothing compared them until a registry edited by hand during its
    own building left thirteen calls pointing at five ids that are not here.

    Read and never repaired: what to do about it is a person's business, and the only honest
    repair — a line saying when it was issued and when it stopped — can be taken from the log, not
    from this file.
    """
    from epicrisis import mcp_access

    held = {one.id for one in load(data_dir)}
    named = {entry.get("connector") for entry in mcp_access._entries(data_dir)}
    return {one for one in named if one} - held


@while_editing
def rename(data_dir: Path, connector_id: str, name: str) -> Connector | None:
    """What the page calls this link. The owner's own words, and the only field they type."""
    connectors = load(data_dir)
    renamed = None
    for at, one in enumerate(connectors):
        if one.id == connector_id:
            renamed = connectors[at] = replace(one, name=name.strip())
    if renamed is not None:
        save(data_dir, connectors)
    return renamed


@while_editing
def set_archives(data_dir: Path, connector_id: str, archives: tuple[str, ...]) -> Connector | None:
    """Which archives this link may open, as the ticks on the page stand.

    The whole set and not an add or a remove: the page draws every archive with a tick beside it,
    so what comes back from it is the answer entire. An add would make a tick that failed to
    arrive look like a tick nobody changed.
    """
    connectors = load(data_dir)
    changed = None
    for at, one in enumerate(connectors):
        if one.id == connector_id:
            changed = connectors[at] = replace(one, archives=tuple(dict.fromkeys(archives)))
    if changed is not None:
        save(data_dir, connectors)
    return changed


@while_editing
def set_until(data_dir: Path, connector_id: str, until: str) -> Connector | None:
    """The last day this link answers, or no last day at all where `until` is empty.

    One writer for all three things a person does to a date — give one, move it, take it away —
    because they are one fact being written and a separate `extend` would be a second place
    deciding what a link's end is. Extending is this with a later day; "for ever" is this with
    nothing.

    A day in the past is allowed, and deliberately: it is how somebody stops a link today without
    taking it back, keeping the phone it was set up on for when they want it again. Taking it back
    is `revoke`, and that is the one that cannot be undone.

    Raises ValueError where what arrived is not a day, which the page and the command turn into a
    sentence. Nothing is written in that case — a date nobody could read must not land on a line
    and quietly become the day a link stops.
    """
    wanted = a_day(until) if until.strip() else ""
    connectors = load(data_dir)
    changed = None
    for at, one in enumerate(connectors):
        if one.id == connector_id:
            changed = connectors[at] = replace(one, until=wanted)
    if changed is not None:
        save(data_dir, connectors)
    return changed


@while_editing
def revoke(data_dir: Path, connector_id: str, secrets_folder: Path | None = None) -> Connector | None:
    """Stop this link working, and take its code secret off the machine.

    The line stays, carrying the moment it was revoked: the journal and the access log name ids,
    and an id that names nothing makes both unreadable. The secret goes, because it is the one
    part of this that is dangerous to keep — and a link reissued later gets an id of its own, so
    nothing comes back by reusing a number.

    **A link whose last day has gone by can still be revoked, and until it is, its code secret is
    still on this machine.** Asking `live` here instead of `revoked` would have refused to take
    back exactly the links somebody has stopped thinking about — the ones that expired months ago
    — and left every one of their secrets in `/etc`.
    """
    connectors = load(data_dir)
    gone = None
    for at, one in enumerate(connectors):
        if one.id == connector_id and not one.revoked:
            gone = connectors[at] = replace(one, revoked_at=records.now())
    if gone is None:
        return None
    save(data_dir, connectors)
    secret_file(connector_id, secrets_folder).unlink(missing_ok=True)
    return gone


@while_editing
def carry_the_one_secret_in(data_dir: Path, archives: tuple[str, ...], token_file: Path | None = None,
                            totp_file: Path | None = None, secrets_folder: Path | None = None) -> Connector | None:  # fmt: skip
    """The pair of secrets this machine already has, written down as the first connector.

    Before this file existed, one path secret and one code secret opened the whole instance. That
    pair is still on the machine and still in somebody's phone, so it is carried in rather than
    replaced: the link this person is using goes on working, and their authenticator goes on
    showing codes that this server accepts, until they revoke it themselves.

    It is given **every archive**, which is what it can open today. Narrowing it here would be
    this code deciding what somebody may see, and the first entry says who decides that.

    Nothing is invented: where either file is missing there is nothing to carry, and this returns
    nothing rather than issuing a link with half a credential. Run twice it does nothing the
    second time — the test is whether a connector already carries that path, which is the fact
    itself rather than a flag written beside it.
    """
    from epicrisis import mcp_lock
    from epicrisis.mcp_server import read_path_secret

    token = Path(token_file) if token_file else Path("/etc/epicrisis/mcp-token")
    code = Path(totp_file) if totp_file else mcp_lock.SECRET_FILE
    try:
        path_secret = read_path_secret(token)
    except (OSError, ValueError):
        return None
    code_secret = mcp_lock.read_secret(code)
    if not path_secret or not code_secret:
        return None
    connectors = load(data_dir)
    if any(one.path == path_secret for one in connectors):
        return None
    made = Connector(id=_an_id_nobody_has({one.id for one in connectors}), path=path_secret,
                     name="", archives=tuple(dict.fromkeys(archives)), keeper="",
                     issued_at=records.now())  # fmt: skip
    _keep_a_secret(code_secret, made.id, secrets_folder)
    save(data_dir, [*connectors, made])
    return made
