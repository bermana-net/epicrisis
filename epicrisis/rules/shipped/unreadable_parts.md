+++
id = "unreadable_parts"
name = "Parts of a page that could not be read"
summary = """The reading itself said it could not make something out: a signature, a stamp, a \
handwritten note in the margin, a line under a fold."""
kind = "unreadable-parts"
attaches = "document"   # where a finding of it hangs: on a value, or on the document
order = 12             # where it stands in the queue a person works through
settles = """Mostly nothing to do: a signature, a stamp, a handwritten margin. Read what could not be read, and open only what touches a value."""
does = "marks"
at = "validate"
on_by_default = true
+++

# What it looks at

What the transcription of a document listed as unreadable, counted.


# How it can be wrong

It is the most common finding in an archive of scans and the least urgent, which is exactly why
it stands last in the order a person works through them.
