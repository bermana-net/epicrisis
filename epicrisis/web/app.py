"""Status dashboard: which folders are registered and how far each got through the pipeline.

It shows counts and paths only, never document contents or values.
"""

import json
from contextlib import closing, suppress
from functools import partial
from itertools import count
import os
import secrets
import shutil
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

from fastapi import FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from epicrisis import invocation, layout
from epicrisis.classify.backend import backend_installed
from epicrisis.classify.pages import PageUnreadable, cannot_be_read, original_png, page_refs
from epicrisis.classify.report import latest_pages
from epicrisis.classify.run import all_refs, is_running
from epicrisis.extract.run import LOCK_NAME as EXTRACT_LOCK
from epicrisis.extract.run import document_refs, done_keys
from epicrisis.consent import has_consent, not_covered as consent_not_covered, record_consent, withdraw_consent
from epicrisis.corrections import CORRECTABLE, line_key, set_document_date, set_primary_copy, set_value
from epicrisis import indicators as indicator_store
from epicrisis import judgements
from epicrisis.index.build import index_path, index_state
from epicrisis.indicator_check import load_checks
from epicrisis import mcp_access
from epicrisis.mcp_lock import read_secret as read_lock_secret
from epicrisis import engines
from epicrisis.engines import set_engine
from epicrisis.models import KNOWN_MODELS, PASSES, model_for
from epicrisis import query as query_index
from epicrisis import rules
from epicrisis.rules import kinds, tally
from epicrisis import series
from epicrisis.query import IndexMissing, open_index
from epicrisis.state import NoSpace, Unreadable, no_space
from epicrisis.printed_values import fold
from epicrisis.inventory.report import Summary
from epicrisis.records import read_records, torn_lines
from epicrisis.runs import ABANDONED_AFTER_HOURS, Busy, holder
from epicrisis.sources import Source, SourceError, SourceRegistry, source_output_dir
from epicrisis.web.browse import BrowseError, list_folder
from epicrisis.web.markdown import render_markdown
from epicrisis.ask import ask, carried_questions, delete_chat, list_chats, load_chat, new_chat
from epicrisis.ask import running as chat_running
from epicrisis.settings import unreadable as settings_unreadable
from epicrisis.settings import (ANSWER_MODES, answer_mode, ask_enabled,
                                mcp_lock_minutes, mcp_lock_on, mcp_lock_scope, rule_on,
                                rule_settings, rules_on, set_answer_mode, set_ask_enabled,
                                set_chosen_models, set_mcp_lock, set_mcp_lock_minutes,
                                set_mcp_lock_scope, set_rule_on, set_rule_settings,
                                set_trusts_read_materials,
                                trusts_read_materials)  # fmt: skip
from epicrisis.update import start_in_background as start_update
from epicrisis.update import update_running
from epicrisis.validate import validate_source, validation_state
from epicrisis.web.building import Building
from epicrisis.web.documents import document_card, reading_colour, review_view, source_documents
from epicrisis.web.jobs import CAN_BE_SAID, InventoryJobs
from epicrisis.invocation import CLI

PIPELINE_STEPS = ["Inventory", "Classify", "Extract", "Validate", "Index"]
# The earliest year a person may give a document by hand. Before this it is a typing slip rather
# than a record, and the field on the card says so as they type as well as the server after.
EARLIEST_YEAR = 1900
LOCAL_HOSTS = ["localhost", "127.0.0.1"]


# The four tabs of the settings page, in the order they stand in. First is where an address
# that names no tab at all, or names one that is not here, arrives.
SETTINGS_TABS = ("model", "reading", "rules", "network")
# What each answer mode is called, for the line that says what one press of Save stored. The
# banner named the setting and not the side — "Saved: what may be said about a value" for the
# move into the one mode where this application compares a number with a printed range, and the
# same words for the move back out of it. Its neighbours in that list all say which way they went.
ANSWER_MODE_NAMES = {"as_printed": "as printed only", "with_meaning": "the values may also be read",
                     "direct": "no limits set here"}  # fmt: skip
# What the two filters of the indicator page offer. Nothing else is a filter.
INDICATOR_STATUSES = ("all", "approved", "proposed")
INDICATOR_VIEWS = ("all", "to_review", "disagreed")

# The order the material tabs stand in, and the words on them. Blood leads because most of a
# person's results are blood. What the form did not say comes last and stays its own answer: an
# unmarked value is probably blood, and probably is not something this archive says out loud.
MATERIAL_ORDER = ("blood", "urine", "stool", "semen", "swab", "csf", "saliva", "sputum",
                  # Last, and not materials: the two reasons a value has none. See query.MATERIAL_KEY.
                  "not_a_sample", "unknown")  # fmt: skip
# What a person may set by hand on one line, where the form's layout leaves it ambiguous: a
# table with rows of two specimens, a panel headed for one thing and holding a section of
# another. "none" is here too, for a measurement made on the person rather than in a sample.
MATERIALS_TO_CHOOSE = ("blood", "urine", "stool", "semen", "swab", "csf", "saliva", "sputum", "none")
# "Not said" was said of both of these, and they are not the same thing at all: one is an answer
# about a measurement made on a person, the other is a lab value whose label is missing and which
# somebody can still supply.
MATERIAL_LABELS = {"not_a_sample": "Not a sample", "unknown": "Material unknown"}


def material_tabs(counted: dict[str, int]) -> list[dict]:
    """One tab per material there is anything to show for, in that order, with its count."""
    return [
        {"key": key, "label": MATERIAL_LABELS.get(key, key), "count": counted[key]}
        for key in (*MATERIAL_ORDER, *sorted(set(counted) - set(MATERIAL_ORDER)))
        if key in counted
    ]  # fmt: skip


def create_app(
    data_dir: Path, allowed_hosts: list[str] | None = None, background_jobs: bool = True
) -> FastAPI:
    registry = SourceRegistry(data_dir)
    jobs = InventoryJobs(registry.data_dir, background=background_jobs)
    # What a person corrects reaches the chart, the search and the tools only once the index is
    # built again. See building.py: it happens by itself, behind the page, and every page says so
    # while it has not happened yet.
    building = Building(registry.data_dir, registry, background=background_jobs)
    templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
    templates.env.filters["thousands"] = lambda number: f"{number:,}"
    templates.env.filters["markdown"] = render_markdown

    # Every page shows whose archive it is, so the header asks for it as it renders.
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
    templates.env.globals["owners"] = lambda: _owners()
    templates.env.globals["stage"] = lambda: _stage()
    templates.env.globals["catching_up"] = lambda: _catching_up()
    # The two dates a document may be given, handed to the browser as well as checked by the server.
    # Both refusals existed and neither was in the field: a person typing 1899 or next year met a
    # refusal after pressing Save, where the date picker itself could have said so as they typed.
    templates.env.globals["date_limits"] = lambda: {"first": f"{EARLIEST_YEAR}-01-01",
                                                    "last": date.today().isoformat()}  # fmt: skip
    # An id for a control that has to be pointed at from another element — an explanation tied to
    # the button that reveals it. Unique within the page, which is all an id has to be.
    numbering = count(1)
    templates.env.globals["an_id"] = lambda prefix="id": f"{prefix}-{next(numbering)}"

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
            registry.list()
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
        """
        # Where to go on from here, and nowhere at all when the file that will not read is the list
        # of archives: every page of this dashboard begins by reading it, so each of them answers
        # with this same page — including the status page the button pointed at. A button that
        # promises a way out and returns a person to where they are standing is worse than none, and
        # this page exists for exactly the class of defect that was.
        every_page_is_this_one = broken.file == layout.SOURCES
        return templates.TemplateResponse(
            request, "trouble.html",
            {"heading": "A file of this instance cannot be read", "what": str(broken).split(". ")[0] + ".",
             "safe": broken.safe, "mend": broken.mend, "where": broken.file,
             "named_archive": False,
             "nowhere_to_go": ("Until that file is readable there is nowhere in this interface to go: "
                               "every page of it begins by asking which archives there are."
                               if every_page_is_this_one else ""),
             "back": "" if every_page_is_this_one else "/status",
             "back_label": "Archive status"},
            status_code=503,
        )  # fmt: skip

    @app.exception_handler(NoSpace)
    async def the_disk_is_full(request: Request, full: NoSpace):
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
            raise trouble
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

    def _the_open_archive(source_id: str) -> Source | None:
        """The archive named in an address, but only while it is the one that is open.

        A document, its scan and the corrections on it are content, and every page that shows
        them carries one person's name at the top. Addressed from under another archive they
        answer as though they do not exist, which is the same rule the chats follow. The status
        page is the exception it makes itself: it lists every archive, and renaming, rescanning
        or taking one off the list are acts on the list rather than on anybody's records.
        """
        active = registry.active()
        return registry.get(source_id) if active and active.id == source_id else None

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

    def _lines_lost() -> dict[str, int]:
        """Lines this server could not read, from every file that holds them — asked, not waited for.

        torn_lines() knows only about files something in this process has already opened, and the
        status page opens the inventory and the classification and nothing else. So the two files
        its own warning calls irreplaceable — the corrections and the verdicts a person typed —
        were the ones it stayed silent about longest: a line lost from those is lost, and the page
        mentioned it only once somebody had happened to visit the page that reads them. They are a
        few kilobytes; they are read here so that the warning is true when it is drawn.
        """
        for source in registry.list():
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

    def _folders_not_where_they_were() -> list[dict]:
        """Archives whose folder is not there, or cannot be read, right now.

        One is_dir() per archive, asked as the page draws. Without it a folder that had been moved
        or a disk that had not been mounted left this page saying "Files 43 · Pages 43 · Damaged 0"
        beside a path to nothing, with the trouble showing up only as a broken image where a scan
        should have been — and the only way to make the page admit it was to press Rescan.
        """
        gone = []
        for source in registry.list():
            folder = Path(source.path)
            try:
                there = folder.is_dir() and os.access(folder, os.R_OK | os.X_OK)
            except OSError:
                there = False
            if not there:
                gone.append({"id": source.id, "whose": source.whose})
        return gone

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

    def _open_archives(registry: SourceRegistry) -> list[Source]:
        """The archive being looked at, as a list, or none at all when none is added yet.

        Every page but the status page is about one person. The status page lists the archives,
        which is what it is for; the rest answer for whoever is open and for nobody else.
        """
        active = registry.active()
        return [active] if active is not None else []

    def _showing(registry: SourceRegistry = registry) -> str | None:
        """The id of the archive the interface is showing, or None when none is added yet."""
        active = registry.active()
        return active.id if active else None

    def _stage() -> dict:
        """How far this instance has got, and never a reason for a page to fail.

        Asked by every page as it draws its title and its menu — including the page whose whole
        job is to say that a file of this instance will not read. Left unguarded, that page asked
        this question, this question read the same file, and a person who had torn sources.json
        was answered with the words Internal Server Error about the file they had just torn.
        """
        try:
            return _how_far()
        except Unreadable:
            return {"state": "no_archive", "whose": "", "consented": False, "installed": False,
                    "running": False, "archives": 0}  # fmt: skip

    def _how_far() -> dict:
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
        ready_to_start["archives"] = len(registry.list())
        active = registry.active()
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

    def _catching_up() -> dict:
        """Whether the open archive's index is older than what it is built from, and what of it.

        A document's card is drawn from this archive's own files, so a correction shows on it the
        moment it is saved. The chart, the search, the timeline and the tools over the network all
        answer from the index. Between the two there was nothing at all: a person put a number
        right to show a doctor the chart, the card agreed with them, the chart went on drawing the
        model's reading, and no page mentioned either fact.

        Stat calls only, on the few files layout.py names — this is asked once for every page
        drawn, so it cannot be a question that opens the index.
        """
        try:
            active = registry.active()
        except Unreadable:
            # A line on a page is never a reason for the page not to be drawn, and the list of
            # archives is one of the files that can be the trouble being reported.
            return {}
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

    def _owners() -> dict:
        """Who this server holds archives for, and whose is open. Names are shown, ids are not.

        Never a reason for a page not to be drawn, for the same reason _stage is not: this is the
        second question the header of every page asks, and it reads the same file. Guarded there and
        not here, a torn list of archives took down the one page that says an address leads nowhere
        — so a typed address or an old bookmark, at the very moment the file was torn, answered with
        the two words instead of the page naming the file. Including /favicon.ico, which a browser
        asks for by itself on every page, filling the log with tracebacks exactly when it is read.
        """
        try:
            sources = registry.list()
            active = registry.active()
        except Unreadable:
            return {"whose": "", "active_id": "", "all": []}
        return {
            "whose": active.whose if active else "",
            "active_id": active.id if active else "",
            "all": [{"id": source.id, "whose": source.whose} for source in sources],
        }

    def render(request: Request, error: str | None = None, form_path: str = "", status_code: int = 200,
               forgotten: str = "", form_owner: str = ""):  # fmt: skip
        context = build_view(registry.list(), jobs, showing=_showing(registry))
        context.update(
            model_ready=backend_installed(),
            mcp={"last": mcp_access.last(registry.data_dir), "counts": mcp_access.counts(registry.data_dir),
                 "day": mcp_access.activity(registry.data_dir), "lock": mcp_lock_on(registry.data_dir),
                 "secret": bool(read_lock_secret())},
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
            torn=[{"file": _inside_the_data_dir(where), "lines": count} for where, count in _lines_lost().items()],
            # The three things a person comes to this page to find out when something is wrong,
            # and which it used to answer by looking perfectly healthy: whether the settings file
            # can be read, whether each archive's folder is where it was, and whether the disk
            # this instance writes to has any room left.
            settings_unreadable=settings_unreadable(registry.data_dir),
            gone_folders=_folders_not_where_they_were(),
            disk=_room_on_the_disk(),
        )
        return templates.TemplateResponse(request, "status.html", context, status_code=status_code)

    @app.get("/status", response_class=HTMLResponse)
    def status_page(request: Request, forgotten: str = ""):
        return render(request, forgotten=forgotten)

    VIEWS = ("feed", "lanes", "indicators")
    PAGE, FEW_TESTS, INDICATOR_PAGE = 120, 40, 60

    @app.get("/", response_class=HTMLResponse)
    def timeline_page(request: Request, view: str = "feed", year: int | None = None, doc_type: str = "",
                      material: str = "", skip: int = 0, undated: bool = False, all_tests: bool = False,
                      paperwork: bool = False, test: str = ""):  # fmt: skip
        """The archive by its own dates. Three views of the same documents."""
        context = {"current": "timeline", "view": view if view in VIEWS else "feed", "year": year,
                   "doc_type": doc_type, "material": material, "query": "", "skip": max(0, skip),
                   "undated": undated, "all_tests": all_tests, "paperwork": paperwork, "test": test}  # fmt: skip
        try:
            connection = open_index(registry.data_dir, _showing(registry))
        except IndexMissing:
            return templates.TemplateResponse(request, "timeline.html", {**context, "missing": True})
        with closing(connection):
            since, until = (f"{year}-01-01", f"{year}-12-31") if year else (None, None)
            # The year strip of the feed view counts the documents of the type that is chosen —
            # that is what it is for. The other two views draw their own things against an axis,
            # and an axis counted over one set while the points are drawn from another puts those
            # points outside it: a type carried here from the feed view built the axis out of that
            # type's years and then drew every type on it, so eleven points of forty stood from
            # -31% to 107% of the width. Ten of them were off the left of a phone's screen, and
            # the rest stood on the wrong year, which is a page stating a date that is not true.
            showing = context["view"]
            context["years"] = query_index.years(connection, doc_type or None if showing == "feed" else None)
            context["overview"] = query_index.overview(connection)
            context["undated_count"] = query_index.count_documents(connection, undated=True)
            if context["view"] == "lanes":
                # One set: the filters that are in force narrow the documents, and the axis is
                # then the span of the documents that are actually drawn.
                context["lanes"] = query_index.lanes(connection, since=since, until=until,
                                                     doc_type=doc_type or None)  # fmt: skip
                drawn = sorted(int(item["date"][:4]) for lane in context["lanes"] for item in lane["documents"])
                if drawn:
                    context["axis"] = {"first": drawn[0], "last": drawn[-1] + 1}
                    # Marks inside the axis and never on its edge: with `last` one year past the
                    # newest document, a mark at `last` stands at the full width and names a year
                    # the page holds nothing of — and a page of a single year was labelled with the
                    # year after it. Where no fifth year falls inside, the span's own first year is
                    # the one mark worth printing.
                    inside = [one for one in range(drawn[0], drawn[-1] + 1) if one % 5 == 0]
                    context["ticks"] = inside or [drawn[0]]
            elif context["view"] == "indicators":
                # One material at a time here too: a row of dots mixing the days a test was
                # measured in blood with the days it was measured in urine reads as one history
                # of one test, and it is two.
                materials = material_tabs(query_index.materials_present(connection))
                if materials and material not in {item["key"] for item in materials}:
                    material = materials[0]["key"]
                context["material"] = material
                context["materials"] = materials
                every = query_index.indicator_timeline(connection, material=material or None, limit=1000)
                if test.strip():
                    # Against the label and against every printed spelling the group holds, folded
                    # on both sides. A label is one language — usually English — and a person
                    # looking for their own result types what their own form printed.
                    wanted = fold(test)
                    spellings = {item.id: item.names for item in indicator_store.load(registry.data_dir)}
                    every = [item for item in every
                             if wanted in fold(item["label"])
                             or any(wanted in fold(name) for name in spellings.get(item["indicator_id"], ()))]  # fmt: skip
                context["series"] = every if all_tests else every[:FEW_TESTS]
                context["series_total"] = len(every)
            else:
                context["documents"] = query_index.timeline(connection, since=since, until=until, undated=undated,
                                                            doc_type=doc_type or None, limit=PAGE, offset=context["skip"],
                                                            with_paperwork=paperwork)  # fmt: skip
                context["total"] = query_index.count_documents(connection, since=since, until=until, undated=undated,
                                                               doc_type=doc_type or None, with_paperwork=paperwork)  # fmt: skip
                # Every tab of the row means "click and see this many", and with a year chosen it
                # did not: the counts were of the whole archive, and the link under each of them
                # carries the year on. A tab read "consultation 3" in a year that holds none, and
                # pressing it gave "Showing 0 of 0" — and then the By type view beside it, which
                # drew nothing at all. Counted here with the year in force, by the same call the
                # page's own footer counts with, so the tab and the page it leads to agree.
                context["type_counts"] = {
                    name: query_index.count_documents(connection, since=since, until=until, doc_type=name)
                    for name in context["overview"]["types"]
                }
                # What the Records tab shows if it is pressed, so the row of tabs adds up to the
                # archive instead of leaving a person to guess what the difference was.
                context["records_count"] = query_index.count_documents(connection, since=since, until=until,
                                                                       with_paperwork=False)  # fmt: skip
                context["paperwork_count"] = query_index.count_documents(connection, since=since,
                                                                         until=until) - context["records_count"]  # fmt: skip
            return templates.TemplateResponse(request, "timeline.html", context)

    @app.get("/progress")
    def progress():
        """Step bars only, polled by the status page instead of reloading it."""
        view = build_view(registry.list(), jobs, showing=_showing(registry))
        rows = [{"id": row["id"], "steps": row["steps"]} for row in view["rows"]]
        return {"any_running": view["any_running"], "rows": rows}

    @app.post("/sources")
    def add_source(request: Request, path: str = Form(""), owner: str = Form("")):
        # Whose records these are is not decoration: every page carries the name and every answer
        # the tools give says it. An archive added without one reads as nobody's, and the reading
        # starts the moment it is added, so it is asked for before anything begins.
        if not owner.strip():
            return render(request, error="Say whose archive this is. The name is on every page and in every answer.",
                          form_path=path, form_owner=owner, status_code=400)  # fmt: skip
        try:
            source = registry.add(path, owner)
        except SourceError as exc:
            return render(request, error=str(exc), form_path=path, form_owner=owner, status_code=400)
        if len(registry.list()) == 1:
            registry.set_active(source.id)
        jobs.start(source)
        return RedirectResponse("/status", status_code=303)

    @app.post("/owner")
    def choose_owner(request: Request, source: str = Form(""), back: str = Form("")):
        """Show another owner's archive, without leaving the page the question was asked on.

        Each archive keeps its own index, so the same page simply answers for somebody else —
        and where they have nothing, it says so where it stands rather than sending a person
        back to the timeline to find their way again.
        """
        registry.set_active(source)
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
        registry.set_owner(source_id, owner)
        return RedirectResponse("/status", status_code=303)

    @app.post("/sources/{source_id}/forget")
    def forget_source(request: Request, source_id: str, understood: str = Form("")):
        """Read this archive again from nothing. The folder stays; the reading is put aside."""
        if understood != "yes":
            return RedirectResponse("/status", status_code=303)
        # A run writing into the folder we are about to move would carry on writing into nowhere.
        # Every lock in the folder, not a list of three by name: the search for dates and the
        # checks write here too and were not among the three, so a run of either was moved out
        # from under itself.
        output = source_output_dir(registry.data_dir, source_id)
        held = [lock for lock in sorted(output.glob("*.lock")) if holder(lock)]
        if update_running(registry.data_dir) or held:
            # Which lock, named. "Wait for it to finish" was the whole of this answer, and over a
            # lock left behind by a run that had died it was advice to wait for ever — under the
            # one button that would have put the archive back in order.
            error = "Something is reading this archive right now. Wait for it to finish."
            if held and not update_running(registry.data_dir):
                error += (" What holds it is the lock "
                          + ", ".join(str(lock.relative_to(registry.data_dir)) for lock in held)
                          + ". If nothing is running — the machine was restarted, or the run died — that "
                          "file is left over, and deleting it lets this archive be read again. A lock "
                          f"older than {ABANDONED_AFTER_HOURS} hours is ignored by itself.")
            return render(request, error=error, status_code=409)
        aside = registry.forget(source_id)
        where = f"?forgotten={quote(str(aside))}" if aside else "?forgotten=nothing"
        return RedirectResponse(f"/status{where}", status_code=303)

    @app.post("/owners/{source_id}/remove")
    def remove_owner(request: Request, source_id: str):
        """Take an archive off the list. What was read from it stays on disk, as does the folder."""
        going = registry.remove(source_id)
        if going and going.active and registry.list():
            registry.set_active(registry.list()[0].id)
        return RedirectResponse("/status", status_code=303)

    def consent_context(error: str | None = None) -> dict:
        """What a run would send — which is every archive on this server, not only the open one.

        Agreeing is for the instance, once, and the reading it allows walks every archive here.
        A screen that counted the pages of the archive being looked at named a fraction of what
        leaves the machine, and named one person while three people's pages went.
        """
        pages = files = 0
        whose = []
        for source in registry.list():
            inventory = jobs.records_path(source.id)
            if not inventory.exists():
                continue
            refs = all_refs(list(read_records(inventory)))
            if refs:
                whose.append(source.whose)
            pages += len(refs)
            files += len({ref.file_sha256 for ref in refs})
        showing = registry.active()
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
        by_id = {source.id: source.whose for source in registry.list()}
        return {"consented": consented, "error": error, "pages": pages, "files": files,
                "whose": showing.whose if showing else "", "archives": whose,
                "added_since": [by_id.get(source_id, source_id) for source_id in added_since],
                "engine": engines.chosen_engine(registry.data_dir)}  # fmt: skip

    @app.get("/consent", response_class=HTMLResponse)
    def consent_page(request: Request):
        return templates.TemplateResponse(request, "consent.html", consent_context())

    @app.post("/consent")
    def confirm_consent(request: Request, understood: str = Form(""), action: str = Form("on")):
        # Taken back by one press, as it was given by one. There was no way at all before this —
        # not a button, not a command, not a line of documentation, only editing consent.json by
        # hand — while the button that gives it is called "Turn on model processing" and a section
        # headed "Your control" said only that nothing is sent before it is pressed. With update in
        # a crontab, that is the difference between "it no longer sends" and "it sends every night".
        if action == "off":
            withdraw_consent(registry.data_dir, engines.engine_name(registry.data_dir))
            return RedirectResponse("/consent", status_code=303)
        if understood != "yes":
            context = consent_context(error="Tick the box to confirm.")
            return templates.TemplateResponse(request, "consent.html", context, status_code=400)
        record_consent(registry.data_dir, engines.engine_name(registry.data_dir))
        return RedirectResponse("/", status_code=303)

    @app.get("/tests/{indicator_id}", response_class=HTMLResponse)
    def test_series(request: Request, indicator_id: str, material: str = ""):
        """One test over the years, one material at a time.

        There is no view of every material at once. The same printed name means a different
        measurement in blood and in urine, and a page holding both would be a page of two
        different tests with no way to tell which number is which. So a material is always
        chosen, and where the form said nothing, "not said" is its own answer rather than a
        guess folded in with blood.
        """
        context = {"current": "timeline", "indicator_id": indicator_id, "query": ""}
        try:
            connection = open_index(registry.data_dir, _showing(registry))
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

    @app.post("/tests/{indicator_id}/material")
    def settle_the_material(request: Request, indicator_id: str, material: str = Form("")):
        """Say what these were measured in, for every value of this test that has no answer.

        One press for a page of them, because that is how they arrive: a form holding two specimens
        leaves its whole panel without a label, and settling twelve values one card at a time is
        twelve visits to say one thing. It is written as what it is — a person's own correction, one
        line per value, in the file beside their archive — so it outlives every later reading, the
        index takes it, and the page marks those values as set by hand rather than printed.

        Only the values nobody has corrected yet. A line that already carries a correction is keyed
        by what the model printed, and the index shows it as the person left it, so the two cannot
        be matched from here without guessing; those are said out loud and settled on their card.
        """
        source = registry.active()
        if source is None:
            return _not_here(request, "That is not an archive this server holds.", "/status", "Archive status")
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
                    s: str = ""):  # fmt: skip
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
            connection = open_index(registry.data_dir, _showing(registry))
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
            context["tests"] = query_index.indicators_matching(connection, q) if asked else []
            # And, where nothing at all matched, what there is instead: a person who typed the word
            # people use for a thing rather than the word a laboratory prints was told "Nothing
            # matched. Try a shorter word, or another language", did both, and was told it again.
            # Then they decide the archive does not hold it and take the box of paper to the doctor.
            context["nothing_matched"] = bool(asked) and not context["documents"] and not context["names"] \
                and not context["tests"]  # fmt: skip
            context["tests_in_all"] = query_index.count_indicators(connection) if context["nothing_matched"] else 0
            return templates.TemplateResponse(request, "search.html", context)

    @app.get("/documents", response_class=HTMLResponse)
    def documents(request: Request):
        # The archive that is open, and no other. These pages carry one person's name at the top
        # and listing everybody's under it is how one archive is read as another's.
        sources = [
            view
            for source in _open_archives(registry)
            if (view := source_documents(source, jobs.records_path(source.id).parent)) is not None
        ]
        legend = [{"label": f"{round(share * 100)}%", **reading_colour(share)} for share in (0, 0.5, 0.75, 0.9, 1)]
        return templates.TemplateResponse(request, "documents.html", {"sources": sources, "legend": legend})

    @app.get("/documents/{source_id}/{sha256}/{first_page}", response_class=HTMLResponse)
    def card(request: Request, source_id: str, sha256: str, first_page: int):
        source = _the_open_archive(source_id)
        view = document_card(source, jobs.records_path(source_id).parent, sha256, first_page) if source else None
        if view is None:
            return _not_here(request, "No document of this archive is at that address.",
                                     "/documents", "The documents")  # fmt: skip
        return templates.TemplateResponse(
            request, "card.html", {"card": view, "materials_to_choose": MATERIALS_TO_CHOOSE}
        )

    @app.post("/documents/{source_id}/{sha256}/{first_page}/date")
    def set_date(request: Request, source_id: str, sha256: str, first_page: int, value: str = Form("")):
        source = _the_open_archive(source_id)
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
            return refused(what="That is not a date this page can read. A date is written as 2019-07-08.")
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
                   settles: str = Form(""), attaches: str = Form("document"), about: str = Form("")):  # fmt: skip
        """A rule of this archive's own: a kind that already exists, and words of a person's own.

        No code is written anywhere. The kinds are the ones in the repository under tests, which
        is the same boundary that keeps a rule file from being a program.
        """
        made, wrong = rules.write_one(registry.data_dir,
                                      {"kind": kind, "name": name, "summary": summary,
                                       "settles": settles, "attaches": attaches}, about, kinds.KINDS)  # fmt: skip
        if wrong:
            return _settings_page(request, tab="rules", trouble=wrong)
        return RedirectResponse(
            f"/settings?tab=rules&saved={_remember_saved(f'the rule {made}', '')}#{made}", status_code=303)  # fmt: skip

    @app.post("/review/{source_id}/judge")
    def judge_finding(request: Request, source_id: str, rule: str = Form(""), sha256: str = Form(""),
                      pages: str = Form(""), verdict: str = Form("")):  # fmt: skip
        """A person's word about one finding: that it was real, or that it was noise.

        It marks and does not hide. Hiding what somebody called noise is the obvious next step
        and it is wrong: one mistaken click would lose a real finding with nothing to show it.
        """
        source = _the_open_archive(source_id)
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

    def _spelling(folded: str, printed: dict) -> dict:
        found = printed.get(folded)
        if found:
            return {"folded": folded, **found}
        return {"folded": folded, "name": folded, "times": 0, "units": [], "elsewhere": True}

    @app.get("/indicators", response_class=HTMLResponse)
    def indicators_page(request: Request, status: str = "all", find: str = "", show: str = "all",
                        skip: int = 0, trouble: str = ""):  # fmt: skip
        trouble = just_saved.pop(trouble, (0.0, "", ""))[2] if trouble else ""
        # A status or a view that is none of the ones this page offers would silently empty it,
        # and an archive drawn with none of its vocabulary reads as an archive that lost it.
        # Anything unrecognised means no filter at all, the way an unknown view does elsewhere.
        status = status if status in INDICATOR_STATUSES else "all"
        show = show if show in INDICATOR_VIEWS else "all"
        context = {"current": "indicators", "status": status, "find": find, "show": show,
                   "query": "", "trouble": trouble}  # fmt: skip
        try:
            connection = open_index(registry.data_dir, _showing(registry))
        except IndexMissing:
            return templates.TemplateResponse(request, "indicators.html", {**context, "missing": True})
        try:
            printed = {item["folded"]: item for item in indicator_store.printed_names(connection)}
            materials = {
                item["id"]: [name for name in item["materials"] if name]
                for item in query_index.indicator_list(connection, status=None)
            }
        finally:
            connection.close()
        wanted = fold(find)
        assigned = indicator_store.assigned_names(registry.data_dir)
        # What a second reader said about each group. Agreement is quiet; a disagreement is the
        # only thing here that asks for a person's time.
        checks = load_checks(registry.data_dir)
        coverage = indicator_store.coverage(registry.data_dir, list(printed.values()))
        labels = {item.id: item.label for item in indicator_store.load(registry.data_dir)}
        rows = []
        for indicator in indicator_store.load(registry.data_dir):
            if status != "all" and indicator.status != status:
                continue
            check = checks.get(indicator.id)
            if show == "to_review" and indicator.reviewed and not indicator.proposed_names:
                continue
            if show == "disagreed" and (check is None or check.get("agrees")):
                continue
            # The names of an indicator are kept in their search form, with accents and the
            # Ukrainian and Russian letter pairs already folded; what was typed has to be folded
            # the same way or most printed names in this archive match nothing. The page says
            # above the results that they are matched as one.
            if wanted and wanted not in fold(indicator.label) and not any(wanted in fold(name) for name in indicator.names + indicator.proposed_names):
                continue
            rows.append({
                "indicator": indicator,
                "materials": materials.get(indicator.id, []),
                # Not "values": every dict has a .values method, and a template asking for
                # row.values is handed the method rather than the number.
                "values_count": sum(printed.get(name, {}).get("times", 0) for name in indicator.names),
                # A spelling the open archive has never printed has no printed form to show:
                # what is left is the folded key, which is lower case with the letters of the two
                # alphabets merged ("леикоцити"). Shown as it is, it reads as a misspelling of a
                # name; it is marked instead, and the mark says where it came from.
                "spellings": [_spelling(name, printed) for name in sorted(indicator.names)],
                "proposed": [_spelling(name, printed) for name in sorted(indicator.proposed_names)],
                "related": [{**item, "in_label": labels.get(item["indicator"])} for item in coverage.get(indicator.id, [])][:12],
                "check": check,
            })  # fmt: skip
        waiting = [item for folded, item in printed.items() if folded not in assigned]
        # 507 groups with every spelling under each is megabytes of page: a phone should not have
        # to carry the whole archive's vocabulary to look at sixty groups of it.
        ordered = sorted(rows, key=lambda row: (-row["values_count"], row["indicator"].label.casefold()))
        skip = max(0, min(skip, max(len(ordered) - 1, 0)))
        return templates.TemplateResponse(
            request,
            "indicators.html",
            {
                # Built on the context made at the top, which carries `trouble`. Written out fresh
                # here, the one message this page exists to show — that the index could not be
                # built, so these numbers answer the old question — reached nothing at all.
                **context,
                "rows": ordered[skip : skip + INDICATOR_PAGE],
                "rows_total": len(ordered),
                "skip": skip,
                "page_size": INDICATOR_PAGE,
                "waiting": sorted(waiting, key=lambda item: -item["times"])[:200],
                "checked": len(checks),
                "disagreed": sum(1 for item in checks.values() if not item.get("agrees")),
                "waiting_total": len(waiting),
                "printed_total": len(printed),
                "to_review": sum(1 for item in indicator_store.load(registry.data_dir) if not item.reviewed or item.proposed_names),
                "related_loose": sum(1 for items in coverage.values() for item in items if item["indicator"] is None),
                "all_indicators": sorted(indicator_store.load(registry.data_dir), key=lambda item: item.label.casefold()),
            },
        )

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
    ):  # fmt: skip
        data_dir = registry.data_dir
        changed = True
        if action == "save":
            try:
                indicator_store.upsert(data_dir, indicator_id or None, label, names.splitlines(), status)
            except ValueError as problem:
                # Back to the page, with the reason on it. This page is five hundred groups of the
                # vocabulary, and a person who cleared the label field and pressed Save lost the
                # whole of it for one sentence of plain text on a white background — while the page
                # already had a channel for saying exactly this kind of thing and it went unused.
                # The words travel by key rather than in the address, as everything here does.
                return _back_to_the_indicators(str(problem).capitalize() + ".",
                                               {"status": at_status, "find": at_find,
                                                "show": at_show, "skip": at_skip}, indicator_id)  # fmt: skip
        elif action == "delete" and indicator_id:
            indicator_store.remove(data_dir, indicator_id)
        elif action in ("accept", "reject") and indicator_id:
            indicator_store.decide_names(data_dir, indicator_id, [line for line in names.splitlines() if line.strip()], accept=action == "accept")
        elif action == "assign" and indicator_id and spelling:
            indicator_store.add_names(data_dir, indicator_id, [spelling], reviewed=True)
        elif action == "drop" and indicator_id and spelling:
            indicator_store.drop_name(data_dir, indicator_id, spelling)
        elif action == "reviewed" and indicator_id:
            # "I have looked at this group" changes no spelling, so the index has nothing to learn
            # from it. Rebuilding every archive for it made working through five hundred groups —
            # which is what this page is for — five hundred full builds, each a hung request.
            indicator_store.mark_reviewed(data_dir, indicator_id)
            changed = False
        else:
            changed = False  # a form that asked for nothing this page does is not a reason to build
        # Which spellings are one test decides the indicator of every value in the index, so a
        # decision here is not a decision about a page: it is built in, at once. Seconds, no
        # model, nothing sent. Left out, the page a person went to look at was the page they had
        # just changed nothing on, and they agreed the same spelling again.
        # A build that failed leaves the page showing the old answer to a question that has changed,
        # and saying nothing is how a person comes to trust a number that is stale.
        return _back_to_the_indicators(
            _rebuild_index() if changed else None,
            {"status": at_status, "find": at_find, "show": at_show, "skip": at_skip},
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
    def settings_page(request: Request, saved: str = "", tab: str = ""):
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
        return _settings_page(request, bool(said), trouble, tab, stored=when_stored)

    def _settings_page(request: Request, saved: bool = False, trouble: str = "", tab: str = "",
                       waiting: dict | None = None, trying: tuple | None = None,
                       stored: str = "", kept: dict | None = None):  # fmt: skip
        """The page: for a visit, for a change held back for asking, or for a threshold tried out."""
        # The tab is a radio button and the panels are drawn by CSS from which one is checked, so
        # a name that is none of the four leaves every panel hidden and the page empty. An
        # unknown tab is the first tab, the way an unknown view is on the timeline.
        tab = tab if tab in SETTINGS_TABS else SETTINGS_TABS[0]
        waiting = waiting or {}
        # Worked out once for the whole page. Asked for per rule, this read the index, ran every
        # rule of the search and re-read the settings nineteen times over, and the page took four
        # seconds to open.
        loaded = rules.load(registry.data_dir)
        switches = {rule.id: rule_on(registry.data_dir, rule) for rule in loaded}
        chosen = {rule.id: rule_settings(registry.data_dir, rule) for rule in loaded}
        counts = _tally(loaded, {rule for rule, on in switches.items() if on})
        tried, asked_for = _trial(loaded, trying)
        context = {
                "current": "settings",
                "enabled": ask_enabled(registry.data_dir),
                "mode": answer_mode(registry.data_dir),
                "model_ready": backend_installed(),
                "rules": [
                    {"id": rule.id, "name": rule.name, "summary": rule.summary, "about": render_markdown(rule.about),
                     "at": rule.at, "cost": rule.cost, "shipped": rule.shipped, "costly": rule.costly,
                     # Where turning it off does more than stop a line being reported, the rule
                     # says so itself and the switch says it too.
                     "switching_off": rule.switching_off,
                     "on": waiting.get(rule.id, switches[rule.id]),
                     "found": counts.get(rule.id, tally.Tally(counted=False)).says,
                     # What this archive's own verdicts say about whether the rule earns its
                     # place. Usually nothing, which is right: it speaks only where a person has
                     # judged enough of its findings for their judgement to mean something.
                     "worth_keeping": counts.get(rule.id, tally.Tally(counted=False)).worth_keeping,
                     # The form is built from what the kind declares, so a name it does not
                     # have cannot be typed and a number cannot be given as a word.
                     "tried": tried if tried and trying and trying[0] == rule.id else None,
                     "knobs": [{"name": name.replace("_", " "),
                                "value": asked_for.get(f"{rule.id}:{name}", chosen[rule.id][name]),
                                "field": f"{rule.id}:{name}", "means": rule.check.means.get(name, ""),
                                "number": isinstance(default, int | float) and not isinstance(default, bool),
                                "default": default}
                               for name, default in rule.settings.items()],  # fmt: skip
                     "tryable": rule.at == kinds.SUSPECTS,
                     "waiting": rule.id in waiting, "turning_on": waiting.get(rule.id)}
                    # By the step that runs them, in the order the program runs its steps: what
                    # turning one on asks of a person is decided by its step, so rules that ask
                    # the same thing stand together.
                    for rule in sorted(loaded, key=lambda rule: (kinds.AT.index(rule.at), rule.name))
                ],
                "rule_problems": loaded.problems,
                # Only the kinds a person can honestly fill in: one that places a value on a
                # scale answers in a shape of its own, and there is nothing here to type for it.
                "kinds": [{"name": name, "about": item.about, "at": item.at, "cost": item.cost,
                           "settings": ", ".join(item.settings) or "none"}
                          for name, item in sorted(kinds.KINDS.items()) if item.does == kinds.MARKS],  # fmt: skip
                "read_materials": trusts_read_materials(registry.data_dir),
                "passes": [
                    {"key": key, "label": item["label"], "about": item["about"],
                     "chosen": model_for(registry.data_dir, key)}
                    for key, item in PASSES.items()
                ],
                "known_models": KNOWN_MODELS,
                "engines": [
                    {"name": item.name, "label": item.label, "about": item.about,
                     "ready": not engines.what_it_needs(item.name, registry.data_dir),
                     "chosen": item.name == engines.chosen_engine(registry.data_dir),
                     "needs_what": engines.what_it_needs(item.name, registry.data_dir)}
                    for item in engines.ENGINES
                ],  # fmt: skip
                "known_names": [name for name, _about in KNOWN_MODELS],
                "read_materials_known": _tables_read(),
                "mcp_lock": mcp_lock_on(registry.data_dir),
                "mcp_lock_scope": mcp_lock_scope(registry.data_dir),
                "mcp_lock_minutes": mcp_lock_minutes(registry.data_dir),
                "mcp_secret": bool(read_lock_secret()),
                "confirmed": has_consent(registry.data_dir, engines.engine_name(registry.data_dir)),
                "saved": saved,
                "stored": stored,
                "trying": bool(trying),
                "tab": tab,
                "waiting": waiting,
                "trouble": trouble,
                # Asked on the way in, not only on the way out. The switches below come from the
                # file, and over a file that cannot be read every one of them is drawn at its
                # default — the answer mode, the materials, the length of the code's window —
                # which a person reads as the truth about their own instance. Worse for the lock:
                # it fails closed on an unreadable file, so it drew as on over an archive whose
                # owner had never turned it on, indistinguishable from their own choice. The only
                # way to learn any of this was to press Save and be refused.
                "settings_unreadable": settings_unreadable(registry.data_dir),
                # The folder this instance keeps its files in, so that the commands this page gives
                # can be copied whole. Every one of them that writes a setting needs to be told
                # which instance, and the page used to print them without it.
                "data_dir": str(registry.data_dir),
        }
        # Trying a threshold draws this page again from the submission it came in, not from
        # storage. Without this, pressing "Try it" on the Rules tab silently put back whatever a
        # person had just changed on the other three — a switch, an answer mode, a model — and
        # said nothing about it. Nothing is stored either way: trying is not saving.
        if kept:
            was_drawn = set(kept["shown"])
            if "ask_page" in was_drawn:
                context["enabled"] = kept["ask_page"] == "on"
            if "read_materials" in was_drawn:
                context["read_materials"] = kept["read_materials"] == "on"
            if "mcp_lock" in was_drawn:
                context["mcp_lock"] = kept["mcp_lock"] == "on"
            if kept["mode"] in ANSWER_MODES:
                context["mode"] = kept["mode"]
            context["mcp_lock_scope"] = kept["mcp_lock_scope"]
            context["mcp_lock_minutes"] = kept["mcp_lock_minutes"]
            for item in context["engines"]:
                if any(kept["engine"] == known.name for known in engines.ENGINES):
                    item["chosen"] = item["name"] == kept["engine"]
            for item in context["passes"]:
                item["chosen"] = kept["models"].get(item["key"]) or item["chosen"]
            for rule in context["rules"]:
                if rule["id"] in was_drawn:
                    rule["on"] = rule["id"] in kept["rules_on"]
        return templates.TemplateResponse(request, "settings.html", context)

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
                      try_rule: str = Form(""), tab: str = Form("")):  # fmt: skip
        # Which settings a rule has is the kind's business and changes with it, so the knobs
        # cannot be declared one by one here. They travel as two lists in the order the page
        # wrote them: what each one is, and what was typed into it.
        form = dict(zip(knob_name, knob_value, strict=False))
        # Nothing on this page can be stored while the file it is all stored in cannot be read:
        # every write builds the whole file from what is there, so one saved setting would take
        # the place of all the rest. Said on the page rather than raised at it.
        if settings_unreadable(registry.data_dir):
            return _settings_page(request, tab=tab, trouble=(
                "The settings file of this instance is there and cannot be read, so nothing was "
                "changed. Repair data/settings.json, or move it aside to start from the defaults. "
                "Until then the lock over the network stays on, if a code was ever set up here."
            ))  # fmt: skip
        # Trying is not saving. Nothing at all is stored on this path: a person turning a
        # threshold over in their hands has not decided anything yet.
        if try_rule:
            return _settings_page(request, tab="rules", trying=(try_rule, form), kept={
                "shown": shown, "ask_page": ask_page, "engine": engine, "mode": mode,
                "models": {"first": model_first, "strong": model_strong, "second_reader": model_second_reader},
                "read_materials": read_materials, "mcp_lock": mcp_lock,
                "mcp_lock_scope": mcp_lock_scope_choice, "mcp_lock_minutes": mcp_lock_minutes_choice,
                "rules_on": set(rule_on_ids),
            })  # fmt: skip
        # What was in fact stored, in a person's words. "Saved." on its own, over a page that can
        # store an engine, three models, an answer mode, nineteen switches, their thresholds and
        # the lock in one press, says that something happened and not what.
        stored: list[str] = []
        if "ask_page" in shown and ask_enabled(registry.data_dir) != (ask_page == "on"):
            set_ask_enabled(registry.data_dir, ask_page == "on")
            stored.append("answering questions " + ("on" if ask_page == "on" else "off"))
        # An engine that is not built, or not known, is simply not stored: the page offers it as a
        # thing that is coming, and a form can always be made to say something the page did not.
        with suppress(ValueError):
            if engine and engine != engines.chosen_engine(registry.data_dir):
                set_engine(registry.data_dir, engine)
                stored.append(f"the engine — {engine}")
        # Checkboxes only say what is ticked, so what is not in the list is what was turned off.
        # A rule whose step reads documents again is not stored on the strength of a click: it
        # is held back, said out loud with what it will cost, and stored on the second answer.
        # A checkbox that is not ticked is not sent at all, so a form arriving without one is
        # indistinguishable from a form that turned it off. The page says what it drew, and only
        # those are changed — otherwise a half-sent form silently turns off everything at once,
        # and for the switch that reads materials that also means rebuilding the index.
        waiting, changed = {}, set()
        thresholds, switched = 0, 0
        for rule in rules.load(registry.data_dir):
            if rule.id not in shown:
                continue
            # The thresholds are saved for every rule, switched on or not: turning one on next
            # month should find what somebody set for it, not what it shipped with. Saved only
            # when they differ, so that an untouched page rewrites nothing.
            given = {name: form[f"{rule.id}:{name}"] for name in rule.settings
                     if form.get(f"{rule.id}:{name}") not in (None, "")}  # fmt: skip
            now = {name: str(value) for name, value in rule_settings(registry.data_dir, rule).items() if name in given}
            if given and given != now:
                with suppress(ValueError):
                    set_rule_settings(registry.data_dir, rule, given)
                    changed.add(rule.at)
                    thresholds += 1
            wanted = rule.id in rule_on_ids
            if wanted == rule_on(registry.data_dir, rule):
                continue
            if rule.costly and rule.id not in confirmed_rules:
                waiting[rule.id] = wanted
                continue
            set_rule_on(registry.data_dir, rule.id, wanted)
            changed.add(rule.at)
            switched += 1
        if thresholds:
            stored.append(f"thresholds of {thresholds} rule" + ("s" if thresholds != 1 else ""))
        if switched:
            stored.append(f"{switched} rule" + ("s" if switched != 1 else "") + " switched")
        if "models" in shown:
            was_models = {key: model_for(registry.data_dir, key) for key in PASSES}
            set_chosen_models(registry.data_dir, {
                "first": model_first, "strong": model_strong, "second_reader": model_second_reader,
            })  # fmt: skip
            if {key: model_for(registry.data_dir, key) for key in PASSES} != was_models:
                stored.append("the models")
        # This one changes what is in the index, not only how a page draws it, so the index is
        # built again — and only when the answer actually changed.
        trouble = None
        build_again = False
        if "read_materials" in shown and trusts_read_materials(registry.data_dir) != (read_materials == "on"):
            set_trusts_read_materials(registry.data_dir, read_materials == "on")
            stored.append("reading the material from the table heading "
                          + ("on" if read_materials == "on" else "off")
                          + ", and the index built again")
            build_again = True
        # A rule turned off has to stop counting now, not at the next run of the checks. The
        # findings of an archive are a file on disk; leaving it as it was would show a person
        # findings from a rule they have just switched off, with no way to tell why they persist.
        if kinds.VALIDATE in changed:
            trouble = _check_every_archive() or trouble
            # And then built in. The findings of a check live in the index as well as in the file
            # of findings, and the tools answer over the network from the index: a rule switched
            # off cleared the page and went on being handed to a model as something to look at,
            # with nothing on either side to say why.
            build_again = True
            stored.append("every archive checked again and built in")
        # Once for the whole press, however many of the things above asked for it. Two of them in
        # one press built every archive's index twice, and the second build's failure quietly
        # replaced the first one's.
        if build_again:
            trouble = _rebuild_index() or trouble
        if "mcp_lock" in shown and mcp_lock_on(registry.data_dir) != (mcp_lock == "on"):
            set_mcp_lock(registry.data_dir, mcp_lock == "on" and bool(read_lock_secret()))
            stored.append("the lock over the network " + ("on" if mcp_lock_on(registry.data_dir) else "off"))
        with suppress(ValueError):
            if mcp_lock_scope_choice != mcp_lock_scope(registry.data_dir):
                set_mcp_lock_scope(registry.data_dir, mcp_lock_scope_choice)
                stored.append("what a code opens")
        with suppress(ValueError):
            if mcp_lock_minutes_choice != mcp_lock_minutes(registry.data_dir):
                set_mcp_lock_minutes(registry.data_dir, mcp_lock_minutes_choice)
                stored.append("how long a code lasts")
        if mode in ANSWER_MODES and mode != answer_mode(registry.data_dir):
            set_answer_mode(registry.data_dir, mode)
            stored.append("what may be said about a value — " + ANSWER_MODE_NAMES[mode])
        said = ", ".join(stored)
        if waiting:
            # Everything else is already stored; only the held-back ones come back as a question,
            # shown the way they were asked for so that answering yes is one step and not two.
            return _settings_page(request, saved=True, trouble=trouble or "", tab="rules",
                                  waiting=waiting, stored=said)  # fmt: skip
        return RedirectResponse(f"/settings?saved={_remember_saved(said, trouble or '')}&tab={quote(tab)}",
                                status_code=303)  # fmt: skip

    def _check_every_archive() -> str:
        """Every archive checked again with the rules as they now stand. No model, seconds."""
        for source in registry.list():
            try:
                validate_source(source_output_dir(registry.data_dir, source.id), Path(source.path))
            except Exception as exc:  # the type only: a message can quote a document
                return f"The archive could not be checked again: {type(exc).__name__}. Run {CLI} validate."
        return ""

    def _trial(loaded, trying: tuple | None):
        """What one rule would find with the thresholds just typed, and those thresholds back.

        The numbers a person typed are handed back to the page whether the trial worked or not:
        a form that forgot what was in it the moment you asked a question of it is worse than no
        question at all.
        """
        if not trying:
            return None, {}
        rule_id, typed = trying
        rule = loaded.get(rule_id)
        if rule is None:
            return None, typed
        wanted = {name: typed[f"{rule_id}:{name}"] for name in rule.settings if f"{rule_id}:{name}" in typed}
        showing = registry.active()
        try:
            asked = {name: type(rule.settings[name])(value) for name, value in wanted.items()}
            return tally.trial(registry.data_dir, showing.id if showing else "", rule, asked), typed
        except (TypeError, ValueError):
            return {"trouble": "Those are not numbers this rule can use."}, typed
        except Exception:  # a half-built archive is not a reason for the page to fail
            return {"trouble": "This archive could not be read just now."}, typed

    def _tally(loaded, on: set[str]) -> dict:
        """What every rule has found on the archive being shown. A fifth of a second, so it is
        worked out when the page is drawn rather than kept and left to go stale."""
        showing = registry.active()
        try:
            return tally.counts(registry.data_dir, showing.id if showing else "", loaded, on)
        except Exception:  # a half-built archive is not a reason for the settings page to fail
            return {}

    def _tables_read() -> int:
        """How many tables a model has already been asked about, in the archive that is open.

        Not every archive here: what it is shown beside is what this archive's own reading has
        settled, and a total of several people's would be a number about nobody.
        """
        from epicrisis.material_reading import answered

        return sum(len(answered(jobs.records_path(source.id).parent)) for source in _open_archives(registry))

    def _rebuild_index() -> str | None:
        """Build every archive's index again. The first failure is returned, and shown."""
        from epicrisis.index.build import build_index

        for source in registry.list():
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
    def ask_page(request: Request, chat_id: str | None = None):
        # A chat is about one person's archive. Asked for from another, it is not found — the
        # same answer as one that never existed, because which chats exist is not this page's
        # to tell.
        chat = load_chat(registry.data_dir, chat_id, registry.active()) if chat_id else None
        if chat_id and chat is None:
            return _not_here(request, "No conversation of this archive is at that address.", "/ask", "Ask")
        return templates.TemplateResponse(
            request,
            "ask.html",
            {
                "current": "ask",
                "chats": list_chats(registry.data_dir, registry.active()),
                "chat": chat,
                "enabled": ask_enabled(registry.data_dir),
                "mode": answer_mode(registry.data_dir),
                "carried": carried_questions(chat) if chat else 0,
                "confirmed": has_consent(registry.data_dir, engines.engine_name(registry.data_dir)),
            },
        )

    @app.post("/ask")
    @app.post("/ask/{chat_id}")
    def ask_question(request: Request, chat_id: str | None = None, question: str = Form(""), continue_chat: str = Form("", alias="continue")):
        if not (ask_enabled(registry.data_dir) and has_consent(registry.data_dir, engines.engine_name(registry.data_dir))):
            # A page, and the one place this is changed. It was a sentence of plain text on a white
            # background, which is what this program answers with nowhere else.
            return _refused(request, "Asking is turned off",
                            "Answering questions is turned off for this instance, or sending pages to "
                            "a model has not been agreed to. Both are on the Settings page, and what "
                            "would be sent is on Model processing.",
                            "/settings", "Settings", 403)  # fmt: skip
        # Unchecked box: the question starts its own chat, so nothing said earlier reaches the model.
        open_archive = registry.active()
        chat = (load_chat(registry.data_dir, chat_id, open_archive) if chat_id and continue_chat
                else new_chat(registry.data_dir, open_archive))  # fmt: skip
        if chat is None:
            return _not_here(request, "No conversation of this archive is at that address.", "/ask", "Ask")
        if background_jobs:
            ask(registry.data_dir, chat["id"], question)
        return RedirectResponse(f"/ask/{chat['id']}", status_code=303)

    @app.post("/ask/{chat_id}/delete")
    def remove_chat(request: Request, chat_id: str):
        if load_chat(registry.data_dir, chat_id, registry.active()) is None:
            return _not_here(request, "No conversation of this archive is at that address.", "/ask", "Ask")
        if not delete_chat(registry.data_dir, chat_id):
            return _not_here(request, "No conversation of this archive is at that address.", "/ask", "Ask")
        return RedirectResponse("/ask", status_code=303)

    @app.get("/ask/{chat_id}/state")
    def ask_state(chat_id: str):
        chat = load_chat(registry.data_dir, chat_id, registry.active())
        if chat is None:
            return Response("Unknown chat.", status_code=404)
        return JSONResponse({"running": chat_running(chat), "messages": chat["messages"]})

    @app.get("/review", response_class=HTMLResponse)
    def review(request: Request, copies: str = "", check: str = ""):
        sources = []
        for source in _open_archives(registry):
            view = review_view(source, jobs.records_path(source.id).parent)
            if view is not None:
                sources.append(_from_the_index(view, source))
        return templates.TemplateResponse(
            request, "review.html", {"sources": sources, "current": "review",
                                     "open_copies": bool(copies), "open_check": check}  # fmt: skip
        )

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
        return {**view, "copy_groups": groups, "checks": checks}

    @app.post("/review/{source_id}/{sha256}/{first_page}/copy")
    def choose_copy(request: Request, source_id: str, sha256: str, first_page: int):
        """This one of the copies is the one that answers."""
        source = _the_open_archive(source_id)
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
    def run_validation(request: Request, source_id: str):
        # The checks read one archive's transcriptions and write into its own folder, so they
        # run for the archive that is open and for no other. See _the_open_archive.
        source = _the_open_archive(source_id)
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
    ):  # fmt: skip
        source = _the_open_archive(source_id)
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

    def _the_page(source_id: str, sha256: str, page: int):
        """The archive, the file's record and the one page of it named in an address."""
        source = _the_open_archive(source_id)
        inventory = jobs.records_path(source_id)
        if source is None or not inventory.exists():
            return None, None, None
        record = next((record for record in read_records(inventory) if record.get("sha256") == sha256), None)
        refs = page_refs(record) if record else []
        return source, refs, next((ref for ref in refs if ref.page == page), None)

    @app.get("/sources/{source_id}/files/{sha256}/pages/{page}", response_class=HTMLResponse)
    def page_original(request: Request, source_id: str, sha256: str, page: int):
        """The scan of one page, with enough around it to know what one is looking at.

        This was the image alone, opened in a tab of its own: no page number, no name of the file
        it came from, no way to the next page of the same form and no way back. Checking a
        four-page form against its card meant four tabs and no captions. The image itself is
        still one address of its own, which is what this page draws.
        """
        source, refs, ref = _the_page(source_id, sha256, page)
        if source is None:
            # Not "there is no such archive": the archive is on this list and has simply been
            # switched, which is what the paragraph under this sentence goes on to explain. A
            # person who had this very page open a minute ago read the first line as their
            # archive having gone. The card of the same document says it of the address.
            return _not_here(request, "That page is not in the archive that is open.",
                             "/status", "Archive status")  # fmt: skip
        if ref is None:
            return _not_here(request, "No page of this archive is at that address.", "/documents", "The documents")
        numbers = sorted(one.page for one in refs)
        at = numbers.index(page)
        # Which document this page belongs to, so there is a way back to the card it was opened
        # from. A page can belong to none, in a file whose pages were never grouped.
        view = source_documents(source, jobs.records_path(source_id).parent)
        belongs = next((row for group in (view or {}).get("years", []) for row in group["documents"]
                        if row["file"]["sha256"] == sha256 and page in row["pages"]), None)  # fmt: skip
        return templates.TemplateResponse(request, "page.html", {
            "current": "documents", "source_id": source_id, "sha256": sha256, "page": page,
            "path": Path(record_path(source, sha256) or "").name,
            "pages": numbers,
            "previous": numbers[at - 1] if at else None,
            "next": numbers[at + 1] if at + 1 < len(numbers) else None,
            "document": belongs,
            # Why this scan cannot be shown, where it cannot, in words on the page. It used to ask
            # one question — is the folder there — and say a sentence for that and nothing at all
            # for the likelier trouble: one file changed under the archive, rescanned or resaved or
            # damaged, where the page stayed whole with a broken image in the middle of it. Over the
            # one promise this program makes about every value it shows: that the page it was read
            # from is one click away.
            "cannot_be_shown": cannot_be_read(ref, Path(source.path)),
        })  # fmt: skip

    def record_path(source: Source, sha256: str) -> str:
        """The name of the file a page came from. The folder it sits in is not shown anywhere."""
        record = next((one for one in read_records(jobs.records_path(source.id)) if one.get("sha256") == sha256), None)
        return (record or {}).get("path", "")

    @app.get("/sources/{source_id}/files/{sha256}/pages/{page}/image")
    def page_image(request: Request, source_id: str, sha256: str, page: int):
        """The scan itself, one page of it, drawn by the page above and by nothing else."""
        source, _refs, ref = _the_page(source_id, sha256, page)
        if source is None:
            # Said of the address and not of the archive, for the reason written over the page above.
            return _not_here(request, "That page is not in the archive that is open.",
                             "/status", "Archive status")  # fmt: skip
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
    def browse(path: str = ""):
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
            listing = list_folder(path, added_paths={source.path for source in registry.list()},
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
    def build_in_what_changed(request: Request, source_id: str):
        """Build this archive's index again, because a person asked for it on the page saying so.

        It happens by itself after a correction. This is for every other way an index comes to be
        older than the files it is built from — a reading run in a terminal, a build that failed, a
        server that was not running when the correction was made — and for a person who would
        rather press the thing than trust that it is happening.
        """
        # One archive's own, and only the one being looked at: the same boundary as the checks and
        # the corrections. See _the_open_archive.
        source = _the_open_archive(source_id)
        if source is None:
            return _not_here(request, "That is not an archive this server holds.", "/status", "Archive status")
        # What went wrong is not carried back in the address: it is kept beside the archive it
        # happened to, and the same line on every page that reports the index being behind reports
        # it. An address travels into a person's history and between their devices.
        building.now(source_id)
        return RedirectResponse(_same_page(request.headers.get("referer", "/"), source_id) or "/", status_code=303)

    @app.post("/sources/{source_id}/inventory")
    def rescan_source(request: Request, source_id: str):
        source = registry.get(source_id)
        if source is None:
            return _not_here(request, "That is not an archive this server holds.", "/status", "Archive status")
        jobs.start(source)
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
