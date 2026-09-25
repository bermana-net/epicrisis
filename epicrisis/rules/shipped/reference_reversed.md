+++
id = "reference_reversed"
name = "A reference range that reads backwards"
summary = """The lower bound of a printed range stands above its upper one. Two numbers read in \
the wrong order, or a range the laboratory itself printed that way."""
kind = "reference-reversed"
does = "marks"
at = "validate"
on_by_default = true
+++

# What it looks at

Ranges of the plain form "low - high", where the first number is larger than the second.

# What settles it

Look at the page, and correct it **only if the form does not print it that way**. Where the
laboratory printed it backwards, the archive keeps it backwards: what is printed is what is
stored.

# How it can be wrong

Forms do print ranges backwards, and more often than one would think. This is why it asks rather
than corrects.
