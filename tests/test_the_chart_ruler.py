"""The ruler over every chart, and the two things it has to say out loud.

tools/chart-snapshot.py draws every chart of every indicator of every archive and writes them as
one sorted list, so that a change to how charts are drawn can be diffed rather than argued about.
It lived outside this repository for a fortnight, which is how both of these got lost.

A round of findings recorded 816 charts where the ruler reported 815. The difference was not in
the code: tools/findings-snapshot.py builds the index itself, so running the other ruler rebuilt
the archive underneath this one, and four corrections the owner had saved by hand in between moved
three series. Nothing in the file said which build of the index had been measured, so "identical
byte for byte" could only ever mean "nobody saved anything while we were measuring" — which is the
failure the sixth entry of the constitution is about.

Nothing here reads anybody's archive: every test builds an index of its own in a temporary folder.
"""

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(where: str, called: str):
    """A script from tools/, loaded from its path: tools/ is not a package and the name is hyphenated."""
    spec = importlib.util.spec_from_file_location(called, ROOT / where)
    module = importlib.util.module_from_spec(spec)
    sys.modules[called] = module
    spec.loader.exec_module(module)
    return module


ruler = load("tools/chart-snapshot.py", "chart_snapshot")

A_BUILD = "2026-01-01T00:00:00+00:00"
A_LATER_BUILD = "2026-01-01T09:30:00+00:00"


def an_index(data_dir: Path, name: str, built_at: str, indicators: tuple[str, ...] = ()) -> Path:
    """An index with the two tables this ruler reads, and nothing of anybody in it."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"index-{name}.sqlite"
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute("CREATE TABLE IF NOT EXISTS indicators (id TEXT PRIMARY KEY, label TEXT)")
        connection.execute("INSERT OR REPLACE INTO meta VALUES ('built_at', ?)", (built_at,))
        connection.executemany("INSERT OR REPLACE INTO indicators VALUES (?, ?)",
                               [(one, one) for one in indicators])  # fmt: skip
    connection.close()
    return path


def test_the_header_says_which_build_of_which_index_it_measured(tmp_path: Path):
    """The whole of the 816-against-815 confusion: a line of numbers that did not say when.

    The letters below come from the order of the files, so they say nothing by themselves; naming
    each one beside the build it carried is what lets a diff tell an archive that moved from a
    chart that moved.
    """
    data_dir = tmp_path / "data"
    first = an_index(data_dir, "aaaaaaaa", A_BUILD)
    second = an_index(data_dir, "bbbbbbbb", A_LATER_BUILD)

    lines = ruler.header(data_dir, [first, second], frozen=True)

    assert lines[1] == f"# A index-aaaaaaaa.sqlite built_at={A_BUILD}"
    assert lines[2] == f"# B index-bbbbbbbb.sqlite built_at={A_LATER_BUILD}"


def test_the_header_says_so_when_the_archive_was_read_where_it_lies(tmp_path: Path):
    """--live gives up the one guarantee below, so it may not be the silent default."""
    data_dir = tmp_path / "data"
    an_index(data_dir, "aaaaaaaa", A_BUILD)

    frozen = ruler.header(data_dir, ruler.indexes(data_dir), frozen=True)[0]
    live = ruler.header(data_dir, ruler.indexes(data_dir), frozen=False)[0]

    assert "frozen copy" in frozen and "live" in live
    assert "anything saved while this ran is in the numbers below" in live


def test_the_measurement_is_taken_off_a_copy_the_archive_cannot_move_under(tmp_path: Path):
    """The archive underneath is a live one, written to by hand while a measurement runs.

    An index rebuilt mid-run moves the charts of whatever was corrected, and the ruler reports it
    as a change in the code. The copy costs the size of the indexes for the length of the run.
    """
    data_dir = tmp_path / "data"
    an_index(data_dir, "aaaaaaaa", A_BUILD, indicators=("creatinine",))

    frozen = ruler.freeze(data_dir, tmp_path / "beside")
    # The owner saves a correction, and the index is rebuilt under the running measurement.
    an_index(data_dir, "aaaaaaaa", A_LATER_BUILD, indicators=("creatinine", "ferritin"))

    copied = frozen / "index-aaaaaaaa.sqlite"
    assert ruler.built_at(copied) == A_BUILD
    with sqlite3.connect(f"file:{copied}?mode=ro", uri=True) as reading:
        assert [row[0] for row in reading.execute("SELECT id FROM indicators")] == ["creatinine"]
    assert ruler.built_at(data_dir / "index-aaaaaaaa.sqlite") == A_LATER_BUILD


def test_the_switches_and_the_rules_are_frozen_with_the_indexes(tmp_path: Path):
    """They are read while the charts are drawn, so a rule turned off mid-run moves the numbers too."""
    data_dir = tmp_path / "data"
    an_index(data_dir, "aaaaaaaa", A_BUILD)
    (data_dir / ruler.SETTINGS).write_text(json.dumps({"rules": {"a-rule": {"on": True}}}), encoding="utf-8")
    (data_dir / ruler.RULES).mkdir()
    (data_dir / ruler.RULES / "one-of-this-archive-s-own.md").write_text("# a rule\n", encoding="utf-8")

    frozen = ruler.freeze(data_dir, tmp_path / "beside")
    (data_dir / ruler.SETTINGS).write_text(json.dumps({"rules": {"a-rule": {"on": False}}}), encoding="utf-8")

    assert json.loads((frozen / ruler.SETTINGS).read_text(encoding="utf-8"))["rules"]["a-rule"]["on"] is True
    assert (frozen / ruler.RULES / "one-of-this-archive-s-own.md").exists()


def run(*arguments: str) -> subprocess.CompletedProcess:
    """The ruler as it is actually run. In its own process: it imports epicrisis from the tree it
    is pointed at, and swapping those modules inside this one would be felt by every other test."""
    return subprocess.run([sys.executable, str(ROOT / "tools" / "chart-snapshot.py"), *arguments],
                          capture_output=True, text=True)  # fmt: skip


def test_the_file_it_writes_opens_with_the_archive_it_measured(tmp_path: Path):
    data_dir = tmp_path / "data"
    an_index(data_dir, "aaaaaaaa", A_BUILD)
    out = tmp_path / "charts.txt"

    done = run(str(out), str(ROOT), "--data-dir", str(data_dir))

    assert done.returncode == 0, done.stderr
    written = out.read_text(encoding="utf-8").splitlines()
    assert written[0].startswith("# measured on a frozen copy of")
    assert written[1] == f"# A index-aaaaaaaa.sqlite built_at={A_BUILD}"
    assert "0 charts" in done.stdout and f"built_at={A_BUILD}" in done.stdout


def test_a_tree_that_is_not_this_program_is_refused_before_anything_is_measured(tmp_path: Path):
    data_dir = tmp_path / "data"
    an_index(data_dir, "aaaaaaaa", A_BUILD)
    out = tmp_path / "charts.txt"

    done = run(str(out), str(tmp_path), "--data-dir", str(data_dir))

    assert done.returncode == 2 and "not a tree of this program" in done.stderr
    assert not out.exists()


def test_a_data_directory_with_no_index_says_so_rather_than_writing_an_empty_file(tmp_path: Path):
    """An empty list of charts and a file saying nothing moved are the same bytes, and must not be."""
    out = tmp_path / "charts.txt"

    done = run(str(out), str(ROOT), "--data-dir", str(tmp_path / "data"))

    assert done.returncode == 2 and "nothing to measure" in done.stderr
    assert not out.exists()
