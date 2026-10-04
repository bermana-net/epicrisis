"""The kinds of document this program knows: the name a model returns, and the words a page prints.

Two names for one thing, and which of them is which decides where it may appear. The machine name
is what classify asks a model for, what the index stores, what an address carries, what a form
posts back and what a tool over the network takes. The words beside it are the only form a person
is ever shown.

They used to live apart -- the list of names in `classify/backend.py`, the words in
`web/documents.py` -- and the words were asked for in one place out of fourteen. So one path
through the dashboard spoke two languages: the feed said `lab_panel`, the card it led to said
"Lab results", the link back from a scan said "back to Lab results", and the search results said
`lab_panel` twenty-two times on one page. A person looking for their blood test had no way of
knowing those were the same kind of document.

One answer, asked by everyone: callers import `in_words`, and the templates reach the same
function through the `in_words` filter that `web/app.py` registers. Nothing keeps a second
dictionary.
"""

# What a model may answer with, and the only values the index, an address or a tool ever carries.
# Order is the order they are offered to the model in `classify/backend.py`.
DOC_TYPES = [
    "lab_panel",
    "imaging_report",
    "consultation",
    "discharge",
    "prescription",
    "referral",
    "admin",
    "insurance",
    "id_document",
    "blank",
    "other",
]

# And the words for each. Short, because they stand in a row of tabs and in a one-line caption on
# a phone, and because a reader who is scanning a list reads the first word only.
IN_WORDS = {
    "lab_panel": "Lab results",
    "imaging_report": "Imaging report",
    "consultation": "Consultation",
    "discharge": "Discharge summary",
    "prescription": "Prescription",
    "referral": "Referral",
    "admin": "Administrative",
    "insurance": "Insurance, billing",
    "id_document": "ID document",
    "blank": "Blank page",
    "other": "Other",
}


def in_words(doc_type: str | None) -> str | None:
    """What a page prints for a kind of document.

    A kind with no words of its own comes back exactly as it was given, because an index built by
    an older version of this program can hold a name this one has never heard of, and a page that
    prints the stored name is readable while a page that prints nothing is not.
    """
    if not doc_type:
        return doc_type
    return IN_WORDS.get(doc_type, doc_type)
