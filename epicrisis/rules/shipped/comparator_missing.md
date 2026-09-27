+++
id = "comparator_missing"
name = "A < or > printed and not stored, or stored and not printed"
summary = """A sign that changes what a value means. «<0,5» stored as 0,5 reads as a \
measurement; 0,5 stored as «<0,5» invents a limit the laboratory never printed."""
kind = "comparator-missing"
attaches = "value"   # where a finding of it hangs: on a value, or on the document
order = 3             # where it stands in the queue a person works through
settles = """A < or > is printed and not stored, or stored and not printed. Correct the line on the card."""
does = "marks"
at = "validate"
on_by_default = true
+++

# What it looks at

The sign in front of the printed value against the comparator stored with it, both ways round. A
comparator written in words — «up to 5», «до 5» — counts as printed.


# How it can be wrong

A form that prints its limit in an unusual wording, in a language whose words for "less than"
this does not hold, will look like a sign that was invented.
