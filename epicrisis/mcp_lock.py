"""A lock on the archive over the network: a code from the owner's authenticator.

The path holds a secret and the tunnel only lets the connector's own network through, but neither
says who is calling. Two people with the same address and the same secret look the same. This
asks for something only the owner has: a six-digit code from their phone, by the ordinary rule
of RFC 6238, the one every authenticator implements.

How it works here. `unlock` takes a code and gives back a pass, good for as long as the instance
says (four hours to begin with). Every other
tool wants that pass and refuses without it. The pass is a random string that lives in the
conversation; a stranger who knows the path and sits inside the right network still does not have
it. `lock_archive` throws a pass away early — worth doing when a conversation ends, because the pass
stays written in it.

Why a pass and not "the server is open": requests here carry no session, so an open server would
be open to everyone who reaches it, including whoever was waiting for exactly that. The pass
keeps the opening with the one who opened it. An instance may choose the other way — one code
opening everything for the window — and then it gives that up knowingly.

The code itself is checked against a shared secret, because that is what a six-digit code is: the
same secret sits in the phone and on the server. It is generated on the server by its owner, read
once into the authenticator, and never passed through a conversation.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

from epicrisis.runs import belongs_to_the_folder

SECRET_FILE = Path("/etc/epicrisis/mcp-totp")
STEP_SECONDS = 30
DIGITS = 6
DRIFT_STEPS = 1  # one step either way: a phone's clock is never exactly a server's
# How far out a refused code is looked for, to tell a person their clock has drifted rather than
# that their code is wrong. Nothing within this window is accepted — only recognised, and named.
#
# Two hours and not twelve. Recognising a code is answering a question nobody asked — "are these
# six digits a real code of this secret?" — and a blind guess gets a yes once in every 10^6 divided
# by the number of moments looked at. Twelve hours is 2881 moments and a yes about three times in a
# thousand; two hours is 481 and once in two thousand. Nothing is opened either way, and the
# guesser learns only that this server's clock is not theirs. What is bought by the smaller window
# is that they learn it less often; what is given up is naming the drift of a machine that has
# stood switched off for half a day — and for that, `epicrisis mcp-lock status` prints this
# server's own time, which is the honest way to find out.
HOURS_OF_DRIFT_LOOKED_FOR = 2
PASS_MINUTES = 240  # four hours: enough for an evening, gone by morning
SCOPES = ("conversation", "server")
WRONG_CODES = 5  # attempts before the lock starts making whoever is guessing wait
# Each further run of wrong codes waits longer, and knocking during a wait counts as another
# wrong code, so hammering only lengthens it. The wait stops growing at a quarter of an hour:
# beyond that a stranger could keep the owner out for a day by guessing badly on purpose, and the
# guessing is already slow enough. A correct code ends the run; the owner can also end it from the
# server with `epicrisis mcp-lock clear`.
WAITS_MINUTES = (1, 5, 15)
SECRET_BYTES = 20  # the size RFC 4226 recommends for the shared secret
# The run of wrong codes, kept across a restart — one file per lock, in a folder of their own.
#
# They used to sit loose in the data directory as `mcp-lock-wrong-codes.json.<link>`, and the
# server that writes them runs under a unit that may write the access log and nothing else beside
# it. So every one of these writes failed, `_keep_wrong` set `writes = False`, and the growing
# delay for wrong codes lived in one process's memory: it survived nothing, and a restart was a
# fresh start for whoever was guessing. A folder can be named in the unit; a file per link, whose
# name nobody knows in advance, cannot.
WRONG_CODES_FOLDER = "mcp-locks"
WRONG_CODES_FILE = "mcp-lock-wrong-codes.json"  # the instance's own, inside that folder


class Locked(Exception):
    """Raised instead of an answer while the archive is locked."""


def new_secret() -> str:
    """A fresh shared secret, in the base32 every authenticator reads."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def uri(secret: str, account: str = "archive", issuer: str = "Epicrisis") -> str:
    """The line an authenticator turns into codes. It holds the secret, so it is never printed twice."""
    return (
        f"otpauth://totp/{issuer}:{account}?secret={secret}&issuer={issuer}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


def code_at(secret: str, when: float, digits: int = DIGITS, step: int = STEP_SECONDS) -> str:
    """The code an authenticator holding this secret shows at that moment (RFC 6238)."""
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    counter = struct.pack(">Q", int(when // step))
    digest = hmac.new(key, counter, hashlib.sha1).digest()
    start = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[start : start + 4])[0] & 0x7FFFFFFF
    return str(number % (10**digits)).zfill(digits)


# The path is resolved when the secret is read, not when this module is imported: a default
# argument binds once, and a server or a test that puts the file elsewhere would be ignored.
def read_secret(path: Path | None = None) -> str | None:
    try:
        secret = Path(path or SECRET_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return secret or None


def where_the_wait_is_kept(data_dir: Path, link: str | None = None) -> Path:
    """The file holding one lock's run of wrong codes: the instance's, or one link's.

    One place answers this for the server that writes them and for the command that clears them.
    They were built in two: the server named `<file>.<link>` and the command knew only the file
    without a link, so `mcp-lock clear` cleared the wait of an instance nobody was knocking on and
    left every link's wait standing. A person locked out of their own archive ran the documented
    way out and it did nothing — which is the shape of the finding that gave this program its
    recovery role.
    """
    folder = Path(data_dir) / WRONG_CODES_FOLDER
    return folder / (f"{link}.json" if link else WRONG_CODES_FILE)


def make_the_place_for_waits(data_dir: Path) -> Path | None:
    """Make the folder the runs of wrong codes live in, or give back nothing where that failed.

    **Nothing in this program made it, and the one place that needed it could not.** The MCP unit
    is sandboxed — `ProtectSystem=strict`, with the data directory not writable and this one
    folder named in `ReadWritePaths` — and that line carries a dash, so that a folder which does
    not exist yet cannot take the whole server down (it did once, 226/NAMESPACE, for the two
    minutes it took to find out why). The dash also makes the folder's absence silent: with no
    mount, `_keep_wrong` gets EROFS, sets `writes = False`, and the growing delay after wrong
    codes lives in one process's memory — surviving nothing, and saying nothing anywhere.

    So it is made from the side that can: the dashboard and the commands run with the data
    directory writable. Called where a link is issued, because a link is what will need one, and
    where the dashboard starts, so an instance that has not issued one yet is still ready.

    Nothing is raised. A folder that cannot be made is a server that still answers codes and still
    makes people wait, within one process — and the place that cares says so out loud instead.
    """
    folder = Path(data_dir) / WRONG_CODES_FOLDER
    try:
        folder.mkdir(parents=True, exist_ok=True)
        folder.chmod(0o700)
        belongs_to_the_folder(folder / WRONG_CODES_FILE)
    except OSError:
        return None
    return folder


def the_waits_can_be_kept(data_dir: Path) -> bool:
    """Whether a run of wrong codes written now would still be there after a restart.

    Asked by the server as it starts, so that the one thing standing between somebody's archive
    and a patient guesser is not quietly a thing that lives until the next restart. §7.
    """
    folder = Path(data_dir) / WRONG_CODES_FOLDER
    return folder.is_dir() and os.access(folder, os.W_OK)


def every_wait_kept(data_dir: Path) -> list[Path]:
    """Every such file there is, the instance's and every link's. A file is not a wait."""
    folder = Path(data_dir) / WRONG_CODES_FOLDER
    return sorted(file for file in folder.glob("*.json")) if folder.is_dir() else []


def whoever_is_waiting(data_dir: Path, now: float | None = None) -> list[Path]:
    """The files of the locks that are keeping somebody waiting **now**, which is a question about
    what is in them.

    A file is not a wait, and counting files answered a different question from the one the page
    asked: a run of wrong codes that was answered correctly leaves `[]` behind, and a run from last
    week has aged out of the window entirely. Measured on the owner's own machine — one file,
    two bytes, holding `[]` — while the settings page said "1 link is in a wait after wrong codes"
    and offered him the command to clear it.

    Asked of the same two things the lock itself asks, and nothing else: how many wrong codes are
    still inside the window, and how long the step for that many says to wait. §7 — a count that
    disagrees with the thing it counts is a defect.
    """
    at = time.time() if now is None else now
    waiting = []
    for file in every_wait_kept(data_dir):
        lock = Lock(secret=None, remembers=file)
        lock._recall_wrong(at)
        if lock._wait_over(at) > 0:
            waiting.append(file)
    return waiting


def let_the_server_read(file: Path) -> None:
    """Hand a secret to the group the server runs as, so the service can check codes against it.

    Here rather than in `cli.py`, where it was, because this module is the one place a secret file
    is created and the registry of connectors creates one per link. Two copies of this would be
    two answers to "who may read a secret of this program", and the second one written would be
    the one that forgot the group.

    Quiet where it cannot: a test writes these under a temporary folder as whoever runs pytest,
    and there is no root and no such group there. The mode from `write_secret` already keeps the
    file shut to everybody else, so failing to widen it errs towards closed.
    """
    import grp
    import pwd

    try:
        os.chown(file, pwd.getpwnam("root").pw_uid, grp.getgrnam("ubuntu").gr_gid)
    except (KeyError, PermissionError, OSError):
        pass


def write_secret(secret: str, path: Path | None = None) -> Path:
    """Write the secret where only root and the group running the server can read it.

    Created with that mode rather than corrected to it afterwards. Written and then chmod-ed, the
    file stands at 0644 for an instant in a directory anyone may enter, and this is the one secret
    where a single silent read is permanent: codes made from it look exactly like the owner's, for
    ever, and nothing would ever show that somebody else has them.
    """
    file = Path(path or SECRET_FILE)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.unlink(missing_ok=True)  # O_EXCL below: a new secret replaces the old one deliberately
    # Created shut, widened to the group while it is still empty, and only then written. The mode
    # given to os.open is cut down by the umask — and the command that writes this sets the umask
    # to 0o077 on purpose — so the group the server runs as would lose the file it has to read.
    # fchmod is not cut down by anything, and at the moment it runs there is no secret in the file.
    opened = os.open(file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.fchmod(opened, 0o640)
    except BaseException:
        os.close(opened)
        raise
    with os.fdopen(opened, "w", encoding="utf-8") as writing:
        writing.write(secret + "\n")
    return file


@dataclass
class Lock:
    """The state of the lock in one running server: who is open, and who has been guessing."""

    secret: str | None = None
    # Where this lock's own secret is kept, for the one case below where it has to be read again.
    # **A lock reads its own file and never the instance's.** It used to fall back to the
    # instance-wide secret whenever its own was missing, which was written for the lock of the
    # whole server — where that file *is* the instance's — and inherited by the lock of a link,
    # where it meant something else entirely: a link whose code secret could not be read accepted
    # the code that once opened the whole instance, and refused the code it had itself printed for
    # whoever holds it. Everything else in this program fails closed; that one failed open.
    secret_file: Path | None = None
    minutes: int = PASS_MINUTES
    open_until: float = 0.0  # while the whole server is open, for instances that ask for that
    # pass -> (when it stops working, the archive it has been used for or "")
    #
    # **One patient to a session, which is what a pass is.** The archive is not written when the
    # pass is given out — a code opens the lock and picks nobody — but on the first call that
    # names one, and after that this pass answers about that archive and no other. Another means
    # closing this one and taking a new code, which is the whole of the rule: the records of two
    # people never meet, and a model's context is somewhere they could.
    #
    # Not the same thing as what used to be here. That wrote the archive at unlock time, from
    # whatever the dashboard had open, and tore the pass up when somebody pressed Show — a rule
    # about the dashboard, which no longer reaches a connector at all. This is a rule about the
    # conversation: it binds to what was *asked for*, once, by whoever is holding the pass.
    passes: dict[str, tuple[float, str]] = field(default_factory=dict)
    used: set[tuple[str, int]] = field(default_factory=set)  # a code counts once
    wrong: list[float] = field(default_factory=list)
    # Where the run of wrong codes is kept, so that it survives the server being restarted. Held
    # only in memory, the wait was undone by a restart — and the way the owner was told to end a
    # wait that somebody else had put them into was to restart the server, which is to say: the
    # documented way out for the owner was also the way out for whoever was guessing.
    remembers: Path | None = None
    # Whether that file is still being kept up to date. A file that can be read and not written
    # empties the wait altogether, because every attempt is read back from a file that never grew.
    writes: bool = True

    def _recall_wrong(self, now: float) -> None:
        """The run of wrong codes as the file has it. The file is the truth, not this process.

        It used to be the union of the file and what this process remembered, which made the
        owner's way out impossible: `mcp-lock clear` takes the file away, and the union put the
        wait straight back from memory. A running server has to be able to forget.

        And only times that could be a wrong code are read. Anything outside the window the wait
        can last is a broken file or a clock that moved — a timestamp in the future made the wait
        last as long as the jump, and the message politely offered to try again in ten years. A
        server whose clock is corrected, a snapshot restored, a machine migrated: all ordinary.
        """
        if self.remembers is None or not self.writes:
            return  # the file is not being kept up to date, so this process's own count is the truth
        try:
            kept = json.loads(self.remembers.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.wrong = []
            return
        except (OSError, ValueError, TypeError):
            return
        earliest = now - WAITS_MINUTES[-1] * 60
        try:
            self.wrong = sorted(when for when in map(float, kept) if earliest <= when <= now)[-len(WAITS_MINUTES) * WRONG_CODES:]
        except (TypeError, ValueError):
            self.wrong = []

    def _keep_wrong(self) -> None:
        """Write down the run of wrong codes, and stop trusting the file if it cannot be written.

        The file is the truth and this process reads it back on every attempt — which is right,
        and which means that a file that can be read and not written empties the wait entirely:
        each wrong code is written nowhere and then read back as nothing, so the count never
        reaches five and the delay never comes. A disk with no room left, a data directory mounted
        read-only, a copy restored with somebody else's ownership — and the lock quietly stops
        slowing anybody down, while every page goes on saying it does.

        So a write that fails is remembered. From then on this process keeps its own count, which
        is weaker than a file across restarts and far better than nothing at all.
        """
        if self.remembers is None or not self.writes:
            return
        try:
            self.remembers.parent.mkdir(parents=True, exist_ok=True)
            self.remembers.write_text(json.dumps(self.wrong), encoding="utf-8")
            belongs_to_the_folder(self.remembers)
        except OSError:
            self.writes = False

    def unlock(self, code: str, now: float | None = None, minutes: int | None = None,
               scope: str = "conversation") -> dict:  # fmt: skip
        """Take a code, give back a pass. Raises Locked on a wrong code or too many tries.

        The scope is the instance's own setting, and it is read here rather than only where a
        call is let through: an opening made for one conversation must not become an opening of
        the whole server if the setting changes while the pass is still good.
        """
        now = time.time() if now is None else now
        minutes = self.minutes if minutes is None else minutes
        if not self.secret:
            # A secret made after the server started is picked up here, without a restart — its
            # own, named when this lock was built. Where nothing named one, this is the lock of
            # the instance and the default file is the instance's, which is what it was always
            # reading; where a link named one, a missing file now means no lock rather than the
            # instance's lock.
            self.secret = read_secret(self.secret_file)
        if not self.secret:
            raise Locked("This archive has no lock set up; a code cannot be checked.")
        self._recall_wrong(now)
        self._forget_old(now)
        waiting = self._wait_over(now)
        if waiting > 0:
            # The wait is not made longer by knocking on the door. Counting a knock restarted the
            # clock from it, so anyone who could reach the server could keep the owner out for as
            # long as they cared to knock — with the owner's own code refused meanwhile.
            raise Locked(f"Too many wrong codes. Try again in {int(waiting / 60) + 1} minutes.")
        step = int(now // STEP_SECONDS)
        # Digits of another script are not a code: hmac.compare_digest refuses anything but ASCII.
        digits = "".join(character for character in str(code) if character.isascii() and character.isdigit())
        for drift in range(-DRIFT_STEPS, DRIFT_STEPS + 1):
            at = (step + drift) * STEP_SECONDS
            if hmac.compare_digest(code_at(self.secret, at), digits) and (digits, step + drift) not in self.used:
                self.used.add((digits, step + drift))
                self.wrong = []  # a code that fits ends the run of wrong ones
                self._keep_wrong()
                ticket = secrets.token_urlsafe(18)
                until = now + minutes * 60
                self.passes[ticket] = (until, "")  # nobody yet: the first call names them
                # An instance set to open as a whole opens here too; one set to open a conversation
                # at a time leaves this at nothing, and the pass is the only way in.
                if scope == "server":
                    self.open_until = max(self.open_until, until)
                return {"pass": ticket, "open_for_minutes": minutes, "until": _clock(until)}
        # A code that is right for this secret and wrong only for this clock is not a guess, so it
        # does not spend one of the owner's five tries. Counted, the five honest attempts of
        # somebody whose server has drifted ran out, and the sixth answered "Too many wrong codes"
        # with no word about the clock — which is precisely the state the message was written to
        # get them out of. Nothing is opened by this: the code is refused either way, and a code
        # that fits no moment in the window counts as before.
        drifted = self._drift_of_the_clock(digits, step)
        if drifted:
            raise Locked(
                f"That code is a right code, but about {drifted} out of step with this server's "
                "clock, so it cannot be accepted. The clock of this machine is what needs putting "
                "right — check its time, and its time service."
            )
        # A wrong code, and only now is it counted as one: the message about the clock above is
        # written for somebody whose code is real, and a real code refused by this server is the
        # server's fault, not a guess at the door.
        self.wrong.append(now)
        self._keep_wrong()
        raise Locked("That code does not fit, or it has already been used once.")

    def _drift_of_the_clock(self, digits: str, step: int) -> str:
        """How far off this server's clock is, where a refused code says it is off rather than wrong.

        Looked for well beyond the step either way, because the point is to recognise a real code
        from a real authenticator rather than to accept it. Nothing is opened by this, no attempt is
        spent differently, and a guessed code matches nothing here any more than it did before.
        """
        for drift in range(-HOURS_OF_DRIFT_LOOKED_FOR * 120, HOURS_OF_DRIFT_LOOKED_FOR * 120 + 1):
            if abs(drift) <= DRIFT_STEPS:
                continue  # already tried, and accepted if it fitted
            if hmac.compare_digest(code_at(self.secret, (step + drift) * STEP_SECONDS), digits):
                seconds = abs(drift) * STEP_SECONDS
                if seconds < 90 * 60:
                    return f"{round(seconds / 60)} minutes"
                return f"{round(seconds / 3600, 1)} hours"
        return ""

    def lock(self, ticket: str | None = None, everywhere: bool = False) -> dict:
        """Throw a pass away now, or every pass at once."""
        if everywhere:
            closed = len(self.passes)
            self.passes.clear()
            self.open_until = 0.0
            return {"locked": True, "passes_closed": closed}
        if ticket and ticket in self.passes:
            del self.passes[ticket]
            return {"locked": True, "passes_closed": 1}
        return {"locked": True, "passes_closed": 0}

    def require(self, ticket: str | None, enabled: bool, now: float | None = None,
                scope: str = "conversation", about: str = "") -> None:  # fmt: skip
        """Let a call through, or stop it. Raises Locked with what to do about it.

        With scope "conversation" only the pass opens a call, so an opening stays with whoever
        made it. With scope "server" one code opens everything until the window runs out, which
        is easier to live with and gives away the point of the lock to anyone who reaches the
        server in that window with the secret in hand.

        **And it holds one patient to a session.** `about` is the archive this call names, which
        `mcp_server.answering` has already checked against what the link reaches. The first call
        to name one writes it on the pass; a later call naming another is refused, and the refusal
        says what to do — close this pass and take a new code. A conversation therefore holds the
        records of one person, and the one place two could have met is a model's own context.

        That is not the rule this used to keep. The old one wrote the archive at unlock time, out
        of whatever the dashboard had open, and tore the pass up when somebody pressed Show: a
        rule about the dashboard, which reaches no connector now. This one is about the
        conversation, and it binds to what was asked for rather than to what was on a screen.
        """
        if not enabled:
            return
        now = time.time() if now is None else now
        self._forget_old(now)
        given = self.passes.get(ticket or "")
        if scope == "server" and self.open_until > now:
            # Everything is open for the length of the window, which is what this setting means
            # and what the page says it means. **The one person to a conversation still holds**
            # wherever there is a conversation to hold it on: a call carrying a pass that has
            # already read somebody is refused for anybody else, exactly as under the other
            # setting. This return stood above that check, so choosing "everything" quietly
            # switched off a rule of the constitution — and the server went on telling the model,
            # in its own instructions, that one conversation holds one person. A call with no
            # pass at all has no conversation and is let through: that is the setting, and it is
            # the half the page warns about.
            if ticket and given and given[0] > now:
                self._hold_to_one_person(ticket, given, about)
            return

        if given and given[0] > now:
            self._hold_to_one_person(ticket, given, about)
            return
        raise Locked(
            "This archive is locked, which is normal and not a failure. Do not give up and do not "
            "answer from memory. Ask the person you are talking to for the six digits their "
            "authenticator app is showing for Epicrisis, call unlock with them, and pass the string "
            "it gives back as `ticket` on this and every later call. It stays good for a few hours."
        )

    def _wait_over(self, now: float) -> float:
        """Seconds still to wait before a code is even looked at."""
        runs = len(self.wrong) // WRONG_CODES
        if runs < 1:
            return 0.0
        minutes = WAITS_MINUTES[min(runs, len(WAITS_MINUTES)) - 1]
        return max(0.0, self.wrong[-1] + minutes * 60 - now)

    def clear(self) -> None:
        """Forget the guessing. For the owner, from the server, when a stranger made them wait.

        Written through as well as forgotten, or the next code reads the wait back off the file.
        """
        self.wrong = []
        self._keep_wrong()

    def _hold_to_one_person(self, ticket: str | None, given: tuple, about: str) -> None:
        """One conversation holds one person: bind this pass to the first archive asked about.

        Written once and called from both settings, because it belongs to neither of them. What a
        code opens — this conversation or the whole server for a while — is a question about who
        may call at all; this is a question about what one conversation may hold, and the first
        entry of the constitution does not have a setting.
        """
        if about and given[1] and given[1] != about:
            raise Locked(
                "This pass has been reading one person's records and is for that one only. "
                "To read another: call lock_archive on this pass, then unlock with a fresh "
                "six-digit code and ask about the other archive first. **The code comes from "
                "the same authenticator entry as the first one** — there is one code for this "
                "way in, not one for each person — so the person you are talking to has it "
                "already and nobody else has to be asked for anything. The records of two "
                "people do not go into one conversation: that is the rule here and not a "
                "fault of the question."
            )
        if about and not given[1]:
            # The first call to name somebody. Written here rather than at unlock, because a
            # code opens the lock and picks nobody: who the conversation is about is decided
            # by the first question asked in it.
            self.passes[ticket or ""] = (given[0], about)

    def _forget_old(self, now: float) -> None:
        self.passes = {ticket: held for ticket, held in self.passes.items() if held[0] > now}
        self.open_until = self.open_until if self.open_until > now else 0.0
        if self.wrong and self._wait_over(now) <= 0 and now - self.wrong[-1] > WAITS_MINUTES[-1] * 60:
            self.wrong = []
            self._keep_wrong()  # or the file outlives the run it recorded, for ever
        step = int(now // STEP_SECONDS)
        self.used = {(code, at) for code, at in self.used if at >= step - DRIFT_STEPS - 1}


def _clock(when: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(when, UTC).isoformat(timespec="minutes")
