+++
id = "comparator_not_printed"
name = "A comparator stored and not printed"
summary = """A sign stored beside a value — < or > — that the form does not print beside it: a \
comparison the reading made rather than read."""
kind = "comparator-stored-and-not-printed"
does = "marks"
at = "extract"
on_by_default = true
+++

# What it looks at

Values carrying a stored comparator whose printed form holds none. A comparator here is a thing the
form printed — `<`, `>`, "less than", "не более" — and never a comparison with the range standing
beside it. A model that stores `<` because the number is under the norm has answered a question
nobody asked, and this is how that shows.

# How it can be wrong

A form that prints the sign in a column of its own, away from the value, leaves a value with a
comparator that the value's own printed form does not carry — and the reading was right.

**What is said about this to a person comes from elsewhere.** A rule of the validate step,
`comparator_missing`, checks both directions of the same printed fact and owns the finding; this
one only decides whether the document is worth reading again. That is why turning this off takes
nothing away from the list of work: it changes what gets paid for, not what gets seen.
