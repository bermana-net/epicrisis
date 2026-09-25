"""What this program knows about units: which spellings are one unit, and what converts to what.

One place to add a unit. Whether two spellings are the same measure lived with the charts, the
table of what converts into what lived here, and a unit named inside a printed reference range
lived here too — so adding one unit meant remembering all three.

The first half is reading: a spelling folded to a key, two keys that are the same measure, the
unit a printed range names. The second half is converting, which happens only when a person asks
for it.

Bringing values of one test to one scale, when a person asks for it:

Off by default, and off in the repository: the archive shows what the form printed. Turned on,
a chart of one test puts every value on the scale European forms print most often — creatinine
in µmol/L, urea and glucose in mmol/L, haemoglobin in g/L — so that a history written by four
laboratories in three unit systems can be read as one line.

What keeps this honest:

- Only the pairs in the table below are ever converted. An analyte or a unit that is not here
  keeps its own chart, untouched. Nothing is guessed from the size of a number.
- The printed value, its unit and its reference range stay exactly as they were, beside the
  chart. A converted point says what it was converted from and by what factor.
- Nothing converted is stored. The archive and the index hold the printed value alone; the
  conversion happens when the chart is drawn, and switching the setting off undoes it entirely.
- The factors are molar masses, and a wrong one moves a value by a factor of ten or twenty. So
  each factor is written once, here, with the analyte it belongs to, and each has a test.
"""

import re

from epicrisis.printed_values import fold


# One unit written several ways is one unit: "мкмоль/л", "мкМоль/л" and "umol/L" are the same
# measure in three alphabets. Two units of different size are not: mg/dL and мкмоль/л stay apart,
# because putting them on one axis would mean converting, and nothing here converts anything.
#
# Spellings are joined only where the joining is certain from the writing itself: the same power
# of ten written in five ways (10¹²/л, 10*12/л, 10E12/L, х10¹²/л, 1012/L), the same words in two
# alphabets, a cubic millimetre and a microlitre, which are the same volume by definition. "Т/л"
# and "Г/л" carry their prefix in a capital letter, and that is read before anything is folded,
# because "г/л" in small letters is grams and not giga. Everything else keeps its own chart:
# per litre and per microlitre are not joined, and a spelling that looks like a misreading
# ("10¹²/1") is left alone rather than guessed at.
PREFIXES = ((r"Т\s*/\s*л", "10^12/л"), (r"Г\s*/\s*л", "10^9/л"), (r"T\s*/\s*L", "10^12/l"))
SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
LETTERS = str.maketrans({"µ": "u", "μ": "u", " ": "", "·": "", "*": "", "х": "x"})
WORDS = [("мкмоль", "umol"), ("ммоль", "mmol"), ("моль", "mol"), ("мкг", "ug"), ("мг", "mg"), ("нг", "ng"),
         ("пг", "pg"), ("мл", "ml"), ("дл", "dl"), ("мкл", "ul"), ("ед", "u"), ("г", "g"), ("л", "l")]  # fmt: skip
CELL_WORDS = ("клітин", "клеток", "клетки", "cells", "cell", "ery", "кл.", "лейко", "эритро", "еритро", "wbc", "rbc")
# Counting under a microscope is written a dozen ways in four languages and means one thing:
# what one field of view holds. The words differ, the measure does not.
FIELD = ("вполізору", "вполезрения", "вполязрения", "вп/зр", "вп./зр", "вп/з", "п/з", "п/зр", "полезрения", "полізору")
EXPONENT = re.compile(r"10\^?e?(3|6|9|12)(?![0-9])", re.IGNORECASE)


def unit_key(unit: str | None) -> str:
    """What two spellings of one unit have in common. Nothing about size or kind."""
    text = (unit or "").strip()
    for pattern, plain in PREFIXES:
        text = re.sub(rf"(?<![A-Za-zА-Яа-яЁё]){pattern}(?![A-Za-zА-Яа-яЁё])", plain, text)
    text = text.translate(SUPERSCRIPT).casefold().translate(LETTERS)
    for word in CELL_WORDS:
        text = text.replace(word, "")
    text = text.replace("гр", "г")
    if "hpf" in text or text.strip("/.") in FIELD:
        return "hpf"
    for cyrillic, latin in WORDS:
        text = text.replace(cyrillic, latin)
    text = text.replace("mm3", "ul").replace("mm³", "ul").replace("gr/", "g/").strip("().,;")
    if text in ("мм/l", "mm/l"):
        return "mmol/l"  # millimolar written as mM is millimoles per litre
    text = EXPONENT.sub(lambda found: f"10^{found.group(1)}", text)
    return text.lstrip("x")


# A litre holds a million microlitres, so "10⁶/µL" and "10¹²/л" are one measure written two ways,
# with the same numbers on the page. Such a pair is joined only when the archive's own numbers
# agree: both sides have at least two values and their middles are within a factor of two. That
# keeps cells per microlitre in urine, which are counted from zero, away from cells per litre in
# blood, which are counted in millions, even when a spelling is ambiguous.
PER_LITRE = re.compile(r"^(?:10\^(\d+))?/(l|ul)$")
AGREEMENT = 2.0
MIN_TO_JOIN = 2


def same_measure(key: str) -> int | None:
    """The power of ten this spelling counts in, per litre, or None when it does not say."""
    found = PER_LITRE.match(key)
    if not found:
        return None
    exponent = int(found.group(1) or 0)
    return exponent + 6 if found.group(2) == "ul" else exponent


def says_its_power(key: str) -> bool:
    """Whether the spelling writes its power of ten out, which makes the measure exact.

    "10³/mm³" and "10⁹/L" are one measure by arithmetic alone — a litre holds a million cubic
    millimetres — and no reading of the numbers is needed to know it. A bare "/µL" beside a bare
    "/L" is a different matter: neither says a power, and only the archive's own numbers can say
    whether one lab meant what the other did.
    """
    found = PER_LITRE.match(key)
    return bool(found and found.group(1))


# analyte -> the scale it is brought to, and what one unit of another kind is worth in it.
# Factors are the usual molar conversions; where a unit differs only by a prefix, the factor is
# exact. Cell counts are not here: 10⁹/L and 10³/µL are the same measure written two ways, and
# same_measure above joins those without arithmetic.
SCALES: dict[str, dict] = {
    "creatinine": {"unit": "мкмоль/л", "key": "umol/l", "from": {"mg/dl": 88.4, "mmol/l": 1000.0, "umol/l": 1.0}},
    "urea": {"unit": "ммоль/л", "key": "mmol/l", "from": {"mg/dl": 0.1665, "mmol/l": 1.0, "umol/l": 0.001}},
    "glucose": {"unit": "ммоль/л", "key": "mmol/l", "from": {"mg/dl": 0.0555, "mmol/l": 1.0}},
    "uric acid": {"unit": "мкмоль/л", "key": "umol/l", "from": {"mg/dl": 59.48, "mmol/l": 1000.0, "umol/l": 1.0}},
    "bilirubin": {"unit": "мкмоль/л", "key": "umol/l", "from": {"mg/dl": 17.1, "mmol/l": 1000.0, "umol/l": 1.0}},
    "cholesterol": {"unit": "ммоль/л", "key": "mmol/l", "from": {"mg/dl": 0.02586, "mmol/l": 1.0}},
    "triglyceride": {"unit": "ммоль/л", "key": "mmol/l", "from": {"mg/dl": 0.01129, "mmol/l": 1.0}},
    "calcium": {"unit": "ммоль/л", "key": "mmol/l", "from": {"mg/dl": 0.2495, "mmol/l": 1.0}},
    "phosphate": {"unit": "ммоль/л", "key": "mmol/l", "from": {"mg/dl": 0.3229, "mmol/l": 1.0}},
    "magnesium": {"unit": "ммоль/л", "key": "mmol/l", "from": {"mg/dl": 0.4114, "mmol/l": 1.0}},
    "iron": {"unit": "мкмоль/л", "key": "umol/l", "from": {"ug/dl": 0.1791, "umol/l": 1.0}},
    "protein": {"unit": "г/л", "key": "g/l", "from": {"g/dl": 10.0, "g/l": 1.0}},
    "albumin": {"unit": "г/л", "key": "g/l", "from": {"g/dl": 10.0, "g/l": 1.0}},
    "hemoglobin": {"unit": "г/л", "key": "g/l", "from": {"g/dl": 10.0, "g/l": 1.0}},
}

# Which indicator a scale belongs to. An id has to match one of these exactly: a ratio, a urine
# collection or a fraction is a different measurement and must not borrow another's factor.
INDICATORS: dict[str, str] = {
    "creatinine": "creatinine",
    "urea": "urea",
    "glucose": "glucose", "fasting-glucose": "glucose",
    "uric-acid": "uric acid",
    "bilirubin": "bilirubin", "total-bilirubin": "bilirubin", "direct-bilirubin": "bilirubin", "free-bilirubin": "bilirubin",
    "total-cholesterol": "cholesterol", "hdl-cholesterol": "cholesterol", "ldl-cholesterol": "cholesterol",
    "non-hdl-cholesterol": "cholesterol", "vldl-cholesterol": "cholesterol",
    "triglyceride": "triglyceride",
    "total-calcium": "calcium", "calcium": "calcium", "ionized-calcium": "calcium",
    "phosphate": "phosphate", "phosphorus": "phosphate", "inorganic-phosphorus": "phosphate",
    "magnesium": "magnesium",
    "iron": "iron", "serum-iron": "iron",
    "total-protein": "protein", "protein": "protein",
    "albumin": "albumin",
    "hemoglobin": "hemoglobin",
}  # fmt: skip

# A unit written in the reference range beside a value, where the value itself carries none.
# "53-115 мкмоль/л" says the scale as plainly as a unit column would.
REFERENCE_UNITS = (
    ("umol/l", ("мкмоль/л", "мкмоль/ л", "мкм/л", "µmol/l", "umol/l", "μmol/l")),
    ("mmol/l", ("ммоль/л", "мм/л", "мМ/л", "mmol/l", "mm/l", "ммол/л")),
    ("mg/dl", ("мг/дл", "mg/dl", "мг%")),
    ("g/l", ("г/л", "g/l", "гр/л")),
    ("g/dl", ("г/дл", "g/dl")),
    # The prefixed spellings stand in the table in their own right. Without them "мг/л" and
    # "мкг/л" were read as "г/л", which is the same range a thousand or a million times over.
    ("mg/l", ("мг/л", "mg/l")),
    ("ug/l", ("мкг/л", "ug/l", "µg/l", "μg/l")),
    ("ng/l", ("нг/л", "ng/l")),
    ("ng/ml", ("нг/мл", "ng/ml")),
    ("pg/ml", ("пг/мл", "pg/ml")),
    ("ug/dl", ("мкг/дл", "ug/dl", "µg/dl")),
    ("mg/dl", ("мг/дл", "mg/dl", "мг%")),
    ("u/l", ("ед/л", "од/л", "е/л", "u/l", "iu/l")),
)


# The printed name has to say the analyte too. The factor depends on a molar mass, so it hangs on
# the analyte being the one the table means, and that a name was grouped under an indicator is a
# model's judgement. An abbreviation nobody can read alone ("Cr.", which is also chromium) is left
# unconverted rather than multiplied by a guess.
NAMES: dict[str, tuple[str, ...]] = {
    "creatinine": ("креатинин", "креатинін", "креатинiн", "creatinin", "creatinina", "creatinine", "kreatinin", "κρεατινιν"),
    "urea": ("мочевина", "сечовина", "urea", "ουρια", "ουρία", "harnstoff"),
    "glucose": ("глюкоз", "цукор", "glucos", "glucosa", "glukos", "γλυκοζ", "σακχαρ"),
    "uric acid": ("сечова кислота", "сечова к-та", "мочевая кислота", "мочевая к-та", "uric acid", "urato", "ουρικο"),
    "bilirubin": ("білірубін", "билирубин", "bilirrubina", "bilirubin", "χολερυθρ"),
    "cholesterol": ("холестерин", "холестерол", "colesterol", "cholesterol", "χοληστερ"),
    "triglyceride": ("тригліцерид", "триглицерид", "triglicérido", "triglicerido", "triglyceride", "τριγλυκερ"),
    "calcium": ("кальцій", "кальций", "calcio", "calcium", "ασβεστιο"),
    "phosphate": ("фосфор", "фосфат", "fósforo", "fosforo", "fosfato", "phosphate", "phosphorus", "φωσφορ"),
    "magnesium": ("магній", "магний", "magnesio", "magnesium", "μαγνησιο"),
    "iron": ("залізо", "железо", "hierro", "iron", "σιδηρο"),
    "protein": ("білок", "белок", "proteína", "proteina", "protein", "πρωτεΐν", "πρωτειν"),
    "albumin": ("альбумін", "альбумин", "albúmina", "albumina", "albumin", "λευκωματ"),
    "hemoglobin": ("гемоглоб", "hemoglobin", "haemoglobin", "hemoglobina", "hgb", "αιμοσφαιρ"),
}


# The id an indicator was given when its label had no letters an address could carry.
OPAQUE_ID = re.compile(r"^indicator(-\d+)?$")


def name_says_analyte(printed_name: str | None, analyte: str) -> bool:
    """Whether the name on the form names this analyte itself, not only the group it was put in."""
    folded = fold(printed_name or "")
    return any(fold(word) in folded for word in NAMES.get(analyte, ()))


def scale_of(indicator_id: str | None, printed_name: str | None = None) -> dict | None:
    """The scale this indicator is brought to, or None when it is not one this table knows."""
    analyte = analyte_of(indicator_id, printed_name)
    return SCALES.get(analyte) if analyte else None


def analyte_of(indicator_id: str | None, printed_name: str | None = None) -> str | None:
    """Which analyte a value is of: by the indicator's id, or by the name printed on the form.

    The id is a slug of whatever the person called the group, so an archive whose labels are
    written in Cyrillic or Greek has ids this table cannot match and conversion was silently
    inert for it — on exactly the archives the conversion was written for. The printed name is
    the same evidence the conversion already requires before it will move a value at all.
    """
    identifier = (indicator_id or "").strip()
    known = INDICATORS.get(identifier)
    if known:
        return known
    # Only where the id says nothing at all. An id this table does not hold is usually a decision
    # rather than a gap — "urine-creatinine" is left out on purpose, because a urine collection is
    # not a serum measurement and must not borrow its factor. The gap this fills is the opaque id
    # an archive with Cyrillic or Greek labels used to get, which named nothing.
    # A value in no group at all is not converted either: which values are one test is a
    # person's judgement, and the factor hangs on it.
    if not identifier or not OPAQUE_ID.match(identifier):
        return None
    for analyte in SCALES:
        if name_says_analyte(printed_name, analyte):
            return analyte
    return None


def convert(value: float | None, unit_key: str, indicator_id: str | None, printed_name: str | None = None) -> tuple[float, str, float] | None:
    """(value on the common scale, its unit as written, the factor used), or None when not converted."""
    analyte = analyte_of(indicator_id, printed_name)
    scale = SCALES.get(analyte) if analyte else None
    if scale is None or value is None or not name_says_analyte(printed_name, analyte):
        return None
    factor = scale["from"].get(unit_key)
    if factor is None:
        return None
    return value * factor, scale["unit"], factor


# A range that is nothing but numbers and a per-cent sign says its unit as plainly as a column
# would: "19,0-37,0%" is a percentage and cannot be anything else. A range holding two ranges —
# "19 - 37 % 1,200 - 3,000*10⁹/л", the relative and the absolute count on one line — says two
# things, and which of them the value belongs to is not written anywhere, so it says nothing here.
PER_CENT_RANGE = re.compile(r"^[\d\s.,;:–—+-]*\d[\d\s.,;:–—+-]*%$")


def unit_from_reference(reference: str | None) -> str | None:
    """The unit named inside a printed reference range, for a value whose own unit is missing.

    The longest spelling that occurs wins, not the first one in the table. "г/л" is inside
    "мкг/дл", "мг/л" and "нг/л": read in table order, a range printed in micrograms was read as
    grams and a value put on an axis a thousand times off, under a heading naming the wrong unit.
    """
    text = fold(reference or "")
    if not text or not re.search(r"\d", text):
        return None
    found = [(len(spelling), key) for key, spellings in REFERENCE_UNITS
             for spelling in spellings if fold(spelling) in text]  # fmt: skip
    if found:
        return max(found)[1]
    return "%" if PER_CENT_RANGE.match(text.strip().strip("[]()").strip()) else None
