# Before anything else

**Read [CONSTITUTION.md](CONSTITUTION.md) now, before you read any code.** It is one page, it says
what may never happen here, and every line of it is there because it has already gone wrong once.
Nothing below replaces it; a change that keeps every instruction on this page and breaks one line
of that one is a change that does not get made.

Then, as you need them:

- [ARCHITECTURE.md](ARCHITECTURE.md) — where each decision lives, and which module owns it. One
  decision, one place; that file says which place.
- [CONTRIBUTING.md](CONTRIBUTING.md) — what this project is, what it refuses, and the licence of
  what you send.
- [README.md](README.md) — what the program does and how to run it.

## What this is

One person's medical archive: scans and exports of thirty years of forms, in Russian, Ukrainian,
English, Spanish and Greek, read into structured data by a model and kept exactly as printed. Self
hosted, source available under BSL 1.1, nothing leaves the machine except the page a model is asked
to read.

## Working here

- `uv run pytest -n 4` runs the tests. They need no network and no model.
- `uv run epicrisis demo --into /tmp/demo` builds three archives of invented people to work
  against. Use it rather than anybody's real archive.
- `uv run python tools/nothing-of-yours.py --data-dir data` is what stands between a paste and a
  push. It is the hook in `.githooks/pre-push`, and a fresh clone turns it on once with
  `git config core.hooksPath .githooks`.

## The house style, briefly

Names read as English prose. A comment says **why** the code is as it is — the measurement behind
the threshold, the failure that bought the guard — and never what the line does. Boundaries are
written down in words and then kept.

Nothing here is a reason to break the constitution.
