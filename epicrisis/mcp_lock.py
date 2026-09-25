"""A lock on the archive over the network: a code from the owner's authenticator.

The path holds a secret and the tunnel only lets the connector's own network through, but neither
says who is calling. Two people with the same address and the same secret look the same. This
asks for something only the owner has: a six-digit code from their phone, by the ordinary rule
of RFC 6238, the one every authenticator implements.

How it works here. `unlock` takes a code and gives back a pass, good for as long as the instance
says (four hours to begin with). Every other
tool wants that pass and refuses without it. The pass is a random string that lives in the
conversation; a stranger who knows the path and sits inside the right network still does not have
it. `lock` throws a pass away early — worth doing when a conversation ends, because the pass
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
import os
import secrets
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

SECRET_FILE = Path("/etc/epicrisis/mcp-totp")
STEP_SECONDS = 30
DIGITS = 6
DRIFT_STEPS = 1  # one step either way: a phone's clock is never exactly a server's
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
    """Write the secret where only root and the group running the server can read it."""
    file = Path(path or SECRET_FILE)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(secret + "\n", encoding="utf-8")
    os.chmod(file, 0o640)
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
                ticket = secrets.token_urlsafe(18)
                until = now + minutes * 60
                self.passes[ticket] = (until, archive)
                # An instance set to open as a whole opens here too; one set to open a conversation
                # at a time leaves this at nothing, and the pass is the only way in.
                if scope == "server":
                    self.open_until = max(self.open_until, until)
                    self.opened_for = archive
                return {"pass": ticket, "open_for_minutes": minutes, "until": _clock(until)}
        self.wrong.append(now)
        raise Locked("That code does not fit, or it has already been used once.")

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
        """Forget the guessing. For the owner, from the server, when a stranger made them wait."""
        self.wrong = []

    def _forget_old(self, now: float) -> None:
        self.passes = {ticket: given for ticket, given in self.passes.items() if given[0] > now}
        self.open_until = self.open_until if self.open_until > now else 0.0
        if self.wrong and self._wait_over(now) <= 0 and now - self.wrong[-1] > WAITS_MINUTES[-1] * 60:
            self.wrong = []
        step = int(now // STEP_SECONDS)
        self.used = {(code, at) for code, at in self.used if at >= step - DRIFT_STEPS - 1}


def _clock(when: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(when, UTC).isoformat(timespec="minutes")
