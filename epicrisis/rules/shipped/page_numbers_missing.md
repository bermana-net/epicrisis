+++
id = "page_numbers_missing"
name = "A page whose numbers did not come back"
summary = """The transcription of a page of text is the right length and does not hold the numbers \
the page prints. The words of a result can be written from anywhere; the numbers cannot."""
kind = "page-whose-numbers-are-missing"
does = "marks"
at = "extract"
on_by_default = true

[settings]
numbers_before_asking = 10
least_number_share = 0.9
+++

# What it looks at

The numbers printed on a page that went as text, looked for again in what came back. Digits are
compared in a form that ignores how they were typed — a figure typed in one alphabet and read in
another is the same figure — and nothing is compared but the digits themselves.

Every page printing at least `numbers_before_asking` numbers. Two numbers missing out of three is
a date and a page number; a laboratory form prints dozens, and nine in ten of them coming back is
the line between a reading and a retelling.

It does not ask what the two checks before it found, and carries none of their numbers. It used
to, and that is how a page could fall between them: those numbers are answered separately for each
archive, so the moment two copies of one threshold differed, a page was "not empty" to one check
and "already reported" to the next, and nothing reported it. A page may now be named by this check
and by one of those at once — which is what it is, a page that came back short *and* without its
numbers — and that costs nothing, because a document goes back to a stronger model if anything at
all was found.

# How it can be wrong

A page that prints a long identifier — a request number, a barcode read as digits, an insurance
number — gives those to the count as readily as it gives a result, and a model that leaves out the
barcode but copies every result fails this. The share is set at nine in ten rather than at all of
them for that reason, and an archive whose forms carry many such numbers may want it lower.

It cannot see a number read **wrongly**. A 7 that came back as 1 is a number found and a number
lost, and the share barely moves. That is not what this check is for: it asks whether the page was
read at all, and the checks that compare each stored value with the page it claims to come from are
what ask whether it was read right.
