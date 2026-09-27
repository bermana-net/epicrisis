+++
id = "lab_without_values"
name = "A laboratory form with nothing transcribed from it"
summary = """A page classified as laboratory results, sent to be read, and came back with no \
values at all. Either it is not a results page, or the reading failed on it."""
kind = "lab-form-with-nothing-in-it"
attaches = "document"   # where a finding of it hangs: on a value, or on the document
order = 8             # where it stands in the queue a person works through
settles = """Lab results with nothing transcribed. It may be a covering letter, or it may need reading again."""
does = "marks"
at = "validate"
on_by_default = true
+++

# What it looks at

Documents classified as a laboratory panel, which were due to be transcribed, whose transcription
holds no values.


# How it can be wrong

A results page whose table is a picture too poor to read will land here, and there is nothing to
be done about it except know that it is there.
