"""The page of lines that look misread, asked directly: what it shows and what it leaves out.

None of this could be asked before the page existed, and that is the whole of the defect it was
written for: the rules of the `suspects` step ran from one place — `epicrisis suspects` on the
command line — which printed to a terminal and stored nothing, so there was no gathering to test
and no page to read. The `findings` table of every index held not one row of any of them.

Two things are held here. That the page gathers what the rules find, heaviest first, with enough
of each document to open it. And that the count it shows is the count the command prints over the
same index — the two places, one number of the seventh entry of the constitution, which is kept
by one call answering both rather than by two that are meant to agree.

Built by hand and not read by a model: the shapes a rule of this step fires on are a history with
one number far from the rest and a unit nobody else on that test prints, and inventing them is
the only way to measure a rule against a shape the live archive does not happen to hold.
"""

import sqlite3

import pytest

from epicrisis import rules as rule_files
from epicrisis.index.build import SCHEMA, SCHEMA_VERSION, index_path
from epicrisis.rules import kinds
from epicrisis.settings import rules_on, set_rule_on, set_rule_settings
from epicrisis.suspects import find, rows_from_index
from epicrisis.web.looks_misread import how_many_look_misread, what_looks_misread

ARCHIVE = "aa11bb22"
# One test, one specimen, one unit, printed often enough for its habits to mean anything: the
# rules of this step ask for four readings before a middle means anything and ten before "the
# others" print a unit at all.
HISTORY = [0.9, 1.0, 1.1, 0.95, 1.05, 0.92, 1.08, 0.98, 1.02, 0.96, 1.04, 0.94]
# A decimal point in the wrong place, which is the thing this rule is for, and a chart is where
# it lies: a point fifty times off drags the whole axis with it.
A_MISPLACED_POINT = 50.0


def _one_value(index, source_id: str, sha: str, day: str, printed: str, number: float, unit: str):
    index.execute(
        """INSERT INTO files (sha256, file_id, source_id, path, category, page_count)
           VALUES (?, ?, ?, ?, 'scan', 1)""",
        (sha, sha[:8], source_id, f"/scans/{sha[:4]}.pdf"),
    )  # fmt: skip
    index.execute(
        """INSERT INTO documents (source_id, file_sha256, first_page, pages, doc_type, language,
                                  title, date, date_precision, transcribed, primary_copy)
           VALUES (?, ?, 1, '[1]', 'lab_panel', 'en', 'Biochemistry', ?, 'day', 1, 1)""",
        (source_id, sha, day),
    )  # fmt: skip
    document = index.execute("SELECT last_insert_rowid()").fetchone()[0]
    index.execute(
        """INSERT INTO observations (document_id, page, kind, name, value, value_numeric, unit,
                                     reference, indicator_id, value_role, material, derived)
           VALUES (?, 1, 'quantitative', ?, ?, ?, ?, '0,5-1,0', 'creatinine', 'result', 'blood', 0)""",
        (document, printed, str(number).replace(".", ","), number, unit),
    )  # fmt: skip


@pytest.fixture
def an_archive_with_two_shapes_in_it(data_dir):
    """An index of one test printed thirteen times: one number far out, and one unit alone."""
    path = index_path(data_dir, ARCHIVE)
    index = sqlite3.connect(path)
    with index:
        index.executescript(SCHEMA)
        index.executemany("INSERT INTO meta VALUES (?, ?)",
                          [("built_at", "2026-01-01T00:00:00+00:00"), ("schema_version", str(SCHEMA_VERSION))])  # fmt: skip
        for number, reading in enumerate(HISTORY):
            _one_value(index, ARCHIVE, f"{number:02d}" * 32, f"2020-01-{number + 1:02d}", "Creatinine", reading, "mg/dL")
        _one_value(index, ARCHIVE, "ff" * 32, "2021-02-02", "Creatinine", A_MISPLACED_POINT, "mg/dL")
        _one_value(index, ARCHIVE, "ee" * 32, "2021-03-03", "Creatinine", 1.0, "nonesuch/dL")
    index.close()
    return data_dir


def _what_the_command_would_print(data_dir, source_id: str) -> tuple[int, int]:
    """The documents and the lines `epicrisis suspects` prints, got the way the command gets them."""
    chosen = rules_on(data_dir, rule_files.load(data_dir), kinds.SUSPECTS)
    connection = sqlite3.connect(f"file:{index_path(data_dir, source_id)}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    found = find(*rows_from_index(connection), chosen)
    connection.close()
    return len(found), sum(sum(item.codes.values()) for item in found)


def test_the_page_gathers_the_lines_that_look_misread(an_archive_with_two_shapes_in_it):
    data_dir = an_archive_with_two_shapes_in_it

    shown = what_looks_misread(data_dir, ARCHIVE)

    assert not shown["missing"] and not shown["every_rule_off"]
    assert shown["documents"] == 2 and shown["findings"] == 2
    found_by = {rule["id"] for rule in shown["rules"]}
    assert found_by == {"number_far_from_the_others", "unit_alone_in_a_series"}
    # The heaviest first, by the weights the rules carry and not by the order the archive was
    # walked in or by what they are called: a misplaced decimal point lies on a chart and a stray
    # unit does not, so the one has to be at the top of a queue somebody works through by hand.
    assert [(rule["id"], rule["weight"]) for rule in shown["rules"]] == [
        ("number_far_from_the_others", 3), ("unit_alone_in_a_series", 2),
    ]  # fmt: skip
    assert [item["weight"] for item in shown["shown"]] == sorted(
        (item["weight"] for item in shown["shown"]), reverse=True
    )  # fmt: skip
    assert shown["shown"][0]["sha256"] == "ff" * 32, "the misplaced point weighs most and is not first"
    # Enough of each document to open it: the whole hash, because that is what the address of a
    # document is, and the eight characters a person reads beside it.
    for item in shown["shown"]:
        assert len(item["sha256"]) == 64 and item["file_id"] == item["sha256"][:8]
        assert item["first_page"] == 1 and item["date"] and item["lines"]
        assert item["why"] and all(one["name"] and one["times"] >= 1 for one in item["why"])
    # What the rule itself says would settle one of its findings, which is the only sentence a
    # person reading a queue of these has to act on.
    assert all(rule["settles"] for rule in shown["rules"])
    assert "50" in shown["shown"][0]["lines"][0], "the line does not say what was printed"


def test_the_order_is_the_weight_and_not_the_name(an_archive_with_two_shapes_in_it):
    """Asked of an archive where the two disagree, because otherwise they happen to agree.

    The names of these two rules begin "A number…" and "A unit…", so on this instance as it ships
    the alphabet and the weights put them in the same order and an order taken from either would
    look right. What the list promises is the weights: a person whose laboratory writes one unit
    nobody else does can raise that rule above the misplaced decimal points, and the page has to
    move with them.
    """
    data_dir = an_archive_with_two_shapes_in_it
    heavier = rule_files.load(data_dir).get("unit_alone_in_a_series")
    set_rule_settings(data_dir, heavier, {"weight": 9})

    shown = what_looks_misread(data_dir, ARCHIVE)

    assert [rule["id"] for rule in shown["rules"]] == ["unit_alone_in_a_series", "number_far_from_the_others"]
    assert shown["shown"][0]["sha256"] == "ee" * 32, "the heavier rule's document is not at the top"
    assert [one["name"] for one in shown["shown"][0]["why"]] == [heavier.name]


def test_the_count_on_the_findings_page_is_the_count_the_command_prints(an_archive_with_two_shapes_in_it):
    """Two places, one number. Kept by one call answering both, not by two that should agree."""
    data_dir = an_archive_with_two_shapes_in_it

    line = how_many_look_misread(data_dir, ARCHIVE)

    assert (line["documents"], line["findings"]) == _what_the_command_would_print(data_dir, ARCHIVE)
    assert line["documents"] == what_looks_misread(data_dir, ARCHIVE)["documents"]
    # The line on the page of findings is a count and a link, never the findings themselves: the
    # owner of the archive this was measured on asked for exactly that, in those words, because a
    # hundred and twenty-five documents poured in among the checks buries the checks.
    assert set(line) == {"missing", "every_rule_off", "documents", "findings", "rules"}


def test_a_rule_turned_off_is_not_shown_and_is_not_counted(an_archive_with_two_shapes_in_it):
    data_dir = an_archive_with_two_shapes_in_it

    set_rule_on(data_dir, "number_far_from_the_others", False)
    shown = what_looks_misread(data_dir, ARCHIVE)

    assert [rule["id"] for rule in shown["rules"]] == ["unit_alone_in_a_series"]
    assert shown["documents"] == 1 and shown["shown"][0]["sha256"] == "ee" * 32
    assert not any("50" in line for item in shown["shown"] for line in item["lines"])
    # And the count beside the link moves with it, because it is the same call.
    assert how_many_look_misread(data_dir, ARCHIVE)["documents"] == 1


def test_the_two_rules_that_are_noise_find_nothing_until_somebody_turns_them_on(an_archive_with_two_shapes_in_it):
    """A missing unit and a form with no title are off: they were 378 of the 404 lines found here.

    Neither makes a number wrong — a form with no unit column is a form with no unit column, and a
    form read with no title is harder to find by name and nothing else — and three hundred of them
    in front of the twenty-nine worth opening is how a queue stops being worked through.
    """
    data_dir = an_archive_with_two_shapes_in_it
    index = sqlite3.connect(index_path(data_dir, ARCHIVE))
    with index:
        # One value with no unit at all, on a test whose other forms print one, and one laboratory
        # form read with no title: a finding of each of the two switched-off rules.
        _one_value(index, ARCHIVE, "cc" * 32, "2021-04-04", "Creatinine", 1.0, "")
        index.execute("UPDATE documents SET title = NULL WHERE file_sha256 = ?", ("cc" * 32,))
    index.close()

    off = what_looks_misread(data_dir, ARCHIVE)
    assert "unit_missing_where_others_have_one" not in {rule["id"] for rule in off["rules"]}
    assert "lab_form_without_a_title" not in {rule["id"] for rule in off["rules"]}
    assert not any(item["sha256"] == "cc" * 32 for item in off["shown"])

    set_rule_on(data_dir, "unit_missing_where_others_have_one", True)
    set_rule_on(data_dir, "lab_form_without_a_title", True)
    on = what_looks_misread(data_dir, ARCHIVE)

    assert {"unit_missing_where_others_have_one", "lab_form_without_a_title"} <= {rule["id"] for rule in on["rules"]}
    assert on["documents"] > off["documents"] and on["findings"] > off["findings"]


def test_every_rule_off_and_no_index_are_said_rather_than_drawn_as_nothing(an_archive_with_two_shapes_in_it, tmp_path):
    """An empty list is the one answer that means two different things, and only one is mendable."""
    data_dir = an_archive_with_two_shapes_in_it

    for rule in rule_files.load(data_dir).at(kinds.SUSPECTS):
        set_rule_on(data_dir, rule.id, False)
    silent = what_looks_misread(data_dir, ARCHIVE)
    assert silent["every_rule_off"] and not silent["missing"] and silent["shown"] == []

    nowhere = tmp_path / "another"
    nowhere.mkdir()
    assert what_looks_misread(nowhere, ARCHIVE)["missing"]
    assert how_many_look_misread(nowhere, ARCHIVE)["missing"]


def test_the_page_knows_nothing_of_fastapi_and_takes_the_archive_with_no_default():
    """The shape every page module here keeps: see ARCHITECTURE.md, and web/timeline.py beside it."""
    import inspect

    from epicrisis.web import looks_misread

    source = inspect.getsource(looks_misread)
    assert "fastapi" not in source.lower() and "request" not in source.lower()
    for gathering in (what_looks_misread, how_many_look_misread):
        taken = inspect.signature(gathering).parameters
        assert list(taken)[:2] == ["data_dir", "the_archive"]
        assert all(taken[name].default is inspect.Parameter.empty for name in ("data_dir", "the_archive"))
