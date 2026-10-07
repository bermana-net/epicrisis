+++
id = "page_text_missing"
name = "A page that came back with no text at all"
summary = """A page of the document whose transcription is empty or nearly so. The reading stopped \
before the end, or never reached this page."""
kind = "page-with-no-text"
does = "marks"
at = "extract"
on_by_default = true

[settings]
least_characters = 20
+++

# What it looks at

The transcription of each page of the document, against the pages the document is made of. A page
with fewer characters than the threshold is counted as not transcribed at all.

It asks nothing about what the page says. A page of a form with one line printed on it is a page,
and the threshold is set low for that reason: twenty characters is a date and a signature.

# How it can be wrong

A genuinely blank page inside a document — the back of a sheet, a separator, a page of nothing but
a stamp — is transcribed as nothing because there is nothing on it, and this fires. Those
documents go back to a stronger model and come back the same way, and the cost of that is a second
reading of a page that has nothing on it.

Where an archive is full of scanned sheets with blank backs, raising the threshold does not help —
the text is empty either way — and the thing to do is turn this off for that archive and rely on
the two checks that follow it, which ask about pages that did come back with something.
