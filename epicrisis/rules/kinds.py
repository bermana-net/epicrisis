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
  `places` may only say what scale or unit something is printed in. Nothing here computes a
  value, judges one, or decides anything for a person (MDCG 2019-11). There is no third one.

A kind is added only when a rule genuinely needs something no kind can do. It arrives with its
settings and their defaults, so a rule file naming a setting this kind does not have is refused
rather than quietly ignored.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from epicrisis.rules.subjects import A_SERIES, LOOKS_AT, ONE_DOCUMENT, ONE_MATERIAL, ONE_VALUE, THE_ARCHIVE

MARKS, PLACES = "marks", "places"
DOES = (MARKS, PLACES)

# The steps that run rules, in the order the pipeline runs them. The last two are not steps of
# the pipeline at all but readings made when a page is drawn or a question answered, which is
# why turning one of those on or off costs nothing and changes nothing that is stored.
EXTRACT, VALIDATE, INDEX, CHARTS, SUSPECTS = "extract", "validate", "index", "charts", "suspects"
AT = (EXTRACT, VALIDATE, INDEX, CHARTS, SUSPECTS)
# What turning a rule on or off asks of a person, per step. Said on the settings page, where the
# switch is, and not in a release note nobody reads.
# Steps where changing a rule costs something that cannot be taken back cheaply: documents are
# read again by a model, which takes hours and, on an API key, money. A switch like that is not
# a switch a person should be able to flip by leaning on the mouse, so the page asks first and
# says in the same breath how much there is to read.
COSTLY = (EXTRACT,)
COSTS = {
    EXTRACT: "Documents are read again by a model. That takes time and, on an API key, money.",
    VALIDATE: "The archive is checked again. No model, seconds, nothing is read again.",
    INDEX: "The index is built again from what is stored. No model, seconds.",
    CHARTS: "Takes effect on the next page. Nothing is stored and nothing is built again.",
    SUSPECTS: "Takes effect the next time the list is asked for. Nothing is stored.",
}


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
    run: Callable | None = None

    @property
    def cost(self) -> str:
        return COSTS[self.at]


KINDS: dict[str, Kind] = {}


# Which subject each step actually builds and hands to a rule. A kind declaring a pair nobody
# serves used to be accepted and then skipped in silence by every loop of that step: no error, no
# line anywhere, the rule switched on in the settings and finding nothing for ever. Refused here,
# at the moment the kind is written, rather than discovered by somebody wondering why a rule they
# turned on never fires. Adding a subject to a step means teaching that step to build it first,
# and then adding it to this table — in that order.
SERVED = {
    EXTRACT: set(),
    VALIDATE: {ONE_DOCUMENT, THE_ARCHIVE},
    INDEX: set(),
    CHARTS: {A_SERIES, ONE_VALUE, ONE_MATERIAL},
    SUSPECTS: {THE_ARCHIVE},
}


def kind(name: str, does: str, at: str, about: str, looks_at: str = A_SERIES,
         settings: dict | None = None, means: dict | None = None):  # fmt: skip
    """Register a kind of check. The function it decorates is what the rules of that kind do."""
    if does not in DOES or at not in AT or looks_at not in LOOKS_AT:
        raise ValueError(f"{name}: does={does!r} at={at!r} looks_at={looks_at!r} is not a kind of check that exists")
    if looks_at not in SERVED[at]:
        raise ValueError(
            f"{name}: nothing at the {at} step hands a rule {looks_at!r}. A kind whose subject that step "
            f"does not assemble is not refused anywhere and finds nothing for ever, which looks exactly "
            f"like a rule that is working. What {at} hands out: {', '.join(sorted(SERVED[at]))}."
        )
    # Every threshold says what it means, or it cannot be offered to anybody to change.
    if set(settings or {}) != set(means or {}):
        raise ValueError(f"{name}: every setting needs a line saying what it means, and only those")

    def keep(run: Callable) -> Callable:
        KINDS[name] = Kind(name=name, does=does, at=at, looks_at=looks_at, about=about,
                           settings=settings or {}, means=means or {}, run=run)  # fmt: skip
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
    means={"agreement": "How close two middles have to be, as a factor, to count as the same scale. 2.0 means within twice or half.",
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
