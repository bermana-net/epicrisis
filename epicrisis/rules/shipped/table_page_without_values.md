+++
id = "table_page_without_values"
name = "A page of a table from which no value was stored"
summary = """Classification said this page carries a table of results and the reading stored \
nothing from it. Asked of laboratory results only."""
kind = "table-page-without-values"
does = "marks"
at = "extract"
on_by_default = true

[settings]
of_document_types = ["lab_panel"]
+++

# What it looks at

The pages an earlier step marked as carrying a table of results, against the pages the stored
values actually came from. A page in the first list and not the second is a table that was seen and
not read.

Laboratory results only, as shipped. A discharge summary, a letter, a prescription — all of them
print tables inside their text, and a model that reads one as prose has done nothing wrong.

# How it can be wrong

It inherits whatever the classification step decided. A page classified as holding a table that
holds a key, a legend or a block of reference ranges and no results at all is a page this fires on
for ever: the table is there, the values are not, and both readings are correct.

Adding a document type to the list is a decision about that type across the whole archive, not
about one form. Where one laboratory's discharge summaries really do carry the results in a table
and nothing else does, turning this on for `discharge` sends every discharge in the archive with an
unread table back to a stronger model — including the ones whose table is a list of medicines.
