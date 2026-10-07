+++
id = "lab_form_without_a_title"
name = "A laboratory form read with no title at all"
summary = """A transcribed laboratory form that came back with no title. Most forms print one, \
so its absence usually means the top of the page was not read — and the top of the page is \
where the date and the institution live."""
kind = "lab-form-without-a-title"
attaches = "document"
settles = """Open the document and read the top of the page; every one of these is listed on Looks misread, behind the line on To check. If a title is printed there and was not read, the page may be worth reading again."""
does = "marks"
at = "suspects"
# Off, because nothing it finds makes a number wrong. A form read with no title is harder to find
# by name and nothing else: every value on it, its unit and its printed range are whatever the
# page said. A row that changes no reading is a row between a person and the ones that do, and an
# archive of scans hands this a queue of them. Switch it on when the thing being worked on is
# finding documents rather than trusting their numbers.
on_by_default = false

[settings]
weight = 1
+++

# What it looks at

Documents classified as a laboratory panel, transcribed, and holding no title. It says nothing
about pages that were never transcribed: those are already elsewhere in the checks.

# How it can be wrong

Plenty of real forms print no title — a continuation page, a machine printout, a fax that lost
its header. This is why it weighs the least along with the missing unit: on its own it means
almost nothing, and it earns its place by piling onto a document that other signals also point
at.
