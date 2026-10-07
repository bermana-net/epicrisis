# Contributing

Bug reports, patches and questions are welcome. Three things to know before you send code, because
all three are easier to say now than to untangle later.

## What this project is

One person's medical archive, read by a program that stores and displays and, in its default
mode, does not interpret. Most of the work here is refusing to be helpful: not averaging, not
converting silently, not saying whether a value is normal, not inventing a date a form never
printed. A patch that makes the program smarter about what numbers *mean* will be turned down,
however well it is written.

One door exists, and naming it is part of the rule. The Settings page of an instance has three
modes, and the strictest is the default; only in the third, which an owner chooses for their own
instance, does the application itself compare a number with the range printed beside it on its own
form and count what fell outside. Everything this program computes about "outside the range" lives
in that mode, and a patch that lets any of it out will be turned down with the rest.

Tests come with changes. `uv run pytest -n 4` runs them; nothing in them may contain a real
person's records, and nothing in an issue or a pull request should either — not a value, not a
name, not a scan. If a bug needs data to reproduce, invent it, or build three archives of invented
people with `uv run epicrisis demo --into /tmp/demo`.

## Nothing of a real person goes into this repository

Whoever works on this has a real archive open beside them. That is what makes the work
possible and what makes this rule necessary.

**Never, in code, comments, tests, documentation, rule files or commit messages:** the name of a
person, a doctor's name, a date of birth, the name of an institution that treated somebody, the
name or path of a file of somebody's scans, a hash of one, or any phrase copied out of a
document. These identify. There is no wording that makes them safe.

**Say it in general, not in figures.** A rule file explains what it looks at and how it can be
wrong; neither needs a number out of anybody's archive, and a count of what a rule found on one
real archive belongs in a report, not in a file that ships. Where a figure genuinely explains
something, use the kind that belongs to forms rather than to people.
`tests/test_a_rule_file_counts_nobodys_archive.py` holds the shipped rules to that paragraph, and
says in its own words what it can and cannot tell apart — a paragraph of this page went unenforced
for nine rule files, five of them published in one release, which is what a sentence with no test
behind it is worth.

**A printed reference range or the scale a form uses** — `53-115 µmol/L`, `1,001-1,040`,
`19,0-37,0%` — is a property of laboratory forms and not of a person, and belongs here wherever
it explains something. A single measured value out of a real archive identifies nobody either,
but write an illustration rather than copy one: a habit of quoting real readings is how
something with a date and an institution eventually arrives with them.

`tools/nothing-of-yours.py` is what enforces the first paragraph, over every tracked file **and
over the whole history, commit messages included**. Nothing in a fresh clone runs it for you.
`.githooks/pre-push` holds it, and git runs that hook only once you have said so:
`git config core.hooksPath .githooks` — one line, and the day you clone is the day to type it.
Until you have, nothing stands between a paste and a push but this page. By hand, at any time:
`uv run python tools/nothing-of-yours.py --data-dir data`, which exits `0` when there is nothing
of yours in here.

It gathers what identifies from a live data directory — the people, the doctors, the institutions,
the folders, the file names and their hashes, the lines of diagnosis and the medications the forms
printed, and the text of the documents themselves line by line, where a line is long enough to be
somebody's rather than any form's — and says what kind of thing matched and where, never printing
the phrase itself. It looks for the secrets of this machine as well, whole and hashed, for keys
and tokens by their shape, and for a published picture that nothing accounts for; a stray key of
your own will stop your push as surely as a stranger's name. It does not look for measured values;
numbers are not phrases, and a check that shouts about every number is a check nobody runs twice.

Whole phrases, with one exception, and the exception is a person's surname. A signature is printed
with initials and pasted without them, so a field where a person can be named — the owner of an
archive, the doctor, and the laboratory field on the forms that are filled in with a signature
instead — is looked for in words as well as whole, and a word of a name counts however short it
is. Which words those are is the initials: on a form the name has initials beside it and the
speciality does not. **A surname of yours in a docstring, a test or a commit message now stops the
push, with no initials needed.**

Two columns were asked to be read in words and measured their way out of it, and this is the
reason: a diagnosis and a prescription are sentences, and splitting them means refusing a push
over "after", "history", "level", "treatment", "forma" and the word for "kidney" — the words any
form of that kind prints and any program that reads such forms has to be free to write. The same
is true of a laboratory's name where it is a laboratory's name and not a signature: a place is
written in common nouns, a town and a street. Both are still compared whole, which is how a
sentence out of a record gets pasted anyway.

What it cannot see: a person's name printed only inside the text of a document. The lines of a
document are compared whole, so a name lifted out of one on its own matches nothing — the words
of a line are not read as the words of a name, for the reason the two columns above were left
alone. Do not copy document text and that gap stays shut.

What it also cannot see: one name spelled in the other alphabet. The spelling this check compares
by drops case and accents, and pairs nothing else, so a Russian surname out of an archive and the
Ukrainian spelling of it in a file here are two strings to it and one name to any reader. Measured
on the three archives on this machine: of the words this check reads out of the two name columns,
one more collides with a file of this repository once those letters are paired, and it was an
invented name chosen badly rather than a leak. Invent in the alphabet of the archive and look for
both spellings.

## The licence of what you send

This project is under the [Business Source License 1.1](LICENSE): free for a person keeping and
reading medical records — their own, their household's, and those of relatives or friends they
help without being paid — and a commercial licence for organisations. That is written into the
licence itself rather than promised on this page. The author sells licences to organisations,
and to be able to do that he has to hold the rights to all of the code.

So, by opening a pull request you confirm that:

1. the contribution is yours to give — you wrote it, and no employer or client owns it;
2. you grant Artem Berman a perpetual, worldwide, irrevocable, royalty-free right to use, copy,
   modify and distribute your contribution, and to license it to others **under any terms,
   including commercial ones and including licences other than this one**;
3. you keep your own copyright and every right to use your contribution elsewhere yourself — this
   grant is not exclusive and takes nothing from you.

Nothing is signed and there is no form to fill in: the pull request is the record. If that is not
acceptable to you, say so in the issue and the change can be described rather than written, which
is often the more useful half anyway.
