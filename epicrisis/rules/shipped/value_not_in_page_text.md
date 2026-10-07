+++
id = "value_not_in_page_text"
name = "A value not in the text of the page it came from"
summary = """On a page that went as text: the stored value is not in the page's own text at all."""
kind = "value-not-in-the-page-text"
does = "marks"
at = "extract"
on_by_default = true
+++

# What it looks at

Every stored value of a page that went to the model as text, against that page's text, by its
digits. No threshold: a page of three words is asked exactly as a page of three hundred is.

It is the plainer half of the check beside it. That one is written for the finding a person is
shown and passes over short pages and values printed as words; this one asks the simplest form of
the question of every value there is, and what it decides is whether the document is worth a
stronger model's time.

# How it can be wrong

Everything said beside `value_not_on_the_page` holds here, and more often: with no threshold, a
page whose text layer holds a line and a page number fires on every value stored from it. Those are
the pages a stronger reading is most likely to be worth paying for, which is why the threshold is
not here — but on an archive of scans with thin text layers it is also the check most likely to be
paying for nothing.
