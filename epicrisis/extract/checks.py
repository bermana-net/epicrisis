"""What the checks of the extract step actually do, one function per kind.

The checks live here and the kinds in `rules/kinds.py` only name them, which is the rule this
project works by: a rule file holds no code, a kind holds no logic, and the doing belongs to the
module that owns the decision. The decision these own is **whether a transcription looks
finished** — never whether a value is right, what it means, or what to do about it.

They are the only checks in the program that cost money when they fire. Each one, firing, sends
the document back to a stronger model: 181 documents were read again because of
`unreadable_on_images`, 118 because of `letters_in_numeric_value_on_image`, 57 because of
`value_not_in_own_page_text`. That is why they are rules at all — until they were, the owner
paying per document could not turn off a check that was escalating their forms for nothing.

Every one of them takes the subject every other rule of a document takes (`subjects.Document`)
and gives back a list of what it found. The length of that list is the count; nothing in it is
ever shown to anybody, because what these report is this program's reading of a page and not
anything about the person whose page it is.
"""

from epicrisis.printed_values import number_tokens, squeezed, typewriter_digits


def _transcribed(document) -> dict[int, str]:
    """The text that came back for each page of this document."""
    return {item["page"]: item["text"] for item in document.item["page_texts"]}


def _is_empty(text: str, settings: dict) -> bool:
    return len(text.strip()) < settings["least_characters"]


def _is_short(text: str, sent: str, settings: dict) -> bool:
    """Much less text back than went out, on a page long enough for a share of it to mean anything."""
    return (len(sent.split()) > settings["words_before_asking"]
            and len(text.split()) < settings["least_share"] * len(sent.split()))  # fmt: skip


def pages_with_no_text(document, settings: dict) -> list[int]:
    """Pages of the document whose transcription is empty or nearly so.

    A model can stop early and still write correct fields for the part it did read, so the
    document comes back looking complete. This is the plainest way that shows.
    """
    if document.item is None:
        return []
    transcribed = _transcribed(document)
    return [page for page in document.item["pages"] if _is_empty(transcribed.get(page) or "", settings)]


def pages_much_shorter_than_the_page(document, settings: dict) -> list[int]:
    """Pages that went as text and came back as much less text than was sent.

    **Asked of every page, including ones the check above already reports.** It used to skip them,
    and the skip was written here as "reporting it twice would send one document back for one
    fault counted two ways" — which is not what happens: a document goes back to a stronger model
    if *anything* was found, so a page named by two checks costs exactly what a page named by one
    costs. What the skip did cost was a hole. It re-derived "already reported as empty" from a
    copy of the other check's threshold, and the two are stored separately per archive: raise one
    and leave the other, and a page of thirty characters is **not empty** to the check above and
    **already reported** to this one, so nothing reports it at all. Three copies of one number
    made a partition that only held while all three were equal, and nothing anywhere said when
    they stopped being.

    So each rung of the ladder now asks its own question with its own threshold, and nothing here
    reads another check's number. A page can be named by two of them, which reads as what it is —
    the page came back empty *and* much shorter than it was sent.
    """
    if document.item is None:
        return []
    transcribed, sent = _transcribed(document), document.sent_texts or {}
    return [page for page in document.item["pages"]
            if page in sent and _is_short(transcribed.get(page) or "", sent[page], settings)]  # fmt: skip


def pages_whose_numbers_are_missing(document, settings: dict) -> list[int]:
    """Pages whose transcription does not hold the numbers the page prints.

    The words of a result can be written again from anywhere; the numbers are the part that
    cannot. Asked of every page that prints enough numbers for their absence to mean something,
    and of nothing else: the two checks above are not consulted, for the reason written out in
    the one before this — a rung that re-derives the rung before it from a copy of its threshold
    is a rung that lets a page through the moment the two copies differ.
    """
    if document.item is None:
        return []
    transcribed, sent = _transcribed(document), document.sent_texts or {}
    found = []
    for page in document.item["pages"]:
        text = transcribed.get(page) or ""
        if page not in sent:
            continue
        numbers = number_tokens(sent[page])
        if len(numbers) < settings["numbers_before_asking"]:
            continue
        as_read = squeezed(typewriter_digits(text))
        kept = sum(1 for number in numbers if squeezed(number) in as_read)
        if kept < settings["least_number_share"] * len(numbers):
            found.append(page)
    return found


def table_pages_without_values(document, settings: dict) -> list[int]:
    """Pages classification said carry a table of results, and from which nothing was stored.

    Of laboratory results only. Reports, letters and prescriptions print tables inside their text
    all the time, and a model reading one as prose has done nothing wrong.
    """
    if document.item is None or document.item["doc_type"] not in settings["of_document_types"]:
        return []
    with_values = {item["provenance"]["page"] for item in document.item["observations"]}
    return [page for page in document.tabular_pages if page not in with_values]


#: The printed fields of a document's head: what the form says it is and who printed it. They are
#: named here rather than inside each check because both checks below read the same two, and a
#: third field added to a transcription's head should reach them together or not at all.
#:
#: It said that and nothing read it: one check wrote the pair out as two literals and the other
#: took it from a setting whose default was the same pair a third time, in `rules/kinds.py`. A
#: constant with a docstring about a guarantee and no readers is worse than no constant — it is
#: the shape of a defence, and this project has now found three of them. Both read it now, and the
#: kind's default is this tuple, so a third printed field reaches the two checks together.
THE_HEAD_OF_A_DOCUMENT = ("provider_as_printed", "title_as_printed")


def the_provider_reads_like_a_person(document, settings: dict) -> list[str]:
    """The institution field holding what looks like a person's name.

    A small model takes the name under the stamp — "Гриценко С.А.", "проф. Дорошенко Д.Г." — and
    writes it as the laboratory; the strong model reads the letterhead. What counts as looking
    like a person is `suspects.provider_looks_like_a_person`, which is the one place in the
    program that answers it, and it is asked with the title as well: the two fields are swapped
    often enough that the title is what tells a swap from a form that really prints only a doctor.
    """
    from epicrisis.suspects import provider_looks_like_a_person

    if document.item is None:
        return []
    whose, what = THE_HEAD_OF_A_DOCUMENT
    return [whose] if provider_looks_like_a_person(
        document.item.get(whose), document.item.get(what)) else []  # fmt: skip


def words_in_two_alphabets(document, settings: dict) -> list[str]:
    """Fields of the head holding a word written in both alphabets at once, as in "Кліnіка".

    A name may hold words of each — "Клініка VITAMED" is two words and two alphabets and nothing
    is wrong — but one word holding both is a letter read from the wrong one.

    One hit per field and never per word, which is what the check it replaces counted: a title
    with four such words is one field read wrongly, and a document is sent back to a stronger
    model once either way.
    """
    from epicrisis.printed_values import mixed_script_words

    if document.item is None:
        return []
    return [field for field in settings["of_fields"] if mixed_script_words(document.item.get(field))]


def _the_text_of(document, page: int) -> str:
    """The text this page is judged against: what was sent where it went as text, the model's own
    reading where it went as an image.

    One page, one source, and which of the two it is decides the name of every check below that
    reads it. A page that went as text is the page itself; a page that went as an image is a
    reading of it, and comparing a reading with itself is a weaker question — which is why the
    codes stay apart.
    """
    sent = document.sent_texts or {}
    if page in sent:
        return sent[page]
    return "\n".join(text["text"] for text in document.item["page_texts"] if text["page"] == page)


def _went_as_text(document, page: int) -> bool:
    return page in (document.sent_texts or {})


def _as_digits(text: str | None) -> str:
    """Digits compared the way the rest of the program compares them: spacing gone, and a figure
    typed in one alphabet the same as the same figure typed in another."""
    return squeezed(typewriter_digits(text or ""))


def values_not_on_their_page(document, settings: dict) -> list[dict]:
    """Values that are nowhere in the text of the page they claim to come from.

    Only pages that went **as text**, and only pages of real text: the text of a text-layer page
    is the page itself, not a reading of it, so a number that is not in it was not printed there —
    whether a model misread the layout or the page told it what to write. A scan's text is the
    model's own transcription and says nothing either way; a page of a few words says nothing
    either.

    This is the one check of the extract step whose finding a person is shown, under its own name
    and with its own words about what to do. The rest are the step reporting on its own reading.
    """
    if document.item is None:
        return []
    found = []
    for item in document.item["observations"]:
        page = item["provenance"]["page"]
        if not _went_as_text(document, page):
            continue
        text = _the_text_of(document, page)
        printed = (item.get("value_as_printed") or "").strip()
        if len(text.split()) < settings["words_before_asking"] or not printed:
            continue
        if settings["skip_qualitative"] and item.get("value_kind") == "qualitative":
            continue
        if _as_digits(printed) not in _as_digits(text):
            found.append(item)
    return found


def _values_not_in_the_text(document, *, as_text: bool) -> list[dict]:
    """Values whose printed form is not in the page's text at all, on the pages of one kind."""
    if document.item is None:
        return []
    return [item for item in document.item["observations"]
            if _went_as_text(document, item["provenance"]["page"]) is as_text
            and _as_digits(item["value_as_printed"]) not in _as_digits(_the_text_of(document, item["provenance"]["page"]))]  # fmt: skip


def values_not_in_the_page_text(document, settings: dict) -> list[dict]:
    """On pages that went as text: the page itself does not hold this value."""
    return _values_not_in_the_text(document, as_text=True)


def values_not_in_the_models_own_text(document, settings: dict) -> list[dict]:
    """On pages that went as images: the model's own transcription does not hold the value it
    stored from that page. It disagrees with itself, which is the strongest thing a reading of a
    scan can say about itself without another reading."""
    return _values_not_in_the_text(document, as_text=False)


def _references_not_in_the_text(document, *, as_text: bool) -> list[dict]:
    """Printed ranges whose numbers are not all on the page.

    Number by number and never as one piece: a range is printed over several lines or columns —
    norms for men and women, norms by age — and the joined text of it appears nowhere.
    """
    if document.item is None:
        return []
    from epicrisis.printed_values import numbers_in_text

    found = []
    for item in document.item["observations"]:
        page = item["provenance"]["page"]
        if _went_as_text(document, page) is not as_text or not item.get("reference_as_printed"):
            continue
        if not numbers_in_text(item["reference_as_printed"], _the_text_of(document, page)):
            found.append(item)
    return found


def references_not_in_the_page_text(document, settings: dict) -> list[dict]:
    """On pages that went as text: the printed range is not on the page."""
    return _references_not_in_the_text(document, as_text=True)


def references_not_in_the_models_own_text(document, settings: dict) -> list[dict]:
    """On pages that went as images: the printed range is not in the model's own transcription."""
    return _references_not_in_the_text(document, as_text=False)


def letters_in_a_numeric_value_on_an_image(document, settings: dict) -> list[dict]:
    """A value stored as a number whose printed form carries letters nothing explains.

    Only pages that went as images. On a text page the comparison above is exact and the letters
    beside a number are printed ones — "Normal", "neg" — read from the page as they stand; on a
    scan they are as likely to be the reading's own.
    """
    if document.item is None:
        return []
    from epicrisis.printed_values import unexplained_letters

    return [item for item in document.item["observations"]
            if not _went_as_text(document, item["provenance"]["page"])
            and item.get("value_numeric") is not None
            and unexplained_letters(item["value_as_printed"])]  # fmt: skip


def comparators_not_printed(document, settings: dict) -> list[dict]:
    """A comparator stored against a value whose printed form carries none.

    A comparator is a sign or a word the form printed beside the number — `<`, `>`, "less than" —
    and never a comparison the reading made with the range beside it. Stored without being
    printed, it is the second kind.
    """
    if document.item is None:
        return []
    from epicrisis.printed_values import comparator_printed

    return [item for item in document.item["observations"]
            if item.get("comparator") and not comparator_printed(item["value_as_printed"])]  # fmt: skip


def rows_of_several_values_without_a_heading(document, settings: dict) -> list[str]:
    """One row printing several values and no column heading anywhere in the document.

    Headings matter where a row prints more than one value: they are what tells the result from
    the rest of the row. Many forms print one value per row and no headings at all, and that is
    not a problem.

    **A row, and never a page.** This once counted a name appearing twice anywhere on the page,
    which is not a row of several values — it is a measurement printed in two places, which any
    long report does. On an archive read on 2 October it fired on four documents where no name
    repeated inside any row at all, and each of those was read a second time by the costliest
    model to answer a complaint about a table that was not there. What tells one row from another
    is the piece of the original line kept beside every value.
    """
    if document.item is None:
        return []
    from collections import Counter

    values = document.item["observations"]
    rows = Counter((item["provenance"]["page"], squeezed(item["provenance"].get("snippet")),
                    squeezed(item["name_as_printed"])) for item in values)  # fmt: skip
    if any(count > 1 for count in rows.values()) and not any(item.get("column_as_printed") for item in values):
        return ["this document"]
    return []


def dates_that_are_a_birth_date(document, settings: dict) -> list[str]:
    """A date printed as the document's own that is somebody's date of birth on the same page.

    A form prints a birth date beside the patient's name, and a reading that takes it as the date
    of the study files the whole document decades out of place — in the archive, on the chart, and
    in every answer about when something happened.
    """
    if document.item is None:
        return []
    from epicrisis.dates import birth_dates, read_printed_date, same_date

    head = document.item
    language = head.get("language")
    texts = [*(document.sent_texts or {}).values(), *(item["text"] for item in head["page_texts"])]
    births = [birth for text in texts for birth in birth_dates(text, language)]
    found = []
    for field in settings["of_dates"]:
        printed = read_printed_date(head.get(field), language)
        if any(same_date(printed, birth) for birth in births):
            found.append(field)
    return found


def unreadable_parts_on_pages_that_went_as_images(document, settings: dict) -> list[str]:
    """The reading says part of this document could not be read, and some of it went as an image.

    Where every page went as text there is nothing a second reading would see differently: the
    text layer is the page. Where a page went as an image, "I could not read this" is a thing a
    stronger model may well be able to read, and that is the whole of what this step decides.
    """
    if document.item is None:
        return []
    went_as_text = len(document.sent_texts or {})
    if document.item["unreadable"] and went_as_text < len(document.item["pages"]):
        return ["this document"]
    return []
