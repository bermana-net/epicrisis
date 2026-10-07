"""Command-line entry point.

The pipeline is five independent commands. Each can be run and re-run on its own:
inventory -> classify -> extract -> validate -> index.
"""

import errno
import signal
import os
import socket
import sys
from datetime import UTC, datetime
from contextlib import closing
from collections.abc import Callable
from pathlib import Path

import typer

from epicrisis import layout
from epicrisis import __version__, engines, invocation
from epicrisis.inventory.report import render
from epicrisis.inventory.run import NothingWhereTheArchiveWas, OutputInsideArchive, write_inventory
from epicrisis.invocation import CLI

app = typer.Typer(
    help="Turn an archive of scanned medical documents into structured data, kept as printed.",
    no_args_is_help=True,
)


def run() -> None:
    """The entry point. One place where trouble a person can act on is answered in a sentence.

    Every command that stores a choice can meet a file of state that is there and will not parse,
    and every command that writes can meet a lock left behind by a run that died. Unanswered,
    both came out as a traceback with the path to the file in it — over a machine whose paths are
    not for showing, and to a person who needs one sentence, not a stack. The page says the
    sentence; the terminal said nothing of the kind.

    SystemExit and not typer.Exit: typer.Exit is caught by Click inside app(), and raised out here
    it was caught by nobody, so the sentence was followed by thirty-five lines of traceback with
    the path printed a second time, and the process left with status 1 where a script was looking
    for 2.
    """
    from epicrisis import journal
    from epicrisis.runs import Busy
    from epicrisis.state import NoSpace, Unreadable, no_space

    instance = _the_instance_in(sys.argv)
    try:
        # The program's own name, so that usage lines say "epicrisis" and not the name of whatever
        # file happened to start it — "root ask [OPTIONS]" under a console script run as root.
        app(prog_name="epicrisis")
    except SystemExit as ending:
        # Every refusal of every command, by the code it leaves. Click turns typer.Exit into this
        # on its way out of app(), so the thirty places that say "no" and exit 2 are caught in one
        # — and those are the ones nothing else here hears about: the four below each print a
        # sentence a person can act on, while a refusal deep in a command printed its sentence to
        # a terminal and left nothing behind at all.
        code = ending.code if isinstance(ending.code, int) else (0 if ending.code is None else 1)
        if code:
            journal.record(instance, {"event": "a command refused and stopped", "code": code,
                                      **_which_command(sys.argv)})  # fmt: skip
        raise
    except Unreadable as broken:
        typer.echo(str(broken), err=True)
        journal.went_wrong(instance, "a file of this instance would not read", broken,
                           file=broken.file, code=2, **_which_command(sys.argv))  # fmt: skip
        raise SystemExit(2) from broken
    except Busy as busy:
        typer.echo(str(busy), err=True)
        journal.went_wrong(instance, "a step was already running", busy, code=3,
                           **({"step": busy.what} if busy.what else {}),
                           **_which_command(sys.argv))  # fmt: skip
        raise SystemExit(3) from busy
    except NoSpace as full:
        typer.echo(str(full), err=True)
        journal.went_wrong(instance, "there was no space left on the disk", full, code=4,
                           **_which_command(sys.argv))  # fmt: skip
        raise SystemExit(4) from full
    except OSError as trouble:
        if not no_space(trouble):
            journal.went_wrong(instance, "a command failed with nothing to say about it", trouble,
                               **_which_command(sys.argv))  # fmt: skip
            raise
        journal.went_wrong(instance, "there was no space left on the disk", trouble, code=4,
                           **_which_command(sys.argv))  # fmt: skip
        typer.echo(
            "There is no space left on the disk this instance writes to. Nothing was changed: "
            "every file here is written whole and renamed into place, so the ones already on disk "
            "are whole. Free some space and run the command again.",
            err=True,
        )
        raise SystemExit(4) from trouble


DEFAULT_DATA_DIR = Path("data")


def _the_instance_in(argv: list[str]) -> Path:
    """Which instance a command was acting on, read back out of its own arguments.

    The journal is a file in the data directory, and run() is outside every command, where nothing
    has parsed the arguments yet — and parsing them a second time with typer to find out would
    mean running the command twice. So the one option that decides where the file goes is read
    off the line directly, and a line that does not carry it means the default, exactly as the
    commands themselves mean it.

    A directory that is not there records nowhere: journal.record swallows that, which is right.
    Writing the line into a folder this command was not acting on would be worse than losing it.
    """
    for index, word in enumerate(argv):
        if word == "--data-dir" and index + 1 < len(argv):
            return Path(argv[index + 1])
        if word.startswith("--data-dir="):
            return Path(word.split("=", 1)[1])
    return DEFAULT_DATA_DIR


def _which_command(argv: list[str]) -> dict:
    """The name of the command that was run, and only if it is one this program has.

    Nothing else off the line. An argument here is a path to somebody's archive — the folder names
    carry surnames and often what was wrong with them — or a search, or the name of a model. The
    command's own name is this program's vocabulary and says what a person was doing, which is
    the whole of what the journal needs.
    """
    known = {one.name or (one.callback.__name__.replace("_", "-") if one.callback else "")
             for one in app.registered_commands}  # fmt: skip
    for word in argv[1:]:
        if word in known:
            return {"command": word}
        if not word.startswith("-"):
            break  # the first bare word is the command or nothing is
    return {}


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
    except NothingWhereTheArchiveWas as gone:
        # This message names no path and was written to be read by a person; the usual rule of
        # showing only the type of an exception is about messages that can quote a document.
        typer.echo(str(gone), err=True)
        raise typer.Exit(code=2) from gone
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
    data_dir: Path = typer.Option(DEFAULT_DATA_DIR, "--data-dir", help="Where sources and results are kept."),
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

    # Bound here rather than left to uvicorn, so that a port already taken is answered in this
    # program's own words. See _take_the_port.
    listening = _take_the_port(host, port, where, data_dir)

    # No access log: /browse query strings carry folder names, which must not land in logs.
    server = uvicorn.Server(uvicorn.Config(web_app, host=host, port=port, log_level="warning", access_log=False))
    original = server.startup

    async def startup(sockets=None):
        await original(sockets=sockets)
        typer.echo(f"Epicrisis Companion: {where}")

    server.startup = startup
    try:
        server.run(sockets=[listening])
    except OSError as trouble:
        typer.echo(f"Cannot listen on {host}:{port}: {trouble.strerror or trouble}. Nothing was started.", err=True)
        raise typer.Exit(code=3) from trouble


def _take_the_port(host: str, port: int, where: str, data_dir: Path) -> socket.socket:
    """The socket this dashboard will listen on, held before uvicorn starts — or a way out.

    uvicorn binds inside its own startup and answers an OSError there with `logger.error(exc)`
    and `sys.exit`, so the `except OSError` around `server.run()` never ran once: what a person
    got was uvicorn's line, in uvicorn's voice, naming the cause and nothing else —

        ERROR: [Errno 98] error while attempting to bind on address ('127.0.0.1', 8050):
               [errno 98] address already in use

    and that is the path the README walks a reader down. It has them run `serve` twice, the demo
    archive first and their own second, both times on the default port; a second server on 8050
    is the described way through this program and not a corner of it. So the port is taken here,
    where the refusal can say which address is busy, that the thing already there is probably the
    first dashboard, and the command that takes another port.
    """
    sock = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET)
    # The same option uvicorn sets. It lets a port in TIME_WAIT be taken again after a restart;
    # it does not let two servers listen on one port, so it hides nothing this refusal is about.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError as trouble:
        sock.close()
        elsewhere = invocation.run(f"serve --port {port + 1 if port < 65535 else port - 1}", data_dir)
        if trouble.errno == errno.EADDRINUSE:
            typer.echo(
                f"Something is already listening on {host}:{port}, so this dashboard did not start. "
                "Nothing was changed and nothing was read.\n"
                f"If it is another Epicrisis Companion — the demo archives, or this instance started "
                f"in another terminal — it is serving at {where} already, and that page is the one "
                "this command would have opened.\n"
                f"If it is something else, take a port of your own: {elsewhere}",
                err=True,
            )  # fmt: skip
        else:
            typer.echo(
                f"Cannot listen on {host}:{port}: {trouble.strerror or trouble}. Nothing was started.\n"
                f"A port under 1024 is the server's to give and needs root; anything above it does "
                f"not. Another port: {elsewhere}, and --host says which address to listen on.",
                err=True,
            )  # fmt: skip
        raise typer.Exit(code=3) from trouble
    return sock


SOURCE_OPTION = typer.Option(None, "--source", help="Source id. Defaults to the only registered source.")
YEARS_OPTION = typer.Option(None, "--years", help="Only files whose folder year is listed, e.g. 1992-2003 or 1992-2003,2025.")
DATA_DIR_OPTION = typer.Option(DEFAULT_DATA_DIR, "--data-dir", help="Where sources and results are kept.")


def _an_instance(data_dir: Path) -> Path:
    """The data directory of an instance that exists, resolved, or a refusal saying it does not.

    --data-dir defaults to the relative path "data", so a command run from anywhere else means a
    folder next to wherever the person is standing. For a command that reads, a folder that is not
    there is harmless. For one that writes a setting it was not: somebody whose phone had been lost
    typed the line the settings page gives them, from their home directory, and were told "The lock
    is off." What had happened was that a new ./data/ had been made beside them holding one setting,
    which no server would ever read, while the lock stayed shut over their archive — and `status`
    from the same place reported confidently on that instance-of-nothing, down to the line about the
    secret, which is read from /etc and is set whatever folder one is in.

    Two of the three commands in that same piece of advice write to /etc and work from anywhere, so
    expecting the third to was reasonable. This does not refuse a folder that is merely empty: an
    instance where the lock is set up before the first archive is added is a real instance, and its
    folder exists. What it refuses is making one.
    """
    resolved = Path(data_dir).expanduser().resolve()
    if resolved.is_dir():
        return resolved
    typer.echo(
        f"There is no data folder at {resolved}, so there is no instance of this program there. "
        "Nothing was changed, and no folder was made: one made here would hold a setting no server "
        "of yours would read, or an index of no archive.\n"
        "Say which instance with --data-dir, pointing at the folder the server runs on — the one "
        f"'{CLI} serve' was given. Run from inside that folder, plain 'data' is it. If you have no "
        "instance yet, adding an archive makes one: "
        + invocation.run("sources add <folder> --owner <name>", resolved),
        err=True,
    )  # fmt: skip
    raise typer.Exit(code=2)
WORKERS_OPTION = typer.Option(
    3, "--workers", min=1, max=8, help="Model calls at once. More is faster and uses the subscription limit sooner."
)


def _say_what_was_lost(cover: dict) -> None:
    """Lines of this archive's own files that could not be read at all, said out loud.

    A torn line is skipped so that the rest of an archive still opens, and it is counted. Nobody
    asked for the count outside one page of the dashboard, so a run from a terminal reported an
    archive that had quietly become smaller, with every number agreeing with every other.
    """
    lost = cover.get("lines_not_read") or {}
    if not lost:
        return
    for name, count in sorted(lost.items()):
        typer.echo(f"  {count} line{'s' if count != 1 else ''} of {name} could not be read, and "
                   f"{'they are' if count != 1 else 'it is'} not counted above.", err=True)  # fmt: skip
    typer.echo("  Each one is a record: a page that was classified, a value that was read, a "
               "correction somebody made. What a model wrote can be read again; corrections.jsonl "
               "and judgements.jsonl hold what a person typed, and a line lost from those is lost.",
               err=True)  # fmt: skip


def _say_what_rule_was_refused(data_dir: Path) -> None:
    """Rule files this instance could not read, said out loud wherever rules are run.

    One page of the dashboard printed these and nothing else did. A rule file edited by hand with
    one mistyped threshold is refused whole, so sixteen checks become fifteen — and from a
    terminal, which is where somebody editing a file by hand is standing, every number agreed with
    every other and nothing said a check had stopped running. Measured: one typo took
    `page_text_missing` out, and the document that would have gone to a stronger model did not.
    """
    from epicrisis.rules import load as load_rules

    for problem in load_rules(data_dir).problems:
        typer.echo(f"  {problem} — that rule is not running at all, and the checks ran without it.",
                   err=True)  # fmt: skip


def _read_index(data_dir: Path, source):
    """Open an archive's index, or say what to run first. A traceback is not an answer."""
    from epicrisis.query import IndexMissing, open_index

    try:
        return open_index(data_dir, source.id if source else None)
    except IndexMissing:
        typer.echo(f"Nothing is indexed yet. Run: {invocation.run('index', data_dir)}", err=True)
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
    from epicrisis.consent import has_consent, not_covered

    if not has_consent(data_dir, backend_name):
        # Two reasons, and they read differently to somebody who pressed the button a year ago:
        # nothing has been agreed to, or an archive has been added since and the agreement was given
        # for the archives it named. Counted rather than named — a terminal's scrollback is not a
        # page of this program, and a name here is a person's.
        added = not_covered(data_dir, backend_name)
        typer.echo(
            (f"Model processing is confirmed, but not for {len(added)} archive"
             f"{'s' if len(added) != 1 else ''} added to this instance since. " if added else
             "Model processing is not confirmed. ")
            + "Review and confirm it once, on the page that says exactly what would go and where, "
              f"for every archive on the list: run {CLI} serve and open /consent on it.",
            err=True,
        )  # fmt: skip
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
    from epicrisis.datesearch import LOCK_NAME, documents_without_a_date, search_source

    backend = engines.date_search(data_dir)
    registry, source, output = _prepare_model_step(data_dir, source_id, backend.name, lambda path: is_running(path, LOCK_NAME))
    # Both numbers below are the length of this one list, asked before the run and again after it.
    # They were two walks of the documents with two filters: this one left blank pages out — a
    # blank page is a kind of document and has no date to find — and the one that printed the
    # second number did not. So an archive with blank pages was told "Documents without a date: 4"
    # and, underneath, "Documents still without a date: 7", even where a date had been found on
    # every one of the four.
    targets = documents_without_a_date(source, output)
    stats = search_source(registry.data_dir, source, backend, targets, workers=workers)
    typer.echo(
        f"Documents without a date: {len(targets)}. This run: searched {stats.searched}, with dates found "
        f"{stats.with_dates}, unreadable {stats.unreadable}, failed {stats.failed}"
    )
    if stats.stopped == "usage_limit":
        typer.echo("Stopped at the subscription usage limit. Run the same command later to continue.")
    typer.echo(f"Documents still without a date: {len(documents_without_a_date(source, output))}")


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
    found_by = rules_on(data_dir, rules.load(data_dir), kinds.SUSPECTS,
                        in_archive=showing.id if showing else "")
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
    """The service runs as its own user, so the secret it checks codes against is theirs to read.

    The doing lives in `mcp_lock`, beside the one function that creates a secret file: the
    registry of connectors creates one per link, and two copies of this would be two answers to
    "who may read a secret of this program".
    """
    from epicrisis.mcp_lock import let_the_server_read

    let_the_server_read(file)


@app.command(name="mcp-secret")
def mcp_secret(
    out: Path = typer.Argument(Path("/etc/epicrisis/mcp-token"), help="Where to keep it. Only root and the server's group read it."),
    force: bool = typer.Option(False, "--force", help="Replace a secret that is already there."),
) -> None:  # fmt: skip
    """Make the secret that stands in the served path, for reaching this archive over the network.

    `mcp --http` refuses to start without one, and there was no way to make it: the README
    described the lock and named no command, so a person had to work out for themselves that a
    file of at least thirty-two characters was wanted, and invent it.

    This is the first of the three locks and the weakest of them: it says where a request came
    from and nothing about who sent it. Set the code from an authenticator up as well
    (`epicrisis mcp-lock init`), which is the part a stranger cannot copy out of an address bar.
    """
    from epicrisis.mcp_lock import write_secret
    from epicrisis.mcp_server import new_path_secret

    if out.exists() and not force:
        typer.echo(f"{out} is already there. Use --force to replace it — every address made from "
                   "the old one stops working.", err=True)  # fmt: skip
        raise typer.Exit(code=2)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        written = write_secret(new_path_secret(), out)
        _let_the_server_read(written)
    except OSError as problem:
        typer.echo(f"Cannot write {out}: {problem}. Run this as root.", err=True)
        raise typer.Exit(code=2) from problem
    typer.echo(f"Kept in {written}. Start the server with: {CLI} mcp --http --secret-file {written}")
    typer.echo("The secret is the address. It is not printed here; read it out of that file when "
               "you set the connector up, and send it nowhere else.")  # fmt: skip


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
        typer.echo(f"\nKept in {written}. Turn the lock on with: {CLI} mcp-lock on")
        return
    if action == "clear":
        from epicrisis.mcp_lock import every_wait_kept, whoever_is_waiting

        data_dir = _an_instance(data_dir)
        # Every wait there is, and not only the instance's. Each link counts wrong codes on its
        # own — one person guessing badly must not hold the others out — so there is a file per
        # link, and this command knew about none of them: somebody locked out of their own link
        # ran the way out that is written down and nothing happened.
        #
        # It takes every file, and it says how many of them were holding anybody out. A file whose
        # run of wrong codes was answered correctly, or has aged out of the window, is litter and
        # not a wait — and "1 wait cleared" over such a file told somebody their way out had done
        # something when there had been nothing to do.
        kept, held = every_wait_kept(data_dir), whoever_is_waiting(data_dir)
        for file in kept:
            file.unlink(missing_ok=True)
        if held:
            typer.echo(f"{len(held)} wait{'s' if len(held) != 1 else ''} cleared in {data_dir}: "
                       "whoever was being kept out can try a code again now.")  # fmt: skip
        elif kept:
            # Not "past its wait": a run that never reached the count has no wait either. What
            # both have in common is the thing a person cares about — nobody was being held out.
            typer.echo(f"There was no wait to clear in {data_dir}. {len(kept)} file"
                       f"{'s' if len(kept) != 1 else ''} of wrong codes that "
                       f"{'were' if len(kept) != 1 else 'was'} holding nobody out "
                       f"{'were' if len(kept) != 1 else 'was'} taken away.")  # fmt: skip
        else:
            typer.echo(f"There was no wait to clear in {data_dir}.")
        typer.echo("The server reads these on the next code; no restart needed.")
        return
    if action in ("on", "off"):
        if action == "on" and not read_secret():
            typer.echo(f"No secret yet. Run: {CLI} mcp-lock init", err=True)
            raise typer.Exit(code=2)
        data_dir = _an_instance(data_dir)
        set_mcp_lock(data_dir, action == "on")
        typer.echo(f"The lock is {'on' if action == 'on' else 'off'} in {data_dir}. "
                   "The server reads this on the next call; no restart needed.")  # fmt: skip
        return
    if action == "scope":
        if value not in SCOPES:
            typer.echo(f"Say one of: {', '.join(SCOPES)}. conversation: a code opens the conversation it was given in."
                       " server: one code opens everything until the window runs out.", err=True)  # fmt: skip
            raise typer.Exit(code=2)
        data_dir = _an_instance(data_dir)
        set_mcp_lock_scope(data_dir, value)
        typer.echo(f"A code now opens: {value}, in {data_dir}.")
        return
    if action == "window":
        data_dir = _an_instance(data_dir)
        try:
            set_mcp_lock_minutes(data_dir, int(value))
        except (TypeError, ValueError) as problem:
            typer.echo("Say the window in minutes, from 1 to 10080.", err=True)
            raise typer.Exit(code=2) from problem
        typer.echo(f"A code now opens the archive for {mcp_lock_minutes(data_dir)} minutes, in {data_dir}.")
        return
    if action != "status":
        typer.echo("Say one of: status, init, on, off, scope, window, clear.", err=True)
        raise typer.Exit(code=2)
    data_dir = _an_instance(data_dir)
    typer.echo(f"Of the instance in {data_dir}")
    # Whether anything below was chosen here at all. Over a settings file that will not parse every
    # reader in this program answers with its own default, which is right — and this command printed
    # those defaults as a calm report and said nothing about the file. An owner working out why the
    # lock is behaving as it is (a lost phone, a clock that drifted) read "a code opens the
    # conversation, for 240 minutes" over a file that says 120 and is not being read by anybody. The
    # settings page has said this in full all along; settings.unreadable() answers it in one call.
    from epicrisis.settings import SETTINGS_FILE
    from epicrisis.settings import unreadable as settings_unreadable

    on_its_defaults = settings_unreadable(data_dir)
    if on_its_defaults:
        typer.echo(f"{SETTINGS_FILE} is there and cannot be read, so what this instance was told is "
                   "not being read by anything: the two lines below are this program's own "
                   "defaults and not what was chosen here, and nothing can be stored until that "
                   "file is put right. The lock itself stays on wherever a code was ever set up, "
                   "because reading it fails closed. "
                   f"Repair it, or copy back {SETTINGS_FILE}.previous beside it — the version "
                   "before the last change.")  # fmt: skip
    default = " (a default: the file above cannot be read)" if on_its_defaults else ""
    typer.echo(f"Lock: {'on' if mcp_lock_on(data_dir) else 'off'}{default}")
    typer.echo(f"A code opens: {mcp_lock_scope(data_dir)}, for {mcp_lock_minutes(data_dir)} minutes{default}")
    typer.echo(f"Secret: {'set' if read_secret() else 'not set'} ({SECRET_FILE})")
    # The clock, so that a code refused as wrong can be told from a code refused because this
    # machine does not know what time it is. Comparing it with the phone takes a glance.
    typer.echo(f"This server's clock: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC — compare it "
               "with the phone that makes the codes; a code from a clock that has drifted is refused.")  # fmt: skip
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
    from epicrisis.validate import validate_source, vocabulary

    registry = SourceRegistry(_an_instance(data_dir))
    sources = registry.list()
    source = registry.get(source_id) if source_id else (sources[0] if len(sources) == 1 else None)
    if source is None:
        if not sources:
            # An instance that is there and holds nothing is a different answer from a folder that
            # is not an instance at all, and neither one is "choose a source with --source: ".
            typer.echo("No archive here yet. Add one: "
                       + invocation.run("sources add <folder> --owner <name>", registry.data_dir), err=True)  # fmt: skip
        else:
            typer.echo("Choose a source with --source: " + ", ".join(s.id for s in sources), err=True)
        raise typer.Exit(code=2)
    output = source_output_dir(registry.data_dir, source.id)
    if not (output / layout.CLASSIFY).exists():
        typer.echo("Run classify for this source first.", err=True)
        raise typer.Exit(code=2)
    _say_what_rule_was_refused(registry.data_dir)
    result = validate_source(output, Path(source.path))
    cover = result["coverage"]
    typer.echo(
        f"Coverage: files {cover['files']}, not read {len(cover['files_not_read'])}; pages {cover['pages']}, "
        f"not classified {cover['pages_not_classified']}; documents due {cover['documents_due']}, "
        f"not transcribed {len(cover['documents_not_transcribed'])}"
    )
    _say_what_was_lost(cover)
    for gap in cover["files_not_read"]:
        typer.echo(f"  file {gap['file_id']} not read: {gap['reason']}")
    typer.echo(f"Documents checked: {result['documents_checked']}, with findings: {len(result['documents'])}")
    for code, said in vocabulary(data_dir).items():
        documents = sum(1 for document in result["documents"] if code in document["findings"])
        if documents:
            typer.echo(f"  {said['label']}: {documents} documents, {result['totals'][code]} findings")


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
def people(
    propose: bool = typer.Option(False, "--propose", help="Ask a model which printed names are one doctor, or one place."),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:
    """Doctors and institutions: printed names grouped under one label. Nothing is ever joined here.

    Unlike the indicators, no answer from a model is applied, however sure it says it is. The
    difference is not that this mistake costs more — it does, since being wrong here says two human
    beings are one — but that nothing on the screen could show it was wrong: no document anywhere
    says whether two "surname plus one initial" are the same person, while two spellings of a test
    sit side by side under their label and a wrong one is plain to see. Every group waits on the
    "Doctors and clinics" page for somebody to press a button.
    """
    import tempfile

    from epicrisis import people as store
    from epicrisis import query as query_index
    from epicrisis.people_proposals import ProposalBackend, names_to_ask_about, propose_people
    from epicrisis.sources import showing as sources_showing

    # Before anything is counted. The docstring of this function has promised since it was written
    # that the move is done "by the page and by the command line", and no command called it: a
    # person who restored data/people.json from an old copy and ran this was told "0 joined by
    # you" while their own work sat in a file beside the instance. The page is not an answer for
    # somebody working in a terminal, and this is the one command this file is about.
    carried = store.carry_the_old_file_in(data_dir)
    for source_id, how_many in sorted(carried.items()):
        typer.echo(f"Carried {how_many} group(s) from {store.FILE_NAME} beside this instance into "
                   f"the archive {source_id}, which prints those names.")  # fmt: skip
    waiting_outside = store.still_beside_the_instance(data_dir)
    if waiting_outside:
        # Said whether anything moved or not, because the case that matters is the one where
        # nothing could: a group naming nobody this server has an index for, or one belonging to
        # an archive that already has a people.json of its own. It used to wait there with nothing
        # anywhere saying it was waiting.
        typer.echo(
            f"{data_dir / store.FILE_NAME} still stands beside this instance, holding "
            f"{waiting_outside} group(s) joined by hand. Nothing is read from there. It is still "
            f"here because at least one of them has been carried nowhere: it names nobody this "
            f"server has an index for, or belongs to an archive that already has a "
            f"{store.FILE_NAME} of its own. What an archive here does name is already inside it. "
            f"Read those documents, or add the archive that prints those names, and the rest moves "
            f"by itself. Deleting that file loses the work: nothing makes it again."
        )
    showing = sources_showing(data_dir)
    connection = _read_index(data_dir, showing)
    makers = query_index.who_made_them(connection, store.load(data_dir, showing.id))
    connection.close()
    if propose:
        _require_consent(data_dir, engines.engine_name(data_dir))
        with tempfile.TemporaryDirectory(prefix="epicrisis-people-") as workdir:
            from epicrisis.models import model_for

            counts = propose_people(data_dir, showing.id, makers, ProposalBackend(model=model_for(data_dir, "strong"), data_dir=data_dir),
                                    Path(workdir), say=typer.echo)  # fmt: skip
        typer.echo(
            f"Asked about {counts['asked']} names in {counts['calls']} call(s); {counts['proposed']} group(s) "
            f"waiting for you on the Doctors and clinics page"
            + (f"; {counts['left_out']} names did not fit in one call" if counts["left_out"] else "")
        )
    groups = store.load(data_dir, showing.id)
    for kind in store.KINDS:
        here = [one for one in makers if one["what"] == kind]
        typer.echo(
            f"{kind.capitalize()}s: {len(here)} printed names, {len(store.settled(groups, kind))} joined by you, "
            f"{len(store.waiting(groups, kind))} waiting; "
            f"{len(store.worth_joining(kind, [one['name'] for one in here]))} pairs the word count offers, "
            f"{len(names_to_ask_about(makers, kind, groups))} names a model has not been asked about"
        )


@app.command()
def mcp(
    data_dir: Path = DATA_DIR_OPTION,
    http: bool = typer.Option(False, "--http", help="Serve over HTTP instead of stdio, for a Claude connector."),
    secret_file: Path = typer.Option(None, help="File holding a link's path secret, checked against the registry and nothing more. Not needed: every live link the registry holds is served."),
    host: str = typer.Option("127.0.0.1", help="Address to listen on. Keep it local and put a tunnel in front."),
    port: int = typer.Option(8051, help="Port to listen on with --http."),
    public_host: str = typer.Option(None, help="The name the tunnel answers on, for instance epicrisis.example.ts.net. Taken from the settings page when it is not given here."),
    allow_from: str = typer.Option(
        "160.79.104.0/21",
        help="Networks allowed to reach it through the tunnel, comma separated. The default is the range Anthropic publishes for its connectors; this machine and private networks are always allowed. An empty value lets anyone in.",
    ),
    source_id: str = typer.Option(
        None, "--source",
        help="Serve this one archive, whatever the dashboard is showing. For a question asked about one person, so that switching archive while it is being answered cannot move it to another.",
    ),  # fmt: skip
) -> None:
    """Serve the archive as read-only MCP tools: over stdio for Claude Code, or over HTTP for a connector."""
    from epicrisis.mcp_server import read_path_secret, run, run_http

    if not http:
        run(data_dir, pinned_to=source_id)
        return
    # The secret is no longer something the server is started with: every live link in the
    # registry is served, so one issued on the page works without a restart and a revoked one
    # stops the same way. The flag is kept because it is in the README and in whatever anybody has
    # in a service file, and it now does one useful thing — it checks that the secret in that
    # file is a link the registry holds, and says what to do when it is not. Starting the server
    # on a secret nothing has carried in would have served nothing and said nothing.
    from epicrisis import connectors
    from epicrisis import mcp_lock as mcp_lock_module

    if secret_file is not None:
        try:
            secret = read_path_secret(secret_file)
        except (OSError, ValueError) as problem:
            typer.echo(str(problem), err=True)
            raise typer.Exit(code=2) from problem
        if not any(one.live and one.path == secret for one in connectors.load(data_dir)):
            typer.echo(f"The secret in {secret_file} is not a link this instance has issued, so "
                       f"nothing would answer on it. Carry it in with "
                       + invocation.run("connector carry-in", data_dir)
                       + ", or drop --secret-file: every link on the registry is served.", err=True)  # fmt: skip
            raise typer.Exit(code=2)
    issued = connectors.load(data_dir)
    # Made here as well as where a link is issued: this server cannot make it — it runs with the
    # data directory read-only and this one folder mounted in — so a fresh machine would serve
    # with its waits living in memory alone. Tried before the warning below, so the warning is
    # about a folder that could not be made rather than one nobody had made yet.
    mcp_lock_folder = mcp_lock_module.make_the_place_for_waits(data_dir)
    live = [one for one in issued if one.live]
    if not live:
        # Said apart from "none has been issued", because the two are different situations and
        # the second one is a server that worked yesterday. A person reading "no link has been
        # issued" on a machine holding four of them goes looking for a lost file.
        ended = [one for one in issued if one.expired()]
        typer.echo(
            (f"Every link here has stopped answering: {len(ended)} past its last day. Give one a "
             f"later day — " + invocation.run("connector until <id> <day>", data_dir) + " — or "
             "make a new one." if ended else
             "No link has been issued, so nothing can reach this server. Make one on the settings "
             "page, or with " + invocation.run("connector add", data_dir)),
            err=True)  # fmt: skip
        raise typer.Exit(code=2)
    # The flag wins where it is given, and the setting answers where it is not: the instance now
    # knows its own public name, and a request arriving through a tunnel under a name nothing
    # allows is refused before it reaches the archive. Two answers to one question is what
    # ARCHITECTURE forbids, so the flag is read as "this once, instead" and nothing is written.
    if public_host is None:
        from epicrisis.settings import the_name_the_tunnel_answers_on

        public_host = the_name_the_tunnel_answers_on(data_dir) or None
        if public_host:
            typer.echo(f"Answering as {public_host}, as the settings page says.")
    # The nearest end, out loud at the start: a link stops answering on its own here, and nothing
    # anywhere warns the person holding it. The log of calls shows a connector going quiet and
    # says nothing about why, so the one place this can be said is where the server says what it
    # is serving. §7.
    ending = sorted(one.until for one in live if one.until)
    typer.echo(f"Epicrisis MCP on http://{host}:{port}/mcp/<secret>, "
               f"{len(live)} link{'s' if len(live) != 1 else ''} answering"
               + (f", the first of them until {ending[0]}" if ending else ", none with an end"))  # fmt: skip
    if not allow_from.strip():
        typer.echo("Warning: no source filter. Anyone who learns the address may try the secret.", err=True)
    # The lock is a setting, and a setting is a thing somebody turned off nine days ago and does
    # not remember. This server started in silence all that time, and its owner learnt that his
    # archive was answering without a code by watching an assistant answer without asking for one.
    # The seventh entry of the constitution is about exactly this: the program says what it does.
    from epicrisis.settings import mcp_lock_on

    # What the lock can and cannot keep, said where the server says what it is serving. A wait
    # that does not outlive a restart is a wait somebody patient simply waits out, and the only
    # sign of it was a silent `writes = False` inside one object.
    if mcp_lock_folder is None and not mcp_lock_module.the_waits_can_be_kept(data_dir):
        typer.echo(f"The runs of wrong codes cannot be written to "
                   f"{data_dir}/{mcp_lock_module.WRONG_CODES_FOLDER}, so the growing wait after "
                   "wrong codes lasts only until this server is restarted. Make that folder "
                   "writable by whoever this service runs as. The unit names it in "
                   "ReadWritePaths, with a leading dash so that its absence cannot stop the "
                   "server — which is also why nothing said this until now.", err=True)  # fmt: skip
    if not mcp_lock_on(data_dir):
        typer.echo("The six-digit code is OFF for this instance: whoever has a link's address "
                   "reads that archive without one. The address and the tunnel say where a "
                   "request came from and nothing about who sent it. Turn it on under Settings "
                   "-> Over the network.", err=True)  # fmt: skip
    run_http(data_dir, host=host, port=port, public_host=public_host, allow_from=allow_from)


connector = typer.Typer(help="The MCP links this instance has issued, and which archives each may open.")
app.add_typer(connector, name="connector")


@connector.command("list")
def connector_list(data_dir: Path = DATA_DIR_OPTION) -> None:
    """Every link issued, what it may open, and which of them have been revoked.

    No secret is printed, here or anywhere else after the moment a link is issued: the path is the
    address, and a terminal keeps scrollback.
    """
    from epicrisis import connectors
    from epicrisis.sources import SourceRegistry

    data_dir = _an_instance(data_dir)
    issued = connectors.load(data_dir)
    if not issued:
        typer.echo("No link has been issued. Make one: "
                   + invocation.run("connector add --name <what to call it>", data_dir))
        return
    archives = SourceRegistry(data_dir).list()
    for one in issued:
        may_open = connectors.the_archives_it_may_open(one, archives)
        # By owner and never by id: a list of random ids is a list nobody can act on, and the
        # owners of these archives are the words the person who issued the link was thinking in.
        whose = ", ".join(each.owner or "nobody named" for each in may_open) or "nothing"
        # Three states and not two, and the middle one said as what it is: a link past its last
        # day answers nothing, exactly as a revoked one does, and is the only one of the three
        # that comes back when somebody types a later date.
        if one.revoked_at:
            when = f"revoked {one.revoked_at}"
        elif one.expired():
            when = f"ended {one.until}"
        else:
            when = f"issued {one.issued_at}" + (f", until {one.until}" if one.until else "")
        typer.echo(f"{one.id}  {one.name or 'unnamed':24}  {when}  may open: {whose}")
    # And the other direction: ids the log of calls names that this registry does not hold. A line
    # here stays when a link is taken back, precisely so that the journal and the access log go on
    # naming something — and the file was edited by hand during the registry's own building, which
    # left thirteen calls pointing at five ids that name nothing. Nothing said so; the log simply
    # had strangers in it. This is the only place both lists are in one hand.
    stray = connectors.ids_the_log_names_that_are_not_here(data_dir)
    if stray:
        typer.echo(f"\n{len(stray)} id{'s' if len(stray) != 1 else ''} in the log of calls "
                   f"{'name' if len(stray) != 1 else 'names'} no link here: {', '.join(sorted(stray))}.\n"
                   "A revoked link keeps its line on purpose, so this means a line was removed "
                   "rather than revoked. Nothing is broken by it; the log is simply unreadable "
                   "where those ids appear.")  # fmt: skip


@connector.command("add")
def connector_add(
    name: str = typer.Option("", "--name", help="What to call it on the page. Your own words; it is the only thing you type."),
    archive: list[str] = typer.Option([], "--archive", help="The id of an archive this link may open. Repeat it for several."),
    until: str = typer.Option("", "--until", help="The last day it answers, as 2027-03-31, that day included. Left out, the link has no end."),
    data_dir: Path = DATA_DIR_OPTION,
    secrets_folder: Path = typer.Option(None, help="Where to keep its code secret. The default is /etc/epicrisis/connectors."),
) -> None:  # fmt: skip
    """Issue a link: its address, and the code secret to read into an authenticator once.

    Both are printed once and never again. The code secret cannot be fetched a second time by any
    command here — that is deliberate, and losing it before the phone is set up costs one
    `connector revoke` and one `connector add`.
    """
    from epicrisis import connectors
    from epicrisis.mcp_lock import uri
    from epicrisis.sources import SourceRegistry

    data_dir = _an_instance(data_dir)
    known = {one.id for one in SourceRegistry(data_dir).list()}
    unknown = [one for one in archive if one not in known]
    if unknown:
        # Refused rather than written: an id that is on no archive opens nothing, so a link made
        # with a typo would look issued and reach nothing, and nothing on the page would say why.
        typer.echo(f"No archive here has the id {', '.join(unknown)}. "
                   + invocation.run("connector list", data_dir) + " shows the ids.", err=True)  # fmt: skip
        raise typer.Exit(code=2)
    if until.strip():
        # Read before anything is written, as the page reads it: a link issued and then refused
        # its date would be a credential handed over that this command had not meant to make.
        try:
            connectors.a_day(until)
        except ValueError as not_a_day:
            typer.echo(f"{not_a_day}. Nothing was issued.", err=True)
            raise typer.Exit(code=2) from not_a_day
    try:
        made, code_secret = connectors.issue(data_dir, name=name, archives=tuple(archive),
                                             until=until, secrets_folder=secrets_folder)  # fmt: skip
    except OSError as problem:
        typer.echo(f"Cannot write the code secret: {problem}. Run this as root.", err=True)
        raise typer.Exit(code=2) from problem
    typer.echo(f"Link {made.id} issued"
               + (f", and it answers until {made.until} inclusive." if made.until else ", with no end.")
               + ("" if archive else " It may open nothing yet: give it archives with --archive, "
                  "or on the settings page."))  # fmt: skip
    typer.echo("")
    typer.echo(f"  The address:  /mcp/{made.path}")
    typer.echo(f"  The code:     {uri(code_secret, account=made.name or made.id)}")
    typer.echo("")
    typer.echo("Read that second line into an authenticator now. Neither line is printed again by "
               "any command, and the code secret is in no file this program will show you.")  # fmt: skip


@connector.command("carry-in")
def connector_carry_in(
    data_dir: Path = DATA_DIR_OPTION,
    secrets_folder: Path = typer.Option(None, help="Where to keep its code secret."),
) -> None:  # fmt: skip
    """Write the pair of secrets this machine already has down as its first link.

    Before the registry there was one path secret and one code secret, and together they opened
    the whole instance. That pair is still on the machine and still in somebody's phone, so it is
    carried in rather than replaced: the address they use goes on working and their authenticator
    goes on being accepted, until they revoke it themselves.

    It is given every archive, because that is what it opens today. Narrowing it here would be
    this program deciding what somebody may see.
    """
    from epicrisis import connectors
    from epicrisis.sources import SourceRegistry

    data_dir = _an_instance(data_dir)
    archives = tuple(one.id for one in SourceRegistry(data_dir).list())
    try:
        made = connectors.carry_the_one_secret_in(data_dir, archives, secrets_folder=secrets_folder)
    except OSError as problem:
        typer.echo(f"Cannot write the code secret: {problem}. Run this as root.", err=True)
        raise typer.Exit(code=2) from problem
    if made is None:
        typer.echo("Nothing to carry in: either this machine has no such pair of secrets, or the "
                   "pair it has is already on the list. Nothing was written.")  # fmt: skip
        return
    typer.echo(f"Carried in as {made.id}, with every archive here ({len(made.archives)}). The "
               "address and the code that were already in use go on working unchanged.")  # fmt: skip


@connector.command("rename")
def connector_rename(
    connector_id: str = typer.Argument(..., help="The id of the link, as `connector list` prints it."),
    name: str = typer.Argument(..., help="What to call it."),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:  # fmt: skip
    """Change what a link is called. Nothing else about it moves."""
    from epicrisis import connectors

    data_dir = _an_instance(data_dir)
    if connectors.rename(data_dir, connector_id, name) is None:
        typer.echo(f"No link here has the id {connector_id}.", err=True)
        raise typer.Exit(code=2)
    typer.echo(f"{connector_id} is now called {name!r}.")


@connector.command("until")
def connector_until(
    connector_id: str = typer.Argument(..., help="The id of the link, as `connector list` prints it."),
    day: str = typer.Argument(..., help="The last day it answers, as 2027-03-31, that day included. The word `forever` takes the end off."),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:  # fmt: skip
    """Set, move or take off the last day a link answers. Nothing else about it moves.

    One command for all three, because they are one fact being written: a later day is an
    extension, an earlier one brings the end forward, and `forever` is a link with no end. The
    address and the authenticator are untouched by every one of them, which is the whole point of
    a date rather than a revoke — a link stopped this way can be started again, and a revoked one
    cannot.

    A day in the past is allowed: it is how somebody stops a link today and keeps the phone it was
    set up on. What stops answering stops silently, as a revoked link does and for the same
    reason — whoever holds it must not be able to tell an address that has ended from one that
    never existed.
    """
    from epicrisis import connectors

    data_dir = _an_instance(data_dir)
    # One word rather than an empty argument, because an empty one is what a shell sends by
    # accident: `connector until <id> ""` would be a slip that takes the end off a link.
    wanted = "" if day.strip().lower() in ("forever", "never", "none") else day
    try:
        moved = connectors.set_until(data_dir, connector_id, wanted)
    except ValueError as not_a_day:
        typer.echo(f"{not_a_day}. Nothing was changed; `forever` takes the end off.", err=True)
        raise typer.Exit(code=2) from not_a_day
    if moved is None:
        typer.echo(f"No link here has the id {connector_id}.", err=True)
        raise typer.Exit(code=2)
    if not moved.until:
        typer.echo(f"{connector_id} has no end: it answers until it is revoked.")
        return
    typer.echo(f"{connector_id} answers until {moved.until} inclusive"
               + (", which has gone by, so it answers nothing now. Its code secret is still on "
                  "this machine, so a later day here starts it again; `connector revoke` is what "
                  "takes the secret off." if moved.expired() else "."))  # fmt: skip


@connector.command("revoke")
def connector_revoke(
    connector_id: str = typer.Argument(..., help="The id of the link, as `connector list` prints it."),
    data_dir: Path = DATA_DIR_OPTION,
    secrets_folder: Path = typer.Option(None, help="Where its code secret is kept."),
) -> None:  # fmt: skip
    """Stop a link working and take its code secret off the machine.

    The line stays on the list with the moment it was revoked, because the journal and the access
    log name ids and an id that names nothing makes both unreadable.
    """
    from epicrisis import connectors

    data_dir = _an_instance(data_dir)
    gone = connectors.revoke(data_dir, connector_id, secrets_folder=secrets_folder)
    if gone is None:
        typer.echo(f"No live link here has the id {connector_id}.", err=True)
        raise typer.Exit(code=2)
    typer.echo(f"{connector_id} is revoked. Its address answers nothing, and its code secret is "
               "off this machine. Whoever held it needs a new link.")  # fmt: skip


sources = typer.Typer(help="The archives this instance holds. Adding one reads nothing and sends nothing.")
app.add_typer(sources, name="sources")


@sources.command("add")
def sources_add(
    folder: Path = typer.Argument(..., help="The folder of documents. It is only ever read."),
    owner: str = typer.Option("", "--owner", help="Whose records these are. Every page carries the name."),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:  # fmt: skip
    """Add a folder of documents as an archive. Nothing in it is renamed, moved or changed.

    The dashboard does this too, with a folder picker, and that is the easier way. This is here
    because it is the way the README and this program's own messages have always named — and for
    two versions it named a command that did not exist, which left a person who had installed
    everything and liked the demo with nowhere to go.
    """
    from epicrisis.sources import SourceError, SourceRegistry

    registry = SourceRegistry(data_dir)
    if not owner.strip():
        # Whose records these are is not decoration: every page carries the name and every answer
        # the tools give says it. An archive added without one reads as nobody's.
        typer.echo("Say whose records these are: --owner \"Their name\".", err=True)
        raise typer.Exit(code=2)
    try:
        # Typed, not picked: the folders a page may wander in do not bound a path somebody wrote
        # out themselves. A disk of scans of its own is the ordinary case, and this is the line the
        # dashboard's own refusal now names.
        added = registry.add(str(folder), owner, typed=True)
    except SourceError as wrong:
        typer.echo(str(wrong), err=True)
        raise typer.Exit(code=2) from wrong
    if len(registry.list()) == 1:
        registry.set_active(added.id)
    typer.echo(f"Added the archive of {added.owner}: {added.path}")
    typer.echo(f"Nothing has been read yet. Next: {invocation.run('serve', registry.data_dir)}, "
               "and say yes on the page that says what would be sent.")  # fmt: skip


@sources.command("set-path")
def sources_set_path(
    source_id: str = typer.Argument(..., help=f"The id of the archive, as '{CLI} sources list' prints it."),
    folder: Path = typer.Argument(..., help="Where that folder is now. It is only ever read."),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:  # fmt: skip
    """Point an archive at the folder it has moved to, keeping everything already read from it.

    For a disk remounted somewhere else, documents carried to a bigger drive, a machine rebuilt.
    Use this rather than adding the folder again: adding it again makes a second archive of the
    same person under a new id, leaves the first one on the list pointing at nothing, and puts
    every hour of reading — the classification, the transcriptions, the checks, the index and the
    corrections you typed by hand — under an id the new archive cannot see.

    Nothing read is tied to where the folder is: a file is known by the sha256 of its contents, and
    where it sits is stored relative to the root of the archive. So this is the whole of what
    moving an archive costs.
    """
    from epicrisis.sources import SourceError, SourceRegistry

    registry = SourceRegistry(data_dir)
    try:
        moved = registry.set_path(source_id, str(folder), typed=True)
    except SourceError as wrong:
        typer.echo(str(wrong), err=True)
        raise typer.Exit(code=2) from wrong
    if moved is None:
        typer.echo(f"No archive of this instance has the id {source_id}. "
                   f"The ids are in: {invocation.run('sources list', registry.data_dir)}", err=True)  # fmt: skip
        raise typer.Exit(code=2)
    typer.echo(f"The archive of {moved.whose} is now read from {moved.path}")
    typer.echo("Everything already read from it is kept, and so are the corrections. "
               f"Next: {invocation.run('update', registry.data_dir)}, which walks the folder again "
               "and reads only what is new.")  # fmt: skip


@app.command()
def backup(
    into: Path = typer.Argument(..., help="A folder outside this instance to copy into."),
    data_dir: Path = DATA_DIR_OPTION,
) -> None:  # fmt: skip
    """Copy out the part of this instance that nothing can rebuild. A few megabytes, not the scans.

    The index rebuilds in seconds and the checks with it. The readings rebuild only by paying a
    model to read every document again, differently. What rebuilds by nothing at all is what you
    typed yourself: your corrections against your own printed lines, your verdicts on findings, the
    groups of spellings you approved one at a time, the earlier readings kept when a later one
    displaced them, and your conversations. Those are what this copies, into a folder you name,
    outside this instance.

    The scans are not copied: they are yours already, in the folder you pointed this at, which
    nothing here ever writes to.
    """
    from epicrisis.backup import UNREADABLE_SUFFIX as BACKUP_UNREADABLE, back_up

    resolved = _an_instance(data_dir)
    from epicrisis.state import no_space

    try:
        copied = back_up(resolved, into)
    except OSError as trouble:
        if no_space(trouble):
            raise  # run() says what a full disk means, in a sentence, and leaves with 4
        typer.echo(f"The copy could not be made: {trouble.strerror or trouble}. Nothing was changed.", err=True)
        raise typer.Exit(code=2) from trouble
    except ValueError as wrong:
        typer.echo(str(wrong), err=True)
        raise typer.Exit(code=2) from wrong
    if copied.unreadable:
        # Loud, and before the list of what went: this is the one thing a person must not miss.
        typer.echo("These files of this instance no longer read as what they are:", err=True)
        for name in copied.unreadable:
            typer.echo(f"  {name}", err=True)
        if copied.kept_instead:
            typer.echo("The whole copy already in that folder was kept for each of them; the "
                       "unreadable one is beside it, ending in " + BACKUP_UNREADABLE + ", so that "
                       "nothing of either is lost. Put the whole copy back rather than this one.", err=True)  # fmt: skip
        else:
            typer.echo("Nothing of them was in that folder yet, so they went as they are. A copy of "
                       "a file that will not read is still better than none, and it is not the copy "
                       "to put back.", err=True)  # fmt: skip
    if not copied.files:
        typer.echo(f"Nothing to copy: this instance holds none of the files a person makes by hand yet. "
                   f"They appear under {resolved} as soon as you correct a line, judge a finding or "
                   "approve a group of spellings.")  # fmt: skip
        return
    typer.echo(f"Copied {copied.files} files, {copied.bytes / 1024:.0f} KB, into {Path(into).expanduser().resolve()}")
    for taken in copied.took:
        typer.echo(f"  {taken}")
    # Said from the same lists the copy is chosen by, so that a file moved from one list to the
    # other cannot leave this sentence describing the arrangement before last.
    typer.echo("Left behind on purpose: " + ", ".join(layout.MADE_AGAIN_BY_CODE)
               + " and the index, which code makes again in seconds; and " + ", ".join(layout.MADE_AGAIN_BY_A_MODEL)
               + ", which only a model makes again — for money, for hours, and differently. "
               + ", ".join(layout.ASKED_FOR_AGAIN) + " is left because a restored copy should ask, not assume.")  # fmt: skip
    if copied.missing:
        typer.echo("None of these in this instance yet: " + ", ".join(copied.missing))
    typer.echo("Putting it back: copy these files into the data folder of an instance, keeping the "
               f"folders they are in, and run '{invocation.run('update')} --data-dir <that folder>'. "
               "sources.json goes back with them, "
               "which is what makes the rest of it findable: the folder each archive's work sits in "
               "is named by an id that lives only in that file. No version of this program is needed "
               "to read any of it.")  # fmt: skip


@sources.command("list")
def sources_list(data_dir: Path = DATA_DIR_OPTION) -> None:
    """The archives this instance holds, which one is open, and any whose folder is not there."""
    from epicrisis.sources import SourceRegistry, folder_is_there

    data_dir = _an_instance(data_dir)
    registry = SourceRegistry(data_dir)
    listed = registry.list()
    if not listed:
        typer.echo("No archive here yet. Add one: "
                   + invocation.run("sources add <folder> --owner <name>", data_dir))
        # Said here too, and here most of all: a list that came back empty over folders full of
        # work is the state somebody reaches by putting back a copy older than they thought.
        _work_no_archive_names(data_dir, listed)
        return
    open_now = registry.active()
    gone = []
    for source in listed:
        here = " (open)" if open_now and open_now.id == source.id else ""
        there = folder_is_there(source.path)
        if not there:
            gone.append(source)
        typer.echo(f"{source.id}  {source.owner or 'nobody named'}{here}  {source.path}"
                   + ("" if there else "  <- not there now"))  # fmt: skip
    _folders_not_where_they_were(data_dir, gone)
    _work_no_archive_names(data_dir, listed)


def _folders_not_where_they_were(data_dir: Path, gone: list) -> None:
    """Archives on the list whose folder is not there, said rather than printed as if it were.

    This is the one command that shows the folders, and it showed a path to nothing exactly as it
    shows a path to an archive — no mark, no sentence, nothing. A folder renamed and a disk that
    did not mount are the ordinary reasons, and the moment somebody asks for this list is usually
    just after one of them. The status page answers the same state well and these are its words;
    `epicrisis update` answers it honestly too. The terminal was the door that did not.
    """
    if not gone:
        return
    typer.echo("")
    for source in gone:
        typer.echo(f"The folder of the archive of {source.whose} is not where it was, or cannot be "
                   f"read by this account: {source.path}", err=True)  # fmt: skip
    typer.echo("Nothing has been lost: everything read from those folders is kept here, beside this "
               "instance, and the corrections are too. Check whether the disk is mounted. If a "
               "folder has moved, point its archive at the new place, which keeps every reading and "
               "every correction:", err=True)  # fmt: skip
    for source in gone:
        typer.echo("  " + invocation.run(f"sources set-path {source.id} /the/new/folder", data_dir), err=True)
    typer.echo("Adding the folder again instead makes a second archive of the same person and reads "
               "it all from nothing.", err=True)  # fmt: skip


def _work_no_archive_names(data_dir: Path, listed: list) -> None:
    """Folders of work under sources/ that no archive on the list names, said rather than left.

    The list is the only thing that ties a random id to somebody's folder, and it is one file. Put
    back from sources.json.previous — which is the version before the last change, and the way out
    this program itself recommends — it comes back without an archive added since then, and the
    hours of reading and the corrections under that archive's id stay on disk with nothing naming
    them. Taking an archive off the list does the same on purpose, and says so at the time.
    Nothing said it afterwards: not this command, and not the copy `backup` takes, which walks the
    list and therefore skips exactly the folder nobody would think to look for.
    """
    from epicrisis.sources import OUTPUT_DIR_NAME

    output = data_dir / OUTPUT_DIR_NAME
    if not output.is_dir():
        return
    named = {source.id for source in listed}
    strays = sorted(folder.name for folder in output.iterdir() if folder.is_dir() and folder.name not in named)
    if not strays:
        return
    typer.echo("")
    typer.echo(f"Read from archives this list does not name, under {output}: " + ", ".join(strays))
    typer.echo("Each is the work of an archive taken off the list, or of one that was on a list "
               "since put back from an older copy. The folder of documents it was read from is not "
               "named in it. Add that folder again and move what is inside this folder into the "
               "folder of its new id, and the reading and the corrections are back.")  # fmt: skip


@app.command()
def update(data_dir: Path = DATA_DIR_OPTION) -> None:
    """Process new or changed files in every source: all steps, skipping what is done."""
    from epicrisis.sources import SourceRegistry
    from epicrisis.update import run_update

    data_dir = _an_instance(data_dir)
    if not SourceRegistry(data_dir).list():
        typer.echo("No archive here yet. Add one: "
                   + invocation.run("sources add <folder> --owner <name>", data_dir)
                   + ", or run " + invocation.run("serve", data_dir)
                   + " and add it on the Archive status page.", err=True)  # fmt: skip
        raise typer.Exit(code=2)
    # Asked for, and then left to the lock itself. This used to answer "An update is already
    # running." and stop — five words, no pid, no file, no way out — for the commonest lock in the
    # program: the machine restarted in the middle of an update, and the number in update.lock now
    # belongs to some live daemon. Busy is the sentence that names the file and says that deleting
    # it lets the step run again, and taking the lock is the only thing that raises it, so the
    # check standing in front of the lock was the reason nobody ever heard it.
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
    from epicrisis.records import torn_under
    from epicrisis.validate import validate_source, validation_state

    data_dir = _an_instance(data_dir)
    registry = SourceRegistry(data_dir)
    sources = registry.list()
    if not sources:
        # Silence and a zero exit read as "done"; there is nothing here to index, and saying so
        # is the answer.
        typer.echo("No archive here yet. Add one: "
                   + invocation.run("sources add <folder> --owner <name>", data_dir)
                   + ", or run " + invocation.run("serve", data_dir)
                   + " and add it on the Archive status page.", err=True)  # fmt: skip
        raise typer.Exit(code=2)
    _say_what_rule_was_refused(registry.data_dir)
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
        # Built from the same files, so anything this run could not read is missing from the
        # numbers just printed, and the numbers agree with each other regardless.
        _say_what_was_lost({"lines_not_read": torn_under(output)})
    older = index_path(registry.data_dir)
    if older.exists() and sources:
        # The single index of an instance built before archives had owners; each archive now has
        # its own, so this one is history and would only answer a question twice.
        older.rename(older.with_name(older.name + ".before-owners"))
        typer.echo(f"The index from before archives had owners is kept as {older.name}.before-owners")


@app.command()
def forget(
    source_id: str = typer.Argument(..., help=f"The archive's id, as `{CLI} serve` shows it on /status."),
    data_dir: Path = DATA_DIR_OPTION,
    yes: bool = typer.Option(False, "--yes", help="Do it without asking."),
) -> None:
    """Put aside everything read from one archive, so the next run reads it again from nothing.

    The folder is not touched and stays on the list. The inventory, the classification, the
    transcriptions, the materials, the boundaries, the checks and the index move into
    data/sources/<id>/forgotten-<when>/. What is the person's own stays where it is: corrections
    and verdicts, which apply again to the next reading, and the readings a later reading
    displaced, which are the only copy of themselves there is.
    """
    from epicrisis.sources import SourceRegistry

    registry = SourceRegistry(_an_instance(data_dir))
    source = registry.get(source_id)
    if source is None:
        typer.echo(f"No archive with the id {source_id}. Run `{CLI} serve` and open /status to see them.", err=True)
        raise typer.Exit(code=2)
    if not yes and not typer.confirm(f"Read {source.whose} again from nothing? Nothing is deleted."):
        raise typer.Exit(code=1)
    aside = registry.forget(source_id)
    if aside is None:
        typer.echo(f"Nothing had been read from {source.whose} yet.")
        return
    typer.echo(f"Moved aside to {aside}")
    typer.echo(f"Run `{invocation.run('update', registry.data_dir)}` to read the archive again.")


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
    typer.echo(f"Run `{invocation.run('index', data_dir)}` to put them in the index.")


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
    typer.echo(f"Run `{invocation.run('index', data_dir)}` to put them in the index.")


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

    from epicrisis.indicator_web_check import names_to_settle, settle_names, web_backend
    from epicrisis.models import model_for
    from epicrisis.sources import SourceRegistry

    registry = SourceRegistry(data_dir.resolve())
    printed, _ = _printed_names_everywhere(registry)

    waiting = names_to_settle(registry.data_dir, list(printed.values()))
    typer.echo(f"{len(waiting)} printed names would be sent to a web search: the name, its units and its count.")
    typer.echo("No value, no date, no document and no person leaves this server.")
    if not yes and not typer.confirm("Send them?"):
        raise typer.Exit(code=1)

    # The backend first, then consent for it: the consent is recorded against the destination,
    # and the destination is what changes when the engine does.
    backend = web_backend(registry.data_dir, model or model_for(data_dir, "strong"))
    _require_consent(data_dir, backend.name)
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

    from epicrisis.indicator_web_check import look_up_names, tests_to_look_up, web_backend
    from epicrisis.models import model_for
    from epicrisis.sources import SourceRegistry

    registry = SourceRegistry(data_dir.resolve())
    printed, _ = _printed_names_everywhere(registry)

    waiting = tests_to_look_up(registry.data_dir, list(printed.values()))
    typer.echo(f"{len(waiting)} tests would be looked up: the label, the spellings this archive printed, the units.")
    typer.echo("No value, no date, no document and no person leaves this server.")
    if not yes and not typer.confirm("Look them up?"):
        raise typer.Exit(code=1)

    # The backend first, then consent for it: the consent is recorded against the destination,
    # and the destination is what changes when the engine does.
    backend = web_backend(registry.data_dir, model or model_for(data_dir, "strong"))
    _require_consent(data_dir, backend.name)
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
    from epicrisis.sources import SourceError

    try:
        # The folder is looked at before a page is drawn; the sentence is the demo's own, and this
        # says it the way `sources add` says its refusal of a folder. It used to come out as the
        # registry's traceback, on the way in, with an invented person's scans already on disk.
        made = build(into, seed=seed, say=lambda text: typer.echo(text, err=True))
    except SourceError as wrong:
        typer.echo(str(wrong), err=True)
        raise typer.Exit(code=2) from wrong

    whose = ", ".join(life.whose for life in LIVES)
    typer.echo(f"\nThree archives of people who do not exist: {whose}")
    typer.echo(f"{made['documents']} documents, {made['observations']} values")
    for archive in made["archives"]:
        typer.echo(f"Scans:  {archive}")
    typer.echo(f"Look at it with: {CLI} serve --data-dir {made['data_dir']}")
