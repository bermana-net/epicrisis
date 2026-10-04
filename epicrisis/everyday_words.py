"""The words people say for a test, next to the words laboratories print for it.

A person looking for their own blood sugar types "sugar". No form in any archive prints that word,
so the search answered nothing, the find box on the indicators page answered nothing, and the one
way on — "Ask for it in your own words" — needs a model and is off in the installation this
project ships. Out of the box there was no path at all from the word a person has to the row a
laboratory printed, over an archive holding forty-four values of Glucose.

**What this is under the constitution.** It names a form, not a person: that laboratories print
"Glucose" for what people call sugar says nothing about anybody, is true of every archive, and is
the kind of vocabulary the first entry says is shared on purpose. It holds no value, no date, no
institution and no name, so it ships in this repository rather than beside an archive.

**What it is not, and the line is hard.** This is not interpretation and no medical judgement is
made here (the third entry): "sugar" to "glucose" is about what the form calls the row, never
about what the number on it means. So every line of the table obeys one rule, and the rule is a
sentence that has to be writable about it:

    what people call X, a form prints as a row named Y.

A word that cannot be put in that sentence does not go in the table. Refused for that reason, and
each of them was considered:

- "chest pain" — a complaint. No row of any form is named it, and nothing here turns a symptom
  into a measurement to look at.
- "thyroid", "kidney function", "liver" — an organ, or what one does. Which rows stand for an
  organ is a medical judgement, and this program does not make one.
- "good cholesterol", "bad cholesterol" — carries a verdict on the value, which is the one thing
  the third entry of the constitution forbids outright. HDL is printed as HDL.
- "anaemia", "diabetes" — a diagnosis.
- "iron" — a word laboratories already print, and it is printed for two different rows (serum
  iron and ferritin are not one test). An everyday word that is also a printed name belongs
  nowhere near this table: the ordinary search already answers it, correctly and literally.

No model is asked anything here, and nothing is written at run time: the table is small, explicit,
and read by eye in a review. A page that answers by it says so in its own words rather than
pretending the person typed the printed name — the seventh entry — and the callers use it only
where a question found nothing by name at all, so a question that already worked is never widened
and never given a hit it did not have.
"""

from epicrisis.printed_values import fold

# Everyday words on the left, in every language the archives are written in; on the right the names
# a laboratory prints for the same row, enough of them that one matches whatever a group of
# spellings happens to be labelled with. Both sides are written as a person or a form writes them
# and folded below, so that this table stays something a reviewer can read.
_TABLE: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    # The word this whole file was written for. Glucose is printed; sugar is said.
    (("sugar", "blood sugar", "azúcar", "ζάχαρη", "сахар", "цукор", "сахар в крови", "цукор у крові"),
     ("Glucose", "Glucosa", "Γλυκόζη", "Глюкоза")),
    # Salt is sodium chloride and the row a form prints is the sodium in it.
    (("salt", "sal", "αλάτι", "соль", "сіль"),
     ("Sodium", "Sodio", "Νάτριο", "Натрий", "Натрій")),
    (("white blood cells", "white cell count", "glóbulos blancos", "λευκά αιμοσφαίρια",
      "белые клетки", "белые клетки крови", "білі клітини", "білі клітини крові"),
     ("Leukocytes", "White cells", "Leucocitos", "Λευκά", "Лейкоциты", "Лейкоцити")),
    (("red blood cells", "red cell count", "glóbulos rojos", "ερυθρά αιμοσφαίρια",
      "красные клетки", "красные клетки крови", "червоні клітини", "червоні клітини крові"),
     ("Erythrocytes", "Red cells", "Hematíes", "Ερυθρά", "Эритроциты", "Еритроцити")),
    # A form prints the D in Latin even in a Russian or Ukrainian name, and a person at a Cyrillic
    # keyboard types the Cyrillic letter. Not a fold and not an alphabet swapped whole: see
    # printed_values.also_written_as, which answers only for a word every letter of which has a
    # twin, and "витамин д" is not one.
    (("витамин д", "вітамін д", "вит д", "віт д"),
     ("Vitamin D", "Vitamina D", "Βιταμίνη D", "Витамин D", "Вітамін D")),
)

# Folded, because every match in this program is made on the folded form of printed text. Built
# once: a table read on every keystroke of a search box is a table read a thousand times a minute.
# Folding also joins pairs that differ only by a letter it merges, so the printed names come out
# deduplicated: Russian "Натрий" and Ukrainian "Натрій" both fold to one word, and a term offered
# twice would make a page say it twice.
EVERYDAY_WORDS: dict[str, tuple[str, ...]] = {
    fold(said): tuple(dict.fromkeys(fold(printed) for printed in printed_names))
    for said_as, printed_names in _TABLE
    for said in said_as
}


def stands_for(question: str | None) -> tuple[str, ...]:
    """The printed names an everyday word stands for, folded, or nothing if it is not one.

    The whole question, not a word inside it. A word taken out of the middle of a sentence would
    make "sugar beet" a question about blood glucose, and a page that cannot say plainly which
    word it answered is worse than a page that answers nothing.
    """
    if not question or not question.strip():
        return ()
    # Stripped before folding: folding does not trim, and a word pasted out of a document arrives
    # with a space on either side of it.
    return EVERYDAY_WORDS.get(fold(question.strip()), ())
