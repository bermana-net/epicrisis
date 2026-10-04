"""Printed values laid out as a chart: geometry only, computed here and drawn as plain SVG.

The chart shows and does not interpret. Points are the numbers the laboratory printed; the band
behind them is the reference range printed on that same form, which is why it changes shape when
the laboratory changed it. Nothing is averaged, no trend is drawn, and no point is coloured for
being above or below anything: that reading belongs to a doctor.

What is one unit and what converts into what is in units.py; this file draws.

Values in different units never share a chart - a chart per unit, never a conversion. Nor do
values of different materials: blood and urine are two measurements, whatever the name on the
form. A value that is not a number ("Absent", "Normal") cannot be a point and is listed beside
the chart.
"""

import math
from datetime import date
from statistics import median

from epicrisis import reference, units
from epicrisis.values import is_result
from epicrisis.rules.subjects import Material, Series, Value
from epicrisis.units import AGREEMENT, MIN_TO_JOIN, same_measure, says_its_power, unit_key

WIDTH, HEIGHT = 900, 260
PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM = 52, 16, 16, 28
MIN_POINTS = 2


def number(text: str | None) -> float | None:
    """The number a stored value holds, or nothing.

    "Nothing" includes the numbers that are not points on a chart: a NaN drew an SVG full of
    "nan,nan" with NaN axis labels beside a table that was perfectly correct, and an infinity
    stretches an axis so far that every real value lies on one line at the bottom.
    """
    try:
        value = float(str(text).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def printed_range(text: str | None, unit: str | None = None) -> tuple[float | None, float | None] | None:
    """The reference range as the form printed it: (low, high), either side open.

    One reader for the whole program. There were three — this one, reference.parse and the check
    in validate — and their vocabularies had already drifted apart: "менее 5" drew a band here
    and read as nothing there, and a range with its unit beside it ("3,5-5,5 ммоль/л") drew no
    band at all, so bands appeared on some points of one test and not on others.

    The unit is the one the band is wanted in, and it settles one thing only: which band of a line
    that printed one per unit belongs to the value in hand. Asked with no unit, that line is two
    ranges and nothing here says which — see reference.a_band_for_each_unit.
    """
    return reference.parse(text, unit)


def _join_equivalent(by_unit: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Join spellings of one measure where the numbers themselves say it is one measure."""
    middles = {key: median(values) for key, items in by_unit.items() if (values := _the_numbers_of(items))}
    joined: dict[str, list[dict]] = {}
    for key, items in by_unit.items():
        measure = same_measure(key)
        mine = middles.get(key)
        target = None
        for other in joined:
            if same_measure(other) != measure or measure is None:
                continue
            theirs = middles.get(other)
            enough = len(by_unit[other]) >= MIN_TO_JOIN and len(items) >= MIN_TO_JOIN
            agrees = mine and theirs and max(mine, theirs) <= AGREEMENT * min(mine, theirs)
            # Written-out powers are the same measure however few values carry them: a single
            # "x10³/mm³" drew a chart of its own beside two years of "10⁹/L", which is the same
            # count written the other way, and no eye could have put the two together.
            exact = says_its_power(key) and says_its_power(other)
            if exact or (enough and agrees):
                target = other
                break
        joined.setdefault(target or key, []).extend(items)
    return joined


def place_by_the_numbers(by_unit: dict[str, list[dict]], settings: dict) -> dict[str, list[dict]]:
    """Put the values whose form printed no unit at all on the scale their own numbers match.

    Old forms print a leukocyte formula with no unit column and no range: the numbers are
    per-cent, and nothing on the page says so. Two readings, in this order, because this program
    prefers what a page says to anything guessed from numbers:

    First, where the forms printed a reference range beside the values with no unit, that range is
    compared with each scale's numbers. A prostate-specific antigen printed "up to 4" against
    values of 1.96 to 4.35 is one scale and joins. A range printed with one end and left open at
    the other is asked for that end to be the end of those numbers as well, because an open end
    bounds nothing and a floor alone read as "the numbers are positive"; the measurement is in
    units.numbers_fit_the_range, beside the arithmetic. Where no range was printed beside them
    this reading says nothing rather than guessing, and the next paragraph is reached — including
    where some other form of the same test printed a range of its own.

    A line that printed one band per unit — "47 – 72 % 2,000 – 5,500*10⁹/л" — printed no range
    this reading may use, and _the_range_printed_beside says so rather than handing over a half.
    It printed one band for each of two scales; both fit their own scale's numbers, because one
    laboratory printed both of them for one test; so nothing here tells which scale the value
    beside them is on, and the next paragraph is reached.

    Second, where no range was printed beside the values with no unit, the spreads themselves, end
    to end: the low of the values with no unit against the low of the scale, the high against the
    high, each within the agreement. A sedimentation rate of 4 to 35 joins one of 2 to 35; a
    creatinine of 0.5 to 55.3 does not join one of 30 to 92.8, because the low ends are a factor
    of sixty apart.

    The second reading is asked whenever the first says nothing, including where some other form
    of the same test printed a range of its own. That was written the other way first — a range
    anywhere meant the page had spoken and the numbers were not asked — and measured on three
    archives it cost sixty-seven values their scale to gain four. A haemoglobin of 14.8, printed
    with neither unit nor range beside three readings of 15.5 in grams per decilitre, stopped
    being drawn with them: a range printed beside somebody else's row says nothing about that one,
    and silence there is not the page speaking.

    Third, where the ends disagree, the values that stand next to each other in time, pair by
    pair, in _the_pairs_in_time_agree. A spread is as wide as the years and the readings that went
    into it, so two sets of different size over different years are not asked the same question
    end to end: a marker that rises over a lifetime has its small years in one set and its large
    ones in the other, and the ends say the two are different scales when they are one history.
    Two readings a few weeks apart are the same quantity, whatever it has done over thirty years,
    so their ratio is about the scale and nothing else.

    Either way a scale is joined only when exactly one fits and no other does, and the scales in
    front of it are counted the way the charts will be drawn — one per measure, not one per
    spelling, which is _the_scales_in_front_of_them. Nothing is converted, and each value moved
    this way is marked, because this is the one reading in the program taken from numbers and not
    from a form.
    """
    bare = by_unit.get("")
    if not bare:
        return by_unit
    agreement = settings["agreement"]
    together = _the_scales_in_front_of_them(by_unit)
    numbers = {key: readings for key, items in together.items() if (readings := _the_numbers_of(items))}
    named = [key for key in numbers if key and len(together[key]) >= settings["least_to_join"]]
    printed = _the_range_printed_beside(bare)
    if printed is not None:
        near = [key for key in named if units.numbers_fit_the_range(printed, numbers[key], agreement)]
    elif (mine := numbers.get("")) is not None:
        spread = (min(mine), max(mine))
        # End to end where there is a spread to compare, and inside the scale's own where there is
        # not. One value has no spread: its low is its high, and asked end to end a lone 0.06
        # against a scale running 0.01 to 0.06 is refused on its low ends being six times apart,
        # although it sits exactly on the scale's own top. Measured: four such values across these
        # archives stood off their scale for that reason alone.
        near = [key for key in named
                if (units.ends_agree(spread, (min(numbers[key]), max(numbers[key])), agreement)
                    if spread[0] != spread[1]
                    else units.numbers_fit_the_range((min(numbers[key]), max(numbers[key])), mine, agreement))
                or _the_pairs_in_time_agree(bare, together[key], agreement)]  # fmt: skip
    else:
        return by_unit
    if len(near) != 1:
        return by_unit  # two scales it could belong to, or none: nothing here says which
    moved = {key: items for key, items in by_unit.items() if key != ""}
    moved[near[0]] = [*moved[near[0]], *({**item, "unit_by_numbers": True} for item in bare)]
    return moved


def _the_scales_in_front_of_them(by_unit: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """The scales a value with no unit could join: one per measure, as the charts will be drawn.

    Asked of the spellings instead, "exactly one fits and no other does" was never true where one
    measure is written two ways. A litre holds a thousand millilitres, so "10^9/L" and "10^3/µL"
    are one scale and _join_equivalent puts them on one chart a moment after this runs — but
    counted here they were two candidates, and three tests of one archive kept a chart of their
    own headed with no unit beside the chart they belong on, every one of them with a printed
    range that fitted both spellings because both spellings are the same scale.

    The same function decides it, so the two cannot drift apart: a scale this returns is a chart
    that will be drawn, and the key it comes back under is the one that chart will be headed with.
    Only the question is asked of the joined view; the rows themselves are left where they are,
    and the charts join them again in their own time.
    """
    bare = by_unit.get("", [])
    joined = _join_equivalent({key: items for key, items in by_unit.items() if key})
    return {**joined, "": bare} if bare else joined


def _the_pairs_in_time_agree(bare: list[dict], named: list[dict], agreement: float) -> bool:
    """Whether each value with no unit is the size of the value nearest it in time on this scale.

    The question two spreads cannot answer. A spread is as wide as the years and the readings that
    went into it: eleven readings of fifteen years and two readings of one year have spreads of
    different width whatever scale either is on, so compared end to end they say which set is
    longer and not which scale it is. The owner saw it on a marker that rises with age — the years
    with no unit printed held its small readings and the years with one held its large ones, the
    low ends stood a factor of nine apart, and one history was drawn as two charts.

    Two readings a few weeks apart are the same quantity, however far it has moved over a
    lifetime, so the ratio between them is about the scale and nothing else. Every value with no
    unit is asked against its nearest neighbour in time on this scale, and every pair has to
    agree: one pair of the wrong size is a column holding two scales, which is the thing this
    whole rule exists to refuse. Where neither side carries a date there is no pair to ask, and
    nothing here says anything.
    """
    mine, theirs = _dated_numbers(bare), _dated_numbers(named)
    if not mine or not theirs:
        return False
    # The smaller reading breaks a tie, so two neighbours equally near give the same answer
    # whatever order the rows arrived in, and the answer is the stricter of the two.
    return all(units.the_same_size(value, min(theirs, key=lambda other: (abs(other[0] - day), other[1]))[1],
                                   agreement)
               for day, value in mine)  # fmt: skip


def _dated_numbers(items: list[dict]) -> list[tuple[date, float]]:
    """Every row of these that holds both a number and a day, as the two of them."""
    out = []
    for item in items:
        value = number(item.get("value_numeric"))
        try:
            day = date.fromisoformat(str(item.get("date"))[:10])
        except (TypeError, ValueError):
            continue
        if value is not None:
            out.append((day, value))
    return out


def _the_numbers_of(items: list[dict]) -> list[float]:
    """Every number these rows hold, on the scale the chart is drawn in."""
    return [reading for item in items if (reading := number(item.get("value_numeric"))) is not None]


def _the_range_printed_beside(items: list[dict]) -> tuple[float | None, float | None] | None:
    """The reference range these forms printed, at its widest, or nothing when none printed one.

    At its widest because a laboratory changes its range over the years and both printings are
    the page talking. Taking the narrowest, or the newest, would have thrown away half of what
    was said for no reason.

    No unit is in hand here, and that is why a line printing one band per unit gives nothing: the
    scale these values are on is the very thing being worked out, so neither band may be preferred
    and the reading below is left to the numbers, which is what this rule is for. Measured on the
    three archives here, that costs ten eosinophil values their scale and is in the report beside
    this commit: they were on it because the per-cent half of such a line was being read as the
    whole of what the form printed.
    """
    bands = [band for item in items if (band := _printed_band_brought_along(item)) is not None]
    if not bands:
        return None
    lows = [low for low, _ in bands if low is not None]
    highs = [high for _, high in bands if high is not None]
    return (min(lows) if lows else None, max(highs) if highs else None)


def _one_scale(items: list[dict], scale_rules, unit_of_the_chart: str = "") -> list[dict]:
    """One test printed at two scales, drawn on one, by whichever rules are on.

    The rules are handed in rather than read from disk here: this file draws, and what an
    instance has turned on is not its business. Where more than one rule would move a series,
    the first one that moves anything decides it — two rules quietly moving the same points
    twice is the one thing worse than neither of them running.

    The printed value and its printed range stay exactly as they are in the rows beside the
    chart; only the point moves, and it carries what it was moved by.
    """
    # The numbers here have already been brought to one unit; the ranges have to be brought with
    # them before anything compares the two. Compared as printed, every converted value looked to
    # this rule like a value printed at another scale than its own range — a hemoglobin of 15.07
    # g/dL, drawn as 150.7 г/л, beside a range printed "13.5 - 18" — so the rule dutifully moved
    # the band by a power of ten, and the band was then multiplied by the conversion as well. The
    # values were right and the band was ten or a hundred times too high, which set the top of the
    # axis: fifteen years of a person's results drawn as one flat line along the bottom of the
    # chart, on thirty-five charts of this archive. Nothing was wrong with any of the numbers.
    series = Series(numbers=[number(item.get("value_numeric")) for item in items],
                    bands=[_printed_band_brought_along(item) for item in items])  # fmt: skip
    powers = None
    for rule in scale_rules:
        moves = rule.check.run(series, rule.settings)
        if any(value or band for value, band in moves):
            powers = moves
            break
    if powers is None:
        return items
    moved = []
    for item, (power, band_power) in zip(items, powers, strict=True):
        if band_power and _the_band_says_its_own_unit(item, unit_of_the_chart):
            # A range that names a unit has said its own scale, and where that unit is the one
            # this chart is drawn in there is nothing to move it onto. A haematocrit printed
            # "0,48" with no unit beside a range printed "0,2-1,0%" is a fraction and belongs at
            # 48 per cent — the value moves, and it should. The range does not: it is already in
            # per cent, it says so, and moved with the value it became a band from twenty to a
            # hundred per cent over values between thirty-seven and forty-eight, which is not a
            # range of anything and set the top of the axis.
            band_power = 0
        if not power and not band_power:
            moved.append(item)
            continue
        factor, standing = 10.0**power, number(item.get("value_numeric"))
        # A row with no number keeps no number. "Not detected" printed where a number usually
        # stands has a printed range beside it, so the range moves with the rest of the series —
        # and the value used to move with it, out of nothing into a nought: `None or 0` times the
        # factor is 0.0. That nought was then drawn as a point on the line, joined to the real
        # values, and it left the list of what could not be drawn, which is the one place a
        # person could have checked it against the form.
        moved.append({**item,
                      "value_numeric": None if standing is None else standing * factor,
                      "scaled": {"from_value": item.get("value"), "factor": factor,
                                 "band_factor": 10.0**band_power}})  # fmt: skip
    return moved


def _the_band_says_its_own_unit(item: dict, unit_of_the_chart: str) -> bool:
    """Whether the printed range names the unit this chart is drawn in, and so needs no moving."""
    if not unit_of_the_chart:
        return False
    if reference.a_band_for_each_unit(item.get("reference")):
        # A line that printed one band per unit named this chart's unit beside the band drawn
        # here, or it gave this chart no band at all. Either way the band is already in the unit
        # of the chart and there is nothing to move it onto — the same reason the one named unit
        # below is left alone, and the same mistake it was written to stop.
        return printed_range(item.get("reference"), unit_of_the_chart) is not None
    named = units.unit_from_reference(item.get("reference"))
    return bool(named) and unit_key(named) == unit_key(unit_of_the_chart)


def date_label(item: dict) -> str | None:
    """The date as far as it is known: a day, a month, or a year — never a day that was invented.

    The index keeps 05.2019 as 2019-05-01 with its precision beside it, because a table has to
    sort. A page that prints the stored day says the form named a day it never named.
    """
    date = item.get("date")
    if not date:
        return None
    precision = item.get("date_precision") or "day"
    return {"month": date[:7].replace("-", "."), "year": date[:4]}.get(precision, date)


# Why a chart drew no line. One sentence used to cover every one of these cases — "Not enough
# numbers to draw a line here" — and on most of them it was untrue in the way that costs a person
# an appointment: a reader who has been told there are not enough numbers goes and has the test
# taken again, and on a chart of eight urine colours printed as words no number of further tests
# would ever draw a line, because not one of those values is a number. Measured on the three demo
# archives, nine charts drew nothing and eight of them held no number at all: eight colours, eight
# transparencies, one occult blood, one stool consistency, and six urine leukocyte counts on two
# scales printed as spans ("1-2", "2-4"). The README already promises the other thing in so many
# words — where the archive has only a word, nothing is drawn and the page says so — so these are
# the three things
# the page may truthfully say instead, and the template says which values they are about.
NOT_NUMBERS = "not numbers"  # nothing on this scale was read as a number at all
NOWHERE_TO_PUT_THEM = "nowhere to put them"  # numbers, but none of them can stand on this line
TOO_FEW = "too few"  # numbers that could be drawn, fewer than a line needs


def _printed_shape(item: dict) -> str:
    """What the form printed where this value stands, for a chart that could not draw it.

    Read off the printed text alone. Whether a reading turned that text into a number is the
    separate question asked beside this one, and the case where the two disagree — a form that
    printed "0,033" whose value came back qualitative, which is two of the demo archive's eight
    urine protein values — is the only one of these a person can put right, so it is told apart
    from a word rather than counted with it.
    """
    text = (item.get("value") or "").strip()
    if number(text) is not None:
        return "a number"
    span = printed_range(text)
    if span is not None and span[0] is not None and span[1] is not None:
        return "a span"
    if not reference.NUMBER.search(text):
        return "a word"
    return "another shape"


def _why_no_line(items: list[dict], drawable: list[dict]) -> dict:
    """What a chart with no line may say about itself: the cause, and the values behind it.

    Counts only, and the printed values themselves for the few the page quotes. The sentences
    are in series.html, where the rest of this page's prose is.
    """
    numbers = [item for item in items if number(item.get("value_numeric")) is not None]
    shapes: dict[str, int] = {}
    examples: dict[str, list[str]] = {}
    for item in items:
        if number(item.get("value_numeric")) is not None:
            continue
        shape = _printed_shape(item)
        shapes[shape] = shapes.get(shape, 0) + 1
        printed = (item.get("value") or "").strip()
        seen = examples.setdefault(shape, [])
        if printed and printed not in seen and len(seen) < 3:
            seen.append(printed)
    reason = TOO_FEW if drawable else NOWHERE_TO_PUT_THEM if numbers else NOT_NUMBERS
    return {"reason": reason, "drawable": len(drawable), "numbers": len(numbers),
            "not_numbers": len(items) - len(numbers), "least": MIN_POINTS,
            "numbers_undated": sum(1 for item in numbers if not item.get("date")),
            "numbers_beside": sum(1 for item in numbers if not is_result(item)),
            "shapes": shapes, "examples": examples}  # fmt: skip


# What counts as the result of a form is decided in epicrisis/values.py, for every reader of it.



def unit_of_the_row(values: list[dict]) -> list[dict]:
    """A further column of a row takes the unit printed for that row.

    A "previous value" column carries no unit of its own; the unit stands once, for the whole
    row. Reading it from the row is reading the form, and without it such values fell together
    into a chart headed "no unit printed" that mixed per-cent with counts per litre.
    """
    units: dict[tuple, str] = {}
    for item in values:
        if is_result(item) and (item.get("unit") or "").strip():
            units.setdefault((item.get("document_id"), item.get("name"), item.get("page")), item["unit"])
    out = []
    for item in values:
        unit = units.get((item.get("document_id"), item.get("name"), item.get("page")))
        if unit and not is_result(item) and not (item.get("unit") or "").strip():
            item = {**item, "unit": unit, "unit_from_the_row": True}
        out.append(item)
    return out


def charts(values: list[dict], width: int = WIDTH, height: int = HEIGHT, indicator: str | None = None,
           placing=()) -> list[dict]:  # fmt: skip
    """One chart per material and unit, oldest first. Values that are not numbers come back as a list.

    from_range: where a value carries no unit of its own, the unit named inside its printed
    reference range is used — "53-115 мкмоль/л" says the scale as plainly as a unit column would,
    and reading it is reading the form. Such a value is marked.

    by_numbers: a value whose form printed no unit anywhere is put on the scale its own numbers
    match. That is the one reading here taken from numbers rather than from the page, so it is a
    setting, off unless a person asks for it, and every value moved that way is marked.

    to_scale brings the units this archive knows how to convert onto one scale; see units.py.

    scale_rules are the rules, already chosen by whoever asked for the chart, that may place a
    value on another scale: one test two laboratories printed a power of ten apart - 1,015 and
    1015 - drawn as one history. See epicrisis/rules/.

    A material is never joined to another. Blood and urine carry the same printed name and often
    the same unit, and their numbers differ by two orders of magnitude, so one line through both
    would be a line through two different measurements. Each material gets its own charts, and
    values whose material the form did not say stay with the blood they are most likely to be.
    """
    by_material: dict[str, dict[str, list[dict]]] = {}
    from_range = _one(placing, "unit-from-the-printed-range")
    to_scale = _one(placing, "one-scale-for-a-test")
    # Before anything else, because everything after it sorts and draws by the date: a value a
    # document quotes from an earlier study belongs on the day its own line prints, not on the day
    # of the document doing the quoting. Done here rather than at the index so that turning the
    # rule off puts every point back where it was, with nothing to build again.
    quoted = _one(placing, "date-printed-in-the-line")
    values = _on_their_own_dates(values, quoted) if quoted else values
    for item in unit_of_the_row(values):
        by_unit = by_material.setdefault((item.get("material") or "").strip(), {})
        key = unit_key(item.get("unit"))
        if not key and from_range:
            from_reference = from_range.check.run(Value(item=item), from_range.settings)
            if from_reference:
                key = from_reference
                item = {**item, "unit_from_reference": True}
        if to_scale:
            moved = to_scale.check.run(Value(item=item, indicator=indicator, unit_key=key), to_scale.settings)
            if moved:
                value, unit, factor = moved
                item = {**item, "value_numeric": value, "converted": {
                    "from_value": item.get("value"), "from_unit": (item.get("unit") or "").strip() or None,
                    "factor": factor, "to_unit": unit,
                }}  # fmt: skip
                key = unit_key(unit)
        by_unit.setdefault(key, []).append(item)
    charts_out = []
    for material, by_unit in by_material.items():
        by_numbers = _one(placing, "unit-by-the-numbers")
        grouped = by_numbers.check.run(Material(by_unit=by_unit), by_numbers.settings) if by_numbers else by_unit
        charts_out += _charts_of(grouped, material, width, height, [rule for rule in placing
                                                                   if rule.kind == "value-against-its-printed-range"])  # fmt: skip
    # Blood and the unmarked first, then the other materials by name; inside a material, the
    # chart with the most points leads.
    charts_out.sort(key=lambda chart: (chart["material"] != "", chart["material"], -len(chart["points"]), -chart["count"]))
    return charts_out


def _on_their_own_dates(values: list[dict], quoted) -> list[dict]:
    """Quoted values moved to the day their own line prints, and the copies among them dropped.

    Two things, because they are one act. A consultation that retells an earlier result is usually
    retelling a form this archive already holds — twenty-six of the twenty-eight quotations on the
    archive this was written against were exactly that — and once such a value is back on its own
    date it is a second point sitting on top of the first, in whatever unit the doctor happened to
    write out. Two points for one measurement is not a history, and the doctor's line is the copy:
    the form is the record, and the retelling is somebody's note about it.

    The two that are not copies stay. Their own forms were never scanned, and a quotation is the
    only surviving record of them — dropping those would lose a measurement to tidiness.

    A copy is recognised the way a person would: the same test, the same number, within a few days
    of the same day. Nothing is compared across tests and nothing is rounded.
    """
    moved = []
    for item in values:
        when = quoted.check.run(Value(item=item), quoted.settings)
        moved.append({**item, "date": when, "quoted_from": item.get("date"), "quoted": True} if when else item)
    # Only a row that is itself a result may stand in for a retelling. A form's "previous value"
    # column is a row this program lists and never draws — and read as a form it took the quotation
    # away and left the measurement of that day on no chart at all, represented by the one row that
    # is not drawn. values.py says of such a column that it "lands on the date of the form that
    # quoted it, which is a date no laboratory ever gave it": preferring it to the retelling is
    # preferring the record this program itself calls wrong.
    from_a_form = [item for item in moved
                   if not item.get("quoted") and item.get("date") and is_result(item)]  # fmt: skip
    # Which kept row stood in for how many retellings. Counted rather than mutated: a row that is
    # not a quotation is the caller's own dict, passed through untouched, and writing a count into
    # it would reach back into the values the page was built from. Kept because the page has to say
    # it: the heading counted every value this test has, the chart counts what it drew, and for one
    # archive those were 26 and 25 with nothing anywhere to say where the twenty-sixth went. A
    # count that differs from another count on the same page is a defect, not a detail.
    folded: dict[int, int] = {}
    kept = []
    for item in moved:
        if item.get("quoted"):
            stood_in = next((other for other in from_a_form if _the_same_measurement(item, other)), None)
            if stood_in is None:
                standing = next((other for other in kept
                                 if other.get("quoted") and _the_same_measurement(item, other)), None)  # fmt: skip
                # Between two retellings of one measurement, the one that says more stands in for
                # the other: one of them names the specimen and the unit and the other names
                # neither, and the chart the measurement lands on is the chart of whichever is
                # kept. Kept the wrong way round, the measurement left the blood chart for a chart
                # of its own with no unit and no specimen — which is the finding this answers, and
                # is why the specimen used to have to match exactly.
                if standing is not None and _says_more(item, standing):
                    kept[kept.index(standing)] = item
                    folded[id(item)] = folded.pop(id(standing), 0) + 1
                    continue
                stood_in = standing
            if stood_in is not None:
                folded[id(stood_in)] = folded.get(id(stood_in), 0) + 1
                continue
        kept.append(item)
    # And two doctors quoting one measurement are still one measurement — that is the second of the
    # two searches above. Seen on a real chart: a thyrotropin taken in January 2016 was retold in
    # three later consultations, its own form was never scanned, so nothing dropped any of them and
    # the chart drew one reading as three points standing on one day. The form is preferred where
    # there is one; where there is none, the first retelling is kept and the rest are the same
    # sentence said again.
    return [{**item, "folded_retellings": folded[id(item)]} if id(item) in folded else item
            for item in kept]  # fmt: skip


def _says_more(one: dict, other: dict) -> bool:
    """Whether this retelling names something about the measurement that the other one leaves out.

    Only the two things a chart is split by: which specimen was measured and at what scale. A
    retelling naming both is the one to keep, because the chart the measurement is drawn on is the
    chart of the row that was kept, and a row naming neither is drawn apart from everything.
    """
    said = [(bool((item.get("material") or "").strip()), bool(unit_key(item.get("unit")))) for item in (one, other)]
    return sum(said[0]) > sum(said[1])


#: How far apart a quotation and the form it quotes may be dated and still be the one measurement.
#: A note written from memory gives the week rather than the day, and a form is often signed days
#: after the sample was taken.
SAME_STUDY_DAYS = 45


def _the_same_measurement(quotation: dict, printed: dict) -> bool:
    one, other = number(quotation.get("value_numeric")), number(printed.get("value_numeric"))
    if one is None or other is None or one != other:
        return False
    # The same specimen, where both sides named one. Blood is never joined to urine anywhere else
    # here and it must not be joined by the back door either — but a retelling that named no
    # specimen at all has not named another one, and refusing it on that silence cost the owner
    # the chart he complained about: two doctors retold one prostate antigen of December, one of
    # them writing the specimen and the unit and one of them writing neither, and the second went
    # to a chart of its own with no unit and no specimen beside the chart it belongs on. Where the
    # two differ only in that one of them says less, the one that says more is the one kept — which
    # is the other half of this, below in _says_more, and without it the silent retelling stood in
    # for the one that named blood and took the whole measurement onto a chart of its own: that is
    # what happened to a thyrotropin of three consultations, and it is why this was written as an
    # exact match first.
    mine, theirs = (quotation.get("material") or ""), (printed.get("material") or "")
    if mine and theirs and mine != theirs:
        return False
    # And the same scale, where both sides named one. A quotation in millimoles and a form in
    # milligrams per decilitre are not one measurement however their digits agree, and read as one
    # the form took the quotation away and left a chart of two points with none: measured on
    # invented rows, adding a single document in the other unit destroyed the whole chart.
    #
    # Where one side printed no unit at all they are still one measurement, and this is not a
    # softening — it is the commonest shape there is. A doctor retelling a result writes the unit
    # out because his sentence needs it; the laboratory printout the retelling came from puts it in
    # a column heading the reader never transcribed. On the archive this was written against, every
    # prostate-antigen quotation carries "ng/ml" and every form holding the same number carries
    # nothing, so an exact match would have folded none of them and left the duplicates it was
    # built to remove.
    mine, theirs = unit_key(quotation.get("unit")), unit_key(printed.get("unit"))
    if mine and theirs and mine != theirs:
        return False
    if (quotation.get("indicator_id") or printed.get("indicator_id")) and \
            quotation.get("indicator_id") != printed.get("indicator_id"):  # fmt: skip
        return False
    try:
        apart = date.fromisoformat(str(quotation["date"])[:10]) - date.fromisoformat(str(printed["date"])[:10])
    except (KeyError, TypeError, ValueError):
        return False
    return abs(apart.days) <= SAME_STUDY_DAYS


def _one(placing, kind: str):
    """The rule of this kind that is on, or nothing. Each hook here asks for its own kind.

    The rules are handed in, already chosen by whoever asked for the chart: this file draws, and
    what an instance has turned on is not its business.
    """
    return next((rule for rule in placing if rule.kind == kind), None)


def _on_the_chart_it_landed_on(item: dict, unit_of_the_chart: str) -> dict:
    """This row with the unit of its chart on it, and a mark where that is what read its band.

    Two things, and they are one act. A form that printed both bands of one test on one line —
    "47 – 72 % 2,000 – 5,500*10⁹/л" — printed one of them for this chart, and the unit of the
    chart is the only thing on either side that says which; the row carries it so that every
    reader of a printed range on this page gets the same answer.

    And the mark, because the seventh entry of the constitution is not satisfied by getting it
    right quietly: a band drawn from a line that printed two is a band this program chose, and the
    page says so beside the value rather than in a footer. Nothing else in the program said it —
    the row prints the whole printed text, so a reader could see two bands there and could not see
    which one was drawn.
    """
    mine = {**item, "read_in": unit_of_the_chart}
    if reference.a_band_for_each_unit(item.get("reference")) and _printed_band_brought_along(mine):
        mine["band_by_its_unit"] = True
    return mine


def _charts_of(by_unit: dict[str, list[dict]], material: str, width: int, height: int, scale_rules=()) -> list[dict]:
    """The charts of one material: one per unit, after equivalent spellings are joined."""
    charts_out = []
    for unit_of_these, items in _join_equivalent(by_unit).items():
        # Before anything reads a printed range off these rows: which chart a row landed on is
        # what tells a line that printed one band per unit which of them stands beside this value.
        items = [_on_the_chart_it_landed_on(item, unit_of_these) for item in items]
        if scale_rules:
            items = _one_scale(items, scale_rules, unit_of_these)
        spellings: dict[str, int] = {}
        for item in items:
            printed = (item.get("unit") or "").strip()
            if printed:
                spellings[printed] = spellings.get(printed, 0) + 1
        unit = max(spellings, key=lambda name: spellings[name]) if spellings else ""
        # The label carries the slash the unit was meant to have. A backslash in a unit is a
        # Cyrillic keyboard's neighbouring key and nothing else, and the key this chart is grouped
        # under already reads it as a slash — but the label is chosen from the printed spellings,
        # so after the quotations that spelled it properly were folded away as copies this chart
        # was headed "нг\мл" and read as a merge that had failed. The value's own row still shows
        # what its form printed; this is the heading over several of them.
        unit = unit.replace("\\", "/")
        # A converted chart is labelled with the scale it was brought to, and says what it moved.
        moved = {}
        for item in items:
            done = item.get("converted")
            if done and done["factor"] != 1.0:
                moved[done["from_unit"] or "unit read from the printed range"] = done["factor"]
            if done:
                unit = done["to_unit"]
        # By date, always: joining two spellings puts one list after the other, and a line drawn
        # in that order runs backwards through the years. A value from a document whose date is
        # not settled has no place on the line — there is nowhere to put it — but it is a value
        # of this test, so it is listed last and counted, rather than disappearing from a page
        # whose heading counted it.
        items = sorted(items, key=lambda item: (item.get("date") is None, item.get("date") or ""))
        dated = [item for item in items if item.get("date")]
        undated = [item for item in items if not item.get("date")]
        # number(), not float(): a value stored as text — "4,2" from a reading that wrote it
        # with a comma — passed the filter and raised where the chart was drawn, turning the
        # whole page into a 500.
        numeric = [item for item in dated if number(item.get("value_numeric")) is not None and is_result(item)]
        other = [item for item in items if number(item.get("value_numeric")) is None]
        # rows, not points: a value the chart cannot draw is still a value, and it is listed.
        items = [{**item, "date_label": date_label(item)} for item in items]
        chart = {"unit": unit, "material": material, "converted_from": moved,
                 "spellings": sorted(spellings, key=lambda name: -spellings[name]),
                 "as_printed": other, "points": [], "count": len(items),
                 "by_numbers": sum(1 for item in items if item.get("unit_by_numbers")),
                 "scaled": sum(1 for item in items if item.get("scaled")),
                 "beside_the_result": sum(1 for item in items if not is_result(item)),
                 "folded": sum(item.get("folded_retellings", 0) for item in items),
                 "undated": len(undated), "rows": items}  # fmt: skip
        if len(numeric) >= MIN_POINTS:
            chart.update(_geometry(numeric, width, height))
        else:
            chart["not_drawn"] = _why_no_line(items, numeric)
        charts_out.append(chart)
    return charts_out


def _printed_band_brought_along(item: dict) -> tuple[float | None, float | None] | None:
    """The printed range, brought to the unit the chart is drawn in and nothing more.

    The range a form prints beside a value is in the unit that form used, the same as the value,
    so it converts exactly as the value did. This is the honest half of moving a band, and it is
    exact: a real conversion factor, not a power of ten.

    The chart's own unit travels on the row, under "read_in", because one line needs it to be
    read at all: a form that printed both bands of a blood count on one line — the per-cent
    corridor and the absolute one, each with its own unit — printed a band for this chart and a
    band for another, and the unit of the chart is what says which. A row with no chart yet, which
    is every row place_by_the_numbers is weighing up, has no unit in hand and gets no band from
    such a line: that is the truth about it, and preferring either half would be this program
    deciding what the form printed.
    """
    band = printed_range(item.get("reference"), item.get("read_in"))
    factor = (item.get("converted") or {}).get("factor") or 1.0
    if band is None or factor == 1.0:
        return band
    return tuple(None if edge is None else edge * factor for edge in band)


def _band_of(item: dict) -> tuple[float | None, float | None] | None:
    """The printed range of a value, on the scale that value is drawn on.

    Two things can move it, and they are not the same thing. The unit conversion moves it exactly,
    because the range is printed in the unit of the value beside it. The scale rule moves it by a
    power of ten, for the other case: a form that prints the range at a different scale from the
    result it stands beside. They used to be multiplied together over values where only the first
    had happened, because the rule was comparing converted numbers against unconverted ranges and
    saw a mismatch that the conversion had already explained.
    """
    band = _printed_band_brought_along(item)
    factor = (item.get("scaled") or {}).get("band_factor") or 1.0
    if band is None or factor == 1.0:
        return band
    return tuple(None if edge is None else edge * factor for edge in band)


def _geometry(items: list[dict], width: int, height: int) -> dict:
    days = [_days(item["date"]) for item in items]
    numbers = [number(item["value_numeric"]) for item in items]
    bands = [_band_of(item) for item in items]
    lows = [low for band in bands if band for low in (band[0],) if low is not None]
    highs = [high for band in bands if band for high in (band[1],) if high is not None]
    lowest = min([*numbers, *lows, *highs])
    highest = max([*numbers, *lows, *highs])
    if highest == lowest:
        lowest, highest = lowest - 1, highest + 1
    margin = (highest - lowest) * 0.08
    lowest, highest = lowest - margin, highest + margin
    first_day, last_day = min(days), max(days)
    span = max(last_day - first_day, 1)
    plot_width = width - PAD_LEFT - PAD_RIGHT
    plot_height = height - PAD_TOP - PAD_BOTTOM

    def x_of(day: int) -> float:
        return round(PAD_LEFT + (day - first_day) / span * plot_width, 2)

    def y_of(value: float) -> float:
        return round(PAD_TOP + (highest - value) / (highest - lowest) * plot_height, 2)

    points = []
    for item, day, value, band in zip(items, days, numbers, bands, strict=True):
        points.append({
            **item, "x": x_of(day), "y": y_of(value),
            "band_top": y_of(band[1]) if band and band[1] is not None else PAD_TOP,
            "band_bottom": y_of(band[0]) if band and band[0] is not None else PAD_TOP + plot_height,
            "has_band": bool(band),
        })  # fmt: skip
    return {
        "points": points,
        "line": " ".join(f"{point['x']},{point['y']}" for point in points),
        "bands": _bands(points, x_of, first_day, last_day),
        "y_ticks": _y_ticks(lowest, highest, y_of),
        "x_ticks": _x_ticks(items, x_of),
        "width": width, "height": height,
        "plot": {"left": PAD_LEFT, "right": width - PAD_RIGHT, "top": PAD_TOP, "bottom": height - PAD_BOTTOM},
        "first": items[0], "last": items[-1],
    }  # fmt: skip


def _bands(points: list[dict], x_of, first_day: int, last_day: int) -> list[dict]:
    """The printed range, around the value it was printed beside.

    Each band reaches half way to the point before it and half way to the point after, so the
    value it belongs to stands inside it. It used to run forward only — from its own point to the
    next — which put every value on the left edge of its own band and left it sitting against the
    band of the form before it, often another laboratory's. The newest value, the one a chart is
    usually opened for, had no band at all: two pixels at the right-hand edge, and it read as a
    value that had left the shaded area.

    A form that printed no range leaves a gap, and the gap is the truth: the range of the form
    before it says nothing about a value printed without one.
    """
    bands = []
    for index, point in enumerate(points):
        if not point["has_band"]:
            continue
        # At the two ends there is only one neighbour, so the half-width of the side that exists
        # is mirrored onto the side that does not. Without that the oldest and the newest value
        # each stand on the edge of their own band, and the newest is the one a person looks at.
        before = points[index - 1]["x"] if index else None
        after = points[index + 1]["x"] if index + 1 < len(points) else None
        reaches_back = (point["x"] - before) / 2 if before is not None else None
        reaches_on = (after - point["x"]) / 2 if after is not None else None
        reaches_back = reaches_back if reaches_back is not None else (reaches_on or 6)
        reaches_on = reaches_on if reaches_on is not None else reaches_back
        start = max(point["x"] - reaches_back, x_of(first_day))
        end = min(point["x"] + reaches_on, x_of(last_day))
        bands.append({"x": start, "width": max(end - start, 2), "y": point["band_top"],
                      "height": max(point["band_bottom"] - point["band_top"], 1)})  # fmt: skip
    return bands


def _y_ticks(lowest: float, highest: float, y_of) -> list[dict]:
    """Five marks up the side, each one saying a different number.

    A urine specific gravity runs from 1,004 to 1,025, and rounded the way an axis of whole
    numbers is rounded, all five marks read "1". So the axis keeps as many places as it takes
    for the marks to differ from one another.
    """
    step = (highest - lowest) / 4
    values = [lowest + step * index for index in range(5)]
    labels = [_label(value) for value in values]
    for places in range(2, 7):
        if len(set(labels)) == len(labels):
            break
        labels = [f"{value:.{places}f}" for value in values]
    return [{"y": y_of(value), "label": label} for value, label in zip(values, labels, strict=True)]


def _x_ticks(items: list[dict], x_of) -> list[dict]:
    years = sorted({item["date"][:4] for item in items})
    if len(years) > 8:
        years = [year for year in years if int(year) % 5 == 0] or years[:: max(1, len(years) // 6)]
    ticks = []
    for year in years:
        first = min(item["date"] for item in items if item["date"][:4] == year)
        ticks.append({"x": x_of(_days(first)), "label": year})
    return ticks


def _label(value: float) -> str:
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 1:
        return f"{value:.1f}".replace(".0", "")
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _days(text: str) -> int:
    return date.fromisoformat(text[:10]).toordinal()
