"""How values are printed on real forms, for checks that compare stored fields with the page.

Typewriters printed the digit 1 as a letter I and 0 as O; Spanish and Ukrainian forms group
thousands with a dot or space; powers come as superscripts; comparators come as signs or words.
These helpers never change stored data, they only tell a real mismatch from a way of printing.
"""

import math
import re
import unicodedata

SIGNS = ("<", ">", "≤", "≥")
COMPARATOR_WORDS = re.compile(
    r"^\s*(до|від|от|менее|более|меньше|больше|свыше|выше|ниже|не\s+более|не\s+менее|понад|нижче|вище|більше|менше|"
    r"up\s+to|less\s+than|more\s+than|below|above|under|over|hasta|menor\s+de|mayor\s+de|inferior\s+a|superior\s+a|"
    r"έως|κάτω\s+από|άνω\s+του|μέχρι)(?![^\W\d_])",
    re.IGNORECASE,
)
SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
# A letter counts as a digit only between digits or before one, never at the start of a unit ("75lpm").
_TYPEWRITER_ONE = re.compile(r"(?<![^\W\d_])[IlІ](?=[\d,.]?\d)|(?<=[\d,.])[IlІ](?![^\W\d_])")
_TYPEWRITER_ZERO = re.compile(r"(?<![^\W\d_])[OoОо](?=[\d,.]?\d)|(?<=[\d,.])[OoОо](?![^\W\d_])")
_POWER = re.compile(r"(\d+)\s*(?:\^|\*\*)?\s*([⁰¹²³⁴⁵⁶⁷⁸⁹⁻]+)")
_TOKEN = re.compile(r"[-+]?(?:\d{1,3}(?:[. ]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?|[.,]\d+)")


def typewriter_digits(text: str) -> str:
    return _TYPEWRITER_ZERO.sub("0", _TYPEWRITER_ONE.sub("1", text or ""))


def number_tokens(text: str) -> list[str]:
    return _TOKEN.findall(typewriter_digits(text))


def readings(token: str) -> set[float]:
    """Every number a printed token can mean: decimal comma, decimal point, grouped thousands."""
    values = set()
    candidates = {token.replace(",", "."), token.replace(" ", "").replace(".", "").replace(",", ".")}
    for candidate in candidates:
        candidate = candidate.replace(" ", "")
        if candidate.startswith((".", "-.", "+.")):
            candidate = candidate.replace(".", "0.", 1)
        try:
            values.add(float(candidate))
        except ValueError:
            pass
    return values


def number_matches(printed: str, value: float) -> bool:
    """False only when the printed text holds exactly one number and no reading of it is the value."""
    text = typewriter_digits(printed)
    for base, exponent in _POWER.findall(text):
        try:
            power = float(base) ** int(exponent.translate(SUPERSCRIPTS))
        except (OverflowError, ValueError):
            # "4,5⁹⁹⁹⁹⁹" is not a power anybody printed on a form; it is a misread superscript,
            # and it used to end the whole validation run for the archive.
            continue
        if math.isclose(power, value, rel_tol=1e-9):
            return True
    tokens = _TOKEN.findall(text)
    if len(tokens) != 1:
        return True
    return any(math.isclose(reading, value, rel_tol=1e-9, abs_tol=1e-12) for reading in readings(tokens[0]))


def comparator_printed(printed: str) -> bool:
    return (printed or "").lstrip().startswith(SIGNS) or bool(COMPARATOR_WORDS.match(printed or ""))


def unexplained_letters(printed: str) -> bool:
    """Letters in a numeric value that are not a comparator word, typewriter digits or a unit after the number."""
    text = COMPARATOR_WORDS.sub("", typewriter_digits(printed or ""), count=1)
    text = re.sub(r"(?<=\d)\s*[^\W\d_][^\d]*$", "", text.strip())
    return bool(re.search(r"[^\W\d_]", text))


def numbers_in_text(printed: str, text: str) -> bool:
    """Every number of a printed field appears in the page text, wherever the lines were joined."""
    squeezed = re.sub(r"\s+", "", typewriter_digits(text)).casefold()
    return all(re.sub(r"\s+", "", token) in squeezed for token in number_tokens(printed))


# Letters that differ between Ukrainian and Russian spellings of the same word. ы and э belong
# here for the commonest pairs of all: Эритроциты and Еритроцити, Белок and Білок, Мышцы and
# М'язи. Without them a Russian spelling found nothing in an archive whose forms are Ukrainian,
# on a page that promises the two are matched as one.
_FOLD = str.maketrans({"і": "и", "ї": "и", "є": "е", "ё": "е", "ы": "и", "э": "е", "ґ": "г", "й": "и", "ъ": "", "ь": ""})


def squeezed(text: str | None) -> str:
    """All space taken out and the case dropped: for telling one printed string from another."""
    return re.sub(r"\s+", "", text or "").casefold()


def fold(text: str | None) -> str:
    """Search form of a text: lower case, no accents, Ukrainian and Russian letters paired."""
    decomposed = unicodedata.normalize("NFKD", (text or "").casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).translate(_FOLD)


def fold_with_offsets(text: str) -> tuple[str, list[int]]:
    """The search form of a text and, for every character of it, its place in the original."""
    folded, offsets = [], []
    for position, character in enumerate(text):
        piece = fold(character)
        folded.append(piece)
        offsets.extend([position] * len(piece))
    return "".join(folded), offsets
