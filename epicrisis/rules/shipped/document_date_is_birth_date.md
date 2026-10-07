+++
id = "document_date_is_birth_date"
name = "A document dated with somebody's birthday"
summary = """A date stored as the document's own is a date of birth printed on the same page: the \
document would stand decades from where it belongs."""
kind = "a-document-date-that-is-a-birth-date"
does = "marks"
at = "extract"
on_by_default = true

[settings]
of_dates = ["date_of_study_as_printed", "date_of_report_as_printed"]
+++

# What it looks at

The dates the reading stored as the document's own, against every date of birth it can find printed
on the same pages. A form prints a birth date beside the patient's name at the top, in the same
shape as every other date on the sheet, and a reading that takes it for the date of the study files
the document in the wrong decade — in the list, on the chart, and in every answer about when
something happened.

Reading dates is `dates.py`'s work, and both halves are asked there: what a printed date means in
this document's language, and which printed dates look like dates of birth.

# How it can be wrong

A document really made on somebody's birthday fires this for ever — a yearly check-up booked on the
day is not rare — and is read correctly. There is no way to tell the two apart from the page, and
the check is the cheap half of a question whose expensive half is a second reading.

It is also blind where the birth date is printed in a form `dates.py` does not recognise as one.
