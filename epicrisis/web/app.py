"""Status dashboard: which folders are registered and how far each got through the pipeline.

It shows counts and paths only, never document contents or values.
"""

import json
from collections.abc import Iterator
from contextlib import closing, suppress
from contextvars import ContextVar
from functools import partial
from itertools import count
import os
import secrets
import shutil
import time
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlencode, urlsplit

from fastapi import Depends, FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from epicrisis import doc_types, invocation, layout
from epicrisis.classify.backend import backend_installed
from epicrisis.classify.pages import PageUnreadable, original_png, page_refs
from epicrisis.classify.report import latest_pages
from epicrisis.classify.run import all_refs, is_running
from epicrisis.extract.run import LOCK_NAME as EXTRACT_LOCK
from epicrisis.extract.run import document_refs, done_keys
from epicrisis.consent import has_consent, not_covered as consent_not_covered, record_consent, withdraw_consent
from epicrisis.corrections import CORRECTABLE, line_key, set_document_date, set_primary_copy, set_value
from epicrisis import judgements
from epicrisis.index.build import FILE_NAME as THE_INDEX
from epicrisis.index.build import index_path, index_state
from epicrisis import journal
from epicrisis import mcp_access
from epicrisis.mcp_lock import read_secret as read_lock_secret
from epicrisis import engines
from epicrisis import people
from epicrisis import query as query_index
from epicrisis import rules
from epicrisis.rules import kinds
from epicrisis import series
from epicrisis.query import IndexMissing, open_index
from epicrisis.state import NoSpace, Unreadable, no_space
from epicrisis.inventory.report import Summary
from epicrisis.records import read_records, torn_lines
from epicrisis.runs import Busy
from epicrisis.sources import (NO_ARCHIVES, Source, SourceError, SourceRegistry, TheArchives,
                               folder_is_there, source_output_dir)  # fmt: skip
from epicrisis.web.browse import BrowseError, list_folder
from epicrisis.web.markdown import render_markdown
from epicrisis.ask import ask, carried_questions, delete_chat, list_chats, load_chat, new_chat
from epicrisis.ask import running as chat_running
from epicrisis.settings import unreadable as settings_unreadable
from epicrisis.settings import answer_mode, ask_enabled, mcp_lock_on, rules_on
from epicrisis.update import start_in_background as start_update
from epicrisis.update import update_running
from epicrisis.validate import validate_source, validation_state
from epicrisis.web.building import Building
from epicrisis.web.documents import (document_card, how_many_documents_to_check, nothing_read_yet,
                                     one_scanned_page, reading_colour, review_view, said_in,
                                     source_documents, the_scan_at)  # fmt: skip
# The row of material tabs lives beside the page that first drew it — the By test view of the
# timeline — and the page of one test draws the same row, so it is imported rather than written
# twice. MATERIALS_TO_CHOOSE below is a different list and a different question: what somebody
# may set by hand, not what there is anything to show for.
from epicrisis.web.timeline import material_tabs, timeline_view
# SETTINGS_TABS comes in with them because the sweep in test_the_wall_between_people.py reads it
# off this module to know which tabs of that page it has to ask for.
from epicrisis.web.settings_page import SETTINGS_TABS, settings_pressed, settings_view
# Imported whole rather than by name: the four presses are called `joined`, `declined`,
# `reconsidered` and `separated`, and those are words about doctors and clinics only where the
# page they belong to is written beside them.
from epicrisis.web import who
from epicrisis.web.indicators_page import indicators_pressed, indicators_view
from epicrisis.web.looks_misread import how_many_look_misread, what_looks_misread
# Imported whole, as web/who.py is: `added`, `shown_instead` and `taken_off_the_list` are words
# about the list of archives only where the module they stand in says so.
from epicrisis.web import the_list_of_archives as the_list
from epicrisis.web.jobs import CAN_BE_SAID, InventoryJobs
from epicrisis.invocation import CLI

PIPELINE_STEPS = ["Inventory", "Classify", "Extract", "Validate", "Index"]
# The earliest year a person may give a document by hand. Before this it is a typing slip rather
# than a record, and the field on the card says so as they type as well as the server after.
EARLIEST_YEAR = 1900
# A date written out, shown on the page when what somebody typed cannot be read as one. The day
# that stood here is printed on a Ukrainian laboratory form in the archive this was built for, as
# the hour a sample was taken — and it has gone out with every release since the first. A bare day
# with nothing beside it names nobody, so nothing was undone by it; it was simply a real day where
# an invented one would do. This one is on no form in any archive here, and tests/conftest.py says
# how that was checked and keeps the same day for the illustrations in the tests.
A_DATE_WRITTEN_OUT = "2011-07-09"
LOCAL_HOSTS = ["localhost", "127.0.0.1"]

# Where the page about a file that will not read sends a person on, in the order the two help: the
# status page is where somebody goes when something is wrong, and the timeline is the archive
# itself. One of them is offered, and only one that answers.
WAYS_ON = (("/status", "Archive status"), ("/", "The timeline"))
# Which of those two is itself drawn out of which file of state, so that the button is never a
# button back to the page a person is already standing on. This is measured and not reasoned:
# test_trouble.py tears each of these files in a built archive and asks both pages, and it fails
# if a line here is wrong in either direction — a door named shut that answers, or a door offered
# that does not.
#
# A file named nowhere here is treated as shutting both, because the one thing this page may not
# do is promise a way out that is not there: better no button and the sentence that says so.
# Two of them torn at once is the limit of this table, and it is a limit worth writing down: a
# refusal carries one file, so the door may lead to a second page about the second file — which
# names that file and its own way out, rather than repeating the first.
SHUT_WHILE_TORN = {
    # Every page of this dashboard begins by asking which archives there are.
    layout.SOURCES: ("/status", "/"),
    # Both pages draw their switches and their badges at the defaults over a torn settings file,
    # and say so in a line of their own rather than refusing.
    layout.SETTINGS: (),
    # The vocabulary is read by the page that shows it and by the timeline's cut by test, and the
    # timeline answers without it on the cut it opens at.
    layout.INDICATORS: (),
    # The names a person joined are laid over the timeline's cuts by doctor and by institution.
    layout.PEOPLE: ("/",),
    # The findings of the checks: the status page counts them in a badge, the page of things to
    # check is made of them.
    layout.VALIDATION: ("/status",),
    # One document's transcription, which the status page reaches through the count of documents
    # still to transcribe.
    layout.EXTRACTED: ("/status",),
    # The index is what the timeline is drawn from; the status page says which step is broken
    # instead of refusing as a whole.
    THE_INDEX: ("/",),
    # One conversation of the page that asks a model questions. Nothing else reads the chats, so
    # both ways on answer — which is why it is here: a file named nowhere in this table is treated
    # as shutting both, and a torn conversation would have been met with no door at all.
    layout.CHATS: (),
}


#: The numbering of ids inside the page being drawn. Set at the start of every request, so that one
#: page is numbered from one however many threads draw pages beside it.
_numbering: ContextVar[Iterator[int]] = ContextVar("numbering")


def _an_id(prefix: str = "id") -> str:
    """An id unique inside this page, numbered from one. Registered as the template global `an_id`.

    A render outside a request — a template drawn straight from a test — gets a counter of its own
    rather than a refusal: nothing here is worth failing a page over.
    """
    numbering = _numbering.get(None)
    if numbering is None:
        numbering = count(1)
        _numbering.set(numbering)
    return f"{prefix}-{next(numbering)}"


def the_torn_file(named: str) -> str:
    """A refusal's file, named as the table above names it.

    A refusal carries the path a person can walk to — `sources/4f2a9c81/extracted/<sha>.json` —
    and what settles which pages are down is the *kind* of file it is: one archive's reading of
    one document, whatever its hash, and one archive's index, whose name carries the archive's
    id. So a reading is looked up by the folder it sits in and an index by both ends of its name,
    and everything that sits in the data directory as itself by that name.
    """
    parts = PurePosixPath(named).parts
    if layout.EXTRACTED in parts:
        return layout.EXTRACTED
    # One conversation, whatever its random id, the way one transcription is looked up by its
    # folder rather than by its hash.
    if layout.CHATS in parts:
        return layout.CHATS
    name = parts[-1] if parts else named
    # Asked of index_path rather than matched against a spelling written out here, so that the
    # shape of an index's name stays decided in the one module that decides it.
    one_archives = index_path(Path(), name.removeprefix("index-").removesuffix(Path(THE_INDEX).suffix)).name
    if name in (THE_INDEX, one_archives):
        return THE_INDEX
    return name


def a_way_on(broken: Unreadable) -> tuple[str, str] | None:
    """The first way on this torn file does not take down, or nothing where it takes both.

    The button used to be the status page for everything but sources.json, and the status page is
    drawn out of three of these files: a torn validation.json, a torn transcription of one
    document, answered 503 on the status page and offered a button to the status page. The one
    class of defect this page exists for, on the page that exists for it.
    """
    shut = SHUT_WHILE_TORN.get(the_torn_file(broken.file), tuple(where for where, _ in WAYS_ON))
    return next(((where, label) for where, label in WAYS_ON if where not in shut), None)


# The four tabs of the patient card. Personal data leads because it is the shortest and
# the steadiest of the four: a blood group does not change, and a person looking one up should not
# have to pass every medication the archive prints to reach it. The settings page's own four are
# in web/settings_page.py, beside what they draw.
CARD_TABS = ("person", "medications", "diagnoses", "conflicts")

# What a person may set by hand on one line, where the form's layout leaves it ambiguous: a
# table with rows of two specimens, a panel headed for one thing and holding a section of
# another. "none" is here too, for a measurement made on the person rather than in a sample.
MATERIALS_TO_CHOOSE = ("blood", "urine", "stool", "semen", "swab", "csf", "saliva", "sputum", "none")


def _the_open_archive(archives: TheArchives, source_id: str) -> Source | None:
    """The archive named in an address, but only while it is the one that is open.

    A document, its scan and the corrections on it are content, and every page that shows
    them carries one person's name at the top. Addressed from under another archive they
    answer as though they do not exist, which is the same rule the chats follow. The status
    page is the exception it makes itself: it lists every archive, and renaming, rescanning
    or taking one off the list are acts on the list rather than on anybody's records.

    Both halves are still here and both are still asked. The archive comes out of the
    address, which is what makes this a door and not a guess, and it is checked against the
    archive that is open — the one reading this request was decided by, handed in rather than
    fetched. What is *not* allowed is to take the archive from the request and write to it:
    switch the archive between the drawing of a page and a press on it and the press must be
    refused, with the reason said, which is what every caller of this does.

    It stands here, outside `create_app`, and not because anything in it needed to: it closed
    over nothing. It is here so that it can be handed to the presses that have moved beside
    their own page — `web/who.py` is given this very function — and so that a test can be
    given the same one. A door answered in a second place is a door answered two ways, which
    is the whole history of the four doors ARCHITECTURE.md names.
    """
    return archives.get(source_id) if archives.showing_id == source_id else None


def create_app(
    data_dir: Path, allowed_hosts: list[str] | None = None, background_jobs: bool = True
) -> FastAPI:
    registry = SourceRegistry(data_dir)
    # Anybody who ran the version of one day has a people.json beside the instance rather than
    # inside an archive, and it holds work nothing else makes again. Carried in here rather than
    # read from where it is, because reading it from there is how one person saw another's doctors.
    #
    # What it carried is written down. The answer used to be thrown away — the call stood here
    # with nothing on the left of it — and no page, no command and no line of the README said a
    # word about the move, so a group carried nowhere waited in that file with nothing on the
    # machine saying so. The archive status page says what is still waiting; this says what moved.
    carried_in = people.carry_the_old_file_in(registry.data_dir)
    if carried_in:
        journal.record(registry.data_dir, {"event": "the old people.json was carried into the archives",
                                           "archives": len(carried_in),
                                           "names": sum(carried_in.values())})  # fmt: skip
    jobs = InventoryJobs(registry.data_dir, background=background_jobs)
    # What a person corrects reaches the chart, the search and the tools only once the index is
    # built again. See building.py: it happens by itself, behind the page, and every page says so
    # while it has not happened yet.
    building = Building(registry.data_dir, registry, background=background_jobs)

    def the_archives_of(request: Request) -> TheArchives:
        """Which archive this request is about: decided once, at the top, and handed on as a value.

        Every route that is about somebody's records declares this in its signature, as
        `Depends(the_archives_of)`, so it arrives as an argument rather than being fetched from
        the middle of a handler. That is the whole of the change, and the reason is not the cost.

        Three closures used to answer this question — the open archive of an address, the open
        archive as a list, the id of the open archive — and because they were free variables
        inside `create_app` they could not be forgotten and could not be passed either: there was
        nothing to pass, they were already everywhere. So a page asked twice and got two answers
        on either side of a switch, a press wrote into whichever archive happened to be open when
        it landed rather than the one the page was drawn from, and four forms of the page of
        doctors and clinics took the archive out of the air instead of out of the address. Each of
        those was found and mended one at a time. The next route would have made the same mistake,
        because the shape of the file invited it.

        A value cannot be re-asked. Whoever holds it is holding the archive this request is about;
        whoever needs it has to be given it, which is what the signatures below now say.

        Kept on the request as well as returned, because two things that draw a page have no
        dependencies to declare: the shell every page is drawn in, and the handlers that answer a
        fault with a page. Both of them ask this same function, and get the same reading.
        """
        held = getattr(request.state, "archives", None)
        if held is None:
            held = registry.as_one_reading()
            request.state.archives = held
        return held

    def the_shell_of_every_page(request: Request) -> dict:
        """What the bar and the title of every page say about whose archive this is.

        The header prints the owner's name, the picker of archives and the line about the index
        catching up, and it used to ask for each of those as it rendered — `stage()` three times
        over, `owners()` and `catching_up()` once each, five readings of the list of archives for
        one page, and `stage()` opening the index three times. Worse than the cost: the bar could
        name one person while the page under it was drawn from another's, which is precisely what
        the first entry of the constitution forbids.

        So the shell is given the one reading this request was decided by, as values. It is a
        context processor rather than three globals because a global has no request to ask, and
        the request is where the decision is.
        """
        try:
            archives = the_archives_of(request)
        except Unreadable:
            # A line on a page is never a reason for the page not to be drawn, and the list of
            # archives is one of the files that can be the trouble being reported. Left
            # unguarded, a person who had torn sources.json was answered with the words Internal
            # Server Error about the file they had just torn — including for /favicon.ico, which
            # a browser asks for by itself on every page.
            archives = NO_ARCHIVES
        try:
            here = _how_far(archives)
        except Unreadable:
            here = {"state": "no_archive", "whose": "", "consented": False, "installed": False,
                    "running": False, "archives": 0}  # fmt: skip
        return {"stage": here, "owners": _owners(archives), "catching_up": _catching_up(archives)}

    templates = Jinja2Templates(directory=Path(__file__).parent / "templates",
                                context_processors=[the_shell_of_every_page])  # fmt: skip
    templates.env.filters["thousands"] = lambda number: f"{number:,}"
    templates.env.filters["markdown"] = render_markdown
    # The words for a kind of document, from the one place that holds them. Registered here so a
    # template can ask the same function the Python side asks, instead of printing the name the
    # model returned: six pages printed `lab_panel` where the seventh said "Lab results", and the
    # search results said it twenty-two times on one page. doc_types.py says why.
    templates.env.filters["in_words"] = doc_types.in_words
    # The language of the document whose printed text an element carries, as a lang= on that
    # element. The page itself is English and says so; its content is Russian, Ukrainian, Greek
    # or Spanish, and said nothing — so a browser picked a fallback face and a reading voice for
    # all of it from lang="en". documents.said_in says what it does and does not invent.
    templates.env.filters["said_in"] = said_in

    # Whose archive a page is of is not here: it is a value this request was decided by, and it
    # arrives through the context processor above. A global is a question with no request to ask,
    # which is how the bar came to be able to name somebody the page was not drawn from.
    #
    # The stylesheet is asked for with its own last-changed time, so a change to it reaches a
    # browser that already has the old one. Written by hand, that number is forgotten exactly
    # when it matters: a page is edited, the style with it, and the person who asked for the
    # change sees the old one and reports it as a bug.
    templates.env.globals["style_version"] = lambda: int((Path(__file__).parent / "static" / "app.css").stat().st_mtime)
    # What a person types to reach this program, for every page that tells them to run something:
    # `epicrisis index` on a page and no such command in their shell is not advice.
    templates.env.globals["cli"] = invocation.how_to_run()
    templates.env.globals["cli_root"] = invocation.as_root
    # And which instance every one of those commands acts on. Without it they mean "the folder
    # called data beside wherever you are standing", so a person who had followed the demo and
    # stood in the program's own folder ran the page's advice against another instance, or made
    # one, and was told it had worked. The settings page asked its route for this; every page
    # that prints a command needs it, so it is asked for once, here, like the spelling itself.
    templates.env.globals["data_dir"] = str(registry.data_dir)
    # The two dates a document may be given, handed to the browser as well as checked by the server.
    # Both refusals existed and neither was in the field: a person typing 1899 or next year met a
    # refusal after pressing Save, where the date picker itself could have said so as they typed.
    templates.env.globals["date_limits"] = lambda: {"first": f"{EARLIEST_YEAR}-01-01",
                                                    "last": date.today().isoformat()}  # fmt: skip
    # An id for a control that has to be pointed at from another element — an explanation tied to
    # the button that reveals it. Unique within the page, which is all an id has to be, and
    # numbered from one on every page for the same reason.
    #
    # The counter used to be made here, once, and so it ran for the life of the server: the same
    # page read twice differed in nothing but these numbers. Harmless to a person — the ids still
    # matched inside each page — and expensive to this project, because the sixth entry asks every
    # change to prove it moved nothing, and the ruler that proves it compares pages byte for byte.
    # That ruler was noisy by construction. In two days it cost three separate investigations:
    # "24 of 45 pages shifted", "+2 on pages unrelated to the change", and a report of two entries
    # swapping places on a page where nothing had swapped. A ruler that cries every time is a
    # ruler nobody reads on the day it is right.
    #
    # A context variable rather than a counter per request handed down the call chain, because the
    # macro that asks for an id is imported without context (`{% from %}`) and sees environment
    # globals and nothing else. Starlette copies the context into the threadpool it runs sync
    # handlers in, so one request has one counter whichever thread draws the page.
    templates.env.globals["an_id"] = _an_id

    app = FastAPI(title="Epicrisis Companion", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    # Only answer to the local names: blocks DNS-rebinding pages from reading the dashboard.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or LOCAL_HOSTS)
    # The list of findings is a megabyte of HTML and the vocabulary nearly as much. Served over a
    # phone on a hotel network that is the whole wait. The pages are text and compress to a
    # fraction; the images already do not, and are left alone by the minimum size.
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.exception_handler(StarletteHTTPException)
    async def an_address_that_leads_nowhere(request: Request, gone: StarletteHTTPException):
        """A typed address, or a stale bookmark, answered as a page rather than as JSON.

        Every dead end inside a handler was given one; the router's own 404 and 405 were left
        answering {"detail":"Not Found"} on a white page — and a typed address is the very case
        the page exists for, since a person arrives holding something that worked a minute ago.
        """
        if gone.status_code not in (404, 405) or request.url.path.startswith("/static"):
            return JSONResponse({"detail": gone.detail}, status_code=gone.status_code)
        try:
            the_archives_of(request)
        except Unreadable as broken:
            # The address may lead nowhere *because* nothing can be read. "No page is at that
            # address" is then the smaller of two true things, and the one that helps nobody: a
            # person who mistyped a page, or opened an old bookmark, at the moment the list of
            # archives was torn, was told about their typing and not about the file.
            return await a_file_of_state_that_will_not_read(request, broken)
        said = ("No page of this archive is at that address."
                if gone.status_code == 404 else
                "That address exists, but not for the way it was asked for.")
        return _not_here(request, said, "/", "The timeline", gone.status_code)

    @app.exception_handler(Unreadable)
    async def a_file_of_state_that_will_not_read(request: Request, broken: Unreadable):
        """A page saying which file, what is safe and what puts it right.

        Five files of this program's own state can be there and not parse — sources.json,
        settings.json, indicators.json, validation.json, the index — and each of them used to be
        met differently. Four of the five answered with the words Internal Server Error on a white
        page: the whole dashboard for the first, two pages of seven for the fourth, every page for
        the last. Including, each time, the status page and the settings page, which are where a
        person goes when something is wrong. The file was never named. The MCP server had been
        taught to answer this in words years before its owner's own screen was.

        Two of them are a person's own work and one is a reading a model was paid for, so the
        sentences differ; the one thing that does not is that there is a page, and that it names a
        way on which answers. See SHUT_WHILE_TORN for how that way on is chosen.
        """
        # Where to go on from here: the first way on that this particular file does not take down,
        # or no button at all where it takes both of them down. A button that promises a way out
        # and returns a person to where they are standing is worse than none, and this page exists
        # for exactly the class of defect that was. It used to say "Archive status" for everything
        # but the list of archives, while the status page is drawn out of three of these files.
        way_on = a_way_on(broken)
        every_page_is_this_one = the_torn_file(broken.file) == layout.SOURCES
        # The page says it once, to whoever is looking at it. The journal says it again, with a
        # time and the line it came from, to whoever is asked about it tomorrow. `broken.file` is
        # already relative to the data directory — state.where() cut it there — and the sentences
        # the exception carries are left out: the page is where they belong, and the one thing the
        # journal adds that the page cannot is which of the nine raise sites this was.
        journal.went_wrong(registry.data_dir, "a file of this instance would not read", broken,
                           file=broken.file, code=503)  # fmt: skip
        return templates.TemplateResponse(
            request, "trouble.html",
            {"heading": "A file of this instance cannot be read", "what": str(broken).split(". ")[0] + ".",
             "safe": broken.safe, "mend": broken.mend, "where": broken.file,
             "named_archive": False,
             "nowhere_to_go": "" if way_on else (
                 "Until that file is readable there is nowhere in this interface to go: every page "
                 "of it begins by asking which archives there are."
                 if every_page_is_this_one else
                 "Until that file is readable this page cannot name another that would answer, so "
                 "it offers no button rather than one that leads back to here. The line above is "
                 "the way out."),
             "back": way_on[0] if way_on else "",
             "back_label": way_on[1] if way_on else ""},
            status_code=503,
        )  # fmt: skip

    @app.exception_handler(NoSpace)
    async def the_disk_is_full(request: Request, full: NoSpace):
        journal.went_wrong(registry.data_dir, "there was no space left on the disk", full, code=507)
        return _the_disk_is_full_page(request)

    @app.exception_handler(Busy)
    async def another_run_holds_it(request: Request, busy: Busy):
        """A step already running, answered as a page rather than with the words a crash leaves.

        Every step of this program takes a lock, and the commands this dashboard itself tells a
        person to run take the same locks its buttons do — the indicators are edited by six buttons
        here and by four commands in a terminal, all through indicators.lock. Pressing a button
        while one of those commands was running answered with the words Internal Server Error, and
        the sentence saying which step held the lock and what to do about it went into the server's
        log instead, with the full path of the lock file in it. One button, the one that runs the
        checks, caught this for itself and said it properly; the rest did not.
        """
        # The name of the step is written in this program; the lock is named relative to the data
        # directory, because a path outside it could be an archive folder and those are named
        # after people and after what was wrong with them.
        journal.went_wrong(registry.data_dir, "a step was already running", busy, code=409,
                           **({"step": busy.what} if busy.what else {}),
                           **({"file": _inside_the_data_dir(busy.lock)} if busy.lock else {}))  # fmt: skip
        return templates.TemplateResponse(
            request, "trouble.html",
            {"heading": "That is already running",
             "what": f"{busy.what or 'That step'} is already running on this machine, so it was not "
                     "started a second time.",
             "safe": "Nothing was changed by this and nothing is lost. The run that holds it is "
                     "doing the same work, and it writes what it writes whole or not at all.",
             "mend": "Give it a moment and do it again. If nothing is running — the machine was "
                     "restarted, or that number belongs to something else now — the lock is the file "
                     "named below, and deleting it lets the step run again.",
             "where": _inside_the_data_dir(busy.lock) if busy.lock else "",
             "named_archive": False, "back": "/status", "back_label": "Archive status"},
            status_code=409,
        )  # fmt: skip

    @app.exception_handler(OSError)
    async def trouble_with_a_file(request: Request, trouble: OSError):
        """A full disk, answered as a page. Anything else with a file is still a fault to report.

        On a data directory with nothing free, six buttons of this dashboard — Save, I agree,
        approve a group, rename an owner, judge a finding, rescan a folder — each answered with
        the words Internal Server Error, while every page of it looked healthy and the word "disk"
        appeared nowhere. The likeliest next act of a person meeting that is to start deleting the
        folder that holds thirty years of their reading.
        """
        if not no_space(trouble):
            # Not recorded here: it goes on up, and the middleware below writes the line. Recording
            # it in both places would put every such fault in the journal twice.
            raise trouble
        journal.went_wrong(registry.data_dir, "there was no space left on the disk", trouble, code=507)
        return _the_disk_is_full_page(request)

    def _the_disk_is_full_page(request: Request) -> Response:
        return templates.TemplateResponse(
            request, "trouble.html",
            {"heading": "There is no space left on the disk",
             "what": "This instance could not write what you asked it to, because the disk it keeps its files on is full.",
             "safe": "Nothing was changed and nothing was damaged: every file here is written whole "
                     "and renamed into place, so the one that was already there is still whole.",
             "mend": "Free some space on this machine, then do it again.",
             "where": "", "named_archive": False, "back": "/status", "back_label": "Archive status"},
            status_code=507,
        )  # fmt: skip

    @app.exception_handler(RequestValidationError)
    async def a_number_that_is_not_one(request: Request, trouble: RequestValidationError):
        """A page asked for with ?year=abc answers as a page saying so, not as a JSON error.

        The parameters here are all optional refinements of a view: a wrong one is a typed
        address, not an API call, and a wall of validation JSON is no answer to a person.
        """
        return templates.TemplateResponse(
            request, "bad_request.html",
            {"current": "", "query": "", "wrong": sorted({str(item["loc"][-1]) for item in trouble.errors()})},
            status_code=400,
        )  # fmt: skip

    @app.middleware("http")
    async def number_the_ids_of_this_page_from_one(request: Request, call_next):
        """One page, one numbering, from one. See `_an_id` for what a counter per process cost."""
        _numbering.set(count(1))
        return await call_next(request)

    @app.middleware("http")
    async def write_down_a_fault_nothing_answered(request: Request, call_next):
        """Every failure this dashboard has no page for, recorded on its way out.

        There is no handler for Exception here on purpose: a fault nobody foresaw must not be
        dressed up as one of the five this program knows how to explain. So it goes on up and the
        server answers with the words a crash leaves — and until now that was the whole of it. The
        traceback went to whatever started the server, which on this machine is a terminal
        somebody closed, and nothing on disk remembered that a request had failed at all.

        Which page was being asked for is not written down. A path here carries an archive's
        random id, which is safe, and the id of a document, which is a hash — but it also carries
        whatever a person typed into a search, and the method and the type of the fault are what
        a person looking into it needs.
        """
        try:
            return await call_next(request)
        except Exception as nobody_answered:
            journal.went_wrong(registry.data_dir, "a request failed with no page to answer it",
                               nobody_answered, method=request.method)  # fmt: skip
            raise

    @app.middleware("http")
    async def refuse_cross_origin_writes(request: Request, call_next):
        """A write submitted by another site is refused. A write submitted by this one is not.

        Sec-Fetch-Site is the answer when it is there: the browser computes it, no page can set
        it, and it says plainly whether the form that was submitted was one of ours.

        Origin alone was the check here, and it refused every form on the dashboard. This server
        asks browsers not to pass its address on (Referrer-Policy: no-referrer), and Chrome, told
        that, sends `Origin: null` with a form post from our own page — which is not another
        site, it is this one with its return address taken off. Where Sec-Fetch-Site is absent,
        an Origin naming somebody else still refuses, and a null one refuses with it.
        """
        if request.method not in ("GET", "HEAD"):
            site = request.headers.get("sec-fetch-site")
            origin = request.headers.get("origin")
            if site is not None:
                if site not in ("same-origin", "none"):
                    return Response("Cross-origin request refused.", status_code=403)
            elif origin is not None and urlsplit(origin).netloc not in _our_own_addresses(request):
                return Response("Cross-origin request refused.", status_code=403)
        return await call_next(request)

    def _our_own_addresses(request: Request) -> set[str]:
        """The addresses a browser could have used to reach this page, as it would write them.

        Behind a proxy on the same machine — `tailscale serve`, a port forwarded over ssh — the
        Host header is this server's own address while the one the person typed arrives in
        X-Forwarded-Host, and comparing Origin with Host alone refused every form the dashboard
        has. Neither header can be set by a page on another site; only something in front of us
        can set them, and what is in front of us is the person's own tunnel.
        """
        forwarded = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
        return {address for address in (request.headers.get("host"), forwarded) if address}

    @app.middleware("http")
    async def say_what_a_page_may_do(request: Request, call_next):
        """Headers a page carrying somebody's medical values should not be without.

        Nothing here is loaded from anywhere else and nothing is framed, so the policy can be as
        narrow as the program is; and a page of values has no business sitting in a shared cache
        or naming this address to whatever a link leads to.
        """
        answer = await call_next(request)
        answer.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        answer.headers.setdefault("X-Content-Type-Options", "nosniff")
        answer.headers.setdefault("Referrer-Policy", "no-referrer")
        answer.headers.setdefault("X-Frame-Options", "DENY")
        # Everything this server answers with, except what it serves out of /static. The reason
        # written above is about a page of values, and it was applied to text/html alone — while the
        # densest text in the whole dashboard is not a page but GET /ask/<id>/state, which hands
        # back the whole of a conversation, the questions a person asked about their own health and
        # the answers holding their values, and which is asked again every two seconds while one is
        # being written. /browse carries the names of folders, which are surnames and sometimes
        # diagnoses. A stylesheet and a font are the only things here that a cache should keep.
        if not request.url.path.startswith("/static"):
            answer.headers.setdefault("Cache-Control", "no-store")
        return answer

    def _not_here(request: Request, what: str, back: str = "/", back_label: str = "The timeline",
                  code: int = 404) -> Response:  # fmt: skip
        """A dead end drawn as a page rather than as a line of text on a white background.

        Every one of these has an ordinary cause: the archive that is open was switched, here or
        in another tab left on a document. A person meets it holding an address that worked a
        minute ago, and needs the name of the archive they are in, the menu, and a way out —
        which is precisely what a bare 404 string gives none of.
        """
        return templates.TemplateResponse(
            request, "not_here.html",
            {"what": what, "back": back, "back_label": back_label, "heading": ""}, status_code=code,
        )  # fmt: skip

    def _refused(request: Request, heading: str, what: str, back: str, back_label: str,
                 code: int = 400) -> Response:  # fmt: skip
        """Something a person asked for that this program will not do, said with its own heading.

        The same page as a dead end, because it needs the same things — the name of the archive, the
        menu, a way out — but not the same words. A date before 1900 and a step that could not be
        run were answered under the heading "That is not in this archive", with a paragraph about one
        server holding several archives beneath it: a person was told their archive was gone while
        it was open in front of them, and the thing they had actually done wrong went unsaid.
        """
        return templates.TemplateResponse(
            request, "not_here.html",
            {"what": what, "back": back, "back_label": back_label, "heading": heading}, status_code=code,
        )  # fmt: skip

    def _lines_lost(archives: TheArchives) -> dict[str, int]:
        """Lines this server could not read, from every file that holds them — asked, not waited for.

        torn_lines() knows only about files something in this process has already opened, and the
        status page opens the inventory and the classification and nothing else. So the two files
        its own warning calls irreplaceable — the corrections and the verdicts a person typed —
        were the ones it stayed silent about longest: a line lost from those is lost, and the page
        mentioned it only once somebody had happened to visit the page that reads them. They are a
        few kilobytes; they are read here so that the warning is true when it is drawn.
        """
        for source in archives.all:
            output = source_output_dir(registry.data_dir, source.id)
            for name in (layout.CORRECTIONS, layout.JUDGEMENTS):
                if (output / name).exists():
                    for _ in read_records(output / name):
                        pass
        return torn_lines()

    def _inside_the_data_dir(where: str) -> str:
        """A written file named by its place in this instance's data directory, and no further up.

        Nothing above the data directory reaches a page from here: a path outside it could be an
        archive folder, and those are named after people and what was wrong with them.
        """
        try:
            return str(Path(where).resolve().relative_to(registry.data_dir))
        except ValueError:
            return Path(where).name

    def _folders_not_where_they_were(archives: TheArchives) -> list[dict]:
        """Archives whose folder is not there, or cannot be read, right now.

        One is_dir() per archive, asked as the page draws. Without it a folder that had been moved
        or a disk that had not been mounted left this page saying "Files 43 · Pages 43 · Damaged 0"
        beside a path to nothing, with the trouble showing up only as a broken image where a scan
        should have been — and the only way to make the page admit it was to press Rescan.

        The asking itself is `sources.folder_is_there`, because `sources list` has to give the
        same answer as this page about the same folder, and used to give none at all.
        """
        return [{"id": source.id, "whose": source.whose}
                for source in archives.all if not folder_is_there(source.path)]  # fmt: skip

    def _room_on_the_disk() -> dict:
        """How much room is left where this instance writes, when there is little enough to say so.

        A full disk made every writing button on this dashboard answer with the words Internal
        Server Error while every page of it looked well, and the word "disk" appeared nowhere. A
        person meeting that is as likely to start deleting data/ as to run df.
        """
        try:
            room = shutil.disk_usage(registry.data_dir)
        except OSError:
            return {}
        # Said when it is little: a number on a page that is always there is a number nobody reads.
        little = room.free < max(200 * 1024 * 1024, room.total // 100)
        return {"free": room.free, "total": room.total, "little": little}

    # The archive being looked at, as a list, and the id of it: `archives.open` and
    # `archives.showing_id` on the reading this request was decided by. They stood here as two
    # closures over the registry, each reading sources.json on every call — which is why a page
    # could be drawn out of two archives, and why `/who` took the archive for four of its forms
    # out of the air rather than out of the address.

    def _how_far(archives: TheArchives) -> dict:
        """How far this instance has got, for the pages that have nothing to show yet.

        A tool with no data should read as new, not as broken, and the answer differs: no archive
        added at all, a folder still being looked through, documents not yet read by a model, or a
        folder that was looked through and holds nothing this program can read at all.
        """
        # Whether the reading can be started from where a person is standing, and whether it is
        # already going: the one thing to do next should be doable without finding a page first.
        ready_to_start = {
            "consented": has_consent(registry.data_dir, engines.engine_name(registry.data_dir)),
            "installed": backend_installed(),
            "running": update_running(registry.data_dir),
        }
        # How many archives a reading started from here would walk: it walks all of them.
        ready_to_start["archives"] = len(archives.all)
        active = archives.showing
        if active is None:
            return {"state": "no_archive", "whose": "", **ready_to_start}
        try:
            with closing(open_index(registry.data_dir, active.id)) as connection:
                read = query_index.overview(connection)["documents"]
        except (IndexMissing, Unreadable):
            # An index that cannot be read counts as nothing read, here. Every page that has
            # nothing to show without one answers with a page naming the file and the command that
            # makes it again; this one question is asked by the header of every page, including
            # the status page, which is where a person goes when something is wrong and which must
            # stay on its feet. The step for the index says what is wrong with it.
            read = 0
        if read:
            # Documents in the index are what every page needs; how they got there does not matter.
            return {"state": "ready", "whose": active.whose, **ready_to_start}
        status = jobs.status(active.id) or {}
        # "Being looked through" only while something is actually going. A folder that was
        # scanned and then read, whose index is missing or out of date, is not being worked on
        # by anybody, and telling a person to wait for that is telling them to wait for ever.
        #
        # An archive with no state at all is not being looked through either: that is an archive
        # added from the command line, where nothing starts by itself — adding from the page starts
        # the walk, adding by typing does not. It was read as "a scan whose state has not been
        # written yet", so the one person this program tells to use the command line, because their
        # scans are on a disk of their own, was shown "is being looked through right now" over an
        # instance where nothing was running and nothing would. They wait, and the page that would
        # have told them the real next step — read what goes to a model, and agree — is the branch
        # they never see.
        scanning = status.get("state") in ("running", "queued") and not status.get("finished_at")
        transcribed = (jobs.records_path(active.id).parent / layout.EXTRACTED).is_dir()
        if scanning and not transcribed:
            return {"state": "scanning", "whose": active.whose, **ready_to_start}
        if transcribed:
            return {"state": "unindexed", "whose": active.whose, **ready_to_start}
        # A folder looked all the way through that holds nothing this program can read is not an
        # archive waiting to be read. Every page of this interface told such a person that "the
        # documents have not been read yet" and offered them the step that sends pages to a model
        # — for nought documents — while the one page that knew better, the status page, said
        # "Files 0 / Pages 0" where nobody was sent to look. The likeliest cause is the folder: a
        # level too high, a level too low, or a folder of something else entirely.
        #
        # Only where the walk got all the way through: a scan that failed or was cut off has its own
        # line on the status page, and "there is nothing in that folder" is not what happened to it.
        if status.get("state") == "done" and _nothing_to_read(active.id):
            return {"state": "nothing_to_read", "whose": active.whose, **ready_to_start}
        return {"state": "unread", "whose": active.whose, **ready_to_start}

    def _nothing_to_read(source_id: str) -> bool:
        """Whether the walk of this folder found no page a model could be asked to read.

        The first record with a page in it is the answer, so this costs nothing on an archive that
        has any — which is every archive but the one this question exists for. A file the walk could
        not make sense of, or was refused, carries no pages either: a folder of nothing but those is
        as empty to this program as an empty one, and is the same mistake about the folder.
        """
        inventory = jobs.records_path(source_id)
        if not inventory.exists():
            return True
        return not any(page_refs(record) for record in read_records(inventory))

    def _catching_up(archives: TheArchives) -> dict:
        """Whether the open archive's index is older than what it is built from, and what of it.

        A document's card is drawn from this archive's own files, so a correction shows on it the
        moment it is saved. The chart, the search, the timeline and the tools over the network all
        answer from the index. Between the two there was nothing at all: a person put a number
        right to show a doctor the chart, the card agreed with them, the chart went on drawing the
        model's reading, and no page mentioned either fact.

        Stat calls only, on the few files layout.py names — this is asked once for every page
        drawn, so it cannot be a question that opens the index.
        """
        # A torn list of archives is not caught here any more: it is caught once, where the
        # reading is made, and reaches this as no archive at all — which is the same answer, and
        # the three questions the shell of a page asks now give it together instead of each
        # catching the same exception its own way.
        active = archives.showing
        if active is None:
            return {}
        path = index_path(registry.data_dir, active.id)
        if not path.exists():
            # No index at all is a different sentence, and every page that needs one says it
            # already: what is missing, and the command that makes it.
            return {}
        output = jobs.records_path(active.id).parent
        built = path.stat().st_mtime
        state = building.state(active.id)
        behind = built < layout.changed_since(output, registry.data_dir, "index")
        if not (behind or state["building"] or state["trouble"]):
            return {}
        corrections = output / layout.CORRECTIONS
        return {
            "archive": active.id,
            "behind": behind,
            # Which of the two it is, because the two are not the same news: a correction is a
            # person's own reading of their own page, and it is what they are standing there
            # looking for. Anything else is this program's work catching up with itself.
            "corrected": corrections.exists() and corrections.stat().st_mtime > built,
            **state,
        }

    def _owners(archives: TheArchives) -> dict:
        """Who this server holds archives for, and whose is open. Names are shown, ids are not.

        The picker in the bar and the name over it come out of one reading, which they always had
        to and did not: `list()` and `active()` were two readings of the same file, and the switch
        is a POST the server answers on another thread while this page is being drawn. A bar
        offering three archives with the wrong one marked as open is the smaller half of it.

        Never a reason for a page not to be drawn, which is why the reading is guarded where it is
        made rather than here: a torn list of archives took down the one page that says an address
        leads nowhere — so a typed address or an old bookmark, at the very moment the file was
        torn, answered with the two words instead of the page naming the file. Including
        /favicon.ico, which a browser asks for by itself on every page.
        """
        active = archives.showing
        return {
            "whose": active.whose if active else "",
            "active_id": active.id if active else "",
            "all": [{"id": source.id, "whose": source.whose} for source in archives.all],
        }

    def render(request: Request, archives: TheArchives, error: str | None = None, form_path: str = "",
               status_code: int = 200, forgotten: str = "", form_owner: str = ""):  # fmt: skip
        context = build_view(archives.all, jobs, showing=archives.showing_id)
        context.update(
            model_ready=backend_installed(),
            mcp={"last": mcp_access.last(registry.data_dir), "counts": mcp_access.counts(registry.data_dir),
                 "day": mcp_access.activity(registry.data_dir), "lock": mcp_lock_on(registry.data_dir),
                 "secret": bool(read_lock_secret())},
            # The journal is a new file in the data directory, so this page says it is there, what
            # it is for and — the part that matters more — what is not in it. A file nobody is told
            # about is a file nobody reads when something goes wrong, and a log of a medical
            # archive is a thing a person is entitled to be told the contents of.
            journal={"file": journal.FILE_NAME, "where": str(journal.path(registry.data_dir)),
                     "counts": journal.counts(registry.data_dir),
                     "last": journal.last(registry.data_dir)},  # fmt: skip
            model_consent=has_consent(registry.data_dir, engines.engine_name(registry.data_dir)),
            host=request.headers.get("host", ""),
            updated=datetime.now().astimezone().strftime("%H:%M %Z"),
            error=error,
            form_path=form_path,
            form_owner=form_owner,
            forgotten=forgotten,
            # Lines this server could not read since it started. read_records skips them rather
            # than raising — one torn line must not take every page down — and its docstring
            # promises that the pages which count what an archive holds say so. This is that.
            #
            # Named within the data directory, not by the base name alone: every archive has a
            # classify.jsonl, so "6 in classify.jsonl" over a server holding three of them said
            # nothing about whose records had lost a line.
            torn=[{"file": _inside_the_data_dir(where), "lines": count} for where, count in _lines_lost(archives).items()],
            # The three things a person comes to this page to find out when something is wrong,
            # and which it used to answer by looking perfectly healthy: whether the settings file
            # can be read, whether each archive's folder is where it was, and whether the disk
            # this instance writes to has any room left.
            settings_unreadable=settings_unreadable(registry.data_dir),
            gone_folders=_folders_not_where_they_were(archives),
            disk=_room_on_the_disk(),
            # Groups of doctors and clinics still sitting in an instance-wide people.json. Nought
            # on every instance made since that file moved inside the archives, which is nearly
            # all of them — and the one thing the migration never had was a place to say that it
            # had not finished. A group naming nobody this server knows, or one whose archive
            # already had a file of its own, waited there with nothing on the machine saying so.
            people_waiting=people.still_beside_the_instance(registry.data_dir),
            people_file=str(Path(registry.data_dir) / people.FILE_NAME),
        )
        return templates.TemplateResponse(request, "status.html", context, status_code=status_code)

    @app.get("/status", response_class=HTMLResponse)
    def status_page(request: Request, forgotten: str = "",
                    archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """The exception every other page is measured against: this one is about the list itself.

        Every page but this one answers for the archive that is open and for nobody else. This
        lists them all, with the progress of each, because that is what it is for — and it does
        it out of the same single reading, `archives.all`, so the rows and the counts above them
        cannot come from two different readings of the file either.
        """
        return render(request, archives, forgotten=forgotten)

    @app.get("/", response_class=HTMLResponse)
    def timeline_page(request: Request, view: str = "feed", year: int | None = None, doc_type: str = "",
                      material: str = "", skip: int = 0, undated: bool = False, all_tests: bool = False,
                      paperwork: bool = False, test: str = "", provider: str = "", doctor: str = "",
                      cut: str = "", archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """The archive by its own dates. What it shows is gathered in web/timeline.py.

        The defaults above are what the address asked for when it asked for nothing, and they are
        written in `timeline_view` as well, because FastAPI reads them here to know which of the
        parameters a query string may leave out. tests/test_the_timeline_without_http.py holds the
        two signatures to each other, so the pair cannot drift apart unnoticed.
        """
        # Decided once for the whole request and handed in, because the rows and the groups laid
        # over them have to be of one person. Asked twice, they were not: the archive is
        # switchable from the bar of every page, the switch is an ordinary POST that FastAPI
        # serves on another thread, and nothing holds a request still. A switch landing between
        # the two readings drew one archive's documents under the other archive's joined names —
        # the first entry of the constitution on the page this program opens on.
        context = timeline_view(registry.data_dir, archives.showing_id, view=view, year=year,
                                doc_type=doc_type, material=material, skip=skip, undated=undated,
                                all_tests=all_tests, paperwork=paperwork, test=test,
                                provider=provider, doctor=doctor, cut=cut)  # fmt: skip
        return templates.TemplateResponse(request, "timeline.html", context)

    @app.get("/progress")
    def progress(archives: TheArchives = Depends(the_archives_of)):
        """Step bars only, polled by the status page instead of reloading it."""
        view = build_view(archives.all, jobs, showing=archives.showing_id)
        rows = [{"id": row["id"], "steps": row["steps"]} for row in view["rows"]]
        return {"any_running": view["any_running"], "rows": rows}

    @app.post("/sources")
    def add_source(request: Request, path: str = Form(""), owner: str = Form(""),
                   archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """The shell: what this press does is decided in web/the_list_of_archives.py.

        A refusal is this page again, with what was typed still standing in the form: a folder
        path typed by hand and lost to a sentence is a person typing it twice.
        """
        pressed = the_list.added(registry, path=path, owner=owner)
        if pressed.refused:
            return render(request, archives, error=pressed.trouble, form_path=path,
                          form_owner=owner, status_code=pressed.code)  # fmt: skip
        if pressed.started is not None:
            jobs.start(pressed.started)
        return RedirectResponse("/status", status_code=303)

    @app.post("/owner")
    def choose_owner(request: Request, source: str = Form(""), back: str = Form(""),
                     archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """The shell: what this press does is decided in web/the_list_of_archives.py.

        Where it lands is this file's business, because it is an address: `_same_page` below.
        """
        the_list.shown_instead(registry, archives, source)
        return RedirectResponse(_same_page(back, source), status_code=303)

    def _same_page(back: str, active: str) -> str:
        """The page to return to: the one it was asked from, unless that page is another's.

        A card belongs to one archive by its address, so switching away from it goes to the list
        rather than to a document the new owner does not have. Anything that is not a plain path
        on this server is ignored, so the form cannot be used to send a person elsewhere.
        """
        if not back.startswith("/") or back.startswith("//") or "\\" in back:
            return "/"
        parts = back.split("?")[0].strip("/").split("/")
        # A conversation belongs to one archive by its address, as a document card does, so
        # switching away from it goes to the list rather than to somebody else's chat.
        if len(parts) > 1 and parts[0] == "ask":
            return "/ask"
        if len(parts) > 1 and parts[0] in ("documents", "sources", "owners", "review") and parts[1] != active:
            # Where a person lands, and it should be the same kind of place they left. The page of
            # a scan lives under /sources/<id>/files/…, which was lumped in with acts on the list
            # of archives — renaming an owner, taking one off — so somebody reading a scan and
            # switching person was put on the status page, while doing the same from the card two
            # clicks away left them among the documents.
            among = {"documents": "/documents", "review": "/review", "sources": "/documents"}
            return among.get(parts[0], "/status")
        return back

    @app.post("/owners/{source_id}/name")
    def name_owner(request: Request, source_id: str, owner: str = Form("")):
        """The shell: what this press does is decided in web/the_list_of_archives.py."""
        the_list.owner_named(registry, source_id, owner=owner)
        return RedirectResponse("/status", status_code=303)

    @app.post("/sources/{source_id}/forget")
    def forget_source(request: Request, source_id: str, understood: str = Form(""),
                      archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """The shell: what this press does is decided in web/the_list_of_archives.py.

        Where the reading went is carried to the page in the address, because the page says it in
        so many words and a person wants the path: §8 is that their own work is moved aside and
        kept, and a sentence that does not say where it went is not that promise kept.
        """
        pressed = the_list.read_again_from_nothing(registry, source_id, understood=understood)
        if pressed.refused:
            return render(request, archives, error=pressed.trouble, status_code=pressed.code)
        if not pressed.stored:
            return RedirectResponse("/status", status_code=303)
        where = "?forgotten=nothing" if pressed.nothing_to_move else f"?forgotten={quote(str(pressed.moved_aside))}"
        return RedirectResponse(f"/status{where}", status_code=303)

    @app.post("/owners/{source_id}/remove")
    def remove_owner(request: Request, source_id: str):
        """The shell: what this press does is decided in web/the_list_of_archives.py."""
        the_list.taken_off_the_list(registry, source_id)
        return RedirectResponse("/status", status_code=303)

    def consent_context(archives: TheArchives, error: str | None = None) -> dict:
        """What a run would send — which is every archive on this server, not only the open one.

        Agreeing is for the instance, once, and the reading it allows walks every archive here.
        A screen that counted the pages of the archive being looked at named a fraction of what
        leaves the machine, and named one person while three people's pages went.
        """
        pages = files = 0
        whose = []
        for source in archives.all:
            inventory = jobs.records_path(source.id)
            if not inventory.exists():
                continue
            refs = all_refs(list(read_records(inventory)))
            if refs:
                whose.append(source.whose)
            pages += len(refs)
            files += len({ref.file_sha256 for ref in refs})
        showing = archives.showing
        consented = has_consent(registry.data_dir, engines.engine_name(registry.data_dir))
        # Which engine this is about. Consent is kept per engine, so changing the engine asks
        # again — and the page used to describe Claude Code and a consumer subscription whichever
        # engine was chosen. Somebody agreeing on their own API key was told the wrong transport,
        # the wrong terms and the wrong bill, in the one place where they decide whether to send
        # their pages at all.
        # Whose archives this agreement was never given for: a folder added since is a person who
        # was not named on the page when somebody pressed the button, and often a person who never
        # sees this program at all. Their pages used to go to a provider on the strength of it.
        added_since = consent_not_covered(registry.data_dir, engines.engine_name(registry.data_dir))
        by_id = {source.id: source.whose for source in archives.all}
        return {"consented": consented, "error": error, "pages": pages, "files": files,
                "whose": showing.whose if showing else "", "archives": whose,
                "added_since": [by_id.get(source_id, source_id) for source_id in added_since],
                "engine": engines.chosen_engine(registry.data_dir)}  # fmt: skip

    @app.get("/consent", response_class=HTMLResponse)
    def consent_page(request: Request, archives: TheArchives = Depends(the_archives_of)):
        return templates.TemplateResponse(request, "consent.html", consent_context(archives))

    @app.post("/consent")
    def confirm_consent(request: Request, understood: str = Form(""), action: str = Form("on"),
                        archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        # Taken back by one press, as it was given by one. There was no way at all before this —
        # not a button, not a command, not a line of documentation, only editing consent.json by
        # hand — while the button that gives it is called "Turn on model processing" and a section
        # headed "Your control" said only that nothing is sent before it is pressed. With update in
        # a crontab, that is the difference between "it no longer sends" and "it sends every night".
        if action == "off":
            withdraw_consent(registry.data_dir, engines.engine_name(registry.data_dir))
            return RedirectResponse("/consent", status_code=303)
        if understood != "yes":
            context = consent_context(archives, error="Tick the box to confirm.")
            return templates.TemplateResponse(request, "consent.html", context, status_code=400)
        record_consent(registry.data_dir, engines.engine_name(registry.data_dir))
        return RedirectResponse("/", status_code=303)

    @app.get("/tests/{indicator_id}", response_class=HTMLResponse)
    def test_series(request: Request, indicator_id: str, material: str = "",
                    archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """One test over the years, one material at a time.

        There is no view of every material at once. The same printed name means a different
        measurement in blood and in urine, and a page holding both would be a page of two
        different tests with no way to tell which number is which. So a material is always
        chosen, and where the form said nothing, "not said" is its own answer rather than a
        guess folded in with blood.
        """
        # Decided once and carried into the page, because the one button this page offers writes
        # a correction and has to write it against the archive these values were read out of. See
        # `settle_the_material`.
        showing = archives.showing_id
        context = {"current": "timeline", "indicator_id": indicator_id, "query": "",
                   "archive": showing or ""}  # fmt: skip
        try:
            connection = open_index(registry.data_dir, showing)
        except IndexMissing:
            return templates.TemplateResponse(request, "series.html", {**context, "material": material, "missing": True})
        with closing(connection):
            label = next((item["label"] for item in query_index.indicator_list(connection, status=None)
                          if item["id"] == indicator_id), indicator_id)  # fmt: skip
            every = query_index.whole_history(connection, indicator_id)
            counted: dict[str, int] = {}
            for item in every:
                counted[item["material_key"]] = counted.get(item["material_key"], 0) + 1
            materials = material_tabs(counted)
            if not every:
                # Switching archive keeps a person on this address, and the archive they moved to
                # may have no values of this test. That is an answer, and it is given here — with
                # the header, the name of the archive and a way on — rather than as a bare line.
                known = next((item for item in query_index.indicator_list(connection, status=None)
                              if item["id"] == indicator_id), None)  # fmt: skip
                if known is None:
                    return _not_here(request, "No test of this archive is named by that address.",
                                     "/indicators", "The indicators")  # fmt: skip
                # "No values of this test" has to mean that, and not "none that this page draws".
                calculated = query_index.count_values(connection, indicator=indicator_id, include_derived=True)
                return templates.TemplateResponse(
                    request, "series.html",
                    {**context, "label": known["label"], "material": material, "materials": [],
                     "values": [], "charts": [], "span": {}, "none_here": True,
                     "derived_left_out": calculated},
                )  # fmt: skip
            if material not in {item["key"] for item in materials}:
                material = materials[0]["key"]
            values = query_index.whole_history(connection, indicator_id, material)
            # What the heading says about this history has to be true of the whole of it, not of
            # the part that fitted: how many values there are, and from when to when.
            total = query_index.count_values(connection, indicator=indicator_id, material=material)
            # And what is not in it. Values a laboratory calculated rather than measured are left
            # out of every list and every chart here, deliberately — but silently, so a test whose
            # values are all calculated read as a test this archive has none of. A history that
            # leaves something out has to say what.
            context["derived_left_out"] = query_index.count_values(
                connection, indicator=indicator_id, material=material, include_derived=True) - total  # fmt: skip
            dated = [series.date_label(item) for item in values if item.get("date")]
            span = {"first": dated[0] if dated else None, "last": dated[-1] if dated else None,
                    "undated": sum(1 for item in values if not item.get("date")),
                    "total": total, "more": total > len(values)}  # fmt: skip
        placing = rules_on(registry.data_dir, rules.load(registry.data_dir), kinds.CHARTS)
        context.update(
            label=label, material=material, materials=materials, values=values, span=span,
            material_label=next((item["label"] for item in materials if item["key"] == material), material),
            # Where the form printed no material, a model read the table; the page says which
            # values those are rather than showing a reading and a printed word as one thing.
            read_by_model=sum(1 for item in values if item.get("material_source") == "model"),
            materials_to_choose=[one for one in MATERIALS_TO_CHOOSE if one != "none"],
            charts=series.charts(values, indicator=indicator_id, placing=placing),
        )  # fmt: skip
        return templates.TemplateResponse(request, "series.html", context)

    @app.post("/tests/{source_id}/{indicator_id}/material")
    def settle_the_material(request: Request, source_id: str, indicator_id: str, material: str = Form(""),
                            archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """Say what these were measured in, for every value of this test that has no answer.

        One press for a page of them, because that is how they arrive: a form holding two specimens
        leaves its whole panel without a label, and settling twelve values one card at a time is
        twelve visits to say one thing. It is written as what it is — a person's own correction, one
        line per value, in the file beside their archive — so it outlives every later reading, the
        index takes it, and the page marks those values as set by hand rather than printed.

        Only the values nobody has corrected yet. A line that already carries a correction is keyed
        by what the model printed, and the index shows it as the person left it, so the two cannot
        be matched from here without guessing; those are said out loud and settled on their card.

        The archive is in the address, as it is for every other door that writes a correction. This
        one read whichever archive was open instead — the one open when the press landed — and a page
        of values takes a while to read, with the archive switchable from the bar of any page in
        another tab meanwhile. So the press settled the specimen of every unlabelled value of that
        test in an archive the person was not looking at, writing their own work against somebody
        else's printed lines, and said so nowhere. See `_the_open_archive`.
        """
        source = _the_open_archive(archives, source_id)
        if source is None:
            return _not_here(request, "That was an answer about an archive other than the one open "
                                      "now, so nothing was changed. This page was drawn before the "
                                      "archive was switched.",
                             f"/tests/{indicator_id}", "The test")  # fmt: skip
        if material not in MATERIALS_TO_CHOOSE:
            return _refused(request, "That is not a material this archive can be told about",
                            "The specimen has to be one this program knows: " + ", ".join(MATERIALS_TO_CHOOSE) + ".",
                            f"/tests/{indicator_id}", "The test", 400)  # fmt: skip
        output = jobs.records_path(source.id).parent
        try:
            with closing(open_index(registry.data_dir, source.id)) as connection:
                waiting = query_index.values_with_no_material(connection, indicator_id)
        except (IndexMissing, Unreadable):
            return _not_here(request, "Nothing is indexed yet, so there is no test at that address.",
                             "/status", "Archive status")  # fmt: skip
        for row in waiting:
            if row["corrected"]:
                continue
            written = {"provenance": {"page": row["page"]}, "name_as_printed": row["name"],
                       "value_as_printed": row["value"], "unit_as_printed": row["unit"],
                       "reference_as_printed": row["reference"]}  # fmt: skip
            set_value(output, row["file_sha256"], json.loads(row["pages"] or "[]"),
                      line_key(written), {"material": material})  # fmt: skip
        building.after_a_change(source.id)
        return RedirectResponse(f"/tests/{indicator_id}?material={material}", status_code=303)

    # A question that has just been asked, kept for the page that answers it and for every time a
    # browser comes back to that page. The words travel in the body of the post and the address
    # carries a key, the way the settings page keeps the words of its own message out of a URL.
    #
    # Unlike that one, this is not read once: "back" is the whole point of it. It is kept until the
    # server is restarted, the newest few hundred questions, so that a tab left open overnight still
    # has its results — and where it has been forgotten the page says so instead of answering
    # nothing.
    asked_of_the_search: dict[str, dict] = {}
    QUESTIONS_KEPT = 300

    def _remember_the_question(q: str, doc_type: str, limit: int, offset: int) -> str:
        key = secrets.token_urlsafe(9)
        asked_of_the_search[key] = {"q": q, "doc_type": doc_type, "limit": limit, "offset": offset}
        while len(asked_of_the_search) > QUESTIONS_KEPT:
            asked_of_the_search.pop(next(iter(asked_of_the_search)), None)
        return key

    @app.post("/search")
    def search_posted(request: Request, q: str = Form(""), doc_type: str = Form(""), limit: int = Form(40),
                      offset: int = Form(0)):  # fmt: skip
        """The words in the body, then an address a browser can come back to.

        An address is kept in a browser's history, synced from there to a vendor's servers, offered
        in the address bar to whoever sits at the machine next, and written into the log of any
        tunnel in front of this dashboard. This program says as much where it refuses to put a name
        in a URL, and then put the plainest medical question a person ever types into one.

        The address by hand still works, and the filters of the other pages are still addresses:
        those are views a person moves around in, and a view that cannot be linked is a different
        and worse thing. This one is a question, and a question needs no address.

        But it does need a page. Answering the post itself left the results in a page reached by
        POST, and every answer here carries Cache-Control: no-store — so opening a document from the
        list and pressing back gave ERR_CACHE_MISS, or "Confirm Form Resubmission" in a Chrome with
        a window open: the words gone, the place in the list gone, and the found thing lost. Each
        page of the results was another such entry in the history. So the post stores the question
        and redirects to it by key: the words stay out of the address, and what comes back is an
        ordinary GET, which is the one thing a browser knows how to return to.
        """
        key = _remember_the_question(q, doc_type, limit, offset)
        return RedirectResponse(f"/search?s={key}", status_code=303)

    @app.get("/search", response_class=HTMLResponse)
    def search_page(request: Request, q: str = "", doc_type: str = "", limit: int = 40, offset: int = 0,
                    s: str = "", archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """One line over the whole archive: text, titles, institutions and the printed names of values."""
        # The question this key stands for, asked a moment ago or last night. Not popped: this page
        # is one a person comes back to. A key this server no longer holds is not an empty search —
        # it is a question it has forgotten, and the page says which of the two it is.
        forgotten_question = False
        if s:
            question = asked_of_the_search.get(s)
            if question is None:
                forgotten_question = True
            else:
                q, doc_type = question["q"], question["doc_type"]
                limit, offset = question["limit"], question["offset"]
        # One cap, the one the index enforces, so that asking for five does not silently give ten
        # and asking for four hundred does not silently give two hundred.
        #
        # And a place in the list, because the cap is real: "show more" used to ask for a longer
        # list, and once it had asked for two hundred it asked for two hundred for ever. A person
        # searching a word their laboratory prints on every form pressed it, got the same forty-
        # first to two-hundredth documents back, and had no way to reach the rest of a number this
        # very page had printed at the top. The list is paged instead: the words are still posted,
        # the place in the list travels with them.
        limit = query_index.within_limit(limit)
        offset = max(0, offset)
        context = {"current": "search", "query": q, "doc_type": doc_type, "limit": limit, "offset": offset,
                   "forgotten_question": forgotten_question}  # fmt: skip
        try:
            connection = open_index(registry.data_dir, archives.showing_id)
        except IndexMissing:
            return templates.TemplateResponse(request, "search.html", {**context, "missing": True})
        with closing(connection):
            asked = q.strip()
            context["total"] = query_index.count_search(connection, q, doc_type=doc_type or None) if asked else 0
            # A place past the end of the list is the last page of it, not an empty page with a
            # count of its own: an address typed by hand said "41 documents", printed "no document
            # of this archive holds that among the words printed on it" under them, and footed the
            # page with "Showing 401–400 of 41". The timeline settles the same case this way.
            if asked and context["total"] and offset >= context["total"]:
                offset = max(0, (context["total"] - 1) // limit * limit)
                context["offset"] = offset
            context["documents"] = query_index.search(connection, q, limit=limit, doc_type=doc_type or None,
                                                      offset=offset) if asked else []  # fmt: skip
            context["names"] = query_index.value_names(connection, q, limit=12) if asked else []
            # Tests whose own name, in any of the archive's languages, holds the words — asked for
            # even when documents matched, because a word can be both. This is the machinery that
            # makes a question in one language find values printed in another, and the search page
            # was the one place that did not use it.
            # With the everyday words, because this is a box a person types into: see
            # everyday_words.py, and `said` on a row, which the page prints beside it.
            context["tests"] = query_index.indicators_matching(connection, q, everyday_words_too=True) if asked else []
            # And, where nothing at all matched, what there is instead: a person who typed the word
            # people use for a thing rather than the word a laboratory prints was told "Nothing
            # matched. Try a shorter word, or another language", did both, and was told it again.
            # Then they decide the archive does not hold it and take the box of paper to the doctor.
            context["nothing_matched"] = bool(asked) and not context["documents"] and not context["names"] \
                and not context["tests"]  # fmt: skip
            context["tests_in_all"] = query_index.count_indicators(connection) if context["nothing_matched"] else 0
            return templates.TemplateResponse(request, "search.html", context)

    @app.get("/documents", response_class=HTMLResponse)
    def documents(request: Request, archives: TheArchives = Depends(the_archives_of)):
        # The archive that is open, and no other. These pages carry one person's name at the top
        # and listing everybody's under it is how one archive is read as another's.
        sources = [
            view
            for source in archives.open
            if (view := source_documents(source, jobs.records_path(source.id).parent)) is not None
        ]
        legend = [{"label": f"{round(share * 100)}%", **reading_colour(share)} for share in (0, 0.5, 0.75, 0.9, 1)]
        return templates.TemplateResponse(request, "documents.html", {"sources": sources, "legend": legend})

    @app.get("/documents/{source_id}/{sha256}/{first_page}", response_class=HTMLResponse)
    def card(request: Request, source_id: str, sha256: str, first_page: int,
             archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        source = _the_open_archive(archives, source_id)
        view = document_card(source, jobs.records_path(source_id).parent, sha256, first_page) if source else None
        if view is None:
            return _not_here(request, "No document of this archive is at that address.",
                                     "/documents", "The documents")  # fmt: skip
        return templates.TemplateResponse(
            request, "card.html", {"card": view, "materials_to_choose": MATERIALS_TO_CHOOSE}
        )

    @app.post("/documents/{source_id}/{sha256}/{first_page}/date")
    def set_date(request: Request, source_id: str, sha256: str, first_page: int, value: str = Form(""),
                 archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        source = _the_open_archive(archives, source_id)
        output = jobs.records_path(source_id).parent
        view = document_card(source, output, sha256, first_page) if source else None
        if view is None:
            return _not_here(request, "No document of this archive is at that address.",
                                     "/documents", "The documents")  # fmt: skip
        # Back to the card the date was typed on, which is the page a person is standing on: two of
        # these three sent them to the list of documents instead, and the third answered with one
        # sentence of plain text on a white page — no heading, no menu, no way on but the browser's
        # own back button, in a program with three templates written for exactly this.
        card = f"/documents/{source_id}/{sha256}/{first_page}"
        refused = partial(_refused, request, "That date was not taken", back=card, back_label="The document")
        try:
            chosen = date.fromisoformat(value) if value else None
        except ValueError:
            return refused(what=f"That is not a date this page can read. A date is written as {A_DATE_WRITTEN_OUT}.")
        if chosen and chosen > date.today():
            return refused(what="A document cannot be dated in the future.")
        if chosen and chosen.year < EARLIEST_YEAR:
            return refused(what=f"A document dated before {EARLIEST_YEAR} is a typing slip rather than "
                                "a record. Correct the year, or leave the date empty to let the "
                                "reading of the page decide it.")  # fmt: skip
        set_document_date(output, sha256, view["summary"]["pages"], chosen)
        # A date is what the timeline puts a document on, and the timeline answers from the index.
        building.after_a_change(source_id)
        return RedirectResponse(f"/documents/{source_id}/{sha256}/{first_page}", status_code=303)

    @app.post("/rules")
    def write_rule(request: Request, kind: str = Form(""), name: str = Form(""), summary: str = Form(""),
                   settles: str = Form(""), attaches: str = Form("document"), about: str = Form(""),
                   archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """A rule of this archive's own: a kind that already exists, and words of a person's own.

        No code is written anywhere. The kinds are the ones in the repository under tests, which
        is the same boundary that keeps a rule file from being a program.
        """
        made, wrong = rules.write_one(registry.data_dir,
                                      {"kind": kind, "name": name, "summary": summary,
                                       "settles": settles, "attaches": attaches}, about, kinds.KINDS)  # fmt: skip
        if wrong:
            return _settings_page(request, archives, tab="rules", trouble=wrong)
        return RedirectResponse(
            f"/settings?tab=rules&saved={_remember_saved(f'the rule {made}', '')}#{made}", status_code=303)  # fmt: skip

    @app.post("/review/{source_id}/judge")
    def judge_finding(request: Request, source_id: str, rule: str = Form(""), sha256: str = Form(""),
                      pages: str = Form(""), verdict: str = Form(""),
                      archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """A person's word about one finding: that it was real, or that it was noise.

        It marks and does not hide. Hiding what somebody called noise is the obvious next step
        and it is wrong: one mistaken click would lose a real finding with nothing to show it.
        """
        source = _the_open_archive(archives, source_id)
        if source is None:
            return _not_here(request, "That is not the archive this server has open.", "/status", "Archive status")
        try:
            judgements.record(source_output_dir(registry.data_dir, source_id), rule, sha256,
                              [int(page) for page in pages.split(",") if page.strip()], verdict)  # fmt: skip
        except ValueError:
            return _not_here(request, "That is not a verdict this page can record.", "/review", "To check", 400)
        # Back to the check that was being worked through, open, at the row. The fragment alone
        # opens nothing: a closed details block has to be told, so the check is named twice.
        return RedirectResponse(f"/review?check={quote(rule)}#{quote(rule)}", status_code=303)

    @app.get("/card", response_class=HTMLResponse)
    def patient_card_page(request: Request, tab: str = CARD_TABS[0],
                          archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """What the documents print about the person: the personal facts, medications, diagnoses.

        Printed, not current. "What this person takes" is a judgement about whether a prescription
        is still in force, and nothing on a page says that — so this page says what each document
        prints and when it printed it, and leaves the judging where it belongs.

        Four tabs, each its own address, and the whole card read for every one of them: the three
        rolls and the disagreements between them come out of one pass over the index, and asking
        for a quarter of it would cost a reader of the page nothing and cost this route a second
        shape of answer to keep right.
        """
        # An unknown tab is the first tab, the way an unknown tab of the settings page is. A tab
        # that is none of the four would otherwise draw the four links and nothing underneath them.
        tab = tab if tab in CARD_TABS else CARD_TABS[0]
        empty = {"current": "card", "tab": tab, "diagnoses": [], "medications": [], "blood": [],
                 "personal": [], "conflicts": []}  # fmt: skip
        try:
            connection = open_index(registry.data_dir, archives.showing_id)
        except IndexMissing:
            return templates.TemplateResponse(request, "patient.html", empty)
        with closing(connection):
            return templates.TemplateResponse(request, "patient.html",
                                              {**empty, **query_index.patient_card(connection)})  # fmt: skip

    @app.get("/who", response_class=HTMLResponse)
    def who_page(request: Request, kind: str = "doctor", trouble: str = "",
                 archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """The shell: what this page shows is gathered in web/who.py and drawn here."""
        # Why a press did nothing, where it did nothing. The words travel in this server's memory
        # and the address carries only a key to them, as on the settings page: a link that carries
        # the sentence lets anything that can open a page in the owner's browser put words on
        # their own page — and the words here would be about their own doctors.
        said = just_saved.pop(trouble, (0.0, "", ""))[2] if trouble else ""
        return templates.TemplateResponse(request, "who.html", who.who_view(
            registry.data_dir, archives.showing_id, kind=kind, trouble=said))  # fmt: skip

    def _what_the_press_decided(request: Request, decided: who.Decided) -> Response:
        """A press on the page of doctors and clinics, drawn: a dead end, a sentence, or the page.

        What a dead end and a sentence look like is this file's business; what they say is
        web/who.py's. The tab the person comes back on is the one the press carried, and the
        module hands it back rather than the route guessing it a second time.
        """
        if decided.a_dead_end:
            return _not_here(request, decided.trouble, f"/who?kind={decided.kind}", "Doctors and clinics")
        if decided.trouble:
            return _back_to_who(decided.kind, decided.trouble)
        return RedirectResponse(f"/who?kind={decided.kind}", status_code=303)

    @app.post("/who/{source_id}/join")
    def join_names(request: Request, source_id: str, kind: str = Form("doctor"), one: str = Form(""),
                   other: str = Form(""), label: str = Form(""), names: list[str] = Form([]),
                   archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """The shell: what this press does is decided in web/who.py and answered here."""
        return _what_the_press_decided(request, who.joined(
            registry.data_dir, archives, source_id, the_open_archive=_the_open_archive,
            kind=kind, one=one, other=other, label=label, names=names))  # fmt: skip

    def _back_to_who(kind: str, trouble: str) -> RedirectResponse:
        """To the page, carrying a key to the sentence rather than the sentence itself."""
        return RedirectResponse(f"/who?kind={kind}&trouble={_remember_saved('', trouble)}",
                                status_code=303)  # fmt: skip

    @app.post("/who/{source_id}/decline")
    def decline_names(request: Request, source_id: str, kind: str = Form("doctor"),
                      names: list[str] = Form([]),
                      archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """The shell: what this press does is decided in web/who.py and answered here."""
        return _what_the_press_decided(request, who.declined(
            registry.data_dir, archives, source_id, the_open_archive=_the_open_archive,
            kind=kind, names=names))  # fmt: skip

    @app.post("/who/{source_id}/reconsider")
    def reconsider_names(request: Request, source_id: str, kind: str = Form("doctor"),
                         names: list[str] = Form([]),
                         archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """The shell: what this press does is decided in web/who.py and answered here."""
        return _what_the_press_decided(request, who.reconsidered(
            registry.data_dir, archives, source_id, the_open_archive=_the_open_archive,
            kind=kind, names=names))  # fmt: skip

    @app.post("/who/{source_id}/split")
    def split_names(request: Request, source_id: str, kind: str = Form("doctor"), label: str = Form(""),
                    archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """The shell: what this press does is decided in web/who.py and answered here."""
        return _what_the_press_decided(request, who.separated(
            registry.data_dir, archives, source_id, the_open_archive=_the_open_archive,
            kind=kind, label=label))  # fmt: skip

    @app.get("/indicators", response_class=HTMLResponse)
    def indicators_page(request: Request, status: str = "all", find: str = "", show: str = "all",
                        skip: int = 0, all_waiting: bool = False, trouble: str = "",
                        archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """The shell: what this page shows is gathered in web/indicators_page.py and drawn here."""
        said = just_saved.pop(trouble, (0.0, "", ""))[2] if trouble else ""
        return templates.TemplateResponse(request, "indicators.html", indicators_view(
            registry.data_dir, archives.showing_id, status=status, find=find, show=show, skip=skip,
            all_waiting=all_waiting, trouble=said))  # fmt: skip

    @app.post("/indicators")
    def save_indicator(
        request: Request,
        action: str = Form("save"),
        indicator_id: str = Form(""),
        label: str = Form(""),
        names: str = Form(""),
        status: str = Form("approved"),
        spelling: str = Form(""),
        # Where on the page the person was standing, carried by the form. See _where_i_was.html:
        # the way back was read from the Referer, and this server sends none.
        at_status: str = Form(""), at_find: str = Form(""), at_show: str = Form(""), at_skip: int = Form(0),
        at_all_waiting: str = Form(""),
        archives: TheArchives = Depends(the_archives_of),
    ):  # fmt: skip
        """The shell: what this press does is decided in web/indicators_page.py and answered here."""
        saved = indicators_pressed(
            registry.data_dir, archives, action=action, indicator_id=indicator_id, label=label,
            names=names, status=status, spelling=spelling,
            # Building every archive's index again is the settings page's door as well, so it is
            # one thing in one place here and handed to the press rather than reached for.
            rebuild_index=_rebuild_index,
        )  # fmt: skip
        return _back_to_the_indicators(
            saved.trouble,
            {"status": at_status, "find": at_find, "show": at_show, "skip": at_skip,
             "all_waiting": at_all_waiting},  # fmt: skip
            indicator_id,
        )  # fmt: skip

    def _back_to_the_indicators(trouble: str | None, where: dict, indicator_id: str = "") -> Response:
        """Back to the page this was pressed on, standing where it was pressed.

        The way back used to be read from the Referer header, and this server sets
        Referrer-Policy: no-referrer on everything it answers — so there was never one, and every
        button on this page came back to its first screen: no filter, nothing found, five hundred
        groups closed again. The page whose whole purpose is to be worked through group by group
        forgot where a person was every time they said anything about a group.

        So the page carries its own place in the form, and it lands on the group that was pressed.
        A sentence about what went wrong travels by key rather than in the words: an address that
        carries the words lets any link make this person's own panel say whatever it likes.
        """
        asked = {name: value for name, value in where.items() if value not in ("", 0, None)}
        if trouble:
            asked["trouble"] = _remember_saved("", trouble)
        back = "/indicators" + ("?" + urlencode(asked) if asked else "")
        return RedirectResponse(back + (f"#{indicator_id}" if indicator_id else ""), status_code=303)

    # What one press of Save stored, kept for the redirect that follows it and read once. It used
    # to travel in the address: anything that could open a page in the owner's browser could then
    # make their own panel tell them what had been saved — "the lock over the network off" — with
    # nothing having been saved at all. The address now carries a key that means nothing to
    # anybody who did not just press the button.
    just_saved: dict[str, tuple[float, str, str]] = {}

    def _remember_saved(stored: str, trouble: str) -> str:
        key = secrets.token_urlsafe(9)
        for old_key, (when, _stored, _trouble) in list(just_saved.items()):
            if time.time() - when > 60:
                just_saved.pop(old_key, None)
        just_saved[key] = (time.time(), stored, trouble)
        return key

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, saved: str = "", tab: str = "",
                      archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        when_stored, trouble = "", ""
        # Whether anything was in fact just saved, and not merely whether the address carries the
        # word. A key is read once, on purpose — it is how the words of a message are kept out of an
        # address — so a person who reloads that address, or opens it again from their history, gets
        # nothing back for the key. The page then said "Saved. Nothing on the page was different
        # from what was already stored", which is a statement about their last press and is false:
        # what they changed was stored, and the page told them it had not been.
        said = just_saved.pop(saved, None) if saved else None
        if said:
            _when, when_stored, trouble = said
        return _settings_page(request, archives, bool(said), trouble, tab, stored=when_stored)

    def _settings_page(request: Request, archives: TheArchives, saved: bool = False, trouble: str = "",
                       tab: str = "", waiting: dict | None = None, trying: tuple | None = None,
                       stored: str = "", kept: dict | None = None):  # fmt: skip
        """The shell: what the page shows is gathered in web/settings_page.py and drawn here."""
        return templates.TemplateResponse(request, "settings.html", settings_view(
            registry.data_dir, archives, saved=saved, trouble=trouble, tab=tab,
            waiting=waiting, trying=trying, stored=stored, kept=kept))  # fmt: skip

    @app.post("/settings")
    def save_settings(request: Request, ask_page: str = Form(""), mode: str = Form("as_printed"),
                      engine: str = Form(""),
                      rule_on_ids: list[str] = Form([], alias="rule_on"),
                      shown: list[str] = Form([], alias="shown"),
                      confirmed_rules: list[str] = Form([], alias="confirm_rule"),
                      read_materials: str = Form(""),
                      model_first: str = Form(""), model_strong: str = Form(""),
                      model_second_reader: str = Form(""),
                      mcp_lock: str = Form(""), mcp_lock_scope_choice: str = Form("conversation", alias="mcp_lock_scope"),
                      mcp_lock_minutes_choice: int = Form(240, alias="mcp_lock_minutes"),
                      knob_name: list[str] = Form([]), knob_value: list[str] = Form([]),
                      try_rule: str = Form(""), tab: str = Form(""),
                      archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """The shell: what the press does is decided in web/settings_page.py and answered here."""
        pressed = settings_pressed(
            registry.data_dir, archives, ask_page=ask_page, mode=mode, engine=engine,
            rule_on_ids=rule_on_ids, shown=shown, confirmed_rules=confirmed_rules,
            read_materials=read_materials,
            models={"first": model_first, "strong": model_strong, "second_reader": model_second_reader},
            mcp_lock=mcp_lock, mcp_lock_scope_choice=mcp_lock_scope_choice,
            mcp_lock_minutes_choice=mcp_lock_minutes_choice,
            knob_name=knob_name, knob_value=knob_value, try_rule=try_rule, tab=tab,
            # Building every archive's index again is the indicator page's door as well, so it
            # is one thing in one place here and handed to the press rather than reached for.
            build_indexes=lambda: _rebuild_index(archives),
        )  # fmt: skip
        # A press that is not over: a settings file that cannot be read, a threshold being tried
        # out, or a costly rule held back for asking. The words are already decided; this draws
        # them.
        if pressed.draw_again is not None:
            return _settings_page(request, archives, **pressed.draw_again)
        return RedirectResponse(f"/settings?saved={_remember_saved(pressed.said, pressed.trouble)}&tab={quote(tab)}",
                                status_code=303)  # fmt: skip

    def _rebuild_index(archives: TheArchives) -> str | None:
        """Build every archive's index again. The first failure is returned, and shown."""
        from epicrisis.index.build import build_index

        for source in archives.all:
            try:
                build_index(registry.data_dir, [source])
            except Exception as problem:  # noqa: BLE001 - whatever went wrong, the page must say so
                # The kind of failure and which archive by its id. This sentence travels in the
                # address of the page that shows it, and an address is kept in the browser's
                # history and carried between a person's devices by it. A name belongs on the
                # page, not in a URL, and an exception's own words can quote a path or a value.
                return f"The index of archive {source.id} could not be built again: {type(problem).__name__}."
        return None

    @app.get("/ask", response_class=HTMLResponse)
    @app.get("/ask/{chat_id}", response_class=HTMLResponse)
    def ask_page(request: Request, chat_id: str | None = None,
                 archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        # A chat is about one person's archive. Asked for from another, it is not found — the
        # same answer as one that never existed, because which chats exist is not this page's
        # to tell.
        #
        # Decided once and carried, because the conversation shown and the list it is shown in
        # have to be of one person. Asked twice, a switch landing between them put one person's
        # conversation at the head of the other person's list of them.
        open_archive = archives.showing
        chat = load_chat(registry.data_dir, chat_id, open_archive) if chat_id else None
        if chat_id and chat is None:
            return _not_here(request, "No conversation of this archive is at that address.", "/ask", "Ask")
        return templates.TemplateResponse(
            request,
            "ask.html",
            {
                "current": "ask",
                "chats": list_chats(registry.data_dir, open_archive),
                "chat": chat,
                "enabled": ask_enabled(registry.data_dir),
                "mode": answer_mode(registry.data_dir),
                "carried": carried_questions(chat) if chat else 0,
                "confirmed": has_consent(registry.data_dir, engines.engine_name(registry.data_dir)),
            },
        )

    @app.post("/ask")
    @app.post("/ask/{chat_id}")
    def ask_question(request: Request, chat_id: str | None = None, question: str = Form(""),
                     continue_chat: str = Form("", alias="continue"),
                     archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        if not (ask_enabled(registry.data_dir) and has_consent(registry.data_dir, engines.engine_name(registry.data_dir))):
            # A page, and the one place this is changed. It was a sentence of plain text on a white
            # background, which is what this program answers with nowhere else.
            return _refused(request, "Asking is turned off",
                            "Answering questions is turned off for this instance, or sending pages to "
                            "a model has not been agreed to. Both are on the Settings page, and what "
                            "would be sent is on Model processing.",
                            "/settings", "Settings", 403)  # fmt: skip
        # Unchecked box: the question starts its own chat, so nothing said earlier reaches the model.
        open_archive = archives.showing
        chat = (load_chat(registry.data_dir, chat_id, open_archive) if chat_id and continue_chat
                else new_chat(registry.data_dir, open_archive))  # fmt: skip
        if chat is None:
            return _not_here(request, "No conversation of this archive is at that address.", "/ask", "Ask")
        if background_jobs:
            ask(registry.data_dir, chat["id"], question)
        return RedirectResponse(f"/ask/{chat['id']}", status_code=303)

    @app.post("/ask/{chat_id}/delete")
    def remove_chat(request: Request, chat_id: str,
                    archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        if load_chat(registry.data_dir, chat_id, archives.showing) is None:
            return _not_here(request, "No conversation of this archive is at that address.", "/ask", "Ask")
        if not delete_chat(registry.data_dir, chat_id):
            return _not_here(request, "No conversation of this archive is at that address.", "/ask", "Ask")
        return RedirectResponse("/ask", status_code=303)

    @app.get("/ask/{chat_id}/state")
    def ask_state(chat_id: str, archives: TheArchives = Depends(the_archives_of)):
        chat = load_chat(registry.data_dir, chat_id, archives.showing)
        if chat is None:
            return Response("Unknown chat.", status_code=404)
        return JSONResponse({"running": chat_running(chat), "messages": chat["messages"]})

    @app.get("/review", response_class=HTMLResponse)
    def review(request: Request, copies: str = "", check: str = "",
               archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        sources = []
        for source in archives.open:
            view = review_view(source, jobs.records_path(source.id).parent)
            if view is not None:
                # One line and a link, never the findings themselves. The rules of the suspects
                # step find a hundred and twenty-five documents on this archive, and poured into
                # the list above they would bury the checks a person actually works through —
                # "I shall go mad working through hundreds", in the owner's own words. The count
                # is asked for from the one place that answers it, so this line and the page
                # behind it cannot disagree: see web/looks_misread.py.
                sources.append({**_from_the_index(view, source),
                                "misread": how_many_look_misread(registry.data_dir, source.id)})  # fmt: skip
        return templates.TemplateResponse(
            request, "review.html", {"sources": sources, "current": "review",
                                     "open_copies": bool(copies), "open_check": check}  # fmt: skip
        )

    @app.get("/misread", response_class=HTMLResponse)
    def misread(request: Request, archives: TheArchives = Depends(the_archives_of)):
        """The lines that look misread, heaviest first. One archive's, and nobody else's."""
        sources = [
            {"id": source.id, "whose": source.whose,
             **what_looks_misread(registry.data_dir, source.id)}  # fmt: skip
            for source in archives.open
        ]
        return templates.TemplateResponse(request, "misread.html",
                                          {"sources": sources, "current": "review"})  # fmt: skip

    def _from_the_index(view: dict, source: Source) -> dict:
        """What the index can add to a list of findings, so the page asks one clear thing.

        A group of copies is one thing to decide, not three things to read: which of them
        answers. The index has already grouped them and chosen one, so the page shows that
        choice and lets a person move it, instead of listing each document beside its copies.

        Unreadable parts are the other way round: nine hundred of them, mostly a signature or a
        stamp, and no way to tell which is which without opening the document. The model wrote
        down what it could not read; that sentence goes on the page beside the document.
        """
        try:
            connection = open_index(registry.data_dir, source.id)
        except IndexMissing:
            return view
        with closing(connection):
            groups = query_index.copy_groups(connection)
            parts = query_index.unreadable_parts(connection)
        checks = view["checks"] if not groups else [
            check for check in view["checks"] if check["code"] != "possible_copy"
        ]  # fmt: skip
        if parts:
            checks = [
                check if check["code"] != "unreadable_parts" else {**check, "entries": [
                    {**entry, "parts": parts.get((entry["row"]["file"]["sha256"], entry["row"]["pages"][0]), [])}
                    for entry in check["entries"]
                ]}
                for check in checks
            ]  # fmt: skip
        # Counted again, because this is where what the page draws was last changed: taking
        # possible_copy out of the blocks left its documents in the header's number, and putting
        # the groups in their own block put theirs on the page. One answer, asked where the
        # drawing is settled — web/documents.py holds it.
        drawn = {**view, "copy_groups": groups, "checks": checks}
        return {**drawn, "documents_with_findings": how_many_documents_to_check(drawn)}

    @app.post("/review/{source_id}/{sha256}/{first_page}/copy")
    def choose_copy(request: Request, source_id: str, sha256: str, first_page: int,
                    archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """This one of the copies is the one that answers."""
        source = _the_open_archive(archives, source_id)
        output = jobs.records_path(source_id).parent
        if source is None:
            return _not_here(request, "That is not an archive this server holds.", "/status", "Archive status")
        try:
            group = query_index.choose_primary_copy(registry.data_dir, source_id, sha256, first_page)
        except IndexMissing:
            return _not_here(request, "Nothing is indexed yet, so there are no groups of copies to decide.",
                                     "/status", "Archive status")  # fmt: skip
        if group is None:
            return _not_here(request, "That document is not one of a group of copies.", "/review", "To check")
        # The choice is taken off the rest of the group as well as put on this one. Written only
        # as "this one", the choice made before it stayed on the file, and the next indexing found
        # two chosen documents in one group and decided between them by itself.
        for other in group["others"]:
            set_primary_copy(output, other["file_sha256"], other["pages"], False)
        set_primary_copy(output, sha256, group["pages"], True)
        # No build is asked for here, and this is the one correction that needs none:
        # choose_primary_copy above moves the choice in the index itself, and the correction beside
        # it is what makes it survive the next indexing. Asked for anyway, it would throw away the
        # grouping of every copy in the archive and work it out again to reach the same answer.
        # Back to the group that was just decided, open, rather than to a closed page.
        return RedirectResponse("/review?copies=open#copies", status_code=303)

    @app.post("/sources/{source_id}/validate")
    def run_validation(request: Request, source_id: str,
                       archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        # The checks read one archive's transcriptions and write into its own folder, so they
        # run for the archive that is open and for no other. See _the_open_archive.
        source = _the_open_archive(archives, source_id)
        output = jobs.records_path(source_id).parent
        if source is None or not (output / layout.CLASSIFY).exists():
            return _not_here(request, "That is not an archive this server holds.", "/status", "Archive status")
        # The same care the settings page takes with the same call: the checks take a lock and so
        # can refuse while another run holds it, and a rule can fail in any way at all. Unguarded,
        # that was a 500 for the person and the exception's own words in the server's log — and
        # those words can quote a document or a path, which is what every other place here avoids.
        try:
            validate_source(output, Path(source.path))
        except Busy:
            return _refused(request, "The checks are already running",
                            "The checks are already running on this archive. They take seconds; try "
                            "again in a moment.", "/review", "To check", 409)  # fmt: skip
        except OSError as trouble:
            # A full disk says one thing in all seven places it can happen, and this was the
            # eighth: the broad except below stood in front of the handler for it, so the one
            # button that could not write answered "That is not in this archive" and the word
            # OSError, while the six around it answered with the page about the disk. The heading
            # was a lie as well — the archive was open, in front of the person reading it.
            if no_space(trouble):
                raise
            return _refused(request, "The checks could not be run",
                            f"The checks could not be run: {type(trouble).__name__}. Nothing was "
                            f"changed. Run {CLI} validate in a terminal to see why.",
                            "/review", "To check", 500)  # fmt: skip
        except Exception as exc:  # the type only: a message can quote a document
            return _refused(request, "The checks could not be run",
                            f"The checks could not be run: {type(exc).__name__}. Nothing was changed. "
                            f"Run {CLI} validate in a terminal to see why.",
                            "/review", "To check", 500)  # fmt: skip
        # And built in, by itself, behind the page — as a correction is. What the checks found is in
        # the index as well as in this archive's own file, and the tools over the network answer from
        # the index, so after this the index really is behind: the banner on every page was telling
        # the truth. But it was telling it to somebody who had just done what the page itself
        # advised, and the cure it offered was a second button and a fright. The cure is the build.
        building.after_a_change(source_id)
        return RedirectResponse("/review", status_code=303)

    @app.post("/documents/{source_id}/{sha256}/{first_page}/value")
    def correct_value(
        request: Request, source_id: str, sha256: str, first_page: int,
        key: str = Form(""), action: str = Form("save"),
        name: str = Form(""), value: str = Form(""), unit: str = Form(""), reference: str = Form(""), flag: str = Form(""),
        material: str = Form(""),
        archives: TheArchives = Depends(the_archives_of),
    ):  # fmt: skip
        source = _the_open_archive(archives, source_id)
        output = jobs.records_path(source_id).parent
        view = document_card(source, output, sha256, first_page) if source else None
        if view is None or not key:
            return _not_here(request, "No document of this archive is at that address.",
                                     "/documents", "The documents")  # fmt: skip
        known = {item["key"] for table in view["observation_tables"] for row in table["rows"] for item in [row["main"]]}
        if key not in known:
            return _not_here(request, "No line of this document is the one that correction was "
                                      "made on. A model may have read the page differently since.",
                             "/documents", "The documents")  # fmt: skip
        pages = view["summary"]["pages"]
        if action == "remove":
            set_value(output, sha256, pages, key, None, removed=True)
        elif action == "reset":
            set_value(output, sha256, pages, key, None)
        else:
            # The fields a person may put right are named in corrections.py, so the form cannot
            # come to write one the index does not read.
            written = dict(zip(CORRECTABLE, (name, value, unit, reference, flag), strict=True))
            set_value(output, sha256, pages, key, {
                **written,
                **({"material": material} if material in MATERIALS_TO_CHOOSE else {}),
            })  # fmt: skip
        # The card below shows what was just typed, because a card is read from the files. The
        # chart, the search and the tools read the index, and it is built from them: see
        # building.py for why that is not done here, in front of the person waiting.
        building.after_a_change(source_id)
        return RedirectResponse(f"/documents/{source_id}/{sha256}/{first_page}", status_code=303)

    @app.get("/sources/{source_id}/files/{sha256}/pages/{page}", response_class=HTMLResponse)
    def page_original(request: Request, source_id: str, sha256: str, page: int,
                      archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """The shell: what this page shows is gathered in web/documents.py and drawn here.

        It is gathered there and not beside the list of archives, although its address stands
        under /sources: what it draws is one page of one document, and the card it offers a way
        back to is gathered two functions above it.
        """
        source = _the_open_archive(archives, source_id)
        output = jobs.records_path(source_id).parent
        if source is None or nothing_read_yet(output):
            # Not "there is no such archive": the archive is on this list and has simply been
            # switched, which is what the paragraph under this sentence goes on to explain. A
            # person who had this very page open a minute ago read the first line as their
            # archive having gone. The card of the same document says it of the address.
            return _not_here(request, "That page is not in the archive that is open.",
                             "/status", "Archive status")  # fmt: skip
        shown = one_scanned_page(source, output, sha256, page)
        if shown is None:
            return _not_here(request, "No page of this archive is at that address.", "/documents", "The documents")
        return templates.TemplateResponse(request, "page.html", shown)

    @app.get("/sources/{source_id}/files/{sha256}/pages/{page}/image")
    def page_image(request: Request, source_id: str, sha256: str, page: int,
                   archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """The scan itself, one page of it, drawn by the page above and by nothing else."""
        source = _the_open_archive(archives, source_id)
        output = jobs.records_path(source_id).parent
        if source is None or nothing_read_yet(output):
            # Said of the address and not of the archive, for the reason written over the page above.
            return _not_here(request, "That page is not in the archive that is open.",
                             "/status", "Archive status")  # fmt: skip
        ref = the_scan_at(source, output, sha256, page)
        if ref is None:
            return _not_here(request, "No page of this archive is at that address.", "/documents", "The documents")
        try:
            image = original_png(ref, Path(source.path))
        except PageUnreadable as exc:
            # A page, because this address is also a link on the page above it — "the image on its
            # own" — and a person following it met one line of text with no content type at all.
            # PageUnreadable's words are written in this program and name no file of anybody's.
            return _refused(request, "This page cannot be shown", f"This page cannot be shown: {exc}.",
                            f"/sources/{source_id}/files/{sha256}/pages/{page}", "The page", 409)  # fmt: skip
        return Response(image, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/browse")
    def browse(path: str = "", archives: TheArchives = Depends(the_archives_of)):
        if not path:
            # Somewhere the picker is allowed to look. It opened on the home folder of whoever
            # runs the server, and a server run as root has a home the picker refuses — so the
            # window came up empty, with the button dead and a refusal advising the very folder
            # nobody had chosen. The first root is a folder it can show; where there is none, the
            # refusal that says so is the honest answer and it is the same one either way.
            archive = registry.data_dir / "archive"
            roots = registry.roots()
            path = str(archive if archive.is_dir() else (roots[0] if roots else Path.home()))
        try:
            listing = list_folder(path, added_paths={source.path for source in archives.all},
                                  roots=registry.roots(), data_dir=registry.data_dir)  # fmt: skip
        except BrowseError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status_code)
        try:
            registry.validate(listing["path"])
            listing.update(can_add=True, reason="")
        except SourceError as exc:
            listing.update(can_add=False, reason=str(exc))
        return listing

    @app.post("/update")
    def process_new_files(request: Request):
        """Start the reading, from wherever the person pressed it, and show them the progress.

        A lock left behind by a machine that died holds this for a day, and the button did nothing
        at all: no reading started, no sentence appeared, and the page went on saying the documents
        were being read. The one thing in the way has a name and a file, and pressing the button is
        exactly when to say them.
        """
        if not background_jobs:
            return RedirectResponse("/status", status_code=303)
        if update_running(registry.data_dir):
            return _refused(request, "A reading is already going",
                            "A reading of this archive is already going, or a lock says it is. What "
                            f"says so is the file {registry.data_dir / 'update.lock'}, which names the "
                            "process that took it. If that process is gone — a machine restarted in "
                            "the middle of a reading leaves the lock behind — deleting that one file "
                            "lets this step run again. A lock older than a day is ignored by itself.",
                            "/status", "Archive status", 409)  # fmt: skip
        start_update(registry.data_dir)
        return RedirectResponse("/status", status_code=303)

    @app.post("/index/{source_id}/build")
    def build_in_what_changed(request: Request, source_id: str,
                              archives: TheArchives = Depends(the_archives_of)):  # fmt: skip
        """Build this archive's index again, because a person asked for it on the page saying so.

        It happens by itself after a correction. This is for every other way an index comes to be
        older than the files it is built from — a reading run in a terminal, a build that failed, a
        server that was not running when the correction was made — and for a person who would
        rather press the thing than trust that it is happening.
        """
        # One archive's own, and only the one being looked at: the same boundary as the checks and
        # the corrections. See _the_open_archive.
        source = _the_open_archive(archives, source_id)
        if source is None:
            return _not_here(request, "That is not an archive this server holds.", "/status", "Archive status")
        # What went wrong is not carried back in the address: it is kept beside the archive it
        # happened to, and the same line on every page that reports the index being behind reports
        # it. An address travels into a person's history and between their devices.
        building.now(source_id)
        return RedirectResponse(_same_page(request.headers.get("referer", "/"), source_id) or "/", status_code=303)

    @app.post("/sources/{source_id}/inventory")
    def rescan_source(request: Request, source_id: str):
        """The shell: what this press does is decided in web/the_list_of_archives.py."""
        pressed = the_list.looked_through_again(registry, source_id)
        if pressed.started is None:
            return _not_here(request, "That is not an archive this server holds.", "/status", "Archive status")
        jobs.start(pressed.started)
        return RedirectResponse("/status", status_code=303)

    return app


def build_view(sources: list[Source], jobs: InventoryJobs, showing: str | None = None) -> dict:
    """Every archive's progress, and the counts of the one that is open.

    The rows are the list of archives, which is what this page is for. The numbers above them
    are of the archive being looked at: with two people on one server, a total of both is a
    number about nobody, and it appeared under whichever name was open.
    """
    totals = Summary()
    rows = []
    for source in sources:
        summary = None
        records: list[dict] = []
        records_path = jobs.records_path(source.id)
        if records_path.exists():
            summary = Summary()
            records = list(read_records(records_path))
            for record in records:
                summary.add(record)
                if showing is None or source.id == showing:
                    totals.add(record)
        # Read once and handed to both, as the ledger above already is. Each step used to read the
        # whole of classify.jsonl for itself — 171 ms apiece on an archive ten times this one, so
        # 343 ms of which half was a repetition, and multiplied by the number of archives on the
        # list. This is the page that must stay standing whatever else has happened to the data,
        # and it had become the most expensive one in the program.
        classify_pages = latest_pages(records_path.parent / layout.CLASSIFY)
        classify = _classify_step(records, records_path.parent, classify_pages)
        extract = _extract_step(records, records_path.parent, classify_pages)
        rows.append(
            _source_row(
                source, summary, jobs.status(source.id), classify, extract,
                validation_state(records_path.parent), index_state(jobs.data_dir, records_path.parent, source.id),
            )  # fmt: skip
        )

    everyone = Summary()
    for source in sources:
        records_path = jobs.records_path(source.id)
        if records_path.exists():
            for record in read_records(records_path):
                everyone.add(record)

    return {
        "steps": PIPELINE_STEPS,
        "rows": rows,
        # What the "read the documents" button would send: every archive here, not the open one.
        "everyone": {"pages": everyone.pdf_pages + everyone.image_frames, "archives": len(sources)},
        "any_running": any(step["state"] == "running" for row in rows for step in row["steps"]),
        "update_running": update_running(jobs.data_dir),
        "whose_totals": next((source.whose for source in sources if source.id == showing), ""),
        "totals": {
            "files": totals.files,
            "pages": totals.pdf_pages + totals.image_frames,
            "vision_pages": totals.vision_pages,
            "pages_without_text": totals.pdf_pages_without_text,
            "duplicates": totals.extra_copies,
            "damaged": len(totals.damaged),
        },
    }


def _classify_step(records: list[dict], output: Path, classify_pages: list[dict] | None = None) -> dict:
    """`classify_pages` is the file already read, for a caller that needs it twice."""
    wanted = {(ref.file_sha256, ref.page) for ref in all_refs(records)}
    if not wanted:
        return {"state": "not_started", "label": "", "title": "Classify: nothing to classify yet"}
    pages = latest_pages(output / layout.CLASSIFY) if classify_pages is None else classify_pages
    done = sum(1 for page in pages if (page["file_sha256"], page["page"]) in wanted)
    percent = int(done * 100 / len(wanted))
    title = f"Classify: {done} of {len(wanted)} pages"
    # A run holding the lock is running, whatever the counts say — pages classified again after a
    # change are counted as done while the pass that is redoing them is still going. Extract has
    # always answered this way; the two now agree, and neither reports a finished step as busy.
    if is_running(output):
        return {"state": "running", "percent": percent, "label": f"{percent}%", "title": title}
    if done >= len(wanted):
        return {"state": "done", "label": "", "title": title}
    if done:
        return {"state": "partial", "percent": percent, "label": f"{percent}%", "title": title}
    return {"state": "not_started", "label": "", "title": title}


def _extract_step(records: list[dict], output: Path, classify_pages: list[dict] | None = None) -> dict:
    """How far the reading of the documents got: by the ledger, and by what is on the disk.

    The ledger alone said done where a transcription had gone missing from extracted/ — a file
    deleted by hand, a folder half-restored from a copy, a disk that lost it. The ledger holds the
    key, so `epicrisis update` never reads that document again, and the step drew as finished and
    green: the one place a person looks to find out whether their archive has been read told them
    it had. Every other part of this program had it right at the same moment — validate counted it
    as not transcribed, the card said "Not transcribed yet" — but nobody goes looking for a
    document they have been told is there.

    So the step counts the two together, and says both numbers when they differ. The way out is
    cheap and now nameable: one document, one call of a model.
    """
    by_file = {record["sha256"]: record for record in records if "sha256" in record}
    if classify_pages is None:  # the caller that needs it twice reads it once and hands it over
        classify_pages = latest_pages(output / layout.CLASSIFY)
    documents = document_refs(by_file, classify_pages)
    if not documents:
        return {"state": "not_started", "label": "", "title": "Extract: nothing to extract yet"}
    finished = {key[:2] for key in done_keys(output / layout.LEDGER, classify_pages)}
    done = sum(1 for document in documents if (document.file_sha256, document.pages) in finished)
    # A document the reading itself could not make out is finished with, and carries no
    # transcription by design. Counted among those that should have one, it made the page say
    # values were gone — for ever, since reading it again ends the same way — on an archive where
    # nothing had been lost. What it is, the checks say in their own words on their own page.
    transcribed = {key[:2] for key in done_keys(output / layout.LEDGER, classify_pages, statuses=("done",))}
    # The document, not the file it is filed in. One file holds a list of documents, so the file
    # can be there without the one the ledger counts as read — a four-page scan that is two forms
    # and a folder half restored from an older copy, which is the very case named a few lines up.
    # The checks a step away ask this question properly; this one asked whether a file exists.
    expected = sum(1 for document in documents if (document.file_sha256, document.pages) in transcribed)
    on_disk = sum(1 for document in documents
                  if (document.file_sha256, document.pages) in transcribed
                  and _the_document_is_there(output, document))  # fmt: skip
    percent = int(done * 100 / len(documents))
    title = f"Extract: {done} of {len(documents)} documents classified so far"
    if is_running(output, EXTRACT_LOCK):
        return {"state": "running", "percent": percent, "label": f"{percent}%", "title": title}
    if on_disk < expected:
        missing = expected - on_disk
        return {
            "state": "partial", "percent": int(on_disk * 100 / len(documents)), "label": f"{on_disk}/{len(documents)}",
            "title": f"Extract: {done} of {len(documents)} documents read by the ledger, {on_disk} on disk",
            "note": f"{missing} document{'s' if missing > 1 else ''} counted as read {'have' if missing > 1 else 'has'} "
                    "no transcription on disk any more, so the values read from "
                    f"{'them' if missing > 1 else 'it'} are gone and '{CLI} update' will not read "
                    f"{'them' if missing > 1 else 'it'} again: the ledger says it is done. Read "
                    f"{'them' if missing > 1 else 'it'} again with '{CLI} extract --redo', which "
                    "asks the model only for what is missing.",
            "alert": True,
        }  # fmt: skip
    if done >= len(documents):
        return {"state": "done", "label": "", "title": title}
    if done:
        return {"state": "partial", "percent": percent, "label": f"{percent}%", "title": title}
    return {"state": "not_started", "label": "", "title": title}


def _the_document_is_there(output: Path, document) -> bool:
    """Whether this document — these pages of this file — is actually inside what was written."""
    from epicrisis.extract.run import load_extracted

    written = load_extracted(output / layout.EXTRACTED, document.file_sha256)
    return any(one["pages"] == list(document.pages) for one in (written or {"documents": []})["documents"])


def _source_row(source: Source, summary: Summary | None, status: dict | None, classify: dict, extract: dict, validate: dict, index: dict) -> dict:
    state = status["state"] if status else "not_started"
    inventory = {"state": state, "label": "", "title": "Inventory"}
    note, alert = "", False

    if state == "running":
        total = status.get("total") or 0
        percent = int(status["scanned"] * 100 / total) if total else 0
        inventory.update(state="running", percent=percent, label=f"{percent}%")
    elif state == "done":
        inventory["title"] = "Inventory done"
    elif state == "failed":
        # In a sentence where there is one to say. The message of the exception is not shown and
        # not kept: reading a folder of somebody's documents fails with their file names in it.
        # But this program's own refusals explain themselves in words written in this program, and
        # those words carry no path — so the commonest failure of all, a folder that is no longer
        # there, no longer reaches a person as the name of a Python class with "try again" under it.
        said = status.get("said") or CAN_BE_SAID.get(status.get("error", ""), "")
        if not said:
            went_wrong = status.get("error") or "the scan"
            said = f"The folder could not be read through: {went_wrong}. Nothing in it was changed. Rescan to try again."
        inventory.update(label="Failed", title=said)
        note, alert = said, True
    elif state == "interrupted":
        inventory.update(label="Interrupted", title="The server stopped during the scan. Rescan to finish.")
    else:
        inventory["label"] = "Queued"

    if summary is not None and not note:
        details = []
        if summary.damaged:
            details.append(f"{len(summary.damaged)} damaged")
            alert = True
        if summary.extra_copies:
            details.append(f"{summary.extra_copies} duplicate" + ("s" if summary.extra_copies != 1 else ""))
        if summary.unsupported:
            details.append(f"{len(summary.unsupported)} unsupported")
        note = " / ".join(details)

    later_steps = [
        validate,
        index,
    ]
    # A step that has something to say about itself says it on the row, **beside** the scan's own
    # note and not instead of it. Written as "only if nothing is here yet", the sentence about a
    # transcription that has gone missing — values lost, and 'update' will never read that
    # document again — was displaced by "3 duplicates" on every archive that has a duplicate in
    # it, which is nearly all of them. The neutral note won because it was written first.
    for step in (classify, extract, validate, index):
        if step.get("note"):
            note = f"{note} · {step['note']}" if note else step["note"]
            alert = alert or step.get("alert", False)
    return {
        "id": source.id,
        "name": source.name,
        "whose": source.whose,
        "owner": source.owner,
        "active": source.active,
        "path": source.path,
        "files": summary.files if summary is not None else None,
        "note": note,
        "alert": alert,
        "can_rescan": state != "running",
        "steps": [inventory, classify, extract, *later_steps],
    }
