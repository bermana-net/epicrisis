"""The archive as read-only MCP tools: `epicrisis mcp` over stdio, `--http` over the network.

Every tool reads the index and returns values as printed together with where they came from:
file id, pages, document date, and links to the card and the original page on this server. No
tool writes anything, reads a file from the archive, or runs anything.

Over the network the whole server lives behind one unguessable path, so a request that does not
carry the secret is answered as if nothing were there. The secret is the key to the archive: it
is read from a file, never printed, and never written to a log.

The tools state what they do not do: they never compare a value with its reference range, never
say whether something is normal, and never diagnose. Whoever reads the answers does that.
"""

import hmac
import ipaddress
import contextvars
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any, NamedTuple

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

from epicrisis import mcp_access, mcp_lock, query, rules
from epicrisis.sources import SourceRegistry
from epicrisis.rules import kinds

# Whose archive this is comes first, before anything about how to read it: a person reading a
# conversation should be able to see at a glance whose records were being talked about. The name
# here is the archive that was open when this session began, and the archive can be changed on
# the dashboard while the session runs — so the head says as much, and points at the field that
# is always right: archive_of, on every answer.
#: Whose archive this is is **not** said here, and the reason is that this sentence cannot be
#: taken back. It is handed over in the answer to `initialize`, once per connection, and the
#: protocol gives a server no way to change it afterwards — so a name written into it was composed
#: from whichever archive happened to be open when the process started and then stood at the top
#: of a model's context for as long as the process lived. Switch the archive at noon and every
#: answer is correctly about the second person while this line still names the first, which is the
#: one thing the first entry of the constitution forbids.
#:
#: Where the name belongs instead is the moment a person proves they may have it: `unlock` names
#: the archive its pass was issued for, and `Lock.require` refuses the moment the archive shown is
#: not that one, so the sentence a holder was told can never go stale — it dies with the pass. A
#: new code gives a new pass and a new sentence about whoever is open now. That is the owner's
#: design and it needed no new machinery: both halves were already here.
INSTRUCTIONS_HEAD = (
    "You are reading one person's own medical archive, through Epicrisis Companion. Whose it is is "
    "not written here: this server may hold several, one open at a time, and it can be changed "
    "while you are connected. Every answer says which archive it actually came from, in "
    "`archive_of`, and that field is the one to trust and to quote; where this archive asks for a "
    "code, the answer to `unlock` names whose records the pass was opened for."
)

INSTRUCTIONS = """One person's own medical archive, in Russian, Ukrainian, English, Spanish and Greek.

Documents are transcribed by a model, page by page, and every value is kept exactly as printed, with its unit and the reference range printed next to it on the form. Nothing is converted, normalised or computed.

Working with it:
- Matching is literal and per-language. A term that returns nothing in one language may return documents in another, and an empty result never means the archive lacks the subject. value_history and value_names widen a question to every spelling of a matching indicator and say which ones they used; search_documents does not, so ask it in more than one language.
- Names differ between labs and languages. Ask list_indicators first: an indicator gathers every spelling of one test, and value_history with its id returns the whole history. Where no indicator covers a test, use value_names to find the spellings; search and values match on a form of the text without case, accents or Ukrainian and Russian letter differences.
- The same result often appears in several files (a copy, an export, a letter citing it). One document of each group answers; ask for all_copies to see the rest.
- A value marked derived is calculated by the lab (a filtration rate), not measured.
- material says what was measured: urine, stool and so on, read from the heading of the table. An indicator such as Protein or Glucose holds both the blood and the urine test, because the printed name is the same; keep them apart by material, and never put them in one series.
- Reference ranges differ between labs and years; units differ too (g/L and g/dL). Say so rather than comparing across labs silently.
- Answers should quote what is printed and name the document (file id and date) so a person can open the original.

Every answer says whose archive it came from, in "archive_of". This server may hold the archives of several people, one open at a time, and a value of one person must never be read as another's.

This archive may be locked. When a tool answers that it is, that is not a failure and not a reason to stop or to answer from memory: the person you are talking to holds a six-digit code in their authenticator. Ask them for it, call unlock with it, and pass the string it returns as `ticket` on every call after that; it stays good for four hours. When the conversation is over, call lock_archive, because the pass stays written in the conversation.

`unlock` also says how many archives this way in reaches, and lists their signatures in `may_reach`. It does not name the people: ask `archive_name` for a signature when you need the name, one at a time, and only for a signature it listed. That is deliberate — a conversation that opened this and went no further has been told how many people are within reach and not who they are. Where there is more than one, say the names you were given and let the person you are talking to choose; the choosing is theirs and never yours, because what names a person is a claim about who somebody is.

Send the chosen signature as `archive` on every call. **One conversation holds one person.** The first call that names somebody settles who this conversation is about, and a later call naming another is refused — that is the rule here and not a fault of your question. If the person you are talking to wants to move to somebody else, call lock_archive, ask them for a fresh six-digit code, call unlock with it, and begin again: their records and the first person's must not sit in one conversation together."""


class TheArchiveServed(NamedTuple):
    """The archive one tool call is about: its id, and whose it is, for `archive_of`.

    One value rather than two readings, because the two have to be of the same person. Read
    apart, they were not: see `answering`.
    """

    id: str | None
    whose: str


def _page(rows: list, name: str, total: int | None, offset: int) -> dict[str, Any]:
    """One page of a list, saying where it sits: nothing is cut without the caller being told.

    The rows ride under "result", which is where a caller expects a list from a tool of this
    library, and "kind" says what they are. A page that renamed the list broke callers holding an
    older description of the tool: their schema asked for "result" and found a page without one.
    """
    answer: dict[str, Any] = {"kind": name, "result": rows, "returned": len(rows), "offset": offset}
    if total is not None:
        answer["total"] = total
        if offset + len(rows) < total:
            answer["next_offset"] = offset + len(rows)
    elif len(rows):
        answer["next_offset"] = offset + len(rows)
    return answer


TICKET = Annotated[str | None, Field(description="The string unlock gave back. Needed while this archive is locked.")]
#: Which archive this call is about, as a signature out of `may_reach`.
#:
#: An argument on every tool and never a thing the server remembers, which is what
#: `ARCHITECTURE.md` says of all four doors — every door takes the archive, no default — and what
#: the first entry of the constitution means by a call that forgets having to fail rather than
#: answer about somebody. The alternative was to keep the choice in the pass, and the deciding
#: difference is what a mistake looks like: forgotten here it is a refusal that names the
#: signatures, and forgotten there it is a confident answer about another person. This program has
#: already paid for the second shape once — `answering` exists because three readings of
#: `showing()` inside one call served one archive's counts under another archive's owner.
#:
#: Left out where the link reaches exactly one archive, because there is nothing to be ambiguous
#: about: the one archive is the answer. Where it reaches several, a call without it is refused.
ARCHIVE = Annotated[str | None, Field(description="The signature of the archive to answer about, out of the ones `unlock` listed in `may_reach`. May be left out only where this link reaches exactly one archive.")]


def _found_nothing(connection, words: str | None) -> dict[str, Any]:
    """What an empty answer has to say, so that it is not read as "the archive lacks this".

    Matching is literal and within one language. A term that finds nothing in Spanish may find
    documents in Ukrainian, and a model that sees a bare empty list will report the subject
    missing — which has already happened once, with a recommendation built on top of it.
    """
    counts = query.language_counts(connection)
    return {
        "found": 0,
        "this_is_not_evidence_of_absence": (
            "Nothing matched these words. Matching is literal and within one language, so this is "
            "not evidence that the archive lacks the test or the subject. Try the term in another "
            "language of the archive, or ask list_indicators, which gathers the spellings of one "
            "test across languages."
        ),
        "documents_by_language": counts,
        "searched_for": words,
    }


def _about_comparing(data_dir: Path) -> str:
    """What flagged_values says about comparing a value with its range, on this instance.

    "Where the instance allows it" is true of the program and useless to the caller: on an instance
    that does not allow it, a model reads that sentence, asks for the comparison, is refused, and
    asks again without it — one round of its own thinking and one of the person's waiting for a
    parameter that was never going to answer. One of the two repeated calls in a measured run of
    ten was this one. The refusal inside the tool stays where it is and remains the authority; this
    only stops the question being asked.

    Read once, where the server is built. The Ask page builds one per question, so it is read for
    every conversation; a server left running while the setting is changed says the older of the
    two until it is restarted, and the call is refused with the reason either way.
    """
    from epicrisis.settings import answer_mode

    if answer_mode(data_dir) == "direct":
        return ("compare_with_printed_range instead compares each value with the range printed beside it "
                "on that same form, and says how many could not be compared at all.")
    return ("compare_with_printed_range is refused on this instance and asking for it answers nothing: "
            "this instance shows what the forms printed and does not compare values with their ranges "
            "itself. The range printed beside each value comes back with the value, so read both.")


def build_server(data_dir: Path, over_the_network: bool = False, pinned_to: str | None = None) -> MCPServer:
    """The tools of one archive. The lock is asked for only where this server is reachable.

    The code exists because `--http` puts the archive on an address the internet can reach. Over
    stdio there is no address: the process is started by whoever already has the files — the Ask
    page of this person's own dashboard, or a terminal on this machine — and asking them for the
    six digits guards nothing, while the settings page promises in as many words that tools used
    on this machine are not affected.
    """

    # Nobody is named here, on a locked server or an open one. It used to be named where saying so
    # gave nothing away — which was true about what it gave away and wrong about what it claimed,
    # because the sentence outlived the archive it was composed from. See INSTRUCTIONS_HEAD.
    head = INSTRUCTIONS_HEAD
    # The version this program is, not a second version written down beside it: a string here
    # would go on telling a connector 0.2 for as long as nobody remembered it existed.
    from epicrisis import __version__

    server = MCPServer(name="epicrisis", instructions=f"{head}\n\n{INSTRUCTIONS}", version=__version__)
    # One lock per link, and one for stdio. A code is a thing one person holds, so the secret it
    # is checked against belongs to the link they were given — and the wait after five wrong codes
    # belongs there too: counted for the server, one person guessing badly would hold every other
    # link shut, which is somebody else's doctor locked out by a stranger.
    #
    # Made on demand and kept, because a lock holds the passes it has given out: a fresh one per
    # call would hand out a pass and then not know it. Over stdio there is no link, and that one
    # reads the instance's own secret as it always did — stdio is the owner at their own machine.
    locks: dict[str | None, mcp_lock.Lock] = {}

    def the_lock_for(link: str | None) -> mcp_lock.Lock:
        if link not in locks:
            from epicrisis import connectors

            # The file as well as what is in it: a secret written after this server started is
            # picked up without a restart, and the lock has to know **whose** file to read again.
            # Given only the secret, a link whose file could not be read fell back to the
            # instance's and accepted the code that once opened everything.
            its_own = connectors.secret_file(link) if link else None
            locks[link] = mcp_lock.Lock(
                secret=mcp_lock.read_secret(its_own), secret_file=its_own,
                remembers=mcp_lock.where_the_wait_is_kept(Path(data_dir), link),
            )  # fmt: skip
        return locks[link]

    def whom_this_link_may_reach(link: str | None) -> tuple[str, ...]:
        """The signatures of the archives the link answering may open, in the list's own order.

        Signatures and never names. The names are what this program is for, so it knows them —
        they are in `sources.json` where their owners typed them — and what is controlled here is
        **what leaves and when**: a pass nobody has used to look at a patient has given away no
        name at all, and the name of one comes back from a call about that one. That is
        measurable, unlike not knowing.

        Read against the archives that exist, through `connectors.the_archives_it_may_open`, so a
        signature on a link that names no archive here reaches nothing — which archives exist is
        `sources.json`'s answer and a second answerer is the defect this project spends its weeks
        removing.

        Over stdio there is no link, and the answer is every archive: stdio is the owner at their
        own machine, and the console has never asked them to prove anything.
        """
        from epicrisis import connectors
        from epicrisis.sources import SourceRegistry
        from epicrisis.state import Unreadable

        try:
            archives = SourceRegistry(Path(data_dir)).list()
        except Unreadable:
            return ()
        if link is None:
            return tuple(one.id for one in archives)
        try:
            entry = connectors.get(Path(data_dir), link)
        except Unreadable:
            # A registry that will not read reaches nothing, which is the direction that file
            # fails in everywhere else: the archives are shut rather than open.
            return ()
        if entry is None:
            return ()
        return tuple(one.id for one in connectors.the_archives_it_may_open(entry, archives))

    def answering(ticket: str | None, asked_about: str | None = None) -> tuple[dict[str, Any] | None, TheArchiveServed]:
        """What one tool call is about: the archive, decided once, and the notice that stops it.

        Every tool begins here and then carries that archive through its own answer instead of
        asking again. `showing()` reads the list of archives afresh, which is right — the archive
        can be switched while a client is connected — but one call used to read it three times:
        the pass was checked against the first reading, the index opened on the second, and the
        name put into `archive_of` on the third. A switch landing between them served one
        archive's counts under another archive's owner, and these instructions tell the model that
        `archive_of` is the field to trust and to quote.

        The lock is the worse half of it. `mcp_lock.require(archive=…)` exists so that nothing of
        one person is read as another's, and it was given the first reading while the data came
        from the second: a pass granted over one archive served a read of the other, which is the
        one thing that lock is there to prevent. Three readings of one question inside one call
        were a repeated chain of calls; this is the name they wanted.

        **Over the network the archive is the caller's argument and not what the dashboard shows.**
        That is the change this door was waiting for, and it is the last of the four
        `ARCHITECTURE.md` names to make it: every door takes the archive, no default. What the
        dashboard has open stops being able to move what a connector answers about at all — so
        the passes no longer have to be torn up when somebody presses Show, and the sentence that
        said they would has gone with it.

        Over stdio it is still `showing()`. There is no link there, nothing to be allowed, and no
        tunnel: it is the owner at their own machine, and a signature given there is checked only
        for being an archive that exists.
        """
        link = THE_LINK_ANSWERING.get()
        if link is None:
            # Over stdio, and the argument may still name one of the archives here.
            if not asked_about:
                # One reading, carried. Written as two calls to showing() this was the very defect
                # this function was made to end, and `test_one_call_of_one_tool_answers_out_of_one
                # _archive_however_the_server_moves` caught it within the minute.
                here = showing()
                return guard(ticket, here), here
            found = next((one for one in SourceRegistry(Path(data_dir)).list() if one.id == asked_about), None)
            if found is None:
                return _no_such_archive(), TheArchiveServed(None, "")
            here = TheArchiveServed(found.id, found.whose)
            return guard(ticket, here), here
        within_reach = whom_this_link_may_reach(link)
        if asked_about:
            if asked_about not in within_reach:
                # The same refusal `archive_name` gives, and for the same reason: an answer that
                # told "not yours" from "not there" would let somebody walk the signatures.
                return _no_such_archive(), TheArchiveServed(None, "")
            chosen = asked_about
        elif len(within_reach) == 1:
            # Nothing to be ambiguous about: one archive within reach is the answer, and a reader
            # of a link made for one person never has to name them.
            chosen = within_reach[0]
        elif not within_reach:
            # None at all, which is not the same sentence as "more than one". A link is issued
            # before anybody is ticked for it, and one whose archives were all taken away is in
            # the same state: told "say which one" it would read as a thing the caller got wrong.
            return _nobody_within_reach(), TheArchiveServed(None, "")
        else:
            return _which_archive(within_reach), TheArchiveServed(None, "")
        found = next((one for one in SourceRegistry(Path(data_dir)).list() if one.id == chosen), None)
        here = TheArchiveServed(chosen, found.whose if found else "")
        return guard(ticket, here), here

    def _no_such_archive() -> dict[str, Any]:
        """One refusal for a signature out of reach and a signature of no archive at all."""
        return {"archive_of": None, "no_such_access": True,
                "what_this_means": "This way in does not reach an archive with that signature. "
                "Ask `unlock` again for the signatures it does reach; nothing was read, and this "
                "says nothing about whether such an archive exists."}  # fmt: skip

    def _nobody_within_reach() -> dict[str, Any]:
        """Refused because this way in has not been given anybody, which is nobody's mistake here.

        Named as what it is and pointed at the person who can change it: a link is issued before
        the ticks are put beside it, so this is an ordinary half-finished state and not an error
        made by whoever is calling.
        """
        return {"archive_of": None, "no_such_access": True, "archives_within_reach": 0,
                "what_this_means": "This way in has not been given any archive to read, so there "
                "is nothing for it to answer about. Whoever keeps the server decides that, under "
                "Links over the network; nothing is wrong with the question."}  # fmt: skip

    def _which_archive(within_reach: tuple[str, ...]) -> dict[str, Any]:
        """Refused for want of knowing whom it is about, which is the whole point of the argument.

        A refusal and never a guess. Picking one of several would be this server deciding which
        person a question was about, and the one it picked would be answered confidently under
        somebody else's name — the failure `answering` was written to end.
        """
        return {"archive_of": None, "which_archive": list(within_reach),
                "what_to_do_now": "This way in reaches more than one archive, so every call has "
                "to say which one it is about: send the signature as `archive`. Ask "
                "`archive_name` for each of the signatures above if you need to say the names to "
                "the person you are talking to, and let them choose."}  # fmt: skip

    def guard(ticket: str | None, archive: TheArchiveServed) -> dict[str, Any] | None:
        """Whether this call may be answered at all. With the lock off it returns nothing.

        Locked, it gives back a notice rather than an error. An error is drawn as a failure and
        read as one; a notice is read as what it is — a step to take before the question can be
        answered. The field names are loud on purpose: an answer of no data must never be mistaken
        for an answer of no results.

        The archive is taken and not used here any more: the pass says who is calling and the call
        says which archive, and `answering` has already checked that the one named is one this way
        in reaches. Kept in the signature because every caller has it and the day the lock has a
        second question to ask about it, this is where it goes.
        """
        from epicrisis.settings import mcp_lock_on, mcp_lock_scope

        try:
            the_lock_for(THE_LINK_ANSWERING.get()).require(
                ticket, enabled=over_the_network and mcp_lock_on(data_dir),
                scope=mcp_lock_scope(data_dir), about=archive.id or "")  # fmt: skip
        except mcp_lock.Locked as refusal:
            # Whose archive this is is not said here. Someone holding the address and no code
            # would otherwise learn that it belongs to a named person, which is the one fact the
            # lock exists to keep.
            return {
                "locked": True,
                "this_is_not_data_and_not_a_failure": (
                    "The archive is locked. Nothing was searched, so this says nothing about what "
                    "the archive holds."
                ),
                "what_to_do_now": "You are at a medical archive that is locked. " + str(refusal),
            }
        return None

    @server.tool(description="Open this archive for four hours with the code from its owner's authenticator. Returns a pass to send as `ticket` on every call after that. Nothing else answers while the archive is locked.")
    def unlock(
        code: Annotated[str, Field(description="The six digits the owner's authenticator is showing now")],
    ) -> dict[str, Any]:
        from epicrisis.settings import mcp_lock_minutes, mcp_lock_scope

        try:
            scope = mcp_lock_scope(data_dir)
            link = THE_LINK_ANSWERING.get()
            # The pass no longer carries an archive. It says who is calling; which archive a call
            # is about is the call's own argument, and two answers to one question is what
            # ARCHITECTURE forbids. What the archive on a pass used to buy — tearing up every pass
            # when somebody pressed Show on the dashboard — is bought now by the dashboard not
            # being able to move what a connector answers about at all.
            opened = the_lock_for(link).unlock(code, minutes=mcp_lock_minutes(data_dir), scope=scope)
            may_reach = whom_this_link_may_reach(link)
            return {**opened, "opens": scope,
                    # **This answer names nobody**, and that is the whole of the fifth entry's
                    # half of this step. It used to carry `archive_of` — the owner of whatever the
                    # dashboard had open — which was right while that was the archive the next
                    # call would be answered out of. It no longer is: this opens the lock and
                    # reads nothing, so there is no archive for it to be about, and a name here
                    # would be telling an assistant who somebody is before anybody asked.
                    #
                    # What a pass that is never used has now given away: a count. `archive_name`
                    # gives one name, for one signature, when somebody asks for it.
                    "may_reach": list(may_reach), "archives_within_reach": len(may_reach),
                    # How to say which of them a call is about. One line, because an assistant
                    # that has to work it out will work it out wrongly once.
                    "how_to_choose": "Send one of those signatures as `archive` on every call. "
                    + ("It may be left out: this way in reaches one archive."
                       if len(may_reach) == 1 else
                       "It is required, because this way in reaches more than one."),
                    # Which link this code belonged to. Four random bytes carrying no part of
                    # anybody's name, and the thing the owner needs to say when they want it
                    # taken back — "the one called such-and-such" is a name they chose, and this
                    # is what the page and the log of calls both print beside it.
                    **({"opened_through_link": link} if link else {}),
                    # What used to be here said the pass would close if somebody switched the
                    # archive on the dashboard. That stopped being true the moment a call names
                    # the archive itself: the dashboard moves nothing here now. §7 — the sentence
                    # says what is, and the old one would have been a promise about a thing that
                    # no longer happens.
                    "what_this_pass_is": "This pass says it is you calling, for "
                    f"{mcp_lock_minutes(data_dir)} minutes. It picks nobody: the first question "
                    "you ask with it settles whose records it is for, and from then on it "
                    "answers about that one person. For another, close this pass with "
                    "`lock_archive` and open a new one with a fresh code from the same "
                    "authenticator entry — the code belongs to this way in, not to any one "
                    "person. Nothing anybody does on the dashboard moves what you are reading."}  # fmt: skip
        except mcp_lock.Locked as refusal:
            raise ToolError(str(refusal)) from refusal

    @server.tool(description="Close this archive now instead of waiting for the pass to run out. Worth doing when a conversation ends: the pass stays written in it.")
    def lock_archive(
        ticket: TICKET = None,
        archive: ARCHIVE = None,
        everywhere: Annotated[bool, Field(description="Close every pass that is open, not only this one")] = False,
    ) -> dict[str, Any]:
        if everywhere:
            # Shutting everyone out is something only someone already let in may do; otherwise a
            # stranger who reached this address could keep the archive closed to its owner.
            notice, _served = answering(ticket, archive)
            if notice is not None:
                return notice
        # The lock of the link this call came through, so "close everything that is open" closes
        # what this link opened and nothing anybody else holds.
        return the_lock_for(THE_LINK_ANSWERING.get()).lock(ticket, everywhere=everywhere)

    def showing() -> TheArchiveServed:
        """The archive being served and whose it is. Every answer says the name, so that one
        person's records can never be read as another's.

        Asked afresh every call, because the archive can be switched while a client is connected —
        except where this server was started for one archive and told which. The Ask page of the
        dashboard starts one per question, and a question takes tens of seconds: switching archive
        in another tab meanwhile had the rest of that answer read from somebody else's records and
        written into a conversation filed under the first person. Over the network the same case
        is refused, and well — the pass ends rather than quietly continuing over another's records.
        """
        from epicrisis.sources import SourceRegistry
        from epicrisis.sources import showing as the_archive

        if pinned_to:
            held = SourceRegistry(Path(data_dir)).get(pinned_to)
            return TheArchiveServed(held.id, held.whose) if held else TheArchiveServed(pinned_to, "")
        active = the_archive(data_dir)
        return TheArchiveServed(active.id, active.whose) if active else TheArchiveServed(None, "")

    @contextmanager
    def index(archive: TheArchiveServed):
        """The index of the archive being served, for the length of one tool call.

        The archive comes in rather than being looked up here, because looking it up here was a
        second reading of a question the call had already answered. See `answering`.

        A tool that cannot open the index says so in words. It used to raise whatever SQLite
        raised, which reached the person as "Error executing tool search_documents" and nothing
        else — so a server whose files had been made unreadable looked exactly like a server that
        had been asked something it could not answer. The reason is here; the journal has the rest.
        """
        # Tools run in worker threads and an SQLite connection belongs to one thread.
        try:
            connection = query.open_index(data_dir, archive.id)
        except (sqlite3.Error, query.IndexMissing, OSError) as trouble:
            raise ToolError(cannot_be_read(trouble)) from trouble
        try:
            yield connection
        except sqlite3.Error as trouble:
            raise ToolError(cannot_be_read(trouble)) from trouble
        finally:
            connection.close()

    def cannot_be_read(trouble: Exception) -> str:
        """What to say when the archive is there but the server cannot read it."""
        return (
            f"This archive cannot be read on the server right now ({trouble}). Nothing was "
            "searched, so this says nothing about what the archive holds. Whoever keeps the "
            "server should look at its journal: the index may not have been built yet, or the "
            "files may have been written by another account than the one the server runs as."
        )

    @server.tool(description="Whose archive one signature belongs to, as its owner typed the name. Ask it of the signatures `unlock` listed, one at a time, so that the person you are talking to can say which of them to work with. It answers only for the archives this link may open.")
    def archive_name(
        signature: Annotated[str, Field(description="One of the signatures `unlock` returned in `may_reach`")],
        ticket: TICKET = None,
    ) -> dict[str, Any]:  # fmt: skip
        """The name of one archive, asked for one signature at a time.

        **Why a name is asked for rather than listed.** The names are the program's to give — they
        are in `sources.json`, typed by their owner, and `archive_of` carries one on every answer
        about an archive being read. What this keeps is the timing: a conversation that opened a
        link and went no further has been told how many people are within its reach and not who
        they are, and each name after that is a thing somebody asked for.

        **Why a signature and not a name the other way round.** A name is a spelling. Two people
        share one, and one person is written two ways; the fourth entry says that what names a
        person is a claim, settled by the person whose archive it is and never by matching text.
        So the choosing takes the signature, and a name is what comes back for reading aloud.

        **The refusal is one refusal.** A signature outside this link's reach and a signature of
        no archive at all answer the same words, because an answer that told them apart would let
        somebody walk the signatures and learn how many archives this machine holds and which of
        them they are nearly allowed.
        """
        # **Naming is not reading, so this one tool is outside the pass's archive.** It went
        # through `answering` like the rest, which meant two things at once: without `archive` it
        # was told "say which archive" — the very question it exists to help a person answer —
        # and with one it was refused by a pass already bound to somebody else. So the server
        # told an assistant to ask here, and then refused to answer. Seen within an hour of the
        # lock being turned on: a person was offered a choice between three people and could not
        # be told who two of them were.
        #
        # What this gives away is a name, for one signature, of an archive this link already
        # reaches — the one thing about another archive that is ever shown, and the thing the
        # person choosing has to hear. It neither binds the pass nor is refused by a bound one.
        # The lock still has to be open: a way in with no code learns how many people are within
        # reach and not who they are.
        notice = guard(ticket, TheArchiveServed(None, ""))
        if notice is not None:
            return notice
        link = THE_LINK_ANSWERING.get()
        within_reach = whom_this_link_may_reach(link)
        if not within_reach:
            # Half-finished and not a mistake of the caller's, which is the sentence `answering`
            # gives and which this tool used to borrow from it. A link issued before anybody was
            # ticked for it says so in those words, rather than answering "no such archive" to
            # every signature there is.
            return _nobody_within_reach()
        if signature not in within_reach:
            return {"archive_of": None, "no_such_access": True,
                    "what_this_means": "This link does not reach an archive with that signature. "
                    "Ask `unlock` again for the signatures it does reach; nothing was read and "
                    "this says nothing about whether such an archive exists."}  # fmt: skip
        from epicrisis.sources import SourceRegistry

        found = next((one for one in SourceRegistry(Path(data_dir)).list() if one.id == signature), None)
        return {"archive_of": found.whose if found else "", "signature": signature}

    @server.tool(description="What the archive holds: counts of documents and values, the span of dates, types and languages. Counts only: nothing here says whether anything in it is normal.")
    def archive_overview(ticket: TICKET = None, archive: ARCHIVE = None) -> dict[str, Any]:
        notice, served = answering(ticket, archive)
        if notice is not None:
            return notice
        with index(served) as connection:
            return {"archive_of": served.whose, **query.overview(connection)}

    @server.tool(description="Documents whose text, title, institution or value names match the words. Returns a piece of the original text around the match, as printed. Matching is literal: it does not rank documents by importance and an empty answer is not evidence the archive lacks the subject.")
    def search_documents(
        query_text: Annotated[str, Field(description="Words to look for, in any of the archive's languages")],
        limit: Annotated[int, Field(description="How many documents", ge=1, le=200)] = 20,
        since: Annotated[str | None, Field(description="Earliest document date, YYYY-MM-DD")] = None,
        until: Annotated[str | None, Field(description="Latest document date, YYYY-MM-DD")] = None,
        doc_type: Annotated[str | None, Field(description="lab_panel, imaging_report, consultation, discharge, prescription, referral, admin, insurance, other")] = None,
        offset: Annotated[int, Field(description="Skip this many, to read the next page", ge=0)] = 0,
        ticket: TICKET = None,
        archive: ARCHIVE = None,
    ) -> dict[str, Any]:
        notice, served = answering(ticket, archive)
        if notice is not None:
            return notice
        with index(served) as connection:
            rows = query.search(connection, query_text, limit=limit, since=since, until=until,
                                doc_type=doc_type, offset=offset)  # fmt: skip
            if not rows and not offset:
                return {"archive_of": served.whose, **_found_nothing(connection, query_text)}
            # Through _page, whose own words are "nothing is cut without the caller being told" —
            # which this tool did not do. "found" was the length of the page: twenty-two matches
            # answered as twenty, in an answer shaped exactly like the answer to "that is all there
            # is", and a model then wrote about the archive from part of it. The count was already
            # in this file's reach, and the page of the dashboard has been showing it all along.
            total = query.count_search(connection, query_text, since=since, until=until, doc_type=doc_type)
            return {"archive_of": served.whose, **_page(rows, "documents", total, offset)}

    @server.tool(description="Documents by their own printed date, newest first. Returns a page and says how many there are in all. The dates are the ones printed on the documents; nothing here groups them into episodes or decides which of them matter.")
    def list_documents(
        since: Annotated[str | None, Field(description="Earliest document date, YYYY-MM-DD")] = None,
        until: Annotated[str | None, Field(description="Latest document date, YYYY-MM-DD")] = None,
        doc_type: Annotated[str | None, Field(description="Document type to keep")] = None,
        limit: Annotated[int, Field(description="How many documents in this page", ge=1, le=200)] = 25,
        offset: Annotated[int, Field(description="Skip this many, to read the next page", ge=0)] = 0,
        ticket: TICKET = None,
        archive: ARCHIVE = None,
    ) -> dict[str, Any]:
        notice, served = answering(ticket, archive)
        if notice is not None:
            return notice
        with index(served) as connection:
            rows = query.timeline(connection, since=since, until=until, doc_type=doc_type, limit=limit, offset=offset)
            total = query.count_documents(connection, since=since, until=until, doc_type=doc_type)
            return {"archive_of": served.whose, **_page(rows, "documents", total, offset)}

    @server.tool(description="How a test is printed across the archive: every printed name matching the words, with how often it appears and over which years. Spellings, not meanings: it does not say that two printed names are the same test unless a person has said so.")
    def value_names(
        query_text: Annotated[str | None, Field(description="Part of a name, in any language")] = None,
        limit: Annotated[int, Field(description="How many names", ge=1, le=200)] = 50,
        include_derived: Annotated[bool, Field(description="Include values the lab calculated, such as filtration rates")] = False,
        offset: Annotated[int, Field(description="Skip this many, to read the next page", ge=0)] = 0,
        ticket: TICKET = None,
        archive: ARCHIVE = None,
    ) -> dict[str, Any]:
        notice, served = answering(ticket, archive)
        if notice is not None:
            return notice
        with index(served) as connection:
            rows = query.value_names(connection, query_text, limit=limit,
                                     include_derived=include_derived, offset=offset)  # fmt: skip
            indicators = query.indicators_matching(connection, query_text)
            if not rows and not indicators and not offset:
                return {"archive_of": served.whose, **_found_nothing(connection, query_text)}
            total = query.count_value_names(connection, query_text, include_derived=include_derived)
            answer: dict[str, Any] = {"archive_of": served.whose, **_page(rows, "printed_names", total, offset)}
            if indicators:
                # The names printed in other languages sit under the same indicator as these ones.
                answer["indicators_holding_these_words"] = [
                    {"id": item["id"], "label": item["label"], "spellings": item["names"]} for item in indicators
                ]
            return answer

    @server.tool(description="Indicators: one label over the many ways a test is printed across laboratories and languages. Use an indicator id with value_history to get a whole history at once. Returns a page; ask for the next with offset. A label is a grouping of spellings that a person approved, not a judgement about the test or about anybody's results.")
    def list_indicators(
        status: Annotated[str | None, Field(description="approved, proposed, or null for all")] = "approved",
        limit: Annotated[int, Field(description="How many indicators in this page", ge=1, le=200)] = 50,
        offset: Annotated[int, Field(description="Skip this many, to read the next page", ge=0)] = 0,
        with_spellings: Annotated[bool, Field(description="Include every printed spelling of each indicator. Off by default: the whole list with spellings does not fit in one answer.")] = False,
        ticket: TICKET = None,
        archive: ARCHIVE = None,
    ) -> dict[str, Any]:
        notice, served = answering(ticket, archive)
        if notice is not None:
            return notice
        with index(served) as connection:
            rows = query.indicator_list(connection, status=status, brief=not with_spellings, limit=limit, offset=offset)
            return {"archive_of": served.whose, **_page(rows, "indicators", query.count_indicators(connection, status=status), offset)}

    @server.tool(description="Every value of one indicator, or whose printed name contains the words, as printed, oldest first, with unit, reference range, flag and the document it comes from. Nothing is converted, averaged or compared: values in different units stay in the units their forms printed, and none of them is marked high or low here.")
    def value_history(
        name: Annotated[str | None, Field(description="Words of the printed name, for instance 'цистатин' or 'cistatina'")] = None,
        indicator: Annotated[str | None, Field(description="Indicator id from list_indicators: every spelling at once")] = None,
        since: Annotated[str | None, Field(description="Earliest document date, YYYY-MM-DD")] = None,
        until: Annotated[str | None, Field(description="Latest document date, YYYY-MM-DD")] = None,
        include_derived: Annotated[bool, Field(description="Include values the lab calculated from others")] = False,
        all_copies: Annotated[bool, Field(description="Include documents that are copies of one another")] = False,
        material: Annotated[str | None, Field(description="Keep one material: urine, stool, csf, saliva, sputum, semen, swab, or 'none' for values whose form does not say (usually blood)")] = None,
        limit: Annotated[int, Field(description="How many values", ge=1, le=200)] = 200,
        ticket: TICKET = None,
        archive: ARCHIVE = None,
    ) -> dict[str, Any]:
        notice, served = answering(ticket, archive)
        if notice is not None:
            return notice
        with index(served) as connection:
            rows = query.values(connection, name, since=since, until=until, include_derived=include_derived,
                                all_copies=all_copies, limit=limit, indicator=indicator, material=material)  # fmt: skip
            searched: dict[str, Any] = {}
            if name and not indicator:
                # One test is printed a dozen ways across languages. A question in one of them
                # should find the values printed in the others, and say that it did.
                held = query.indicators_matching(connection, name)
                seen = {(item["document_id"], item["page"], item["name"], item["value"]) for item in rows}
                for item in held:
                    for more in query.values(connection, None, indicator=item["id"], since=since, until=until,
                                             include_derived=include_derived, all_copies=all_copies,
                                             limit=limit, material=material):  # fmt: skip
                        key = (more["document_id"], more["page"], more["name"], more["value"])
                        if key not in seen:
                            seen.add(key)
                            rows.append(more)
                if held:
                    rows.sort(key=lambda item: (item["date"] is None, item["date"] or "", item["page"]))
                    rows = rows[: max(1, min(limit, 200))]
                    searched = {"searched_every_spelling_of": [
                        {"id": item["id"], "label": item["label"], "spellings": item["names"]} for item in held
                    ]}  # fmt: skip
            if not rows:
                return {"archive_of": served.whose, **_found_nothing(connection, name)}
            # How many there are under the same question, not how many fitted. The rows come back
            # oldest first and the cap takes them from the top, so a test with more values than
            # the cap answered with its oldest and said nothing about the rest — and a history
            # that stops years ago reads like a history that stops years ago, not like a page of
            # one. Counted with the same period as the list, or the note would fire on a question
            # that was narrowed on purpose and tell the model to narrow it again.
            answer = {"archive_of": served.whose, "result": rows, "found": len(rows), **searched}
            # The same set the rows were gathered from, counted once. Summing a count per indicator
            # answered a different question twice over: a value printed under a name this question
            # matched, but under no indicator, was not counted at all, and a value under two of them
            # was counted twice. On the live archive the note said "50 earliest of 89" where 185
            # matched — and where the sum came out at or below the page, the note was left off
            # altogether and a cut answer looked like the whole of a history.
            spellings = tuple(item["id"] for item in (searched.get("searched_every_spelling_of") or []))
            if indicator:
                answer["values_in_all"] = query.count_values(
                    connection, indicator=indicator, material=material, include_derived=include_derived,
                    all_copies=all_copies, since=since, until=until)  # fmt: skip
            elif name:
                answer["values_in_all"] = query.count_values(
                    connection, name=name, indicators=spellings, material=material,
                    include_derived=include_derived, all_copies=all_copies, since=since, until=until)  # fmt: skip
            held = answer.get("values_in_all")
            if held is None or held <= len(rows):
                answer.pop("values_in_all", None)
            else:
                answer["note"] = (f"These are the {len(rows)} earliest of {held} that match. Narrow the "
                                  "period with since and until to reach the later ones.")  # fmt: skip
            return answer

    @server.tool(description="Values a laboratory itself marked on the form (H, L, an asterisk, an arrow), over a period. The archive never adds a mark of its own. " + _about_comparing(data_dir))
    def flagged_values(
        since: Annotated[str | None, Field(description="Earliest document date, YYYY-MM-DD")] = None,
        until: Annotated[str | None, Field(description="Latest document date, YYYY-MM-DD")] = None,
        flag: Annotated[str | None, Field(description="One printed mark to keep, for instance H")] = None,
        indicator: Annotated[str | None, Field(description="Indicator id to keep")] = None,
        compare_with_printed_range: Annotated[bool, Field(description="Compare the number with the range printed beside it on the same form instead of reading the mark. Needs the instance to allow it. The answer is about that laboratory's printed range, not about the person.")] = False,
        include_derived: Annotated[bool, Field(description="Include values the lab calculated from others")] = False,
        limit: Annotated[int, Field(description="How many values in this page", ge=1, le=200)] = 100,
        offset: Annotated[int, Field(description="Skip this many, to read the next page", ge=0)] = 0,
        ticket: TICKET = None,
        archive: ARCHIVE = None,
    ) -> dict[str, Any]:
        notice, served = answering(ticket, archive)
        if notice is not None:
            return notice
        from epicrisis.settings import answer_mode, rules_on

        # Only the last mode, where the person has taken every limit off their own instance, lets
        # the application itself compare a value with a range. In the middle mode the model may
        # compare — it has the reference beside every value — but the application does not.
        if compare_with_printed_range and answer_mode(data_dir) != "direct":
            return {
                "archive_of": served.whose,
                # Not "you may have this if you take every limit off". That sentence sent people
                # to switch off the last of their own limits for something they did not need it
                # for: the range is printed beside every value in the answer, and reading it is
                # reading the form. What is refused here is the application doing the arithmetic
                # and calling the result a finding.
                "refused": "This instance shows values as printed and does not compare them with their ranges itself. This is about what the application will compute, not about what may be said.",
                "instead": "Ask without compare_with_printed_range: every value comes back with the range printed beside it on its own form, and you can compare them yourself. Or ask for the marks the laboratories themselves printed.",
                "how_to_allow": "Only an instance with every limit taken off on the Settings page has the application compare them. That setting is about more than this, and it is not needed to read a printed range.",
            }
        with index(served) as connection:
            rows, counts, how_many = query.flagged_values(
                connection, since=since, until=until, flag=flag, indicator=indicator,
                include_derived=include_derived, compare_with_printed_range=compare_with_printed_range,
                limit=limit, offset=offset,
                # The same rules the charts are drawn with: a list that judged a value against a
                # range printed at another scale would report the scale as an excursion.
                placing=rules_on(data_dir, rules.load(data_dir), kinds.CHARTS, in_archive=served.id),
            )  # fmt: skip
            # With the count, so that a page says whether it is the whole of it. Without one, _page
            # offers a next_offset on any page that has rows at all, and six values returned out of
            # six read as six out of many: the three tools that cut in silence were given their
            # counts a release ago and this was the fourth, cutting nothing and saying so anyway.
            answer = {"archive_of": served.whose, **_page(rows, "values", how_many, offset)}
            answer["compared_with_printed_range"] = bool(compare_with_printed_range)
            if not rows:
                # The emptiest answer in this program and the most easily misread: asked whether
                # anything was flagged and handed a bare list, a model says the laboratories
                # marked nothing, and a person reads that as "nothing was wrong with them". The
                # archive holds no mark of its own — only the ones printed on the forms — so an
                # empty list here is a fact about what was printed and about nothing else.
                answer["this_is_not_evidence_of_absence"] = (
                    "No value in this archive carries a mark of the kind asked for. The archive never"
                    " adds a mark of its own: these are the ones laboratories printed on their forms,"
                    " and a form that printed none is not a form that found nothing. This says nothing"
                    " about the person, and nothing about values the question did not reach."
                )
            if compare_with_printed_range:
                # The two sides are not symmetric, and saying so is part of the answer: a value
                # outside a printed range is a fact about that laboratory's range, while a value
                # inside it says little, and a range that could not be read says nothing at all.
                answer["counted"] = counts
                answer["what_this_is"] = (
                    "Each number was compared with the range printed beside it on its own form."
                    f" {counts['outside']} fell outside, {counts['inside']} did not, and {counts['range_not_read']}"
                    " could not be compared because their printed range cannot be read plainly."
                    f" A further {counts.get('no_range_printed', 0)} are not in any of those three:"
                    " their form printed no range beside them at all, so there was nothing to compare"
                    " them with. A laboratory's range is for a general population and may not fit this"
                    " person; inside it is not the same as fine, and this is never a count of everything."
                )
            return answer

    @server.tool(description="One document: header and counts of every part, then the parts asked for, a page at a time. A long document does not fit in one answer, so 'counts' says what the document holds and 'more' says what is left; offset and limit are the same for every part asked for, so a part that has more is asked for on its own, with its own next_offset. Ask with parts=['sections','text'] for the words rather than the table. Parts of a document as it was transcribed; it neither summarises the document nor says what it means.")
    def get_document(
        file_id: Annotated[str | None, Field(description="Short file id, eight characters")] = None,
        first_page: Annotated[int | None, Field(description="First page of the document within the file")] = None,
        document_id: Annotated[int | None, Field(description="Document id from another answer")] = None,
        parts: Annotated[list[str] | None, Field(description="Which parts to return: values, sections, text, diagnoses, medications, unreadable, to_check, copies. All but the text by default.")] = None,
        offset: Annotated[int, Field(description="Skip this many items of each part asked for", ge=0)] = 0,
        limit: Annotated[int, Field(description="How many items of each part", ge=1, le=200)] = 40,
        text_offset: Annotated[int, Field(description="Where to start in the transcribed text, in characters", ge=0)] = 0,
        with_text: Annotated[bool, Field(description="Include the transcribed page text. Ask for it when the words matter: a report's findings live in the text, not in the values.")] = False,
        ticket: TICKET = None,
        archive: ARCHIVE = None,
    ) -> dict[str, Any] | None:
        notice, served = answering(ticket, archive)
        if notice is not None:
            return notice
        chosen = tuple(parts) if parts else tuple(part for part in query.PARTS if part != "text" or with_text)
        with index(served) as connection:
            found = query.document(
                connection, document_id=document_id, file_id=file_id, first_page=first_page,
                with_text=with_text or bool(parts and "text" in parts), parts=chosen,
                offset=offset, limit=limit, text_offset=text_offset,
            )  # fmt: skip
            if not found:
                return None
            answer = {"archive_of": served.whose, **found}
            if "more" in answer:
                # One offset for every part asked for, and a next_offset of its own under each part
                # that was cut: a caller that asks for the cut part by itself and leaves the offset
                # behind gets the first page over again. That was one of two repeated calls in a
                # measured run of ten — the same document, the same part, the same page of it —
                # and neither the answer nor the description said how the two fit together.
                answer["how_to_ask_for_the_rest"] = (
                    "Each part under 'more' was cut. offset and limit apply to every part asked for at"
                    " once, so ask for one part at a time with that part's own next_offset:"
                    " parts=['sections'], offset=<its next_offset>. Asking again without the offset"
                    " returns the page you already have."
                )
            return answer

    @server.tool(description="Documents the validation flagged for a person to check: incomplete transcriptions, dates, copies, parts that could not be read. Every one of these is about the reading of a page, never about the health of the person the page is about.")
    def documents_to_check(
        code: Annotated[str | None, Field(description="One check code, for instance date_to_check or transcription_incomplete")] = None,
        limit: Annotated[int, Field(description="How many documents", ge=1, le=200)] = 50,
        offset: Annotated[int, Field(description="Skip this many, to read the next page", ge=0)] = 0,
        ticket: TICKET = None,
        archive: ARCHIVE = None,
    ) -> dict[str, Any]:
        notice, served = answering(ticket, archive)
        if notice is not None:
            return notice
        with index(served) as connection:
            rows = query.to_check(connection, code=code, limit=limit, offset=offset)
            total = query.count_to_check(connection, code=code)
            return {"archive_of": served.whose, **_page(rows, "documents_to_check", total, offset)}

    return server


MIN_SECRET = 32
LOCAL_HOSTS = ("localhost", "127.0.0.1")


def new_path_secret() -> str:
    return secrets.token_hex(32)


def read_path_secret(path: Path) -> str:
    secret = Path(path).read_text(encoding="utf-8").strip()
    if len(secret) < MIN_SECRET:
        raise ValueError(f"the secret in {path} is shorter than {MIN_SECRET} characters")
    return secret


# Anthropic publishes the addresses its connectors call from. A request through the tunnel that
# comes from anywhere else is not a connector, whatever it knows about the path.
ANTHROPIC_OUTBOUND = "160.79.104.0/21"
OWN_NETWORKS = ("127.0.0.0/8", "::1/128", "100.64.0.0/10", "10.0.0.0/8", "192.168.0.0/16", "172.16.0.0/12", "fd7a:115c:a1e0::/48")


def _networks(spec: str) -> list[ipaddress._BaseNetwork]:
    return [ipaddress.ip_network(part.strip(), strict=False) for part in spec.split(",") if part.strip()]


def caller_of(headers: dict, peer: str) -> tuple[str, bool]:
    """Who is really calling, and whether the tunnel brought them.

    The tunnel connects from this machine, so the socket says nothing; it puts the caller's own
    address at the end of X-Forwarded-For and marks the request as its own. Only the last entry is
    read: anyone may send the header, but only what stands in front of us may add to it, and what
    it adds is the address it saw.

    Two kinds of tunnel put a caller in front of us. Funnel marks its requests; `tailscale serve`
    marks nothing, and a request through it used to arrive looking like a call from this machine —
    which made it welcome before --allow-from was so much as consulted, so the one setting that
    says "only the connectors may reach this" did nothing at all in that arrangement. A request
    from the loopback address carrying a forwarding header can only have been forwarded by
    something on this machine, so its last entry is read the same way. Nothing is given away by
    that: a caller who can reach us from loopback was already welcome, and all this can do is
    narrow who they are taken for.
    """
    through_tunnel = bool(headers.get("tailscale-funnel-request"))
    forwarded = [part.strip() for part in (headers.get("x-forwarded-for") or "").split(",") if part.strip()]
    passed_on_from_here = allowed_source(peer, _networks("127.0.0.0/8, ::1/128"))
    if forwarded and (through_tunnel or passed_on_from_here):
        return forwarded[-1], True
    return peer, through_tunnel


def how_it_arrived(headers: dict, peer: str) -> dict:
    """What the log needs beyond the address: where the connection itself came from, and who says so.

    The address above is taken from a header when the request came through a tunnel, which is
    right — the socket says only that the tunnel is on this machine. But anything on this machine
    can send that header too, so a process on the loopback could sign its calls with the published
    address of a connector, and the log is the only thing that ever says who read the archive: a
    person going back to it would have seen "the connector" and believed it.

    Nothing is refused because of this. What changes is that the line says where the connection
    actually came from and on whose word the address was taken, so the two can be told apart.
    """
    if not (headers.get("x-forwarded-for") or "").strip():
        return {}
    if headers.get("tailscale-funnel-request"):
        return {"arrived_from": peer, "address_claimed_by": "tailscale-funnel"}
    if allowed_source(peer, _networks("127.0.0.0/8, ::1/128")):
        # Said plainly: this address is what the request asked to be called, and the request came
        # from this machine. Anything here could have written it.
        return {"arrived_from": peer, "address_claimed_by": "a header, from this machine"}
    return {"arrived_from": peer, "address_claimed_by": "a header"}


def allowed_source(address: str, allow: list) -> bool:
    try:
        who = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(who in network for network in allow)


class RecordAccess:
    """Writes one line per HTTP call: who asked, for which tool, and whether they were let in.

    It reads the first body chunk to learn the name of the call and passes it on untouched. The
    arguments are not read and never written: a log of this archive that held the questions would
    be a second copy of it.
    """

    def __init__(self, app, data_dir: Path, allow_from: str = ANTHROPIC_OUTBOUND):
        self.app, self.data_dir = app, data_dir
        self.sweeps: dict[str, list] = {}  # address -> [when a line was last written, how many since]
        # Own networks are always in: this machine, and the private wire the dashboard lives on.
        self.allow = _networks(allow_from) + _networks(",".join(OWN_NETWORKS)) if allow_from else []

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        first = await receive()
        sent = False

        async def again():
            nonlocal sent
            if not sent:
                sent = True
                return first
            return await receive()

        headers = {name.decode().lower(): value.decode() for name, value in scope.get("headers", [])}
        address, through_tunnel = caller_of(headers, (scope.get("client") or ("", 0))[0])
        from_here = not through_tunnel and allowed_source(address, _networks(",".join(OWN_NETWORKS)))
        welcome = from_here or not self.allow or allowed_source(address, self.allow)
        # The path holds the secret, so it is compared the way a secret is compared — and a secret
        # of this program is made of letters and digits, so anything else in the path is a wrong
        # path and not a question. compare_digest refuses a string holding anything but ASCII by
        # raising, which happened before the request was written down at all: one accented letter
        # in the address and the server answered 500 to a scanner, told it something is there, and
        # kept no record of having been asked.
        asked_for = scope.get("path") or ""
        answered_by = self._whose_path(asked_for) if welcome else None
        allowed = answered_by is not None
        facts = {**mcp_access.request_facts(scope, allowed, None if allowed else ("address" if not welcome else "path")),
                 **how_it_arrived(headers, (scope.get("client") or ("", 0))[0])}  # fmt: skip
        if answered_by is not None:
            # Which link answered, so the log of calls can be read per connector. The id is four
            # random bytes carrying no part of anybody's name; the secret never reaches this line.
            facts["connector"] = answered_by
        called = self._called(first.get("body", b"") if first.get("type") == "http.request" else b"")
        if not welcome:
            # Refused before the path is looked at, so a wrong address learns nothing about it.
            # A sweep repeats hundreds of times a minute; written out in full it would push the
            # real calls out of the log, so one line a minute carries the count of the rest.
            repeats = self._sweep(address)
            if repeats is not None:
                mcp_access.record(self.data_dir, {**facts, "caller": address, "refused": "source", "repeats": repeats})
            return await self._refuse(send)
        if not allowed:
            # The path is compared the way a secret is compared, and it decides here — not in the
            # router underneath, which compares it as any string. The comment above said this
            # happened; nothing made it happen, and a wrong path fell through to a 404 from
            # Starlette instead of the same refusal a wrong address gets.
            mcp_access.record(self.data_dir, {**facts, "caller": address, "refused": "path"})
            # Answered as the router underneath would have answered: a wrong path finds nothing,
            # and nothing is what a server behind a secret address should look like.
            return await self._refuse(send, status=404, body=b"Not found.\n")
        mcp_access.record(self.data_dir, {**facts, **called, "caller": address})
        # The path is rewritten to the one the application underneath was built with, which is how
        # one application serves every link: the secret has done its work by here and goes no
        # further. `raw_path` as well, because what reads it is not what reads `path`, and a
        # request whose two disagreed is a request half of the stack answers differently.
        passed_on = {**scope, "path": SERVED_AT, "raw_path": SERVED_AT.encode("ascii"),
                     "epicrisis_connector": answered_by}  # fmt: skip
        # And in a place a tool can read, because the library hands a tool no request.
        #
        # The reset is not what keeps two links apart — every request that reaches the application
        # passes through this line and sets it, so a stale value would be written over rather than
        # read. Said plainly because a mutation that dropped the reset changed nothing any test
        # could see, and a comment claiming otherwise would have sent the next reader looking for
        # a guarantee that is not here. What it does buy is narrow and real: anything that reads
        # the variable after this request is finished — a task spawned inside it, a callback —
        # reads None rather than a link that has stopped answering.
        held = THE_LINK_ANSWERING.set(answered_by)
        try:
            return await self.app(passed_on, again, send)
        finally:
            THE_LINK_ANSWERING.reset(held)

    def _whose_path(self, asked_for: str) -> str | None:
        """Which live link this path belongs to, or None. Compared the way a secret is compared.

        Three things this holds, and each of them was a defect somewhere before:

        **Not ASCII is not a question.** `compare_digest` raises on a string holding anything else,
        which happened before the request was written down at all: one accented letter in the
        address and the server answered 500 to a scanner, told it something was there, and kept no
        record of having been asked.

        **Every live entry is compared, and the answer is not returned early.** How long this
        takes must not say which link matched, or whether one did at all.

        **A revoked link is a wrong path and nothing more.** It is not on the live list, so it
        falls to the same refusal an invented path gets — somebody who could tell the two apart
        would have learnt that the address was once real.
        """
        from epicrisis import connectors
        from epicrisis.state import Unreadable

        if not asked_for.isascii() or not asked_for.startswith("/mcp/"):
            return None
        offered = asked_for[len("/mcp/") :]
        try:
            issued = connectors.load(self.data_dir)
        except Unreadable:
            # A registry that will not read is every link refused, which is the safe direction for
            # this file to fail in: the archives are shut rather than open. The refusal below says
            # nothing about why, because a stranger is not owed that either.
            return None
        found = None
        for one in issued:
            if not one.live or len(one.path) < MIN_SECRET:
                continue
            if hmac.compare_digest(offered, one.path):
                found = one.id
        return found

    def _sweep(self, address: str) -> int | None:
        """How many refusals to report now, or None while the last line is still fresh."""
        now = time.monotonic()
        seen = self.sweeps.get(address)
        if seen is None or now - seen[0] >= mcp_access.QUIET_SECONDS:
            self.sweeps[address] = [now, 0]
            return 0 if seen is None else seen[1]
        seen[1] += 1
        return None

    @staticmethod
    async def _refuse(send, status: int = 403, body: bytes = b"Not from here.\n") -> None:
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")]})  # fmt: skip
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _called(body: bytes) -> dict:
        """The name of the call, the tool, and the one argument that is safe to write down.

        **One argument and never the others.** The rule above this class is that the arguments are
        not read, because a log of this archive holding the questions would be a second copy of
        it: a search term is a line off somebody's form, or the name of their disease. `archive`
        is not that. It is four random bytes — that is why an archive's id is random, and why
        folder names are not used for it — and without it this log says that a link read something
        and not whose.
        """
        try:
            asked = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
        if not isinstance(asked, dict):
            return {}
        call = asked.get("method")
        params = asked.get("params") if isinstance(asked.get("params"), dict) else {}
        name = params.get("name")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        # As asked for, which is not always as served: a signature out of reach is refused inside
        # the tool and this line is already written by then. That is the honest thing to record —
        # what was asked — and `allowed` above it is about the address and the path, not about
        # this. Written only when it is a string of the shape an id has, so that a caller cannot
        # put a sentence of somebody's document into this file by naming it `archive`.
        about = arguments.get("archive")
        safe = isinstance(about, str) and 0 < len(about) <= 32 and about.isalnum() and about.isascii()
        return {"call": call, "tool": name, **({"about": about} if safe else {})} if call else {}


#: Where the MCP application itself is mounted, behind the dispatcher. One path, decided when the
#: server is built, because `streamable_http_app` takes exactly one and bakes it in — and a
#: sub-application per connector would mean restarting the server to hand somebody a link.
#:
#: Nothing outside can reach it. A request asking for this path literally matches no entry of the
#: registry, so it is refused like any other wrong path; the only way through is the dispatcher,
#: which rewrites the path itself after a secret has matched.
SERVED_AT = "/mcp/served"
#: Which link the request being answered came through, or None where there is no link at all —
#: over stdio, which is the owner at their own machine.
#:
#: A context variable and not an argument, because the tools are built as closures before any
#: request exists and the MCP library hands them no request. Set by the dispatcher immediately
#: before the application is awaited, so it belongs to that request's own task: with
#: `stateless_http=True` every request is its own task, and two connectors asking at once cannot
#: see each other's. Reset after, so a task reused for something else reads None rather than
#: whoever was here before.
THE_LINK_ANSWERING: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "the link answering", default=None)  # fmt: skip


def http_app(data_dir: Path, public_host: str | None = None, allow_from: str = ANTHROPIC_OUTBOUND):
    """The MCP server as a web application, served at the path of every live connector.

    One application behind one dispatcher, rather than the one secret this used to be built with.
    The secret is no longer a thing the server is started with at all: it is whatever the registry
    holds, which is why a link issued on the settings page works without the server being
    restarted, and why revoking one stops working the same way.
    """
    names = [*LOCAL_HOSTS, *([public_host] if public_host else [])]
    hosts = [name for host in names for name in (host, f"{host}:*")]
    served = build_server(data_dir, over_the_network=True).streamable_http_app(
        streamable_http_path=SERVED_AT,
        stateless_http=True,  # every request stands on its own: no session to keep across a proxy
        transport_security=TransportSecuritySettings(
            allowed_hosts=hosts,
            allowed_origins=[f"https://{host}" for host in hosts] + [f"http://{host}" for host in hosts if host.startswith(LOCAL_HOSTS)],
        ),
    )
    return RecordAccess(served, data_dir, allow_from)


def run(data_dir: Path, pinned_to: str | None = None) -> None:
    build_server(data_dir, pinned_to=pinned_to).run(transport="stdio")


def run_http(data_dir: Path, host: str = "127.0.0.1", port: int = 8051, public_host: str | None = None,
             allow_from: str = ANTHROPIC_OUTBOUND) -> None:  # fmt: skip
    import uvicorn

    # No access log: the path carries the secret, and a log is a place a secret should never reach.
    uvicorn.run(http_app(data_dir, public_host, allow_from), host=host, port=port, log_level="warning", access_log=False)
