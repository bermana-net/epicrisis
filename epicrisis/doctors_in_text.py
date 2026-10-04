"""The doctor a document names inside its own text, read out of what is already stored.

The field for a doctor was added to this program after these archives were read, so not one of
their 706 transcriptions carries it. The plan on the table was to read 386 documents again to
fill it, and the ninth entry of the constitution was written instead: the stored text is searched
first, at no cost and in under a second. Measured on the three archives here, the text names a
doctor on 192 documents in 84 distinct names, and 51 of those names stand nowhere in the index's
doctor column — which is why the owner looked on the page of doctors for two of his own and found
neither.

**Nothing here is applied, and that is the fourth entry and not a preference.** A name is a claim
about who a person is. What this module does is read what a form printed and count it; it never
says that two spellings are one doctor, never fills the doctor column, never touches a
transcription and never writes a file at all. The names it finds go on the page beside the names
the index read, each with the line it was read from, and every join is still the press a person
makes in `people.py`.

Why that is enough for the fourth entry's third condition, which for a person's name usually
fails: the claim made here is not "these two are one human being" — no document on earth settles
that — but "this document prints this name under this label", and the document *does* say that.
So the page carries the printed line beside the name, and a reading that took a department for a
surname is visible to anybody who reads the line. See `WHERE_IT_CAME_FROM`.

**A name must prove that it is a name**, and this is the whole of the design. The crude first
search was a label followed by a word, minus a stop list of the form words that follow such a
label — and a stop list only ever holds the form words somebody has already been caught by. So
instead the shape of the name is the evidence: initials, or a patronymic behind two names, or an
honorific printed in front. A department, a degree, a kind of room and a word like
«Відділення» do not come with initials, so no list of them is needed and none is kept. What it
costs is written down rather than hidden: a bare surname under a label — «Зав. відділенням
Квазитрофенко», with nothing else on the line — is not read, because nothing in those letters
tells a surname from a speciality.
"""

import re
import unicodedata
from dataclasses import dataclass

#: Cyrillic, written out letter by letter rather than as a block. `Ѐ-ӿ` was the first spelling of
#: it, and that range holds the whole alphabet including the capitals — so the filler between a
#: label and a name swallowed the surname and the reading came back as the initials welded to the
#: next word of the form. Measured before and after on the three archives here: 29 of 84 names
#: were that shape, and all 29 came right.
UPPER = "А-ЯЁЇІЄҐЎ"
LOWER = "а-яёїієґў"
ANY = UPPER + LOWER

#: The labels a form of five countries prints where the person who saw, performed or signed goes.
#: `лікар` is matched as a whole word on purpose: «лікарня» is a hospital and holds it whole.
SIGNED = (
    r"лікуюч\w*\s+лікар\w*", r"лечащ\w*\s+врач\w*", r"л[іi]кар[ья]?", r"врач",
    # «доктор медичних наук» is a degree printed on a letterhead, not the role of whoever signed:
    # it named a scientific supervisor off the heading of four documents here, which is a name off
    # the form's top and not a signature.
    r"доктор(?!\s+меди[цч])",
    r"зав[іi]дувач\w*", r"завідуюч\w*", r"заведующ\w*", r"зав\.",
    r"зам\.?\s*головного\s+л[іi]кар\w*", r"зам\.?\s*главного\s+врача",
    r"виконав\w*", r"виконала", r"исполнитель", r"в[іi]дпов[іi]дальн\w*",
    r"médico", r"medico", r"facultativo", r"firmado", r"fdo\.",
)
#: Who sent the person here, or who was asked for. Recognised **in order to be left out**: the
#: field asks for the person who saw, performed or signed, and a referring doctor did none of the
#: three. Leaving these in is how a reading names somebody who never saw the person — the Greek
#: laboratories print «ΠΑΡΑΠΕΜΠΩΝ ΙΑΤΡΟΣ: NOT ASSIGNED» in the same place a signature goes.
REFERRED = (
    r"ф\.?\s?и\.?\s?о\.?\s+врача", r"п\.?\s?і\.?\s?б\.?\s+л[іi]каря",
    r"направив\w*", r"напрям\w*", r"направил\w*", r"παραπεμπων\s+ιατρος",
    r"referring\s+(?:physician|doctor)", r"m[eé]dico\s+solicitante", r"solicita\w*",
)
#: An honorific is itself the proof that what follows is a name: no form prints "Dr." in front of
#: a department. `(?<![\w.])` is not decoration — an eye examination here prints «AR (Mydr.)», and
#: the crude search read a refraction table as a doctor.
#:
#: **The bare Cyrillic «др» is deliberately not here**, and only the hyphenated «д-р» is. «и др.»
#: is Russian for "and others" and stands once in these archives already, with no lookbehind able
#: to tell it from an honorific: the word before it is a space either way. Measured before it was
#: taken out — the bare form yields nothing at all on all 706 documents, so it was risking the
#: reading of "and others" as a person in exchange for nothing.
HONORIFIC = r"(?:dr|dra|d-?r|д-р|δρ)\.?"

#: An academic degree stands between the label and the name on every discharge summary of one
#: hospital here. It is written in lower case with dots, so it is named rather than left to the
#: lower-case word below: «к.м.н.» would otherwise read as initials.
DEGREE = r"(?:к\.\s?м\.\s?н\.|д\.\s?м\.\s?н\.|м\.\s?н\.\s?с\.|с\.\s?н\.\s?с\.|проф\.|доц\.|д-р)"
#: What a form prints between the label and the name, and nothing else may stand there: a colon, a
#: rule of underscores or dots, a transcriber's bracket, a degree, a department in lower case, and
#: a department's initials in capitals. Three deliberate limits — a word is let through only in
#: lower case, because a department is printed in lower case and a surname is not; capitals are
#: let through only two to five of them with no dot after, which is «КДЦ» and never a name; and
#: nothing else at all, so the filler can never cross the name it is looking for.
#:
#: **The lookbehind on each word is what tells a doctor from a hospital**, and it is the only
#: thing that does. «лікарня» is a hospital and holds the label whole, and the label used to carry
#: a word boundary of its own against exactly that — two statements of one guard, and the weaker
#: of the two: a boundary after the label blocks «лікарня» and so does this, while this also
#: blocks «лікарняний», whose five remaining letters the filler would otherwise have walked
#: straight over. Measured with the boundary and without it over all 706 documents here: 50, 29
#: and 5 names either way, so what it was doing this was already doing. It went, and the guard
#: lives in one place.
FILLER = (rf"(?:[\s:：\-_/\\|.,;()№]|{DEGREE}"
          rf"|(?<![{ANY}])[{LOWER}][{LOWER}'’-]{{2,}}(?![{ANY}])"
          rf"|(?<![{ANY}])[{UPPER}]{{2,5}}(?![{ANY}.]))*")  # fmt: skip

WORD = rf"[{UPPER}][{ANY}'’ʼ`-]+"
INITIAL = rf"[{UPPER}]\."
#: One or two initials, the second allowed to have lost its dot: of the 84 names read here, the
#: forms print 31 with the last dot missing. Up to two spaces between them and no more, because a
#: form's columns leave the gap its own layout leaves — and bounded at two, because an unbounded
#: gap would reach across a line to the next capital-and-dot on it and read two fields as one name.
INITIALS = rf"{INITIAL}\s{{0,2}}(?:[{UPPER}]\.?)?"
#: The suffixes a patronymic is built with. Only ever used behind **two** other names, and that is
#: a measurement and not caution: a great many Ukrainian surnames end the same way, so
#: «Завідуюча КДЛ Квазитрофенко» read as a name-plus-patronymic and came back as the department
#: welded to the surname. Three words is proof; two is a coincidence.
PATRONYMIC = (rf"[{UPPER}][{ANY}]*"
              r"(?:ович|евич|йович|ьович|івич|овна|евна|ївна|івна|инична|ічна)")  # fmt: skip

#: The three shapes a Cyrillic name proves itself by. Each is one named group, so a reading can
#: say which shape it was read as — the page shows it, and a defect in one shape is then a defect
#: anybody can see the extent of.
NAME = (rf"(?P<surname_then_initials>{WORD}\s*{INITIALS})"
        rf"|(?P<initials_then_surname>{INITIALS}\s?{INITIAL}?\s*{WORD})"
        rf"|(?P<three_part>{WORD}\s+{WORD}\s+{PATRONYMIC})")  # fmt: skip

LATIN = "A-ZÁÉÍÓÚÑÜ"
LATIN_LOWER = "a-záéíóúñü"
#: A Latin name, which has no initials to prove itself by and leans on the honorific in front of
#: it instead. The trailing guard on the capitals is one archive's export writing the surname into
#: the next word with no space between: «DRA. QUALTRINA VEXMOORColegiado nº ...» gave a surname one
#: letter too long until the run was made to stop where the lower case starts.
LATIN_NAME = (rf"(?P<latin>(?:[{LATIN}]\.\s*){{0,2}}[{LATIN}][{LATIN_LOWER}]+"
              rf"(?:\s+(?:[{LATIN}]\.\s*)?[{LATIN}][{LATIN_LOWER}]+){{1,2}})"
              rf"|(?P<latin_caps>[{LATIN}]{{2,}}(?:\s+[{LATIN}]{{2,}}){{1,2}})(?![{LATIN_LOWER}])")  # fmt: skip
#: Four or more capitalised Latin words behind an honorific is a stamp with a role welded onto the
#: name — "Dr Qualtrina Vexmoor Personal Doctor". Nothing in the letters says where the name stops,
#: so nothing is read: a fourth of a stamp is not a name, and a guess here is the kind of thing
#: the page could not show to be wrong.
TOO_LONG = re.compile(rf"[{LATIN}][{LATIN_LOWER}]+(?:\s+[{LATIN}][{LATIN_LOWER}]+){{3,}}"
                      rf"|[{LATIN}]{{2,}}(?:\s+[{LATIN}]{{2,}}){{3,}}")  # fmt: skip

AFTER_LABEL = re.compile(rf"(?P<label>(?i:{'|'.join(SIGNED)})){FILLER}(?:{NAME})")
AFTER_HONORIFIC = re.compile(rf"(?<![\w.])(?i:{HONORIFIC})\s+(?:{LATIN_NAME}|{NAME})")
A_REFERRAL = re.compile(rf"(?i:{'|'.join(REFERRED)})")
#: What a transcriber wrote about a mark on the paper rather than what the form printed. Inside one
#: the order of a label and a name is the order of somebody describing a picture, not the layout of
#: a form — a round stamp here reads «[печать: ... * ЛІКАР * ...]», and read as a form it gave a
#: patronymic with no surname in front of it. So a bracket is blanked before the labels are looked
#: for, and the label a name is read under is always one the form itself printed.
A_NOTE = re.compile(r"\[[^\]]*\]")

SHAPES = ("surname_then_initials", "initials_then_surname", "three_part", "latin", "latin_caps")

#: The sentence the page says beside such a name, in the page's own words and not in a footer.
#: The ninth entry asks for it and says why: the index's own fallback moves a provider into the
#: doctor field when the provider looks like a person, and that is a different kind of claim from
#: this one — one is a name off the form's heading, this is a name out of the form's own text. A
#: person deciding has to know which of the two they are looking at.
WHERE_IT_CAME_FROM = ("Read out of this document's own text, under the label the form prints "
                      "beside a signature. Nobody has confirmed it, and nothing has been filled "
                      "in from it.")  # fmt: skip


@dataclass(frozen=True)
class Reading:
    """One name a document prints under one label, and the line it was printed on.

    The line travels with the name and is not a nicety: it is the whole of what makes this
    readable as right or wrong (the fourth entry's third condition), and a name shown without it
    would be a claim about a person with its evidence hidden.
    """

    name: str
    label: str
    shape: str
    line: str


def tidy(name: str) -> str:
    """One name as the form printed it, with the run of spaces an export leaves inside it closed up.

    Not a normalisation of the name — the second entry forbids that, and nothing here renames
    anything. A form prints «Квазитрофенко  О.П.» with the two spaces its columns happen to leave,
    and that is the same printed name as with one. Case, letters and order are left exactly alone.
    """
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", name)).strip(" \t:_-/\\|.,;")


def tidy_label(label: str) -> str:
    """One label as the form printed it, keeping the dot that is part of it.

    `tidy` strips a trailing dot, which is right for a name — a form ends the initials with one and
    ends the line with one too — and wrong for a label: «Зав.» is an abbreviation and the dot is
    the abbreviating. The page prints this label in quotation marks beside the name, so a label
    shown as «Зав» would be the page quoting a word no form printed (§2).
    """
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", label)).strip(" \t:：_-/\\|,;")


def readings(text: str) -> list[Reading]:
    """Every doctor one document's stored text names, in the order the pages print them.

    Nothing is sent anywhere and nothing is written. Measured on the three archives here: 0.32
    seconds for all 706 documents, read out of the index's own `page_texts`.
    """
    found: list[Reading] = []
    seen: set[tuple[str, str]] = set()
    for line in (text or "").split("\n"):
        # The bracket is blanked rather than cut out, so that every offset still points at the
        # line the person will read.
        without_notes = A_NOTE.sub(lambda note: " " * (note.end() - note.start()), line)
        referral = A_REFERRAL.search(without_notes)
        for pattern, honorific in ((AFTER_LABEL, ""), (AFTER_HONORIFIC, "Dr.")):
            for match in pattern.finditer(without_notes):
                # A name standing after "who referred" on the line is that doctor, not this one.
                if referral and referral.start() <= match.start():
                    continue
                shape = next(one for one in SHAPES if match.groupdict().get(one))
                if TOO_LONG.match(line, match.start(shape)):
                    continue
                name = tidy(match.group(shape))
                label = honorific or tidy_label(match.group("label"))
                if not name or (name, line) in seen:
                    continue
                seen.add((name, line))
                found.append(Reading(name=name, label=label, shape=shape, line=line.strip()))
    return found


def who_stands_in_the_text(connection) -> list[dict]:
    """Every doctor the stored text of one archive names, counted, with a line for each.

    Takes an open index connection and nothing else, so that the archive this answers about is the
    archive the caller already opened — the first entry asks every door to take which archive it is
    and this one cannot forget, having no way to open a second.

    Only the copy a person is shown is counted. The same result arrives here three times — a
    letter quoting a printout quoting a laboratory — and counting all three would say one doctor
    signed three documents where he signed one.
    """
    pages: dict[int, list[str]] = {}
    for document_id, text in connection.execute(
        "SELECT p.document_id, p.text FROM page_texts p JOIN documents d ON d.id = p.document_id "
        "WHERE d.primary_copy = 1 ORDER BY p.document_id, p.page"
    ):
        pages.setdefault(document_id, []).append(text or "")
    gathered: dict[str, dict] = {}
    for document_id, text in pages.items():
        for one in readings("\n".join(text)):
            standing = gathered.setdefault(one.name, {"name": one.name, "documents": 0,
                                                      "labels": [], "lines": [], "shape": one.shape,
                                                      "found_on": set()})  # fmt: skip
            # Documents and not readings. A discharge summary prints the treating doctor twice,
            # once under the summary and once under the recommendations, and counting readings
            # said two documents where there is one — the seventh entry calls a count that
            # disagrees with another count on the same page a defect rather than a detail.
            standing["found_on"].add(document_id)
            standing["documents"] = len(standing["found_on"])
            if one.label not in standing["labels"]:
                standing["labels"].append(one.label)
            if one.line not in standing["lines"]:
                standing["lines"].append(one.line)
    for standing in gathered.values():
        del standing["found_on"]  # which documents is the page's question, not this count's
    # The commonest first, because the doctor somebody is looking for is the one they saw often.
    return sorted(gathered.values(), key=lambda one: (-one["documents"], one["name"]))
