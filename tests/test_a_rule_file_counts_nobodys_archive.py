"""What a shipped rule file may say about what it found on a real archive, which is nothing.

`CONTRIBUTING.md` has said it since before these rules were written: a rule file explains what it
looks at and how it can be wrong, and "a count of what a rule found on one real archive belongs in
a report, not in a file that ships". Five rule files published for the first time in 0.4.0 carried
such counts anyway — one of them a whole section of four — and so did four of the twenty-one that
were already there, in the comment that says why a rule ships off, which is the half nobody had
noticed. Nine in all.

**A number in a rule file cannot be told from a count off an archive by looking at the number.**
60 is a threshold in days, `1,001-1,040` is the scale a form prints a urine specific gravity at,
1900 is the year before which a date is refused, and eight is the length a printed name has to
reach before a rule will believe it. Every one of those belongs here, and `CONTRIBUTING.md` says
so in as many words. What can be told apart is the **sentence around the number**. A count off
somebody's archive says three things at once: where it was counted — an archive — what was counted
— documents, values, lines, rows, tests, charts, findings, quotations — and how many. A threshold
says a size and locates itself nowhere; a printed range is a property of laboratory forms; a year
is a year.

So that is what this reads: no paragraph of a shipped rule file holds all three at once. The
reader is deliberately coarse in the one direction that matters — it reads a whole paragraph, not
a sentence, because the counts it was written for arrive in runs ("On one archive, ninety values
carried an eye in their name. Thirty-eight of them were…") and only the first sentence of such a
run says which archive. A paragraph that locates itself in an archive may not count that archive's
things at all.

What it cannot catch has a test of its own below, so that the gap is written down rather than
assumed away.
"""

import pathlib
import re

import pytest

SHIPPED = pathlib.Path(__file__).resolve().parent.parent / "epicrisis" / "rules" / "shipped"

# Where a sentence says it was counted. "Measured against" and "measured on" are here because that
# is the other way these sentences introduce themselves, with the archive left implied.
AN_ARCHIVE = re.compile(r"\barchives?\b|\bmeasured (?:against|on)\b", re.IGNORECASE)

# What an archive holds, counted. Each of these is a thing a check finds; none of them is a
# property of a laboratory form, which is the kind of figure CONTRIBUTING.md asks for instead.
A_THING_AN_ARCHIVE_HOLDS = (r"documents?|values?|lines?|rows?|tests?|charts?|findings?|"
                            r"quotations?|scans?")

# How many. Digits in any shape, including a figure written with a space for a thousands separator
# the way these pages write them, and the numbers this project writes out in words — which it does
# for everything under a hundred, so the words are where most of these were. "No" is here because
# a count of nought is a count ("reported no rows at all"). "One" is not: it is an article in this
# prose ("on one archive", "one test, one printed unit"), never a count that says anything.
A_QUANTITY = (r"\d[\d\s,.]*|no|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
              r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|"
              r"fifty|sixty|seventy|eighty|ninety|hundred|thousand|dozen|dozens")

# A quantity standing on one of those things: **the number has to be a count of them**, not merely
# in the same paragraph. That is what tells "ninety values carried an eye in their name" from "the
# two disagree" and "below eight letters", both of which are a figure beside the word "archive" in
# an honest paragraph. Two words of room between the two, because these sentences put one there:
# "eight such quotations", "350 lines on 63 documents".
A_COUNT_OF_THEM = re.compile(
    rf"\b(?:{A_QUANTITY})\s+(?:\S+\s+){{0,2}}(?:{A_THING_AN_ARCHIVE_HOLDS})\b", re.IGNORECASE)

# How many archives it was run over, which is a count of this machine and not of a check. It is
# read separately from the words above, because "archive" is the subject of half the honest prose
# in these files: a paragraph may say what an archive is and what one holds; it may not say how
# many of them are on somebody's desk. "On all three archives here" is how most of these opened.
ARCHIVES_COUNTED = re.compile(rf"\b(?:{A_QUANTITY})\s+archives\b", re.IGNORECASE)

# A line of the TOML header that states a threshold, an order, a switch or a list of them. The
# header's prose — the name, the one-line summary, what settles a finding, and the comments that
# explain why a rule ships off — is read like any other paragraph; its numbers are not prose and
# have their own home, which is `[settings]`.
A_SETTING = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*(?:[-+.\d]|true|false|\[)", re.IGNORECASE)


def paragraphs_of(text: str) -> list[str]:
    """Every stretch of a rule file a person reads, one paragraph at a time.

    The header is read as well as the body. It carries the summary printed beside the switch, the
    sentence saying what would settle a finding, and — in the rules that ship off — the comment
    saying why, which is exactly where two of these counts were. Only its settings are dropped,
    because a threshold is a number with a home of its own.
    """
    fenced = text.split("+++")
    header, body = (fenced[1], "+++".join(fenced[2:])) if len(fenced) >= 3 else ("", text)
    kept = [line for line in header.splitlines() if not A_SETTING.match(line)]
    return [one for one in ("\n".join(kept) + "\n\n" + body).split("\n\n") if one.strip()]


def counts_an_archive(paragraph: str) -> bool:
    """Whether this paragraph says how many of an archive's things a rule found there."""
    if ARCHIVES_COUNTED.search(paragraph):
        return True
    return bool(AN_ARCHIVE.search(paragraph) and A_COUNT_OF_THEM.search(paragraph))


def shipped_rule_files() -> list[pathlib.Path]:
    found = sorted(SHIPPED.glob("*.md"))
    assert len(found) > 20, f"{SHIPPED} holds no rules: {found}"
    return found


@pytest.mark.parametrize("rule", shipped_rule_files(), ids=lambda rule: rule.stem)
def test_no_shipped_rule_file_says_how_much_it_found_on_an_archive(rule: pathlib.Path):
    """Each rule file, held to the paragraph above in CONTRIBUTING.md.

    A failure here is mended by saying the same thing without the figure: what the rule looks for,
    why it is worth looking, and how it can be wrong. The twenty-one that never had a count are
    the shape to copy, and the count itself goes in the report of the round that measured it.
    """
    counted = [one for one in paragraphs_of(rule.read_text(encoding="utf-8")) if counts_an_archive(one)]
    assert not counted, (
        f"{rule.name} says how many of an archive's things it found. CONTRIBUTING.md: a count of "
        f"what a rule found on one real archive belongs in a report, not in a file that ships.\n\n"
        + "\n\n".join(counted))


def test_the_reader_finds_a_count_in_the_shape_these_five_arrived_in():
    """The positive control: the sentences that were in the files, as they were written.

    Without this, the test above is a test that passes because its reader never says yes. Each of
    these is a real sentence out of a rule file of 0.4.0 or of the twenty-one before it, with the
    archive's own figures left in — they name nobody, and this is the one file where they are
    evidence rather than a leak.
    """
    for said in ("On one archive, ninety values carried an eye in their name.",
                 "On one archive nineteen values were in this state, every one of them from an eye examination.",
                 "On the three archives here: twenty-eight values carry a date of their own.",
                 "Nothing, on the three archives this project has. It was run over all three and reported no rows at all.",
                 "Before this archive was cut at the lines its own export draws, six of its twenty "
                 "documents covered more than two months and one covered 1666 days.",
                 "It found 28 documents on the archive it was measured against.",
                 "On the archive it was measured against it found 350 lines on 63 documents.",
                 "255 documents of one archive here are that",
                 "that cost sixty-seven values their scale on three archives to gain four"):  # fmt: skip
        assert counts_an_archive(said), said


def test_the_reader_is_silent_on_every_number_that_belongs_in_a_rule_file():
    """The other half of the control: what a rule file is *for* must survive the check.

    A threshold with the measurement behind it, the scale a form prints a test at, a printed
    reference range, a year, the length a name has to reach, an illustration of a line — these are
    the figures `CONTRIBUTING.md` asks for in place of a count, and a check that refused them would
    be a check nobody could keep. Each of these is a real stretch of a shipped rule file.
    """
    for said in ("The threshold is a power and a half, about thirty-two times: the geometric middle "
                 "between the ten-fold that honest ranges can reach and the hundred-fold of a misplaced scale.",
                 "0.15 is about forty per cent either way: enough for two laboratories printing "
                 "1,001-1,040 and 1010-1030, far too little for two ranges that are simply different.",
                 "A day that cannot exist, a year before 1900, and a date later than the document "
                 "that carries it are all refused.",
                 "0,2-1,0 % is the line of basophils on the same form, and this archive is not wrong.",
                 "Eight is what a real archive measured out; it may be the wrong number for yours.",
                 "One laboratory prints a urine specific gravity of 1,015 and the next prints 1015.",
                 "On a line reading `Vis OD = 0.99 iz sph -9.75 cyl -9,0 ax 99=0,9` there are four to choose from."):  # fmt: skip
        assert not counts_an_archive(said), said


def test_what_this_cannot_catch():
    """Named, because a check whose gaps are not written down is read as a check with none.

    Three things get past it, and all three are the same shortcoming: it reads the words around a
    number and not the number's meaning.

    - **A proportion said in words.** "A third of an archive", "half an archive", "most of them" —
      a figure by `CONTRIBUTING.md`'s standard, and no quantity this reader knows. It cannot be
      added: "half" and "a third" are ordinary words in this prose ("this is the half of the
      defect that cannot be mended"), and a check that shouts about them is a check nobody runs
      twice. Both of the ones that were there have been written as "much of" instead.
    - **A count whose paragraph never names an archive.** "Twenty-eight documents carried no date"
      says where it was counted only to a reader who knows there is nowhere else it could have
      been counted. The paragraph is the widest honest scope — wider, and a figure anywhere in a
      file that mentions an archive anywhere would fail.
    - **A thing an archive holds that is not in the list.** Pages, spellings, groups, copies,
      indicators. Each would cost false positives in prose that is about what a form prints
      ("the pages of one form belong together"), and the list holds what these counts were
      actually of.

    The honest summary: this catches the shape every count in this project has actually been
    written in, and nothing about a count makes it catchable in general. The rest is the review,
    and `CONTRIBUTING.md` is what the review reads.
    """
    assert not counts_an_archive("A rule over every date printed anywhere fires on a third of an "
                                 "archive of ordinary scans and says nothing.")
    assert not counts_an_archive("Twenty-eight documents carried no date at all.")
    assert not counts_an_archive("Ninety pages of this archive print no unit column.")
