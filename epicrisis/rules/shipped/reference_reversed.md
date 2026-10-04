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

Any printed range this program can read at all, where the first of its two ends stands above the
second. The range is read by `reference.py`, the one reader of a printed range here, so every
spelling that reader knows is covered: a dash, two dots, and the word a Spanish, Greek, Russian,
Ukrainian or English form puts between the ends; a label in front of the range; a unit after it;
thousands grouped with a space. It had a pattern of its own before, which knew the dash and
nothing else, and on the two languages that print a range with a word it never fired.

Why this of all the checks must see every spelling: a range that reads backwards is read as no
range at all, so the band under the chart goes missing and the third answer mode has nothing to
compare the number with. This check is the only thing that tells a person why.


# How it can be wrong

Forms do print ranges backwards, and more often than one would think. This is why it asks rather
than corrects.
