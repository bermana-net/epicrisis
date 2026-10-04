"""The page of doctors and clinics: what it shows, and what each of its four presses does.

`who_view` **shows**: the names each document prints, the groups a person has settled, what a
model has offered and nobody has answered, what has been refused, and the families the word count
proposes. It gathers and counts; it joins nothing.

`joined`, `declined`, `reconsidered` and `separated` **apply a press**. Each hands back a
`Decided` — what was stored and what was refused — as a value rather than printing or
redirecting, so that a test can ask a press what it did instead of reading it out of HTML.

Which archive comes in as a value with no default of its own, and for this page that is not a
convention: this is the page the leak was found on. The four forms carried the kind, the
spellings and the label and said nothing at all about whose spellings they were, so each of them
wrote into whichever archive happened to be open when the press landed. So the archive is in the
address the form posts to and is checked against the one reading of the list this request was
decided by — the door `_the_archive_that_was_drawn` below, which asks `the_open_archive`, the one
place in `web/app.py` that every page which writes goes through. It is handed in rather than
reached for, the way `settings_pressed` is handed the building of the indexes: a door answered in
two places is a door answered two ways, and that is how this went wrong.

Nothing here knows about `request`, `templates` or FastAPI. The routes in `web/app.py` are the
shells, and they draw a `Decided`.

It shows printed names and counts of them, and settles nothing a person did not settle.
"""

from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from epicrisis import doctors_in_text, people
from epicrisis import query as query_index
from epicrisis.query import IndexMissing, open_index
from epicrisis.sources import Source, TheArchives

#: Said to a press whose archive is not the one that is open. Not "there is no such archive": the
#: archive is on this list and has simply been switched, which is what the rest of the sentence
#: goes on to explain.
NOT_THIS_ARCHIVE = ("That was a decision about an archive other than the one open now, so "
                    "nothing was changed. This page was drawn before the archive was switched.")  # fmt: skip

#: The names of the two kinds in a sentence. The program's own words are `doctor` and
#: `institution`; these are what a page prints for them, in one place rather than in four
#: conditionals down a template.
IN_WORDS = {"doctor": ("doctor", "doctors", "a doctor"),
            "institution": ("institution", "institutions", "an institution")}  # fmt: skip


def what_the_page_holds(kind: str, names: int, counted: dict, in_the_text: int = 0) -> str:
    """How many names this tab shows, off how many documents, out of how many this archive holds.

    **This replaces a promise.** The heading read "every institution and every doctor named on
    these documents", and the owner read it as what it says: he looked here for a doctor he had
    seen, did not find him, and concluded the archive did not hold him. Twice, with two
    surnames. What
    this page actually shows is the names that were read into the provider and the doctor field of
    a document — measured on his archive, the doctor field is filled on 20 of its 414 documents,
    while 38 documents carry a labelled surname in their transcribed text, 20 distinct names, that
    is in no field at all and cannot reach this page. Why those twenty are not here is a question
    about the reading and not about this page; what this page owes the reader is to stop saying it
    holds them.

    So the heading says the three numbers instead, and the last sentence says which names are
    missing rather than how many, because how many is the one thing nothing here can count: a name
    that was never read is a name nothing knows the number of. It stands where the promise stood —
    the first line under the heading, on both tabs — and not in a note at the foot, because the
    promise was not at the foot either.

    The first number is the length of the list this page draws under it, handed in rather than
    counted again, so the sentence and the list cannot disagree (§7). The other two come off the
    index, over the same documents the list is gathered from: `query.how_many_name_them`.
    """
    one, many, a_name = IN_WORDS.get(kind, IN_WORDS["doctor"])
    whole, naming = int(counted.get("documents") or 0), int(counted.get(kind) or 0)
    held = f"{whole} document" + ("" if whole == 1 else "s")
    if not whole:
        return "This archive holds no documents yet."
    if not names or not naming:
        return f"None of the {held} of this archive names {a_name}."
    counted_names = f"{names} {one if names == 1 else many}"
    rest = whole - naming
    if not rest:
        return f"{counted_names}, read off every one of the {held} of this archive."
    said = f"{counted_names}, read off {naming} of the {held} of this archive."
    rest_of_it = f"The other {rest} {'prints' if rest == 1 else 'print'} no {one} that was read"
    if not in_the_text:
        return (f"{said} {rest_of_it}: a name standing only inside a document's own text is not "
                f"on this page.")
    # The last clause used to end "is not on this page", and that was true until the reading out
    # of stored text put such names on it. A sentence that goes on saying what the page used to do
    # is the promise this whole sentence replaced, made a second time — so the count moves with
    # the page, and the number is the length of the list drawn below rather than a second reading
    # of anything (§7).
    return (f"{said} {rest_of_it} into a field. A further {in_the_text} "
            f"{'name' if in_the_text == 1 else 'names'} {'stands' if in_the_text == 1 else 'stand'} "
            f"only inside the documents' own text, read out of it below and filled in nowhere.")


def who_view(data_dir: Path, the_archive: str | None, *, kind: str = "doctor",
             trouble: str = "") -> dict:  # fmt: skip
    """Who made these documents: institutions and doctors, as each document prints them.

    A cut of the archive nobody could take before the doctor had a field of their own: until
    then a person's name sat where the institution goes, and the two could not be told apart.

    Two tabs, and under each the names this program thinks are one and the same, for a person
    to join or to leave alone. It proposes and never joins: two doctors of one surname and one
    initial work in two clinics of every city.

    Which archive these names are printed on goes into the four forms this page draws, because
    a press arrives minutes after the page does. See `_the_archive_that_was_drawn`.
    """
    kind = kind if kind in people.KINDS else "doctor"
    # Decided once and carried, rather than asked again at each of the three places below:
    # the names on the page, the groups laid over them and the archive the forms post to have
    # to be of one person, and three readings of sources.json are three chances for them not
    # to be.
    showing = the_archive
    empty = {"current": "who", "makers": [], "kind": kind, "proposals": [], "groups": [],
             "thought": [], "refused": [], "trouble": trouble, "elsewhere": None,
             "archive": showing or "", "holds": "", "in_the_text": [],
             "where_it_came_from": doctors_in_text.WHERE_IT_CAME_FROM}  # fmt: skip
    try:
        connection = open_index(data_dir, showing)
    except IndexMissing:
        return empty
    with closing(connection):
        groups = people.load(data_dir, showing)
        makers = query_index.who_made_them(connection, groups)
        here = [one for one in makers if one["what"] == kind]
        # The other tab, when this one is empty and that one is not. The menu item reads
        # "Doctors and clinics" and opens on kind=doctor, and a folder of laboratory printouts
        # names the laboratory on every page and the person who signed on none — so a person
        # pressing it landed on "No document here names a doctor yet" with every name in the
        # archive one tab away and nothing on the page saying so.
        #
        # Said here rather than mended by opening whichever tab has something: the dead end is
        # at the explicit address too, which a bookmark, a link from the timeline and this
        # page's own redirect after a join all use, and a default tab would leave every one of
        # those exactly as it was. /who?kind=doctor also has to go on meaning the doctors.
        beside = [one for one in makers if one["what"] != kind]
        if not here and beside:
            other = next(one for one in people.KINDS if one != kind)
            empty["elsewhere"] = {"kind": other, "count": len(beside)}
        # The doctors the documents name in their own text and no field of the index holds. The
        # owner looked on this page for two of his own doctors, found neither, and concluded the
        # archive did not hold them — it held them in the text all along, because the field for a
        # doctor was added after these archives were read. The ninth entry: what the program has
        # come to want it takes out of the text it already keeps, and never by reading again.
        #
        # Doctors only. An institution is printed on the letterhead, which the reading already
        # has, and there is no label beside a signature for a hospital to stand under — so there
        # is nothing here the institutions tab could be offered, and offering it an empty list
        # would be a heading promising something again.
        #
        # Names the index already read are left out rather than listed twice: this list is what
        # cannot reach the page any other way, and a name standing in both places is already
        # below, counted off its field, with no need of a second row saying the same thing.
        standing_already = {one["name"] for one in here} | {
            name for group in people.settled(groups, kind) for name in group.names}
        in_the_text = ([one for one in doctors_in_text.who_stands_in_the_text(connection)
                        if one["name"] not in standing_already]
                       if kind == "doctor" else [])  # fmt: skip
        settled = people.settled(groups, kind)
        # What a model offered and nobody has answered. Shown with the sentence it wrote: a
        # person is being asked to say that two human beings are one, and "a model thought so"
        # is not a reason anybody can weigh.
        thought = people.waiting(groups, kind)
        asked = {frozenset(one.names) for one in thought}
        # And what he has already said is not one. Shown under a heading of its own with a way
        # to take it back: a refusal nothing could undo is the same dead end turned round.
        said_no = people.refused(groups, kind)
        return {
            **empty,
            # What this tab holds, in numbers, where the promise used to be. Counted off the one
            # connection this page already has open and over the documents `here` was gathered
            # from, so there is no second reading of anything to disagree with the first.
            "holds": what_the_page_holds(kind, len(here), query_index.how_many_name_them(connection),
                                         in_the_text=len(in_the_text)),
            "makers": here,
            "in_the_text": in_the_text,
            "groups": settled,
            "thought": thought,
            "refused": said_no,
            # A family at a time, not a pair. One laboratory on a real archive writes itself
            # five ways — its own name, the name with its software, the software with a
            # version, the version with a point release, the branch and the city — and offered
            # as pairs that is ten rows about one laboratory, where pressing any one of them
            # leaves the other nine standing. The owner read it as the joining not having
            # worked, which is exactly what it looked like.
            #
            # A family is a question unless this person has already answered this one. They have
            # answered it when all of it is one group they settled — and that, and not "every
            # name of it is settled somewhere", is the question. The difference is the whole of
            # the second finding here: a group appears on this page as its label, so two groups
            # standing for one doctor were a family every name of which was settled, and this
            # list dropped it without a word. Two settled groups were therefore never once
            # offered against each other, and nothing on the page asked. join() has absorbed a
            # settled group holding any of the names since the day it was written, so the
            # machinery to merge two groups was there and only the offering was missing.
            #
            # It skipped a family that so much as touched a settled name once, too, which was
            # right while a family came as one button over all of it and wrong the moment a
            # person could untick a spelling — the one they unticked, standing beside the group
            # they had just made, was never offered again.
            #
            # Nor one a model has already put on this page — the same claim twice, once with a
            # reason and once without, is a page that teaches a person to stop reading. Nor one
            # that has been answered with "not these", which is what made this page a circle:
            # separating a group put the family straight back into this list, and there was no
            # way at all of saying no to a family the word count had counted. A refusal between
            # two groups is remembered by the same three functions and in the same record as a
            # refusal between two spellings, because the names it is about are the two labels:
            # there is one way of remembering "no" here and it did not need a second.
            #
            # **What is compared is the labels, and not every spelling of one group against every
            # spelling of the other.** Three reasons, and the third decides it. The label is the
            # name the person chose to stand for the group, so it is the name this page draws and
            # the only one of them a reader sees. The spellings a group holds are exactly the odd
            # ones — an abbreviation, a bare surname, a branch, a version — and those are what
            # stand inside another name by accident, which is the false pair the word count is
            # already warned about on this page. And §4: a page may put a pair in front of a
            # person only where it can show that it is wrong, and two labels that look alike can
            # be weighed by anyone reading them, while two groups paired through a spelling
            # neither label shows would be a question with its reason hidden.
            # A name read out of the text is offered against the names of the fields by the same
            # word count, through the same four presses, and `people.join` writes it with the same
            # hand. That is the whole of how such a reading ever takes effect: the fourth entry
            # forbids a program settling that two names are one person, and nothing here settles
            # it — the pair goes in front of somebody with both printed lines beside it, and they
            # press. What is new is only that one of the two spellings now reaches the page at all.
            "proposals": [_a_family_to_offer(groups, kind, family)
                          for family in people.families(kind, [one["name"] for one in here]
                                                       + [one["name"] for one in in_the_text])
                          if not people.already_one(groups, kind, family)
                          and not people.says_no_to(groups, kind, family)
                          and not any(set(family) <= set(names) for names in asked)],  # fmt: skip
        }  # fmt: skip


@dataclass(frozen=True)
class Offered:
    """One family this page offers to join, and what a press over it would really join.

    `names` is what the tick boxes carry: the names as this page draws them, which for a group the
    person has settled is its label. `under` says what each of those labels stands for, so the
    spellings inside a group sit on the page beside it — §4 asks that a page which puts a pair in
    front of somebody can show when it is wrong, and a label on its own shows nothing.

    `said` is the heading over them. It exists because the heading read "N spellings that look like
    one name" over a family in which one name stood for a group of five: the press would have
    joined six spellings while the page claimed two, and §7 calls a count that disagrees with
    another count on the same page a defect rather than a detail.
    """

    names: tuple[str, ...]
    #: The spellings under each name that is the label of a settled group. Empty for a family of
    #: loose spellings, which is most of them.
    under: dict[str, tuple[str, ...]]
    #: How many printed spellings one press over this family would join.
    spellings: int

    @property
    def said(self) -> str:
        """What this family is, counted, in the heading above the tick boxes."""
        if not self.under:
            return f"{len(self.names)} spellings that look like one name"
        groups = len(self.under)
        return (f"{len(self.names)} names that look like one — {groups} of them "
                f"{'a group' if groups == 1 else 'groups'} you joined, "
                f"{self.spellings} printed spellings in all")  # fmt: skip


def _a_family_to_offer(groups: list[people.Group], kind: str, family: list[str]) -> Offered:
    """One row of "Look like one and the same", with what the press over it would join."""
    standing = people.standing_for(groups, kind, family)
    under = {one.label: tuple(one.names) for one in standing}
    # A name that is nobody's label is one printed spelling; a label is as many as its group holds.
    return Offered(names=tuple(family), under=under,
                   spellings=sum(len(names) for names in under.values())
                             + len([name for name in family if name not in under]))  # fmt: skip


@dataclass(frozen=True)
class Decided:
    """What one press on this page came to: what was stored, what was refused, and where to.

    `stored` and `refused` are the two halves of one sentence, the way they are on the settings
    page, and both are values here for the same reason: a press that wrote nothing can be asked
    whether it wrote nothing, rather than having it read out of the page it redirected to. The
    presses that guard this archive's own file of decisions are the ones where that matters most.

    `a_dead_end` is the one answer that is not the page again: a press about an archive other
    than the one open now. The route draws it, because what a dead end looks like is the route's
    business and what it says is this module's.

    `kind` is the tab the page comes back on, and it is the word the press itself carried — a
    press that asked about something which is neither a doctor nor an institution comes back on
    the doctors.
    """

    kind: str
    stored: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()
    a_dead_end: bool = False

    @property
    def said(self) -> str:
        """What was in fact written, in a person's words."""
        return ", ".join(self.stored)

    @property
    def trouble(self) -> str:
        """Why a press did nothing, in a person's words. Empty where it did something."""
        return " ".join(self.refused)


#: Said to a press that asked about neither of the two kinds this page knows.
NOT_A_KIND = ("That asked about something which is neither a doctor nor an institution, so "
              "nothing was changed.")  # fmt: skip

#: Which archive a press is about: the one in the address, while it is the one that is open.
#: `web/app.py` holds the single answer and hands it in; see this module's own first paragraph.
TheDoor = Callable[[TheArchives, str], Source | None]


def _the_archive_that_was_drawn(archives: TheArchives, source_id: str, kind: str,
                                the_open_archive: TheDoor) -> Source | Decided:  # fmt: skip
    """The archive a press on the page of doctors and clinics was made about, or a dead end.

    The four forms of that page carried the kind, the spellings and the label, and said
    nothing at all about whose spellings they were — so each of them wrote into whichever
    archive happened to be open when the press landed, which is not the archive the names
    were read off. Three ordinary acts reach it and none of them is unusual: draw the page of
    one archive, switch the archive with the picker that stands in the bar of every page,
    press Join on the page still open. What that wrote was a group of one person's printed
    spellings settled inside another person's own file of decisions, labelled as the first
    archive prints it — and the second person's page then listed the first person's
    laboratory under their own name, beneath a line reading "as printed on the documents
    themselves". That is the first entry of the constitution twice over, and it is the exact
    shape of the failure that entry was written for.

    So the archive is in the address the form posts to, and checked here against the one that
    is open, which is the door `POST /documents/{source_id}/…/date` and
    `POST /review/{source_id}/judge` already go through. A press for another archive is a
    dead end naming the cause rather than an answer about somebody.
    """
    source = the_open_archive(archives, source_id)
    if source is None:
        return Decided(kind=kind, refused=(NOT_THIS_ARCHIVE,), a_dead_end=True)
    return source


def _off_the_form(name: str) -> str:
    """A name or a label as the archive holds it, undoing what the browser did to its line break.

    Every press on this page sends names back to be looked up by what they say, and the browser
    is required to rewrite a lone line feed inside a form value as a carriage return and a line
    feed. A name printed across two lines of a form therefore arrives as a name no document
    carries. See people.a_printed_name for the closed circle that made here. This is the one
    place the page undoes it, because this is the one place a name arrives off a form.
    """
    return people.a_printed_name(name)


def joined(data_dir: Path, archives: TheArchives, source_id: str, *, the_open_archive: TheDoor,
           kind: str = "doctor", one: str = "", other: str = "", label: str = "",
           names: Sequence[str] = ()) -> Decided:  # fmt: skip
    """Say that these printed names are one doctor, or one institution. Undone by one press too.

    Two names come as `one` and `other`, from the pairs the word count offers; a model's group
    may hold three or four and comes as `names`. Both arrive here, because what is being said
    is the same thing either way.

    A press that joins nothing says so on the page it returns to. It used to return in
    silence: one spelling ticked out of five looked exactly like a join that had worked, and
    the only way to find out it had not was to read the list underneath.
    """
    if kind not in people.KINDS:
        return Decided(kind="doctor", refused=(NOT_A_KIND,))
    source = _the_archive_that_was_drawn(archives, source_id, kind, the_open_archive)
    if isinstance(source, Decided):
        return source
    wanted = [_off_the_form(name) for name in names if name] or [_off_the_form(name) for name in (one, other) if name]
    try:
        people.join(data_dir, source.id, kind, wanted, _off_the_form(label) or None)
    except people.NotAJoin as not_one:
        return Decided(kind=kind, refused=(f"{not_one.said} Nothing was changed. {not_one.mend}",))
    return Decided(kind=kind, stored=(f"{len(wanted)} spellings joined as one {kind}",))


def declined(data_dir: Path, archives: TheArchives, source_id: str, *, the_open_archive: TheDoor,
             kind: str = "doctor", names: Sequence[str] = ()) -> Decided:  # fmt: skip
    """Say no, whoever asked. The spellings stand as the forms print them, and are not offered
    again until the refusal is taken back.

    The button existed under what a model offered and nowhere else, so a family the word count
    had counted could only be joined or left alone — and left alone it came back on every draw
    of the page, for ever. The ticked boxes are what is refused, so unticking one before this
    says no to the rest and leaves that one its own question.
    """
    if kind not in people.KINDS:
        return Decided(kind="doctor", refused=(NOT_A_KIND,))
    source = _the_archive_that_was_drawn(archives, source_id, kind, the_open_archive)
    if isinstance(source, Decided):
        return source
    wanted = [_off_the_form(name) for name in names if name]
    try:
        people.decline(data_dir, source.id, kind, wanted)
    except people.NotAJoin as not_one:
        return Decided(kind=kind, refused=(f"{not_one.said} Nothing was changed. {not_one.mend}",))
    return Decided(kind=kind, stored=(f"{len(wanted)} spellings said not to be one {kind}",))


def reconsidered(data_dir: Path, archives: TheArchives, source_id: str, *,
                 the_open_archive: TheDoor, kind: str = "doctor",
                 names: Sequence[str] = ()) -> Decided:  # fmt: skip
    """Take a refusal back, so the page may offer these spellings again."""
    if kind not in people.KINDS:
        return Decided(kind="doctor", refused=(NOT_A_KIND,))
    source = _the_archive_that_was_drawn(archives, source_id, kind, the_open_archive)
    if isinstance(source, Decided):
        return source
    wanted = [_off_the_form(name) for name in names if name]
    if len(wanted) >= 2:
        people.reconsider(data_dir, source.id, kind, wanted)
        return Decided(kind=kind, stored=(f"a refusal of {len(wanted)} spellings taken back",))
    return Decided(kind=kind)


def separated(data_dir: Path, archives: TheArchives, source_id: str, *, the_open_archive: TheDoor,
              kind: str = "doctor", label: str = "") -> Decided:  # fmt: skip
    """Take a group apart again, by the label it was settled under."""
    # The kind the dead end offers a way back to is one of the two this page has; the kind the
    # press itself carried is what `people.split` is asked about and what the page comes back
    # on. The two are not the same word, and were not before this moved either.
    source = _the_archive_that_was_drawn(archives, source_id, kind if kind in people.KINDS else "doctor",
                                         the_open_archive)  # fmt: skip
    if isinstance(source, Decided):
        return source
    label = _off_the_form(label)
    if label:
        people.split(data_dir, source.id, kind, label)
        return Decided(kind=kind, stored=(f"the group under “{label}” taken apart",))
    return Decided(kind=kind)
