+++
id = "repeated_value"
name = "One line of a form transcribed twice"
summary = """The same value, on the same page, under the same name, in the same column, from the \
same fragment of the page — stored twice. The same value printed in two places is not this."""
kind = "repeated-value"
does = "marks"
at = "validate"
on_by_default = true
+++

# What it looks at

Values that agree on all of page, name, printed text, column and the fragment of the original
they were read from. A form that genuinely prints one result twice — a summary line repeating a
table — comes from two different fragments and is left alone.

# What settles it

Remove the second one on the card.

# How it can be wrong

Where a page holds two identical rows that really are two measurements, and both were read from
the same fragment, this counts one of them as a repeat.
