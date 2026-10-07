+++
id = "named_after_the_eye"
name = "A value named after the eye, not after what was measured"
summary = """The name of this value is an eye and nothing else — OD, OS, ОС — while its own \
printed line names the measurement beside the number. Which eye is not what was measured."""
kind = "named-after-the-eye"
attaches = "value"
order = 13
settles = """The name says which eye and not what was measured. The finding names the measurements the printed line itself names; put the right one in the name, with the eye after it, the way "Vis OD" is written."""
does = "marks"
at = "validate"
on_by_default = true
+++

# What it looks at

The name of each value, and the printed line kept beside it. Two things have to be true at once.

The name, with its spacing and full stops taken off, is one of the six ways a form says which
eye — OD, OS, OU and ОД, ОС, ОУ, in either alphabet or mixed between them. A name that holds
anything more than that is not this: "Vis OD" is named properly, because Vis is the measurement
and the eye only says which of the two it was measured in.

And the line the value was read from names a measurement of its own beside a number: sph, cyl,
ax, сф, ціл, ах, ось, vis. An eye examination prints the whole refraction on one line, with the
names of the measurements inside the line and no column anywhere, which is how the eye came to
be stored as the name in the first place. The reading of those words is in `epicrisis/eyes.py`.

# What it will not do

It does not rename anything, and nothing in this program ever will. A rule may say "look at
this" and no more; the name stays exactly as it was read until a person changes it, with the
same correction they would make on any other misread line.

It also says nothing about a value whose stored *value* holds several measurements at once. No
name is right for a field holding a sphere and a cylinder together, so asking somebody to rename
one would be asking for the wrong work. Those are reported by "Several measurements in one
value", which says what they really need.

# Why it exists

A chart is drawn under a name, so a value named after the eye draws one chart of everything that
eye was ever measured for: the dioptres of a sphere and a decimal of visual acuity on one axis,
with a line between them that means nothing. The name is the only thing wrong with it — the
number, the unit and the printed line are as the form printed them — which makes it the cheapest
kind of defect to mend and the easiest to walk past.

Properly named lines sit beside these on the same form: "Vis OD" is written exactly as it should
be, and an archive of eye examinations holds both shapes. That is why the name has to be an eye
and nothing else before anything is said.

# How it can be wrong

"ОС" is an abbreviation on forms that have nothing to do with eyes, which is why the line has to
name a measurement before anything is said. Two of the words it reads are ordinary words of the
language as well — «ось» is "here" in Ukrainian, «ах» is an interjection — so those two are read
only in the company of a word that can be nothing but a measurement.

Where a line names several measurements, this rule says which ones the line names and does not
guess which of them belongs to this particular number. On a line reading
`Vis OD = 0.99 із sph -9.75 cyl -9,0Д ax 99=0,9` there are four to choose from, and choosing is a
person's to do with the page in front of them.
