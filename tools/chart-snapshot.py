"""Every chart of every test, as numbers: the ruler for anything that changes how they are drawn.

    tools/chart-snapshot.py before.txt --data-dir data
    ... a change to how charts are drawn ...
    tools/chart-snapshot.py after.txt --data-dir data && diff before.txt after.txt

A second tree may be named, because the point of this is to run two of them:

    git worktree add /tmp/before <commit>
    tools/chart-snapshot.py before.txt /tmp/before --data-dir data
    tools/chart-snapshot.py after.txt  .          --data-dir data

It holds indicator ids, units, counts and numbers off somebody's forms, so it is written where it
is asked for and never into this repository — the same rule tools/findings-snapshot.py works by.

Two things this ruler says out loud, both of them bought by a round of findings where it reported
815 charts against a round record of 816:

  * **Which build of the index it measured.** The archive underneath is a live one, and the owner
    saves a correction by hand whenever he likes; tools/findings-snapshot.py builds the index
    itself, so merely running the other ruler moves this one's numbers. A diff of two runs then
    reads as a change in the code when it was a change in the archive. Every line of the header
    says which index was read and what `built_at` it carried, so the two can never again be
    confused: a header that moved is an archive that moved.
  * **That nothing moved while it was being read.** Each index is copied first, through sqlite's
    own backup, which takes a read lock and hands back a consistent file; every chart is then
    drawn off that copy. The cost is the size of the indexes on disk for the length of the run
    (nine megabytes for the three archives here, gone when it exits) and about a second. That is
    cheap against the thing it buys: "identical byte for byte" now means the behaviour did not
    change, and not merely that nobody happened to save anything while we were measuring.

`--live` skips the copy and reads the indexes where they lie. It is faster and needs no room, and
it gives up the second guarantee above, so the header says it was used.
"""

import argparse
import glob
import pathlib
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing

SETTINGS = "settings.json"
RULES = "rules"


def draw(series, data_dir: pathlib.Path, values, indicator):
    """One test's charts, however the tree being measured asks to be told about the rules.

    Both shapes are kept because this ruler is run against two trees at once, and the older of
    them took the three switches one by one where the newer takes the rules themselves.
    """
    from epicrisis import rules
    from epicrisis.settings import rules_on

    if "placing" in series.charts.__code__.co_varnames:      # the rules
        return series.charts(values, indicator=indicator,
                             placing=rules_on(data_dir, rules.load(data_dir), "charts"))
    return series.charts(values, indicator=indicator, to_scale=True, from_range=True, by_numbers=True,
                         scale_rules=rules_on(data_dir, rules.load(data_dir), "charts"))


def band_of(series, item) -> str:
    """The printed range as this chart would draw it, in the same words every run.

    The ruler recorded the values and not the band, so a snapshot that matched byte for byte said
    nothing at all about how a printed range had been read — and the reader of ranges was broken
    and repaired four times in one day underneath it, every time with the rulers reporting no
    movement. A measuring stick blind in the direction you keep slipping is worse than none: it
    is a reason to stop checking.
    """
    low, high = (series._band_of(item) or (None, None))
    if low is None and high is None:
        return "-"
    return f"{'' if low is None else format(low, '.6g')}:{'' if high is None else format(high, '.6g')}"


def indexes(data_dir: pathlib.Path) -> list[pathlib.Path]:
    """Every index under the data directory, not a list written by hand.

    The list was written when there were two archives; a third was added, and for a fortnight this
    ruler reported "no movement" about a change that acted on nothing but that third one. A
    measuring stick blind in the direction you are walking is worse than none: it is a reason to
    stop checking.
    """
    return [pathlib.Path(path) for path in sorted(glob.glob(str(data_dir / "index-*.sqlite")))]


def read_only(path: pathlib.Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def built_at(path: pathlib.Path) -> str:
    """When the index being read was built, or why that cannot be said."""
    with closing(read_only(path)) as connection:
        row = connection.execute("SELECT value FROM meta WHERE key = 'built_at'").fetchone()
    return row[0] if row else "not said"


def freeze(data_dir: pathlib.Path, into: pathlib.Path) -> pathlib.Path:
    """A data directory that cannot move under the measurement: the indexes copied, the rest linked.

    The indexes go through sqlite's backup rather than a file copy, because a copy of a database
    being written to is a database with half a transaction in it. The switches and the instance's
    own rules are copied too: they are read while the charts are drawn, and a rule turned off
    mid-run would move the numbers exactly as a saved correction does.
    """
    frozen = into / "data"
    (frozen / RULES).mkdir(parents=True, exist_ok=True)
    for path in indexes(data_dir):
        with closing(read_only(path)) as live, closing(sqlite3.connect(frozen / path.name)) as copy:
            live.backup(copy)
    if (data_dir / SETTINGS).exists():
        shutil.copy2(data_dir / SETTINGS, frozen / SETTINGS)
    for rule in sorted((data_dir / RULES).glob("*.md")) if (data_dir / RULES).is_dir() else []:
        shutil.copy2(rule, frozen / RULES / rule.name)
    return frozen


def header(data_dir: pathlib.Path, read: list[pathlib.Path], frozen: bool) -> list[str]:
    """Which archive each letter below is, and what build of it this run measured.

    The letters come from the order of the files, so a fourth archive renames the three before it;
    naming them here is what lets a diff tell that apart from a chart that moved.
    """
    lines = [f"# measured on {'a frozen copy of ' if frozen else 'the live '}{data_dir}"]
    if not frozen:
        lines[0] += " — anything saved while this ran is in the numbers below"
    for letter, path in zip((chr(65 + n) for n in range(len(read))), read):
        lines.append(f"# {letter} {path.name} built_at={built_at(path)}")
    return lines


def chart_lines(tree: pathlib.Path, data_dir: pathlib.Path, read: list[pathlib.Path]) -> list[str]:
    """Every chart every indicator of every archive draws, one line each, sorted."""
    sys.path.insert(0, str(tree))
    for module in [name for name in sys.modules if name.startswith("epicrisis")]:
        del sys.modules[module]
    from epicrisis import query, series

    lines = []
    for letter, path in zip((chr(65 + n) for n in range(len(read))), read):
        with closing(read_only(path)) as db:
            for row in db.execute("SELECT id FROM indicators"):
                for chart in draw(series, data_dir, query.whole_history(db, row["id"]), row["id"]):
                    numbers = sorted(f"{item['value_numeric']:.6g}" for item in chart["rows"]
                                     if item.get("value_numeric") is not None)  # fmt: skip
                    # Every band this chart would draw, sorted, so the line does not move when the
                    # rows do. A range the reader refuses comes out as "-", which is itself worth
                    # seeing move.
                    bands = sorted(band_of(series, item) for item in chart["rows"])
                    lines.append(f"{letter} {row['id']} [{chart['unit']}] {chart['material'] or '-'} "
                                 f"count={chart['count']} points={len(chart['points'])} scaled={chart.get('scaled', 0)} "
                                 f"by_numbers={chart.get('by_numbers', 0)} converted={sorted(chart.get('converted_from', {}).items())} "
                                 f"values={','.join(numbers)} bands={','.join(bands)}")  # fmt: skip
    sys.path.remove(str(tree))
    return sorted(lines)


def measure(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=pathlib.Path, help="Where to write the lines; never inside this repository")
    parser.add_argument("tree", nargs="?", default=".", type=pathlib.Path, help="The tree whose charts to draw")
    parser.add_argument("--data-dir", type=pathlib.Path, default=pathlib.Path("data"))
    parser.add_argument("--live", action="store_true",
                        help="Read the indexes where they lie, rather than a copy nothing can move")  # fmt: skip
    args = parser.parse_args(argv)

    if not (args.tree / "epicrisis" / "series.py").exists():
        print(f"{args.tree} is not a tree of this program: it holds no epicrisis/series.py", file=sys.stderr)
        return 2
    live = indexes(args.data_dir)
    if not live:
        print(f"No index under {args.data_dir}. There is nothing to measure.", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="chart-snapshot-") as beside:
        data_dir = args.data_dir if args.live else freeze(args.data_dir, pathlib.Path(beside))
        read = live if args.live else indexes(data_dir)
        lines = header(args.data_dir, read, frozen=not args.live) + chart_lines(args.tree.resolve(), data_dir, read)
        charts = len(lines) - len(live) - 1
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{charts} charts -> {args.out}")
    for line in lines[:len(live) + 1]:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(measure())
