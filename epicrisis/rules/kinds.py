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
    run: Callable | None = None

    @property
    def cost(self) -> str:
        return COSTS[self.at]


KINDS: dict[str, Kind] = {}


def kind(name: str, does: str, at: str, about: str, looks_at: str = A_SERIES, settings: dict | None = None):
    """Register a kind of check. The function it decorates is what the rules of that kind do."""
    if does not in DOES or at not in AT or looks_at not in LOOKS_AT:
        raise ValueError(f"{name}: does={does!r} at={at!r} looks_at={looks_at!r} is not a kind of check that exists")

    def keep(run: Callable) -> Callable:
        KINDS[name] = Kind(name=name, does=does, at=at, looks_at=looks_at, about=about,
                           settings=settings or {}, run=run)  # fmt: skip
        return run

    return keep


@kind(
    "value-against-its-printed-range",
    does=PLACES,
    at=CHARTS,
    looks_at=A_SERIES,
    about="Compares the numbers of one test with the reference ranges printed beside them, to say "
          "which of them are written at another scale.",
    settings={"same_band": 0.15, "bands_to_see_a_scale": 2},
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
)  # fmt: skip
def _unit_missing(archive, settings: dict):
    from epicrisis.suspects import unit_missing_where_others_have_one

    return unit_missing_where_others_have_one(archive, settings)


@kind(
    "number-far-from-the-others", does=MARKS, at=SUSPECTS, looks_at=THE_ARCHIVE,
    about="A number many times away from every other reading of the same test, in the same unit "
          "and the same specimen.",
    settings={"weight": 3, "least_history": 4, "times_away": 10},
)  # fmt: skip
def _number_far(archive, settings: dict):
    from epicrisis.suspects import number_far_from_the_others

    return number_far_from_the_others(archive, settings)


@kind(
    "institution-looks-like-a-name", does=MARKS, at=SUSPECTS, looks_at=THE_ARCHIVE,
    about="An institution recorded as somebody's name or initials: the doctor under the stamp "
          "read as the laboratory.",
    settings={"weight": 3},
)  # fmt: skip
def _institution_is_a_person(archive, settings: dict):
    from epicrisis.suspects import institution_looks_like_a_name

    return institution_looks_like_a_name(archive, settings)


@kind(
    "lab-form-without-a-title", does=MARKS, at=SUSPECTS, looks_at=THE_ARCHIVE,
    about="A laboratory form transcribed with no title at all.",
    settings={"weight": 1},
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
)  # fmt: skip
def _unit_by_the_numbers(material, settings: dict) -> dict:
    from epicrisis.series import place_by_the_numbers

    return place_by_the_numbers(material.by_unit, settings)
