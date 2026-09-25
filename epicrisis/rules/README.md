# Writing a rule

A rule is one file in `shipped/` (rules that come with the program) or in `<data>/rules/` (rules
an archive added for itself). Both folders take the same format and are checked the same way.

```
+++
id = "number_far_from_the_others"          # and the file is named after it
name = "A number many times away from every other reading of the same test"
summary = """One sentence, shown beside the switch."""
kind = "number-far-from-the-others"        # one of the kinds in kinds.py
does = "marks"                             # or "places". There is no third one.
at = "suspects"                            # which step runs it
on_by_default = true

[settings]
weight = 3                                 # only names this kind declares, with the right types
times_away = 10
+++

# What it looks at
...
# How it can be wrong
...
```

The body is Markdown and is the larger part on purpose: the person deciding whether to turn a
rule on needs to know what it looks at and how it can be wrong, and that is not something a
threshold can say. A file with nothing written in it is refused.

`does` and `at` are on the kind already; the file repeats them because the first question anyone
opening a rule has is what it is allowed to do and which part of the program it belongs to.
Where the file and the kind disagree, the file is refused, so the two cannot drift apart.

A rule file holds no code, and a rule in a data folder may only name a kind that already exists.
That is the boundary that lets rules be shared: a shared rule is a thing you read, not a thing
that runs.

## Adding a kind

Only when a rule needs something no kind can do. A kind goes in `kinds.py` with its settings and
their defaults, the subject it takes (`subjects.py`), the step that runs it, and whether it
marks or places. The *doing* belongs in the module that owns that decision — the arithmetic of
scales in `units.py`, the reading of an index in `suspects.py` — and the kind only names it.
Then the same kind with another threshold, another list of words or another set of tests is a
new file and no new code at all.

## A rule that needs a model

None exists yet. When one does, these hold, and they are written here so that the first one does
not have to work them out again:

- **It reaches the model through `engines.py`**, like every other model call in the program, so
  that it runs under whichever engine the instance chose and never bills a key the person
  thought was idle. Never `subprocess`, never `httpx`, never a key read from the environment.
- **Its step is a costly one** (`extract` today). The settings page holds such a switch back and
  asks before it takes effect, saying what it will cost; see `COSTLY` in `kinds.py`. A rule that
  sends pages to a model must never be a switch somebody flips by leaning on the mouse.
- **The prompt is a named field in the header, not the prose.** The body can be reworded any
  time without changing a single answer; a prompt cannot. Mixing them means rephrasing a
  paragraph for a reader and silently changing what the archive reads next time.
- **The prompt is part of what decides whether a document must be read again.** The pipeline
  already keys its ledger on a prompt version (`PROMPT_VERSION` in the steps); a model-using
  rule needs the same, computed from its own prompt, or editing that prompt would leave every
  document looking already done.
- **Consent still governs it.** Sending a page to a model is what `consent.py` records, by
  destination. A rule cannot be a way around that, so such a kind checks consent before it runs
  and says plainly when it has none.
- **The boundary does not move.** A model-using rule still only `marks` or `places`. It may be
  asked what is printed on a page; it may not be asked whether a value is bad, what it means, or
  what to do about it (MDCG 2019-11).

## The ruler

Before changing anything that a rule touches, take the snapshot and compare it afterwards:

```
tools/findings-snapshot.py before.txt
... the change ...
tools/findings-snapshot.py after.txt && diff before.txt after.txt
```

It re-runs every check over the real archives and writes codes and counts, no medical content.
A move that keeps its promise produces an identical file. Write it somewhere outside the
repository.
