+++
id = "provider_reads_like_a_person"
name = "An institution read as a person's name"
summary = """The institution field of the reading holds what looks like a signature — a surname \
with initials, a title before a name — rather than a letterhead."""
kind = "provider-reads-like-a-person"
does = "marks"
at = "extract"
on_by_default = true
+++

# What it looks at

Two printed fields of the reading: the institution and the title. A name with initials beside it,
a title in front of it, or initials alone are what a signature looks like; a word naming a kind of
institution — `ТОВ`, `клініка`, `Ltd` — says it is not a person whatever else stands there, and an
abbreviation a hospital writes on its own forms is left alone.

With the title in hand there is one more sign: the institution's own words stand in the title while
the institution field holds none of them. The two were swapped.

What counts as looking like a person is answered in one place for the whole program
(`suspects.provider_looks_like_a_person`), and this asks it rather than deciding again. The index
asks the same question when it files such a name as the doctor, and a rule of the suspects step
reads what the index recorded — so one question has one answer and three readers.

**It is not the same check as the rule of the suspects step**, and the name here changed to say so.
That one reads the index, after the archive is built, and hangs a finding somebody works through.
This one reads a transcription the moment it comes back and decides whether the document is worth a
stronger model's time.

# How it can be wrong

A laboratory that really is a person — a consulting room under a doctor's own name, which is how
half the private practice in this archive prints itself — is a form where the institution field is
a person's name and nothing is wrong. Those documents go back to a stronger model and come back
saying the same thing.

The other way: a form whose letterhead is an acronym with no word of institution in it, signed by
somebody whose name reads like a company, passes this and should not.

Turning it off saves the cost on an archive full of the first kind. What it does not do is change
what the archive holds: the finding a person sees about such names comes from the rule of the
suspects step, which reads the index and goes on reading it.
