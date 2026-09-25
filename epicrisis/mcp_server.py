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
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

from epicrisis import mcp_access, mcp_lock, query

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


def build_server(data_dir: Path, over_the_network: bool = False) -> MCPServer:
    """The tools of one archive. The lock is asked for only where this server is reachable.

    The code exists because `--http` puts the archive on an address the internet can reach. Over
    stdio there is no address: the process is started by whoever already has the files — the Ask
    page of this person's own dashboard, or a terminal on this machine — and asking them for the
    six digits guards nothing, while the settings page promises in as many words that tools used
    on this machine are not affected.
    """

    from epicrisis.sources import showing as showing_archive

    opened = showing_archive(data_dir)
    head = INSTRUCTIONS_HEAD.format(whose=opened.whose if opened else "someone whose name is not set")
    server = MCPServer(name="epicrisis", instructions=f"{head}\n\n{INSTRUCTIONS}", version="0.2")
    lock = mcp_lock.Lock(secret=mcp_lock.read_secret())

    def guard(ticket: str | None) -> dict[str, Any] | None:
        """Every tool asks this first. With the lock off it returns nothing and nothing changes.

        Locked, it gives back a notice rather than an error. An error is drawn as a failure and
        read as one; a notice is read as what it is — a step to take before the question can be
        answered. The field names are loud on purpose: an answer of no data must never be mistaken
        for an answer of no results.
        """
        from epicrisis.settings import mcp_lock_on, mcp_lock_scope

        try:
            # The archive that is open right now, so that a pass given for another one closes
            # the moment the dashboard is switched to somebody else.
            lock.require(ticket, enabled=over_the_network and mcp_lock_on(data_dir),
                         scope=mcp_lock_scope(data_dir), archive=showing()[0] or "")  # fmt: skip
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
            opened = lock.unlock(code, minutes=mcp_lock_minutes(data_dir), scope=scope,
                                 archive=showing()[0] or "")  # fmt: skip
            return {**opened, "opens": scope, "archive_of": whose(),
                    "until_the_archive_is_switched": "This pass opens the archive of "
                    f"{whose()}. If the person switches this server to another archive, the pass "
                    "closes and a new code is needed."}  # fmt: skip
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
            notice = guard(ticket)
            if notice is not None:
                return notice
        return lock.lock(ticket, everywhere=everywhere)

    def whose() -> str:
        """Whose archive is open. It rides on every answer: this server holds more than one."""
        return showing()[1]

    def showing() -> tuple[str | None, str]:
        """The archive being served and whose it is. Every answer says the name, so that one
        person's records can never be read as another's."""
        from epicrisis.sources import showing as the_archive

        active = the_archive(data_dir)
        return (active.id, active.whose) if active else (None, "")

    @contextmanager
    def index():
        """The index of the archive being served, for the length of one tool call.

        A tool that cannot open the index says so in words. It used to raise whatever SQLite
        raised, which reached the person as "Error executing tool search_documents" and nothing
        else — so a server whose files had been made unreadable looked exactly like a server that
        had been asked something it could not answer. The reason is here; the journal has the rest.
        """
        # Tools run in worker threads and an SQLite connection belongs to one thread.
        try:
            connection = query.open_index(data_dir, showing()[0])
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

    @server.tool(description="What the archive holds: counts of documents and values, the span of dates, types and languages.")
    def archive_overview(ticket: TICKET = None) -> dict[str, Any]:
        notice = guard(ticket)
        if notice is not None:
            return notice
        with index() as connection:
            return {"archive_of": whose(), **query.overview(connection)}

    @server.tool(description="Documents whose text, title, institution or value names match the words. Returns a piece of the original text around the match.")
    def search_documents(
        query_text: Annotated[str, Field(description="Words to look for, in any of the archive's languages")],
        limit: Annotated[int, Field(description="How many documents", ge=1, le=200)] = 20,
        since: Annotated[str | None, Field(description="Earliest document date, YYYY-MM-DD")] = None,
        until: Annotated[str | None, Field(description="Latest document date, YYYY-MM-DD")] = None,
        doc_type: Annotated[str | None, Field(description="lab_panel, imaging_report, consultation, discharge, prescription, referral, admin, insurance, other")] = None,
        ticket: TICKET = None,
    ) -> dict[str, Any]:
        notice = guard(ticket)
        if notice is not None:
            return notice
        with index() as connection:
            rows = query.search(connection, query_text, limit=limit, since=since, until=until, doc_type=doc_type)
            if not rows:
                return {"archive_of": whose(), **_found_nothing(connection, query_text)}
            return {"archive_of": whose(), "result": rows, "found": len(rows)}

    @server.tool(description="Documents by their own printed date, newest first. Returns a page and says how many there are in all.")
    def list_documents(
        since: Annotated[str | None, Field(description="Earliest document date, YYYY-MM-DD")] = None,
        until: Annotated[str | None, Field(description="Latest document date, YYYY-MM-DD")] = None,
        doc_type: Annotated[str | None, Field(description="Document type to keep")] = None,
        limit: Annotated[int, Field(description="How many documents in this page", ge=1, le=200)] = 25,
        offset: Annotated[int, Field(description="Skip this many, to read the next page", ge=0)] = 0,
        ticket: TICKET = None
    ) -> dict[str, Any]:
        notice = guard(ticket)
        if notice is not None:
            return notice
        with index() as connection:
            rows = query.timeline(connection, since=since, until=until, doc_type=doc_type, limit=limit, offset=offset)
            total = query.count_documents(connection, since=since, until=until, doc_type=doc_type)
            return {"archive_of": whose(), **_page(rows, "documents", total, offset)}

    @server.tool(description="How a test is printed across the archive: every printed name matching the words, with how often it appears and over which years.")
    def value_names(
        query_text: Annotated[str | None, Field(description="Part of a name, in any language")] = None,
        limit: Annotated[int, Field(description="How many names", ge=1, le=200)] = 50,
        include_derived: Annotated[bool, Field(description="Include values the lab calculated, such as filtration rates")] = False,
        ticket: TICKET = None
    ) -> dict[str, Any]:
        notice = guard(ticket)
        if notice is not None:
            return notice
        with index() as connection:
            rows = query.value_names(connection, query_text, limit=limit, include_derived=include_derived)
            indicators = query.indicators_matching(connection, query_text)
            if not rows and not indicators:
                return {"archive_of": whose(), **_found_nothing(connection, query_text)}
            answer: dict[str, Any] = {"archive_of": whose(), "result": rows, "found": len(rows)}
            if indicators:
                # The names printed in other languages sit under the same indicator as these ones.
                answer["indicators_holding_these_words"] = [
                    {"id": item["id"], "label": item["label"], "spellings": item["names"]} for item in indicators
                ]
            return answer

    @server.tool(description="Indicators: one label over the many ways a test is printed across laboratories and languages. Use an indicator id with value_history to get a whole history at once. Returns a page; ask for the next with offset.")
    def list_indicators(
        status: Annotated[str | None, Field(description="approved, proposed, or null for all")] = "approved",
        limit: Annotated[int, Field(description="How many indicators in this page", ge=1, le=200)] = 50,
        offset: Annotated[int, Field(description="Skip this many, to read the next page", ge=0)] = 0,
        with_spellings: Annotated[bool, Field(description="Include every printed spelling of each indicator. Off by default: the whole list with spellings does not fit in one answer.")] = False,
        ticket: TICKET = None
    ) -> dict[str, Any]:
        notice = guard(ticket)
        if notice is not None:
            return notice
        with index() as connection:
            rows = query.indicator_list(connection, status=status, brief=not with_spellings, limit=limit, offset=offset)
            return {"archive_of": whose(), **_page(rows, "indicators", query.count_indicators(connection, status=status), offset)}

    @server.tool(description="Every value of one indicator, or whose printed name contains the words, as printed, oldest first, with unit, reference range, flag and the document it comes from.")
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
        notice = guard(ticket)
        if notice is not None:
            return notice
        with index() as connection:
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
                return {"archive_of": whose(), **_found_nothing(connection, name)}
            return {"archive_of": whose(), "result": rows, "found": len(rows), **searched}

    @server.tool(description="Values a laboratory itself marked on the form (H, L, an asterisk, an arrow), over a period. The archive never adds a mark of its own. Where the instance allows it, compare_with_printed_range instead compares each value with the range printed beside it on that same form, and says how many could not be compared at all.")
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
        notice = guard(ticket)
        if notice is not None:
            return notice
        from epicrisis.settings import answer_mode

        # Only the last mode, where the person has taken every limit off their own instance, lets
        # the application itself compare a value with a range. In the middle mode the model may
        # compare — it has the reference beside every value — but the application does not.
        if compare_with_printed_range and answer_mode(data_dir) != "direct":
            return {
                "archive_of": whose(),
                "refused": "This instance shows values as printed and does not compare them with their ranges itself.",
                "how_to_allow": "The person whose archive this is can take every limit off on the Settings page.",
                "instead": "Ask without compare_with_printed_range for the marks the laboratories themselves printed, or read the reference printed beside each value and compare it yourself.",
            }
        with index() as connection:
            rows, counts = query.flagged_values(
                connection, since=since, until=until, flag=flag, indicator=indicator,
                include_derived=include_derived, compare_with_printed_range=compare_with_printed_range,
                limit=limit, offset=offset,
            )  # fmt: skip
            answer = {"archive_of": whose(), **_page(rows, "values", None, offset)}
            answer["compared_with_printed_range"] = bool(compare_with_printed_range)
            if compare_with_printed_range:
                # The two sides are not symmetric, and saying so is part of the answer: a value
                # outside a printed range is a fact about that laboratory's range, while a value
                # inside it says little, and a range that could not be read says nothing at all.
                answer["counted"] = counts
                answer["what_this_is"] = (
                    "Each number was compared with the range printed beside it on its own form."
                    f" {counts['outside']} fell outside, {counts['inside']} did not, and {counts['range_not_read']}"
                    " could not be compared because their printed range cannot be read plainly."
                    " A laboratory's range is for a general population and may not fit this person;"
                    " inside it is not the same as fine, and this is never a count of everything."
                )
            return answer

    @server.tool(description="One document: header and counts of every part, then the parts asked for, a page at a time. A long document does not fit in one answer, so 'counts' says what the document holds and 'more' says what is left; ask again with offset, or with parts=['sections','text'] for the words rather than the table.")
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
        notice = guard(ticket)
        if notice is not None:
            return notice
        chosen = tuple(parts) if parts else tuple(part for part in query.PARTS if part != "text" or with_text)
        with index() as connection:
            found = query.document(
                connection, document_id=document_id, file_id=file_id, first_page=first_page,
                with_text=with_text or bool(parts and "text" in parts), parts=chosen,
                offset=offset, limit=limit, text_offset=text_offset,
            )  # fmt: skip
            return {"archive_of": whose(), **found} if found else None

    @server.tool(description="Documents the validation flagged for a person to check: incomplete transcriptions, dates, copies, parts that could not be read.")
    def documents_to_check(
        code: Annotated[str | None, Field(description="One check code, for instance date_to_check or transcription_incomplete")] = None,
        limit: Annotated[int, Field(description="How many documents", ge=1, le=200)] = 50,
        ticket: TICKET = None,
    ) -> dict[str, Any]:
        notice = guard(ticket)
        if notice is not None:
            return notice
        with index() as connection:
            rows = query.to_check(connection, code=code, limit=limit)
            return {"archive_of": whose(), "result": rows, "found": len(rows)}

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
    address at the end of X-Forwarded-For and marks the request as its own. The header is trusted
    only on a request the tunnel marked, and only its last entry: anyone may send the header, but
    only the tunnel may add to it, and what it adds is the address it saw.
    """
    through_tunnel = bool(headers.get("tailscale-funnel-request"))
    forwarded = [part.strip() for part in (headers.get("x-forwarded-for") or "").split(",") if part.strip()]
    if through_tunnel and forwarded:
        return forwarded[-1], True
    return peer, through_tunnel


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
        # The path holds the secret, so it is compared the way a secret is compared.
        allowed = welcome and hmac.compare_digest(scope.get("path") or "", self.allowed_path)
        facts = mcp_access.request_facts(scope, allowed, None if allowed else ("address" if not welcome else "path"))
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


def run(data_dir: Path) -> None:
    build_server(data_dir).run(transport="stdio")


def run_http(data_dir: Path, secret: str, host: str = "127.0.0.1", port: int = 8051, public_host: str | None = None,
             allow_from: str = ANTHROPIC_OUTBOUND) -> None:  # fmt: skip
    import uvicorn

    # No access log: the path carries the secret, and a log is a place a secret should never reach.
    uvicorn.run(http_app(data_dir, secret, public_host, allow_from), host=host, port=port, log_level="warning", access_log=False)
