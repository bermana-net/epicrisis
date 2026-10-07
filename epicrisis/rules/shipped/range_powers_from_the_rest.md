+++
id = "range_powers_from_the_rest"
name = "A printed range that cannot be this value's"
summary = """The reference range printed beside this value stands powers of ten from the ranges \
printed beside every other reading of the same test, in the same printed unit and the same \
specimen: a range of some other row of the form."""
kind = "printed-range-powers-from-the-rest"
attaches = "value"
order = 16
settles = """Look at the page and read the range off the row the value stands in. Where the form prints another range, correct the printed range; where the form really prints this one, leave it and call this noise — the laboratory put somebody else's line in that column, and nothing in the archive is wrong."""
does = "marks"
at = "validate"
on_by_default = false
+++

# What it looks at

Reference ranges, and only reference ranges. For one test, one printed unit and one specimen at a
time, it takes the middle of every range printed beside a reading of that test — geometrically, so
that 35–50 and 0,2–1,0 are a hundred apart and not fifty — and reports a range standing powers of
ten from the middle of the rest.

The specimen is the settled one and not only the word the form printed: the person's own
correction first, then the form, then a heading a model read — the order `index/build.py` decides
once for the whole program. Keyed by the printed word alone, a urine protein whose form prints no
heading fell into the serum protein's group and was reported as carrying another row's range, and
a specimen somebody had corrected by hand was not seen at all.

A range counts here only where it is closed at both ends and where the form printed a unit, either
in a column of its own or inside the range itself: «0,2-1,0 %» names its unit as plainly as a
column would, and that spelling is read in `units.py`, which already owns what scale a number is
on.

Why it exists: a haematocrit stored as 0,48 was drawn as 48 per cent, rightly, with «0,2-1,0 %»
printed beside it as its range, and the axis of its chart ran from a fifth of a per cent to fifty.
0,2–1,0 % is the line of basophils on the same form. The value was right; the band under it was
another row's.


# What it will not do

It does not read the value. Not once, not as a tie-breaker, not to confirm anything.

That is the whole of how it tells "this range belongs to another row" from "this person's reading
is far from normal", which is the case this program exists to show and must never be dressed up as
an error. A printed range is a fact about the test and the laboratory; it is not a fact about the
person. One person's haematocrit may read 21 one year and 48 the next, and the range printed beside
both is 35–50 either way. So the ranges of a test are weighed against each other, the reading is
left out of it, and a value far from its band cannot make this fire even in principle.

It also moves nothing. No value, no range, no unit, no band, no scale, no verdict about anybody's
health. The band under a chart is still drawn from the printed text, in one place, as before. This
only sends the row to the page of things to check.


# What it does not settle

Which row the range came from. It can say a range is not this test's; it cannot say whose it is,
and it does not guess. Nor does it say whether the laboratory printed the wrong line or the model
read the wrong line — that is what the scan is for, and both end in the same place: a person
looking at the page.

It says nothing where no unit is printed anywhere on the row. Without a printed unit the form has
not said what scale its range is at, and then a range at another size is indistinguishable from a
form printing the whole test at another scale — a haematocrit written as a fraction, 0,35–0,50
beside 0,44, which is an honest form. Those belong to the two-scales reading in `units.py`, which
moves the points and says by how much; this check steps aside from it rather than shouting over it.

It says nothing about a test whose printed ranges are not one range to begin with. Where fewer than
`ranges_agree` of them stand nearer their own middle than `powers_apart` calls far, there is no
"rest of the test" to be powers of ten from, and which of two scales is the odd one is a question
with no answer in the archive. What counts as agreeing with the rest is the same distance that
counts as standing away from it, on purpose: a second number for it would be a threshold nobody
could see or move.


# How it can be wrong

A laboratory that prints a test as a fraction and labels the column per cent all the same is
reported by this, and the archive is not wrong — the form is. It is worth seeing once: the band
under that chart is a hundred times too small whatever the reason, so the row did need looking at.

A form that got two rows of one table wrong is quieter than a form that got one wrong. The faulty
ranges count towards the share that has to agree, so a test with five printed ranges of which two
are foreign falls under the threshold and nothing is said. The check is built to be believed rather
than to catch everything.

A document exported or quoted three times carries its range three times, so a group of copies
reports the finding on each of them, like every check at this step. Which document of a group
answers is the business of `possible_copy`.

Two laboratories do print different ranges for one test — another method, another age band — and
those differ by a factor of a few. The threshold is a power and a half, about thirty-two times:
the geometric middle between the ten-fold that honest ranges can reach and the hundred-fold of a
misplaced scale. Lower than two powers on purpose, because the shape this was written for —
0,2–1,0 against 35–50 — is ninety-three times, and a threshold of a hundred would have missed the
row that started it.


# Why it ships off

It is silent even on the row it was written for, and the reason is worth stating rather than
tuning away. The checks run over an archive's own files, where there is no index and so no
indicator, so a test is gathered by its folded printed name. Two laboratories that write
haematocrit under two printed names split one test into families, and a family smaller than
`ranges_agree` has no "rest of the test" to be weighed against. Lowering that threshold would
make the check louder and less certain at once, which is the wrong trade for a check whose whole
value is being believed.

So it ships **off**. The code and its tests are sound; the reach is not there, and a rule that is
on and finds nothing is a promise of a check that is not being made. What it needs is to gather a
test by the indicator — the group of spellings a person has already approved — which means running
where the index is. That is written down as its own card.

