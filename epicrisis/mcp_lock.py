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
WRONG_CODES_FILE = "mcp-lock-wrong-codes.json"  # the run of wrong codes, kept across a restart


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
    minutes: int = PASS_MINUTES
    open_until: float = 0.0  # while the whole server is open, for instances that ask for that
    opened_for: str = ""  # the archive that was open when that window was opened
    # pass -> (when it stops working, the archive it was given for). A pass opens one person's
    # archive, not this address: see require().
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
               scope: str = "conversation", archive: str = "") -> dict:  # fmt: skip
        """Take a code, give back a pass. Raises Locked on a wrong code or too many tries.

        The scope is the instance's own setting, and it is read here rather than only where a
        call is let through: an opening made for one conversation must not become an opening of
        the whole server if the setting changes while the pass is still good.
        """
        now = time.time() if now is None else now
        minutes = self.minutes if minutes is None else minutes
        if not self.secret:
            # A secret made after the server started is picked up here, without a restart.
            self.secret = read_secret()
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
                self.passes[ticket] = (until, archive)
                # An instance set to open as a whole opens here too; one set to open a conversation
                # at a time leaves this at nothing, and the pass is the only way in.
                if scope == "server":
                    self.open_until = max(self.open_until, until)
                    self.opened_for = archive
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
            self.opened_for = ""
            return {"locked": True, "passes_closed": closed}
        if ticket and ticket in self.passes:
            del self.passes[ticket]
            return {"locked": True, "passes_closed": 1}
        return {"locked": True, "passes_closed": 0}

    def require(self, ticket: str | None, enabled: bool, now: float | None = None,
                scope: str = "conversation", archive: str = "") -> None:  # fmt: skip
        """Let a call through, or stop it. Raises Locked with what to do about it.

        With scope "conversation" only the pass opens a call, so an opening stays with whoever
        made it. With scope "server" one code opens everything until the window runs out, which
        is easier to live with and gives away the point of the lock to anyone who reaches the
        server in that window with the secret in hand.

        A pass opens one person's archive. Whoever is holding it was told whose records they were
        reading, and that sentence has to stay true: when the archive being shown is changed on
        the dashboard, every pass given for the one before it stops working there and then. The
        session ends rather than quietly continuing over somebody else's records.
        """
        if not enabled:
            return
        now = time.time() if now is None else now
        self._forget_old(now)
        if scope == "server" and self.open_until > now and self.opened_for == archive:
            return
        given = self.passes.get(ticket or "")
        if given and given[0] > now:
            if given[1] == archive:
                return
            del self.passes[ticket or ""]
            raise Locked(
                "The archive shown by this server was changed to somebody else's while you were "
                "reading. This pass opened the one before it and has been closed, so that nothing "
                "of one person is read as another's. Ask for a six-digit code again to open the "
                "archive that is open now."
            )
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

    def _forget_old(self, now: float) -> None:
        self.passes = {ticket: given for ticket, given in self.passes.items() if given[0] > now}
        self.open_until = self.open_until if self.open_until > now else 0.0
        if self.wrong and self._wait_over(now) <= 0 and now - self.wrong[-1] > WAITS_MINUTES[-1] * 60:
            self.wrong = []
            self._keep_wrong()  # or the file outlives the run it recorded, for ever
        step = int(now // STEP_SECONDS)
        self.used = {(code, at) for code, at in self.used if at >= step - DRIFT_STEPS - 1}


def _clock(when: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(when, UTC).isoformat(timespec="minutes")
