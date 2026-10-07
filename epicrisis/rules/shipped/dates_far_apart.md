+++
id = "dates_far_apart"
name = "Pages of one document dated far apart"
summary = """Two pages of one document carry dates a long way apart, which is what two documents \
cut into one looks like."""
kind = "dates-far-apart-in-one-document"
attaches = "document"
order = 15
settles = """Look at the pages. If they are two documents, the cut was wrong; if one document \
printed two dates, there is nothing to do."""
does = "marks"
at = "validate"
on_by_default = true

[settings]
apart_by_days = 60
+++

# What it looks at

The date the reading gave each page of a document, and nothing else on the page. A form carries a
birth date, a date of collection and a date of a report; a rule over every date printed anywhere
fires on much of an archive of ordinary scans and says nothing.

A scan has pages because somebody printed it on paper, and the pages of one form belong together
whatever dates they carry. **A text file has no pages at all** — this program cuts it into them —
and that is where this earns its keep: where the cut fell inside a run of visits, a visit of one
year and a visit of another are stored as one document, and the whole of it is dated by the first.
An export of a clinic's own system is years of visits in a single file, so a document of it that
spans seasons is a cut in the wrong place every time, and cutting the file where its own export
draws its lines is what makes these go quiet.


# How it can be wrong

A discharge summary is admitted on one date and discharged on another, and a laboratory sheet is
collected one day and reported the next. Those are days apart, not months, which is what the
threshold is for. A consultation that quotes an older study on its second page is a real document
with a real older date in it, and will be reported — the quoting is worth knowing about, but the
cut was right.
