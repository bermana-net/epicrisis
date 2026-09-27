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

    @property
    def says(self) -> str:
        if not self.counted:
            return NOT_COUNTED
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
    """What the last run of the checks wrote, by the rule that found it."""
    from epicrisis.validate import load_validation

    stored = load_validation(output)
    if not stored:
        return {}
    documents: dict[str, int] = {}
    for document in stored.get("documents", []):
        for code in document.get("findings", {}):
            documents[code] = documents.get(code, 0) + 1
    return {code: Tally(found=count, documents=documents.get(code, 0), ran=code in on)
            for code, count in stored.get("totals", {}).items()}  # fmt: skip


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


def counts(data_dir: Path, source_id: str, loaded, on: set[str]) -> dict[str, Tally]:
    """Every rule against one archive: what it found, what it would find, or nothing to count."""
    if not source_id:
        return {}
    output = source_output_dir(data_dir, source_id)
    tallies = of_the_checks(output, on) if output.exists() else {}
    tallies |= of_the_search(data_dir, source_id, loaded.at(kinds.SUSPECTS), on)
    for rule in loaded:
        if rule.at not in (kinds.VALIDATE, kinds.SUSPECTS):
            tallies[rule.id] = Tally(counted=False)
        elif rule.id not in tallies:
            # A check that is on and found nothing, and a check that is off and wrote nothing,
            # look the same in a stored file. Only the switch tells them apart.
            tallies[rule.id] = Tally(found=0, ran=rule.id in on)
    # After every rule has a tally, because a rule that finds nothing today may well have been
    # judged when it still found something, and that word is worth keeping in front of a person.
    for code, was in (judgements.counted(output) if output.exists() else {}).items():
        if code in tallies:
            tallies[code] = replace(tallies[code], real=was.real, noise=was.noise)
    # The stored findings also hold the checks that have not become rules yet. They are real
    # findings and a person sees them in the review; they simply have no switch to stand beside.
    return {rule.id: tallies[rule.id] for rule in loaded}


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
