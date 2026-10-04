"""The page of lines that look misread: what `/misread` draws, for one archive and no other.

These findings had nowhere to be. The rules of the `suspects` step were run from exactly one
place — `epicrisis suspects` on the command line — which printed them to a terminal and stored
nothing. `update` never called the step, `index/build.py` never wrote what it found, and the
`findings` table of all three indexes of this archive held not one row of any of them while
holding hundreds of the `validate` step's. A person who did not know the command existed had no
way to learn that a hundred and twenty-five of their documents carried a signal, and one of the
rules settled with the words *open the page and read the unit*, about a page that did not exist.

**Asked here and now, rather than stored.** The other way round was open: make `suspects` a step
of `update`, write its findings beside the `validate` step's, and count them out of the index
like every other finding. It was not taken, for three reasons and one measurement:

- The step reads the index, and the index is the last thing `update` builds. Its findings could
  only be written by a second pass over a database that had just been finished, into a file the
  `validate` step owns — a second home for one answer, which `ARCHITECTURE.md` exists to prevent.
- A stored count goes stale the moment a correction lands, and this page would then disagree with
  `epicrisis suspects` over the same archive. Two places, one number, is the whole of the seventh
  entry of the constitution; one place answering both is how it is kept rather than promised.
- `rules/tally.py` already runs every rule of this step live, for the counts beside the switches
  on the settings page. A second way of getting the same numbers would be the disagreement.

The measurement is the cost of asking: 0.11 seconds over the largest archive here — 770 pages,
7,700 values — with the two rules that are on by default, and 0.12 with all five. That is the
whole of the page's own time, and it is paid only on the two pages that ask.

It gathers and counts. Nothing here judges a value, and nothing it shows is an error: a rule of
this step says a line looks as though the page was read wrong, and the person reads the page.
"""

from contextlib import closing
from pathlib import Path

from epicrisis import rules as rule_files
from epicrisis.query import IndexMissing, open_index
from epicrisis.rules import kinds
from epicrisis.settings import rules_on
from epicrisis.suspects import find, rows_from_index

# Documents shown at once. The whole list is counted and the first page of it is drawn: the owner
# of this archive asked for one line on the findings page and a page of its own behind it, in
# those words — "I shall go mad working through hundreds" — and a page that draws every one of a
# hundred and twenty-five documents with four lines each is the wall he was describing.
PAGE = 60


def how_many_look_misread(data_dir: Path, the_archive: str | None) -> dict:
    """The one line on the page of findings: how much there is, and nothing else.

    Which archive has no default, as every door into an archive here: see ARCHITECTURE.md.
    """
    gathered = what_looks_misread(data_dir, the_archive, limit=0)
    return {name: gathered[name] for name in ("missing", "every_rule_off", "documents", "findings", "rules")}


def what_looks_misread(data_dir: Path, the_archive: str | None, *, limit: int = PAGE) -> dict:
    """Every document of one archive that carries a signal, the heaviest first.

    The order is the rules' own weights and not the order the archive was walked in: a misplaced
    decimal point lies on a chart, and a form that printed no unit column does not, so the one
    has to be at the top of the list and the other at the bottom. `suspects.find` already sorts
    by it; this only says that it is what the order means.
    """
    empty = {"missing": False, "every_rule_off": False, "documents": 0,
             "findings": 0, "rules": [], "shown": [], "more": 0, "limit": limit}  # fmt: skip
    chosen = rules_on(data_dir, rule_files.load(data_dir), kinds.SUSPECTS)
    if not chosen:
        # Said rather than drawn as an empty list: every rule off and no rule written are the
        # same page otherwise, and only one of the two has anything a person can do about it.
        return {**empty, "every_rule_off": True}
    # An index that is there and will not read is not caught here, as it is not caught on the page
    # of findings either: `Unreadable` has one answer for the whole interface and it is written
    # once, in app.py, where the name of the file and the one act that mends it are already said.
    try:
        connection = open_index(data_dir, the_archive)
    except IndexMissing:
        return {**empty, "missing": True}
    with closing(connection):
        rows, documents, spellings = rows_from_index(connection)
    found = find(rows, documents, spellings, chosen)
    # What each rule has to say about itself, for the person reading the list: its name, how much
    # of this is its, and what settles one of its findings. The last is the rule's own `settles`,
    # which is the only place that sentence is written down.
    by_rule = {rule.id: rule for rule in chosen}
    per_rule: dict[str, list[int]] = {rule.id: [0, 0] for rule in chosen}
    for item in found:
        for code, times in item.codes.items():
            if code in per_rule:
                per_rule[code][0] += times
                per_rule[code][1] += 1
    said = {
        "rules": [
            {"id": rule_id, "name": by_rule[rule_id].name, "settles": by_rule[rule_id].settles,
             "weight": by_rule[rule_id].settings.get("weight", 1),
             "findings": findings, "documents": count}  # fmt: skip
            for rule_id, (findings, count) in per_rule.items()
            if findings
        ],
        "documents": len(found),
        "findings": sum(sum(item.codes.values()) for item in found),
    }
    said["rules"].sort(key=lambda rule: (-rule["weight"], rule["name"]))
    header = {sha: (document.get("doc_type"), document.get("title"))
              for document, sha in ((one, one["file_sha256"]) for one in documents)}  # fmt: skip
    shown = [
        {"sha256": item.file_sha256, "file_id": item.file_id, "first_page": item.first_page,
         "date": item.date, "weight": item.weight,
         "doc_type": header.get(item.file_sha256, (None, None))[0],
         "title": header.get(item.file_sha256, (None, None))[1],
         # The names a person reads, in the order the rules weigh them, and the lines underneath.
         "why": [{"name": by_rule[code].name, "times": times}
                 for code, times in sorted(item.codes.items(),
                                           key=lambda pair: -by_rule[pair[0]].settings.get("weight", 1))
                 if code in by_rule],
         "lines": item.lines}  # fmt: skip
        for item in found[:limit]
    ]
    return {**empty, **said, "shown": shown, "more": max(0, len(found) - len(shown))}
