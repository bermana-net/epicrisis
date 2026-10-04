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
from epicrisis.rules import kinds

# Whose archive this is comes first, before anything about how to read it: a person reading a
# conversation should be able to see at a glance whose records were being talked about. The name
# here is the archive that was open when this session began, and the archive can be changed on
# the dashboard while the session runs — so the head says as much, and points at the field that
# is always right: archive_of, on every answer.
INSTRUCTIONS_HEAD = (
    "You are reading the medical archive of {whose}, through Epicrisis Companion. That is the "
    "archive that was open when this session began. This server may hold several, one open at a "
    "time, and it can be changed while you are connected: every answer says which archive it "
    "actually came from, in `archive_of`, and that field is the one to trust and to quote."
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

This archive may be locked. When a tool answers that it is, that is not a failure and not a reason to stop or to answer from memory: the person you are talking to holds a six-digit code in their authenticator. Ask them for it, call unlock with it, and pass the string it returns as `ticket` on every call after that; it stays good for four hours. When the conversation is over, call lock_archive, because the pass stays written in the conversation."""


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

    from epicrisis.sources import showing as showing_archive

    opened = showing_archive(data_dir)
    # Whose archive it is, only where saying so gives nothing away. These instructions are handed
    # over in the answer to `initialize`, which is the first thing a client asks and which needs no
    # code at all — so on a locked server this sentence told whoever held the address the one fact
    # the lock exists to keep, and the docstring of guard() a few lines down says exactly that
    # about its own refusals. Over stdio the lock does not apply and the process is started by
    # somebody who already has the files; with the lock off nothing is being kept from anybody.
    from epicrisis.settings import mcp_lock_on

    kept_back = over_the_network and mcp_lock_on(data_dir)
    head = INSTRUCTIONS_HEAD.format(
        whose="the person whose archive this instance holds" if kept_back
        else (opened.whose if opened else "someone whose name is not set")
    )  # fmt: skip
    # The version this program is, not a second version written down beside it: a string here
    # would go on telling a connector 0.2 for as long as nobody remembered it existed.
    from epicrisis import __version__

    server = MCPServer(name="epicrisis", instructions=f"{head}\n\n{INSTRUCTIONS}", version=__version__)
    lock = mcp_lock.Lock(secret=mcp_lock.read_secret(),
                         remembers=Path(data_dir) / mcp_lock.WRONG_CODES_FILE)  # fmt: skip

    def answering(ticket: str | None) -> tuple[dict[str, Any] | None, TheArchiveServed]:
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
        """
        archive = showing()
        return guard(ticket, archive), archive

    def guard(ticket: str | None, archive: TheArchiveServed) -> dict[str, Any] | None:
        """Whether this call may be answered at all. With the lock off it returns nothing.

        Locked, it gives back a notice rather than an error. An error is drawn as a failure and
        read as one; a notice is read as what it is — a step to take before the question can be
        answered. The field names are loud on purpose: an answer of no data must never be mistaken
        for an answer of no results.
        """
        from epicrisis.settings import mcp_lock_on, mcp_lock_scope

        try:
            # The archive this call is being answered out of, so that a pass given for another
            # one closes the moment the dashboard is switched to somebody else — and so that the
            # pass is checked against the archive the answer will actually come from.
            lock.require(ticket, enabled=over_the_network and mcp_lock_on(data_dir),
                         scope=mcp_lock_scope(data_dir), archive=archive.id or "")  # fmt: skip
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
            # One reading: the archive the pass is written over is the archive the answer names.
            archive = showing()
            opened = lock.unlock(code, minutes=mcp_lock_minutes(data_dir), scope=scope,
                                 archive=archive.id or "")  # fmt: skip
            return {**opened, "opens": scope, "archive_of": archive.whose,
                    "until_the_archive_is_switched": "This pass opens the archive of "
                    f"{archive.whose}. If the person switches this server to another archive, the "
                    "pass closes and a new code is needed."}  # fmt: skip
        except mcp_lock.Locked as refusal:
            raise ToolError(str(refusal)) from refusal

    @server.tool(description="Close this archive now instead of waiting for the pass to run out. Worth doing when a conversation ends: the pass stays written in it.")
    def lock_archive(
        ticket: TICKET = None,
        everywhere: Annotated[bool, Field(description="Close every pass that is open, not only this one")] = False,
    ) -> dict[str, Any]:
        if everywhere:
            # Shutting everyone out is something only someone already let in may do; otherwise a
            # stranger who reached this address could keep the archive closed to its owner.
            notice, _archive = answering(ticket)
            if notice is not None:
                return notice
        return lock.lock(ticket, everywhere=everywhere)

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

    @server.tool(description="What the archive holds: counts of documents and values, the span of dates, types and languages. Counts only: nothing here says whether anything in it is normal.")
    def archive_overview(ticket: TICKET = None) -> dict[str, Any]:
        notice, archive = answering(ticket)
        if notice is not None:
            return notice
        with index(archive) as connection:
            return {"archive_of": archive.whose, **query.overview(connection)}

    @server.tool(description="Documents whose text, title, institution or value names match the words. Returns a piece of the original text around the match, as printed. Matching is literal: it does not rank documents by importance and an empty answer is not evidence the archive lacks the subject.")
    def search_documents(
        query_text: Annotated[str, Field(description="Words to look for, in any of the archive's languages")],
        limit: Annotated[int, Field(description="How many documents", ge=1, le=200)] = 20,
        since: Annotated[str | None, Field(description="Earliest document date, YYYY-MM-DD")] = None,
        until: Annotated[str | None, Field(description="Latest document date, YYYY-MM-DD")] = None,
        doc_type: Annotated[str | None, Field(description="lab_panel, imaging_report, consultation, discharge, prescription, referral, admin, insurance, other")] = None,
        offset: Annotated[int, Field(description="Skip this many, to read the next page", ge=0)] = 0,
        ticket: TICKET = None,
    ) -> dict[str, Any]:
        notice, archive = answering(ticket)
        if notice is not None:
            return notice
        with index(archive) as connection:
            rows = query.search(connection, query_text, limit=limit, since=since, until=until,
                                doc_type=doc_type, offset=offset)  # fmt: skip
            if not rows and not offset:
                return {"archive_of": archive.whose, **_found_nothing(connection, query_text)}
            # Through _page, whose own words are "nothing is cut without the caller being told" —
            # which this tool did not do. "found" was the length of the page: twenty-two matches
            # answered as twenty, in an answer shaped exactly like the answer to "that is all there
            # is", and a model then wrote about the archive from part of it. The count was already
            # in this file's reach, and the page of the dashboard has been showing it all along.
            total = query.count_search(connection, query_text, since=since, until=until, doc_type=doc_type)
            return {"archive_of": archive.whose, **_page(rows, "documents", total, offset)}

    @server.tool(description="Documents by their own printed date, newest first. Returns a page and says how many there are in all. The dates are the ones printed on the documents; nothing here groups them into episodes or decides which of them matter.")
    def list_documents(
        since: Annotated[str | None, Field(description="Earliest document date, YYYY-MM-DD")] = None,
        until: Annotated[str | None, Field(description="Latest document date, YYYY-MM-DD")] = None,
        doc_type: Annotated[str | None, Field(description="Document type to keep")] = None,
        limit: Annotated[int, Field(description="How many documents in this page", ge=1, le=200)] = 25,
        offset: Annotated[int, Field(description="Skip this many, to read the next page", ge=0)] = 0,
        ticket: TICKET = None
    ) -> dict[str, Any]:
        notice, archive = answering(ticket)
        if notice is not None:
            return notice
        with index(archive) as connection:
            rows = query.timeline(connection, since=since, until=until, doc_type=doc_type, limit=limit, offset=offset)
            total = query.count_documents(connection, since=since, until=until, doc_type=doc_type)
            return {"archive_of": archive.whose, **_page(rows, "documents", total, offset)}

    @server.tool(description="How a test is printed across the archive: every printed name matching the words, with how often it appears and over which years. Spellings, not meanings: it does not say that two printed names are the same test unless a person has said so.")
    def value_names(
        query_text: Annotated[str | None, Field(description="Part of a name, in any language")] = None,
        limit: Annotated[int, Field(description="How many names", ge=1, le=200)] = 50,
        include_derived: Annotated[bool, Field(description="Include values the lab calculated, such as filtration rates")] = False,
        offset: Annotated[int, Field(description="Skip this many, to read the next page", ge=0)] = 0,
        ticket: TICKET = None
    ) -> dict[str, Any]:
        notice, archive = answering(ticket)
        if notice is not None:
            return notice
        with index(archive) as connection:
            rows = query.value_names(connection, query_text, limit=limit,
                                     include_derived=include_derived, offset=offset)  # fmt: skip
            indicators = query.indicators_matching(connection, query_text)
            if not rows and not indicators and not offset:
                return {"archive_of": archive.whose, **_found_nothing(connection, query_text)}
            total = query.count_value_names(connection, query_text, include_derived=include_derived)
            answer: dict[str, Any] = {"archive_of": archive.whose, **_page(rows, "printed_names", total, offset)}
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
        ticket: TICKET = None
    ) -> dict[str, Any]:
        notice, archive = answering(ticket)
        if notice is not None:
            return notice
        with index(archive) as connection:
            rows = query.indicator_list(connection, status=status, brief=not with_spellings, limit=limit, offset=offset)
            return {"archive_of": archive.whose, **_page(rows, "indicators", query.count_indicators(connection, status=status), offset)}

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
        ticket: TICKET = None
    ) -> dict[str, Any]:
        notice, archive = answering(ticket)
        if notice is not None:
            return notice
        with index(archive) as connection:
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
                return {"archive_of": archive.whose, **_found_nothing(connection, name)}
            # How many there are under the same question, not how many fitted. The rows come back
            # oldest first and the cap takes them from the top, so a test with more values than
            # the cap answered with its oldest and said nothing about the rest — and a history
            # that stops years ago reads like a history that stops years ago, not like a page of
            # one. Counted with the same period as the list, or the note would fire on a question
            # that was narrowed on purpose and tell the model to narrow it again.
            answer = {"archive_of": archive.whose, "result": rows, "found": len(rows), **searched}
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
        ticket: TICKET = None
    ) -> dict[str, Any]:
        notice, archive = answering(ticket)
        if notice is not None:
            return notice
        from epicrisis.settings import answer_mode, rules_on

        # Only the last mode, where the person has taken every limit off their own instance, lets
        # the application itself compare a value with a range. In the middle mode the model may
        # compare — it has the reference beside every value — but the application does not.
        if compare_with_printed_range and answer_mode(data_dir) != "direct":
            return {
                "archive_of": archive.whose,
                # Not "you may have this if you take every limit off". That sentence sent people
                # to switch off the last of their own limits for something they did not need it
                # for: the range is printed beside every value in the answer, and reading it is
                # reading the form. What is refused here is the application doing the arithmetic
                # and calling the result a finding.
                "refused": "This instance shows values as printed and does not compare them with their ranges itself. This is about what the application will compute, not about what may be said.",
                "instead": "Ask without compare_with_printed_range: every value comes back with the range printed beside it on its own form, and you can compare them yourself. Or ask for the marks the laboratories themselves printed.",
                "how_to_allow": "Only an instance with every limit taken off on the Settings page has the application compare them. That setting is about more than this, and it is not needed to read a printed range.",
            }
        with index(archive) as connection:
            rows, counts, how_many = query.flagged_values(
                connection, since=since, until=until, flag=flag, indicator=indicator,
                include_derived=include_derived, compare_with_printed_range=compare_with_printed_range,
                limit=limit, offset=offset,
                # The same rules the charts are drawn with: a list that judged a value against a
                # range printed at another scale would report the scale as an excursion.
                placing=rules_on(data_dir, rules.load(data_dir), kinds.CHARTS),
            )  # fmt: skip
            # With the count, so that a page says whether it is the whole of it. Without one, _page
            # offers a next_offset on any page that has rows at all, and six values returned out of
            # six read as six out of many: the three tools that cut in silence were given their
            # counts a release ago and this was the fourth, cutting nothing and saying so anyway.
            answer = {"archive_of": archive.whose, **_page(rows, "values", how_many, offset)}
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
        ticket: TICKET = None
    ) -> dict[str, Any] | None:
        notice, archive = answering(ticket)
        if notice is not None:
            return notice
        chosen = tuple(parts) if parts else tuple(part for part in query.PARTS if part != "text" or with_text)
        with index(archive) as connection:
            found = query.document(
                connection, document_id=document_id, file_id=file_id, first_page=first_page,
                with_text=with_text or bool(parts and "text" in parts), parts=chosen,
                offset=offset, limit=limit, text_offset=text_offset,
            )  # fmt: skip
            if not found:
                return None
            answer = {"archive_of": archive.whose, **found}
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
    ) -> dict[str, Any]:
        notice, archive = answering(ticket)
        if notice is not None:
            return notice
        with index(archive) as connection:
            rows = query.to_check(connection, code=code, limit=limit, offset=offset)
            total = query.count_to_check(connection, code=code)
            return {"archive_of": archive.whose, **_page(rows, "documents_to_check", total, offset)}

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

    def __init__(self, app, data_dir: Path, allowed_path: str, allow_from: str = ANTHROPIC_OUTBOUND):
        self.app, self.data_dir, self.allowed_path = app, data_dir, allowed_path
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
        allowed = welcome and asked_for.isascii() and hmac.compare_digest(asked_for, self.allowed_path)
        facts = {**mcp_access.request_facts(scope, allowed, None if allowed else ("address" if not welcome else "path")),
                 **how_it_arrived(headers, (scope.get("client") or ("", 0))[0])}  # fmt: skip
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
        return await self.app(scope, again, send)

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
        try:
            asked = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
        if not isinstance(asked, dict):
            return {}
        call = asked.get("method")
        name = (asked.get("params") or {}).get("name") if isinstance(asked.get("params"), dict) else None
        return {"call": call, "tool": name} if call else {}


def http_app(data_dir: Path, secret: str, public_host: str | None = None, allow_from: str = ANTHROPIC_OUTBOUND):
    """The MCP server as a web application, served at one path only: /mcp/<secret>."""
    if len(secret) < MIN_SECRET:
        raise ValueError(f"a secret shorter than {MIN_SECRET} characters is not a secret")
    names = [*LOCAL_HOSTS, *([public_host] if public_host else [])]
    hosts = [name for host in names for name in (host, f"{host}:*")]
    served = build_server(data_dir, over_the_network=True).streamable_http_app(
        streamable_http_path=f"/mcp/{secret}",
        stateless_http=True,  # every request stands on its own: no session to keep across a proxy
        transport_security=TransportSecuritySettings(
            allowed_hosts=hosts,
            allowed_origins=[f"https://{host}" for host in hosts] + [f"http://{host}" for host in hosts if host.startswith(LOCAL_HOSTS)],
        ),
    )
    return RecordAccess(served, data_dir, f"/mcp/{secret}", allow_from)


def run(data_dir: Path, pinned_to: str | None = None) -> None:
    build_server(data_dir, pinned_to=pinned_to).run(transport="stdio")


def run_http(data_dir: Path, secret: str, host: str = "127.0.0.1", port: int = 8051, public_host: str | None = None,
             allow_from: str = ANTHROPIC_OUTBOUND) -> None:  # fmt: skip
    import uvicorn

    # No access log: the path carries the secret, and a log is a place a secret should never reach.
    uvicorn.run(http_app(data_dir, secret, public_host, allow_from), host=host, port=port, log_level="warning", access_log=False)
