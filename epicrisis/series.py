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

from epicrisis import reference
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


def printed_range(text: str | None) -> tuple[float | None, float | None] | None:
    """The reference range as the form printed it: (low, high), either side open.

    One reader for the whole program. There were three — this one, reference.parse and the check
    in validate — and their vocabularies had already drifted apart: "менее 5" drew a band here
    and read as nothing there, and a range with its unit beside it ("3,5-5,5 ммоль/л") drew no
    band at all, so bands appeared on some points of one test and not on others.
    """
    return reference.parse(text)


def _join_equivalent(by_unit: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Join spellings of one measure where the numbers themselves say it is one measure."""
    middles = {
        key: median(values)
        for key, items in by_unit.items()
        if (values := [reading for item in items if (reading := number(item.get("value_numeric"))) is not None])
    }
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
    per-cent, and nothing on the page says so. Here the archive's own numbers say it — the middle
    of these values against the middle of each scale this test is drawn on, joined only where one
    scale is within a factor of two and no other scale is. Nothing is converted, and each value
    moved this way is marked, because this is the one reading taken from numbers and not from a
    form.
    """
    bare = by_unit.get("")
    middles = {
        key: median(numbers)
        for key, items in by_unit.items()
        if (numbers := [reading for item in items if (reading := number(item.get("value_numeric"))) is not None])
    }
    mine = middles.get("")
    if not bare or mine is None:
        return by_unit
    near = [key for key, theirs in middles.items()
            if key and len(by_unit[key]) >= settings["least_to_join"]
            and max(mine, theirs) <= settings["agreement"] * min(mine, theirs)]  # fmt: skip
    if len(near) != 1:
        return by_unit  # two scales it could belong to, or none: the numbers do not say
    moved = {key: items for key, items in by_unit.items() if key != ""}
    moved[near[0]] = [*moved[near[0]], *({**item, "unit_by_numbers": True} for item in bare)]
    return moved


def _one_scale(items: list[dict], scale_rules) -> list[dict]:
    """One test printed at two scales, drawn on one, by whichever rules are on.

    The rules are handed in rather than read from disk here: this file draws, and what an
    instance has turned on is not its business. Where more than one rule would move a series,
    the first one that moves anything decides it — two rules quietly moving the same points
    twice is the one thing worse than neither of them running.

    The printed value and its printed range stay exactly as they are in the rows beside the
    chart; only the point moves, and it carries what it was moved by.
    """
    series = Series(numbers=[number(item.get("value_numeric")) for item in items],
                    bands=[printed_range(item.get("reference")) for item in items])  # fmt: skip
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
        if not power and not band_power:
            moved.append(item)
            continue
        factor = 10.0**power
        moved.append({**item, "value_numeric": (number(item.get("value_numeric")) or 0) * factor,
                      "scaled": {"from_value": item.get("value"), "factor": factor,
                                 "band_factor": 10.0**band_power}})  # fmt: skip
    return moved


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


def _one(placing, kind: str):
    """The rule of this kind that is on, or nothing. Each hook here asks for its own kind.

    The rules are handed in, already chosen by whoever asked for the chart: this file draws, and
    what an instance has turned on is not its business.
    """
    return next((rule for rule in placing if rule.kind == kind), None)


def _charts_of(by_unit: dict[str, list[dict]], material: str, width: int, height: int, scale_rules=()) -> list[dict]:
    """The charts of one material: one per unit, after equivalent spellings are joined."""
    charts_out = []
    for items in _join_equivalent(by_unit).values():
        if scale_rules:
            items = _one_scale(items, scale_rules)
        spellings: dict[str, int] = {}
        for item in items:
            printed = (item.get("unit") or "").strip()
            if printed:
                spellings[printed] = spellings.get(printed, 0) + 1
        unit = max(spellings, key=lambda name: spellings[name]) if spellings else ""
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
                 "undated": len(undated), "rows": items}  # fmt: skip
        if len(numeric) >= MIN_POINTS:
            chart.update(_geometry(numeric, width, height))
        charts_out.append(chart)
    return charts_out


def _band_of(item: dict) -> tuple[float | None, float | None] | None:
    """The printed range of a value, on the scale that value is drawn on.

    Where the chart converts, the range printed beside the value is in the unit the form used,
    so it moves with the value or it is not drawn at all. Left where it was, it pinned the band
    to the floor of the chart and stretched the axis around a value sitting in the middle of it.
    """
    band = printed_range(item.get("reference"))
    factor = ((item.get("converted") or {}).get("factor") or 1.0) * ((item.get("scaled") or {}).get("band_factor") or 1.0)
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
    """The printed range, held from one form to the next: a step, not a smooth line."""
    bands = []
    for index, point in enumerate(points):
        if not point["has_band"]:
            continue
        start = point["x"] if index else x_of(first_day)
        following = points[index + 1] if index + 1 < len(points) else None
        end = following["x"] if following else x_of(last_day)
        if following is None or end > start:
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
