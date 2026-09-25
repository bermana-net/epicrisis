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
REVIEW = "review"  # what did not pass a check and waits for a person
LEDGER = "ledger.jsonl"  # what each step has finished, so a stopped run continues where it was
DATE_SEARCH = "date_search.jsonl"  # dates found inside documents that printed none where expected
VALIDATION = "validation.json"  # the findings of the checks that need no model
CORRECTIONS = "corrections.jsonl"  # what a person changed by hand, kept apart from what a model wrote

# The data directory itself
SOURCES = "sources.json"  # the archives this instance holds
INDICATORS = "indicators.json"  # which printed spellings are one test
SETTINGS = "settings.json"  # what this instance allows
CHATS = "chats"  # conversations of the page that asks a model questions
