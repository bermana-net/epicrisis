"""The rules this program checks an archive against, one file each.

Why a registry at all. A check written into the step that runs it can only be changed by
changing the program: it cannot be switched off for an archive where it is noise, it cannot say
which rule found a thing, and nobody can tell whether it has ever been right. Rules also go
stale — a rule that fires once on one laboratory's form and never again is a rule to delete, and
you can only delete what you can count.

A rule is one file: a TOML header a machine reads and a Markdown body a person reads. The body
is the larger part and the one that matters, because the person deciding whether to turn a rule
on needs to know what it looks at and how it can be wrong. What a rule does is not in the file:
the file names a *kind* of check, and the kinds live in kinds.py, in this repository, under
tests. A rule of a kind that already exists is one file and no code at all.

That division is not tidiness, it is the security boundary. Rules are meant to be shared - one
person's laboratory prints something nobody else has ever seen - and a shared rule must be a
thing you can read, not a thing that runs. Nothing loaded from an archive's own folder can bring
code with it, because a rule file cannot hold code and a kind cannot come from there.

Two folders, one format:

- `epicrisis/rules/shipped/` — the rules that come with the program. They live in the
  repository, so a change to one is a diff somebody can read and argue with.
- `<data>/rules/` — the rules this instance added for itself. Same format, same checking, and
  they may only name a kind that already exists.

Two things a rule file states about itself and the loader checks against the kind: what it
`does` — `marks` sends a row or a document to be looked at, `places` says what scale or unit
something is printed in, and there is no third one — and where it runs, `at`. Both are on the
kind already; the file repeats them because the first question a person opening a rule has is
what it is allowed to do and what part of the program it belongs to, and an answer that has to
be looked up somewhere else is an answer nobody looks up. Where the two disagree the file is
refused, so they cannot drift apart.
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from epicrisis import layout
from epicrisis.printed_values import as_a_name
# The steps and what each costs are the table in kinds.py, asked at the point of use and not
# bound here: a name imported once is a second copy of the answer, and this file refuses a
# rule by it.
from epicrisis.rules import kinds
from epicrisis.rules.kinds import DOES, KINDS, Kind

FENCE = "+++"
SHIPPED = Path(__file__).resolve().parent / "shipped"
# Inside the data directory: this instance's own rules. The name comes from layout.py,
# which owns the names of everything this program writes beside an archive — and which also
# names this folder among what the checks are built from, so that a rule edited by hand
# ages their answer. Two spellings of one name is how those two come apart.
FOLDER_NAME = layout.RULES


class RuleFileProblem(ValueError):
    """A rule file that cannot be read. Named, never raised at the program: see load()."""


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    summary: str  # one sentence, for the line beside the switch; the body is behind it
    kind: str
    does: str
    at: str
    on_by_default: bool
    # The name this rule's switch had before it was a rule, if it had one. Read only where no
    # answer has been stored for the rule itself, so that a check moving into a file does not
    # quietly change what an archive had already chosen. Remove it once nobody can still be
    # carrying the old answer.
    was_called: str
    # What a person is being asked to do about a finding, where it hangs, and where it stands in
    # the queue. A list of findings without these is a wall: it says a check failed and leaves
    # the reader to work out whether it is their problem and what would settle it.
    settles: str
    attaches: str  # "value" or "document", and empty for a rule that finds nothing
    # What turning this one off does, where that is more than "it stops reporting". A rule that
    # marks copies decides which document of a group answers, so switching it off makes every copy
    # answer separately — the same measurement two or three times in every series, on every chart
    # and in every answer over the network. Nothing said that anywhere, and the page invited it.
    switching_off: str
    order: int
    settings: dict
    about: str  # the Markdown body, for the person deciding whether to turn it on
    shipped: bool
    path: Path

    @property
    def check(self) -> Kind:
        return KINDS[self.kind]

    @property
    def costly(self) -> bool:
        """Whether turning this one on or off asks for a confirmation rather than a click."""
        return self.at in kinds.COSTLY

    @property
    def cost(self) -> str:
        """What turning this one on or off asks of a person. Decided by the step it runs at."""
        return self.check.cost


@dataclass
class Rules:
    """What was loaded, and what could not be. A bad file is reported, never fatal.

    A rule file with a typo in it must not stop an archive from opening. The program runs
    without that rule and says so, in the same place it says everything else about rules.
    """

    rules: list[Rule] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def __iter__(self):
        return iter(self.rules)

    def __len__(self) -> int:
        return len(self.rules)

    def get(self, rule_id: str) -> Rule | None:
        return next((rule for rule in self.rules if rule.id == rule_id), None)

    def of_kind(self, kind: str) -> list[Rule]:
        return [rule for rule in self.rules if rule.kind == kind]

    def at(self, step: str) -> list[Rule]:
        """The rules one step of the program runs. How a step asks for its own and no others."""
        return [rule for rule in self.rules if rule.at == step]


def split(text: str) -> tuple[dict, str]:
    """A rule file: a TOML header between +++ fences, then Markdown for a person."""
    lines = text.lstrip().splitlines()
    if not lines or lines[0].strip() != FENCE:
        raise RuleFileProblem(f"no {FENCE} header")
    try:
        end = lines.index(FENCE, 1)
    except ValueError:
        raise RuleFileProblem(f"the {FENCE} header is not closed") from None
    try:
        header = tomllib.loads("\n".join(lines[1:end]))
    except tomllib.TOMLDecodeError as exc:
        raise RuleFileProblem(f"the header is not valid TOML: {exc}") from None
    return header, "\n".join(lines[end + 1 :]).strip()


def read(path: Path, shipped: bool) -> Rule:
    """One rule file, checked against the kind it names. Raises RuleFileProblem."""
    header, about = split(path.read_text(encoding="utf-8"))
    for name in ("id", "name", "summary", "kind", "does", "at"):
        if not isinstance(header.get(name), str) or not header[name].strip():
            raise RuleFileProblem(f"{name} is missing")
    if header["id"] != path.stem:
        raise RuleFileProblem(f"id is {header['id']!r} and the file is named {path.stem!r}")
    kind = KINDS.get(header["kind"])
    if kind is None:
        raise RuleFileProblem(f"no such kind of check: {header['kind']!r}")
    if header["does"] not in DOES:
        raise RuleFileProblem(f"does is {header['does']!r}, and it can only be one of {', '.join(DOES)}")
    if header["does"] != kind.does:
        raise RuleFileProblem(f"this rule says it {header['does']} and {kind.name} {kind.does}")
    if header["at"] not in kinds.AT:
        raise RuleFileProblem(f"at is {header['at']!r}, and it can only be one of {', '.join(kinds.AT)}")
    if header["at"] != kind.at:
        raise RuleFileProblem(f"this rule says it runs at {header['at']} and {kind.name} runs at {kind.at}")
    if not about:
        raise RuleFileProblem("nothing is written about what this rule does or how it can be wrong")
    # A rule that sends something to be looked at has to say what would settle it, and where the
    # finding hangs. Without the first, a person is given a wall; without the second, nothing
    # knows whether to show it against a value or against the whole document.
    if header["does"] == "marks":
        if not str(header.get("settles", "")).strip():
            raise RuleFileProblem("settles is missing: a rule that marks has to say what settles it")
        if header.get("attaches") not in ("value", "document"):
            raise RuleFileProblem("attaches should be value or document")
    settings = _settings(header.get("settings", {}), kind)
    return Rule(
        id=header["id"], name=header["name"], summary=header["summary"].strip(),
        kind=header["kind"], does=header["does"], at=header["at"],
        on_by_default=bool(header.get("on_by_default", True)),
        was_called=str(header.get("was_called", "")), settles=str(header.get("settles", "")).strip(),
        attaches=str(header.get("attaches", "")), switching_off=str(header.get("switching_off", "")).strip(),
        order=int(header.get("order", 99)), settings=settings,  # fmt: skip
        about=about, shipped=shipped, path=path,
    )  # fmt: skip


def _settings(given: dict, kind: Kind) -> dict:
    """The kind's own settings, with what the file gives. A name the kind does not have is an error.

    Silently ignoring an unknown setting is how a rule ends up doing something other than what
    its file says: a misspelt threshold would leave the default in place and nobody would know.
    """
    if not isinstance(given, dict):
        raise RuleFileProblem("settings is not a table")
    for name, value in given.items():
        if name not in kind.settings:
            raise RuleFileProblem(f"{kind.name} has no setting called {name!r}")
        wanted = type(kind.settings[name])
        # bool is an int in Python, and a rule that wants a number should not accept "true".
        if isinstance(value, bool) != isinstance(kind.settings[name], bool) or not isinstance(value, wanted | int if wanted is float else wanted):
            raise RuleFileProblem(f"{name} should be {wanted.__name__} and is {type(value).__name__}")
    return {**kind.settings, **given}


def load(data_dir: Path | None = None, shipped_dir: Path | None = None) -> Rules:
    """Every rule, the ones that ship first, then this instance's own."""
    loaded = Rules()
    folders = [(shipped_dir or SHIPPED, True)]
    if data_dir is not None:
        folders.append((Path(data_dir) / FOLDER_NAME, False))
    for folder, shipped in folders:
        for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
            try:
                rule = read(path, shipped)
            except (RuleFileProblem, OSError, UnicodeDecodeError) as exc:
                loaded.problems.append(f"{path.name}: {exc}")
                continue
            if loaded.get(rule.id):
                loaded.problems.append(f"{path.name}: there is already a rule called {rule.id!r}")
                continue
            loaded.rules.append(rule)
    return loaded


def slug(name: str) -> str:
    """A name a person typed, as a rule file can be called. The answer is printed_values.

    It was four lines of its own here, and they kept the Latin letters and threw the rest away.
    Two of the five languages on these forms are written in Cyrillic and one in Greek, so a rule
    named in any of them left nothing behind and came out as the fallback alone: 'Діапазон
    прочитано двома способами' and 'Μία κλίμακα' were both 'a-rule'. This is written from the
    settings page, where the one thing a rule needs is a name — so the second rule a person wrote
    was refused with "There is already a rule called 'a-rule'", an id they had never typed, with
    nothing on the form to suggest the name had to be in Latin letters and a file called a-rule.md
    in the folder saying nothing either. On a Ukrainian, Russian or Greek instance a person could
    write one rule.

    indicators.slug had the answer already, transliteration and unique-name loop and the comment
    saying what each was bought by. It lives in printed_values now, where the fold does, and both
    ask it. Two things stay here, because they are about rules and not about letters: the fallback
    for a name that leaves nothing behind, and that the loop is not asked for. An indicator
    proposed by a model may arrive beside one of the same label and has to be given a name
    anyway; a rule is one person typing one name on a form, and a second rule of the same name is
    refused and told so, which is the decision test_a_name_already_taken_is_refused holds.
    """
    return as_a_name(name, fallback="a-rule")


def _as_toml(text: str) -> str:
    """One string, written so that what it says cannot become part of the file's own grammar.

    These lines used to be built by putting the typed name between three quotes. A name holding
    three quotes of its own closed the string there and the rest of it was read as more keys of
    the rule's header — enough to set a rule on by default that nobody turned on. It could go no
    further than that (the id is a slug, the kind is checked against the ones that exist, and a
    header that will not parse throws the file away), but a name is a thing a person types, and
    nothing a person types should be able to reach the shape of the file.
    """
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    escaped = "".join(ch if ch >= " " and ch != "\x7f" else f"\\u{ord(ch):04x}" for ch in escaped)
    return f'"{escaped}"'


def write_one(data_dir: Path, header: dict, about: str, kinds: dict) -> tuple[str, str]:
    """A rule of this archive's own. Returns its id, or an empty id and what is wrong with it.

    Written, then read back before it is allowed to stay. A file the registry cannot take would
    otherwise sit in the folder saying so on every page, and the person who wrote it would be
    told at some later moment, about something they had stopped thinking about.
    """
    kind = kinds.get(header.get("kind", ""))
    if kind is None:
        return "", "Choose a kind of check."
    if not str(header.get("name", "")).strip():
        return "", "A rule needs a name."
    rule_id = slug(header.get("id") or header["name"])
    folder = Path(data_dir) / FOLDER_NAME
    folder.mkdir(parents=True, exist_ok=True)
    if load(data_dir).get(rule_id) or (folder / f"{rule_id}.md").exists():
        # What puts it right, because the refusal used to say only that something was there. It
        # could not say more while every name in Cyrillic or Greek came out as 'a-rule': the id
        # named nothing the person had typed, and "give it another name" would have been no help
        # at all, since another name came out as 'a-rule' too.
        return "", f"There is already a rule called {rule_id!r}. Give this one a name of its own."

    lines = [FENCE, f"id = {_as_toml(rule_id)}", f"name = {_as_toml(header['name'].strip())}",
             f"summary = {_as_toml((header.get('summary') or header['name']).strip())}",
             f"kind = {_as_toml(kind.name)}", f"does = {_as_toml(kind.does)}", f"at = {_as_toml(kind.at)}",
             "on_by_default = false  # somebody else's archive has not agreed to this one"]  # fmt: skip
    if kind.does == "marks":
        lines += [f"attaches = {_as_toml(header.get('attaches') or 'document')}",
                  f"settles = {_as_toml((header.get('settles') or 'Open the page and see.').strip())}"]  # fmt: skip
    written = "\n".join(lines) + f"\n{FENCE}\n\n" + (about.strip() or "# Written here\n\nNo more was said.") + "\n"

    path = folder / f"{rule_id}.md"
    path.write_text(written, encoding="utf-8")
    try:
        read(path, shipped=False)
    except RuleFileProblem as wrong:
        path.unlink(missing_ok=True)
        return "", str(wrong)
    from epicrisis.runs import belongs_to_the_folder

    belongs_to_the_folder(path)
    return rule_id, ""
