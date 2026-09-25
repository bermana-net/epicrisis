"""Status dashboard: which folders are registered and how far each got through the pipeline.

It shows counts and paths only, never document contents or values.
"""

from contextlib import closing, suppress
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from epicrisis.classify.backend import ClaudeCodeBackend, backend_installed
from epicrisis.classify.pages import PageUnreadable, original_png, page_refs
from epicrisis.classify.report import latest_pages
from epicrisis.classify.run import all_refs, is_running
from epicrisis.extract.run import LOCK_NAME as EXTRACT_LOCK
from epicrisis.extract.run import document_refs, done_keys
from epicrisis.consent import has_consent, record_consent
from epicrisis.corrections import set_document_date, set_primary_copy, set_value
from epicrisis import indicators as indicator_store
from epicrisis.index.build import index_state
from epicrisis.indicator_check import load_checks
from epicrisis import mcp_access
from epicrisis.mcp_lock import read_secret as read_lock_secret
from epicrisis.models import KNOWN_MODELS, PASSES, model_for
from epicrisis import query as query_index
from epicrisis import series
from epicrisis.query import IndexMissing, open_index
from epicrisis.inventory.report import Summary
from epicrisis.records import read_records
from epicrisis.sources import Source, SourceError, SourceRegistry, source_output_dir
from epicrisis.web.browse import BrowseError, list_folder
from epicrisis.web.markdown import render_markdown
from epicrisis.ask import (ANSWER_MODES, answer_mode, ask, ask_enabled, carried_questions, converts_units, delete_chat,
                           places_unit_by_numbers, reads_unit_from_range, set_places_unit_by_numbers,
                           set_reads_unit_from_range,
                           list_chats, load_chat, mcp_lock_minutes, mcp_lock_on, mcp_lock_scope, new_chat,
                           set_answer_mode, set_ask_enabled, set_converts_units, set_mcp_lock, set_mcp_lock_minutes,
                           set_chosen_models, set_trusts_read_materials, trusts_read_materials,
                           set_mcp_lock_scope)
from epicrisis.ask import running as chat_running
from epicrisis.update import start_in_background as start_update
from epicrisis.update import update_running
from epicrisis.validate import validate_source, validation_state
from epicrisis.web.documents import document_card, reading_colour, review_view, source_documents
from epicrisis.web.jobs import InventoryJobs

PIPELINE_STEPS = ["Inventory", "Classify", "Extract", "Validate", "Index"]
LOCAL_HOSTS = ["localhost", "127.0.0.1"]


# The order the material tabs stand in, and the words on them. Blood leads because most of a
# person's results are blood. What the form did not say comes last and stays its own answer: an
# unmarked value is probably blood, and probably is not something this archive says out loud.
MATERIAL_ORDER = ("blood", "urine", "stool", "semen", "swab", "csf", "saliva", "sputum", "none")
# What a person may set by hand on one line, where the form's layout leaves it ambiguous: a
# table with rows of two specimens, a panel headed for one thing and holding a section of
# another. "none" is here too, for a measurement made on the person rather than in a sample.
MATERIALS_TO_CHOOSE = ("blood", "urine", "stool", "semen", "swab", "csf", "saliva", "sputum", "none")
MATERIAL_LABELS = {"none": "Not said"}


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
    templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
    templates.env.filters["thousands"] = lambda number: f"{number:,}"
    templates.env.filters["markdown"] = render_markdown

    # Every page shows whose archive it is, so the header asks for it as it renders.
    templates.env.globals["owners"] = lambda: _owners()
    templates.env.globals["stage"] = lambda: _stage()

    app = FastAPI(title="Epicrisis Companion", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    # Only answer to the local names: blocks DNS-rebinding pages from reading the dashboard.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or LOCAL_HOSTS)

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
        if answer.headers.get("content-type", "").startswith("text/html"):
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
        """How far this instance has got, for the pages that have nothing to show yet.

        A tool with no data should read as new, not as broken, and the answer differs: no archive
        added at all, a folder still being looked through, or documents not yet read by a model.
        """
        # Whether the reading can be started from where a person is standing, and whether it is
        # already going: the one thing to do next should be doable without finding a page first.
        ready_to_start = {
            "consented": has_consent(registry.data_dir, ClaudeCodeBackend.name),
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
        except IndexMissing:
            read = 0
        if read:
            # Documents in the index are what every page needs; how they got there does not matter.
            return {"state": "ready", "whose": active.whose, **ready_to_start}
        status = jobs.status(active.id) or {}
        # "Being looked through" only while something is actually going. A folder that was
        # scanned and then read, whose index is missing or out of date, is not being worked on
        # by anybody, and telling a person to wait for that is telling them to wait for ever.
        scanning = status.get("state") in ("running", "queued", None) and not status.get("finished_at")
        transcribed = (jobs.records_path(active.id).parent / "extracted").is_dir()
        if scanning and not transcribed:
            return {"state": "scanning", "whose": active.whose, **ready_to_start}
        if transcribed:
            return {"state": "unindexed", "whose": active.whose, **ready_to_start}
        return {"state": "unread", "whose": active.whose, **ready_to_start}

    def _owners() -> dict:
        """Who this server holds archives for, and whose is open. Names are shown, ids are not."""
        sources = registry.list()
        active = registry.active()
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
            model_consent=has_consent(registry.data_dir, ClaudeCodeBackend.name),
            host=request.headers.get("host", ""),
            updated=datetime.now().astimezone().strftime("%H:%M %Z"),
            error=error,
            form_path=form_path,
            form_owner=form_owner,
            forgotten=forgotten,
        )
        return templates.TemplateResponse(request, "status.html", context, status_code=status_code)

    @app.get("/status", response_class=HTMLResponse)
    def status_page(request: Request, forgotten: str = ""):
        return render(request, forgotten=forgotten)

    VIEWS = ("feed", "lanes", "indicators")
    PAGE, FEW_TESTS, INDICATOR_PAGE = 120, 40, 60
    EARLIEST_YEAR = 1900

    @app.get("/", response_class=HTMLResponse)
    def timeline_page(request: Request, view: str = "feed", year: int | None = None, doc_type: str = "",
                      material: str = "", skip: int = 0, undated: bool = False, all_tests: bool = False,
                      paperwork: bool = False):  # fmt: skip
        """The archive by its own dates. Three views of the same documents."""
        context = {"current": "timeline", "view": view if view in VIEWS else "feed", "year": year,
                   "doc_type": doc_type, "material": material, "query": "", "skip": max(0, skip),
                   "undated": undated, "all_tests": all_tests, "paperwork": paperwork}  # fmt: skip
        try:
            connection = open_index(registry.data_dir, _showing(registry))
        except IndexMissing:
            return templates.TemplateResponse(request, "timeline.html", {**context, "missing": True})
        with closing(connection):
            since, until = (f"{year}-01-01", f"{year}-12-31") if year else (None, None)
            context["years"] = query_index.years(connection, doc_type or None)
            context["overview"] = query_index.overview(connection)
            context["undated_count"] = query_index.count_documents(connection, undated=True)
            if context["view"] == "lanes":
                context["lanes"] = query_index.lanes(connection)
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
                context["series"] = every if all_tests else every[:FEW_TESTS]
                context["series_total"] = len(every)
            else:
                context["documents"] = query_index.timeline(connection, since=since, until=until, undated=undated,
                                                            doc_type=doc_type or None, limit=PAGE, offset=context["skip"],
                                                            with_paperwork=paperwork)  # fmt: skip
                context["total"] = query_index.count_documents(connection, since=since, until=until, undated=undated,
                                                               doc_type=doc_type or None, with_paperwork=paperwork)  # fmt: skip
                context["paperwork_count"] = sum(context["overview"]["types"].get(kind, 0) for kind in query_index.PAPERWORK)
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
            return f"/{parts[0]}" if parts[0] in ("documents", "review") else "/status"
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
        output = source_output_dir(registry.data_dir, source_id)
        if update_running(registry.data_dir) or is_running(output) or is_running(output, EXTRACT_LOCK):
            return render(request, error="Something is reading this archive right now. Wait for it to finish.",
                          status_code=409)  # fmt: skip
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
        consented = has_consent(registry.data_dir, ClaudeCodeBackend.name)
        return {"consented": consented, "error": error, "pages": pages, "files": files,
                "whose": showing.whose if showing else "", "archives": whose}  # fmt: skip

    @app.get("/consent", response_class=HTMLResponse)
    def consent_page(request: Request):
        return templates.TemplateResponse(request, "consent.html", consent_context())

    @app.post("/consent")
    def confirm_consent(request: Request, understood: str = Form("")):
        if understood != "yes":
            context = consent_context(error="Tick the box to confirm.")
            return templates.TemplateResponse(request, "consent.html", context, status_code=400)
        record_consent(registry.data_dir, ClaudeCodeBackend.name)
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
            every = query_index.values(connection, indicator=indicator_id,
                                       limit=query_index.MAX_SERIES, cap=query_index.MAX_SERIES)  # fmt: skip
            counted: dict[str, int] = {}
            for item in every:
                counted[item["material"] or "none"] = counted.get(item["material"] or "none", 0) + 1
            materials = material_tabs(counted)
            if not every:
                # Switching archive keeps a person on this address, and the archive they moved to
                # may have no values of this test. That is an answer, and it is given here — with
                # the header, the name of the archive and a way on — rather than as a bare line.
                known = next((item for item in query_index.indicator_list(connection, status=None)
                              if item["id"] == indicator_id), None)  # fmt: skip
                if known is None:
                    return Response("Unknown test.", status_code=404)
                return templates.TemplateResponse(
                    request, "series.html",
                    {**context, "label": known["label"], "material": material, "materials": [],
                     "values": [], "charts": [], "span": {}, "none_here": True},
                )  # fmt: skip
            if material not in {item["key"] for item in materials}:
                material = materials[0]["key"]
            values = query_index.values(connection, indicator=indicator_id, material=material,
                                        limit=query_index.MAX_SERIES, cap=query_index.MAX_SERIES)  # fmt: skip
            # What the heading says about this history has to be true of the whole of it, not of
            # the part that fitted: how many values there are, and from when to when.
            total = query_index.count_values(connection, indicator=indicator_id, material=material)
            dated = [series.date_label(item) for item in values if item.get("date")]
            span = {"first": dated[0] if dated else None, "last": dated[-1] if dated else None,
                    "undated": sum(1 for item in values if not item.get("date")),
                    "total": total, "more": total > len(values)}  # fmt: skip
        to_scale = converts_units(registry.data_dir)
        from_range = reads_unit_from_range(registry.data_dir)
        by_numbers = places_unit_by_numbers(registry.data_dir)
        context.update(
            label=label, material=material, materials=materials, to_scale=to_scale, values=values, span=span,
            material_label=next((item["label"] for item in materials if item["key"] == material), material),
            # Where the form printed no material, a model read the table; the page says which
            # values those are rather than showing a reading and a printed word as one thing.
            read_by_model=sum(1 for item in values if item.get("material_source") == "model"),
            charts=series.charts(values, indicator=indicator_id, to_scale=to_scale,
                                 from_range=from_range, by_numbers=by_numbers),
        )  # fmt: skip
        return templates.TemplateResponse(request, "series.html", context)

    @app.get("/search", response_class=HTMLResponse)
    def search_page(request: Request, q: str = "", doc_type: str = "", limit: int = 40):
        """One line over the whole archive: text, titles, institutions and the printed names of values."""
        # One cap, the one the index enforces, so that asking for five does not silently give ten
        # and asking for four hundred does not silently give two hundred.
        limit = max(1, min(limit, query_index.MAX_LIMIT))
        context = {"current": "search", "query": q, "doc_type": doc_type, "limit": limit}
        try:
            connection = open_index(registry.data_dir, _showing(registry))
        except IndexMissing:
            return templates.TemplateResponse(request, "search.html", {**context, "missing": True})
        with closing(connection):
            asked = q.strip()
            context["documents"] = query_index.search(connection, q, limit=limit, doc_type=doc_type or None) if asked else []
            context["total"] = query_index.count_search(connection, q, doc_type=doc_type or None) if asked else 0
            context["names"] = query_index.value_names(connection, q, limit=12) if asked else []
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
            return Response("Unknown document.", status_code=404)
        return templates.TemplateResponse(
            request, "card.html", {"card": view, "materials_to_choose": MATERIALS_TO_CHOOSE}
        )

    @app.post("/documents/{source_id}/{sha256}/{first_page}/date")
    def set_date(request: Request, source_id: str, sha256: str, first_page: int, value: str = Form("")):
        source = _the_open_archive(source_id)
        output = jobs.records_path(source_id).parent
        view = document_card(source, output, sha256, first_page) if source else None
        if view is None:
            return Response("Unknown document.", status_code=404)
        try:
            chosen = date.fromisoformat(value) if value else None
        except ValueError:
            return Response("Not a date.", status_code=400)
        if chosen and chosen > date.today():
            return Response("A document cannot be dated in the future.", status_code=400)
        if chosen and chosen.year < EARLIEST_YEAR:
            return Response(f"A document dated before {EARLIEST_YEAR} is a typing slip, not a record.", status_code=400)
        set_document_date(output, sha256, view["summary"]["pages"], chosen)
        return RedirectResponse(f"/documents/{source_id}/{sha256}/{first_page}", status_code=303)

    def _spelling(folded: str, printed: dict) -> dict:
        found = printed.get(folded)
        if found:
            return {"folded": folded, **found}
        return {"folded": folded, "name": folded, "times": 0, "units": [], "elsewhere": True}

    @app.get("/indicators", response_class=HTMLResponse)
    def indicators_page(request: Request, status: str = "all", find: str = "", show: str = "all", skip: int = 0):
        context = {"current": "indicators", "status": status, "find": find, "show": show, "query": ""}
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
            if find and find.casefold() not in indicator.label.casefold() and not any(find.casefold() in name for name in indicator.names + indicator.proposed_names):
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
                "current": "indicators",
                "rows": ordered[skip : skip + INDICATOR_PAGE],
                "rows_total": len(ordered),
                "skip": skip,
                "page_size": INDICATOR_PAGE,
                "waiting": sorted(waiting, key=lambda item: -item["times"])[:200],
                "checked": len(checks),
                "disagreed": sum(1 for item in checks.values() if not item.get("agrees")),
                "waiting_total": len(waiting),
                "printed_total": len(printed),
                "status": status,
                "find": find,
                "show": show,
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
    ):
        data_dir = registry.data_dir
        if action == "save":
            try:
                indicator_store.upsert(data_dir, indicator_id or None, label, names.splitlines(), status)
            except ValueError as problem:
                return Response(str(problem).capitalize() + ".", status_code=400)
        elif action == "delete" and indicator_id:
            indicator_store.remove(data_dir, indicator_id)
        elif action in ("accept", "reject") and indicator_id:
            indicator_store.decide_names(data_dir, indicator_id, [line for line in names.splitlines() if line.strip()], accept=action == "accept")
        elif action == "assign" and indicator_id and spelling:
            indicator_store.add_names(data_dir, indicator_id, [spelling], reviewed=True)
        elif action == "drop" and indicator_id and spelling:
            indicator_store.drop_name(data_dir, indicator_id, spelling)
        elif action == "reviewed" and indicator_id:
            indicator_store.mark_reviewed(data_dir, indicator_id)
        # Through the same check as every other way back: a header is not a destination.
        return RedirectResponse(_same_page(request.headers.get("referer", "/indicators"),
                                           (registry.active().id if registry.active() else "")) or "/indicators",
                                status_code=303)  # fmt: skip

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, saved: bool = False, trouble: str = ""):
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "current": "settings",
                "enabled": ask_enabled(registry.data_dir),
                "mode": answer_mode(registry.data_dir),
                "model_ready": backend_installed(),
                "scale": converts_units(registry.data_dir),
                "unit_from_range": reads_unit_from_range(registry.data_dir),
                "unit_by_numbers": places_unit_by_numbers(registry.data_dir),
                "read_materials": trusts_read_materials(registry.data_dir),
                "passes": [
                    {"key": key, "label": item["label"], "about": item["about"],
                     "chosen": model_for(registry.data_dir, key)}
                    for key, item in PASSES.items()
                ],
                "known_models": KNOWN_MODELS,
                "known_names": [name for name, _about in KNOWN_MODELS],
                "read_materials_known": _tables_read(),
                "mcp_lock": mcp_lock_on(registry.data_dir),
                "mcp_lock_scope": mcp_lock_scope(registry.data_dir),
                "mcp_lock_minutes": mcp_lock_minutes(registry.data_dir),
                "mcp_secret": bool(read_lock_secret()),
                "confirmed": has_consent(registry.data_dir, ClaudeCodeBackend.name),
                "saved": saved,
                "trouble": trouble,
            },
        )

    @app.post("/settings")
    def save_settings(request: Request, ask_page: str = Form(""), mode: str = Form("as_printed"), scale: str = Form(""),
                      unit_from_range: str = Form(""), unit_by_numbers: str = Form(""),
                      read_materials: str = Form(""),
                      model_first: str = Form(""), model_strong: str = Form(""),
                      model_second_reader: str = Form(""),
                      mcp_lock: str = Form(""), mcp_lock_scope_choice: str = Form("conversation", alias="mcp_lock_scope"),
                      mcp_lock_minutes_choice: int = Form(240, alias="mcp_lock_minutes")):  # fmt: skip
        set_ask_enabled(registry.data_dir, ask_page == "on")
        set_converts_units(registry.data_dir, scale == "on")
        set_reads_unit_from_range(registry.data_dir, unit_from_range == "on")
        set_places_unit_by_numbers(registry.data_dir, unit_by_numbers == "on")
        set_chosen_models(registry.data_dir, {
            "first": model_first, "strong": model_strong, "second_reader": model_second_reader,
        })  # fmt: skip
        # This one changes what is in the index, not only how a page draws it, so the index is
        # built again — and only when the answer actually changed.
        trouble = None
        if trusts_read_materials(registry.data_dir) != (read_materials == "on"):
            set_trusts_read_materials(registry.data_dir, read_materials == "on")
            trouble = _rebuild_index()
        set_mcp_lock(registry.data_dir, mcp_lock == "on" and bool(read_lock_secret()))
        with suppress(ValueError):
            set_mcp_lock_scope(registry.data_dir, mcp_lock_scope_choice)
        with suppress(ValueError):
            set_mcp_lock_minutes(registry.data_dir, mcp_lock_minutes_choice)
        if mode in ANSWER_MODES:
            set_answer_mode(registry.data_dir, mode)
        if trouble:
            return RedirectResponse(f"/settings?saved=true&trouble={quote(trouble)}", status_code=303)
        return RedirectResponse("/settings?saved=true", status_code=303)

    def _tables_read() -> int:
        """How many tables a model has already been asked about, across every archive here."""
        from epicrisis.material_reading import answered

        return sum(len(answered(jobs.records_path(source.id).parent)) for source in _open_archives(registry))

    def _rebuild_index() -> str | None:
        """Build every archive's index again. The first failure is returned, and shown."""
        from epicrisis.index.build import build_index

        for source in registry.list():
            try:
                build_index(registry.data_dir, [source])
            except Exception as problem:  # noqa: BLE001 - whatever went wrong, the page must say so
                return f"The index of {source.whose} could not be built again: {problem}"
        return None

    @app.get("/ask", response_class=HTMLResponse)
    @app.get("/ask/{chat_id}", response_class=HTMLResponse)
    def ask_page(request: Request, chat_id: str | None = None):
        # A chat is about one person's archive. Asked for from another, it is not found — the
        # same answer as one that never existed, because which chats exist is not this page's
        # to tell.
        chat = load_chat(registry.data_dir, chat_id, registry.active()) if chat_id else None
        if chat_id and chat is None:
            return Response("Unknown chat.", status_code=404)
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
                "confirmed": has_consent(registry.data_dir, ClaudeCodeBackend.name),
            },
        )

    @app.post("/ask")
    @app.post("/ask/{chat_id}")
    def ask_question(request: Request, chat_id: str | None = None, question: str = Form(""), continue_chat: str = Form("", alias="continue")):
        if not (ask_enabled(registry.data_dir) and has_consent(registry.data_dir, ClaudeCodeBackend.name)):
            return Response("Asking is turned off for this instance.", status_code=403)
        # Unchecked box: the question starts its own chat, so nothing said earlier reaches the model.
        open_archive = registry.active()
        chat = (load_chat(registry.data_dir, chat_id, open_archive) if chat_id and continue_chat
                else new_chat(registry.data_dir, open_archive))  # fmt: skip
        if chat is None:
            return Response("Unknown chat.", status_code=404)
        if background_jobs:
            ask(registry.data_dir, chat["id"], question)
        return RedirectResponse(f"/ask/{chat['id']}", status_code=303)

    @app.post("/ask/{chat_id}/delete")
    def remove_chat(request: Request, chat_id: str):
        if load_chat(registry.data_dir, chat_id, registry.active()) is None:
            return Response("Unknown chat.", status_code=404)
        if not delete_chat(registry.data_dir, chat_id):
            return Response("Unknown chat.", status_code=404)
        return RedirectResponse("/ask", status_code=303)

    @app.get("/ask/{chat_id}/state")
    def ask_state(chat_id: str):
        chat = load_chat(registry.data_dir, chat_id, registry.active())
        if chat is None:
            return Response("Unknown chat.", status_code=404)
        return JSONResponse({"running": chat_running(chat), "messages": chat["messages"]})

    @app.get("/review", response_class=HTMLResponse)
    def review(request: Request, copies: str = ""):
        sources = []
        for source in _open_archives(registry):
            view = review_view(source, jobs.records_path(source.id).parent)
            if view is not None:
                sources.append(_from_the_index(view, source))
        return templates.TemplateResponse(
            request, "review.html", {"sources": sources, "current": "review", "open_copies": bool(copies)}
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
    def choose_copy(source_id: str, sha256: str, first_page: int):
        """This one of the copies is the one that answers."""
        source = _the_open_archive(source_id)
        output = jobs.records_path(source_id).parent
        if source is None:
            return Response("Unknown source.", status_code=404)
        try:
            pages = query_index.choose_primary_copy(registry.data_dir, source_id, sha256, first_page)
        except IndexMissing:
            return Response("Nothing is indexed yet.", status_code=404)
        if pages is None:
            return Response("That document is not one of a group of copies.", status_code=404)
        set_primary_copy(output, sha256, pages, True)
        # Back to the group that was just decided, open, rather than to a closed page.
        return RedirectResponse("/review?copies=open#copies", status_code=303)

    @app.post("/sources/{source_id}/validate")
    def run_validation(source_id: str):
        # The checks read one archive's transcriptions and write into its own folder, so they
        # run for the archive that is open and for no other. See _the_open_archive.
        source = _the_open_archive(source_id)
        output = jobs.records_path(source_id).parent
        if source is None or not (output / "classify.jsonl").exists():
            return Response("Unknown source.", status_code=404)
        validate_source(output, Path(source.path))
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
            return Response("Unknown document.", status_code=404)
        known = {item["key"] for table in view["observation_tables"] for row in table["rows"] for item in [row["main"]]}
        if key not in known:
            return Response("No such line in this document.", status_code=404)
        pages = view["summary"]["pages"]
        if action == "remove":
            set_value(output, sha256, pages, key, None, removed=True)
        elif action == "reset":
            set_value(output, sha256, pages, key, None)
        else:
            set_value(output, sha256, pages, key, {
                "name_as_printed": name, "value_as_printed": value, "unit_as_printed": unit,
                "reference_as_printed": reference, "flag_as_printed": flag,
                **({"material": material} if material in MATERIALS_TO_CHOOSE else {}),
            })  # fmt: skip
        return RedirectResponse(f"/documents/{source_id}/{sha256}/{first_page}", status_code=303)

    @app.get("/sources/{source_id}/files/{sha256}/pages/{page}")
    def page_image(source_id: str, sha256: str, page: int):
        source = _the_open_archive(source_id)
        inventory = jobs.records_path(source_id)
        if source is None or not inventory.exists():
            return Response("Unknown source.", status_code=404)
        record = next((record for record in read_records(inventory) if record.get("sha256") == sha256), None)
        ref = next((ref for ref in page_refs(record) if ref.page == page), None) if record else None
        if ref is None:
            return Response("Unknown page.", status_code=404)
        try:
            image = original_png(ref, Path(source.path))
        except PageUnreadable as exc:
            return Response(f"This page cannot be shown: {exc}.", status_code=409)
        return Response(image, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/browse")
    def browse(path: str = ""):
        if not path:
            archive = registry.data_dir / "archive"
            path = str(archive if archive.is_dir() else Path.home())
        try:
            listing = list_folder(path, added_paths={source.path for source in registry.list()},
                                  roots=registry.roots())  # fmt: skip
        except BrowseError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status_code)
        try:
            registry.validate(listing["path"])
            listing.update(can_add=True, reason="")
        except SourceError as exc:
            listing.update(can_add=False, reason=str(exc))
        return listing

    @app.post("/update")
    def process_new_files():
        """Start the reading, from wherever the person pressed it, and show them the progress."""
        if background_jobs and not update_running(registry.data_dir):
            start_update(registry.data_dir)
        return RedirectResponse("/status", status_code=303)

    @app.post("/sources/{source_id}/inventory")
    def rescan_source(source_id: str):
        source = registry.get(source_id)
        if source is None:
            return Response("Unknown source.", status_code=404)
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
        classify = _classify_step(records, records_path.parent)
        extract = _extract_step(records, records_path.parent)
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


def _classify_step(records: list[dict], output: Path) -> dict:
    wanted = {(ref.file_sha256, ref.page) for ref in all_refs(records)}
    if not wanted:
        return {"state": "not_started", "label": "", "title": "Classify: nothing to classify yet"}
    done = sum(1 for page in latest_pages(output / "classify.jsonl") if (page["file_sha256"], page["page"]) in wanted)
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


def _extract_step(records: list[dict], output: Path) -> dict:
    by_file = {record["sha256"]: record for record in records if "sha256" in record}
    classify_pages = latest_pages(output / "classify.jsonl")
    documents = document_refs(by_file, classify_pages)
    if not documents:
        return {"state": "not_started", "label": "", "title": "Extract: nothing to extract yet"}
    finished = {key[:2] for key in done_keys(output / "ledger.jsonl", classify_pages)}
    done = sum(1 for document in documents if (document.file_sha256, document.pages) in finished)
    percent = int(done * 100 / len(documents))
    title = f"Extract: {done} of {len(documents)} documents classified so far"
    if is_running(output, EXTRACT_LOCK):
        return {"state": "running", "percent": percent, "label": f"{percent}%", "title": title}
    if done >= len(documents):
        return {"state": "done", "label": "", "title": title}
    if done:
        return {"state": "partial", "percent": percent, "label": f"{percent}%", "title": title}
    return {"state": "not_started", "label": "", "title": title}


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
        inventory.update(label="Failed", title=status.get("error", ""))
        note, alert = status.get("error", "Inventory failed"), True
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
            details.append(f"{summary.extra_copies} duplicates")
        if summary.unsupported:
            details.append(f"{len(summary.unsupported)} unsupported")
        note = " / ".join(details)

    later_steps = [
        validate,
        index,
    ]
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
