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
