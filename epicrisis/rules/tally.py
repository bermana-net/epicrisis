"""How much each rule has found on one archive.

A rule you cannot count is a rule you can never delete. The registry can switch a check off, but
"should it be off" is a question about how often it fires and how often it was right, and
neither is answerable from the code — only from an archive.

This is the first half: how often it fires. The second half — how often a person agreed — needs
somewhere to record that a finding was real, and that is its own piece of work.

What is counted, and what is not, said plainly rather than guessed at:

- **The checks over transcriptions** are counted from what the last run of the checks wrote
  beside the archive. Exact, free, and only for the rules that were running: a check that is
  switched off wrote nothing, and this says so instead of showing a zero that means "off".
  Both kinds of them — the checks of the validate step, whose findings a person is shown, and the
  sixteen of the extract step, which decide whether a document goes back to a stronger model.
  The second kind said "not counted" beside every switch for as long as it existed, while the
  exact number sat in `validation.json` under `checks`, written by the same run and read by
  nothing: the one step whose switches cost money was the one step with no number beside them.
- **The search for lines that look misread** is run here and now, in a fifth of a second, for
  every rule of that step — the ones that are off included. That is the useful direction: a
  person deciding whether to turn one on can see what it would find first.
- **What a person said** about the findings, from judgements.py, beside the count. That is the
  second half this file was missing: how loud a rule is, and whether it was right.
- **The rules that place a value on a scale** are not counted at all. They find nothing; they
  move points on a chart, and "how many points moved" is a different question that belongs
  beside the chart, not beside the switch.
"""

import sqlite3
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path

from epicrisis import judgements
from epicrisis.index.build import index_path
from epicrisis.rules import kinds
from epicrisis.sources import source_output_dir

NOT_COUNTED = "not counted"
# How many findings of a rule a person has to have judged before their verdicts say anything
# about the rule itself. Under this, "all noise" is as likely to be two unlucky documents as a
# rule that does not work.
ENOUGH_TO_JUDGE = 5


@dataclass(frozen=True)
class Tally:
    found: int = 0
    documents: int = 0
    counted: bool = True
    ran: bool = True  # False where the rule was off and the count is what it would find
    real: int = 0  # findings a person has looked at and called real
    noise: int = 0
    #: Why there is no number, in the words the page prints. "Not counted" is the honest answer
    #: for a rule that finds nothing by design; it was the answer given for three different
    #: situations, two of which a person can do something about — an archive nobody has checked
    #: yet, and a check that wrote nothing because it was off. Those two read as "this rule is
    #: uncountable", which sent nobody to press Check and nobody to turn the switch on.
    why_not: str = NOT_COUNTED

    @property
    def says(self) -> str:
        if not self.counted:
            return self.why_not or NOT_COUNTED
        where = f" on {self.documents} document{'s' if self.documents != 1 else ''}"
        if not self.found:
            return "found nothing here" if self.ran else "would find nothing here"
        said = f" · {self.real} real, {self.noise} noise" if self.real or self.noise else ""
        return f"{'found' if self.ran else 'would find'} {self.found}{where}{said}"

    @property
    def worth_keeping(self) -> str:
        """What this archive has to say about whether the rule earns its place, or nothing.

        A rule you cannot count is a rule you can never delete, and a rule nobody has judged is
        one nobody can defend either. This says only what the person's own verdicts say, and only
        once there are enough of them to mean anything: a rule that has found a fair number of
        things here and been called noise every time is a candidate to switch off, and one whose
        findings a person keeps calling real is one to keep. Everything in between says nothing,
        which is most rules most of the time.

        Nothing is decided by this and nothing is switched off by it. It is a sentence beside a
        switch, for the person whose instance it is.
        """
        judged = self.real + self.noise
        if not self.counted or judged < ENOUGH_TO_JUDGE:
            return ""
        if not self.real:
            return f"every one of the {judged} you have looked at was noise — a candidate to switch off"
        if not self.noise:
            return f"every one of the {judged} you have looked at was real"
        return ""


def of_the_checks(output: Path, on: set[str]) -> dict[str, Tally]:
    """What the last run of the checks wrote, by the rule that found it.

    Out of the two things that run writes, because they are two different sets of codes and only
    together do they cover the rules of both steps:

    * `totals` and `documents` — the findings a person is shown, which is what the rules of the
      validate step produce. Four of the extract step's codes are covered by rules elsewhere and
      make no finding at all, so this half cannot see them.
    * `checks` — every extract check, by code, for every document, whether it ended in a finding
      or not. Written for the ruler that guarded the move of those checks into the registry, and
      read by nothing else until now.

    Where a code is in both, `checks` answers: it is the count of that one check, while a total
    may be a summary several checks were folded into.

    `ran` is True for everything here, and that is not the same question as the switch. These
    numbers were written by a run, so the rule did find them; whether it is on *today* is drawn
    beside this by the switch itself. Saying "would find 42" of 42 things a check actually found
    is the one reading of this field that is simply false.
    """
    from epicrisis.validate import load_validation

    stored = load_validation(output)
    if not stored:
        return {}
    documents: dict[str, int] = {}
    for document in stored.get("documents", []):
        for code in document.get("findings", {}):
            documents[code] = documents.get(code, 0) + 1
    found = {code: Tally(found=count, documents=documents.get(code, 0))
             for code, count in stored.get("totals", {}).items()}  # fmt: skip
    return found | _of_the_extract_checks(stored)


def _of_the_extract_checks(stored: dict) -> dict[str, Tally]:
    """Every check of the extract step, counted out of what that same run wrote down.

    One entry per document, holding the codes that fired on it and how many times. Counted here
    rather than folded by whoever stored it, because the two numbers a person wants beside a
    switch — how many times it fired and on how many documents — are both in this and neither is
    in a summary.
    """
    times: dict[str, int] = {}
    documents: dict[str, int] = {}
    for by_code in stored.get("checks", {}).values():
        if not isinstance(by_code, dict):
            continue
        for code, count in by_code.items():
            times[code] = times.get(code, 0) + (count if isinstance(count, int) else 0)
            documents[code] = documents.get(code, 0) + 1
    return {code: Tally(found=count, documents=documents.get(code, 0)) for code, count in times.items()}


def of_the_search(data_dir: Path, source_id: str, every, on: set[str]) -> dict[str, Tally]:
    """What every rule of the search finds right now, the switched-off ones included."""
    from epicrisis import suspects

    path = index_path(data_dir, source_id)
    if not path.exists():
        return {}
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        found = suspects.find(*suspects.rows_from_index(connection), every)
    counts: dict[str, list[int]] = {rule.id: [0, 0] for rule in every}
    for item in found:
        for code, times in item.codes.items():
            if code in counts:
                counts[code][0] += times
                counts[code][1] += 1
    return {code: Tally(found=total, documents=documents, ran=code in on)
            for code, (total, documents) in counts.items()}  # fmt: skip


#: The steps whose rules are counted out of what the last run of the checks wrote beside the
#: archive. Both of them write to the same file and neither is run again to be counted: one
#: because its findings are already stored, the other because re-running it means reading every
#: document again, which is half a minute and no model but still half a minute.
COUNTED_FROM_A_RUN = (kinds.VALIDATE, kinds.EXTRACT)
NOTHING_CHECKED = "nothing has been checked here yet"
WROTE_NOTHING_WHILE_OFF = "nothing was written while it was off"


def counts(data_dir: Path, source_id: str, loaded, on: set[str]) -> dict[str, Tally]:
    """Every rule against one archive: what it found, what it would find, or nothing to count.

    A rule with no number says **which** of the three reasons it has none for, because two of
    them are things a person can act on and the third is not. An archive nobody has run the
    checks over has no numbers for any check; a check switched off wrote nothing while it was off;
    a rule that places a value on a scale finds nothing by design and never will.
    """
    if not source_id:
        return {}
    output = source_output_dir(data_dir, source_id)
    checked = _has_been_checked(output)
    tallies = of_the_checks(output, on) if output.exists() else {}
    tallies |= of_the_search(data_dir, source_id, loaded.at(kinds.SUSPECTS), on)
    for rule in loaded:
        if rule.at not in COUNTED_FROM_A_RUN + (kinds.SUSPECTS,):
            tallies[rule.id] = Tally(counted=False)
        elif rule.id in tallies:
            continue
        elif rule.at == kinds.SUSPECTS:
            # Run here and now, so a rule missing from the answer found nothing, on or off.
            tallies[rule.id] = Tally(found=0, ran=rule.id in on)
        elif not checked:
            tallies[rule.id] = Tally(counted=False, why_not=NOTHING_CHECKED)
        elif rule.id in on:
            tallies[rule.id] = Tally(found=0, ran=True)
        else:
            # A check that is on and found nothing, and a check that is off and wrote nothing,
            # look the same in a stored file: both are absent from it. Only the switch tells them
            # apart, and the second is not a zero — it is no answer, and said as one.
            tallies[rule.id] = Tally(counted=False, why_not=WROTE_NOTHING_WHILE_OFF)
    # After every rule has a tally, because a rule that finds nothing today may well have been
    # judged when it still found something, and that word is worth keeping in front of a person.
    for code, was in (judgements.counted(output) if output.exists() else {}).items():
        if code in tallies:
            tallies[code] = replace(tallies[code], real=was.real, noise=was.noise)
    # The stored findings also hold the checks that have not become rules yet. They are real
    # findings and a person sees them in the review; they simply have no switch to stand beside.
    return {rule.id: tallies[rule.id] for rule in loaded}


def _has_been_checked(output: Path) -> bool:
    """Whether the checks have ever been run over this archive.

    Asked of the file and not of what is in it: a run that found nothing at all writes the file
    with empty totals, and that is an archive with answers rather than one nobody has looked at.
    """
    from epicrisis.validate import load_validation

    return bool(output.exists() and load_validation(output))


def trial(data_dir: Path, source_id: str, rule, settings: dict) -> dict:
    """What this rule would find with these settings, without storing any of them.

    Deciding a threshold by typing a number and hoping is not deciding it. Only the rules of the
    search can be tried like this — they read the index and answer in a fifth of a second. A
    check over the transcriptions would have to read the documents again, which is half a minute
    on this archive, so the page says so rather than offering a button that takes half a minute.
    """
    from dataclasses import replace as _replace

    from epicrisis import suspects

    path = index_path(data_dir, source_id)
    if rule.at != kinds.SUSPECTS or not path.exists():
        return {}
    wanted = _replace(rule, settings={**rule.settings, **settings})
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        found = suspects.find(*suspects.rows_from_index(connection), [wanted])
    lines = [line for item in found for line in item.lines]
    return {"found": sum(sum(item.codes.values()) for item in found), "documents": len(found),
            "examples": lines[:3], "settings": wanted.settings}  # fmt: skip
