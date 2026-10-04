"""Which printed names are one doctor, or one place — asked of a model, decided by a person.

The counting in people.worth_joining finds the pairs where one name stands inside another, and on
a real archive it finds them well. What it cannot see is everything else: an abbreviation beside
the full name of the same hospital, one laboratory written in two alphabets, a surname misspelt by
one letter, a legal form added in front. Those share no words, or share them in the wrong
direction, and no amount of counting will put them together.

So they are asked of a model. Only names go: the printed name and how many documents carry it. No
values, no dates, no diagnoses, no pages — the question is about spelling, and nothing else is
needed to answer it.

Two things are deliberately unlike the indicators, which this otherwise follows.

**Nothing is ever applied.** An indicator marked `sure` is applied to the archive, because being
wrong about it means two spellings of one test charted apart, and a person fixes it in a click.
Being wrong here means saying that two human beings are one — or that one is two — and no
confidence a model reports is worth that. Every group this writes waits for somebody to press a
button. There is no `sure` field to be tempted by.

**The label is not the model's to give.** It is the commonest spelling, counted; a speciality in
front of a name is not part of the name, and the forms print it the other way more often. The
model is asked which names are one and why, and that is all it is asked.

One call per kind, with every name in it. Grouping is a question about the whole list at once: two
spellings that land in different batches can never be put together, so a batch boundary is a wrong
answer by construction rather than a slower one.
"""

import hashlib
import json
from pathlib import Path

from epicrisis import people
from epicrisis.classify.backend import STRONG_MODEL, BackendError
from epicrisis.engines import engine_name
from epicrisis.printed_values import fold

TIMEOUT_SECONDS = 600
#: How much of the list of names one call may carry. Measured rather than guessed: the largest
#: archive here prints 163 institution names in 5 768 characters, so this leaves room for an
#: archive some thirty times that before anything is left out. Above it the commonest spellings go
#: and the rest are reported, because a call that is quietly cut in half is the one thing worse
#: than a call that says what it left behind.
MOST_CHARACTERS = 200_000

WHAT_THEY_ARE = {
    "doctor": "the names of doctors as the forms of five countries printed them",
    "institution": "the names of hospitals, clinics and laboratories as their own forms printed them",
}

RULES = {
    "doctor": """Two names are one doctor when:
- the same surname and the same initials stand in both, and one of them also carries a speciality, a degree or a title ("уролог", "проф.", "д-р", "Dr", "MD"), in front of the name or behind it;
- it is the same name written in another script or transliterated ("Кривопишин В.Г", "Kryvopyshyn V.H", "Кривопишин В.Г");
- the surname differs by one letter in a way a keyboard or a scanner explains, and the initials are the same.

Two names are not one doctor when:
- the initials differ, however alike the surnames: two doctors of one surname and one initial work in two clinics of every city, and a wrong join here says that two people are one;
- the surnames differ, however close they look;
- one of them is not a name at all but a word a form prints where a name goes ("лікар", "врач", "signature", a department, a kind of room).""",
    "institution": """Two names are one place when:
- one is the abbreviation or the initials of the other, and the rest matches ("Міська клінічна лікарня №7", "МКЛ №7");
- it is the same name in another language or script, or transliterated;
- one carries a legal form the other drops ("ТОВ", "ООО", "Ltd", "GmbH", "S.L.");
- one carries a department, a branch at the same address, or the name of the laboratory's own software appended to it.

Two names are not one place when:
- they are two numbered places of one city or one system ("лікарня №7" and "лікарня №3", "поліклініка №2" and "поліклініка №5"): the number is the place;
- one is a kind of institution with no name of its own ("поліклініка", "лабораторія", "clinic") and the other is a named place: a form that prints only the kind has not told you which one, and joining them puts documents under a place nobody named;
- one is a laboratory and the other a hospital that sends work to it.""",
}

SYSTEM_PROMPT = """You are given {what}, with the number of documents each name appears on. Say which of them are the same one, written differently.

{rules}

For each group, give every printed name in it, exactly as it was given to you, and one short sentence in English saying why they are the same one — what you matched. A person reads that sentence and decides; write it so that somebody who knows these documents can tell at a glance whether you are right.

Leave a name out of every group when you are not sure. A name alone is the normal answer: most names are one spelling of one person or one place, and a list with nothing to join is a good answer. Never write a name that was not given to you, and never put one name in two groups.

Nothing you say is applied. Every group waits for a person to agree with it, so a group you are unsure of is not a risk worth taking — it is a question somebody has to read and dismiss."""

SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "names": {"type": "array", "items": {"type": "string"}},
                    "why": {"type": "string"},
                },
                "required": ["names", "why"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["groups"],
    "additionalProperties": False,
}

REQUEST = """{what}, one per line as: name | documents it appears on

{names}"""

PROMPT_VERSION = hashlib.sha256(
    "\n".join([SYSTEM_PROMPT, json.dumps(RULES, sort_keys=True), json.dumps(WHAT_THEY_ARE, sort_keys=True),
               json.dumps(SCHEMA, sort_keys=True), REQUEST]).encode()
).hexdigest()[:12]  # fmt: skip


class ProposalBackend:
    """Something that can be asked one question about one list of names."""

    def __init__(self, model: str = STRONG_MODEL, executable: str = "claude", timeout_seconds: int = TIMEOUT_SECONDS,
                 data_dir=None):  # fmt: skip
        self.model, self.executable, self.timeout_seconds = model, executable, timeout_seconds
        self.data_dir = data_dir
        self.name = engine_name(data_dir)

    def call(self):
        from epicrisis import engines

        return engines.a_call(self.data_dir, model=self.model, timeout_seconds=self.timeout_seconds)

    def group(self, kind: str, names: str, workdir: Path) -> dict:
        what, rules = WHAT_THEY_ARE[kind], RULES[kind]
        fields, _ = self.call().ask(
            SYSTEM_PROMPT.format(what=what, rules=rules), SCHEMA,
            REQUEST.format(what=what[0].upper() + what[1:], names=names), workdir,
        )  # fmt: skip
        if not isinstance(fields.get("groups"), list):
            raise BackendError("no valid structured output")
        return fields


def names_to_ask_about(makers: list[dict], kind: str, groups: list[people.Group]) -> list[dict]:
    """The printed names of one kind that nobody has settled and the counting has not caught.

    A pair the word count already offers is left out on purpose: it is on the page, free and
    instant, and asking a model to find it again spends a person's limits to be told what they can
    already see. What is left is the part counting cannot do.
    """
    here = [one for one in makers if one["what"] == kind]
    already = {name for group in people.settled(groups, kind) for name in group.names}
    obvious = {name for pair in people.worth_joining(kind, [one["name"] for one in here]) for name in pair}
    return [one for one in here if one["name"] not in already and one["name"] not in obvious]


def _fits(todo: list[dict]) -> tuple[list[dict], int]:
    """The names one call can carry, commonest first, and how many were left behind."""
    by_weight = sorted(todo, key=lambda one: (-one["documents"], one["name"]))
    taken, room = [], MOST_CHARACTERS
    for one in by_weight:
        room -= len(one["name"]) + 8
        if room < 0:
            break
        taken.append(one)
    return taken, len(todo) - len(taken)


def propose_people(data_dir: Path, source_id: str, makers: list[dict], backend: ProposalBackend,
                   workdir: Path, say=lambda text: None) -> dict:  # fmt: skip
    """Ask about the doctors and then about the places. Nothing is joined; proposals are written."""
    counts = {"asked": 0, "proposed": 0, "left_out": 0, "calls": 0}
    for kind in people.KINDS:
        todo = names_to_ask_about(makers, kind, people.load(data_dir, source_id))
        if len(todo) < 2:
            continue
        asking, left_out = _fits(todo)
        counts["asked"] += len(asking)
        counts["left_out"] += left_out
        names = "\n".join(f"{one['name']} | {one['documents']}" for one in asking)
        fields = backend.group(kind, names, workdir)
        counts["calls"] += 1
        # Only names that were actually sent, matched the way every other printed name is matched
        # in this program: a model that returns a spelling with its own capitals or its own dash
        # means the name it was given, and a model that returns one nobody sent is ignored.
        sent = {fold(one["name"]): one for one in asking}
        for group in fields["groups"]:
            wanted = {sent[fold(name)]["name"] for name in group.get("names", []) if fold(name) in sent}
            if len(wanted) < 2:
                continue
            # The commonest spelling carries the group, counted here rather than asked of the
            # model: that decision belongs in one place, and this is it.
            label = max(wanted, key=lambda name: (sent[fold(name)]["documents"], -len(name)))
            before = len(people.waiting(people.load(data_dir, source_id), kind))
            after = people.propose(data_dir, source_id, kind, sorted(wanted), label, str(group.get("why", "")).strip())
            counts["proposed"] += len(people.waiting(after, kind)) - before
        say(f"  {kind}s: asked about {len(asking)}, waiting for you: {counts['proposed']}")
    return counts
