+++
id = "unit_missing_where_others_have_one"
name = "A value with no unit, where the same test usually prints one"
summary = """A form that printed no unit for a value, on a test whose other forms all print \
one. Either the unit column was missed when the page was read, or this laboratory left it \
out — and which of the two it is can only be seen on the page."""
kind = "unit-missing-where-others-have-one"
attaches = "document"
settles = """Open the document beside the original; every one of these is listed on Looks misread, behind the line on To check. If the form prints a unit, add it on the card; most old forms print none, and then there is nothing to do."""
does = "marks"
at = "suspects"
# Off, because it is noise here rather than a signal. Almost everything it found where it was
# measured was a form with no unit column at all — which is what it says itself under "How it can
# be wrong", and which the rule above has its own line for. Nothing a reader of those ever did was
# wrong, and a queue of them in front of the few worth opening is how a queue stops being worked
# through. Switch it on where a laboratory really does drop units from some lines and not others.
on_by_default = false

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
