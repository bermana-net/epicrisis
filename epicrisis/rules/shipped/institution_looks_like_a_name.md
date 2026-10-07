+++
id = "institution_looks_like_a_name"
name = "An institution that reads like a person's name"
summary = """The form printed a person's name where a letterhead would print the clinic, so this \
archive reads that name as the doctor of the document and leaves the institution empty. Every \
document where that was done is here, because deciding that a printed name belongs to a person \
is not a thing to do in silence."""
kind = "institution-looks-like-a-name"
attaches = "document"
settles = """Open the original page. Where a letterhead is printed there and was not read, the document is worth reading again — the card says what to run. Where the form really prints only the doctor, as a hospital's own export does, nothing is wrong and this is the archive saying out loud which name it filed as whose."""
does = "marks"
at = "suspects"
on_by_default = true

[settings]
weight = 3
+++

# What it looks at

What the index wrote down: the string a form printed in the institution's place where the index
read it as a person's name rather than a place's — a title in front (доктор, dr, prof, лікар), or
initials in the shape a surname takes, and no word anywhere that an organisation uses of itself.
The reading is `suspects.provider_looks_like_a_person`, asked once, where the decision is acted
on: `index/build.institution_and_doctor`.

It used to ask that question again here, of the provider column, and so it could never find
anything at all — the index moves such a name into the doctor column before this rule is run, so
the column this looked in is empty on exactly the documents the question is about, and the count
beside the switch was a permanent zero wherever it ran. A zero reads as "nothing wrong" and meant
"looking in the wrong place". The same fact was counted at the time by the extract step's own
check, into a line called "the checks still fail" that had no name, no explanation and no switch
of its own; that line no longer carries it.

# How it can be wrong

A practice is often named after the person who runs it, and «Клініка Цьопича» is both a name and
an institution. Those are the false ones, and they are common enough that this only ever marks
the document for a look.

More often now it is not wrong and not a misreading either: an export of a hospital's own records
prints who saw the person and takes the hospital for granted, and a whole archive can be nothing
but such an export. The form was read correctly and the index filed the name under the heading it
belongs to. Such a document is still listed, because the only check on a decision about whose
name a printed string is, is a person reading it; where that is this whole archive and the reader
is content, the switch on the settings page turns the lot off and nothing comes back in its place.

In the other direction it stays silent where a laboratory has an ordinary-looking name in a
language whose words for "clinic" and "laboratory" it does not hold.
