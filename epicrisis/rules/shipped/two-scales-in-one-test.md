+++
id = "two-scales-in-one-test"
name = "One test printed at two scales: draw it as one history"
summary = """One laboratory prints a urine specific gravity of 1,015 and the next prints 1015; \
these are the same measurement, and the reference range printed beside each value says which \
scale that form used. Where the ranges of one test are the same range a power of ten apart, \
every point is drawn on the scale most of the forms used, and the moved ones say so."""
kind = "value-against-its-printed-range"
does = "places"
at = "charts"          # drawn when a page is drawn: nothing stored, nothing read again
on_by_default = true

[settings]
# How far from a whole power of ten two ranges may sit and still be the same range. 0.15 is
# about forty per cent either way: enough for two laboratories printing 1,001-1,040 and
# 1010-1030, far too little for two ranges that are simply different.
same_band = 0.15
# How many printed ranges it takes before this test can be said to have two scales at all.
bands_to_see_a_scale = 2
+++

# What it looks at

One laboratory prints a urine specific gravity of 1,015 and the next prints 1015. One prints a
haematocrit of 0,44 and the next 44%. These are the same measurement, and drawn together they
are two clouds of points a thousand apart with a line between them that means nothing.

The form itself says which scale it used: the reference range printed beside the value is
written at the scale of that value. Where the ranges of one test are the same range ten or a
hundred or a thousand times over, the scale most of the forms used becomes the scale of the
chart, and the rest are drawn on it.

A form that printed its range and had the number written in by hand — an old form where the
range is typeset and the value is in ink — has named two scales, not one. The range decides the
value's scale only while the number is inside it; where it is not, the two move apart, each by
the distance it is actually at.

# What it does not do

Nothing is stored, nothing is converted and nothing is corrected. The printed value, its unit
and its range stand untouched beside the chart, in the rows and in every answer given over the
network. Only the point on the chart moves, and it says what it was moved by.

# How it can be wrong

Nothing moves unless the printed ranges themselves say the test has two scales. That is the
whole safety of it: **one value far outside its own range is an abnormal result, and an abnormal
result must never be quietly divided by ten.**

The first and most obvious version of this rule — "the number is far outside its own range, and
one power of ten brings it inside" — was measured against a real archive before it was written,
and it would have hidden several genuine excursions: results sitting a little above their range,
which one power of ten brings neatly inside it. It was thrown away for this one.

Where a test's ranges are simply different between laboratories, and not one range at another
scale, nothing moves at all. A value whose own form printed no range is placed on the scale its
own size is nearest to, which is unambiguous when the scales are a hundred apart and is the one
reading here not taken from a form.

# How much it touches

Little, and that is the point: a test has to be printed at two scales before anything moves at
all, so on most archives it will reach a handful of tests and no more. Measure it on yours
before turning it on — a rule of this kind that fires often is a rule that is wrong.
