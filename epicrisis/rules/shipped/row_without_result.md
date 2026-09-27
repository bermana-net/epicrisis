+++
id = "row_without_result"
name = "A row with a unit or a range but no result"
summary = """A line of a table that has everything except the number it is about. Usually the \
result sits in a column that was not read."""
kind = "row-without-result"
attaches = "value"   # where a finding of it hangs: on a value, or on the document
order = 6             # where it stands in the queue a person works through
settles = """A row has a unit or a range but no result. The result may sit in a column that was not read. Open it and see."""
does = "marks"
at = "validate"
on_by_default = true
+++

# What it looks at

Rows of one form — one page, one printed name — where nothing among the values is the result of
that row. What counts as a result is decided in values.py, once, for every reader of it.


# How it can be wrong

A form that prints a row of headings, or a reference table with no results in it at all, looks
exactly like this.
