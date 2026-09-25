"""A whole instance of make-believe: archives nobody lived, built without a model.

Screenshots of this program show somebody's medical records, and there is exactly one archive
on this machine that may appear in them — one that never happened. So the demo is generated:
people who do not exist, clinics that do not exist, a decade of forms in five languages, and
values chosen to look like a laboratory's rather than to mean anything.

It is also the only way to try the program without sending a page anywhere. The forms are drawn
here as images, the transcription that a model would have produced is written here beside them,
and the steps that need no model — the checks and the index — are then run for real. What comes
out is a working instance: every page fills, the charts draw, the checks find things, and not
one call leaves the machine.

Three archives, because that is how the program is used: a person keeps their own, and then
their father's, and then their grandmother's, and the whole point is that the three never touch.
Each life moves between countries, so one test is printed in five languages and in two sets of
units, which is the thing the program exists to survive.

Nothing here is medical advice, a real reference range, or a real person's result. The numbers
are made up to sit inside the ranges printed next to them, except where a life is written to
drift, and then they drift the way a chart is meant to show.
"""

import functools
import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# The demo draws its own pages, so it needs a face to draw them with. Debian and Ubuntu keep the
# Liberation fonts where the first path says; macOS and the rest keep their own somewhere else.
# A demo that dies inside an imaging library because a file is missing teaches nobody anything.
FONT_CHOICES = {
    "serif": ("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
              "/usr/share/fonts/liberation/LiberationSerif-Regular.ttf",
              "/Library/Fonts/Times New Roman.ttf", "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
              "C:/Windows/Fonts/times.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
    "serif_bold": ("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
                   "/usr/share/fonts/liberation/LiberationSerif-Bold.ttf",
                   "/Library/Fonts/Times New Roman Bold.ttf",
                   "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
                   "C:/Windows/Fonts/timesbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
    "mono": ("/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
             "/usr/share/fonts/liberation/LiberationMono-Regular.ttf",
             "/System/Library/Fonts/Menlo.ttc", "C:/Windows/Fonts/consola.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
}  # fmt: skip

# Laboratories that do not exist, in the languages this archive is built to read. Two of them
# stand in one city and print in different languages, which is not an invention.
CLINICS = [
    ("Медичний центр «Лісова»", "uk", "Київ"),
    ("Медицинский центр «Дарница»", "ru", "Киев"),
    ("Laboratorio Clínico Puentes", "es", "Valencia"),
    ("Northfield Medical Laboratory", "en", "Leeds"),
    ("Ιατρικό Εργαστήριο Αιγαίου", "el", "Ρόδος"),
]

# One analyte as five laboratories print it: the spellings an indicator has to gather.
# (label, printed name, unit, printed range, the middle to draw from and its digits) — the last
# four keyed by language, because a laboratory that prints mg/dL prints a different number for
# the same blood than one that prints µmol/L, and a demo that got that wrong would be the first
# thing a doctor noticed.
BLOOD = [
    ("Haemoglobin",
     {"uk": "Гемоглобін", "ru": "Гемоглобин", "es": "Hemoglobina", "en": "Haemoglobin", "el": "Αιμοσφαιρίνη"},
     {"uk": "г/л", "ru": "г/л", "es": "g/dL", "en": "g/L", "el": "g/dL"},
     {"uk": "120-150", "ru": "120-150", "es": "12,0 - 16,0", "en": "120-150", "el": "12,0 - 16,0"},
     {"uk": ((134, 7), 0), "ru": ((134, 7), 0), "es": ((13.4, 0.7), 1), "en": ((134, 7), 0), "el": ((13.4, 0.7), 1)}),
    ("Erythrocyte",
     {"uk": "Еритроцити", "ru": "Эритроциты", "es": "Hematíes", "en": "Red cells", "el": "Ερυθρά"},
     {"uk": "10¹²/л", "ru": "10¹²/л", "es": "x10⁶/µL", "en": "10¹²/L", "el": "x10⁶/µL"},
     {"uk": "3,9-4,7", "ru": "3,9-4,7", "es": "4,0 - 5,2", "en": "3,9-4,7", "el": "4,0 - 5,2"},
     {lang: ((4.4, 0.2), 2) for lang in ("uk", "ru", "es", "en", "el")}),
    ("Leukocyte",
     {"uk": "Лейкоцити", "ru": "Лейкоциты", "es": "Leucocitos", "en": "White cells", "el": "Λευκά"},
     {"uk": "10⁹/л", "ru": "10⁹/л", "es": "x10³/µL", "en": "10⁹/L", "el": "x10³/µL"},
     {"uk": "4,0-9,0", "ru": "4,0-9,0", "es": "4,0 - 10,0", "en": "4,0-9,0", "el": "4,0 - 10,0"},
     {lang: ((6.1, 1.1), 1) for lang in ("uk", "ru", "es", "en", "el")}),
    ("Platelet",
     {"uk": "Тромбоцити", "ru": "Тромбоциты", "es": "Plaquetas", "en": "Platelets", "el": "Αιμοπετάλια"},
     {"uk": "10⁹/л", "ru": "10⁹/л", "es": "x10³/µL", "en": "10⁹/L", "el": "x10³/µL"},
     {"uk": "150-400", "ru": "150-400", "es": "150 - 400", "en": "150-400", "el": "150 - 400"},
     {lang: ((248, 42), 0) for lang in ("uk", "ru", "es", "en", "el")}),
    ("Creatinine",
     {"uk": "Креатинін", "ru": "Креатинин", "es": "Creatinina", "en": "Creatinine", "el": "Κρεατινίνη"},
     {"uk": "мкмоль/л", "ru": "мкмоль/л", "es": "mg/dL", "en": "µmol/L", "el": "mg/dL"},
     {"uk": "53-97", "ru": "53-97", "es": "0,51 - 0,95", "en": "53-97", "el": "0,51 - 0,95"},
     {"uk": ((71, 6), 0), "ru": ((71, 6), 0), "es": ((0.8, 0.07), 2), "en": ((71, 6), 0), "el": ((0.8, 0.07), 2)}),
    ("Glucose",
     {"uk": "Глюкоза", "ru": "Глюкоза", "es": "Glucosa", "en": "Glucose", "el": "Γλυκόζη"},
     {"uk": "ммоль/л", "ru": "ммоль/л", "es": "mg/dL", "en": "mmol/L", "el": "mg/dL"},
     {"uk": "3,9-5,8", "ru": "3,9-5,8", "es": "70 - 100", "en": "3,9-5,8", "el": "70 - 100"},
     {"uk": ((5.0, 0.3), 1), "ru": ((5.0, 0.3), 1), "es": ((90, 5), 0), "en": ((5.0, 0.3), 1), "el": ((90, 5), 0)}),
    ("Total cholesterol",
     {"uk": "Холестерин загальний", "ru": "Холестерин общий", "es": "Colesterol total", "en": "Total cholesterol", "el": "Χοληστερόλη"},
     {"uk": "ммоль/л", "ru": "ммоль/л", "es": "mg/dL", "en": "mmol/L", "el": "mg/dL"},
     {"uk": "до 5,2", "ru": "до 5,2", "es": "< 200", "en": "< 5,2", "el": "< 200"},
     {"uk": ((4.9, 0.4), 1), "ru": ((4.9, 0.4), 1), "es": ((190, 15), 0), "en": ((4.9, 0.4), 1), "el": ((190, 15), 0)}),
    ("ALT",
     {"uk": "АЛТ", "ru": "АЛТ", "es": "ALT (GPT)", "en": "ALT", "el": "SGPT"},
     {"uk": "од/л", "ru": "ед/л", "es": "U/L", "en": "U/L", "el": "U/L"},
     {"uk": "до 33", "ru": "до 33", "es": "< 33", "en": "< 33", "el": "< 33"},
     {lang: ((22, 6), 0) for lang in ("uk", "ru", "es", "en", "el")}),
    ("TSH",
     {"uk": "ТТГ", "ru": "ТТГ", "es": "TSH", "en": "TSH", "el": "TSH"},
     {"uk": "мМО/л", "ru": "мМЕ/л", "es": "µUI/mL", "en": "mIU/L", "el": "µIU/mL"},
     {"uk": "0,4-4,0", "ru": "0,4-4,0", "es": "0,40 - 4,00", "en": "0,4-4,0", "el": "0,40 - 4,00"},
     {lang: ((1.9, 0.4), 2) for lang in ("uk", "ru", "es", "en", "el")}),
]

# A second panel, ordered less often, so some charts are dense and some are four points over ten
# years — which is what an archive looks like and what the pages have to survive.
SOMETIMES = [
    ("HbA1c",
     {"uk": "Глікований гемоглобін", "ru": "Гликированный гемоглобин", "es": "Hemoglobina A1c",
      "en": "HbA1c", "el": "Γλυκοζυλιωμένη αιμοσφαιρίνη"},
     {lang: "%" for lang in ("uk", "ru", "es", "en", "el")},
     {"uk": "4,8-5,9", "ru": "4,8-5,9", "es": "< 5,7", "en": "4,8-5,9", "el": "< 5,7"},
     {lang: ((5.3, 0.15), 1) for lang in ("uk", "ru", "es", "en", "el")}),
    ("Ferritin",
     {"uk": "Феритин", "ru": "Ферритин", "es": "Ferritina", "en": "Ferritin", "el": "Φερριτίνη"},
     {"uk": "нг/мл", "ru": "нг/мл", "es": "ng/mL", "en": "µg/L", "el": "ng/mL"},
     {"uk": "13-150", "ru": "13-150", "es": "13 - 150", "en": "13-150", "el": "13 - 150"},
     {lang: ((48, 10), 0) for lang in ("uk", "ru", "es", "en", "el")}),
    ("Vitamin D",
     {"uk": "Вітамін D (25-OH)", "ru": "Витамин D (25-OH)", "es": "Vitamina D (25-OH)",
      "en": "Vitamin D (25-OH)", "el": "Βιταμίνη D (25-OH)"},
     {"uk": "нг/мл", "ru": "нг/мл", "es": "ng/mL", "en": "nmol/L", "el": "ng/mL"},
     {"uk": "30-100", "ru": "30-100", "es": "30 - 100", "en": "75-250", "el": "30 - 100"},
     {"uk": ((32, 6), 0), "ru": ((32, 6), 0), "es": ((32, 6), 0), "en": ((80, 15), 0), "el": ((32, 6), 0)}),
    ("HDL cholesterol",
     {"uk": "Холестерин ЛПВЩ", "ru": "Холестерин ЛПВП", "es": "Colesterol HDL",
      "en": "HDL cholesterol", "el": "HDL χοληστερόλη"},
     {"uk": "ммоль/л", "ru": "ммоль/л", "es": "mg/dL", "en": "mmol/L", "el": "mg/dL"},
     {"uk": "від 1,2", "ru": "от 1,2", "es": "> 50", "en": "> 1,2", "el": "> 50"},
     {"uk": ((1.6, 0.2), 2), "ru": ((1.6, 0.2), 2), "es": ((62, 8), 0), "en": ((1.6, 0.2), 2), "el": ((62, 8), 0)}),
    ("Triglyceride",
     {"uk": "Тригліцериди", "ru": "Триглицериды", "es": "Triglicéridos", "en": "Triglycerides", "el": "Τριγλυκερίδια"},
     {"uk": "ммоль/л", "ru": "ммоль/л", "es": "mg/dL", "en": "mmol/L", "el": "mg/dL"},
     {"uk": "до 1,7", "ru": "до 1,7", "es": "< 150", "en": "< 1,7", "el": "< 150"},
     {"uk": ((1.3, 0.3), 2), "ru": ((1.3, 0.3), 2), "es": ((115, 26), 0), "en": ((1.3, 0.3), 2), "el": ((115, 26), 0)}),
    ("Serum iron",
     {"uk": "Залізо сироватки", "ru": "Железо сыворотки", "es": "Hierro", "en": "Serum iron", "el": "Σίδηρος"},
     {"uk": "мкмоль/л", "ru": "мкмоль/л", "es": "µg/dL", "en": "µmol/L", "el": "µg/dL"},
     {"uk": "10,7-32,2", "ru": "10,7-32,2", "es": "60 - 180", "en": "10,7-32,2", "el": "60 - 180"},
     {"uk": ((17, 4), 1), "ru": ((17, 4), 1), "es": ((95, 22), 0), "en": ((17, 4), 1), "el": ((95, 22), 0)}),
    # A rate the laboratory calculated rather than measured: the index marks it derived by itself.
    ("eGFR",
     {"uk": "ШКФ (CKD-EPI)", "ru": "СКФ (CKD-EPI)", "es": "FG estimado (CKD-EPI)",
      "en": "eGFR (CKD-EPI)", "el": "eGFR (CKD-EPI)"},
     {"uk": "мл/хв/1,73 м²", "ru": "мл/мин/1,73 м²", "es": "mL/min/1,73 m²",
      "en": "mL/min/1.73m²", "el": "mL/min/1,73 m²"},
     {"uk": "понад 90", "ru": "более 90", "es": "> 90", "en": "> 90", "el": "> 90"},
     {lang: ((93, 7), 0) for lang in ("uk", "ru", "es", "en", "el")}),
]

# Values that are words, so a chart has something it cannot draw and says so — and a second
# specimen, so the charts have to be kept apart by what was measured.
URINE = [
    ("Colour",
     {"uk": "Колір", "ru": "Цвет", "en": "Colour", "es": "Color", "el": "Χρώμα"}, "", "",
     {"uk": ["солом'яний", "світло-жовтий"], "ru": ["светло-жёлтый", "жёлтый"],
      "en": ["straw", "pale yellow", "yellow"], "es": ["amarillo pálido", "ámbar"],
      "el": ["αχυρόχρουν", "ωχροκίτρινο"]}),
    ("Transparency",
     {"uk": "Прозорість", "ru": "Прозрачность", "en": "Appearance", "es": "Aspecto", "el": "Διαύγεια"}, "", "",
     {"uk": ["прозора"], "ru": ["прозрачная"], "en": ["clear"], "es": ["transparente"], "el": ["διαυγή"]}),
    ("Protein",
     {"uk": "Білок", "ru": "Белок", "en": "Protein", "es": "Proteínas", "el": "Λεύκωμα"},
     {"uk": "г/л", "ru": "г/л", "en": "g/L", "es": "g/L", "el": "g/L"},
     {"uk": "до 0,033", "ru": "до 0,033", "en": "< 0,15", "es": "< 0,15", "el": "< 0,15"},
     {"uk": ["не виявлено", "0,033"], "ru": ["отсутствует", "0,033"],
      "en": ["not detected", "negative"], "es": ["no detectado", "negativo"],
      "el": ["αρνητικό", "μη ανιχνεύσιμο"]}),
    ("Leukocyte",
     {"uk": "Лейкоцити", "ru": "Лейкоциты", "en": "Leukocytes", "es": "Leucocitos", "el": "Πυοσφαίρια"},
     {"uk": "в п/з", "ru": "в п/з", "en": "per HPF", "es": "por campo", "el": "κ.ο.π."},
     {"uk": "0-5", "ru": "0-5", "en": "0-5", "es": "0 - 5", "el": "0 - 5"},
     {"uk": ["1-2", "2-4"], "ru": ["1-2", "0-1"], "en": ["1-2", "0-1", "2-4"],
      "es": ["1-2", "0-1"], "el": ["1-2", "0-1"]}),
]

# A third specimen, once or twice in a life, which is exactly how a real archive holds it.
STOOL = [
    ("Occult blood",
     {"uk": "Прихована кров", "ru": "Скрытая кровь", "en": "Faecal occult blood",
      "es": "Sangre oculta en heces", "el": "Αιμοσφαιρίνη κοπράνων"}, "",
     {"uk": "негативний", "ru": "отрицательная", "en": "negative", "es": "negativo", "el": "αρνητικό"},
     {"uk": ["негативний"], "ru": ["отрицательная"], "en": ["negative"], "es": ["negativo"],
      "el": ["αρνητικό"]}),
    ("Stool consistency",
     {"uk": "Консистенція", "ru": "Консистенция", "en": "Consistency", "es": "Consistencia",
      "el": "Σύσταση"}, "", "",
     {"uk": ["оформлений"], "ru": ["оформленный"], "en": ["formed"], "es": ["formada"],
      "el": ["σχηματισμένα"]}),
]

PAGE = (1240, 1754)  # A4 at 150 dpi, which is what a home scanner gives


@dataclass(frozen=True)
class Life:
    """One person's archive: where they were, how often they were tested, and what drifted."""

    whose: str
    born: str
    folder: str
    years: range
    # (from this year, this laboratory) — a life that moves countries, so one test is printed
    # in two sets of units and the program has to keep it one test all the same.
    where: tuple[tuple[int, int], ...]
    panels: int = 2
    drift: dict[str, tuple[tuple[int, float], ...]] = field(default_factory=dict)
    # What a consultation prints under its text, in the language of the clinic printing it.
    diagnoses: dict[str, tuple[str, ...]] = field(default_factory=dict)
    medications: dict[str, tuple[str, ...]] = field(default_factory=dict)
    urine_every: int = 2
    stool_in: tuple[int, ...] = ()


LIVES = [
    # The archive most of the pictures are taken from: a life in England, with three years
    # abroad in the middle of it, so one test is printed in two sets of units without anybody
    # moving house twice for the sake of a screenshot.
    Life(
        whose="Vera Lindqvist", born="14.03.1971", folder="archive-of-vera-lindqvist",
        years=range(2013, 2026),
        where=((2013, 3), (2019, 2), (2022, 3)),
        # Nothing dramatic: iron that falls and is put right, and cholesterol that creeps up
        # with the years — the two shapes a person actually recognises in their own chart.
        drift={"Ferritin": ((2013, 1.05), (2017, 0.42), (2019, 0.55), (2021, 1.0), (2025, 1.05)),
               "Serum iron": ((2013, 1.0), (2017, 0.62), (2019, 0.75), (2021, 1.0), (2025, 1.0)),
               "Haemoglobin": ((2013, 1.0), (2017, 0.92), (2019, 0.97), (2021, 1.0), (2025, 1.0)),
               "Total cholesterol": ((2013, 0.93), (2025, 1.12)),
               "Vitamin D": ((2013, 0.95), (2019, 1.1), (2025, 1.1))},
        urine_every=2, stool_in=(2021,),
    ),
    # Her father: forty years of forms in one language, and then a move, in his seventies, to
    # forms in another. Type 2 diabetes found in 2016, treated from 2018, and the kidney that
    # slowly answers for it — the reason a family keeps an archive at all.
    Life(
        whose="Anders Lindqvist", born="02.11.1944", folder="archive-of-anders-lindqvist",
        years=range(2011, 2026), panels=3,
        where=((2011, 1), (2019, 3)),
        drift={"HbA1c": ((2011, 1.0), (2015, 1.12), (2016, 1.62), (2018, 1.74), (2019, 1.44),
                         (2021, 1.34), (2025, 1.30)),
               "Glucose": ((2011, 1.0), (2015, 1.1), (2016, 1.55), (2018, 1.62), (2019, 1.3),
                           (2025, 1.24)),
               "Creatinine": ((2011, 1.0), (2016, 1.08), (2020, 1.2), (2025, 1.34)),
               "eGFR": ((2011, 1.0), (2016, 0.95), (2020, 0.82), (2025, 0.7)),
               "Triglyceride": ((2011, 1.1), (2016, 1.5), (2019, 1.05), (2025, 1.0)),
               "Total cholesterol": ((2011, 1.05), (2016, 1.18), (2019, 0.82), (2025, 0.8))},
        diagnoses={"uk": ("Цукровий діабет 2 типу, стан компенсації",
                          "Артеріальна гіпертензія 2 ступеня"),
                   "ru": ("Сахарный диабет 2 типа, состояние компенсации",
                          "Артериальная гипертензия 2 степени"),
                   "es": ("Diabetes mellitus tipo 2, buen control metabólico",
                          "Hipertensión arterial grado 2"),
                   "en": ("Type 2 diabetes mellitus, adequate control",
                          "Essential hypertension, stage 2")},
        medications={"uk": ("Метформін 1000 мг, двічі на добу", "Аторвастатин 20 мг, увечері"),
                     "ru": ("Метформин 1000 мг, дважды в сутки", "Аторвастатин 20 мг, вечером"),
                     "es": ("Metformina 1000 mg, dos veces al día", "Atorvastatina 20 mg, por la noche"),
                     "en": ("Metformin 1000 mg, twice daily", "Atorvastatin 20 mg, at night")},
        urine_every=2, stool_in=(2017, 2022),
    ),
    # Her grandmother: a small archive, on paper, in the two languages of her own country and
    # then of the island her family moved to.
    Life(
        whose="Zoya Kravets", born="09.06.1936", folder="archive-of-zoya-kravets",
        years=range(2014, 2022), panels=1,
        where=((2014, 0), (2019, 4)),
        drift={"Haemoglobin": ((2014, 1.0), (2019, 0.88), (2021, 0.93)),
               "Creatinine": ((2014, 1.05), (2021, 1.22)),
               "eGFR": ((2014, 0.88), (2021, 0.72))},
        urine_every=1, stool_in=(2016,),
    ),
]

# A test whose number follows the season rather than the years: low in February, high in August.
SEASONAL = {"Vitamin D": 0.22}

RANGE_FORMS = (
    re.compile(r"^\s*(-?[\d.,]+)\s*[-–]\s*(-?[\d.,]+)\s*$"),
    re.compile(r"^\s*(?:<|до|hasta|less than)\s*(-?[\d.,]+)\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:>|від|от|понад|более|más de)\s*(-?[\d.,]+)\s*$", re.IGNORECASE),
)


def _limits(printed: str) -> tuple[float | None, float | None]:
    """The two numbers a printed range means, so the form can mark what falls outside it."""
    def number(text: str) -> float:
        return float(text.replace(",", "."))

    both = RANGE_FORMS[0].match(printed)
    if both:
        return number(both.group(1)), number(both.group(2))
    below = RANGE_FORMS[1].match(printed)
    if below:
        return None, number(below.group(1))
    above = RANGE_FORMS[2].match(printed)
    if above:
        return number(above.group(1)), None
    return None, None


def _flag(number: float, printed: str, language: str) -> str | None:
    """What a laboratory prints in the margin when a value leaves its range."""
    low, high = _limits(printed)
    if high is not None and number > high:
        return "H" if language == "en" else "↑"
    if low is not None and number < low:
        return "L" if language == "en" else "↓"
    return None


@functools.cache
def _font(which: str, size: int) -> ImageFont.FreeTypeFont:
    """A face for one kind of text, found once and kept: a page has hundreds of lines."""
    for path in FONT_CHOICES[which]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit(
        f"No font to draw the demo with. Install the Liberation fonts — on Debian or Ubuntu, "
        f"apt install fonts-liberation — or put one of these where it is expected: "
        + ", ".join(FONT_CHOICES[which])
    )  # fmt: skip


def _draw_form(lines: list[tuple], tilt: float) -> Image.Image:
    """One page of a form, drawn as a scanner would have seen it: slightly askew, a little grey."""
    page = Image.new("RGB", PAGE, (252, 251, 248))
    pen = ImageDraw.Draw(page)
    for kind, text, y in lines:
        if kind == "rule":
            pen.line([(90, y), (PAGE[0] - 90, y)], fill=(60, 60, 60), width=2)
        elif kind == "head":
            pen.text((90, y), text, font=_font("serif_bold", 34), fill=(15, 15, 15))
        elif kind == "sub":
            pen.text((90, y), text, font=_font("serif", 24), fill=(60, 60, 60))
        else:
            pen.text((90, y), text, font=_font("mono", 22), fill=(20, 20, 20))
    return page.rotate(tilt, resample=Image.BICUBIC, fillcolor=(250, 249, 246))


def _where(life: Life, when: date) -> tuple:
    """The laboratory this life was going to that year."""
    chosen = life.where[0][1]
    for year, clinic in life.where:
        if when.year >= year:
            chosen = clinic
    return CLINICS[chosen]


def _scale(life: Life, label: str, when: date) -> float:
    """How far this test had drifted by that date: straight lines between the written points."""
    points = life.drift.get(label)
    factor = 1.0
    if points:
        moment = when.year + (when.month - 1) / 12
        first, last = points[0], points[-1]
        if moment <= first[0]:
            factor = first[1]
        elif moment >= last[0]:
            factor = last[1]
        else:
            for (year, value), (next_year, next_value) in zip(points, points[1:]):
                if year <= moment <= next_year:
                    share = (moment - year) / (next_year - year or 1)
                    factor = value + (next_value - value) * share
                    break
    swing = SEASONAL.get(label)
    if swing:
        import math

        factor *= 1 + swing * math.cos(2 * math.pi * (when.month - 8) / 12)
    return factor


def _value(middle: tuple, digits: int, rng: random.Random, scale: float = 1.0,
           point: str = ",") -> tuple[str, float]:
    """A number where a laboratory's would be, with the decimal mark that country's forms use."""
    centre, spread = middle
    number = round(rng.gauss(centre * scale, spread), digits)
    printed = f"{number:.{digits}f}".replace(".", point) if digits else str(int(number))
    return printed, float(number)


def _written(text: str, language: str) -> str:
    """A printed range as that language writes it: an English form has no decimal commas."""
    return text.replace(",", ".") if language == "en" else text


def _head(life: Life, clinic: tuple, heading: str, when: date, number: int) -> list[tuple]:
    name, _language, town = clinic
    return [("head", name, 110), ("sub", f"{town} · {heading}", 160), ("rule", "", 200),
            ("row", f"{life.whose}   ·   {life.born}   ·   № {number:05d}", 230),
            ("row", when.strftime("%d.%m.%Y"), 264), ("rule", "", 292)]  # fmt: skip


def _panel(life: Life, when: date, clinic: tuple, rng: random.Random, number: int, wider: bool = False) -> dict:
    """One laboratory panel: what the form says, and the transcription of it, side by side."""
    name, language, _town = clinic
    heading = {"uk": "ЗАГАЛЬНИЙ АНАЛІЗ КРОВІ", "ru": "ОБЩИЙ АНАЛИЗ КРОВИ", "es": "ANALÍTICA DE SANGRE",
               "en": "BLOOD TEST REPORT", "el": "ΑΙΜΑΤΟΛΟΓΙΚΟΣ ΕΛΕΓΧΟΣ"}[language]
    lines = _head(life, clinic, heading, when, number)
    observations, y = [], 330
    for label, names, units, ranges, middles in (BLOOD + SOMETIMES if wider else BLOOD):
        point = "." if language == "en" else ","
        printed, number_value = _value(*middles[language], rng, _scale(life, label, when), point)
        reference = _written(ranges[language], language)
        mark = _flag(number_value, reference, language)
        lines.append(("row", f"{names[language]:<26} {printed:>9} {mark or ' '} {units[language]:<14} {reference}", y))
        y += 40
        observations.append({
            "name_as_printed": names[language], "value_as_printed": printed, "value_role": "result",
            "table_as_printed": heading, "column_as_printed": None, "reference_column_as_printed": None,
            "value_numeric": number_value, "comparator": None, "value_kind": "quantitative",
            "unit_as_printed": units[language], "reference_as_printed": reference,
            "flag_as_printed": mark, "method_as_printed": None,
            "provenance": {"page": 1, "snippet": f"{names[language]} {printed} {units[language]}"},
        })  # fmt: skip
    lines += [("rule", "", y + 16), ("sub", {"uk": "Лікар-лаборант", "ru": "Врач-лаборант", "es": "Facultativo",
                                            "en": "Reported by", "el": "Ιατρός"}[language] + "  ______", y + 44)]  # fmt: skip
    return {
        "lines": lines, "language": language, "doc_type": "lab_panel", "title": heading,
        "provider": name, "date": when, "observations": observations, "sections": [],
    }  # fmt: skip


def _by_words(life: Life, when: date, clinic: tuple, rng: random.Random, number: int,
              heading: dict, rows: list) -> dict:
    """A form whose results are words rather than numbers, of a specimen that is not blood."""
    name, language, _town = clinic
    printed_heading = heading[language]
    lines = _head(life, clinic, printed_heading, when, number)
    observations, y = [], 330
    for _label, names, units, references, choices in rows:
        printed = rng.choice(choices[language])
        unit = units[language] if isinstance(units, dict) else units
        reference = references[language] if isinstance(references, dict) else references
        reference = _written(reference, language)
        lines.append(("row", f"{names[language]:<26} {printed:<24} {unit:<10} {reference}", y))
        y += 40
        observations.append({
            "name_as_printed": names[language], "value_as_printed": printed, "value_role": "result",
            "table_as_printed": printed_heading, "column_as_printed": None,
            "reference_column_as_printed": None, "value_numeric": None, "comparator": None,
            "value_kind": "qualitative", "unit_as_printed": unit or None,
            "reference_as_printed": reference or None, "flag_as_printed": None, "method_as_printed": None,
            "provenance": {"page": 1, "snippet": f"{names[language]} {printed}"},
        })  # fmt: skip
    return {
        "lines": lines, "language": language, "doc_type": "lab_panel", "title": printed_heading,
        "provider": name, "date": when, "observations": observations, "sections": [],
    }  # fmt: skip


# What a report says, in the language of the laboratory that printed it. An imaging report is
# written wherever the person happens to live; a consultation is written where their doctor is.
REPORTS = {
    ("imaging_report", "en"): ("ABDOMINAL ULTRASOUND REPORT",
        ["Liver of normal size, smooth outline, homogeneous echotexture.",
         "Gallbladder not distended, walls not thickened, no calculi seen.",
         "Pancreas partly obscured by bowel gas, homogeneous where seen.",
         "Kidneys normally sited, no pelvicalyceal dilatation.",
         "No free intraperitoneal fluid."]),
    ("imaging_report", "uk"): ("УЛЬТРАЗВУКОВЕ ДОСЛІДЖЕННЯ ОРГАНІВ ЧЕРЕВНОЇ ПОРОЖНИНИ",
        ["Печінка звичайних розмірів, контури рівні, структура однорідна.",
         "Жовчний міхур не збільшений, стінки не потовщені, конкрементів не виявлено.",
         "Підшлункова залоза візуалізується частково, структура однорідна.",
         "Нирки розташовані типово, чашечно-мискова система не розширена.",
         "Вільної рідини у черевній порожнині не виявлено."]),
    ("imaging_report", "ru"): ("УЛЬТРАЗВУКОВОЕ ИССЛЕДОВАНИЕ ОРГАНОВ БРЮШНОЙ ПОЛОСТИ",
        ["Печень обычных размеров, контуры ровные, структура однородная.",
         "Желчный пузырь не увеличен, стенки не утолщены, конкрементов не выявлено.",
         "Поджелудочная железа визуализируется частично, структура однородная.",
         "Почки расположены типично, чашечно-лоханочная система не расширена.",
         "Свободной жидкости в брюшной полости не выявлено."]),
    ("imaging_report", "es"): ("ECOGRAFÍA ABDOMINAL",
        ["Hígado de tamaño normal, contornos lisos, ecoestructura homogénea.",
         "Vesícula biliar sin distensión, paredes no engrosadas, sin litiasis.",
         "Páncreas parcialmente visible, de ecoestructura homogénea.",
         "Riñones de situación normal, sin dilatación de la vía excretora.",
         "No se observa líquido libre intraabdominal."]),
    ("imaging_report", "el"): ("ΥΠΕΡΗΧΟΓΡΑΦΗΜΑ ΑΝΩ ΚΟΙΛΙΑΣ",
        ["Ήπαρ φυσιολογικού μεγέθους, με ομαλά όρια και ομοιογενή υφή.",
         "Χοληδόχος κύστη μη διατεταμένη, τοιχώματα φυσιολογικού πάχους, χωρίς λίθους.",
         "Πάγκρεας μερικώς ορατό, ομοιογενούς υφής.",
         "Νεφροί σε φυσιολογική θέση, χωρίς διάταση του πυελοκαλυκικού συστήματος.",
         "Δεν ανευρέθη ελεύθερο υγρό στην περιτοναϊκή κοιλότητα."]),
    ("consultation", "en"): ("GENERAL PRACTICE CONSULTATION",
        ["Reports occasional tiredness towards the end of the day.",
         "On examination: well, no pallor, no oedema.",
         "Full blood count to be repeated in six months.",
         "No change to work or activity advised."]),
    ("consultation", "uk"): ("КОНСУЛЬТАЦІЯ ТЕРАПЕВТА",
        ["Скарги на періодичну втому наприкінці дня.",
         "Об'єктивно: стан задовільний, шкіра звичайного кольору.",
         "Рекомендовано повторити загальний аналіз крові через шість місяців.",
         "Режим праці та відпочинку без змін."]),
    ("consultation", "ru"): ("КОНСУЛЬТАЦИЯ ТЕРАПЕВТА",
        ["Жалобы на периодическую усталость к концу дня.",
         "Объективно: состояние удовлетворительное, кожа обычной окраски.",
         "Рекомендовано повторить общий анализ крови через шесть месяцев.",
         "Режим труда и отдыха без изменений."]),
    ("consultation", "es"): ("CONSULTA DE MEDICINA GENERAL",
        ["Refiere cansancio ocasional al final del día.",
         "Exploración: buen estado general, sin palidez ni edemas.",
         "Se recomienda repetir el hemograma en seis meses.",
         "Sin cambios en el régimen de trabajo y descanso."]),
    ("consultation", "el"): ("ΓΕΝΙΚΗ ΙΑΤΡΙΚΗ ΕΞΕΤΑΣΗ",
        ["Αναφέρει περιοδική κόπωση προς το τέλος της ημέρας.",
         "Αντικειμενικά: καλή γενική κατάσταση, χωρίς ωχρότητα ή οίδημα.",
         "Συνιστάται επανάληψη γενικής αίματος σε έξι μήνες.",
         "Χωρίς μεταβολή στο πρόγραμμα εργασίας και ανάπαυσης."]),
    ("follow_up", "en"): ("DIABETES REVIEW CLINIC",
        ["Reviewed on current treatment; no new complaints.",
         "Home glucose readings brought to the appointment and reviewed.",
         "HbA1c to be repeated every three months.",
         "Blood pressure to be recorded at home, morning and evening."]),
    ("follow_up", "uk"): ("КОНСУЛЬТАЦІЯ ЕНДОКРИНОЛОГА",
        ["Спостереження за призначеним лікуванням, скарг активно не пред'являє.",
         "Самоконтроль глікемії ведеться регулярно, записи надані.",
         "Рекомендовано глікований гемоглобін кожні три місяці.",
         "Контроль артеріального тиску щоденно, вранці та ввечері."]),
    ("follow_up", "ru"): ("КОНСУЛЬТАЦИЯ ЭНДОКРИНОЛОГА",
        ["Наблюдение на назначенном лечении, активных жалоб не предъявляет.",
         "Самоконтроль гликемии ведётся регулярно, записи предоставлены.",
         "Рекомендован гликированный гемоглобин каждые три месяца.",
         "Контроль артериального давления ежедневно, утром и вечером."]),
    ("follow_up", "es"): ("CONSULTA DE ENDOCRINOLOGÍA",
        ["Seguimiento del tratamiento pautado, sin quejas activas.",
         "Autocontrol de glucemia realizado con regularidad, registros aportados.",
         "Se recomienda hemoglobina glicosilada cada tres meses.",
         "Control diario de la tensión arterial, mañana y noche."]),
}


def _report(life: Life, when: date, clinic: tuple, kind: str) -> dict:
    """A report that is words: a page of text, no values, so the archive holds both kinds."""
    name, language, town = clinic
    if (kind, language) not in REPORTS:
        # A silent fallback here printed a Ukrainian page under a Greek letterhead and then
        # recorded the document as Ukrainian. A demo that quietly lies about itself is worse
        # than one that stops while it is being written.
        raise KeyError(f"the demo has no {kind} written in {language}")
    said = language
    heading, body = REPORTS[(kind, said)]
    diagnoses = list(life.diagnoses.get(said, ())) if kind == "follow_up" else []
    medications = list(life.medications.get(said, ())) if kind == "follow_up" else []
    lines = [("head", name, 110), ("sub", f"{town} · {heading}", 160), ("rule", "", 200),
             ("row", f"{life.whose}   ·   {life.born}", 230), ("row", when.strftime("%d.%m.%Y"), 264),
             ("rule", "", 292)]  # fmt: skip
    y = 340
    for sentence in body + diagnoses + medications:
        lines.append(("row", sentence, y))
        y += 44
    return {
        "lines": lines, "language": said,
        "doc_type": "consultation" if kind == "follow_up" else kind,
        "title": heading, "provider": name, "date": when, "observations": [],
        "diagnoses": diagnoses, "medications": medications,
        "sections": [{"heading_as_printed": heading, "text": " ".join(body), "page": 1}],
    }  # fmt: skip


URINE_HEADING = {"uk": "ЗАГАЛЬНИЙ АНАЛІЗ СЕЧІ", "ru": "ОБЩИЙ АНАЛИЗ МОЧИ", "en": "URINALYSIS",
                 "es": "ANÁLISIS DE ORINA", "el": "ΓΕΝΙΚΗ ΕΞΕΤΑΣΗ ΟΥΡΩΝ"}
STOOL_HEADING = {"uk": "КОПРОГРАМА", "ru": "КОПРОГРАММА", "en": "STOOL EXAMINATION",
                 "es": "ESTUDIO COPROLÓGICO", "el": "ΚΟΠΡΟΛΟΓΙΚΗ ΕΞΕΤΑΣΗ"}


def invent(life: Life, seed: int = 7) -> list[dict]:
    """A life nobody lived: what to draw for it and what its transcription says."""
    rng = random.Random(seed + len(life.whose))
    made, number = [], 1
    months = {1: (6,), 2: (3, 9), 3: (2, 6, 10)}[life.panels]
    for year in life.years:
        for month in months:
            when = date(year, month, rng.randint(1, 28))
            clinic = _where(life, when)
            # The wider panel once a year: some tests then have thirty points and some six.
            # The wider panel once a year — which for a life tested once a year is every other
            # year, not every visit: "wider" has to mean something for a small archive too.
            wider = month == months[-1] and (len(months) > 1 or year % 2 == 0)
            made.append(_panel(life, when, clinic, rng, number, wider=wider))
            number += 1
        if year % life.urine_every == 0:
            when = date(year, rng.randint(1, 12), rng.randint(1, 28))
            made.append(_by_words(life, when, _where(life, when), rng, number, URINE_HEADING, URINE))
            number += 1
        if year in life.stool_in:
            when = date(year, rng.randint(1, 12), rng.randint(1, 28))
            made.append(_by_words(life, when, _where(life, when), rng, number, STOOL_HEADING, STOOL))
            number += 1
        if year % 3 == 0:
            when = date(year, rng.randint(1, 12), rng.randint(1, 28))
            made.append(_report(life, when, _where(life, when), "imaging_report"))
        if life.diagnoses and year % 2 == 1 and year > life.where[0][0]:
            when = date(year, rng.randint(1, 12), rng.randint(1, 28))
            made.append(_report(life, when, _where(life, when), "follow_up"))
        elif year % 4 == 0:
            when = date(year, rng.randint(1, 12), rng.randint(1, 28))
            made.append(_report(life, when, _where(life, when), "consultation"))
    # The same panel printed twice and then a third time, as copies sent on by other clinics:
    # the archive should say so rather than count one blood draw as three.
    made.append(dict(made[6]))
    made.append(dict(made[6]))
    _seed_trouble(made)
    return sorted(made, key=lambda item: item["date"])


def _seed_trouble(made: list[dict]) -> None:
    """Three things gone wrong in the transcription, because a page that finds nothing teaches nothing.

    Each is a mistake a model actually makes, written here into the transcription and not into
    the drawn page, so the two disagree exactly as they would after a real reading: a decimal
    point lost, a date that could not be made out, and a corner of the page nobody could read.
    The checks that find them run for real, and so does the page that shows them.
    """
    panels = [item for item in made if item["observations"] and item["doc_type"] == "lab_panel"]
    if len(panels) < 12:
        return
    slipped = next((value for value in panels[4]["observations"] if value["value_numeric"] is not None), None)
    if slipped:
        # A decimal point where the form has none: 231 read as 23,1.
        slipped["value_numeric"] = round(slipped["value_numeric"] / 10, 2)
    panels[7]["date_unreadable"] = True
    panels[10]["unreadable"] = [{"page": 1, "what": "the last line of the table",
                                 "why": "the scan is cut off at the foot of the page"}]


def _name_the_tests(data_dir: Path, say=lambda text: None) -> None:
    """The groups a model would have proposed and a person approved, known here by construction.

    In a real archive these are worked out from the printed names and then read again by a
    second model; here the spellings were written by this file, so what they belong to is not a
    guess and there is nothing to approve.
    """
    from epicrisis import indicators

    for label, names, _units, _ranges, _middles in BLOOD + SOMETIMES:
        # The same demo built twice keeps the same indicators, and so the same addresses: a
        # second run that made "creatinine-2" beside "creatinine" left every /tests/<id> link
        # in the first run's screenshots pointing at nothing.
        existing = next((item for item in indicators.load(data_dir) if item.label == label), None)
        indicators.upsert(data_dir, existing.id if existing else None, label, list(names.values()), "approved",
                          note="Grouped by the demo, which printed these spellings itself.",
                          source="person", reviewed=True)  # fmt: skip
    for label, names, _unit, _reference, _choices in URINE + STOOL:
        existing = next((item for item in indicators.load(data_dir) if item.label == label), None)
        indicators.upsert(data_dir, existing.id if existing else None, label,
                          sorted({*(existing.names if existing else []), *names.values()}), "approved",
                          note="Grouped by the demo, which printed these spellings itself.",
                          source="person", reviewed=True)  # fmt: skip
    say(f"  named {len(indicators.load(data_dir))} tests, the way a person would have approved them")


def _write_life(life: Life, into: Path, data_dir: Path, seed: int, say) -> tuple:
    """Draw one life's pages, register the archive, and write the transcription beside them."""
    from epicrisis.extract.backend import PROMPT_VERSION
    from epicrisis.extract.run import extracted_path
    from epicrisis.inventory.run import write_inventory
    from epicrisis.records import append_line, now
    from epicrisis.sources import SourceRegistry, source_output_dir
    from epicrisis.validate import validate_source

    archive = into / life.folder
    archive.mkdir(parents=True, exist_ok=True)
    made = invent(life, seed)
    rng = random.Random(seed)
    drawn: list[tuple[Path, dict]] = []
    for index, item in enumerate(made, 1):
        year = archive / str(item["date"].year)
        year.mkdir(exist_ok=True)
        path = year / f"{item['date']:%Y-%m-%d}-{item['doc_type']}-{index}.png"
        _draw_form(item["lines"], rng.uniform(-0.6, 0.6)).save(path, "PNG")
        drawn.append((path, item))

    registry = SourceRegistry(data_dir)
    source = next((item for item in registry.list() if Path(item.path) == archive), None)
    if source is None:
        source = registry.add(str(archive), life.whose)
    output = source_output_dir(data_dir, source.id)
    summary = write_inventory(archive, output / "inventory.jsonl")
    # The dashboard reads the inventory's own status file, not the inventory: without it the
    # first step of a finished archive stands at "Queued" for ever.
    (output / "inventory.status.json").write_text(json.dumps({
        "state": "done", "scanned": summary.files, "total": summary.files,
        "started_at": now(), "finished_at": now(),
    }), encoding="utf-8")  # fmt: skip

    for path, item in drawn:
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        append_line(output / "classify.jsonl", {
            "file_sha256": sha, "page": 1, "route": "vision", "doc_type": item["doc_type"],
            "page_role": "first", "language": item["language"],
            "date_on_page": None if item.get("date_unreadable") else item["date"].strftime("%d.%m.%Y"),
            "provider_on_page": item["provider"],
            "has_tabular_results": bool(item["observations"]), "legible": True, "confidence": 0.95,
            "model": "made up, no model was called", "prompt_version": "demo", "at": now(),
        })  # fmt: skip
        text = "\n".join(line[1] for line in item["lines"] if line[0] != "rule")
        extracted_path(output / "extracted", sha).parent.mkdir(parents=True, exist_ok=True)
        extracted_path(output / "extracted", sha).write_text(json.dumps({
            "file_sha256": sha,
            "documents": [{
                "doc_type": item["doc_type"], "language": item["language"], "pages": [1],
                "title_as_printed": item["title"], "provider_as_printed": item["provider"],
                "department_as_printed": None,
                # A date the reading could not make out: printed on the page, and nothing a
                # reader can turn into a day. The card asks for it rather than inventing one.
                "date_of_study_as_printed": ("1?.0?.20?" + item["date"].strftime("%y")[1]
                                             if item.get("date_unreadable") else item["date"].strftime("%d.%m.%Y")),
                "date_of_report_as_printed": None,
                "observations": item["observations"], "sections": item["sections"],
                "page_texts": [{"page": 1, "text": text}], "full_text": text,
                "medications_as_printed": item.get("medications", []),
                "diagnoses_as_printed": item.get("diagnoses", []),
                "unreadable": item.get("unreadable", []),
                "provenance": {"backend": "demo", "model": "made up, no model was called",
                               "requested_model": "none", "prompt_version": "demo",
                               "extracted_at": now(), "calls": 0},
            }],
        }, ensure_ascii=False), encoding="utf-8")  # fmt: skip
        # The ledger is how the program knows a document has been read. Without it the status
        # page says the reading has not started, over an archive that is fully transcribed —
        # which is the first screen anybody following the README sees.
        append_line(output / "ledger.jsonl", {
            "step": "extract", "file_sha256": sha, "pages": [1],
            "model": "made up, no model was called", "prompt_version": PROMPT_VERSION,
            "status": "done", "at": now(),
        })  # fmt: skip
    validate_source(output, archive)
    say(f"  {life.whose}: {len(drawn)} pages drawn, inventoried and transcribed")
    return source, archive


def build(into: Path, seed: int = 7, say=lambda text: None) -> dict:
    """Write the whole instance: the scans of three lives, their transcription, checks and index."""
    from epicrisis.index.build import build_index
    from epicrisis.sources import SourceRegistry

    into = Path(into).resolve()
    data_dir = into / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    written = [_write_life(life, into, data_dir, seed, say) for life in LIVES]
    registry = SourceRegistry(data_dir)
    registry.set_active(written[0][0].id)
    _name_the_tests(data_dir, say)
    # One index file per archive, the way the program builds them, so that nothing of one
    # person's can be answered out of another's even by a mistake.
    totals = {"documents": 0, "transcribed": 0, "observations": 0, "copy_groups": 0}
    for source, _archive in written:
        built = build_index(data_dir, [source])
        for key in totals:
            totals[key] += built[key]
    say(f"  indexed: {totals['documents']} documents, {totals['observations']} values, "
        f"one index file for each of the {len(written)} archives")
    return {"data_dir": data_dir, "into": into, "archives": [archive for _source, archive in written],
            "sources": [source for source, _archive in written], **totals}  # fmt: skip
