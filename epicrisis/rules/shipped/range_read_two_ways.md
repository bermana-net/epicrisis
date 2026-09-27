+++
id = "range_read_two_ways"
name = "The printed range was read two ways"
summary = """The model that transcribed the page read the reference range as two numbers, and this \
program's own reader of the same printed text does not agree with it."""
kind = "range-read-two-ways"
attaches = "value"
order = 2
settles = """Look at the page: which of the two numbers is what the form prints. Correct the printed range if it was transcribed wrongly; where the transcription is right and the reading of it is wrong, this is a defect of the program and worth reporting."""
does = "marks"
at = "validate"
on_by_default = true
+++

# What it looks at

Values whose form printed a reference range beside them, where the transcription carries both the
range as printed and the range as two numbers, and the two readings of that one text disagree — in
either direction. A bound one reading has and the other has not counts: a band that appears on one
reading and not the other is the same disagreement as two different numbers.


# Why it exists

Everything after the reading is done without a model: repeatable, free, offline, and measurable
against the same files a year later. The printed range is therefore read by a parser, and a parser
has to know a decimal comma from a separator of thousands, a unit carrying a power in front of its
range, a word of direction in five languages, a label printed before the range, and a ratio that
looks like a range and is not one. That reader was broken and repaired four times in one day over
shapes this archive does not hold yet, and every measurement of it reported no movement, correctly,
because nothing in the archive could show the difference.

One reader is never wrong out loud. The model that transcribed the page had the page in front of it
and is asked for the same range as two numbers — the same thing it is already asked for the value
itself, and no more interpretation than that. Where the two disagree, a person is shown the scan and
decides. Nothing here chooses between them and no band moves: the band under a chart is drawn from
the printed text by reference.parse, in one place, as before.


# How it can be wrong

A model reading a table of ranges by age or sex may pick the line that seems to fit the person
rather than answering "not one range", and then it disagrees with a reader that correctly refused.
That is a disagreement worth seeing once and dismissing, not a wrong number in the archive.

It says nothing at all about a document transcribed before those two fields were asked for: the
absence of an answer is not a disagreement with one.
