+++
id = "number_far_from_the_others"
name = "A number many times away from every other reading of the same test"
summary = """A value ten times larger or smaller than the middle of the same test, in the same \
unit and the same specimen. A misplaced decimal point reads exactly like this, and so does a \
digit read twice."""
kind = "number-far-from-the-others"
does = "marks"
at = "suspects"
on_by_default = true

[settings]
weight = 3            # the loudest of the four: a decimal point in the wrong place is a real error
least_history = 4     # readings before a middle means anything
times_away = 10       # how far from the middle before it looks like a misplaced decimal point
+++

# What it looks at

The middle of every reading of one test — one indicator, one unit, one specimen — and every
value that sits at least ten times away from it in either direction.

The specimen belongs in that key for the same reason it belongs on a chart: protein in urine and
protein in serum are printed under one name in one unit and differ by a factor of ten, so a
middle taken over both would make each of them look far from the other.

# How it can be wrong

**A real result can be ten times the usual one.** A ferritin after treatment, a CRP during an
infection, a D-dimer after surgery — these are the readings that matter most, and this rule
points at them exactly as loudly as it points at a misread digit.

That is the whole reason it says *look at this* and nothing else. It never decides, never
corrects, and never keeps a value out of a chart. It is a queue of pages worth opening, and a
page opened for nothing costs a few seconds.
