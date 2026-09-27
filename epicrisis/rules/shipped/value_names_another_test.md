+++
id = "value_names_another_test"
name = "The value's own text names a different test"
summary = """A line whose value, rather than its name, carries the name of another test. A \
table of targets prints one test in the row and names another inside the cell, and nothing that \
groups values into tests ever reads inside the cell."""
kind = "value-names-another-test"
attaches = "document"
settles = """Open the page. If the row and the cell really name two different tests, the value belongs to the one named in the cell and the line needs correcting by hand."""
does = "marks"
at = "suspects"
on_by_default = false

[settings]
weight = 2
shortest_spelling = 8  # letters, below which a spelling is an ordinary word and matches everything
+++

# What it looks at

The text of each value against every approved spelling of every other test, matched on whole
words. A match means the cell names a test that is not the test the row is filed under.

# Why it is off unless you ask

**Because the length limit is doing all the work.** Some tests are spelled with ordinary words —
a spelling that means "quantity" or "colour" matches half an archive — and below eight letters
this rule finds those and little else. Eight is what a real archive measured out; it may be
wrong for one written in another language.

Turn it on, look at what it finds, and turn it off again if the answer is noise. That is what
the switch is for.

# How it can be wrong

A value that legitimately mentions another test — a comment, a method, a comparison the
laboratory printed on purpose — reads exactly like a stray. And it finds nothing at all where
the spelling in the cell is not one the archive has approved: a test written one way in the row
and another way in the cell is invisible to it until both spellings are known.
