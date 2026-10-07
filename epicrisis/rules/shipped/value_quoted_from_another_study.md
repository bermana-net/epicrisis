+++
id = "value_quoted_from_another_study"
name = "A value quoted from an earlier study: put it on the date printed beside it"
summary = """A consultation retells what was measured before it — "ТТГ 4.12 від 19.01.16" — and the \
number, read correctly, is then dated by the document that quotes it. Where the value's own \
printed line names the day, the point is drawn on that day instead."""
kind = "date-printed-in-the-line"
does = "places"
at = "charts"
on_by_default = true
+++

# What it looks at

The printed line kept beside every value, and the date of the document that line came from. A
laboratory form prints its date once, at the top, and its rows carry no date of their own. A
doctor writing a note has to say when the thing he is retelling was done, because otherwise his
own sentence means nothing — and that date, printed in the line, is the date of the measurement.

Nothing is read from a model, nothing is computed, and the stored reading is not touched. This is
the same act as reading a unit out of a printed reference range: the page says it, and the chart
draws what the page says.

# What it will not do

It will not read a printed reference range as a date. That is the whole difficulty: "4.11-5.89"
is a glucose range, and to a loose reader it is the eleventh of April 1989. The first reader
written here was that loose, and what it called quotations were printed ranges — every one of them
a real laboratory value that this rule would then have moved decades from where it was measured.

So a date must be one of two shapes and nothing else.

**Three parts with one and the same separator between them**, and where the year is shortened to
two digits the day and the month are written in two digits as well. The one separator is what
tells "11.02.15" from "4.11-5.89", whose separator changes from a dot to a dash. The padding is
what tells a date from everything else that is three small numbers over one separator — a course
of treatment ("5-7-10 днів"), the doses a tablet comes in ("5/10/20 мг"), a count in a field of
view, a line of visual acuities ("6/9/18"), a numbered heading ("2.1.19") and the version a device
prints — all of which were read as dates for as long as this page claimed a triple could be
nothing else. The reading is day first, as all five of these languages write it; a triple that can
only be read month first wants the word below, because month first is the habit of none of them.

**A month and a year that somebody introduced** with a word or set apart in brackets of their own,
printed with a dot or a slash and never a dash. A dash is how a range is printed, and nothing else
separates the two: "(норма 4-2000)" sits in brackets of its own, "4-2000 нг/мл феритин 23" opens
its line, and in "IgE от 5-2015 МЕ/мл" a word that introduces dates everywhere else stands in
front of it.

A month printed as a name — in any of the five languages, in the case each declines it into, in
the abbreviations a laboratory system prints ("10-NOV-2019") or in Roman numerals ("19.ІХ.2019") —
takes the same two shapes. A date in Roman numerals is read only where it is printed tight,
because a Roman month is one or two letters and "х" is also the multiplication sign of every blood
count on these forms: "Лейкоцити 5 х 10 9/л" is five times ten to the ninth and not a day in
October.

A day that cannot exist, a year before 1900, and a date later than the document that carries it
are all refused. Nothing of a date is glued to a letter, so the version a device prints is not one.

It will not move a value whose line names the document's own day, or a day within a month of it: a
form printed on the fifth and signed on the twelfth is one visit, not two studies.

# What it does not settle

Whether a quotation should be drawn at all. Most of what it finds is a doctor retelling a
laboratory form the archive already holds, and some of it is the only surviving record of a
measurement whose own form was never scanned. Which of those a chart shows is not this rule's
business; this rule says when the thing was measured.

# Why it exists

A doctor retells a measurement months or years after it was taken, so a chart that dates the
retelling by the note draws the point where the note is and not where the measurement was. The
distance is the whole defect, and it is a distance of seasons and of years rather than of days:
far enough to put a reading in the wrong decade of a history, to invent a rise that never
happened and to hide one that did. It is also invisible on the page — the note prints the date and
the chart simply does not use it — which is why this is a rule and not a thing to notice.
