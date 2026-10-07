+++
id = "word_in_two_alphabets"
name = "A word written in two alphabets at once"
summary = """A word of the document's head holding Cyrillic and Latin letters together, as in \
"Кліnіка": a letter read from the wrong alphabet."""
kind = "a-word-in-two-alphabets"
does = "marks"
at = "extract"
on_by_default = true

[settings]
of_fields = ["provider_as_printed", "title_as_printed"]
+++

# What it looks at

Each word of the institution and the title, and whether one word holds letters of both alphabets.
A name holding a word of each — `Клініка VITAMED` — is two words, two alphabets and nothing wrong.
One word holding both is a slip of the reading: `о` taken from the wrong alphabet looks exactly
like `o` and is a different letter to everything that searches.

One hit per field and never per word. A title with four such words is one field read wrongly, and
the document goes back to a stronger model once either way.

Why the head and not the whole text: a form prints its institution once, in large letters, and
that is the string the whole archive is grouped by afterwards. A letter from the wrong alphabet in
the middle of a paragraph costs a search one hit; in the name of a clinic it makes a second clinic
that never existed.

# How it can be wrong

A form that really prints a mixed word — a brand written as `СLINIC`, a transliteration somebody
chose on purpose — fires this for ever, and the stronger model reads it the same way, because it
is what the page says.

This archive's forms are printed in five languages and two alphabets, and a laboratory in Cyprus
writing a Ukrainian patient's name beside a Greek heading is ordinary here. That is not what this
reads: it asks about one word, not about a line or a page.
