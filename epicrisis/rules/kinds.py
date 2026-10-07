"""The kinds of check a rule can be, and the only place a rule's logic ever lives.

A rule file says which kind it is and what to set it to; the doing is here, in the repository,
with a test. There are meant to be few of these and many rules: the same kind of check with
another threshold, another list of words or another set of tests is a new file and no new code.

Every kind is called the same way — `run(subject, settings)` — so a kind declares three things
about itself rather than leaving them to be read out of its code:

- `looks_at`: which subject it is handed. The names and what each one holds are in subjects.py.
- `at`: which step of the program runs it. This is not bookkeeping. A rule at `extract` writes
  into what is stored beside the archive and turning it on can mean reading documents again,
  with a model, for money; a rule at `charts` costs nothing and takes effect on the next page.
  A person flipping a switch has to be told which of those they are flipping.
- `does`: the boundary itself. A kind that `marks` may only say "look at this". A kind that
  `places` may only say where a printed thing belongs — at what scale, in what unit, on what day.
  The day was added when a consultation turned out to quote earlier studies with their own dates
  printed beside them, so that a measurement from January stood on a chart in March; reading that
  date is reading the page, exactly as reading a unit out of a printed range is. Nothing here
  computes a value, judges one, or decides anything for a person (MDCG 2019-11). There is no
  third one.

A kind is added only when a rule genuinely needs something no kind can do. It arrives with its
settings and their defaults, so a rule file naming a setting this kind does not have is refused
rather than quietly ignored.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from epicrisis.extract.checks import THE_HEAD_OF_A_DOCUMENT
from epicrisis.rules.subjects import A_SERIES, LOOKS_AT, ONE_DOCUMENT, ONE_MATERIAL, ONE_VALUE, THE_ARCHIVE

MARKS, PLACES = "marks", "places"
DOES = (MARKS, PLACES)

# What a threshold is, where saying so rules out numbers that are in the type and not in the
# world. Declared per setting as one of these two rather than as a pair of numbers, because every
# bound this program has needed is one of exactly these two shapes, and a name reads where a
# `(1, None)` does not.
#
# **The failure this closes, measured.** A number of the right type and the wrong size was taken
# without a word and the check then never fired once: `least_characters = 0` means no page is ever
# empty, `least_share = 0` means no page is ever short, `-5` the same, and nothing anywhere said
# so — not the page, not `validate`, not the journal. The dangerous half is that these are the
# checks that decide whether a document is read again by a model, so a threshold that quietly
# stops one is a hole in the reading that costs nothing and shows nowhere. A wrong *type* was
# always refused; a wrong size was not, and a wrong size is what a person types.
A_COUNT = "a count"  # a whole number of things, and at least one of them
A_SHARE = "a share"  # more than none of them and at most all of them
WITHIN = (A_COUNT, A_SHARE)
#: What each shape wants, in the words the settings page and a refusal both print.
WITHIN_WORDS = {A_COUNT: "a whole number, one or more",
                A_SHARE: "a share: more than 0 and at most 1"}  # fmt: skip


def out_of_range(shape: str, value) -> str:
    """Why this value is not that shape of threshold, or an empty string. The one place it is asked.

    Takes the value as it comes — the rule file hands a number, the settings page hands what
    somebody typed — and answers about numbers only: a shape is declared for a threshold that is
    one, so anything else here is a type the reader above this has already refused.
    """
    if shape not in WITHIN:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if shape == A_COUNT and number < 1:
        return WITHIN_WORDS[A_COUNT]
    if shape == A_SHARE and not 0 < number <= 1:
        return WITHIN_WORDS[A_SHARE]
    return ""

# The steps of the program a rule can belong to, in the order the pipeline runs them. The last two
# are not steps of the pipeline at all but readings made when a page is drawn or a question
# answered, which is why turning one of those on or off costs nothing and changes nothing stored.
EXTRACT, VALIDATE, INDEX, CHARTS, SUSPECTS = "extract", "validate", "index", "charts", "suspects"


@dataclass(frozen=True)
class Step:
    """What a rule standing at one step of the program means: what it is handed, and what it costs.

    One record per step, because this was three lists and two of them disagreed. One said `extract`
    is the step whose switch has to be confirmed before it takes effect; another said nothing at
    `extract` hands a rule anything, and the decorator below refused every kind that tried to stand
    there. So the confirmation on the settings page could not be reached by any rule this program
    would accept, `rules/README.md` went on offering the mechanism to whoever writes the first
    model-using rule, and the one test that covered it put a kind straight into KINDS and went
    round the decorator — green in the suite and dead in the program, which this project has now
    found four times.

    What a step hands out is the fact everything else follows from. A step that assembles no
    subject runs no rules, so no rule can stand at it, so there is no switch of its to hold back.
    Teaching a step to build a subject and saying so here — in that order — is what revives the
    rest, with nothing else to remember.
    """

    serves: frozenset[str]  # the subjects this step assembles and hands a rule, one by one
    costs: str  # what turning a rule of this step on or off asks of a person, in their own words
    # Whether what a rule of this step finds is acted on by the step itself rather than shown to a
    # person to work through. At `extract` it is: a check that fires sends the document back to a
    # stronger model, and nobody is ever handed the finding — what reaches a person is the
    # summary that `validate` writes, under its own name and with its own words about what to do.
    # So a rule of such a step says nothing about where a finding hangs or what settles it, and
    # the rule file is refused for saying it, because a sentence telling somebody how to settle
    # something they will never be shown is a sentence that will never be read.
    answered_by_the_step: bool = False
    # Whether that cost is one the page has to ask about first rather than store on a click.
    # Documents read again by a model take hours and, on an API key, money, and a switch like that
    # is not one a person should be able to flip by leaning on the mouse.
    asks_first: bool = False


# Which subject each step actually builds and hands to a rule. A kind declaring a pair nobody
# serves used to be accepted and then skipped in silence by every loop of that step: no error, no
# line anywhere, the rule switched on in the settings and finding nothing for ever. Refused where
# the kind is written, rather than discovered by somebody wondering why a rule they turned on
# never fires. Adding a subject to a step means teaching that step to build it first, and then
# writing it here — in that order.
STEPS: dict[str, Step] = {
    # The checks that decide whether a document is read again by a stronger model. This step hands
    # them one document — the transcription that has just come back, the text of the pages that
    # went as text, and which pages carry a table — and a rule of it may only mark: "this reading
    # does not look finished". What happens next is the step's own business and not the rule's.
    #
    # It is the one step whose switches cost money, and the only one where turning a rule *on*
    # can mean reading documents again. The page asks before it stores one.
    # What this costs, measured rather than assumed. It said "Documents are read again by a
    # model", which is the thing a person is afraid of and is not what either press does: a check
    # switched on or off, or a threshold moved, changes what the **next** reading of a document
    # does, and a run over an archive that is already read sends nothing — measured at 0 calls,
    # both directions, on an archive of 23 documents. Reading what is already read again takes
    # `forget` and a full re-read, which is the slowest and costliest thing this program does, and
    # no switch on that page starts it.
    EXTRACT: Step(serves=frozenset({ONE_DOCUMENT}), asks_first=True, answered_by_the_step=True,
                  costs="Changes what the next reading costs: a document read after this may be sent "
                        "to a stronger model, which takes time and, on an API key, money. Nothing "
                        "already read is read again."),  # fmt: skip
    VALIDATE: Step(serves=frozenset({ONE_DOCUMENT, THE_ARCHIVE}),
                   costs="The archive is checked again. No model, seconds, nothing is read again."),
    INDEX: Step(serves=frozenset(),
                costs="The index is built again from what is stored. No model, seconds."),
    CHARTS: Step(serves=frozenset({A_SERIES, ONE_VALUE, ONE_MATERIAL}),
                 costs="Takes effect on the next page. Nothing is stored and nothing is built again."),
    SUSPECTS: Step(serves=frozenset({THE_ARCHIVE}),
                   costs="Takes effect the next time the list is asked for. Nothing is stored."),
}  # fmt: skip


def from_the_table():
    """The five questions the rest of the program asks of the table above, all answered from it.

    Kept as plain values rather than as functions because they are read as values everywhere —
    `AT.index(rule.at)` orders the rules on the settings page — and worked out here so that a test
    can say what the table says and have all four follow.
    """
    at = tuple(name for name, step in STEPS.items() if step.serves)
    served = {name: set(step.serves) for name, step in STEPS.items()}
    costs = {name: step.costs for name, step in STEPS.items()}
    # A step that hands a rule nothing has no rule of its own to hold back, so naming it here
    # would be promising a confirmation that nothing can reach. That is the whole of what the two
    # lists this replaces disagreed about, and it is now one word in one record.
    costly = tuple(name for name, step in STEPS.items() if step.asks_first and step.serves)
    answered = tuple(name for name, step in STEPS.items() if step.answered_by_the_step)
    return at, served, costs, costly, answered


# The steps a rule may stand at, what turning one on or off asks of a person, which of those the
# page has to ask about first, and which of them answer their own rules. All four are the table,
# read.
AT, SERVED, COSTS, COSTLY, ANSWERED_BY_THE_STEP = from_the_table()


@dataclass(frozen=True)
class Kind:
    name: str
    does: str
    at: str
    looks_at: str
    about: str
    settings: dict = field(default_factory=dict)  # name -> default, and the type is the default's
    # What each setting means, in words a person can act on. A threshold nobody can explain is a
    # threshold nobody will ever change, and one changed without understanding is worse.
    means: dict = field(default_factory=dict)
    #: Whether this check has a switch at all. Almost every one does, and should: a check that is
    #: useful on two archives and noise on the third is exactly what the switch is for. The
    #: exception is a check reporting on **this program's own reading** — four of them say a page
    #: came back with nothing on it, and the fifth says a stored value is nowhere in the text of
    #: the page it came from. Neither is a judgement about anybody's data to be called noise, and
    #: `validate.LEFTOVER` has said in writing since before these were rules that such a thing
    #: stays on, "because a switch on them would be a switch that hides a hole in somebody's
    #: archive".
    #:
    #: It had one for nine days. Measured: an archive of 23 documents, every one of them read by
    #: the weak model and every page nearly empty, reports 23 of 23 to check; with two of these
    #: switched off for that archive it reports 19, the whole section leaves the findings page, and
    #: nothing anywhere — not the status page, not the coverage, not the journal, not `validate` —
    #: says the archive has a hole in it. The ledger says done.
    stays_on: bool = False
    #: Which of its settings are a count or a share, by name. A threshold with no shape declared
    #: is checked for its type and nothing else, which is right where there is no honest bound to
    #: give: `apart_by` ships as 0.0 and means it.
    within: dict = field(default_factory=dict)
    run: Callable | None = None

    @property
    def cost(self) -> str:
        return COSTS[self.at]

    def refuses(self, name: str, value) -> str:
        """Why this threshold cannot hold that value, or an empty string. Both writers ask here."""
        return out_of_range(self.within.get(name, ""), value)


KINDS: dict[str, Kind] = {}


def kind(name: str, does: str, at: str, about: str, looks_at: str = A_SERIES,
         settings: dict | None = None, means: dict | None = None, stays_on: bool = False,
         within: dict | None = None):  # fmt: skip
    """Register a kind of check. The function it decorates is what the rules of that kind do."""
    if does not in DOES or at not in STEPS or looks_at not in LOOKS_AT:
        raise ValueError(f"{name}: does={does!r} at={at!r} looks_at={looks_at!r} is not a kind of check that exists")
    if looks_at not in SERVED[at]:
        raise ValueError(
            f"{name}: nothing at the {at} step hands a rule {looks_at!r}. A kind whose subject that step "
            f"does not assemble is not refused anywhere and finds nothing for ever, which looks exactly "
            f"like a rule that is working. What {at} hands out: "
            + (", ".join(sorted(SERVED[at])) or "nothing at all — no step of the program assembles a "
               "subject there yet, and teaching it to is where a kind at this step begins")
        )
    # Every threshold says what it means, or it cannot be offered to anybody to change.
    if set(settings or {}) != set(means or {}):
        raise ValueError(f"{name}: every setting needs a line saying what it means, and only those")
    for named, shape in (within or {}).items():
        if named not in (settings or {}):
            raise ValueError(f"{name}: there is no setting called {named!r} to give a shape to")
        if shape not in WITHIN:
            raise ValueError(f"{name}: {named} is {shape!r}, and a threshold is {' or '.join(WITHIN)}")

    def keep(run: Callable) -> Callable:
        KINDS[name] = Kind(name=name, does=does, at=at, looks_at=looks_at, about=about,
                           settings=settings or {}, means=means or {}, stays_on=stays_on,
                           within=within or {}, run=run)  # fmt: skip
        return run

    return keep


# Said once and shared, because the same threshold means the same thing wherever it appears.
WEIGHT = "How much the list should care when this one fires. The heaviest signals lift a document to the top of it."
LEAST_HISTORY = "How many readings of a test there must be before its habits mean anything at all."


@kind(
    "value-against-its-printed-range",
    does=PLACES,
    at=CHARTS,
    looks_at=A_SERIES,
    about="Compares the numbers of one test with the reference ranges printed beside them, to say "
          "which of them are written at another scale.",
    settings={"same_band": 0.15, "bands_to_see_a_scale": 2},
    means={"same_band": "How far from a whole power of ten two printed ranges may sit and still count as one range "
                        "at two scales. 0.15 is about forty per cent either way.",
           "bands_to_see_a_scale": "How many printed ranges it takes before a test can be said to have two scales at all."},
)
def _against_its_printed_range(series, settings: dict) -> list[tuple[int, int]]:
    """The arithmetic is in units.py, which owns what scale a number is on; this only names it."""
    from epicrisis.units import onto_one_scale

    return onto_one_scale(series.numbers, series.bands, **settings)


# The four signals that say a line may have been read wrong. Each is its own kind because each
# asks a different question; what they share is the shape of the answer and a weight, which is
# how much the list should care when one of them fires.


@kind(
    "unit-missing-where-others-have-one", does=MARKS, at=SUSPECTS, looks_at=THE_ARCHIVE,
    about="A value with no unit, on a test whose other forms all print one.",
    settings={"weight": 1, "least_history": 4},
    means={"weight": WEIGHT, "least_history": LEAST_HISTORY},
)  # fmt: skip
def _unit_missing(archive, settings: dict):
    from epicrisis.suspects import unit_missing_where_others_have_one

    return unit_missing_where_others_have_one(archive, settings)


@kind(
    "number-far-from-the-others", does=MARKS, at=SUSPECTS, looks_at=THE_ARCHIVE,
    about="A number many times away from every other reading of the same test, in the same unit "
          "and the same specimen.",
    settings={"weight": 3, "least_history": 4, "times_away": 10},
    means={"weight": WEIGHT, "least_history": LEAST_HISTORY,
           "times_away": "How many times away from the middle of a test a number has to be before it looks "
                         "like a misplaced decimal point rather than a reading."},
)  # fmt: skip
def _number_far(archive, settings: dict):
    from epicrisis.suspects import number_far_from_the_others

    return number_far_from_the_others(archive, settings)


@kind(
    "institution-looks-like-a-name", does=MARKS, at=SUSPECTS, looks_at=THE_ARCHIVE,
    about="An institution recorded as somebody's name or initials: the doctor under the stamp "
          "read as the laboratory.",
    settings={"weight": 3},
    means={"weight": WEIGHT},
)  # fmt: skip
def _institution_is_a_person(archive, settings: dict):
    from epicrisis.suspects import institution_looks_like_a_name

    return institution_looks_like_a_name(archive, settings)


@kind(
    "lab-form-without-a-title", does=MARKS, at=SUSPECTS, looks_at=THE_ARCHIVE,
    about="A laboratory form transcribed with no title at all.",
    settings={"weight": 1},
    means={"weight": WEIGHT},
)  # fmt: skip
def _lab_form_without_a_title(archive, settings: dict):
    from epicrisis.suspects import lab_form_without_a_title

    return lab_form_without_a_title(archive, settings)


# The checks over one transcription. Each imports what it needs inside itself and not at the top
# of this file: validate.py asks the registry which rules to run, so a top-level import here
# would close the circle and neither module would load.

_OVER_ONE_DOCUMENT = {
    "lab-form-with-nothing-in-it": ("A laboratory panel transcribed and holding no values at all.", "lab_without_values"),
    "unreadable-parts": ("Parts of a page the reading itself said it could not make out.", "unreadable_parts"),
    "number-differs": ("A number stored that is not the number printed.", "number_differs"),
    "comparator-missing": ("A < or > printed and not stored, or stored and not printed.", "comparator_missing"),
    "quantitative-without-number": ("A value counted as a number that holds none.", "quantitative_without_number"),
    "reference-reversed": ("A printed range whose lower bound is above its upper one.", "reference_reversed"),
    "row-without-result": ("A row with a unit or a range but nothing that is its result.", "row_without_result"),
    "repeated-value": ("One line of a form transcribed twice.", "repeated_value"),
}


def _over_one_document(name: str, about: str, does_what: str):
    @kind(name, does=MARKS, at=VALIDATE, looks_at=ONE_DOCUMENT, about=about)
    def run(document, settings: dict, _what=does_what):
        from epicrisis import validate

        # A document nobody transcribed has nothing for these to look at. Said once, here,
        # rather than at the top of every one of them.
        return [] if document.item is None else getattr(validate, _what)(document, settings)

    return run


for _name, (_about, _what) in _OVER_ONE_DOCUMENT.items():
    _over_one_document(_name, _about, _what)


@kind(
    "dates-far-apart-in-one-document", does=MARKS, at=VALIDATE, looks_at=ONE_DOCUMENT,
    about="Pages of one document dated far apart: two documents cut into one. A file of plain text "
          "has no page breaks of its own, so where this program cut it in the wrong place two "
          "visits become one document — and the second one's date is the first one's from then on.",
    settings={"apart_by_days": 60},
    means={
        "apart_by_days": "How many days apart the dates of two pages of one document may stand before "
                         "it is reported. A form printing a date of collection and a date of report "
                         "stands days apart and is one document; a year apart is two.",
    },
)  # fmt: skip
def dates_far_apart_in_one_document(document, settings: dict):
    from epicrisis import validate

    return [] if not document.page_dates else validate.dates_far_apart(document, settings)


@kind(
    "range-read-two-ways", does=MARKS, at=VALIDATE, looks_at=ONE_DOCUMENT,
    about="The two readings of one printed range disagree: the numbers the model read off the page, "
          "and the numbers this program reads out of the same printed text.",
    settings={"apart_by": 0.0},
    means={
        "apart_by": "How far the two readings of one printed range may differ before it is reported, as a "
                    "share of the larger number. Nought reports any difference at all; a bound one reading "
                    "has and the other has not is reported whatever this is.",
    },
)  # fmt: skip
def _range_read_two_ways(document, settings: dict):
    """A second opinion on the one thing here that is read by hand.

    The band under a chart comes from a parser: no model, repeatable, and therefore measurable —
    which is why it is a parser. But one reader alone is never wrong out loud, and this one has been
    wrong four times in a day over shapes the archive did not hold yet. The model that transcribed
    the page is asked for the same range as two numbers, which is what it is already asked for the
    value itself, and the two answers are compared. Nothing is chosen by this and no band moves.
    """
    from epicrisis import validate

    return [] if document.item is None else validate.range_read_two_ways(document, settings)


@kind(
    "possible-copy", does=MARKS, at=VALIDATE, looks_at=THE_ARCHIVE,
    about="Two files of the same day printing the same results: an export, an excerpt, a letter "
          "quoting a form. One of a group answers, and a person chooses which.",
    settings={"results_shared": 0.8, "results_at_least": 5, "similar_in_size": 0.6, "results_in_common": 3},
    means={
        "results_shared": "How much of the smaller document's named results the two have to share before "
                          "they are held to be the same result, where both are long enough to compare.",
        "results_at_least": "How many results a document needs before sharing them means anything. Two short "
                            "forms of one day print the same handful of small numbers and are not copies.",
        "similar_in_size": "How close in length two documents have to be to be compared this way at all.",
        "results_in_common": "How many named results a shorter document needs, all of them found in a longer "
                             "one, to be taken for an excerpt of it.",
    },
)  # fmt: skip
def _possible_copy(archive, settings: dict):
    """Four numbers that decided what a copy is, and that nobody could see, move or measure.

    They were constants in validate.py. Whether two files are the same result is a judgement — a
    urinalysis and a coprogram of one day share a handful of small numbers and are not copies —
    and a judgement is what the registry is for: switchable, countable, and answerable by the
    person whose archive it is rather than by whoever last edited a constant.
    """
    from epicrisis import validate

    return validate.possible_copies(archive.documents, settings)


@kind(
    "date-that-could-not-be-settled", does=MARKS, at=VALIDATE, looks_at=ONE_DOCUMENT,
    about="A document whose date could not be settled from what is printed on it.",
)  # fmt: skip
def _date_to_check(document, settings: dict):
    # Not guarded on the transcription: a document nobody could read is exactly one whose date
    # nobody could settle, and it is the one most worth a person's eye.
    from epicrisis import validate

    return validate.date_to_check(document, settings)


# The three that place a value on a scale when a chart is drawn. Each returns what it decided
# rather than a list of findings: a kind that places has something to say about one value, and
# what shape that takes is the kind's own business, written here and used at one hook.


@kind(
    "unit-from-the-printed-range", does=PLACES, at=CHARTS, looks_at=ONE_VALUE,
    about="The unit named inside a value's printed reference range, where the form printed no "
          "unit column of its own.",
)  # fmt: skip
def _unit_from_the_printed_range(value, settings: dict) -> str | None:
    from epicrisis.units import unit_from_reference

    return unit_from_reference(value.item.get("reference"))


@kind(
    "date-printed-in-the-line", does=PLACES, at=CHARTS, looks_at=ONE_VALUE,
    about="A value a document quotes from an earlier study, placed on the date printed in its own "
          "line instead of the date of the document that quotes it.",
)  # fmt: skip
def _date_printed_in_the_line(value, settings: dict):
    """When the study this line retells was done. The careful part is in quotations.py.

    Careful because the thing it must not read as a date is a printed reference range: to a loose
    reader "4.11-5.89" is the eleventh of April. Eight real laboratory values on one archive were
    "quotations" by that reading, and this rule would have moved every one of them decades from
    where it was measured.
    """
    from datetime import date as a_day

    from epicrisis.quotations import quoted_date

    printed = value.item.get("date")
    if not printed:
        return None
    try:
        document_day = a_day.fromisoformat(str(printed)[:10])
    except ValueError:
        return None
    quoted = quoted_date(value.item.get("snippet"), document_day)
    return quoted.isoformat() if quoted else None


@kind(
    "one-scale-for-a-test", does=PLACES, at=CHARTS, looks_at=ONE_VALUE,
    about="A value converted to the scale European forms print most often, for the analytes this "
          "program holds a factor for.",
)  # fmt: skip
def _one_scale_for_a_test(value, settings: dict):
    from epicrisis.series import number
    from epicrisis.units import convert

    return convert(number(value.item.get("value_numeric")), value.unit_key, value.indicator, value.item.get("name"))


@kind(
    "unit-by-the-numbers", does=PLACES, at=CHARTS, looks_at=ONE_MATERIAL,
    about="Values whose form printed no unit anywhere, put on the scale their own numbers agree "
          "with. The one reading in this program taken from numbers rather than from a page.",
    settings={"agreement": 2.0, "least_to_join": 2},
    means={"agreement": "How close two numbers have to be, as a factor, to count as the same scale. 2.0 means within twice or half.",
           "least_to_join": "How many values a scale must already have before anything is allowed to join it."},
)  # fmt: skip
def _unit_by_the_numbers(material, settings: dict) -> dict:
    from epicrisis.series import place_by_the_numbers

    return place_by_the_numbers(material.by_unit, settings)


@kind(
    "unit-alone-in-a-series", does=MARKS, at=SUSPECTS, looks_at=THE_ARCHIVE,
    about="A unit used once on a test whose other forms all print another one. Knows nothing "
          "about the names of tests, so it does not go stale on the next form.",
    settings={"weight": 2, "alone_at_most": 1, "others_at_least": 10},
    means={"weight": WEIGHT,
           "alone_at_most": "How many times a unit may appear on a test before it stops counting as alone.",
           "others_at_least": "How many values carrying some other printed unit there must be before \"the others\" means anything."},
)  # fmt: skip
def _unit_alone(archive, settings: dict):
    from epicrisis.suspects import unit_alone_in_a_series

    return unit_alone_in_a_series(archive, settings)


@kind(
    "value-names-another-test", does=MARKS, at=SUSPECTS, looks_at=THE_ARCHIVE,
    about="The text of a value names a different test than the row it stands in: a table of "
          "targets printing one name in the row and another inside the cell.",
    settings={"weight": 2, "shortest_spelling": 8},
    means={"weight": WEIGHT,
           "shortest_spelling": "Letters. Below this a spelling is an ordinary word and matches half an archive."},
)  # fmt: skip
def _value_names_another_test(archive, settings: dict):
    from epicrisis.suspects import value_names_another_test

    return value_names_another_test(archive, settings)


# The two over an eye examination. Both read the words printed beside the numbers in the line the
# archive already keeps, so both cost nothing: no model, no network, nothing read again. The
# reading itself is in eyes.py, where the guards that keep it from crying wolf are written down.


@kind(
    "named-after-the-eye", does=MARKS, at=VALIDATE, looks_at=ONE_DOCUMENT,
    about="A value named by nothing but an eye — OD, OS, ОС — where its own printed line names "
          "the measurement beside the number. Which eye is not what was measured.",
)  # fmt: skip
def _named_after_the_eye(document, settings: dict):
    from epicrisis import validate

    return [] if document.item is None else validate.named_after_the_eye(document, settings)


@kind(
    "several-measurements-in-one-value", does=MARKS, at=VALIDATE, looks_at=ONE_DOCUMENT,
    about="A stored value holding the words of more than one measurement: a sphere, a cylinder "
          "and an axis in the field of one number. No name is right for such a field.",
)  # fmt: skip
def _several_measurements_in_one_value(document, settings: dict):
    from epicrisis import validate

    return [] if document.item is None else validate.several_measurements_in_one_value(document, settings)


# Written at the very end of this file and nowhere else in it. Another session was adding a kind
# of its own to the same file at the same time, and a kind put in beside its relatives would have
# been a merge conflict over somebody else's work rather than two appends that both apply.


@kind(
    "printed-range-powers-from-the-rest", does=MARKS, at=VALIDATE, looks_at=THE_ARCHIVE,
    about="A reference range printed beside a value that stands powers of ten away from the ranges "
          "printed beside every other reading of the same test, in the same unit and the same "
          "specimen: a range that cannot be this value's. Reads the printed ranges and never the "
          "value, so a reading far from normal — the thing this program exists to show — cannot "
          "make it fire.",
    settings={"powers_apart": 1.5, "ranges_at_least": 5, "ranges_agree": 0.75},
    means={
        "powers_apart": "How many powers of ten a printed range has to stand from the middle of the ranges "
                        "printed beside the other readings of the same test before it is reported. 1.5 is "
                        "about thirty-two times.",
        "ranges_at_least": "How many printed ranges one test, in one unit and one specimen, must have before "
                           "the middle of them means anything at all.",
        "ranges_agree": "What share of those ranges must themselves stand nearer the middle than this says is "
                        "far, before any one of them may be called the odd one out. A test two laboratories "
                        "print at two scales is not one range, and nothing is said about it.",
    },
)  # fmt: skip
def _printed_range_powers_from_the_rest(archive, settings: dict):
    from epicrisis import validate

    return validate.range_powers_from_the_rest(archive, settings)


# The checks of the extract step, which are the only checks in this program that cost money when
# they fire: each one, firing, sends the document back to a stronger model. They were eleven
# conditions written into one function, with their thresholds as module constants — so the owner
# paying per document could not turn off a check that was escalating documents for nothing, could
# not see which of them had fired how often, and could not raise a threshold that was wrong for
# their laboratory's forms. Here they are rules like any other: a name, a sentence about what they
# look at and how they can be wrong, a switch, and thresholds with words beside them.
#
# **The three below ask about completeness**, in the order a page fails: no text at all, far less
# text than the page held, or the text is there and the numbers are not. Each one says in full what
# it looks at rather than standing in a chain with the others, because a rule read on a settings
# page is read alone.
#
# **Each carries only its own thresholds, and that is the fix of a defect this chain shipped
# with.** They were written as a ladder — the second asking only of pages the first let through,
# the third only of pages the second let through — so each one carried a copy of the numbers of
# the ones before it: one `least_characters` written in three kinds and three rule files, one
# `least_share` in two of each. The copies are separate answers, stored per archive and typed one
# at a time on the settings page, so the ladder held only while all three happened to be equal.
# Raise the first and leave the second and a page of thirty characters is not empty to the first
# and already reported to the second: **reported by nothing at all**, which is the one outcome
# these three exist to prevent. Nothing anywhere said when the numbers came apart.
#
# So the rungs are independent now. A page can be named by two of them — it came back empty *and*
# much shorter than it was sent — and that costs nothing: a document goes back to a stronger model
# if anything at all was found, so a page named twice is a page named once as far as the bill goes.
#
# **These three and the table below them keep their thresholds and have no switch** — `stays_on`,
# and the reason is in `validate.LEFTOVER`, which has said since before any of this was a rule
# that a finding of a hole in somebody's archive stays on. What they report is not a judgement
# about anybody's data that could be called noise; it is this program saying it did not finish
# reading a page. The threshold is the knob that was wanted here — how empty is empty for one
# laboratory's forms — and it is still here.

A_PAGE_IS_EMPTY = ("How few characters a page's transcription may hold before it counts as not "
                   "transcribed at all. A page of a form with one line on it is still a page.")


@kind(
    "page-with-no-text", does=MARKS, at=EXTRACT, looks_at=ONE_DOCUMENT, stays_on=True,
    about="A page of the document whose transcription is empty or nearly so, while the page itself "
          "is part of the document. The reading stopped before the end, or never reached this page.",
    settings={"least_characters": 20},
    means={"least_characters": A_PAGE_IS_EMPTY},
    within={"least_characters": A_COUNT},
)  # fmt: skip
def _page_with_no_text(document, settings: dict):
    from epicrisis.extract.checks import pages_with_no_text

    return pages_with_no_text(document, settings)


@kind(
    "page-much-shorter-than-the-page", does=MARKS, at=EXTRACT, looks_at=ONE_DOCUMENT, stays_on=True,
    about="A page that went to the model as text and came back as much less text than was sent. "
          "Only pages whose own text is long enough to compare at all are asked about.",
    settings={"least_share": 0.5, "words_before_asking": 40},
    within={"least_share": A_SHARE, "words_before_asking": A_COUNT},
    means={"least_share": "What share of the words sent must come back before a page counts as transcribed. "
                          "0.5 is half of them.",
           "words_before_asking": "How many words a page must hold before a share of them means anything. A "
                                  "short page can lose half its words to one heading."},
)  # fmt: skip
def _page_much_shorter(document, settings: dict):
    from epicrisis.extract.checks import pages_much_shorter_than_the_page

    return pages_much_shorter_than_the_page(document, settings)


@kind(
    "page-whose-numbers-are-missing", does=MARKS, at=EXTRACT, looks_at=ONE_DOCUMENT, stays_on=True,
    about="A page of text whose transcription came back the right length but without the numbers "
          "the page prints. The words of a result are easy to write again from memory; the numbers "
          "are the one part that cannot be.",
    settings={"numbers_before_asking": 10, "least_number_share": 0.9},
    within={"numbers_before_asking": A_COUNT, "least_number_share": A_SHARE},
    means={"numbers_before_asking": "How many numbers a page must print before their absence means anything. Two "
                                    "numbers missing from three is a date and a page number.",
           "least_number_share": "What share of the page's numbers must be found again in the transcription. "
                                 "0.9 is nine in ten."},
)  # fmt: skip
def _page_whose_numbers_are_missing(document, settings: dict):
    from epicrisis.extract.checks import pages_whose_numbers_are_missing

    return pages_whose_numbers_are_missing(document, settings)


@kind(
    "table-page-without-values", does=MARKS, at=EXTRACT, looks_at=ONE_DOCUMENT, stays_on=True,
    about="A page that classification said carries a table of results, and from which no value was "
          "stored. Asked of laboratory results only: a letter or a discharge often prints a table "
          "inside its text, and nothing is wrong when a model reads it as prose.",
    settings={"of_document_types": ["lab_panel"]},
    means={"of_document_types": "The kinds of document whose table pages must hold values. A type not on this "
                                "list is never asked."},
)  # fmt: skip
def _table_page_without_values(document, settings: dict):
    from epicrisis.extract.checks import table_pages_without_values

    return table_pages_without_values(document, settings)


# **And the two that read the head of a document** — what the form says it is, and who printed it.
# They cost the same as the rest when they fire, and the first of them is the check that fires
# oftenest of all on a real archive after `unreadable_on_images`.


@kind(
    "provider-reads-like-a-person", does=MARKS, at=EXTRACT, looks_at=ONE_DOCUMENT,
    about="The institution field of a transcription holding what looks like a person's name: the "
          "signature under the stamp read as the laboratory. Asked with the title beside it, "
          "because the two are swapped often enough that the title is what tells a swap from a "
          "form that really prints only a doctor.",
)  # fmt: skip
def _provider_reads_like_a_person(document, settings: dict):
    from epicrisis.extract.checks import the_provider_reads_like_a_person

    return the_provider_reads_like_a_person(document, settings)


@kind(
    "a-word-in-two-alphabets", does=MARKS, at=EXTRACT, looks_at=ONE_DOCUMENT,
    about="A word of the document's head written in both alphabets at once, as in \"Кліnіка\": a "
          "letter read from the wrong one. A name holding a word of each is not this.",
    # The pair itself is `extract.checks.THE_HEAD_OF_A_DOCUMENT`, which the other check of the
    # head reads too, so a third printed field added there reaches both. Written out as a list
    # because a setting is stored and read back as JSON, where a tuple is a list anyway.
    settings={"of_fields": list(THE_HEAD_OF_A_DOCUMENT)},
    means={"of_fields": "Which printed fields of the head are read. One hit per field and never per word: "
                        "a title with four such words is one field read wrongly."},
)  # fmt: skip
def _a_word_in_two_alphabets(document, settings: dict):
    from epicrisis.extract.checks import words_in_two_alphabets

    return words_in_two_alphabets(document, settings)


# **And the checks that hold a stored value against the page it came from.** They are the largest
# group and the one that divides in two: a page that went to the model as text can be compared
# with the page itself, and a page that went as an image can only be compared with the model's own
# reading of it. Those are different questions and have always had different codes, so they are
# different rules — a person turning one off is saying something about scans or about text layers,
# and never about both at once.

A_PAGE_WORTH_COMPARING = ("How many words a page must hold before what is missing from it means anything. "
                          "A page of a few words says nothing either way.")


@kind(
    # The third of the three `validate.LEFTOVER` names, and the only check of this step whose
    # findings a person is shown one by one, under this name. It stays on for the reason the other
    # two do: a stored value that is nowhere on its own page is this program reporting that it
    # read something that is not there, and a switch on that is a switch that hides it. Its
    # thresholds are the knobs — which pages are long enough to compare, and whether a value
    # printed as a word is passed over.
    "value-not-on-its-own-page", does=MARKS, at=EXTRACT, looks_at=ONE_DOCUMENT, stays_on=True,
    about="A value that is nowhere in the text of the page it claims to come from, on a page that "
          "went to the model as text. The page itself is the evidence there, not a reading of it.",
    settings={"words_before_asking": 40, "skip_qualitative": True},
    within={"words_before_asking": A_COUNT},
    means={"words_before_asking": A_PAGE_WORTH_COMPARING,
           "skip_qualitative": "Whether values the form printed as words rather than numbers are passed over. "
                               "They are compared by their digits, and a value with none has nothing to compare."},
)  # fmt: skip
def _value_not_on_its_own_page(document, settings: dict):
    from epicrisis.extract.checks import values_not_on_their_page

    return values_not_on_their_page(document, settings)


@kind(
    "value-not-in-the-page-text", does=MARKS, at=EXTRACT, looks_at=ONE_DOCUMENT,
    about="On pages that went as text: a stored value whose printed form is not in the page's own "
          "text at all.",
)  # fmt: skip
def _value_not_in_the_page_text(document, settings: dict):
    from epicrisis.extract.checks import values_not_in_the_page_text

    return values_not_in_the_page_text(document, settings)


@kind(
    "value-not-in-the-models-own-text", does=MARKS, at=EXTRACT, looks_at=ONE_DOCUMENT,
    about="On pages that went as images: a stored value that is not in the model's own "
          "transcription of that page. The reading disagrees with itself.",
)  # fmt: skip
def _value_not_in_the_models_own_text(document, settings: dict):
    from epicrisis.extract.checks import values_not_in_the_models_own_text

    return values_not_in_the_models_own_text(document, settings)


@kind(
    "reference-not-in-the-page-text", does=MARKS, at=EXTRACT, looks_at=ONE_DOCUMENT,
    about="On pages that went as text: a printed range whose numbers are not all on the page. "
          "Number by number, because a range is printed over several lines and columns.",
)  # fmt: skip
def _reference_not_in_the_page_text(document, settings: dict):
    from epicrisis.extract.checks import references_not_in_the_page_text

    return references_not_in_the_page_text(document, settings)


@kind(
    "reference-not-in-the-models-own-text", does=MARKS, at=EXTRACT, looks_at=ONE_DOCUMENT,
    about="On pages that went as images: a printed range whose numbers are not all in the model's "
          "own transcription of that page.",
)  # fmt: skip
def _reference_not_in_the_models_own_text(document, settings: dict):
    from epicrisis.extract.checks import references_not_in_the_models_own_text

    return references_not_in_the_models_own_text(document, settings)


@kind(
    "letters-in-a-numeric-value-on-an-image", does=MARKS, at=EXTRACT, looks_at=ONE_DOCUMENT,
    about="A value stored as a number whose printed form carries letters nothing explains, on a "
          "page that went as an image. On a text page those letters are printed ones.",
)  # fmt: skip
def _letters_in_a_numeric_value(document, settings: dict):
    from epicrisis.extract.checks import letters_in_a_numeric_value_on_an_image

    return letters_in_a_numeric_value_on_an_image(document, settings)


@kind(
    "comparator-stored-and-not-printed", does=MARKS, at=EXTRACT, looks_at=ONE_DOCUMENT,
    about="A comparator stored against a value whose printed form carries none: a sign the reading "
          "worked out from the range rather than read off the form.",
)  # fmt: skip
def _comparator_stored_and_not_printed(document, settings: dict):
    from epicrisis.extract.checks import comparators_not_printed

    return comparators_not_printed(document, settings)


# **And the last three**, which are about the document rather than about one value: a table whose
# columns are unnamed, a date that is somebody's birthday, and a reading that says out loud it
# could not read part of a scan. With these the step's checks are rules entire, and
# `transcription_problems` is a loop over the registry and nothing else.


@kind(
    "rows-of-several-values-without-a-heading", does=MARKS, at=EXTRACT, looks_at=ONE_DOCUMENT,
    about="A row printing more than one value where the document carries no column heading at "
          "all: nothing says which of them is the result. A row, and never a page — a name "
          "printed twice on a page is a measurement in two places, which long reports do.",
)  # fmt: skip
def _rows_without_a_heading(document, settings: dict):
    from epicrisis.extract.checks import rows_of_several_values_without_a_heading

    return rows_of_several_values_without_a_heading(document, settings)


@kind(
    "a-document-date-that-is-a-birth-date", does=MARKS, at=EXTRACT, looks_at=ONE_DOCUMENT,
    about="A date stored as the document's own that is a date of birth printed on the same page. "
          "A document filed under a birth date stands decades from where it belongs.",
    settings={"of_dates": ["date_of_study_as_printed", "date_of_report_as_printed"]},
    means={"of_dates": "Which printed dates of the document are asked about. One hit per field."},
)  # fmt: skip
def _a_document_date_that_is_a_birth_date(document, settings: dict):
    from epicrisis.extract.checks import dates_that_are_a_birth_date

    return dates_that_are_a_birth_date(document, settings)


@kind(
    "unreadable-parts-on-a-scan", does=MARKS, at=EXTRACT, looks_at=ONE_DOCUMENT,
    about="The reading says part of the document could not be read, and part of it went to the "
          "model as an image. Where every page went as text there is nothing a second reading "
          "would see differently.",
)  # fmt: skip
def _unreadable_parts_on_a_scan(document, settings: dict):
    from epicrisis.extract.checks import unreadable_parts_on_pages_that_went_as_images

    return unreadable_parts_on_pages_that_went_as_images(document, settings)
