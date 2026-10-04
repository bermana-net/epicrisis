"""One module for each kind of file an archive holds, and one place that says which is which.

Everything this program knows about a format used to be spread over two files organised by step:
what to look for in a file, in the inventory; how many pages it has and what a page is, in the
step that classifies them. Each of those held a branch per format, and a format added meant a
branch added in both, with nothing saying what the two had to agree about.

A reader answers four questions, and the steps ask them. The questions are the whole of what a
step needs to know about a kind of file:

- `probe(source, mime) -> dict` — what is true of this file: how many pages, how much text, what
  is pasted inside it. Facts only, written into the inventory, with no model anywhere near them.
- `pages(record) -> [(route, part, document)]` — the pages of the file, in order. The route is
  "text" or "vision": whether a page can go to a model as words or has to go as a picture. The
  part says which run of pages inside the file it belongs to, since one file can hold two (a
  Word document holds its text and the scans pasted into it). The document is for a file whose
  documents were marked out before it was cut into pages, and is None for everything else.
- `text_of(data, ref) -> str` — the page as words, for a page whose route is "text".
- `image_of(data, ref, zoom) -> Image` — the page as a picture, for a page that is one. Raw: the
  resizing, the stripping of EXIF and the writing of a PNG belong to the payload, not here.

Not every reader has all four. A photograph has no text and a text file has no picture, and the
step that asks knows which it is asking for from the route it was given.

Four steps of one pass ask the same two questions of the same page — the inventory asks `probe`
whether the page has a text layer, and classify, extract and the checks each ask `text_of` for it
— so a reader whose answer is dear to arrive at may remember it for the length of one pass and no
longer. `readers/pdf.py` does, through `remembering_page_text`, and says there why that is a pass
and not the life of the process. A reader that does not remember anything is not wrong, only
slower: nothing outside the readers knows whether a page was read now or earlier in this pass.
"""

from epicrisis.readers import excel, pdf, picture, text, word

#: Which reader serves a file of each kind, by the category the inventory gave it. A kind of file
#: with no reader here is inventoried and left alone, which is what happens to a format this
#: program does not read: it is counted, named and never sent anywhere.
READERS = {
    "pdf": pdf,
    "image": picture,
    "word": word,
    "excel": excel,
    "text": text,
}


def reader_for(category: str | None):
    """The reader for a kind of file, or nothing where this program does not read that kind."""
    return READERS.get(category or "")
