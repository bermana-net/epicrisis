+++
id = "unit_by_numbers"
name = "Values with no unit anywhere: place them by their numbers"
summary = """Old forms print a leukocyte formula with no unit column and no range at all. The \
numbers are per-cents and nothing on the page says so. Such values join the scale the range \
printed beside them agrees with, or, where no range was printed at all, the scale their own \
spread matches at both ends. Every one of them is marked."""
kind = "unit-by-the-numbers"
does = "places"
at = "charts"
on_by_default = false
was_called = "unit_by_numbers"

[settings]
agreement = 2.0      # how close two numbers must be to count as the same scale
least_to_join = 2    # values a scale must already have before anything may join it
+++

# What it looks at

Three readings, in this order, because a page saying something is always worth more here than a
guess from numbers.

First the reference range the forms printed beside the values with no unit, against the numbers
of every scale this test is drawn on: a scale fits when all of its numbers could have stood
beside that range, each printed end loosened by the agreement above. A prostate-specific antigen
printed "up to 4" beside values of 1.96 to 4.35 is one scale. Where a form printed one end and
left the other open — "up to 4", "more than 0,6" — that one end bounds nothing on its open side,
so it is also asked to be the end of those numbers: the same size, within the agreement, as the
end of them facing it. A ceiling of four is the ceiling of readings of 2.08 and 4.61; a floor of
0,6 is nobody's floor for readings of 34 to 88.6, which are micromoles per litre against a
milligramme-per-decilitre floor. Without that question a floor alone read as "the numbers are
positive".

Where no range was printed beside these values this reading says nothing, and then the numbers
themselves are asked: both ends of the two spreads, the lowest against the lowest, the highest
against the highest, each within the agreement. A sedimentation rate of 4 to 35 joins one of 2 to
35 printed in millimetres an hour. A creatinine of 0.5 to 55.3 does not join one of 30 to 92.8
micromoles per litre, because the low ends are a factor of sixty apart and the two are really
milligrammes per decilitre and micromoles mixed together.

A range printed beside some other form of the same test does not silence this: silence beside
these values is not the page speaking about them. Written the other way round first, it took the
scale away from many more values than it placed.

Where the ends refuse, the last reading asks the one question neither a middle nor a spread can
answer: the values that stand next to each other in time, pair by pair. A spread is as wide as the
years and the readings that went into it, so three readings of one decade and eleven of four
decades have spreads of different width whatever scale either of them is on — and a marker that
rises over a lifetime has its small readings in the set that printed no unit and its large ones in
the set that printed one, which is how one history came to be drawn as two charts with the same
unit written on both. Two readings a few weeks apart are the same quantity, however far it has
moved since, so the ratio between them is about the scale and nothing else. Every value with no
unit is asked against its nearest neighbour in time on that scale, and every pair has to agree:
one pair of the wrong size is a column holding two scales.

The scale a value joins is counted the way the chart will be drawn: one candidate per measure and
not one per spelling. A litre holds a thousand millilitres, so "10⁹/L" and "10³/µL" are one scale
and one chart — counted as two, "exactly one fits" was never true, and a test whose printed range
fitted both spellings kept a chart of its own with no unit on it beside the chart it belongs on.

Either way they join a scale only where exactly one fits and no other does; two candidates, or
none, and they stay where they are. The middle of a group is not used anywhere: measured before
this was written, it put a sedimentation rate on no scale at all, and comparing how far two
spreads overlap joined milligrammes per decilitre to micromoles per litre.

# How it can be wrong

**This is the only reading in this program taken from numbers rather than from a page**, which
is why it is off unless asked for and why every value it moves is marked, on the chart and in
the table.

All three readings are noisy where the named scale holds only two or three values: a spread of two
readings is not the spread of that test, its ends move a long way when one more form is scanned,
and a nearest neighbour drawn from two readings is a neighbour twenty years away. Where this was
measured that happens not to matter, and a handful of tests is no reason to think it never will
matter.

**The pairs in time answer nothing where the two sets never meet.** Where every form that printed
a unit is of the last two years and every form that printed none is older, each old value's
nearest neighbour is the earliest of the new ones, and a marker that has risen since is refused —
correctly, because nothing in those numbers can tell a quantity that grew from a scale that
changed. On the archive this was measured against that is the shape of the test the owner
complained about, and what saves it there is the range its forms print; with no range printed
there is no honest answer, the values stay on no scale, and the page says so rather than guessing.

The printed range is read instead of the numbers and not before them, so a range that fits no
scale at all leaves the values where they are rather than falling through to their spreads. And
a printed end of the right size says nothing about a column that already holds two scales: where
the values with no unit are themselves milligrammes per decilitre and micromoles per litre mixed
together, a ceiling printed in one of the two will take the whole column onto that scale.

Two scales that happen to lie within a factor of two of each other at both ends cannot be told
apart this way, and a test whose values genuinely have no unit — a ratio, an index — will be
pulled onto the scale of whatever it resembles. Nothing is converted and nothing is stored.
