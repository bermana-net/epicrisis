"""The names of the files this program writes beside an archive.

Nothing here decides anything; it only says what a thing is called. That is enough to matter: the
name of the classification file was written out as a string in ten modules and twenty-seven
places, the extracted folder in twelve, the inventory in eleven. A second layout — one folder per
person, say, or a different name for an organisation running several archives — would have meant
finding every one of them, and the first one missed would have written a file nobody reads again.

Where they sit is decided in sources.py, which knows what an archive is; this says what to call
the files inside. The two are on purpose apart: a file moves house more often than it is renamed.
"""

# One source's output directory
INVENTORY = "inventory.jsonl"  # every file found, with its hash and what kind of thing it is
INVENTORY_STATUS = "inventory.status.json"  # how far the last scan of the folder got
CLASSIFY = "classify.jsonl"  # what kind of document each page is, as a model read it
EXTRACTED = "extracted"  # the values of each document, one file per document, named by hash
RECHECKED = "rechecked"  # the same documents read a second time by another model
REPLACED = "replaced"  # readings that a later reading displaced, kept because they were somebody's
LEDGER = "ledger.jsonl"  # what each step has finished, so a stopped run continues where it was
DATE_SEARCH = "date_search.jsonl"  # dates found inside documents that printed none where expected
JUDGEMENTS = "judgements.jsonl"  # what a person said about a finding: real, or noise
VALIDATION = "validation.json"  # the findings of the checks that need no model
CORRECTIONS = "corrections.jsonl"  # what a person changed by hand, kept apart from what a model wrote

# The data directory itself
SOURCES = "sources.json"  # the archives this instance holds
INDICATORS = "indicators.json"  # which printed spellings are one test
SETTINGS = "settings.json"  # what this instance allows
CONSENT = "consent.json"  # that somebody agreed, once, to pages going to a model
CHATS = "chats"  # conversations of the page that asks a model questions
MATERIALS = "materials.jsonl"  # what a model read the heading of each table as

# Whose work each of these is, which is a different question from where it lives and turned out to
# matter more. Everything under data/ was described in one word — "derived" — and told a person they
# could delete the lot and have it rebuilt. Most of it, yes. Some of it only by paying a model to
# read five hundred documents again, and differently. And some of it is nobody's but the person's:
# they typed it, one line at a time, and no code and no money makes it again.
#
# Named here so that a backup, a "start again", and a page that offers to delete something can each
# ask the same question and get the same answer.
THEIR_OWN_WORK = (
    CORRECTIONS,  # what they changed by hand, against their own printed line
    JUDGEMENTS,  # what they said about a finding: real, or noise
    INDICATORS,  # the groups of spellings they approved, one at a time
    REPLACED,  # the only copy of a reading that a later reading displaced
    CHATS,  # what they asked and what was answered
)
# Their answers rather than their work: minutes to give again by hand, and gone without a word if
# nobody carries them. sources.json is here because it is the only thing that says which random id
# belongs to which folder, and without it nothing else in a copy can be put back.
THEIR_CHOICES = (SOURCES, SETTINGS)
# Made again by code alone, in seconds or minutes, from what is already on this machine.
MADE_AGAIN_BY_CODE = (INVENTORY, INVENTORY_STATUS, VALIDATION)
# Made again only by a model reading the documents again: money, hours, and a different result.
MADE_AGAIN_BY_A_MODEL = (CLASSIFY, EXTRACTED, RECHECKED, LEDGER, DATE_SEARCH, MATERIALS)
# Asked for again instead of carried: consent is a person saying yes to this instance, and a
# restored copy should ask rather than assume. Named here so that "not carried" is a decision
# written down rather than a file nobody remembered.
ASKED_FOR_AGAIN = (CONSENT,)


# What each step reads, so that it can say whether it has run since any of them changed. Written
# once because it was written twice and both copies were short: the checks did not count
# settings.json, so turning a rule off left their badge saying "done" and the index went on
# hiding documents by the old answer; and the index did not count inventory.jsonl, although it
# builds its whole table of files out of it.
#
# Each entry is (what is read inside an archive's own folder, what is read from the data directory).
BUILT_FROM = {
    "validate": ((CLASSIFY, CORRECTIONS, DATE_SEARCH, EXTRACTED, INVENTORY, MATERIALS), (SETTINGS,)),
    "index": ((CLASSIFY, CORRECTIONS, DATE_SEARCH, VALIDATION, EXTRACTED, INVENTORY, MATERIALS),
              (INDICATORS, SETTINGS)),  # fmt: skip
}


def changed_since(output, data_dir, step: str) -> float:
    """When anything this step reads last changed, as a moment to compare a step's own file with.

    One function so that a step cannot be told it is up to date by a list somebody forgot to add
    to. The two lists this replaces were each short by a file, and both mistakes looked the same
    from outside: a badge saying "done" over an answer that was no longer the answer.

    Every input is a file and answers with the moment it was written, except one. settings.json
    holds every choice a person makes about this instance — the engine, three models, what an
    answer may contain, nineteen rules and their thresholds, the lock over the network — and its
    mtime moves for all of them alike. Compared as a file, it said that changing what the Ask page
    may say had aged the index: a banner over every page of every archive on the server, "This
    index is older than the files it is built from", which nothing but building each archive's
    index again would take off. So for that one the question is asked of the values a step is
    actually built from, and the answer comes from settings.changed_for.
    """
    from pathlib import Path

    here, instance = BUILT_FROM[step]
    paths = [Path(output) / name for name in here]
    paths += [Path(data_dir) / name for name in instance if name != SETTINGS]
    moments = [path.stat().st_mtime for path in paths if path.exists()]
    if SETTINGS in instance:
        from epicrisis import settings

        moments.append(settings.changed_for(data_dir, step))
    return max(moments, default=0)
