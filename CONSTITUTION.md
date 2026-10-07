# The constitution

Read this before you change anything here. It is short on purpose.

`ARCHITECTURE.md` says where each decision lives. `CONTRIBUTING.md` says how to send a patch. This
file says what may never happen, whatever the patch, whoever the author, however good the reason.
Everything in it was written because it had already gone wrong once.

A rule here is not a style preference and not a default. If a change cannot be made without
breaking one of these, the change does not get made.

---

## 1. The records of two people never meet

One archive is one person. Nothing this program does may put a line, a name, a number or a word
from one person's archive into any answer about another's — not on a page, not in a search, not in
a chart, not over the network, not in a log, not for an instant while a page is loading.

This is first because it is the one failure that cannot be undone by an apology. It has gone wrong:
a file of a person's own decisions was kept for the whole instance, a page read it without asking
whose it was, and one person's screen showed another person's doctors — and a label chosen in one
archive renamed a clinic on thirty-four documents of somebody else, under a line that read *as
printed on the documents themselves*.

**What crosses and what does not**, because the line is sharp and was once drawn in the wrong
place. Personal data does not flow between archives. The shared vocabulary of the program —
libraries of terms, dictionaries, which printed spellings are one test — is shared, and is meant
to be: locking it inside an archive would mean teaching the program the same thing again for every
person, and that vocabulary is the one thing here that gets better the more archives there are.

The test for which side a thing falls on is one question: **does it name a person, or does it name
a form?** Which doctor saw somebody, which clinic, which value, which diagnosis — that names a
person and stays with them. That "Гемоглобін", "Hemoglobina" and "HGB" are one test names a form,
betrays nobody, and is shared.

A shared dictionary is not a shared page. The vocabulary may hold five hundred tests; an archive's
page shows the tests that archive prints, because the page is about that archive and not about the
instance.

**One person and many archives, counted from two sides.** This is where the wall stands, and it
stands in a different place depending on which side of the program you are on. The sentence is the
owner's own, written down the day the registry of connectors was designed:

> С точки зрения консоли это всё ещё однопользовательская система — один человек и много
> пациентов. С точки зрения MCP-коннектора — многопользовательская: много коннекторов, и каждый
> может открывать нескольких или всех пациентов.

The console is one person at this machine, and that is why it has no login: there is no second
person at it to tell apart, and asking a person to prove who they are to their own medical records
is friction and one more way to lose them. What reaches the network is the MCP server, and there
**one link is one session**: the link says which people it may reach, a conversation chooses one of
them and answers about that one until it ends, and reaching another means closing that pass and
taking a new code. Many users is a fact about connectors and never about the console.

So "two archives are never open at once" stopped being true the day a link could carry rights of
its own — not of the rule above, which is about what may meet, but of the construction that used
to keep it: until then one archive was open to the server at a time and a leak between two was
impossible by accident. It is now a thing to be proved, and it is proved by measurement rather than
by argument: two connectors read side by side, in turn and in eight threads at once, and every
answer is swept for every string the other archive prints.

**And the console has no answer for two people at one keyboard, and is not going to have one.**
Two people whose records must not meet get two instances, each under its own system user, where
the separation belongs to the operating system and not to a promise this program makes about
itself. That is said out loud here because the alternative is a program that quietly behaves as
though the second person were impossible — and that is the program which shows somebody another
person's doctors.

What follows from the first paragraph:

- Anything holding a string printed on somebody's document belongs inside that archive's own
  folder, not beside the instance. A file one archive cannot open is a file it cannot leak.
- Every door into an archive takes which archive it is, and takes it as an argument that has no
  default. A call that forgets it must fail, not answer about somebody.
- A filter written at the point of use is not this rule. It is the thing that was forgotten.

## 2. As printed, or not at all

A value is stored exactly as the form printed it, with the unit and the reference range that stood
beside it. Nothing is converted, rounded, averaged, renamed, completed or tidied on the way in.

A reading of the page is allowed and is not interpretation: a unit named inside a printed range,
a date printed in a value's own line, the same unit written in two alphabets. The test is whether
the page says it. If the page does not say it, the program does not know it.

## 3. This is not a medical device and does not interpret

It stores and shows. It does not diagnose, does not advise, does not decide what is normal, and
does not say that a value is high or low.

One door exists and naming it is part of the rule: the settings page has three answer modes, the
strictest is the default, and only in the third does the program itself compare a number with the
range printed beside it. Everything this program computes about "outside the range" lives in that
mode. A patch that lets any of it out is refused.

In the modes an owner opens for themselves, a model may read the values, may say what one means,
and may answer things that sound like advice. That is allowed, and it changes nothing above,
because **it is the model answering and not this program** — and a model's answer about somebody's
documents is not medicine either. What this project owes the reader is that the two voices are
never confused: where a sentence comes from a model it says so, in the page's own words, beside
the sentence and not in a footer. A screen on which the reader cannot tell which of the two is
speaking is a defect of the first order, whatever the mode.

A rule in the registry may **mark** ("look at this") or **place** ("this is printed at that scale,
in that unit, on that day"). There is no third verb. A rule that would need one is not a rule.

## 4. A model may settle what names a form, and never what names a person

The line is the same one the first entry draws, and it is drawn here for the same reason: **does it
name a person, or does it name a form?**

**A person's name is never settled by a model.** That two spellings are one doctor, one laboratory,
one patient is a claim about identity, and two doctors of one surname and one initial work in two
clinics of every city. Nothing here applies such a claim because the model said it was sure — not
on a page, not in a cut of the timeline, not in a file of decisions. A model may put the pair in
front of the person and say why; the person answers.

**A test's name may be.** That "Гемоглобін", "Hemoglobina" and "HGB" are one test is a claim about
how forms print things, and a model may group them and the program may use the grouping, because
three things hold at once and the permission ends if any of them stops holding:

- The grouping is a label over printed names, and **the printed names do not change**. Taking a
  spelling back out restores exactly what the form printed, so the claim is reversible in full.
- **The page says it was a model and that nobody has read it yet**, in those words, beside the
  group and counted in the header — not in a footer.
- **The page can show that it is wrong.** The spellings sit side by side under the label, so a
  spelling that does not belong is visible to anyone who looks. This is the part that does not
  transfer: no document anywhere says whether two "Петров А.Б." are one person, so a person's name
  joined by mistake cannot be caught by reading the screen.

That last point is the whole distinction, and it is why this entry is not symmetrical. The cost of
being wrong differs too — a test wrongly grouped draws one chart where two belong, a person wrongly
joined asserts that two people are one — but cost is not the test. **Reversible, said out loud, and
visible when wrong** is the test, and a model's answer gets applied only where all three hold.

Nothing else a model answers is applied because the model said it was sure.

## 5. Nothing of anybody's is published, and publishing cannot be undone

Before anything leaves this machine, `tools/nothing-of-yours.py` reads a live data directory and
looks for what it finds there in every tracked file and in every commit that will travel. It
answers 0 or it answers 1. An archive it could not read in full is an archive it cannot clear, and
saying "clean" about one is worse than crashing.

A name invented for a test, a docstring, a prompt or a card is looked for in the archives **before**
it is written down. A plausible surname in the right language is usually a real one.

## 6. Every fix names what it could break, and proves it did not

A change comes with a test that fails without it. A change that touches what the program shows
comes with a measurement before and after, and every movement is explained one by one.

**Measuring on the live archive is not enough.** It is blind to the shapes it does not happen to
contain — three defects of the first order were shipped in one day because the archive in front of
us had no document of the shape that would have shown them. Invent the shape and measure that too.

## 7. The program says out loud everything it does

If a value was moved to another scale, the page says so. If it was placed by its own numbers
rather than by a printed unit, the page says so. If a retelling was folded away because the form
it quoted is already here, the page says so. A count that differs from another count on the same
page is a defect, not a detail.

A refusal says which file, what is safe, and what puts it right. A dead end with no way out is a
defect. An error with no cause is a defect.

## 8. A person's own work is never overwritten by what could not be read

Files holding what a person typed, corrected, approved or joined are not rebuildable by any amount
of money or time. A reader that cannot parse one of them raises; it does not answer "empty", because
every writer is read-modify-write and an empty read writes the emptiness back. The version a write
replaces is kept beside it.

## 9. The whole archive is read again on a direct order, and otherwise never

Reading an archive again costs a person hours of waiting and a month of their subscription, and the
pages that come back are the same pages. So a new field, a new question, a new thing the program has
come to want is **not** a reason to send anybody's documents to a model a second time. What the
program needs it takes out of the text it has already read and already keeps, with whatever tool
reads text: a label beside a signature, a date in a line, a unit in a heading. The transcriptions
are not touched doing it, and nothing a model said before is overwritten.

A whole archive goes back to a model when its owner says so, in so many words, and in no other way
— not because a version number moved, not because a step was added, not because a reader got
better. Where re-reading really would buy something, the program says what it would buy, on how
many documents, and waits.

The failure behind this entry was caught one step before it happened. The field for a doctor was
added after these archives were read, so not one of their 706 transcriptions carries it, and the
plan on the table was to read 386 documents again to fill it. Then the stored text was searched
instead: **123 of those 706 documents name their doctor in text the program had already read**, at
no cost and in under a second. The owner's words, and the reason this is written here: *"Если мы в
дальнейшем добавляем функциональность и данные есть из самого текста, то это не повод перечитывать
весь архив."*

What follows:

- A step that wants something new looks in the stored text first, and says what it found there.
- Reading again is a command a person runs, never something a step decides for them.
- A reading taken out of stored text names a person only as a **proposal**; the fourth entry
  governs it exactly as it governs a model's.

---

## How this file is kept

It grows only by subtraction of ambiguity, never by addition of preferences. A new entry needs a
concrete failure behind it, named in the entry.

Every model working on this project reads this file first. `CLAUDE.md` points at it for that
reason, and the point of pointing is that nobody has to remember.
