# Contributing

Bug reports, patches and questions are welcome. Two things to know before you send code, because
both of them are easier to say now than to untangle later.

## What this project is

One person's medical archive, read by a program that stores and displays and does not interpret.
Most of the work here is refusing to be helpful: not averaging, not converting silently, not
saying whether a value is normal, not inventing a date a form never printed. A patch that makes
the program smarter about what numbers *mean* will be turned down, however well it is written.

Tests come with changes. `uv run pytest` runs them; nothing in them may contain a real person's
records, and nothing in an issue or a pull request should either — not a value, not a name, not a
scan. If a bug needs data to reproduce, invent it, or use `epicrisis demo`.

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

**A printed reference range or the scale a form uses** — `53-115 µmol/L`, `1,001-1,040`,
`19,0-37,0%` — is a property of laboratory forms and not of a person, and belongs here wherever
it explains something. A single measured value out of a real archive identifies nobody either,
but write an illustration rather than copy one: a habit of quoting real readings is how
something with a date and an institution eventually arrives with them.

`tools/nothing-of-yours.py` enforces the first paragraph before every push, over every tracked
file **and over the whole history, commit messages included**. It gathers what identifies from a
live data directory — the people, the institutions, the folders, the file names and their hashes
— and says what kind of thing matched and where, never printing the phrase itself. It does not
look for measured values; numbers are not phrases, and a check that shouts about every number is
a check nobody runs twice.

What it cannot see: a person's name that appears only inside the text of a document and nowhere
in the index. Do not copy document text and that gap stays shut.

## The licence of what you send

This project is under the [Business Source License 1.1](LICENSE): free for a person and their
household, a commercial licence for organisations. That means the author sells licences to
organisations, and to be able to do that he has to hold the rights to all of the code.

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
