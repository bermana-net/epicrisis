+++
id = "no_column_headings_in_multi_value_rows"
name = "A row of several values with no column named"
summary = """One row of the form printed more than one value and the reading stored no column \
heading anywhere: nothing says which of them is the result."""
kind = "rows-of-several-values-without-a-heading"
does = "marks"
at = "extract"
on_by_default = true
+++

# What it looks at

Rows, told apart by the piece of the original line kept beside every value. Where one row holds the
same printed name more than once, the form was printing several things side by side — a result, a
previous result, a norm — and the reading stored no `column_as_printed` for any value of the
document. Then nothing on the card says which number is the one that was measured.

Many forms print one value per row and no headings at all, and nothing is asked of them.

# How it can be wrong

**It was wrong, and the shape of it is why this file exists.** It counted a name appearing twice
anywhere on the page, which is not a row of several values: it is one measurement printed in two
places, as every long report does — once in a table and once in the text beneath it. Documents
where no name repeated inside any row at all were sent to the costliest model to answer a complaint
about a table that was not there. The round that measured that has the numbers.

What is left of that: a form that prints its table rows without any repeating name — a single
column of results beside a single column of norms — carries several values per row and is not seen
here at all. This finds the shape it was written for and not the thing it is named after.

**What a person sees about such a form comes from elsewhere.** A rule of the validate step owns
that finding; this one only decides whether the document is worth reading again.
