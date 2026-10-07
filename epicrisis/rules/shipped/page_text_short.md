+++
id = "page_text_short"
name = "A page that came back much shorter than the page"
summary = """A page that went to the model as text and came back as much less text than was sent: \
the reading stopped somewhere in the middle of it."""
kind = "page-much-shorter-than-the-page"
does = "marks"
at = "extract"
on_by_default = true

[settings]
least_share = 0.5
words_before_asking = 40
+++

# What it looks at

Only pages that went to the model **as text**, because only those have something to be compared
with: the page's own text layer is what was sent, and the transcription is what came back. Pages
that went as images are not asked — there the model's reading is the only text there is, and
comparing it with itself says nothing.

Only pages of more than `words_before_asking` words. Every one of them, including the pages that
came back with nothing: a page with nothing at all is also reported by the check before this one,
and being named by both is what it is — the page came back empty *and* much shorter than it was
sent. It costs nothing, because a document goes back to a stronger model if anything at all was
found, not once per finding.

This check used to skip those pages, and worked out which they were from its own copy of the other
check's threshold. The two are answered separately for each archive, so one raised and the other
left made a page of thirty characters "not empty" to that check and "already reported" to this
one: reported by nothing, with no number anywhere saying so. A rung that re-derives the rung
before it is a rung with a hole in it.

# How it can be wrong

A page whose text layer holds the same words twice — a watermark repeated behind every line, a
header that the extraction of the text layer picked up once per column — is a page where half the
words coming back is right. The transcription is complete and this says it is not.

The other way round: a model that copies a page's furniture faithfully, the page numbers and the
footers and the address block, can pass this while leaving out the table in the middle. Half the
words of a form are not the half that matters, and that is what the check after this one is for.
