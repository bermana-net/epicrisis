+++
id = "row_without_result"
name = "A row with a unit or a range but no result"
summary = """A line of a table that has everything except the number it is about. Usually the \
result sits in a column that was not read."""
kind = "row-without-result"
does = "marks"
at = "validate"
on_by_default = true
+++

# What it looks at

Rows of one form — one page, one printed name — where nothing among the values is the result of
that row. What counts as a result is decided in values.py, once, for every reader of it.

# What settles it

Open it and see. The result is often in a further column, a previous value or a second specimen,
and finding it means the table was read one column short.

# How it can be wrong

A form that prints a row of headings, or a reference table with no results in it at all, looks
exactly like this.
