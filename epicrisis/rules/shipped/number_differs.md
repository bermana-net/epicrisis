+++
id = "number_differs"
name = "The number stored is not the number printed"
summary = """The value as printed and the number kept beside it for charts and comparisons do \
not agree. A digit lost, a decimal comma read as a thousands separator, a number invented \
where the form printed words."""
kind = "number-differs"
attaches = "value"   # where a finding of it hangs: on a value, or on the document
order = 1             # where it stands in the queue a person works through
settles = """The number stored is not the one printed. Open the line and set it to what the form says."""
does = "marks"
at = "validate"
on_by_default = true
+++

# What it looks at

Every value that carries a number, against the text the form printed. The text is what the
archive keeps; the number exists only so that a chart can be drawn and a range compared, and
where the two disagree it is the number that is wrong.


# How it can be wrong

Rarely. It compares the two things the transcription itself produced, so a finding here is a
real disagreement and not a judgement about the form.
