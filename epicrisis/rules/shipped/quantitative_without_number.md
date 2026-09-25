+++
id = "quantitative_without_number"
name = "A value counted as a number that holds none"
summary = """The transcription called this value quantitative and there is no number anywhere in \
what was printed. Either the kind is wrong, or the value was not copied."""
kind = "quantitative-without-number"
does = "marks"
at = "validate"
on_by_default = true
+++

# What it looks at

Values marked as numbers whose printed text holds no digits at all.

# What settles it

Read the line on the form and correct it, or mark it as not a value.

# How it can be wrong

A result printed as a word that the form itself treats as a measurement — "negative", "traces" —
is qualitative, and a transcription that called it quantitative is what this is for. It does not
fire on such values when they were read correctly.
