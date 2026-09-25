"""Command-line entry point.

The pipeline is five independent commands. Each can be run and re-run on its own:
inventory -> classify -> extract -> validate -> index.
"""

import signal
import os
import sys
from contextlib import closing
from collections.abc import Callable
from pathlib import Path

import typer

from epicrisis import layout
from epicrisis import __version__, engines
from epicrisis.inventory.report import render
from epicrisis.inventory.run import OutputInsideArchive, write_inventory

app = typer.Typer(
    help="Turn an archive of scanned medical documents into structured data, kept as printed.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    # Everything this program writes is somebody's medical record: the index holds every
    # transcribed value, the sidecars hold the page texts. They are written for their owner and
    # for nobody else on the machine, whatever the account's umask happens to be.
    os.umask(0o077)


@app.command()
def inventory(
    archive: Path = typer.Argument(
        ..., exists=True, file_okay=False, resolve_path=True, help="Archive root. Only read."
    ),
    out: Path = typer.Option(Path(layout.INVENTORY), "--out", "-o", help="JSONL output file."),
    usd_per_page: float = typer.Option(
        0.02, "--usd-per-page", min=0, help="Price of one vision page in USD, for the cost estimate."
    ),
    details: bool = typer.Option(
        False,
        "--details",
        help="List paths of duplicate, damaged and unsupported files. Paths may contain personal data.",
    ),
) -> None:
    """Walk the archive and record every file: hash, type, pages. No model calls."""
    show_progress = sys.stderr.isatty()
    try:
        summary = write_inventory(archive, out, progress=_print_progress if show_progress else None)
    except OutputInsideArchive:
        typer.echo("Refusing to write inside the archive: the archive is read-only.", err=True)
        raise typer.Exit(code=2)
    if show_progress:
        typer.echo("", err=True)

    typer.echo(render(summary, usd_per_page=usd_per_page, details=details))
    typer.echo(f"Inventory written to {out.resolve()}")


def _print_progress(scanned: int, total: int) -> None:
    typer.echo(f"\rScanned {scanned}/{total} files", err=True, nl=False)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Address to listen on. Keep it local and use an SSH tunnel."),
    port: int = typer.Option(8050, help="Port to listen on."),
    data_dir: Path = typer.Option(Path("data"), "--data-dir", help="Where sources and results are kept."),
) -> None:
    """Run the local status dashboard."""
    import uvicorn

    from epicrisis.web.app import LOCAL_HOSTS, create_app

    if host not in LOCAL_HOSTS:
        typer.echo(
            f"Warning: listening on {host}. The dashboard has no login; "
            "anyone who can reach this address sees your archive folders.",
            err=True,
        )
    web_app = create_app(data_dir, allowed_hosts=[*LOCAL_HOSTS, host])
    # The address is announced once the socket is ours and not before: printed first, it told a
    # person where to go and then failed to bind, on a port already in use.
    where = f"http://{'localhost' if host in LOCAL_HOSTS else host}:{port}"

    # No access log: /browse query strings carry folder names, which must not land in logs.
    server = uvicorn.Server(uvicorn.Config(web_app, host=host, port=port, log_level="warning", access_log=False))
    original = server.startup

    async def startup(sockets=None):
        await original(sockets=sockets)
        typer.echo(f"Epicrisis Companion: {where}")

    server.startup = startup
    try:
        server.run()
    except OSError as trouble:
        typer.echo(f"Cannot listen on {host}:{port}: {trouble.strerror or trouble}.", err=True)
        raise typer.Exit(code=3) from trouble


SOURCE_OPTION = typer.Option(None, "--source", help="Source id. Defaults to the only registered source.")
YEARS_OPTION = typer.Option(None, "--years", help="Only files whose folder year is listed, e.g. 1992-2003 or 1992-2003,2025.")
DATA_DIR_OPTION = typer.Option(Path("data"), "--data-dir", help="Where sources and results are kept.")
WORKERS_OPTION = typer.Option(
    3, "--workers", min=1, max=8, help="Model calls at once. More is faster and uses the subscription limit sooner."
)


def _read_index(data_dir: Path, source):
    """Open an archive's index, or say what to run first. A traceback is not an answer."""
    from epicrisis.query import IndexMissing, open_index

    try:
        return open_index(data_dir, source.id if source else None)
    except IndexMissing:
        typer.echo("Nothing is indexed yet. Run: epicrisis index", err=True)
        raise typer.Exit(code=2) from None


def _years_option(sample: bool, years_spec: str | None) -> set[int] | None:
    from epicrisis.classify.run import parse_years

    if sample and years_spec:
        typer.echo("Use either --sample or --years.", err=True)
        raise typer.Exit(code=2)
    try:
        return parse_years(years_spec) if years_spec else None
    except ValueError as exc:
        typer.echo(f"--years: {exc}", err=True)
        raise typer.Exit(code=2)


def _printed_names_everywhere(registry) -> tuple[dict[str, dict], "Path"]:
    """Every printed name on this server, and a folder to work in.

    Indicators are one vocabulary for the whole server, so a spelling that appears in only one
    archive still belongs to the group: shown with no unit and no count it looks like a mistake,
    and a reader judges a group by its units above all. Written three times in this file, the
    three copies were already drifting apart.
    """
    from contextlib import suppress

    from epicrisis import indicators as store
    from epicrisis.query import IndexMissing, open_index
    from epicrisis.sources import source_output_dir

    if not registry.list():
        typer.echo("No archives here yet.", err=True)
        raise typer.Exit(code=2)
    printed: dict[str, dict] = {}
    for source in registry.list():
        with suppress(IndexMissing):
            with closing(open_index(registry.data_dir, source.id)) as connection:
                for item in store.printed_names(connection):
                    held = printed.setdefault(item["folded"], {**item, "units": list(item["units"])})
                    if held is not item:
                        held["times"] += item["times"]
                        held["units"] = sorted(set(held["units"]) | set(item["units"]))
    return printed, source_output_dir(registry.data_dir, registry.list()[0].id)


def _require_consent(data_dir: Path, backend_name: str) -> None:
    """Nothing reaches a model before the person has read, once, what would be sent.

    Every step that sends anything — pages, or only the printed names of values — asks this.
    A step that asked nothing would make the promise on the consent page untrue.
    """
    from epicrisis.consent import has_consent

    if not has_consent(data_dir, backend_name):
        typer.echo(
            "Model processing is not confirmed. Review and confirm it in the dashboard: http://localhost:8050/consent",
            err=True,
        )
        raise typer.Exit(code=2)


def _prepare_model_step(data_dir: Path, source_id: str | None, backend_name: str, running: Callable[[Path], bool]):
    """Source, output directory and the checks every step that sends pages to a model needs."""
    from epicrisis.sources import SourceRegistry, source_output_dir

    registry = SourceRegistry(data_dir)
    sources = registry.list()
    source = registry.get(source_id) if source_id else (sources[0] if len(sources) == 1 else None)
    if source is None:
        # Ids only: source names are folder names and may carry personal data.
        typer.echo("Choose a source with --source: " + ", ".join(s.id for s in sources), err=True)
        raise typer.Exit(code=2)
    output = source_output_dir(registry.data_dir, source.id)
    if not (output / layout.INVENTORY).exists():
        typer.echo("Run the inventory for this source first.", err=True)
        raise typer.Exit(code=2)
    _require_consent(registry.data_dir, backend_name)
    if running(output):
        typer.echo("A run of this step for this source is already in progress.", err=True)
        raise typer.Exit(code=2)
    # Turn a termination signal into a normal exit so temporary page files are removed.
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    return registry, source, output


def _raise_keyboard_interrupt(signum, frame) -> None:
    raise KeyboardInterrupt


@app.command()
def classify(
    source_id: str | None = SOURCE_OPTION,
    sample: bool = typer.Option(
        False, "--sample", help="Only 5 pages: 2 scans before 2014, 2 digital pages from 2015, 1 photo."
    ),
    years_spec: str | None = YEARS_OPTION,
    limit: int | None = typer.Option(None, "--limit", min=1, help="Stop after this many pages."),
    workers: int = WORKERS_OPTION,
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    """Classify every page: document type, page role, language, printed date. Sends pages to a model."""
    from epicrisis.classify.report import latest_pages, render_summary
    from epicrisis.classify.run import all_refs, classify_source, is_running
    from epicrisis.records import read_records

    years = _years_option(sample, years_spec)
    backend = engines.classifier(data_dir)
    registry, source, output = _prepare_model_step(data_dir, source_id, backend.name, is_running)

    show_progress = sys.stderr.isatty()
    stats = classify_source(
        registry.data_dir, source, backend, sample=sample, limit=limit, years=years, workers=workers,
        progress=_print_step_progress("Pages") if show_progress else None,
    )  # fmt: skip
    if show_progress:
        typer.echo("", err=True)
    typer.echo(
        f"This run: classified {stats.classified}, unreadable {stats.unreadable}, "
        f"failed {stats.failed}, already done {stats.already_done}"
    )
    if stats.stopped == "usage_limit":
        typer.echo("Stopped at the subscription usage limit. Run the same command later to continue.")
    total = len(all_refs(list(read_records(output / layout.INVENTORY))))
    typer.echo(render_summary(latest_pages(output / layout.CLASSIFY), total))


@app.command()
def extract(
    source_id: str | None = SOURCE_OPTION,
    sample: bool = typer.Option(False, "--sample", help="Only 5 documents of different types and languages."),
    years_spec: str | None = YEARS_OPTION,
    limit: int | None = typer.Option(None, "--limit", min=1, help="Stop after this many documents."),
    files_spec: str | None = typer.Option(None, "--files", help="Only these files, by the first characters of the file id, comma separated."),
    done_by: str | None = typer.Option(None, "--done-by", help="Only documents a given model transcribed, by part of its name, for instance haiku."),
    redo: bool = typer.Option(False, "--redo", help="Read the documents again even where they are already transcribed."),
    close_ups: bool = typer.Option(False, "--close-ups", help="Read every document again from close-ups as well, whatever the checks say."),
    strong: bool = typer.Option(False, "--strong", help="Use the strong model alone, without the small one first."),
    workers: int = WORKERS_OPTION,
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    """Transcribe documents found by classify: values, units, references and text as printed. Sends pages to a model."""
    from epicrisis.classify.report import latest_pages
    from epicrisis.classify.run import is_running
    from epicrisis.extract.backend import ClaudeCodeExtractBackend, ExtractLadder
    from epicrisis.models import model_for
    from epicrisis.extract.report import load_documents, render_summary
    from epicrisis.extract.run import LOCK_NAME, document_refs, extract_source
    from epicrisis.records import read_records

    years = _years_option(sample, years_spec)
    files = {part.strip() for part in files_spec.split(",") if part.strip()} if files_spec else None
    backend = (ExtractLadder(ClaudeCodeExtractBackend(model=model_for(data_dir, "strong")))
               if strong else engines.extractor(data_dir))  # fmt: skip
    registry, source, output = _prepare_model_step(
        data_dir, source_id, backend.name, lambda path: is_running(path, LOCK_NAME)
    )
    if not (output / layout.CLASSIFY).exists():
        typer.echo("Run classify for this source first.", err=True)
        raise typer.Exit(code=2)

    show_progress = sys.stderr.isatty()
    stats = extract_source(
        registry.data_dir, source, backend, years=years, sample=sample, limit=limit, workers=workers,
        files=files, done_by=done_by, redo=redo, close_ups=close_ups,
        progress=_print_step_progress("Documents") if show_progress else None,
    )  # fmt: skip
    if show_progress:
        typer.echo("", err=True)
    typer.echo(
        f"This run: extracted {stats.extracted}, unreadable {stats.unreadable}, "
        f"failed {stats.failed}, already done {stats.already_done}"
    )
    if stats.escalated:
        typer.echo(f"Transcribed again by the stronger model after a failed check: {stats.escalated}")
    if stats.close_up_passes:
        typer.echo(f"Close-up passes: {stats.close_up_passes}, fewer unreadable parts in {stats.close_up_better}")
    if stats.stopped == "usage_limit":
        typer.echo("Stopped at the subscription usage limit. Run the same command later to continue.")
    records = {record["sha256"]: record for record in read_records(output / layout.INVENTORY) if "sha256" in record}
    total = len(document_refs(records, latest_pages(output / layout.CLASSIFY)))
    years_by_file = {sha: record.get("folder_year_hint") for sha, record in records.items()}
    typer.echo(render_summary(load_documents(output / layout.EXTRACTED), total, years_by_file))



@app.command("find-dates")
def find_dates(
    source_id: str | None = SOURCE_OPTION,
    workers: int = WORKERS_OPTION,
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    """Look again for dates on documents that have none: stamps, signatures, handwriting. Sends pages to a model."""
    from epicrisis.classify.run import is_running
    from epicrisis.datesearch import LOCK_NAME, search_source
    from epicrisis.records import read_records
    from epicrisis.web.documents import source_documents


    backend = engines.date_search(data_dir)
    registry, source, output = _prepare_model_step(data_dir, source_id, backend.name, lambda path: is_running(path, LOCK_NAME))
    records = {record["sha256"]: record for record in read_records(output / layout.INVENTORY) if "sha256" in record}
    view = source_documents(source, output)
    targets = [
        (records[row["file"]["sha256"]], tuple(row["pages"]))
        for group in view["years"]
        for row in group["documents"]
        if row["date"]["value"] is None and not row.get("unreadable") and row["doc_type"] != "Blank page"
    ]
    stats = search_source(registry.data_dir, source, backend, targets, workers=workers)
    typer.echo(
        f"Documents without a date: {len(targets)}. This run: searched {stats.searched}, with dates found "
        f"{stats.with_dates}, unreadable {stats.unreadable}, failed {stats.failed}"
    )
    if stats.stopped == "usage_limit":
        typer.echo("Stopped at the subscription usage limit. Run the same command later to continue.")
    still = sum(1 for group in source_documents(source, output)["years"] for row in group["documents"] if row["date"]["value"] is None and not row.get("unreadable"))
    typer.echo(f"Documents still without a date: {still}")


def _print_step_progress(unit: str) -> Callable:
    def show(stats) -> None:
        typer.echo(f"\r{unit}: {stats.attempted} of {stats.total - stats.already_done}", err=True, nl=False)

    return show


@app.command()
def suspects(
    limit: int = typer.Option(20, min=1, help="How many documents to show."),
    ids_only: bool = typer.Option(False, "--ids-only", help="Print one comma separated list of file ids, for --files."),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    """Lines that look misread, ranked: candidates for a second reading. Reads the index only."""
    from epicrisis import rules
    from epicrisis.rules import kinds
    from epicrisis.settings import rules_on
    from epicrisis.sources import showing as sources_showing
    from epicrisis.suspects import find, rows_from_index

    showing = sources_showing(data_dir)
    connection = _read_index(data_dir, showing)
    found_by = rules_on(data_dir, rules.load(data_dir), kinds.SUSPECTS)
    if not found_by:
        typer.echo("Every rule that finds these is turned off for this archive. See the settings page.")
        return
    found = find(*rows_from_index(connection), found_by)
    first: dict[str, object] = {}
    for item in found:
        first.setdefault(item.file_id, item)
    chosen = list(first.values())[:limit]
    if ids_only:
        typer.echo(",".join(item.file_id for item in chosen))
        return
    typer.echo(f"{len(found)} documents carry a signal; the {len(chosen)} files below look most worth a second reading.\n")
    for item in chosen:
        typer.echo(f"{item.file_id} p{item.first_page} {item.date or '—'} · {', '.join(f'{code} {times}' for code, times in item.codes.most_common())}")
        for line in item.lines[:4]:
            typer.echo(f"    {line}")


def _let_the_server_read(file: Path) -> None:
    """The service runs as its own user, so the secret it checks codes against is theirs to read."""
    import grp
    import os
    import pwd

    try:
        os.chown(file, pwd.getpwnam("root").pw_uid, grp.getgrnam("ubuntu").gr_gid)
    except (KeyError, PermissionError, OSError):
        pass


@app.command(name="mcp-lock")
def mcp_lock_command(
    action: str = typer.Argument("status", help="status, init, on, off, scope, window or clear."),
    value: str = typer.Argument(None, help="With scope: conversation or server. With window: minutes."),
    force: bool = typer.Option(False, "--force", help="With init: replace a secret that already exists."),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    """The lock on the tools served over the network: a code from an authenticator.

    `init` makes the shared secret and prints the line an authenticator reads. That line is the
    secret itself, so it is printed once, to whoever runs this, and never passed on.
    """
    from epicrisis.settings import (mcp_lock_minutes, mcp_lock_on, mcp_lock_scope, set_mcp_lock,
                                    set_mcp_lock_minutes, set_mcp_lock_scope)
    from epicrisis.mcp_lock import SCOPES, SECRET_FILE, new_secret, read_secret, uri, write_secret

    if action == "init":
        if read_secret() and not force:
            typer.echo(f"A secret is already in {SECRET_FILE}. Use --force to replace it, and the old codes stop working.", err=True)
            raise typer.Exit(code=2)
        secret = new_secret()
        try:
            written = write_secret(secret)
            _let_the_server_read(written)
        except OSError as problem:
            typer.echo(f"Cannot write {SECRET_FILE}: {problem}. Run this as root.", err=True)
            raise typer.Exit(code=2) from problem
        typer.echo("Read this line into your authenticator. It is the secret itself: do not send it anywhere.\n")
        typer.echo(uri(secret))
        typer.echo(f"\nKept in {written}. Turn the lock on with: epicrisis mcp-lock on")
        return
    if action == "clear":
        typer.echo("Wrong-code waits are kept by the running server, so clearing them restarts it.")
        typer.echo("Run: sudo systemctl restart epicrisis-mcp.service")
        return
    if action in ("on", "off"):
        if action == "on" and not read_secret():
            typer.echo("No secret yet. Run: epicrisis mcp-lock init", err=True)
            raise typer.Exit(code=2)
        set_mcp_lock(data_dir, action == "on")
        typer.echo(f"The lock is {'on' if action == 'on' else 'off'}. The server reads this on the next call; no restart needed.")
        return
    if action == "scope":
        if value not in SCOPES:
            typer.echo(f"Say one of: {', '.join(SCOPES)}. conversation: a code opens the conversation it was given in."
                       " server: one code opens everything until the window runs out.", err=True)  # fmt: skip
            raise typer.Exit(code=2)
        set_mcp_lock_scope(data_dir, value)
        typer.echo(f"A code now opens: {value}.")
        return
    if action == "window":
        try:
            set_mcp_lock_minutes(data_dir, int(value))
        except (TypeError, ValueError) as problem:
            typer.echo("Say the window in minutes, from 1 to 10080.", err=True)
            raise typer.Exit(code=2) from problem
        typer.echo(f"A code now opens the archive for {mcp_lock_minutes(data_dir)} minutes.")
        return
    if action != "status":
        typer.echo("Say one of: status, init, on, off, scope, window, clear.", err=True)
        raise typer.Exit(code=2)
    typer.echo(f"Lock: {'on' if mcp_lock_on(data_dir) else 'off'}")
    typer.echo(f"A code opens: {mcp_lock_scope(data_dir)}, for {mcp_lock_minutes(data_dir)} minutes")
    typer.echo(f"Secret: {'set' if read_secret() else 'not set'} ({SECRET_FILE})")
    typer.echo("Over stdio the lock does not apply: that is a program on this machine.")


@app.command()
def recheck(
    source_id: str | None = SOURCE_OPTION,
    model: str = typer.Option(None, help="The model that reads the documents again. The second reader by default."),
    files_spec: str | None = typer.Option(None, "--files", help="Only these files, by the first characters of the file id, comma separated."),
    done_by: str | None = typer.Option(None, "--done-by", help="Only documents a given model transcribed, by part of its name."),
    limit: int | None = typer.Option(None, "--limit", min=1, help="Stop after this many documents."),
    close_ups: bool = typer.Option(False, "--close-ups", help="Send every page as an image with close-ups."),
    workers: int = WORKERS_OPTION,
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    """Read documents again with another model and show where the two readings differ. Changes nothing."""
    from epicrisis.recheck import recheck_source

    backend = engines.second_reader(data_dir) if model is None else engines.second_reader(data_dir, model=model)
    registry, source, output = _prepare_model_step(data_dir, source_id, backend.name, lambda path: False)
    files = {part.strip() for part in files_spec.split(",") if part.strip()} if files_spec else None
    stats = recheck_source(
        registry.data_dir, source, backend, files=files, done_by=done_by, limit=limit, close_ups=close_ups, workers=workers,
        say=lambda text: typer.echo(text, err=True),
    )  # fmt: skip

    typer.echo(f"\nRead again by {backend.model}: {stats.documents} documents, {stats.failed} failed")
    if stats.stopped == "usage_limit":
        typer.echo("Stopped at the subscription usage limit; run it again later.")
    typer.echo(f"Values: {stats.values_ours} in the archive, {stats.values_theirs} in the second reading, {stats.agreed} identical")
    typer.echo(f"Transcribed text: {stats.text_chars[0]} characters against {stats.text_chars[1]}")
    for title, items in (("Only in the archive", stats.only_ours), ("Only in the second reading", stats.only_theirs)):
        if items:
            typer.echo(f"\n{title}: {len(items)}")
            for file_id, page, name in items[:40]:
                typer.echo(f"  {file_id} p{page}  {name}")
    if stats.differing or stats.header:
        typer.echo(f"\nRead differently: {len(stats.differing) + len(stats.header)}")
        for item in stats.header + stats.differing:
            typer.echo(f"  {item.file_id} p{item.page}  {item.name} · {item.field}: archive {item.ours!r} · second reading {item.theirs!r}")
    if not (stats.differing or stats.header or stats.only_ours or stats.only_theirs) and stats.documents:
        typer.echo("\nThe two readings say the same.")


@app.command()
def validate(source_id: str | None = SOURCE_OPTION, data_dir: Path = DATA_DIR_OPTION) -> None:
    """Check transcriptions without a model and list what to look at. Changes no data."""
    from epicrisis.sources import SourceRegistry, source_output_dir
    from epicrisis.validate import CHECKS, PRIORITY, validate_source

    registry = SourceRegistry(data_dir)
    sources = registry.list()
    source = registry.get(source_id) if source_id else (sources[0] if len(sources) == 1 else None)
    if source is None:
        typer.echo("Choose a source with --source: " + ", ".join(s.id for s in sources), err=True)
        raise typer.Exit(code=2)
    output = source_output_dir(registry.data_dir, source.id)
    if not (output / layout.CLASSIFY).exists():
        typer.echo("Run classify for this source first.", err=True)
        raise typer.Exit(code=2)
    result = validate_source(output, Path(source.path))
    cover = result["coverage"]
    typer.echo(
        f"Coverage: files {cover['files']}, not read {len(cover['files_not_read'])}; pages {cover['pages']}, "
        f"not classified {cover['pages_not_classified']}; documents due {cover['documents_due']}, "
        f"not transcribed {len(cover['documents_not_transcribed'])}"
    )
    for gap in cover["files_not_read"]:
        typer.echo(f"  file {gap['file_id']} not read: {gap['reason']}")
    typer.echo(f"Documents checked: {result['documents_checked']}, with findings: {len(result['documents'])}")
    for code in PRIORITY:
        documents = sum(1 for document in result["documents"] if code in document["findings"])
        if documents:
            typer.echo(f"  {CHECKS[code][1]}: {documents} documents, {result['totals'][code]} findings")


@app.command()
def ask(
    on: bool = typer.Option(False, "--on", help="Turn on the Ask page for this instance."),
    off: bool = typer.Option(False, "--off", help="Turn it off."),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    """Whether this instance answers questions about the archive on the Ask page."""
    from epicrisis.settings import ask_enabled, set_ask_enabled

    if on or off:
        set_ask_enabled(data_dir, on)
    typer.echo(f"Ask page: {'on' if ask_enabled(data_dir) else 'off'}")


@app.command()
def indicators(
    propose: bool = typer.Option(False, "--propose", help="Ask a model to group the printed names no indicator holds yet."),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    """Indicators: printed names grouped under one label. Proposals wait for a person."""
    import tempfile

    from epicrisis import indicators as store
    from epicrisis.indicator_proposals import ProposalBackend, propose_indicators, unassigned
    from epicrisis.sources import showing as sources_showing

    showing = sources_showing(data_dir)
    connection = _read_index(data_dir, showing)
    printed = store.printed_names(connection)
    waiting = unassigned(data_dir, printed)
    if propose:
        _require_consent(data_dir, engines.engine_name(data_dir))
        with tempfile.TemporaryDirectory(prefix="epicrisis-indicators-") as workdir:
            from epicrisis.models import model_for

            counts = propose_indicators(data_dir, printed, ProposalBackend(model=model_for(data_dir, "strong"), data_dir=data_dir),
                                        Path(workdir), say=typer.echo)  # fmt: skip
        typer.echo(
            f"Proposed: {counts['new_indicators']} new indicators, {counts['added_to_existing']} spellings for existing ones, "
            f"{counts['unclear']} unclear, in {counts['batches']} calls"
        )
    current = store.load(data_dir)
    approved = [item for item in current if item.status == "approved"]
    typer.echo(
        f"Indicators: {len(approved)} approved, {len(current) - len(approved)} proposed; "
        f"printed names {len(printed)}, not in any indicator {len(waiting) if propose else len(unassigned(data_dir, printed))}"
    )
    connection.close()


@app.command()
def mcp(
    data_dir: Path = DATA_DIR_OPTION,
    http: bool = typer.Option(False, "--http", help="Serve over HTTP instead of stdio, for a Claude connector."),
    secret_file: Path = typer.Option(None, help="File holding the secret that stands in the served path. Required with --http."),
    host: str = typer.Option("127.0.0.1", help="Address to listen on. Keep it local and put a tunnel in front."),
    port: int = typer.Option(8051, help="Port to listen on with --http."),
    public_host: str = typer.Option(None, help="The name the tunnel answers on, for instance epicrisis.example.ts.net."),
    allow_from: str = typer.Option(
        "160.79.104.0/21",
        help="Networks allowed to reach it through the tunnel, comma separated. The default is the range Anthropic publishes for its connectors; this machine and private networks are always allowed. An empty value lets anyone in.",
    ),  # fmt: skip
) -> None:
    """Serve the archive as read-only MCP tools: over stdio for Claude Code, or over HTTP for a connector."""
    from epicrisis.mcp_server import read_path_secret, run, run_http

    if not http:
        run(data_dir)
        return
    if secret_file is None:
        typer.echo("--http needs --secret-file: the secret is what keeps the archive closed.", err=True)
        raise typer.Exit(code=2)
    try:
        secret = read_path_secret(secret_file)
    except (OSError, ValueError) as problem:
        typer.echo(str(problem), err=True)
        raise typer.Exit(code=2) from problem
    typer.echo(f"Epicrisis MCP on http://{host}:{port}/mcp/<secret>")
    if not allow_from.strip():
        typer.echo("Warning: no source filter. Anyone who learns the address may try the secret.", err=True)
    run_http(data_dir, secret, host=host, port=port, public_host=public_host, allow_from=allow_from)


@app.command()
def update(data_dir: Path = DATA_DIR_OPTION) -> None:
    """Process new or changed files in every source: all steps, skipping what is done."""
    from epicrisis.sources import SourceRegistry
    from epicrisis.update import run_update, update_running

    if not SourceRegistry(data_dir).list():
        typer.echo("No archive here yet. Add one: epicrisis sources add <folder> --owner <name>", err=True)
        raise typer.Exit(code=2)
    if update_running(data_dir.resolve()):
        typer.echo("An update is already running.", err=True)
        raise typer.Exit(code=2)
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    run_update(data_dir, say=typer.echo)


@app.command()
def index(data_dir: Path = DATA_DIR_OPTION) -> None:
    """Build each archive's own index, running validation first. No model calls.

    One index file per archive: a question asked of one owner's records then cannot reach
    another's, because the other's are not in the database that answers it.
    """
    from epicrisis.index.build import build_index, index_path
    from epicrisis.sources import SourceRegistry, source_output_dir
    from epicrisis.validate import validate_source, validation_state

    registry = SourceRegistry(data_dir)
    sources = registry.list()
    if not sources:
        # Silence and a zero exit read as "done"; there is nothing here to index, and saying so
        # is the answer.
        typer.echo("No archive here yet. Add one: epicrisis sources add <folder> --owner <name>", err=True)
        raise typer.Exit(code=2)
    for source in sources:
        output = source_output_dir(registry.data_dir, source.id)
        if (output / layout.CLASSIFY).exists() and validation_state(output)["state"] != "done":
            validate_source(output, Path(source.path))
    for source in sources:
        totals = build_index(registry.data_dir, [source])
        typer.echo(
            f"{source.whose}: {totals['documents']} documents, {totals['transcribed']} transcribed, "
            f"{totals['observations']} values, {totals['copy_groups']} groups of copies"
        )
        typer.echo(f"  written to {index_path(registry.data_dir, source.id)}")
    older = index_path(registry.data_dir)
    if older.exists() and sources:
        # The single index of an instance built before archives had owners; each archive now has
        # its own, so this one is history and would only answer a question twice.
        older.rename(older.with_name(older.name + ".before-owners"))
        typer.echo(f"The index from before archives had owners is kept as {older.name}.before-owners")


@app.command()
def forget(
    source_id: str = typer.Argument(..., help="The archive's id, as `epicrisis serve` shows it on /status."),
    data_dir: Path = DATA_DIR_OPTION,
    yes: bool = typer.Option(False, "--yes", help="Do it without asking."),
) -> None:
    """Put aside everything read from one archive, so the next run reads it again from nothing.

    The folder is not touched and stays on the list. The inventory, the classification, the
    transcriptions, the checks and the index move into data/sources/<id>/forgotten-<when>/.
    Corrections stay where they are and apply again to the next reading.
    """
    from epicrisis.sources import SourceRegistry

    registry = SourceRegistry(data_dir.resolve())
    source = registry.get(source_id)
    if source is None:
        typer.echo(f"No archive with the id {source_id}. Run `epicrisis serve` and open /status to see them.", err=True)
        raise typer.Exit(code=2)
    if not yes and not typer.confirm(f"Read {source.whose} again from nothing? Nothing is deleted."):
        raise typer.Exit(code=1)
    aside = registry.forget(source_id)
    if aside is None:
        typer.echo(f"Nothing had been read from {source.whose} yet.")
        return
    typer.echo(f"Moved aside to {aside}")
    typer.echo("Run `epicrisis update` to read the archive again.")


@app.command("read-materials")
def read_materials_command(
    source_id: str | None = SOURCE_OPTION,
    model: str = typer.Option(None, help="The model that reads the headings. The small one by default."),
    limit: int | None = typer.Option(None, "--limit", min=1, help="Stop after this many tables."),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    """Ask a model what each table was measured in, where the form did not print it.

    Only headings and the names of values are sent: no numbers, no dates, no file names. What
    comes back is kept beside the corrections and never inside a transcription, and a value it
    settles is marked as read by a model rather than printed.
    """
    from epicrisis.extract.run import load_extracted
    from epicrisis.material_reading import MaterialBackend, read_materials
    from epicrisis.records import read_records

    from epicrisis.models import model_for

    backend = MaterialBackend(model=model or model_for(data_dir, "first"), data_dir=data_dir)
    registry, source, output = _prepare_model_step(data_dir, source_id, backend.name, lambda path: False)
    documents = []
    for record in read_records(output / layout.INVENTORY):
        extracted = load_extracted(output / layout.EXTRACTED, record["sha256"]) if "sha256" in record else None
        for document in (extracted or {"documents": []})["documents"]:
            documents.append({**document, "file_sha256": record["sha256"]})
    stats = read_materials(output, documents, backend, output, say=lambda text: typer.echo(text, err=True), limit=limit)

    typer.echo(f"\nTables read: {stats['panels']} in {stats['batches']} calls")
    typer.echo(f"Settled: {stats['decided']} tables, {stats['values']} values")
    typer.echo(f"Waiting for a person (the model was unsure): {stats['waiting']}")
    typer.echo(f"Could not tell: {stats['unclear']}")
    typer.echo("Run `epicrisis index` to put them in the index.")


@app.command("check-indicators")
def check_indicators_command(
    model: str = typer.Option(None, help="The model that reads the groups again. The second reader by default."),
    limit: int | None = typer.Option(None, "--limit", min=1, help="Stop after this many groups."),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    """Read every group of spellings again with a second model, and list where the two disagree.

    Indicators are one vocabulary for the whole server, so the printed names are gathered from
    every archive on it: a spelling that appears only in one of them would otherwise be shown
    with no unit and no count, and a reader judges a group by its units above all.

    Only groups holding two or more spellings are read: one spelling groups nothing and cannot
    be wrong. Nothing is changed; a disagreement is shown on the Indicators page for a person.
    """

    from epicrisis.indicator_check import CheckBackend, check_groups
    from epicrisis.models import model_for
    from epicrisis.sources import SourceRegistry

    backend = CheckBackend(model=model or model_for(data_dir, "second_reader"), data_dir=data_dir)
    _require_consent(data_dir, engines.engine_name(data_dir))
    registry = SourceRegistry(data_dir.resolve())
    printed, output = _printed_names_everywhere(registry)
    stats = check_groups(registry.data_dir, list(printed.values()), backend, output,
                         say=lambda text: typer.echo(text, err=True), limit=limit)  # fmt: skip

    typer.echo(f"\nGroups read again: {stats['groups']} in {stats['batches']} calls")
    typer.echo(f"Both readers agree: {stats['agreed']}")
    typer.echo(f"They disagree: {stats['disagreed']} groups, {stats['names_questioned']} spellings questioned")
    typer.echo("Open /indicators to settle the disagreements.")


@app.command("apply-agreed")
def apply_agreed_command(data_dir: Path = DATA_DIR_OPTION) -> None:
    """Put into use the groupings both readers agree on. Everything else keeps waiting.

    A spelling a model proposed joins its indicator when the second reader did not object to it.
    A group a model proposed becomes one the archive uses when the second reader agrees with
    every name in it. Nothing a reader objected to is touched, and a group of a single spelling
    is never decided here: whether such a test deserves an indicator is a person's judgement.
    """
    from epicrisis.indicator_check import apply_agreed

    counts = apply_agreed(data_dir.resolve(), say=lambda text: typer.echo(text, err=True))

    typer.echo(f"\nSpellings put into use: {counts['spellings_added']}")
    typer.echo(f"Spellings still waiting for you: {counts['spellings_left_waiting']}")
    typer.echo(f"Groups now in use: {counts['groups_approved']}"
               + (f" ({counts['groups_confirmed_by_a_reference']} confirmed by a reference)"
                  if counts["groups_confirmed_by_a_reference"] else ""))  # fmt: skip
    typer.echo(f"Groups still waiting for you: {counts['groups_left']}")
    if counts["in_use_a_reference_doubts"]:
        typer.echo(f"In use, but a reference says they are no test: {counts['in_use_a_reference_doubts']}"
                   " — nothing was changed; the reason is on each of them.")  # fmt: skip
    typer.echo("Run `epicrisis index` to put them in the index.")


@app.command("settle-names")
def settle_names_command(
    model: str = typer.Option(None, help="The model that searches. The expert one by default."),
    limit: int | None = typer.Option(None, "--limit", min=1, help="Stop after this many names."),
    yes: bool = typer.Option(False, "--yes", help="Do it without asking."),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    """Ask the open web whether a printed name is a real test. The only step that leaves Anthropic.

    It is for the names no second reader can judge: a group holding one spelling, where the
    question is not whether the spellings belong together but whether the name is a test at all.

    What leaves this server is a printed name, its units and how often it appears — no value, no
    date, no document, no person. It runs only when asked for by name and is never part of an
    ordinary run.
    """

    import tempfile

    from epicrisis.indicator_web_check import WebCheckBackend, names_to_settle, settle_names
    from epicrisis.models import model_for
    from epicrisis.sources import SourceRegistry

    registry = SourceRegistry(data_dir.resolve())
    printed, _ = _printed_names_everywhere(registry)

    waiting = names_to_settle(registry.data_dir, list(printed.values()))
    typer.echo(f"{len(waiting)} printed names would be sent to a web search: the name, its units and its count.")
    typer.echo("No value, no date, no document and no person leaves this server.")
    if not yes and not typer.confirm("Send them?"):
        raise typer.Exit(code=1)

    _require_consent(data_dir, WebCheckBackend.name)
    backend = WebCheckBackend(model=model or model_for(data_dir, "strong"))
    # A folder of its own, not the archive's: this is the one pass allowed to reach the open web,
    # and it has no business standing inside the transcriptions while it does.
    with tempfile.TemporaryDirectory(prefix="epicrisis-web-") as workdir:
        counts = settle_names(registry.data_dir, list(printed.values()), backend, Path(workdir),
                              say=lambda text: typer.echo(text, err=True), limit=limit)  # fmt: skip

    typer.echo(f"\nNames settled: {counts['names']} in {counts['batches']} searches")
    typer.echo(f"  a real test: {counts['a test']}")
    typer.echo(f"  not a test at all: {counts['not a test']}")
    typer.echo(f"  could not be told: {counts['unclear']}")
    typer.echo("Open /indicators to see what was found.")


@app.command("look-up-names")
def look_up_names_command(
    model: str = typer.Option(None, help="The model that searches. The expert one by default."),
    limit: int | None = typer.Option(None, "--limit", min=1, help="Stop after this many tests."),
    yes: bool = typer.Option(False, "--yes", help="Do it without asking."),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    """Ask the open web what else each test is called, so a spelling nobody has seen can be placed.

    Nothing found becomes a spelling this archive holds. A name from a reference is a claim about
    how laboratories write a test, not a thing any form printed, so it is kept apart and shown to
    the model that assigns new printed names — where it helps a name land in the right group
    instead of starting a new one.

    What leaves this server is a test's label, the spellings this archive printed for it and its
    units. No value, no date, no document, no person.
    """

    import tempfile

    from epicrisis.indicator_web_check import WebCheckBackend, look_up_names, tests_to_look_up
    from epicrisis.models import model_for
    from epicrisis.sources import SourceRegistry

    registry = SourceRegistry(data_dir.resolve())
    printed, _ = _printed_names_everywhere(registry)

    waiting = tests_to_look_up(registry.data_dir, list(printed.values()))
    typer.echo(f"{len(waiting)} tests would be looked up: the label, the spellings this archive printed, the units.")
    typer.echo("No value, no date, no document and no person leaves this server.")
    if not yes and not typer.confirm("Look them up?"):
        raise typer.Exit(code=1)

    _require_consent(data_dir, WebCheckBackend.name)
    backend = WebCheckBackend(model=model or model_for(data_dir, "strong"))
    # A folder of its own, not the archive's: this is the one pass allowed to reach the open web,
    # and it has no business standing inside the transcriptions while it does.
    with tempfile.TemporaryDirectory(prefix="epicrisis-web-") as workdir:
        counts = look_up_names(registry.data_dir, list(printed.values()), backend, Path(workdir),
                               say=lambda text: typer.echo(text, err=True), limit=limit)  # fmt: skip

    typer.echo(f"\nTests looked up: {counts['tests']} in {counts['batches']} searches")
    typer.echo(f"Tests a reference named differently: {counts['with_names']}")
    typer.echo(f"Names found, kept apart from what this archive printed: {counts['names']}")


@app.command()
def demo(
    into: Path = typer.Option(Path("demo"), "--into", help="Where to build it. Anything already there is used."),
    seed: int = typer.Option(7, "--seed", help="Change it for a different invented archive."),
) -> None:
    """Build a whole instance of make-believe: archives nobody lived, without calling a model.

    It draws three lives of forms in five languages — a person, their father, their grandmother —
    writes the transcription a model would have produced beside them, and then runs for real the
    steps that need no model. What comes out is a working instance to look at and to take
    pictures of, and not one call leaves this machine. Nobody in it exists.
    """
    from epicrisis.demo import LIVES, build

    made = build(into, seed=seed, say=lambda text: typer.echo(text, err=True))

    whose = ", ".join(life.whose for life in LIVES)
    typer.echo(f"\nThree archives of people who do not exist: {whose}")
    typer.echo(f"{made['documents']} documents, {made['observations']} values")
    for archive in made["archives"]:
        typer.echo(f"Scans:  {archive}")
    typer.echo(f"Look at it with: epicrisis serve --data-dir {made['data_dir']}")
