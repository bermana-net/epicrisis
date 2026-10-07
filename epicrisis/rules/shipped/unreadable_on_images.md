+++
id = "unreadable_on_images"
name = "Something unreadable on a page that went as a picture"
summary = """The reading says part of this document could not be read, and part of it went to the \
model as an image rather than as text."""
kind = "unreadable-parts-on-a-scan"
does = "marks"
at = "extract"
on_by_default = true
+++

# What it looks at

Two things together: that the reading recorded something it could not read, and that at least one
page of the document went as an image. Where every page went as text there is nothing a second
reading would see differently — the text layer *is* the page, and a model saying it cannot read
part of it is saying something about the text, not about its own eyes.

Where a page went as an image, "I could not read this" is exactly the thing a stronger model may be
able to read, and whether that is worth paying for is the whole of what this step decides.

# How it can be wrong

It fires on the most honest readings. A model that writes down what it could not make out is doing
what this program asks of it; one that silently guesses says nothing here. So the archives where
this fires most are not the worst-read ones — they may be the best-read ones.

It is also the loudest check in this group on an archive of scans: a faint stamp, a handwritten
margin, a corner cut off by the scanner are all unreadable parts, and none of them is a result. An
owner paying per document and reading mostly old paper should look at what their money is buying
here before anywhere else.
