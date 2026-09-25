+++
id = "unit_from_range"
name = "Read the unit from the printed range"
summary = """Where a form has no unit column, the range beside the value often names the unit \
anyway: «53-115 µmol/L», «19,0-37,0%». Such a value is drawn on that scale and marked as \
having taken its unit from the range."""
kind = "unit-from-the-printed-range"
does = "places"
at = "charts"
on_by_default = true
was_called = "unit_from_range"
+++

# What it looks at

The text of the reference range printed beside a value whose own unit column is empty. The
longest spelling that occurs wins, not the first one in the table: «г/л» is inside «мкг/дл», and
read in table order a range printed in micrograms was once read as grams and put a value on an
axis a thousand times off.

# How it can be wrong

A range holding two ranges at once — the relative and the absolute count on one line — says two
things, and which of them the value belongs to is written nowhere. Such a range is read as
saying nothing at all.

Off, only the unit column counts, and every value whose form printed none stays together under
"no unit printed".
