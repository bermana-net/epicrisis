"""The editor of MCP links: which links exist, what each is called, and whose archives each opens.

**This is the one screen where the names of several people stand side by side**, each with a tick
box, and that is what it is for: a link is given its archives here and nowhere else. It is
allowed — the archives page already lists every owner — and it is the reason this module holds a
line nobody should delete: *a name and a tick, and nothing out of the archives beside them.* The
day a count of documents or a last-read date appears next to those names, this page stops being a
list of permissions and becomes a comparison of three people's records on one screen, which is
the first entry of the constitution read the wrong way round.

**A list and three sheets.** The page is the links, one row each, with what the row can be done
to beside it; everything that needs more room than a row — the address, the name, the ticks, the
taking back, the making of a new one — opens over it as a sheet. Each sheet is an address
(`?editing=`, `?deleting=`, `?issuing=`) and not a thing the page remembers, so it is closed by
Back as readily as by Cancel. Nothing on this page is scripted, which is not true of the dashboard
as a whole and is true here on purpose: what a sheet holds is the address somebody came to copy.

**Two secrets, and only one of them is shown once.** The address — the path secret — is drawn here
every time somebody opens the page, and that is the point: this is where a link is copied to hand
to another person, and a link that could not be looked at again would be a link lost the first
time a message was closed. The code secret for the authenticator is the other one, it is shown in
the single answer that creates it and never again, and the two must not be confused by whoever
reads this next: making the address shy would break the page's one job, and making the code
re-showable would put it in whatever asked.

**Every press here is live.** When this was written nothing read the registry while the server
was answering, and this paragraph said so; it is read on every request now — the path a request
arrives on is looked up in it, and so is the day a link stops. A tick taken off, a date brought
forward, a link taken back: each of them is in force on the next question that assistant asks,
with nothing restarted. What the page says is therefore what the server does, which is why none
of it may be worded as a plan.

What it does not do. It does not say which archive is open, which `sources.json` answers, and it
shows no count and no date out of anybody's records — see the line above about what may stand
beside these names.

Why it is a page of its own and not a tab of the settings page. The settings page answers "what
does this instance allow", one answer per question, and every switch on it is about the whole
instance or about the archive that is open. This answers "who may reach whom", one answer per
pair, and it is the only page in the program whose subject is **several** archives at once. A tab
would have put a grid of people's names inside a page whose own tabs are about the open archive.
"""

import io
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from epicrisis import connectors, journal
from epicrisis.settings import mcp_lock_on, the_name_the_tunnel_answers_on
from epicrisis.state import Unreadable

if TYPE_CHECKING:
    from epicrisis.web.app import TheArchives


@dataclass(frozen=True)
class Pressed:
    """What one press came to: what changed, what was refused, and which link to open again.

    The two halves of one sentence, as the settings page keeps them: a press that renamed a link
    and was turned down over its archives has two true things to say.
    """

    stored: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()
    looking_at: str = ""

    def said(self) -> str:
        return ", ".join(self.stored)


def a_qr_of(uri: str) -> str:
    """The authenticator URI as an inline SVG, or an empty string where it cannot be drawn.

    Inline and never a file: this picture holds the code secret, and a file is a thing that stays
    on a disk and gets served again. In the one response that creates a link, and nowhere else.

    Empty rather than raising. A page whose job is to hand somebody a credential must not fail
    because a drawing library is missing or because a URI came out longer than a symbol can
    carry — the URI is written out as text beside it, and that text is what an authenticator
    actually needs. The picture is the convenience.
    """
    try:
        import segno
    except ImportError:
        return ""
    try:
        # Medium correction, which is what authenticators are set up with, and a quiet border of
        # two modules because a QR with no margin is one many cameras will not see.
        drawn = segno.make(uri, error="m")
        held = io.BytesIO()
        drawn.save(held, kind="svg", scale=5, border=2, dark="#111", light="#fff",
                   xmldecl=False, svgversion=None, nl=False)  # fmt: skip
    except Exception:
        return ""
    return held.getvalue().decode("utf-8")


def connectors_view(data_dir: Path, archives: "TheArchives", *, looking_at: str = "",
                    sheet: str = "", stored: str = "", refused: tuple[str, ...] = ()) -> dict:  # fmt: skip
    """Every link, and for the one being looked at, which archives it may open.

    The archives are handed in rather than fetched, as every page in this program takes them: two
    readings of the list inside one answer can be two different lists, and this page draws the
    same names twice — once down the right-hand side and once as the ticks of the link being
    looked at.

    A registry that will not read is a page that says so and offers nothing to press. It is not
    an empty list: an empty list here reads as "no link has been issued", and somebody would make
    another one over the top of the file that holds the ones they have.

    `sheet` is which panel is open over the list — "editing", "deleting", "issuing", or nothing at
    all. It is an argument rather than a thing the page works out, because each of those is an
    address of its own: a sheet opened by a link can be left by the Back button, shared, and
    reloaded, and nothing on this page has to remember that it is open.
    """
    every = tuple(archives.all)
    host = the_name_the_tunnel_answers_on(data_dir)
    try:
        issued = connectors.load(data_dir)
    except Unreadable as torn:
        return {"trouble": torn.mend, "about": torn.safe, "links": (), "archives": every,
                "host": host, "looking_at": None, "sheet": "", "lock_on": mcp_lock_on(data_dir),
                "stored": stored, "refused": refused}  # fmt: skip
    rows = tuple(
        {
            "id": one.id,
            # What the owner called it, and a plain word where they have not. Never the id as a
            # name: a list of random ids is a list nobody can act on.
            "name": one.name or "unnamed",
            "named": bool(one.name),
            "live": one.live,
            "issued_at": one.issued_at,
            "revoked_at": one.revoked_at,
            # The two facts behind `live`, because the row has three things to say and not two:
            # a link somebody took back is not the same as one whose day went by, and the second
            # is the one a person fixes by typing a later date.
            "expired": one.expired(),
            "until": one.until,
            # By owner and never by id, for the same reason. `the_archives_it_may_open` reads the
            # claim against the archives that exist, so an id on a link that names no archive
            # here shows as nothing rather than as a row of hex.
            "whose": tuple(each.owner or "nobody named"
                           for each in connectors.the_archives_it_may_open(one, every)),  # fmt: skip
        }
        for one in issued
    )
    # The one being looked at: the one asked for, or the first live link, or nothing at all. Asked
    # for and revoked still opens, because "when did this stop working" is the question somebody
    # has when a connector goes quiet.
    chosen = next((one for one in issued if one.id == looking_at), None)
    if chosen is None:
        chosen = next((one for one in issued if one.live), None)
    open_now = None
    if chosen is not None:
        allowed = set(chosen.archives)
        open_now = {
            "id": chosen.id,
            "name": chosen.name,
            "live": chosen.live,
            "issued_at": chosen.issued_at,
            "revoked_at": chosen.revoked_at,
            "expired": chosen.expired(),
            "until": chosen.until,
            # The address, or nothing where this instance has no public name. The page says which
            # of the two it is and what to do about it, rather than printing half an address.
            "link": connectors.the_link_to(chosen, host),
            # Every archive with a tick beside it, which is why the press takes the whole set:
            # a tick that failed to arrive must not read as a tick nobody changed.
            "ticks": tuple({"id": each.id, "whose": each.owner or "nobody named",
                            "ticked": each.id in allowed} for each in every),  # fmt: skip
        }
    return {"trouble": "", "about": "", "links": rows, "archives": every, "host": host,
            "looking_at": open_now, "sheet": sheet if (open_now or sheet == "issuing") else "",
            # Whether a code stands between a link and the records it reaches. This page is where
            # a link is handed to somebody, so it is where the answer belongs: the owner of this
            # instance had the lock off for nine days and found out by watching an assistant
            # answer without asking him for anything.
            "lock_on": mcp_lock_on(data_dir),
            "stored": stored, "refused": refused}  # fmt: skip


@dataclass(frozen=True)
class Issued:
    """The one answer that carries a new link's code, and the only place it is ever drawn.

    Held apart from `Pressed` on purpose, because what it carries is different in kind: `Pressed`
    says what changed and goes back to the page through a redirect, and a redirect puts what it
    carries in an address bar and in a history. This is rendered where it stands and never
    becomes a URL.
    """

    connector_id: str
    name: str
    link: str
    uri: str
    qr: str


def issue_pressed(data_dir: Path, archives: "TheArchives", *, name: str = "",
                  archive_ids: tuple[str, ...] = (), until: str = "",
                  understood: str = "") -> Issued | Pressed:  # fmt: skip
    """Make a link. Returns what to show once, or a refusal to draw beside the form.

    The tick is asked for the way `forget` asks for one: this is the only thing the dashboard
    writes that is a credential rather than a note about an archive, and the one press that
    cannot be undone by pressing again — a link issued and lost is a link to revoke, not a link
    to look at.

    Nothing about a name is required. A link with no name is listed as unnamed and works exactly
    the same; refusing to issue one would be this page deciding that a person has to describe
    their own credential before they may have it.
    """
    if understood != "yes":
        return Pressed((), ("Tick the box to say you understand the code is shown once.",), "")
    known = {each.id for each in archives.all}
    unknown = [each for each in archive_ids if each not in known]
    if unknown:
        return Pressed((), ("One of those archives is not on this instance any more. Nothing was "
                            "issued; open the page again to see what it holds now.",), "")  # fmt: skip
    # The date is read before anything is written. A link issued and then refused its date would
    # be a live credential this page had not meant to hand over, with the code already shown.
    if until.strip():
        try:
            connectors.a_day(until)
        except ValueError:
            return Pressed((), ("Nothing was issued: write the last day as 2027-03-31, or leave it "
                                "empty for a link with no end.",), "")  # fmt: skip
    try:
        made, code_secret = connectors.issue(data_dir, name=name, until=until,
                                             archives=tuple(each for each in archive_ids if each in known))  # fmt: skip
    except OSError as problem:
        # The code secret is written before the line, so this is a link that was not issued at
        # all rather than one issued without a code. Named as what to do about it: the folder is
        # under /etc and the dashboard runs as whoever started it.
        return Pressed((), (f"No link was issued: the code secret could not be written ({problem.strerror}). "
                            f"The dashboard has to be able to write {connectors.SECRETS_FOLDER}.",), "")  # fmt: skip
    journal.record(data_dir, {"event": "an MCP link was issued", "connector": made.id,
                              "archives": len(made.archives)})  # fmt: skip
    uri = _the_authenticator_uri(made, code_secret)
    return Issued(made.id, made.name, connectors.the_link_to(made, the_name_the_tunnel_answers_on(data_dir)),
                  uri, a_qr_of(uri))  # fmt: skip


def _the_authenticator_uri(made, code_secret: str) -> str:
    """The line an authenticator turns into codes, named by what this link is called.

    `mcp_lock.uri` is the one place that line is built, and the account is what the owner called
    the link — so a phone holding codes for two of them says which is which. A link with no name
    is named by its id there, which carries no part of anybody's name and is what the page shows.
    """
    from epicrisis import mcp_lock

    return mcp_lock.uri(code_secret, account=made.name or made.id)


def connectors_pressed(data_dir: Path, archives: "TheArchives", *, connector_id: str = "",
                       name: str = "", archive_ids: tuple[str, ...] = (), until: str = "",
                       shown: tuple[str, ...] = (), revoke: str = "") -> Pressed:  # fmt: skip
    """One press of the editor: a name, a set of ticks, or a link taken back.

    `shown` is what the form drew, and it is read for the same reason the settings page reads it:
    a set of ticks absent from a press means "this page did not ask", never "every tick was
    cleared". Without it a press that saved a name would have taken every archive off the link.
    The date is held to the same discipline and needs it more: an empty date means "no end" and
    an absent one means "not asked", and the two look identical in a form.
    """
    stored: list[str] = []
    refused: list[str] = []
    if revoke:
        gone = connectors.revoke(data_dir, revoke)
        if gone is None:
            refused.append("That link is already revoked, or there is no such link.")
        else:
            journal.record(data_dir, {"event": "an MCP link was revoked", "connector": gone.id})
            stored.append("that link is revoked, and its code is off this machine")
        return Pressed(tuple(stored), tuple(refused), revoke)
    one = connectors.get(data_dir, connector_id) if connector_id else None
    if one is None:
        return Pressed((), ("There is no such link.",), connector_id)
    if "name" in shown and name.strip() != one.name:
        connectors.rename(data_dir, one.id, name)
        journal.record(data_dir, {"event": "an MCP link was renamed", "connector": one.id})
        stored.append(f"what it is called — “{name.strip()}”" if name.strip() else "that it has no name")
    if "until" in shown and until.strip() != one.until:
        # Read as a day before it is written, and said as a sentence when it is not one. The
        # browser's own date field sends nothing at all when what is in it is half typed, and
        # nothing at all means "no end" here — so a person who typed 2027-03 and pressed Save
        # would have been told the link now has no end, which is the opposite of what they meant.
        try:
            moved = connectors.set_until(data_dir, one.id, until)
        except ValueError:
            refused.append("The last day has to be written as 2027-03-31. The date was not "
                           "changed; everything else on this form was saved.")  # fmt: skip
        else:
            journal.record(data_dir, {"event": "when an MCP link stops answering was changed",
                                      "connector": one.id, "until": moved.until if moved else ""})  # fmt: skip
            stored.append(f"the last day it answers — {moved.until}" if moved and moved.until
                          else "that it has no last day")  # fmt: skip
    if "archives" in shown:
        known = {each.id for each in archives.all}
        # An id the form sent that is on no archive here is a form that does not match this
        # instance — a page left open while an archive was forgotten, most likely. Refused rather
        # than written: written, the link would carry an id that opens nothing and the page would
        # go on showing the tick as though it meant something.
        unknown = [each for each in archive_ids if each not in known]
        if unknown:
            refused.append("One of those archives is not on this instance any more. Nothing was "
                           "changed; open the page again to see what it holds now.")  # fmt: skip
        else:
            wanted = tuple(each for each in archive_ids if each in known)
            if set(wanted) != set(one.archives):
                changed = connectors.set_archives(data_dir, one.id, wanted)
                # The journal names the link and counts the archives. Not which archives: it names
                # people by id nowhere else either, and a line saying who somebody may now read is
                # a line about three people in a file that may be shown to anybody.
                journal.record(data_dir, {"event": "what an MCP link may open was changed",
                                          "connector": one.id,
                                          "archives": len(changed.archives if changed else ())})  # fmt: skip
                stored.append(f"what it may open — {len(wanted)} archive" + ("s" if len(wanted) != 1 else ""))
    return Pressed(tuple(stored), tuple(refused), one.id)
