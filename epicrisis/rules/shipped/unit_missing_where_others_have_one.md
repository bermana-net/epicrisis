+++
id = "unit_missing_where_others_have_one"
name = "A value with no unit, where the same test usually prints one"
summary = """A form that printed no unit for a value, on a test whose other forms all print \
one. Either the unit column was missed when the page was read, or this laboratory left it \
out — and which of the two it is can only be seen on the page."""
kind = "unit-missing-where-others-have-one"
does = "marks"
at = "suspects"
on_by_default = true

[settings]
weight = 1            # how much the list should care; a missing unit is common, so little
least_history = 4     # readings of one test before its habits mean anything at all
+++

# What it looks at

Every value that has a number but no unit, on a test where at least a few other forms did print
one. The line says what the others print, so the page can be checked against it at a glance.

# How it can be wrong

Often, and on purpose. Old forms print a whole leukocyte formula with no unit column, and a
laboratory that never printed units will collect one of these on every line it ever issued. That
is why this weighs the least of the four: many of them together say little more than a few, and
the list caps what one signal can count in one document.

Where a test genuinely has no unit — a colour index, a ratio — this fires on nothing, because
the other forms print no unit either.
