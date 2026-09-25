+++
id = "one_scale_for_a_test"
name = "Bring one test to one scale"
summary = """Laboratories print creatinine in µmol/L and in mg/dL, haemoglobin in g/L and in \
g/dL, and a history then falls into several charts. This converts the units this archive holds \
a factor for and says what it converted and by how much."""
kind = "one-scale-for-a-test"
does = "places"
at = "charts"
on_by_default = false
was_called = "convert_units"
+++

# What it looks at

Only the analyte and unit pairs written into the table in units.py. An analyte or a unit that is
not there keeps its own chart, untouched, and nothing is ever guessed from the size of a number.

The printed value, its unit and its reference range stay exactly as they were beside the chart.
Nothing converted is stored: the archive and the index hold the printed value alone, and turning
this off undoes it entirely.

# How it can be wrong

The factors are molar masses, and a wrong one moves a value by a factor of ten or twenty. That
is why each is written once, with the analyte it belongs to, and each has a test of its own.

It is off in the repository because a converted number is not what the form printed, and this
archive's first duty is to show what the form printed.
