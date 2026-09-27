"""What a person said about a finding: that it was real, or that it was noise.

A rule can be counted — it found thirty-three things. Whether those thirty-three were worth
finding is a different question, and nothing in the program could answer it: the counts say how
loud a rule is, never whether it is right. Without that second number, keeping a rule or
deleting it is a matter of somebody's taste, which is exactly what a registry of rules was meant
to stop being.

So a person can say, beside any finding, that it was real or that it was noise. What is kept is
the rule, the document, the verdict and when — never the value and never a reason, because a
reason belongs on the card where the correction is made.

Two decisions worth stating, because both could as easily have gone the other way:

- **A judgement marks, it does not hide.** Hiding what somebody called noise is the obvious next
  step and it is wrong: one mistaken click and a real finding is gone for good, with nothing to
  show it ever existed. Hiding can be a switch later, over the top of this.
- **It is written once and never rewritten.** A person who changes their mind says so again and
  the later word counts, but the earlier one stays on the file. A record of what somebody thought
  at the time is worth more than a tidy current state, and it costs one line.
"""

from dataclasses import dataclass
from pathlib import Path

from epicrisis import layout
from epicrisis.records import append_line, now, read_records

REAL, NOISE = "real", "noise"
VERDICTS = (REAL, NOISE)


@dataclass(frozen=True)
class Counted:
    real: int = 0
    noise: int = 0

    @property
    def judged(self) -> int:
        return self.real + self.noise


def path_for(output: Path) -> Path:
    return output / layout.JUDGEMENTS


def record(output: Path, rule_id: str, file_sha256: str, pages, verdict: str) -> None:
    """One person's word about one rule on one document. Appended, never rewritten."""
    if verdict not in VERDICTS:
        raise ValueError(f"a judgement is {' or '.join(VERDICTS)}, not {verdict!r}")
    # Through records.append_line, which holds the lock while it writes. This wrote its own line
    # without one, and verdicts come from a web request — two presses at once could plait one
    # line into another, and since a torn line is now skipped rather than raised, a verdict would
    # simply not be there.
    append_line(path_for(output), {"rule": rule_id, "file_sha256": file_sha256,
                                   "pages": list(pages), "verdict": verdict, "at": now()})  # fmt: skip


def latest(output: Path) -> dict[tuple, str]:
    """The last word about each rule on each document, by (rule, file, pages)."""
    said: dict[tuple, str] = {}
    if not path_for(output).exists():
        return said  # nobody has said anything yet, which is the ordinary case
    for line in read_records(path_for(output)):
        if line.get("verdict") in VERDICTS:
            said[(line.get("rule"), line.get("file_sha256"), tuple(line.get("pages") or ()))] = line["verdict"]
    return said


def counted(output: Path) -> dict[str, Counted]:
    """How many findings of each rule a person has called real, and how many noise.

    Only where the document judged still exists. A verdict is kept against the pages the
    classification grouped, exactly as a correction on a document is, and a page read again can be
    grouped differently — a two-page form becoming two documents, or two becoming one. Then the
    verdict applies to nothing, and it went on being counted anyway: these two numbers are what
    decides whether a rule is kept, and one of them was reading the verdicts of documents that no
    longer exist. A correction in that state has been counted and shown since the day it could
    happen; a verdict was neither.
    """
    from epicrisis.classify.report import document_keys

    here = document_keys(output)
    totals: dict[str, Counted] = {}
    for (rule_id, file_sha256, pages), verdict in latest(output).items():
        # No classification at all means nothing can be told about which documents exist, and
        # dropping every verdict on that basis would be worse than counting one too many.
        if here and (file_sha256, pages) not in here:
            continue
        was = totals.get(rule_id, Counted())
        totals[rule_id] = Counted(real=was.real + (verdict == REAL), noise=was.noise + (verdict == NOISE))
    return totals


def unmatched(output: Path) -> list[dict]:
    """Verdicts that no longer find the document they were given about.

    The same loss as corrections.unmatched_documents, which has been counted and shown on the page
    for as long as it could happen. This one was silent twice over: not counted as lost, and still
    counted as a verdict.
    """
    from epicrisis.classify.report import document_keys

    here = document_keys(output)
    if not here:
        return []
    return [
        {"rule": rule_id, "file_sha256": file_sha256, "pages": list(pages), "verdict": verdict}
        for (rule_id, file_sha256, pages), verdict in latest(output).items()
        if (file_sha256, pages) not in here
    ]  # fmt: skip
