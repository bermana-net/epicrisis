"""Step 04: checks over transcriptions that need no model. It lists, it never changes data.

Every finding names a document (file and pages), a check code and counts; values and text stay
in the transcription. The result is written whole to data/sources/<id>/validation.json.
"""

import json
import math
import re
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from epicrisis import layout
from epicrisis.classify.pages import PageUnreadable, document_payloads, page_refs
from epicrisis.classify.report import goes_to_extract, group_documents, latest_pages
from epicrisis.corrections import as_a_person_left_it, load_corrections, load_value_corrections
from epicrisis.datesearch import load_search_results
from epicrisis.dates import read_printed_date
from epicrisis.document_dates import document_date, provider_key, source_day_first
from epicrisis.eyes import measurements_named, several_measurements_in_one, the_eye_alone
from epicrisis.extract.run import load_extracted, transcription_problems
from epicrisis.material_reading import load_materials
from epicrisis.state import Unreadable, where
from epicrisis.records import read_records, torn_under
from epicrisis.printed_values import SIGNS, comparator_printed, fold, squeezed, number_matches, number_tokens
from epicrisis import reference
from epicrisis.rules import load as load_rules
from epicrisis.rules.kinds import EXTRACT, VALIDATE
from epicrisis.rules.subjects import ONE_DOCUMENT, THE_ARCHIVE, Archive, Document, Found
from epicrisis.settings import rules_on, trusts_read_materials
from epicrisis.sources import data_dir_of
from epicrisis.runs import one_at_a_time, write_whole
from epicrisis.values import is_result
from epicrisis.invocation import run

FILE_NAME = layout.VALIDATION

# The three findings that are not rules, and are not going to be. Each says what it is, where a
# finding of it hangs, what would settle it, and where it stands in the queue a person works
# through — the same four things every rule says in its own file.
#
# What is left here after possible_copy moved out is not a backlog. These three are not judgements
# about a person's data: they are this program reporting on its own reading. "Parts of the document
# were not transcribed" and "the checks still fail after the strong model" come from what the
# extract step recorded about itself; "a value that is nowhere in the text of its page" is one of
# that step's own checks, surfaced. There is nothing in them to tune and nothing to call noise, and
# a switch on them would be a switch that hides a hole in somebody's archive — which is how a
# transcription that had gone missing from disk came to be drawn as a finished step (see the note
# in web/app.py:_extract_step). They fire when something really is missing, and they stay on.
#
# **"They stay on" is now true of the checks underneath them as well, and was not for nine days.**
# Two of these three are built here out of the extract step's own checks, which became rules with
# switches of their own — so switching off `page_text_missing` and `table_page_without_values` for
# one archive took the whole of "Parts of the document were not transcribed" off the findings page,
# and nothing anywhere said the archive had a hole in it: not the status page, not `coverage`, not
# the journal, not `validate`. Measured on 23 documents: 23 of 23 to check became 19. The five
# checks those two findings are made of carry `stays_on` in `rules/kinds.py` now, which is read in
# one place — `settings.rule_on` — and keeps their thresholds, which is the knob that was wanted.
LEFTOVER = {
    "transcription_incomplete": ("document", "Parts of the document were not transcribed", 0,
        "Open the document beside the original. If pages or tables are missing, this file needs reading again."),
    "value_not_on_the_page": ("value", "A value that is nowhere in the text of its page", 2,
        "The page's own text does not contain this value. Open the page beside the card: either the layout was misread, or the page asked for something other than what it prints."),
    "checks_still_failing": ("document", "Automatic checks still fail after the strong model", 9,
        "The stronger model read this and the checks still do not pass. These need your eyes."),
}


def vocabulary(data_dir: Path | None = None) -> dict[str, dict]:
    """Every finding a person can be shown: what it is, where it hangs, what settles it, in order.

    One home for each of those, which is the rule's own file wherever the check has become a
    rule. What is left here is the handful that have not moved yet.
    """
    from epicrisis.rules import load as load_rules

    said = {code: {"kind": kind, "label": label, "order": order, "ask": ask}
            for code, (kind, label, order, ask) in LEFTOVER.items()}  # fmt: skip
    for rule in load_rules(data_dir):
        if rule.attaches:
            said[rule.id] = {"kind": rule.attaches, "label": rule.name, "order": rule.order, "ask": rule.settles}
    return dict(sorted(said.items(), key=lambda item: item[1]["order"]))


NUMBER = re.compile(r"[-+]?(?:\d+(?:[.,]\d+)?|[.,]\d+)")
# Codes from the extract checks that other checks here already cover or that do not point at an
# error. A code that belongs here and is not here is counted twice on one document: once as the
# rule's own finding, and once in "the checks still fail after the strong model" — and that second
# one answers to no switch, so turning the rule off on the settings page left the finding standing
# with nothing on the page to say why. web/settings_page.py says in its own words that this is the
# thing not to let happen.
#
# `comparator_not_printed` is half of the rule `comparator_missing`, which checks both directions,
# so a value with a sign stored and none printed made two findings of one printed fact. It fires
# on no value of the three archives here today — the shape is in the suite instead — and it is
# still asked of the extract step itself, where it decides whether a document is read again by a
# stronger model: a question about this program's own reading, and not a finding to show anybody.
#
# `provider_reads_like_a_person` — the extract step's own check, which was called
# `institution_looks_like_a_name` until it became a rule and had to stop sharing an id with the
# rule of that name at the suspects step. The two ask the same question of different things: this
# one reads a transcription as it comes back, that one reads what the index recorded. It was
# **not** in this set until the index began writing down what it does with such a name, and why it
# was not is worth keeping: covering a code whose rule is blind deletes the finding instead of
# moving it. Measured then — it fired on 15, 4 and 255
# transcriptions, which is 274 of the 285 `checks_still_failing` findings the three archives hold,
# while the rule of that name found nothing at all on any of them, because
# `index/build.institution_and_doctor` had already moved every such name out of the provider
# column the rule was reading.
#
# The index now records the move at the moment it makes it and the rule reads that record, so the
# rule finds those 274 and 9 besides: names read off the page by classify, which the extract step's
# own check cannot see because it reads the transcription's provider field and those documents have
# none there. 283 documents, one finding each, under a name, an explanation and a switch that works
# — and the 274 leave this line, which is why the code belongs here now. Turning the rule off takes
# the finding away instead of handing it back nameless, which is what this set is for.
#
# `no_column_headings` was here and is gone: nothing has produced that code since the check became
# `no_column_headings_in_multi_value_rows`, and a name in this set that nothing can say is a line
# the next reader has to go and check.
COVERED_CHECK_PROBLEMS = {"unreadable_on_images", "no_column_headings_in_multi_value_rows",
                          "comparator_not_printed", "provider_reads_like_a_person"}  # fmt: skip
# Checks that mean a transcription is incomplete: listed on their own, ahead of the rest.
INCOMPLETE_CHECK_PROBLEMS = {"page_text_missing", "page_text_short", "page_numbers_missing", "table_page_without_values"}
# Checks from the extract pass that stand on their own here, with their own line and their own
# ask, rather than being counted together as "the checks still fail".
OWN_FINDING_PROBLEMS = {"value_not_on_the_page"}


def _rows(item: dict) -> dict[tuple, list[dict]]:
    rows: dict[tuple, list[dict]] = defaultdict(list)
    for value in item["observations"]:
        rows[(value["provenance"]["page"], squeezed(value["name_as_printed"]))].append(value)
    return rows


def _found(document, value, line: str = "") -> Found:
    return Found(document.file_sha256, value["provenance"]["page"], None, line)


def number_differs(document, settings: dict) -> list[Found]:
    """The number stored is not the number printed."""
    return [_found(document, value) for value in document.item["observations"]
            if value.get("value_numeric") is not None
            and not number_matches(value["value_as_printed"] or "", value["value_numeric"])]  # fmt: skip


def comparator_missing(document, settings: dict) -> list[Found]:
    """A < or > printed and not stored, or stored and not printed.

    A comparator in words ("up to 5") counts as printed; a sign that is lost or invented does not.
    """
    found = []
    for value in document.item["observations"]:
        printed = value["value_as_printed"] or ""
        if value.get("value_numeric") is None:
            continue
        if printed.lstrip().startswith(SIGNS) and not value.get("comparator"):
            found.append(_found(document, value))
        if value.get("comparator") and not comparator_printed(printed):
            found.append(_found(document, value))
    return found


def quantitative_without_number(document, settings: dict) -> list[Found]:
    """A value counted as a number that holds none."""
    return [_found(document, value) for value in document.item["observations"]
            if value.get("value_kind") == "quantitative" and not number_tokens(value["value_as_printed"] or "")]  # fmt: skip


def reference_reversed(document, settings: dict) -> list[Found]:
    """A printed range whose lower bound is above its upper one.

    Read by reference.py, the one reader of a printed range in this program — the same reader the
    check below this one asks, and for the same reason. This had a pattern of its own, which knew
    a dash between two plain numbers and nothing else: of nine spellings of one reversed range it
    caught one, so a Spanish "17,0 a 13,0" and a Greek "5,5 έως 3,5" were never put in front of
    anybody, and neither was a range printed under a label of its own or with its unit after it.
    Which is the worst thing for this check of all the checks here to be blind in: a range that
    reads backwards is read as no range at all, so the band under the chart is missing and the
    third answer mode has nothing to compare the number with — and this check is the only thing
    that says so.
    """
    found = []
    for value in document.item["observations"]:
        ends = reference.printed_ends(value.get("reference_as_printed"))
        if ends and ends[0] > ends[1]:
            found.append(_found(document, value))
    return found


def range_read_two_ways(document, settings: dict) -> list[Found]:
    """The two readings of one printed range disagree: the model's numbers and this program's.

    Everything after the reading is done without a model, and the printed range is read by a parser
    in reference.py — a hand-written thing that has to know a decimal comma from a separator of
    thousands, a unit carrying a power, a word of direction in five languages, a label before the
    range, and a ratio that only looks like a range. It has been wrong, and when it is wrong nothing
    disagrees with it: the band is missing, or it is the wrong band, and no page says so. This asks
    the one reader that had the page in front of it for the same two numbers, and reports where the
    two answers differ.

    It reports and decides nothing. Which reading draws the band is one decision in one place —
    reference.parse, as before — and a disagreement is a thing for a person to look at, beside the
    scan of the page, exactly like every other finding here.

    Silent where the model was never asked: a document transcribed before those two fields existed
    carries neither, and the absence of an answer is not a disagreement with one.
    """
    apart_by = settings["apart_by"]

    def far_apart(ours: float | None, theirs: float | None) -> bool:
        if ours is None or theirs is None:
            return ours is not theirs  # one read a bound where the other read none
        widest = max(abs(ours), abs(theirs))
        return abs(ours - theirs) > apart_by * widest

    found = []
    for value in document.item["observations"]:
        printed = value.get("reference_as_printed")
        if not printed or ("reference_low" not in value and "reference_high" not in value):
            continue
        theirs = (value.get("reference_low"), value.get("reference_high"))
        ours = reference.parse(printed) or (None, None)
        if theirs == (None, None) and ours == (None, None):
            continue  # both say this is not one range for this person, which is an answer they share
        if any(far_apart(mine, theirs[side]) for side, mine in enumerate(ours)):
            found.append(_found(document, value))
    return found


def row_without_result(document, settings: dict) -> list[Found]:
    """A row with a unit or a range but nothing that is the result of it."""
    return [_found(document, values[0]) for values in _rows(document.item).values()
            if values and not any(is_result(value) for value in values)]  # fmt: skip


def named_after_the_eye(document, settings: dict) -> list[Found]:
    """A value named by nothing but an eye, where its own printed line names the measurement.

    "OD" and "ОС" say which eye, not what was measured, and an ophthalmic form names the
    measurement inside the line rather than in a column of its own. The reading of the line is in
    eyes.py; what is decided here is only which values are worth a person's eye.

    Silent where the stored value itself holds several measurements. A name cannot be made right
    for a field holding a whole refraction, so telling somebody to rename one would be asking for
    the wrong work; those belong to the rule beneath this one, which says what they really need.
    """
    found = []
    for value in document.item["observations"]:
        eye = the_eye_alone(value.get("name_as_printed"))
        if not eye or several_measurements_in_one(value.get("value_as_printed")):
            continue
        named = measurements_named((value.get("provenance") or {}).get("snippet"))
        if named:
            found.append(_found(document, value,
                                f'{value["name_as_printed"]} is {eye}, which is not what was measured: '
                                f'its printed line names {", ".join(named)}'))  # fmt: skip
    return found


def several_measurements_in_one_value(document, settings: dict) -> list[Found]:
    """A stored value holding the words of more than one measurement.

    The line was split in the wrong places, so one field now holds the sphere, the cylinder and
    the axis together. Nothing about the name is the matter with it and no correction to a name
    improves it: the document has to be read again.
    """
    found = []
    for value in document.item["observations"]:
        named = several_measurements_in_one(value.get("value_as_printed"))
        if named:
            found.append(_found(document, value,
                                f'{value["name_as_printed"]}: one value holding {", ".join(named)}. '
                                f'Renaming it cannot put this right — the document has to be read again'))  # fmt: skip
    return found


def dates_far_apart(document, settings: dict) -> list[Found]:
    """Pages of one document dated far apart: two documents that were cut into one.

    A scan has pages because somebody printed it, and a form that prints a date twice prints the
    same one. A text file has no pages at all — this program cuts it — and where it cut in the
    wrong place a visit of one year and a visit of another end up as one document, each page
    carrying its own date and the whole thing carrying the first. Before this archive was cut at
    the lines its own export draws, six of its twenty documents covered more than two months and
    one covered 1666 days.

    The dates are the ones the reading gave each page, not every date printed on it: a form
    carries a birth date, a date of collection and a date of report, and a rule over all of those
    fires on a third of an archive of ordinary scans.
    """
    apart = settings.get("apart_by_days", 60)
    read = sorted({printed_date.value for printed_date in
                   (read_printed_date(printed, (document.item or {}).get("language"))
                    for printed in document.page_dates) if printed_date.value})  # fmt: skip
    if len(read) < 2 or (read[-1] - read[0]).days <= apart:
        return []
    return [Found(file_sha256=document.file_sha256, first_page=document.pages[0],
                  date=read[0].isoformat(),
                  line=f"pages of one document dated {(read[-1] - read[0]).days} days apart, "
                       f"from {read[0].isoformat()} to {read[-1].isoformat()}")]  # fmt: skip


def repeated_value(document, settings: dict) -> list[Found]:
    """One line transcribed twice. The same value printed in two places is not that."""
    seen: Counter = Counter()
    where: dict[tuple, dict] = {}
    for value in document.item["observations"]:
        key = (value["provenance"]["page"], squeezed(value["name_as_printed"]),
               squeezed(value["value_as_printed"] or ""), value.get("column_as_printed"),
               squeezed(value["provenance"]["snippet"]))  # fmt: skip
        seen[key] += 1
        where.setdefault(key, value)
    return [_found(document, where[key]) for key, count in seen.items() for _ in range(count - 1) if count > 1]


def lab_without_values(document, settings: dict) -> list[Found]:
    """A laboratory panel that was transcribed and came back holding nothing."""
    if not (document.item["doc_type"] == "lab_panel" and not document.item["observations"] and document.goes_to_extract):
        return []
    return [Found(document.file_sha256, document.pages[0] if document.pages else 0, None, "")]


def unreadable_parts(document, settings: dict) -> list[Found]:
    """Parts of the page the reading itself said it could not make out."""
    return [Found(document.file_sha256, document.pages[0] if document.pages else 0, None, "")
            for _ in document.item["unreadable"]]  # fmt: skip


def date_to_check(document, settings: dict) -> list[Found]:
    """A document whose date could not be settled. What could not be settled is decided in
    document_dates.py; this only says that it is worth a person's eye."""
    if not document.date_flags:
        return []
    return [Found(document.file_sha256, document.pages[0] if document.pages else 0, None, "")]


def _the_document_of(documents: list[dict], hit: Found):
    """The one document a finding is about: its file, and the document holding the page it names.

    The hash alone is the file, and a file can hold several documents — a four-page scan that is
    two forms. Hanging a finding by hash put it on every document of the file, which turned
    forty-seven copies into a hundred and seven.

    The page it names, and not the page a document starts on. A rule is free to point at the page
    where the thing it found actually stands, which for a four-page form is usually not the first;
    matched against first pages only, such a finding belonged to no document at all and was thrown
    away in silence — a rule that runs, finds something, and is heard by nobody.
    """
    for doc in documents:
        if doc["file_sha256"] != hit.file_sha256:
            continue
        pages = doc["pages"] or [0]
        if hit.first_page in pages or hit.first_page == pages[0]:
            yield doc


def findings_for(document: Document, checked_by) -> Counter:
    """What the rules find in one document, counted by the id of the rule that found it.

    Only the rules that are handed one document. A rule of this step that looks at the archive as
    a whole is run once for all of them, after every document has been read, and would otherwise
    be handed a document and asked a question it cannot answer from one.
    """
    found: Counter = Counter()
    for rule in checked_by:
        if rule.check.looks_at != ONE_DOCUMENT:
            continue
        hits = rule.check.run(document, rule.settings)
        if hits:
            found[rule.id] += len(hits)
    return found


def validate_source(output: Path, archive_root: Path | None = None) -> dict:
    """Run every check over one archive. One run at a time: it writes that archive's findings."""
    with one_at_a_time(output / "validate.lock", "Checking this archive"):
        return _validate_source(output, archive_root)


def _validate_source(output: Path, archive_root: Path | None = None) -> dict:
    # Which of the checks run here is answered per rule and per archive; the way from an
    # archive's folder back to the instance it belongs to is written once, in sources.py.
    #
    # Which archive this is, is the name of the folder, which `sources.source_output_dir` is the
    # one place that builds — so it is read back here as that folder's name and nowhere else. One
    # check is useful on two archives and noise on a third: this archive's own answer is asked,
    # and where it has none, the instance's.
    data_dir = data_dir_of(output)
    # One reading of the registry for both steps asked about below. `Rules.at(step)` exists so
    # that one load serves them all, and this loaded the files twice three lines apart — forty-two
    # files read twice, and two readings that could in principle see two different sets if the
    # settings page wrote a rule file between them.
    loaded = load_rules(data_dir)
    checked_by = rules_on(data_dir, loaded, VALIDATE, in_archive=Path(output).name)
    # The extract step's own checks, as this archive has them switched. They are re-run here to
    # report on them and never acted on: what they decide — whether a document goes back to a
    # stronger model — was decided when it was read. Asked of the same registry and the same
    # switches as the step itself, because a check turned off for an archive must not go on
    # producing findings about it from this side.
    extract_checks = rules_on(data_dir, loaded, EXTRACT, in_archive=Path(output).name)
    records = {record["sha256"]: record for record in read_records(output / layout.INVENTORY) if "sha256" in record}
    pages = latest_pages(output / layout.CLASSIFY)
    corrections = load_corrections(output)
    # What a person put right themselves. The checks used to read only what the model wrote, so a
    # value somebody had corrected went on being reported as wrong for ever, and a row they had
    # marked as not a value went on producing findings. The only way to clear either was to call
    # the check noise — that is, to say of one's own correction that the check had been mistaken.
    # A list of work that does not shrink as the work is done is not a list of work.
    value_corrections = load_value_corrections(output)
    searches = load_search_results(output)
    # The specimen a model read off a table heading the form left unlabelled, and only where the
    # person whose archive this is has said those readings may be used — the same switch the index
    # asks, and asked here because a check that groups values of one test by what they were
    # measured in has to know the whole answer and not the printed part of it. layout.BUILT_FROM
    # has listed MATERIALS under this step since it was written; nothing here read the file.
    read_materials = load_materials(output) if trusts_read_materials(data_dir_of(output)) else {}

    groups = group_documents(pages)
    day_first_documents, day_first_providers = source_day_first(output, groups)
    documents = []
    # The heading of the last document seen in each file, with the page it ended on: what the back
    # of a two-sheet form needs in order to know which form it is the back of. Read the same way
    # the index reads it, because it is an input to the same decision.
    before: dict[str, tuple[int, str | None]] = {}
    for group in groups:
        sha256, numbers = group[0]["file_sha256"], tuple(page["page"] for page in group)
        if sha256 not in records:
            continue
        extracted = load_extracted(output / layout.EXTRACTED, sha256)
        item = next((doc for doc in (extracted or {"documents": []})["documents"] if tuple(doc["pages"]) == numbers), None)
        if not goes_to_extract(group[0]):
            item = None
        # Two readings of one document, on purpose, and each check gets the one it is asking about.
        # The value checks ask what the archive now holds, which is the transcription with this
        # archive's corrections on it. The transcription check asks whether the model wrote down
        # what was on the page, and judging that by a correction a person made afterwards is
        # answering a different question: the person's reading would be reported as the model's
        # mistake, and correcting a value would add a finding instead of taking one away.
        as_left = item
        if item is not None and value_corrections:
            as_left = {**item, "observations": as_a_person_left_it(
                item["observations"], sha256, numbers, value_corrections)}  # fmt: skip
        date = document_date(
            item, group, correction=corrections.get((sha256, numbers, "document_date")), search=searches.get((sha256, numbers)),
            day_first=(sha256, numbers) in day_first_documents or provider_key(item, group) in day_first_providers,
        )
        # Only the page immediately before, and only in the same file: a form's back page is the
        # next sheet of the same form, never a document further off in the folder.
        ended = before.get(sha256)
        carries_on_from = ended[1] if ended and ended[0] == numbers[0] - 1 else None
        before[sha256] = (numbers[-1], (item or {}).get("title_as_printed"))
        tabular = tuple(page["page"] for page in group if page.get("has_tabular_results"))
        subject = Document(file_sha256=sha256, pages=numbers, item=as_left, tabular_pages=tabular,
                           goes_to_extract=goes_to_extract(group[0]), date_flags=tuple(date["flags"]),
                           page_dates=tuple(page.get("date_on_page") for page in group))  # fmt: skip
        findings = findings_for(subject, checked_by)
        # The extract step's own checks, by code, before they are folded into the three summaries
        # below. Codes and counts, nothing of anybody's — the same thing the journal is allowed to
        # hold. They are kept because the folding is lossy and was unmeasurable: eleven checks
        # arrive here and three numbers leave, so a check that changed its mind about a document
        # moved a summary by one and no ruler could say which check it was. The snapshot that
        # guards the move of these checks into the registry reads this field and adds them up
        # again against the summaries.
        problems: dict[str, int] = {}
        if item:
            # Checks run again with today's rules: the page text for text pages, the transcription otherwise.
            problems = transcription_problems(item, _sent_texts(records[sha256], numbers, archive_root),
                                               tabular, checked_by=extract_checks)  # fmt: skip
            incomplete = {code: count for code, count in problems.items() if code in INCOMPLETE_CHECK_PROBLEMS}
            if incomplete:
                findings["transcription_incomplete"] += sum(incomplete.values())
            for code in OWN_FINDING_PROBLEMS & problems.keys():
                findings[code] += problems[code]
            still = {code: count for code, count in problems.items()
                     if code not in COVERED_CHECK_PROBLEMS | INCOMPLETE_CHECK_PROBLEMS | OWN_FINDING_PROBLEMS}  # fmt: skip
            if still:
                findings["checks_still_failing"] += sum(still.values())
        # as_left, the same reading every line-by-line check is given: the transcription with what
        # a person corrected on top of it. The raw one went to the rules of the whole archive, so
        # the check for copies compared documents by what a model wrote and not by what the person
        # left — and a list of work that does not shrink as the work is done is not a list of work,
        # which is written twenty lines above this and was true of every check but that one.
        documents.append({"file_sha256": sha256, "pages": list(numbers), "date": date["value"],
                          "item": as_left, "findings": findings, "checks": dict(problems),
                          "carries_on_from": carries_on_from})  # fmt: skip

    # The rules of this step that look at the archive as a whole, rather than at one document:
    # they run once, after every document has been read, and hang their findings on the documents
    # they are about. A rule that is switched off does not run and finds nothing, here as anywhere.
    for rule in checked_by:
        if rule.check.looks_at == THE_ARCHIVE:
            # The archive as this step can give it: every document with its transcription, and no
            # rows. The same subject at the suspects step is built whole, out of the index, with
            # the habits and numbers of every test in it — so a rule written against those finds
            # nothing here rather than failing, and the halves are named here instead of guessed
            # at. kinds.SERVED says which steps hand out this subject at all.
            for hit in rule.check.run(Archive(rows=[], documents=documents, read_materials=read_materials),
                                      rule.settings):  # fmt: skip
                for doc in _the_document_of(documents, hit):
                    # Counted, not set. A rule of the whole archive may have several things to say
                    # about one document, and the line-by-line path beside this one counts them;
                    # this one wrote 1 whatever it was handed, so one rule was counted two ways
                    # depending only on which subject it happens to take.
                    doc["findings"][rule.id] += 1
    result = {
        "validated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "documents": [
            {"file_sha256": doc["file_sha256"], "pages": doc["pages"], "findings": dict(doc["findings"]), "copies": doc.get("copies", [])}
            for doc in documents
            if doc["findings"]
        ],
        "totals": dict(sum((doc["findings"] for doc in documents), Counter())),
        # The extract step's own checks, by code, for **every** document and not only for the ones
        # that ended with a finding: four of these codes are covered by rules elsewhere and make no
        # finding at all, so the list above cannot see them. Codes and counts, nothing of anybody's.
        # The list of documents above keeps its own shape — the dashboard counts its length and
        # means "documents with something to look at" by it — so this stands beside it rather than
        # widening it.
        "checks": {f"{doc['file_sha256']}:{'.'.join(str(page) for page in doc['pages'])}": doc["checks"]
                   for doc in documents if doc["checks"]},  # fmt: skip
        "coverage": coverage(output),
        "documents_checked": len(documents),
    }
    path = output / FILE_NAME
    write_whole(path, json.dumps(result, ensure_ascii=False, indent=1) + "\n")
    return result


def coverage(output: Path) -> dict:
    """Whether every file, page and due document went through the pipeline. Counts, and file ids for gaps."""
    records = list(read_records(output / layout.INVENTORY))
    pages = latest_pages(output / layout.CLASSIFY)
    classified = {(page["file_sha256"], page["page"]) for page in pages}
    by_sha = {record["sha256"]: record for record in records if "sha256" in record}
    skipped = [record for record in records if not page_refs(record) and "sha256" in record]
    unclassified = [(sha256, ref.page) for sha256, record in by_sha.items() for ref in page_refs(record) if (sha256, ref.page) not in classified]
    due = [group for group in group_documents(pages) if goes_to_extract(group[0]) and group[0]["file_sha256"] in by_sha]
    untranscribed = []
    for group in due:
        extracted = load_extracted(output / layout.EXTRACTED, group[0]["file_sha256"])
        numbers = [page["page"] for page in group]
        if not any(doc["pages"] == numbers for doc in (extracted or {"documents": []})["documents"]):
            untranscribed.append((group[0]["file_sha256"], numbers))
    return {
        "files": len(by_sha),
        "files_not_read": [{"file_id": record["sha256"][:8], "reason": record.get("unsupported") or record.get("error") or record.get("category")} for record in skipped],
        "pages": sum(len(page_refs(record)) for record in by_sha.values()),
        "pages_not_classified": len(unclassified),
        "documents_due": len(due),
        "documents_not_transcribed": [{"file_id": sha256[:8], "pages": numbers} for sha256, numbers in untranscribed],
        # Lines this run could not read, from this archive's own files. read_records skips a torn
        # line and counts it, which is right — one lost record must not take the rest of an archive
        # down — but the count was asked for in exactly one place, a page of the dashboard, in
        # another process. From a terminal the archive simply got smaller and every number agreed
        # with every other: forty-three files became forty-two, and nothing said a word.
        "lines_not_read": torn_under(output),
    }


def validation_state(output: Path) -> dict:
    """Whether validation ran after the latest change to what it reads."""
    result = load_validation(output)
    if result is None:
        return {"state": "not_started", "label": "", "title": "Validate: not run yet"}
    changed = layout.changed_since(output, data_dir_of(output), "validate")
    ran = (output / FILE_NAME).stat().st_mtime
    documents = len(result["documents"])
    if ran < changed:
        return {"state": "partial", "label": "Outdated", "title": f"Validate: {documents} documents to check, data changed since"}
    return {"state": "done", "label": str(documents), "title": f"Validate: {documents} of {result['documents_checked']} documents to check"}


def _sent_texts(record: dict, pages: tuple[int, ...], archive_root: Path | None) -> dict[int, str]:
    """The text a text-layer document was sent as; empty for documents that went as images."""
    if archive_root is None:
        return {}
    by_page = {ref.page: ref for ref in page_refs(record)}
    refs = [by_page[page] for page in pages if page in by_page]
    if len(refs) != len(pages) or any(ref.route == "vision" for ref in refs):
        return {}
    with tempfile.TemporaryDirectory(prefix="epicrisis-validate-") as workdir:
        try:
            payloads = document_payloads(refs, archive_root, Path(workdir))
        except PageUnreadable:
            return {}
    return {ref.page: payload.text for ref, payload in zip(refs, payloads, strict=True) if payload.text is not None}


def load_validation(output: Path) -> dict | None:
    """The findings of the last run of the checks, or nothing where they have not been run.

    A file that is there and will not parse is neither, and it used to be raised from here into
    whatever was drawing the page: the status page and the page of things to check both answered
    with the words Internal Server Error, while the five pages that live on the index went on
    working — so the archive was half open and nothing said why. The way out is the cheapest in
    this program, and nothing named it: these findings are made by code, in seconds, with no model
    and nothing sent anywhere.
    """
    path = output / FILE_NAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as broken:
        raise Unreadable(
            where(path),
            "Nothing that was read is lost. These are the findings of the checks that need no "
            "model: they are made from what is already on this machine, in seconds.",
            # The command, with the archive and the instance in it, and nothing about a button.
            # This same file draws the status page and the page of things to check, so both are
            # down while it is torn — and "press Check again on the status page" sent a person who
            # lives on the dashboard to the one page that could not answer them, over the half of
            # the advice addressed to them. A way out that is not there is worse than one way out.
            f"Run them again: {run(f'validate --source {output.name}', data_dir_of(output))}. They "
            f"need no model and send nothing anywhere. The Check again button cannot be used for "
            f"this one: the status page it stands on is drawn from this same file and is down with "
            f"it until the checks have been run.",
        ) from broken


def possible_copies(documents: list[dict], settings: dict) -> list[Found]:
    """Documents in different files with the same date that print the same results.

    Either the same named values (any size, one file an excerpt or export of the other), or
    for longer documents of similar size mostly the same values.

    A rule of the registry rather than a check written into this file: the four numbers below
    decide what counts as a copy, they were constants nobody could see or move, and "is this a
    copy" is exactly the kind of judgement a person may want tuned, measured, or turned off —
    which is what the registry is for. It writes the list of twins onto each document as it
    goes, because the page that asks a person to choose which file answers for a group needs to
    know what the group is.
    """
    by_date = defaultdict(list)
    for doc in documents:
        if doc["item"] and doc["date"] and doc["item"]["observations"]:
            by_date[doc["date"]].append(doc)
    found: list[Found] = []
    already: set[int] = set()
    for group in by_date.values():
        for position, one in enumerate(group):
            for other in group[position + 1 :]:
                if one["file_sha256"] == other["file_sha256"]:
                    continue
                if not (_same_named_values(one["item"], other["item"], settings)
                        or _mostly_same_values(one["item"], other["item"], settings)):  # fmt: skip
                    continue
                for doc, twin in ((one, other), (other, one)):
                    # One finding per document, however many twins it has: a group of three used
                    # to report six findings over three documents, which reads as twice the work.
                    if id(doc) not in already:
                        already.add(id(doc))
                        found.append(Found(doc["file_sha256"], doc["pages"][0] if doc["pages"] else 0,
                                           doc["date"], ""))  # fmt: skip
                    doc.setdefault("copies", []).append({"file_sha256": twin["file_sha256"], "pages": twin["pages"]})
    return found


def _named_values(item: dict) -> set[tuple[str, str]]:
    """What a document says, as (name, value) pairs — the decimal separator taken out of it.

    One export writes 5,2 where another writes 5.2 for the same result, and two files of one
    blood draw were not seen as copies of each other because of the comma.
    """
    return {
        (fold(observation["name_as_printed"]).strip(" :"), squeezed(observation["value_as_printed"]).replace(",", "."))
        for observation in item["observations"]
        if is_result(observation)
    }


def _same_named_values(one: dict, other: dict, settings: dict) -> bool:
    """Identical named results, or all results of one document found in the other."""
    a, b = _named_values(one), _named_values(other)
    if not a or not b:
        return False
    small, large = sorted((a, b), key=len)
    return small == large or (len(small) >= settings["results_in_common"] and small <= large)


def _mostly_same_values(one: dict, other: dict, settings: dict) -> bool:
    """Mostly the same results, named. Numbers alone made copies of two different forms.

    A urinalysis and a coprogram from one day print the same handful of small numbers — 0, 1,
    1-2, 2-3 — and were filed as one document, after which one of them answered nothing at all,
    because only one document of a group of copies is shown.
    """
    a, b = _named_values(one), _named_values(other)
    if min(len(one["observations"]), len(other["observations"])) < settings["results_at_least"] or not a or not b:
        return False
    if min(len(a), len(b)) < settings["similar_in_size"] * max(len(a), len(b)):
        return False
    return len(a & b) >= settings["results_shared"] * min(len(a), len(b))


# One printed range against the ranges printed beside the rest of its own test
#
# A haematocrit stored as 0,48 was drawn as 48 per cent, correctly, with «0,2-1,0 %» printed
# beside it as its range, and the axis of the chart stretched from a fifth of a per cent to fifty.
# 0,2–1,0 % is the line of basophils on the same form. No haematocrit is ever that, and the band
# under that chart belonged to another row of the page.
#
# What makes the question answerable without judging anybody's health: a printed reference range
# is a fact about the test and the laboratory, never about the person. One person's haematocrit
# may read 21 one year and 48 the next, and both are theirs — while the range printed beside both
# is 35–50 either way. So the ranges of one test are weighed against each other and the stored
# value is not read at all. "This reading is far from normal" is the thing the whole program
# exists to show, and it cannot reach this check even in principle.


def range_powers_from_the_rest(archive, settings: dict) -> list[Found]:
    """A printed range powers of ten from the ranges printed beside the rest of its test.

    One test, one printed unit and one specimen at a time, over every document at once: the middle
    of a range is taken geometrically, in units.band_middle, and the middle of the test's ranges is
    the median of those. A range far from that median is reported, and nothing is reported unless
    most of the test's ranges agree with the median in the first place — a test two laboratories
    print at two scales is not one range, and which of its ranges is the odd one is then a question
    with no answer. Moving the points of such a test is the business of the two-scales reading in
    units.py; this check steps aside from it rather than shouting over it.

    Silent where no unit is printed, in the column or inside the range itself. Without a printed
    unit the form has not said what scale its range is at, and then a range at another size is
    indistinguishable from a form printing the whole test at another scale — a haematocrit written
    as a fraction, 0,35-0,50 beside 0,44, which is an honest form and not a misplaced row.

    It never says which row a range came from, and never moves or alters it: the band under the
    chart is drawn from the printed text as before. It says the row is worth a person's eye.
    """
    # Inside the function because index/build imports this module: asked for at the top of the
    # file, neither of the two would load at all. What is wanted from there is a reading of the
    # same transcription and nothing else — a total protein in serum and a protein in urine are
    # printed under one name in one unit and are a thousand apart, so the specimen has to be part
    # of what counts as "the same test" or every urine protein in the archive is a finding.
    #
    # settled_material and not material_of, which answers only with the word the form printed.
    # Three shapes it says nothing about, and in each of them two tests under one printed name
    # fell into one group and the range of one was reported as a range that cannot be the other's
    # — a false finding on exactly the test the paragraph above warns about. A specimen a model
    # read off an unlabelled heading (which is what material_reading is for, and most old forms
    # have no heading); a table printed sideways, where the row names the specimen; and a
    # material the person whose archive this is corrected by hand. The third is the worst: "their
    # word wins" is written where that order is decided, and this check could not see their word.
    from epicrisis.corrections import BY_A_PERSON
    from epicrisis.index.build import inverted_tables, settled_material
    from epicrisis.units import band_middle, unit_from_reference, unit_key

    of_a_test: dict[tuple, list[tuple[dict, dict, float]]] = defaultdict(list)
    for doc in archive.documents:
        item = doc["item"]
        sideways = inverted_tables((item or {}).get("observations", ()))
        for value in (item or {}).get("observations", ()):
            printed = value.get("reference_as_printed")
            middle = band_middle(reference.parse(printed))
            name = fold(value.get("name_as_printed")).strip()
            unit = unit_key(value.get("unit_as_printed")) or unit_from_reference(printed) or ""
            if middle is None or not name or not unit:
                continue
            material, _ = settled_material(
                value, item, doc.get("carries_on_from"), archive.read_materials,
                doc["file_sha256"], tuple(doc["pages"]), value.get(BY_A_PERSON),
                (value.get("table_as_printed") or "").strip() in sideways,
            )  # fmt: skip
            of_a_test[(name, unit, material)].append((doc, value, math.log10(middle)))

    found: list[Found] = []
    for group in of_a_test.values():
        if len(group) < settings["ranges_at_least"]:
            continue
        powers = [power for _, _, power in group]
        middle_of_the_test = median(powers)
        # What counts as agreeing with the rest is the same distance that counts as standing away
        # from it, and not a second number of its own: a test is one range when most of its
        # printed ranges are ranges this check would not report. Written as its own constant it
        # would have been a threshold nobody could see, move or measure — which is the defect the
        # registry exists to undo, and it would have sat eight lines above the three settings
        # saying so.
        apart = [abs(power - middle_of_the_test) for power in powers]
        if sum(one < settings["powers_apart"] for one in apart) < settings["ranges_agree"] * len(powers):
            continue
        for (doc, value, _), stands in zip(group, apart, strict=True):
            if stands < settings["powers_apart"]:
                continue
            page = (value.get("provenance") or {}).get("page") or (doc["pages"][0] if doc["pages"] else 0)
            found.append(Found(doc["file_sha256"], page, doc["date"],
                               f"the range printed beside it stands about {round(10**stands)} times from the "
                               f"ranges printed beside the other readings of this test"))  # fmt: skip
    return found

