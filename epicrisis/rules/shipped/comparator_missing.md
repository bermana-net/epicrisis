+++
id = "comparator_missing"
name = "A < or > printed and not stored, or stored and not printed"
summary = """A sign that changes what a value means. «<0,5» stored as 0,5 reads as a \
measurement; 0,5 stored as «<0,5» invents a limit the laboratory never printed."""
kind = "comparator-missing"
does = "marks"
at = "validate"
on_by_default = true
+++

# What it looks at

The sign in front of the printed value against the comparator stored with it, both ways round. A
comparator written in words — «up to 5», «до 5» — counts as printed.

# What settles it

Correct the line on the card, either the value or the sign, so that it says what the form says.

# How it can be wrong

A form that prints its limit in an unusual wording, in a language whose words for "less than"
this does not hold, will look like a sign that was invented.
