+++
id = "reference_reversed"
name = "A reference range that reads backwards"
summary = """The lower bound of a printed range stands above its upper one. Two numbers read in \
the wrong order, or a range the laboratory itself printed that way."""
kind = "reference-reversed"
attaches = "value"   # where a finding of it hangs: on a value, or on the document
order = 5             # where it stands in the queue a person works through
settles = """The range reads backwards. Often the form prints it that way; look, and correct it only if the form does not."""
does = "marks"
at = "validate"
on_by_default = true
+++

# What it looks at

Ranges of the plain form "low - high", where the first number is larger than the second.


# How it can be wrong

Forms do print ranges backwards, and more often than one would think. This is why it asks rather
than corrects.
