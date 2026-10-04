+++
id = "unit_alone_in_a_series"
name = "A unit used once, where the whole test prints another"
summary = """One line of a test carrying a unit that no other form of that test uses. Either \
the unit was misread, or the line belongs to a different measurement that shares a printed \
name — an absolute count standing among percentages, a sediment count among blood counts."""
kind = "unit-alone-in-a-series"
attaches = "document"
settles = """Open the document beside the original and read the unit; every one of these is listed on Looks misread, behind the line on To check. If the form prints what the card says, this is a laboratory that writes it differently and nothing is wrong; if the line belongs to another measurement, it does not belong in this history."""
does = "marks"
at = "suspects"
on_by_default = true

[settings]
weight = 2
alone_at_most = 1     # times the unit may appear before it stops being alone
others_at_least = 10  # units somebody actually printed, before "the others" means anything
+++

# What it looks at

Within one test and one specimen: the unit of each line against every other unit printed for
that test. Compared by the unit's key and not its spelling, so «ммоль/л» and `mmol/L` count as
one — otherwise every Ukrainian form in a Greek archive would be marked.

Only units somebody actually printed count as "the others". A test whose other forms printed no
unit at all says nothing about this line: that is a form without a unit column, and there is a
rule of its own for it.

# Why it does not go stale

It knows nothing about the names of tests, nothing about what any unit means, and nothing about
what a reasonable value would be. It asks one question — is this line's unit the one nobody else
on this test uses — and that question will still make sense on a form nobody has seen yet.

# How it can be wrong

**A laboratory that genuinely prints a unit nobody else does** will be marked every time, and
there is nothing wrong with the line. A test measured two ways under one printed name — a count
and a percentage of the same cells — will mark whichever of the two is rarer, and both are real.

In practice it also finds units this program has not yet learned to join: two spellings of one
unit that its table does not know are the same. Those are worth knowing about too, and they are
dismissed in a second.
