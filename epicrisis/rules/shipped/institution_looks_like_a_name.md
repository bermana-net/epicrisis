+++
id = "institution_looks_like_a_name"
name = "An institution that reads like a person's name"
summary = """The doctor who signed under the stamp recorded as the laboratory that issued the \
form. A small model reading a scan takes the name nearest the stamp, and on many forms that \
name is the signature."""
kind = "institution-looks-like-a-name"
does = "marks"
at = "suspects"
on_by_default = true

[settings]
weight = 3
+++

# What it looks at

The institution as it was read, against the shapes a person's name takes and the words an
organisation writes about itself. A title in front — доктор, dr, prof, лікар — or initials in
the shape a surname takes, and no word anywhere that an institution would use of itself.

# How it can be wrong

A practice is often named after the person who runs it, and «Клініка Іванова» is both a name and
an institution. Those are the false ones, and they are common enough that this only ever marks
the document for a look.

In the other direction it stays silent where a laboratory has an ordinary-looking name in a
language whose words for "clinic" and "laboratory" it does not hold.
