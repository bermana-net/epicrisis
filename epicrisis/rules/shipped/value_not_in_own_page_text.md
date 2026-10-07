+++
id = "value_not_in_own_page_text"
name = "A value not in the model's own reading of its page"
summary = """On a page that went as an image: the value stored from it is not in the \
transcription the model itself wrote of that page. The reading disagrees with itself."""
kind = "value-not-in-the-models-own-text"
does = "marks"
at = "extract"
on_by_default = true
+++

# What it looks at

The same comparison as on a text page, with the one difference that decides everything: there is no
page text here. A scan went as an image, and what it is held against is the model's **own**
transcription of it.

That is a weaker question and an honest one. It cannot say that a number was never printed; it can
say that the reading wrote one thing in the text and another in the field, which is the strongest
thing a reading of a scan can say about itself without a second reading. That is exactly what this
step is for.

# How it can be wrong

A model that reads a table into fields correctly and writes a loose prose summary as the page text
disagrees with itself on paper and is right in the archive. Forms whose numbers are printed in a
column the transcription renders row-wise do this often.

It is also the check most sensitive to how much a model was asked to write: a short transcription
and a full set of fields will fire on every value, and that is a question about the prompt rather
than about the page.
