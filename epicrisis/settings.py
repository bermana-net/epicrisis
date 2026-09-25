"""What this instance allows, kept in one file beside the archive: data/settings.json.

Every choice a person makes about their own instance lives here — which program talks to the
model and with which models, what an answer may contain, how a chart treats units, whether the
archive answers over the network and for how long. The file is written whole and put in place at
once, because a half-written settings file reads as no settings at all, and that would turn the
lock on the archive off without anybody saying so.

It used to live inside ask.py, the page that asks the model questions. That page owned the choice
of engine, of models, of units and of the lock on the network — none of which it has anything to
do with. A setting added tomorrow would have landed there again.

**Adding a setting:** one reader and one writer here, named after what a person would call it,
with the default in the reader. Nothing else in the program reads settings.json directly.
"""

import json
from pathlib import Path

from epicrisis.runs import put_in_place, temporary_name

SETTINGS_FILE = "settings.json"
ANSWER_MODES = ("as_printed", "with_meaning", "direct")


def answer_mode(data_dir: Path) -> str:
    """as_printed: values and printed ranges only. with_meaning: the model may also read them."""
    mode = _settings(data_dir).get("answer_mode", "as_printed")
    return mode if mode in ANSWER_MODES else "as_printed"


def set_answer_mode(data_dir: Path, mode: str) -> None:
    if mode not in ANSWER_MODES:
        raise ValueError("unknown answer mode")
    _write_settings(data_dir, {"answer_mode": mode})


def _settings(data_dir: Path) -> dict:
    try:
        return json.loads(settings_path(data_dir).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _write_settings(data_dir: Path, changes: dict) -> None:
    """Written whole and put in place at once, like every other file of state this program keeps.

    A half-written settings file is unreadable, and an unreadable one reads as no settings at
    all — which would turn the lock on the archive off without anybody saying so.
    """
    settings = {**_settings(data_dir), **changes}
    path = settings_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = temporary_name(path)
    temporary.write_text(json.dumps(settings, indent=1) + "\n", encoding="utf-8")
    put_in_place(temporary, path)


def settings_path(data_dir: Path) -> Path:
    return Path(data_dir) / SETTINGS_FILE


def rule_on(data_dir: Path, rule) -> bool:
    """Whether this instance runs this rule. Its own default until somebody says otherwise.

    One switch per rule, kept by the rule's id, so that a rule added later arrives with its own
    answer and an answer stored for a rule that has since been deleted simply stops mattering.
    """
    kept = _settings(data_dir)
    if rule.id in kept.get("rules", {}):
        return bool(kept["rules"][rule.id])
    # A check that has just become a rule keeps the answer this archive gave its old switch.
    if rule.was_called and rule.was_called in kept:
        return bool(kept[rule.was_called])
    return rule.on_by_default


def set_rule_on(data_dir: Path, rule_id: str, enabled: bool) -> None:
    _write_settings(data_dir, {"rules": {**_settings(data_dir).get("rules", {}), rule_id: enabled}})


def rules_on(data_dir: Path, loaded, step: str) -> list:
    """The rules one step runs here: its own, in file order, minus the ones turned off."""
    return [rule for rule in loaded.at(step) if rule_on(data_dir, rule)]


# What a chart does with units, and what a value with no unit is placed beside, used to be three
# switches here. They are rules now — see epicrisis/rules/shipped — because they are the same
# kind of decision as every other rule: they can be turned off, they can be wrong, and a person
# deciding about one needs to read why.


def trusts_read_materials(data_dir: Path) -> bool:
    """Whether a material a model read is used, where the form printed none.

    Off in the repository, like every other reading this program does not do by itself: with it
    off, a value whose form said nothing stays under "not said", which is what the form says.
    Turned on, the panel a model was sure of settles it, and every such value is marked on the
    page as read rather than printed. What the model was unsure of is never used either way.
    """
    return bool(_settings(data_dir).get("read_materials"))


def set_trusts_read_materials(data_dir: Path, enabled: bool) -> None:
    _write_settings(data_dir, {"read_materials": enabled})


def chosen_models(data_dir: Path) -> dict[str, str]:
    """Which model the person picked for each pass. Empty means the ones this program ships with."""
    chosen = _settings(data_dir).get("models")
    return chosen if isinstance(chosen, dict) else {}


def set_chosen_models(data_dir: Path, models: dict[str, str]) -> None:
    from epicrisis.models import PASSES

    # A name is an argument to a command, never a shell string, so nothing here can run; but a
    # five-hundred-character name would only fail obscurely when that step runs, so it is cut.
    kept = {name: value.strip()[:80] for name, value in models.items() if name in PASSES and value.strip()}
    _write_settings(data_dir, {"models": kept})


def mcp_lock_on(data_dir: Path) -> bool:
    """Whether the tools over the network ask for a code first. Off in the repository by default."""
    return bool(_settings(data_dir).get("mcp_lock"))


def set_mcp_lock(data_dir: Path, enabled: bool) -> None:
    _write_settings(data_dir, {"mcp_lock": enabled})


def mcp_lock_scope(data_dir: Path) -> str:
    """conversation: a code opens the conversation it was given in. server: it opens everything."""
    from epicrisis.mcp_lock import SCOPES

    scope = _settings(data_dir).get("mcp_lock_scope", "conversation")
    return scope if scope in SCOPES else "conversation"


def set_mcp_lock_scope(data_dir: Path, scope: str) -> None:
    from epicrisis.mcp_lock import SCOPES

    if scope not in SCOPES:
        raise ValueError("a lock opens a conversation or the server")
    _write_settings(data_dir, {"mcp_lock_scope": scope})


def mcp_lock_minutes(data_dir: Path) -> int:
    """How long one code keeps the archive open."""
    from epicrisis.mcp_lock import PASS_MINUTES

    minutes = _settings(data_dir).get("mcp_lock_minutes", PASS_MINUTES)
    return minutes if isinstance(minutes, int) and 1 <= minutes <= 7 * 24 * 60 else PASS_MINUTES


def set_mcp_lock_minutes(data_dir: Path, minutes: int) -> None:
    if not 1 <= int(minutes) <= 7 * 24 * 60:
        raise ValueError("a window runs from a minute to a week")
    _write_settings(data_dir, {"mcp_lock_minutes": int(minutes)})


def ask_enabled(data_dir: Path) -> bool:
    return bool(_settings(data_dir).get("ask"))


def set_ask_enabled(data_dir: Path, enabled: bool) -> None:
    _write_settings(data_dir, {"ask": enabled})
