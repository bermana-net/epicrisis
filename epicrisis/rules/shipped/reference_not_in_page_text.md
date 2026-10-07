+++
id = "reference_not_in_page_text"
name = "A printed range not on the page it came from"
summary = """On a page that went as text: the numbers of a stored reference range are not all in \
the page's own text."""
kind = "reference-not-in-the-page-text"
does = "marks"
at = "extract"
on_by_default = true
+++

# What it looks at

Each number of a stored range, looked for in the page's own text — **number by number, never the
range as one piece**. A form prints its norms over several lines and columns: men and women, ages,
units in a heading above them all. The range as the archive stores it (`4,0-9,0`) appears nowhere
on such a page as a single string, and asking for it that way would report every well-read form in
the archive.

# How it can be wrong

A range printed as words — "within normal limits", "отрицательно" — carries no numbers, and nothing
is asked of it. A range whose numbers are printed as a picture of a table fires and is right to.

And a number of the range that also appears elsewhere on the page — a date, a patient's age, the
other half of a different range — satisfies this without being the range. It asks whether the
numbers are on the page, not whether they stand together.
