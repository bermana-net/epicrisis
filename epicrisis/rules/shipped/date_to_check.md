+++
id = "date_to_check"
name = "A document whose date could not be settled"
summary = """Several dates on the page and no way to tell which is the study; a date in a \
format that reads two ways; or no date anywhere at all."""
kind = "date-that-could-not-be-settled"
does = "marks"
at = "validate"
on_by_default = true
+++

# What it looks at

What `document_dates.py` could not settle. **The deciding is there, not here**: this rule only
says that what it could not settle is worth a person's eye, and turning it off hides the
question without changing a single date.

# What settles it

Set the date by hand on the card, or leave it as it was read. A date set by hand is kept apart
from what the model read and survives the document being read again.

# How it can be wrong

A document with no date printed anywhere will be flagged for ever, because there is nothing on
the page that would ever settle it. Those belong on the "date unknown" shelf and a date is never
invented for them.
