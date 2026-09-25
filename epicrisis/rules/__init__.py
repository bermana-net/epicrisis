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

from epicrisis.rules.kinds import AT, DOES, KINDS, Kind

FENCE = "+++"
SHIPPED = Path(__file__).resolve().parent / "shipped"
FOLDER_NAME = "rules"  # inside the data directory: this instance's own


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
        from epicrisis.rules.kinds import COSTLY

        return self.at in COSTLY

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
    if header["at"] not in AT:
        raise RuleFileProblem(f"at is {header['at']!r}, and it can only be one of {', '.join(AT)}")
    if header["at"] != kind.at:
        raise RuleFileProblem(f"this rule says it runs at {header['at']} and {kind.name} runs at {kind.at}")
    if not about:
        raise RuleFileProblem("nothing is written about what this rule does or how it can be wrong")
    settings = _settings(header.get("settings", {}), kind)
    return Rule(
        id=header["id"], name=header["name"], summary=header["summary"].strip(),
        kind=header["kind"], does=header["does"], at=header["at"],
        on_by_default=bool(header.get("on_by_default", True)),
        was_called=str(header.get("was_called", "")), settings=settings,
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
