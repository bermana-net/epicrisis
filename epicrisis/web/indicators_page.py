"""The indicator page: everything it shows, and everything one press of its forms does.

`indicators_view` **shows**: every group of printed spellings this instance has, what a second
reader said about each, the spellings in the open archive that no group holds yet, and the names
elsewhere in the archive that share a word with a group. Five hundred groups is what this page is
for, so the counting, the filters, the everyday word and the page of sixty are all here, where a
test can ask them without fetching an address.

`indicators_pressed` **applies a press**: it writes the one thing the form asked for, records in
the journal that somebody settled a group by hand, and builds every archive's index again where
what it changed is in the index. It hands back what was stored and what was refused as a value,
because a label that cannot be read is the one answer this page has to give and used to lose.

The vocabulary itself is the instance's and is meant to be — §1 of the constitution: that
"Гемоглобін", "Hemoglobina" and "HGB" are one test names a form and betrays nobody. What is of
one person is the counting beside each group: how many values that archive printed under each
spelling, which spellings it prints that nothing holds. So both halves take which archive as a
value with no default of its own, the way every door into an archive does.

`indicators.slug` names the files this writes, so nothing here may change what is asked of it or
the order it is asked in.

Neither half knows about `request`, `templates` or FastAPI. The routes in `web/app.py` are the
shells.

It counts printed names. It decides nothing about anybody's health.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from epicrisis import everyday_words
from epicrisis import indicators as indicator_store
from epicrisis import journal
from epicrisis import query as query_index
from epicrisis.indicator_check import load_checks
from epicrisis.printed_values import fold, in_name_order
from epicrisis.query import IndexMissing, open_index
from epicrisis.sources import TheArchives

# What the two filters of the indicator page offer. Nothing else is a filter.
INDICATOR_STATUSES = ("all", "approved", "proposed")
INDICATOR_VIEWS = ("all", "to_review", "disagreed")
# 507 groups with every spelling under each is megabytes of page: a phone should not have to
# carry the whole archive's vocabulary to look at sixty groups of it.
INDICATOR_PAGE = 60
# And the same for the names no group holds yet, which is the other long list on this page. The
# block said "307 names, most used first" over exactly two hundred rows, with no footer, no
# count of what it was showing and no next page — the one list here that was cut in silence.
# The cut stays and the page says it, with the whole of it one press away.
WAITING_PAGE = 200
# The names elsewhere in the archive that share a word with a group, per group. Twelve is what a
# <details> under a group can hold without burying the form under it, and it is a cut like any
# other: `related_total` is how many there really are, because `row.related|length` was printed
# as a claim about the archive — "12 names in the archive share a word with this one" over
# thirty-nine of the sixty groups of one archive, where the true numbers run to 78.
RELATED = 12


def _spelling(folded: str, printed: dict) -> dict:
    found = printed.get(folded)
    if found:
        return {"folded": folded, **found}
    return {"folded": folded, "name": folded, "times": 0, "units": [], "elsewhere": True}


def indicators_view(data_dir: Path, the_archive: str | None, *, status: str = "all", find: str = "",
                    show: str = "all", skip: int = 0, all_waiting: bool = False,
                    trouble: str = "") -> dict:  # fmt: skip
    """Which printed spellings are one test: the groups, their spellings, and what counts them.

    Which archive comes in as a value with no default of its own, as every door into an archive
    does. The vocabulary is the instance's; the numbers beside each group are of this archive, and
    a page showing one person's counts under another person's name is the first entry of the
    constitution.
    """
    # A status or a view that is none of the ones this page offers would silently empty it,
    # and an archive drawn with none of its vocabulary reads as an archive that lost it.
    # Anything unrecognised means no filter at all, the way an unknown view does elsewhere.
    status = status if status in INDICATOR_STATUSES else "all"
    show = show if show in INDICATOR_VIEWS else "all"
    context = {"current": "indicators", "status": status, "find": find, "show": show,
               "query": "", "trouble": trouble}  # fmt: skip
    try:
        connection = open_index(data_dir, the_archive)
    except IndexMissing:
        return {**context, "missing": True}
    try:
        printed = {item["folded"]: item for item in indicator_store.printed_names(connection)}
        materials = {
            item["id"]: [name for name in item["materials"] if name]
            for item in query_index.indicator_list(connection, status=None)
        }
    finally:
        connection.close()
    wanted = fold(find)
    assigned = indicator_store.assigned_names(data_dir)
    # What a second reader said about each group. Agreement is quiet; a disagreement is the
    # only thing here that asks for a person's time.
    checks = load_checks(data_dir)
    coverage = indicator_store.coverage(data_dir, list(printed.values()))
    labels = {item.id: item.label for item in indicator_store.load(data_dir)}

    def named_by(indicator, term: str) -> bool:
        # The names of an indicator are kept in their search form, with accents and the
        # Ukrainian and Russian letter pairs already folded; what was typed has to be folded
        # the same way or most printed names in this archive match nothing. The page says
        # above the results that they are matched as one.
        return term in fold(indicator.label) or any(term in fold(name)
                                                    for name in indicator.names + indicator.proposed_names)  # fmt: skip

    def the_groups(terms: list[str]) -> list[dict]:
        found = []
        for indicator in indicator_store.load(data_dir):
            if status != "all" and indicator.status != status:
                continue
            check = checks.get(indicator.id)
            if show == "to_review" and indicator.reviewed and not indicator.proposed_names:
                continue
            if show == "disagreed" and (check is None or check.get("agrees")):
                continue
            if terms and not any(named_by(indicator, term) for term in terms):
                continue
            found.append({
                "indicator": indicator,
                "materials": materials.get(indicator.id, []),
                # Not "values": every dict has a .values method, and a template asking for
                # row.values is handed the method rather than the number.
                "values_count": sum(printed.get(name, {}).get("times", 0) for name in indicator.names),
                # A spelling the open archive has never printed has no printed form to show:
                # what is left is the folded key, which is lower case with the letters of the two
                # alphabets merged ("леикоцити"). Shown as it is, it reads as a misspelling of a
                # name; it is marked instead, and the mark says where it came from.
                "spellings": [_spelling(name, printed) for name in sorted(indicator.names)],
                "proposed": [_spelling(name, printed) for name in sorted(indicator.proposed_names)],
                # The lookalikes, cut, and how many there are — both, because the page printed
                # the length of the cut list as the number the archive holds. See RELATED.
                "related": [{**item, "in_label": labels.get(item["indicator"])}
                            for item in coverage.get(indicator.id, [])][:RELATED],  # fmt: skip
                "related_total": len(coverage.get(indicator.id, [])),
                "check": check,
            })  # fmt: skip
        return found

    rows = the_groups([wanted] if wanted else [])
    # The word people use rather than the word a laboratory prints. "sugar" is printed on no
    # form anywhere, so this box answered nothing over an archive holding forty-four values of
    # Glucose, and the page said as much and offered no way on. Only where the box found
    # nothing by name: a question that already answers is never widened. The page says which
    # word it answered by — see everyday_words.py, and what may not be in that table.
    said_instead = ""
    if wanted and not rows:
        printed_for = everyday_words.stands_for(find)
        if printed_for:
            by_an_everyday_word = the_groups(list(printed_for))
            if by_an_everyday_word:
                rows, said_instead = by_an_everyday_word, find.strip()
    waiting = sorted((item for folded, item in printed.items() if folded not in assigned),
                     key=lambda item: -item["times"])  # fmt: skip
    # 507 groups with every spelling under each is megabytes of page: a phone should not have
    # to carry the whole archive's vocabulary to look at sixty groups of it.
    ordered = sorted(rows, key=lambda row: (-row["values_count"], in_name_order(row["indicator"].label)))
    skip = max(0, min(skip, max(len(ordered) - 1, 0)))
    return {
        # Built on the context made at the top, which carries `trouble`. Written out fresh
        # here, the one message this page exists to show — that the index could not be
        # built, so these numbers answer the old question — reached nothing at all.
        **context,
        "rows": ordered[skip : skip + INDICATOR_PAGE],
        "rows_total": len(ordered),
        # The everyday word these groups were found by, where the box found nothing under
        # the name itself. Empty otherwise, and the page says it rather than letting a
        # reader believe they typed a name a form prints.
        "said_instead": said_instead,
        "skip": skip,
        "page_size": INDICATOR_PAGE,
        # The names no group holds, cut unless the whole list was asked for, and counted whole
        # either way. The block over them said "307 names, most used first" above two hundred
        # rows and had no footer to say so: see WAITING_PAGE.
        "waiting": waiting if all_waiting else waiting[:WAITING_PAGE],
        "waiting_page": WAITING_PAGE,
        "all_waiting": all_waiting,
        "checked": len(checks),
        "disagreed": sum(1 for item in checks.values() if not item.get("agrees")),
        "waiting_total": len(waiting),
        "printed_total": len(printed),
        "to_review": sum(1 for item in indicator_store.load(data_dir) if not item.reviewed or item.proposed_names),
        "related_loose": sum(1 for items in coverage.values() for item in items if item["indicator"] is None),
        "all_indicators": sorted(indicator_store.load(data_dir), key=lambda item: in_name_order(item.label)),
    }  # fmt: skip


@dataclass(frozen=True)
class Saved:
    """What one press of this page's forms came to: what was stored, and what was refused.

    Both halves, and both as values, because the refusal is the one this page lost. A person who
    cleared the label field and pressed Save was shown one sentence of plain text on a white
    background, having lost five hundred groups off the screen — while the page already had a
    channel for saying exactly this kind of thing and it went unused. Something that hands back
    what it refused can be asked, in a test, whether it said so.

    `trouble` is the sentence the page shows: the refusal where there was one, and otherwise
    whatever the building of the indexes had to report. Never both, because a press that was
    refused built nothing.
    """

    stored: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()
    trouble: str = ""

    @property
    def said(self) -> str:
        """What was in fact written, in a person's words."""
        return ", ".join(self.stored)


def indicators_pressed(data_dir: Path, archives: TheArchives, *, action: str = "save",
                       indicator_id: str = "", label: str = "", names: str = "",
                       status: str = "approved", spelling: str = "",
                       rebuild_index: Callable[[TheArchives], str | None]) -> Saved:  # fmt: skip
    """One press of this page: the one thing it asked for, written, and said for afterwards.

    Which archive comes in as a value with no default of its own, as every door into an archive
    does. The vocabulary this writes is the instance's, but what the press asks for after it is
    every archive's index built again, and `TheArchives` is the one reading of which those are:
    asked a second time, it could be a different list. `rebuild_index` comes in the same way and
    for a plainer reason — building every archive's index again is what the settings page does
    too, so it is one thing in one place in the routes and is handed here rather than reached for.
    """
    changed = True
    settled = True  # whether this press settled something by hand, for the journal below
    if action == "save":
        try:
            indicator_store.upsert(data_dir, indicator_id or None, label, names.splitlines(), status)
        except ValueError as problem:
            # Back to the page, with the reason on it. This page is five hundred groups of the
            # vocabulary, and a person who cleared the label field and pressed Save lost the
            # whole of it for one sentence of plain text on a white background — while the page
            # already had a channel for saying exactly this kind of thing and it went unused.
            # The words travel by key rather than in the address, as everything here does.
            refusal = str(problem).capitalize() + "."
            return Saved(refused=(refusal,), trouble=refusal)
    elif action == "delete" and indicator_id:
        indicator_store.remove(data_dir, indicator_id)
    elif action in ("accept", "reject") and indicator_id:
        indicator_store.decide_names(data_dir, indicator_id, [line for line in names.splitlines() if line.strip()], accept=action == "accept")
    elif action == "assign" and indicator_id and spelling:
        indicator_store.add_names(data_dir, indicator_id, [spelling], reviewed=True)
    elif action == "drop" and indicator_id and spelling:
        indicator_store.drop_name(data_dir, indicator_id, spelling)
    elif action == "reviewed" and indicator_id:
        # "I have looked at this group" changes no spelling, so the index has nothing to learn
        # from it. Rebuilding every archive for it made working through five hundred groups —
        # which is what this page is for — five hundred full builds, each a hung request.
        indicator_store.mark_reviewed(data_dir, indicator_id)
        changed = False
    else:
        changed = False  # a form that asked for nothing this page does is not a reason to build
        settled = False
    # One spelling per line in the box, or the single one a button carries.
    how_many = len([line for line in names.splitlines() if line.strip()]) or bool(spelling)
    if settled:
        # A person working through five hundred groups of the vocabulary, one press at a time.
        # The groups themselves are in indicators.json, which is their own work; what is
        # nowhere is that they answered, and when. The file holds the answer and writes over
        # the one before it, so a group approved on Tuesday and taken apart on Wednesday
        # leaves a file saying neither ever happened.
        #
        # The word for what was pressed, the standing it was given, and how many spellings it
        # was about. Never the label and never a spelling: those are the printed names of
        # tests, and a journal that holds them says which tests this person has had.
        journal.record(data_dir, {"event": "a group of spellings was settled by hand",
                                  "action": action, "names": int(how_many),
                                  **({"status": status} if action == "save" else {})})  # fmt: skip
    # Which spellings are one test decides the indicator of every value in the index, so a
    # decision here is not a decision about a page: it is built in, at once. Seconds, no
    # model, nothing sent. Left out, the page a person went to look at was the page they had
    # just changed nothing on, and they agreed the same spelling again.
    # A build that failed leaves the page showing the old answer to a question that has changed,
    # and saying nothing is how a person comes to trust a number that is stale.
    trouble = rebuild_index(archives) if changed else None
    # What was in fact done, in the same two facts the journal is given and for the same reason:
    # the word for what was pressed and how many spellings it was about, and never the label or
    # the spelling itself. Those are printed names of tests, and anything carrying them out of
    # here could carry them into an address or a page about somebody else.
    said = int(how_many)
    stored = ((f"{action} — {said} spelling" + ("s" if said != 1 else ""),) if settled else ())
    return Saved(stored=stored, trouble=trouble or "")
