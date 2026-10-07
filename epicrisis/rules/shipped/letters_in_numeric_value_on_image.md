+++
id = "letters_in_numeric_value_on_image"
name = "Letters in a number read from a scan"
summary = """A value stored as a number whose printed form carries letters nothing explains, on a \
page that went as an image."""
kind = "letters-in-a-numeric-value-on-an-image"
does = "marks"
at = "extract"
on_by_default = true
+++

# What it looks at

Values that have a number stored against them and whose printed form holds letters — and only on
pages that went as images. What "nothing explains" means is in `printed_values.unexplained_letters`:
a unit, a comparator, a word a form really prints beside a figure are all explained; a stray letter
in the middle of digits is not.

Why only scans: on a text page the letters beside a number are printed ones, read off the page as
they stand. On a scan they are as likely to be the reading's own — `l` for `1`, `О` for `0`, a
letter from a neighbouring column pulled into a figure.

# How it can be wrong

A form that prints a number with a letter in it on purpose — a sample code, a value with a footnote
mark, "1a" as a row label read as a value — fires here and is read correctly.

It cannot see the misreading that matters most: a digit read as another digit. `7` for `1` leaves
no letters behind and passes this and every other check of this step. What catches that is a person
looking at the scan beside the card, which is why the page keeps the original within one press.
