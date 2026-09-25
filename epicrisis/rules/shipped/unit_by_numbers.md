+++
id = "unit_by_numbers"
name = "Values with no unit anywhere: place them by their numbers"
summary = """Old forms print a leukocyte formula with no unit column and no range at all. The \
numbers are per-cents and nothing on the page says so. Such values join the scale their own \
middle agrees with, and every one of them is marked."""
kind = "unit-by-the-numbers"
does = "places"
at = "charts"
on_by_default = false
was_called = "unit_by_numbers"

[settings]
agreement = 2.0      # how close two middles must be to count as the same scale
least_to_join = 2    # values a scale must already have before anything may join it
+++

# What it looks at

The middle of the values that carry no unit at all, against the middle of every scale this test
is drawn on. They join a scale only where exactly one fits within the agreement above and no
other does; two candidates, or none, and they stay where they are.

# How it can be wrong

**This is the only reading in this program taken from numbers rather than from a page**, which
is why it is off unless asked for and why every value it moves is marked, on the chart and in
the table.

Two scales that happen to lie within a factor of two of each other cannot be told apart this
way, and a test whose values genuinely have no unit — a ratio, an index — will be pulled onto
the scale of whatever it resembles. Nothing is converted and nothing is stored.
