"""A second reader over the groups a model made, so that a person reads only the disagreements.

512 indicators is not 512 decisions: 318 of them hold one printed name each and group nothing,
and nothing there can be wrong. The decisions are the 194 groups that put two or more spellings
together, and the risk in them is one kind of thing — a name that does not belong with the rest,
a fraction filed under its whole, a urine test under its blood namesake.

So a second model reads each group on its own and says whether every spelling in it is the same
measurement. Where both readers agree, the group is marked as checked by a second reader and
stays out of a person's way. Where they disagree, it is put in front of the person with what
the second reader objected to and why. Two models agreeing is not proof — they can be wrong
together — but a disagreement is always worth a look, and that is what this is for.

"Checked by a second reader" is never "looked at by a person": marking a group reviewed stays a
person's own act. This only decides which groups are worth their time.

Only names go to the model, as with the grouping itself: the printed name, its units and how
often it appears. No values, no dates, no documents.
"""

import hashlib
import json
from pathlib import Path

from epicrisis.engines import engine_name
from epicrisis.classify.backend import STRONG_MODEL, BackendError
from epicrisis.printed_values import fold
from epicrisis.records import append_line, now, read_records

FILE_NAME = "indicator-checks.jsonl"
BATCH = 12
TIMEOUT_SECONDS = 600

SYSTEM_PROMPT = """You check groups of laboratory value names that another reader put together, in Russian, Ukrainian, English, Spanish and Greek. For each group, say whether every name in it is the same measurement of the same thing.

Names belong together when they are one test written differently: another language, another spelling, the laboratory's abbreviation, the machine's name for it ("Креатинін", "Creatinina", "CREATININE", "CREA").

Names do not belong together, however similar the words, when they are different measurements:
- a test and a fraction or a form of it: haemoglobin and glycated haemoglobin; total and direct bilirubin; cholesterol and HDL cholesterol; calcium and ionised calcium
- a test and a thing calculated from it: creatinine and eGFR or CKD-EPI
- the same substance in a different specimen: protein in urine is not protein in serum; a 24-hour urine collection is not the blood test
- the same substance counted differently: a percentage and an absolute count; MCH and haemoglobin
- a measurement and its reference, method, or the time it was taken

Judge from the names and their units together: two names with units of a different kind are usually two tests.

For every group return: belongs = the names that are the same measurement as the group's label; and does_not_belong = the names that are not, each with a short reason. A group where every name belongs has an empty does_not_belong.

Be exact rather than generous. If a name is an abbreviation you cannot read with confidence, put it in does_not_belong and say so: a name taken out waits for a person, and nothing is lost."""

SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string"},
                    "agrees": {"type": "boolean"},
                    "does_not_belong": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}, "why": {"type": "string"}},
                            "required": ["name", "why"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["ref", "agrees", "does_not_belong"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["groups"],
    "additionalProperties": False,
}

REQUEST = """Groups to check. One block each, starting with its ref.

{groups}"""

PROMPT_VERSION = hashlib.sha256("\n".join([SYSTEM_PROMPT, json.dumps(SCHEMA, sort_keys=True), REQUEST]).encode()).hexdigest()[:12]


class CheckBackend:
    def __init__(self, model: str = STRONG_MODEL, executable: str = "claude", timeout_seconds: int = TIMEOUT_SECONDS,
                 data_dir=None):  # fmt: skip
        self.model, self.executable, self.timeout_seconds = model, executable, timeout_seconds
        self.data_dir = data_dir
        self.name = engine_name(data_dir)

    def call(self):
        """Something that can answer one question. What carries it there is chosen in engines."""
        from epicrisis import engines

        return engines.a_call(self.data_dir, model=self.model, timeout_seconds=self.timeout_seconds)

    def check(self, groups: str, workdir: Path) -> dict:
        fields, _ = self.call().ask(SYSTEM_PROMPT, SCHEMA, REQUEST.format(groups=groups), workdir)
        if not isinstance(fields.get("groups"), list):
            raise BackendError("no valid structured output")
        return fields


def load_checks(data_dir: Path) -> dict[str, dict]:
    """What a second reader said about each group. The last word for an indicator wins."""
    path = Path(data_dir) / FILE_NAME
    if not path.exists():
        return {}
    return {line["indicator"]: line for line in read_records(path) if line.get("indicator")}


def groups_to_check(data_dir: Path, printed: list[dict]) -> list[dict]:
    """Every indicator that puts two or more spellings together, with what the model is shown.

    A group goes whole: the spellings already in it and the ones waiting for a person, marked as
    waiting. A second reader asked about half a group answers about half a group, and a spelling
    it has never seen cannot be said to have passed it.

    One spelling is not a grouping and cannot be wrong, so those never go: they are most of the
    list, and sending them would spend a person's model budget on nothing. Where a group is one
    spelling plus one waiting, there is a grouping to judge and it goes.
    """
    from epicrisis import indicators

    by_name = {item["folded"]: item for item in printed}

    def named(folded: str, waiting: bool) -> dict:
        printed_name = (by_name.get(folded) or {}).get("name", folded)
        return {
            "name": printed_name,
            "units": (by_name.get(folded) or {}).get("units", []),
            "times": (by_name.get(folded) or {}).get("times", 0),
            "waiting": waiting,
        }

    out = []
    for indicator in indicators.load(data_dir):
        names = [named(folded, False) for folded in sorted(indicator.names)]
        names += [named(folded, True) for folded in sorted(indicator.proposed_names)]
        if len(names) < 2:
            continue
        out.append({"indicator": indicator.id, "label": indicator.label, "names": names,
                    "status": indicator.status})  # fmt: skip
    return out


def _block(number: int, group: dict) -> str:
    names = "\n".join(
        f"  {item['name']} | {', '.join(item['units']) or 'no unit'} | printed {item['times']} times"
        + (" | waiting for a person" if item.get("waiting") else "")
        for item in group["names"]
    )
    return f"ref: {number}\nlabel: {group['label']}\nnames:\n{names}"


def names_key(group: dict) -> str:
    """What a verdict is about. A group that gained a spelling is a different question."""
    return "|".join(sorted(fold(item["name"]) for item in group["names"]))


def _worth_asking(group: dict, already: dict[str, dict]) -> bool:
    """Whether this group still needs a second reader, or has one for the names it holds now.

    A verdict is about a set of names. Where the set has changed the question is new. Verdicts
    written before the set was recorded are trusted for the names they could have seen, which is
    the group without the spellings still waiting for a person.
    """
    said = already.get(group["indicator"])
    if said is None:
        return True
    if said.get("names_key"):
        return said["names_key"] != names_key(group)
    return any(item.get("waiting") for item in group["names"])


def check_groups(data_dir: Path, printed: list[dict], backend: CheckBackend, workdir: Path,
                 say=lambda text: None, limit: int | None = None) -> dict:  # fmt: skip
    """Read every multi-spelling group again. Writes verdicts; changes no indicator."""
    already = load_checks(data_dir)
    todo = [group for group in groups_to_check(data_dir, printed) if _worth_asking(group, already)]
    if limit is not None:
        todo = todo[:limit]
    counts = {"groups": len(todo), "agreed": 0, "disagreed": 0, "names_questioned": 0, "batches": 0}
    for start in range(0, len(todo), BATCH):
        batch = todo[start : start + BATCH]
        by_ref = {str(number): group for number, group in enumerate(batch, start + 1)}
        blocks = "\n\n".join(_block(number, group) for number, group in enumerate(batch, start + 1))
        fields = backend.check(blocks, workdir)
        counts["batches"] += 1
        for answer in fields["groups"]:
            group = by_ref.get(str(answer.get("ref")))
            if group is None:
                continue
            in_group = {fold(item["name"]) for item in group["names"]}
            questioned = [
                item for item in (answer.get("does_not_belong") or []) if fold(item.get("name", "")) in in_group
            ]
            append_line(Path(data_dir) / FILE_NAME, {
                "indicator": group["indicator"],
                "label": group["label"],
                "names": len(group["names"]),
                "names_key": names_key(group),
                "waiting": [item["name"] for item in group["names"] if item.get("waiting")],
                "agrees": not questioned,
                "does_not_belong": [{"name": item["name"], "why": (item.get("why") or "")[:200]} for item in questioned],
                "by": backend.model,
                "prompt_version": PROMPT_VERSION,
                "at": now(),
            })  # fmt: skip
            if questioned:
                counts["disagreed"] += 1
                counts["names_questioned"] += len(questioned)
            else:
                counts["agreed"] += 1
        say(f"  groups {min(start + BATCH, len(todo))} of {len(todo)}")
    return counts


def _from_a_reference(looked_up: dict) -> str:
    """What a reference said about this name, in one line, for the page to show as it stands."""
    verdict = {"a test": "A reference names this test", "not a test": "A reference says this is no test",
               "unclear": "A reference could not settle this"}.get(looked_up.get("verdict"), "")  # fmt: skip
    usual = looked_up.get("usual_name")
    where = looked_up.get("found_in")
    parts = [(verdict + (f", usually called {usual}" if usual else "")).rstrip() + "."]
    if where:
        parts.append(f"Found in {where}.")
    if looked_up.get("why"):
        parts.append(looked_up["why"])
    return " ".join(part for part in parts if part).strip()


def apply_agreed(data_dir: Path, say=lambda text: None) -> dict:
    """Put into use what both readers agree on, and leave everything else exactly as it is.

    Two things are decided here, and only where a second reader has seen the whole group:

    - a spelling waiting for a person joins its indicator when the second reader did not object
      to it. Where it did, the spelling keeps waiting and a person decides.
    - a group a model proposed becomes one the archive uses when the second reader agrees with
      every name in it. Where it objects to any of them, the group keeps waiting.

    A group of a single spelling is never touched here: there is nothing to agree about, and
    whether such a test deserves an indicator at all is a person's judgement, not a reader's.
    Two models agreeing is not proof — it is only a reason not to spend a person's time.
    """
    from epicrisis import indicators

    from epicrisis.indicator_web_check import load_web_checks

    checks = load_checks(data_dir)
    # A group of one spelling has no grouping to agree about, so a second reader never sees it.
    # Where a reference confirms the name is a real test, that is the agreement it can have.
    from_the_web = {line["indicator"]: line for line in load_web_checks(data_dir).values() if line.get("indicator")}
    counts = {"spellings_added": 0, "spellings_left_waiting": 0, "groups_approved": 0, "groups_left": 0,
              "groups_confirmed_by_a_reference": 0, "in_use_a_reference_doubts": 0}  # fmt: skip
    for indicator in indicators.load(data_dir):
        said = checks.get(indicator.id)
        if said is None:
            looked_up = from_the_web.get(indicator.id)
            if looked_up:
                # What a reference said is written on every group it looked at, whatever the
                # group's standing. A group already in use that a reference calls no test is the
                # most useful thing this pass finds, and it has nowhere else to appear.
                settled = looked_up.get("verdict") == "a test"
                becomes = "approved" if settled and indicator.status == "proposed" else indicator.status
                indicators.upsert(data_dir, indicator.id, indicator.label, indicator.names, becomes,
                                  note=_from_a_reference(looked_up), source=indicator.source,
                                  reviewed=indicator.reviewed and indicator.status == becomes)  # fmt: skip
                if indicator.status == "proposed" and settled:
                    counts["groups_approved"] += 1
                    counts["groups_confirmed_by_a_reference"] += 1
                    say(f"  {indicator.label}: confirmed by {looked_up.get('found_in') or 'a reference'}")
                elif indicator.status == "proposed":
                    counts["groups_left"] += 1
                if not settled and indicator.status == "approved":
                    counts["in_use_a_reference_doubts"] += 1
            elif indicator.status == "proposed":
                counts["groups_left"] += 1
            continue
        objected = {fold(item["name"]) for item in said.get("does_not_belong") or []}
        wanted = [name for name in indicator.proposed_names if fold(name) not in objected]
        if wanted:
            indicators.decide_names(data_dir, indicator.id, wanted, accept=True)
            counts["spellings_added"] += len(wanted)
            say(f"  {indicator.label}: {len(wanted)} spelling{'s' if len(wanted) != 1 else ''} added")
        counts["spellings_left_waiting"] += len(indicator.proposed_names) - len(wanted)
        if indicator.status == "proposed":
            if said.get("agrees"):
                indicators.upsert(data_dir, indicator.id, indicator.label, indicator.names,
                                  "approved", source=indicator.source, reviewed=False)  # fmt: skip
                counts["groups_approved"] += 1
            else:
                counts["groups_left"] += 1
    return counts
