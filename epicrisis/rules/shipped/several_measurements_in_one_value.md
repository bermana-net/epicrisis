+++
id = "several_measurements_in_one_value"
name = "Several measurements in one value"
summary = """The stored value names more than one measurement — a sphere, a cylinder, an axis — \
so one field holds what the form printed as several. No name is right for a field like that."""
kind = "several-measurements-in-one-value"
attaches = "value"
order = 14
settles = """One field holds several measurements, so the line was split in the wrong places. No correction to the name can put this right: open the document beside the original and have it read again, so that each measurement becomes a value of its own."""
does = "marks"
at = "validate"
on_by_default = true
+++

# What it looks at

The stored value of each line, and nothing else. It reports a value whose text names two or more
different measurements of a refraction, each with a number to label: `sph -9.75 cyl -9,0Д ax` is
a sphere and a cylinder and an axis in the field of one number.

A word with no number behind it labels nothing and is not counted, and a measurement named twice
in one value — the sphere of each eye on one line — counts once, because that is one measurement
printed twice and not two measurements. The reading is in `epicrisis/eyes.py`.

# What it will not do

It does not split the value, and it does not rename it. This is the half of the defect that
cannot be mended by writing a better name: the numbers of several measurements are in one field
and no name describes them all. The line has to be read again, which is a person's decision
because it costs a model.

# What was measured

On one archive nineteen values were in this state, every one of them from an eye examination,
and every one of them also named after an eye. They were found while looking at the fifty-two
values named by nothing but an eye: renaming would have made the other thirty-three right and
left these nineteen wrong in a way that now looked tidy.

# How it can be wrong

A laboratory may print a comment in a result field that mentions two measurements on purpose, and
a doctor's sentence quoting a correction — "sph -9.0 and cyl -9.0 recommended" — reads exactly
like a value that was split badly. Both need a number beside each word to be reported at all,
which is what keeps ordinary prose out of it, and neither is common.

It finds nothing where the measurements are written in words this program does not know: the list
of spellings is in `eyes.py` and covers the languages these archives are in.
