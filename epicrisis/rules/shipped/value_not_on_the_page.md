+++
id = "value_not_on_the_page"
name = "A value that is nowhere in the text of its page"
summary = """On a page that went to the model as text, a stored value whose digits are not in that \
page at all. The page's own text is the evidence, not a reading of it."""
kind = "value-not-on-its-own-page"
does = "marks"
at = "extract"
on_by_default = true

[settings]
words_before_asking = 40
skip_qualitative = true
+++

# What it looks at

The digits of each stored value, looked for in the text of the page it says it came from — and
only where that page went to the model **as text**. There the text is the page itself: a number
that is not in it was not printed there, whether the layout was misread or the page said something
other than what it holds.

Digits are compared the way the rest of the program compares them: spacing gone, and a figure typed
in one alphabet the same as the same figure typed in another. A page of fewer words than the
threshold is passed over, and so are values the form printed as words rather than numbers — there
is nothing in them to compare.

**This one is different from every other check of this step**: its finding is shown to a person,
under its own name and with its own words about what to do. The rest are the step reporting on its
own reading, and what reaches a person about them is a summary.

# How it can be wrong

A form that prints a number in a picture — a chart, a stamped figure, a value in a scanned table
glued into a text document — has a text layer that does not hold it, and the reading is right. The
same for a value the model assembled correctly out of two columns the text layer gives in the
wrong order.

The other way: a number that *is* printed somewhere on the page, but beside a different test, is
found here and nothing is reported. This asks whether the digits are on the page, not whether they
are on the right line of it.
