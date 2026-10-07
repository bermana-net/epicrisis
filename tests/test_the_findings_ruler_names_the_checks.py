"""The ruler over the findings, and the half of it that was missing.

`tools/findings-snapshot.py` is what stands between a refactor of the checks and the sentence
"nothing moved". It measured the rules of the validate step and the search for misread rows, and
it was blind to the eleven checks of the extract step — which are the ones about to move into the
registry. Eleven codes arrive at `validate` and three summaries leave it, so a check that changed
its mind about one document moved one summary by one, and the diff said that a number somewhere
had changed.

Now the ruler prints the codes by name, and folds them back itself to see whether its own two
halves agree. Nothing here reads anybody's archive.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load(where: str, called: str):
    """A script from tools/, loaded from its path: tools/ is not a package and the name is hyphenated."""
    spec = importlib.util.spec_from_file_location(called, ROOT / where)
    module = importlib.util.module_from_spec(spec)
    sys.modules[called] = module
    spec.loader.exec_module(module)
    return module


ruler = load("tools/findings-snapshot.py", "findings_snapshot")


def test_the_codes_fold_into_the_summaries_the_way_validate_folds_them():
    """The three summaries, reproduced from the sets `validate` declares and not from a copy."""
    from epicrisis.validate import INCOMPLETE_CHECK_PROBLEMS

    incomplete = sorted(INCOMPLETE_CHECK_PROBLEMS)[0]
    checks = {incomplete: 2, "document_date_is_birth_date": 1, "value_not_on_the_page": 3,
              "unreadable_on_images": 7}  # fmt: skip
    findings = {"transcription_incomplete": 2, "checks_still_failing": 1, "value_not_on_the_page": 3}

    said = ruler._the_summaries_add_up("an-archive", "abc p1", checks, findings)

    assert "folded   an-archive abc p1 transcription_incomplete 2" in said
    # One, not eight: `unreadable_on_images` is covered by a rule of its own and lands in no
    # summary at all, which is the thing the codes-by-name lines exist to keep visible.
    assert "folded   an-archive abc p1 checks_still_failing 1" in said
    assert "folded   an-archive abc p1 value_not_on_the_page 3" in said


def test_a_summary_lower_than_the_checks_under_it_stops_the_snapshot():
    """The ruler checking itself, and refusing to hand over a file it cannot stand behind.

    It raises rather than writing a note into the snapshot. A ruler that says "these do not add
    up" in a file somebody diffs a week later is a ruler whose own disagreement travels as data —
    and the whole point of this file is that `diff` answering "identical" means something.
    """
    from epicrisis.validate import INCOMPLETE_CHECK_PROBLEMS

    checks = {sorted(INCOMPLETE_CHECK_PROBLEMS)[0]: 2}

    with pytest.raises(SystemExit) as refused:
        ruler._the_summaries_add_up("an-archive", "abc p1", checks, {"transcription_incomplete": 1})

    assert "transcription_incomplete" in str(refused.value)
    assert "cannot be trusted" in str(refused.value)


def test_a_summary_standing_higher_than_the_checks_is_allowed_and_said_so():
    """Because a rule of the registry may add to the same name.

    `transcription_incomplete` is one of three findings that are not rules and are not going to
    be, but nothing stops a rule hanging a finding under a name a summary also uses — and the day
    one does, a ruler that insisted on equality would refuse to run for a reason that is not an
    error. Lower is the defect: it means a check was counted into a summary that the codes beside
    it cannot account for.
    """
    checks = {"document_date_is_birth_date": 1}

    said = ruler._the_summaries_add_up("an-archive", "abc p1", checks, {"checks_still_failing": 4})

    assert "folded   an-archive abc p1 checks_still_failing 1" in said
