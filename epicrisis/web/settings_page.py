"""The settings page: everything it shows, and everything one press of Save does.

Two things, kept apart on purpose, because they are two different jobs and mixing them is how
this page came to swallow refusals.

`settings_view` **shows**: the rules and their thresholds, the kind of check each one is, the
engine, the models, the answer mode, the lock over the network and the nineteen switches, gathered
into a context a template draws.

`settings_pressed` **applies a press**: it works out what changed, writes it in one transaction
under the settings lock, and hands back two things for the person who pressed — what was stored
and what was refused. It returns them as a value rather than printing or redirecting, because the
other half of this module's history is refusals that reached nobody: a threshold that could not be
read, the two choices of the lock and the engine each went into a `suppress(ValueError)` while the
page said "Saved. Nothing on the page was different from what was already stored". Something that
returns what it refused can be asked, in a test, whether it said so.

A third one only shows, and shows one thing: `who_this_instance_is_for` says which archives are
kept by whom. It is on this page because that is where it was asked for, it has no press and no
form, and it answers nothing that another file already answers — see its own first paragraph,
which is the whole of its licence to be here.

Both of the first two took which archive as an argument with no default of its own, the way every
door into an archive does, and the third takes that same reading as a value. These settings are
the instance's and not one person's, but what the page counts
beside each rule — what it has found, whether a person's own verdicts say it earns its place, how
many tables a model has been asked about — is of the archive being looked at, and `TheArchives` is
one reading of which that is.

Neither knows about `request`, `templates` or FastAPI. The routes in `web/app.py` are the shells.

It shows counts and choices only, and nothing it stores decides what is normal.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from epicrisis import engines
from epicrisis import rules
from epicrisis.classify.backend import backend_installed
from epicrisis.consent import has_consent
from epicrisis.engines import set_engine
from epicrisis.invocation import CLI
from epicrisis.mcp_lock import whoever_is_waiting
from epicrisis.mcp_lock import read_secret as read_lock_secret
from epicrisis.models import KNOWN_MODELS, PASSES, model_for
from epicrisis.rules import kinds, tally
from epicrisis.settings import editing as settings_editing
from epicrisis.settings import unreadable as settings_unreadable
from epicrisis.settings import (ANSWER_MODES, THE_WHOLE_INSTANCE, answer_mode,
                                answered_about, ask_enabled, let_the_instance_answer,
                                mcp_lock_minutes, mcp_lock_on, mcp_lock_scope, rule_on,
                                set_the_name_the_tunnel_answers_on, the_name_the_tunnel_answers_on,
                                rule_settings, set_answer_mode, set_ask_enabled,
                                set_chosen_models, set_mcp_lock, set_mcp_lock_minutes,
                                set_mcp_lock_scope, set_rule_on, set_rule_settings,
                                set_trusts_read_materials,
                                trusts_read_materials, what_a_rule_cannot_use)  # fmt: skip
from epicrisis.sources import TheArchives, source_output_dir
from epicrisis.validate import validate_source
from epicrisis.web.markdown import render_markdown

# The four tabs of the settings page, in the order they stand in. First is where an address
# that names no tab at all, or names one that is not here, arrives.
SETTINGS_TABS = ("model", "reading", "rules", "network")
# What each answer mode is called, for the line that says what one press of Save stored. The
# banner named the setting and not the side — "Saved: what may be said about a value" for the
# move into the one mode where this application compares a number with a printed range, and the
# same words for the move back out of it. Its neighbours in that list all say which way they went.
ANSWER_MODE_NAMES = {"as_printed": "as printed only", "with_meaning": "the values may also be read",
                     "direct": "no limits set here"}  # fmt: skip


def rules_are_about(archives: TheArchives, about: str) -> dict:
    """Which archive the Rules tab is asking about, and what the page says it is asking about.

    **The defect this closes, in one sentence: the count beside each switch was already counted on
    the archive being looked at, and the switch itself was one switch for the whole instance.** So
    a person read "found 255 on 255 documents" beside a box, unticked it, and turned the rule off
    on the two other archives where it had found 24 and 4 things worth looking at — with nothing
    on the page saying the two halves were about different things.

    The archive being shown is the one the counter and "Try it" already use, so the three now
    agree. The instance's own answer is a real answer and reachable by name: it is what an archive
    added next year inherits, and it is where the two rules this instance's owner switched off on
    the fourth of October stand. `about` names which of the two, and the page draws the pair as
    two addresses rather than as a form field, so that arriving at one is a link and not a press.

    Whose it is, by the owner as somebody typed it, never by an id a person has not seen: the same
    answer `who_this_instance_is_for` gives, out of the same one reading.
    """
    showing = archives.showing
    # No archive open — an instance whose list is empty, or one between archives — and then there
    # is no other question to ask: the instance's answer is the only one there is, and the page
    # says so rather than offering a choice of one.
    if showing is None:
        return {"in_archive": THE_WHOLE_INSTANCE, "whose": "", "archive": "",
                "can_choose": False, "about": "instance"}  # fmt: skip
    for_the_instance = about == "instance"
    return {
        # What every reader and writer of a rule's answer below is handed. One value, read once,
        # so that what the switches are drawn from and what the press writes cannot disagree.
        "in_archive": THE_WHOLE_INSTANCE if for_the_instance else showing.id,
        "whose": showing.whose,
        "archive": showing.id,
        "can_choose": True,
        "about": "instance" if for_the_instance else "archive",
    }


def _what_is_held_back(held: dict | None) -> str:
    """Which half of one press is waiting to be answered for, in the words the panel prints.

    Three sentences and not one, because the panel used to say "Turning this on" over a press that
    turned nothing on: a threshold moved on a costly rule is now held back too, and a person
    looking at a question about a switch they did not touch would answer it for the wrong reason.
    """
    if not held:
        return ""
    if held["switching"] and held["thresholds"]:
        return "turning it " + ("on" if held["on"] else "off") + " and moving its thresholds"
    if held["switching"]:
        return "turning it " + ("on" if held["on"] else "off")
    return "moving its thresholds"


def settings_view(data_dir: Path, archives: TheArchives, *, saved: bool = False, trouble: str = "",
                  tab: str = "", waiting: dict | None = None, trying: tuple | None = None,
                  stored: str = "", kept: dict | None = None, about: str = "") -> dict:  # fmt: skip
    """The page: for a visit, for a change held back for asking, or for a threshold tried out."""
    # The tab is a radio button and the panels are drawn by CSS from which one is checked, so
    # a name that is none of the four leaves every panel hidden and the page empty. An
    # unknown tab is the first tab, the way an unknown view is on the timeline.
    tab = tab if tab in SETTINGS_TABS else SETTINGS_TABS[0]
    # Each held-back rule, by id: the switch as it was asked for, whether the switch is moving at
    # all, and the thresholds that were typed. A bare `True`/`False` was enough while only a
    # switch could be held back; a threshold can be held back now, and a press that moves one
    # without touching the switch has to be asked about in words of its own.
    waiting = {rule_id: (held if isinstance(held, dict) else {"on": held, "switching": True, "thresholds": {}})
               for rule_id, held in (waiting or {}).items()}  # fmt: skip
    # Which archive the switches below are about, decided once for the whole page and handed to
    # every reader of a rule's answer as a value: two readings of it would be the two halves of
    # this page disagreeing again, which is the defect it was written to close.
    asking = rules_are_about(archives, about)
    in_archive = asking["in_archive"]
    # Worked out once for the whole page. Asked for per rule, this read the index, ran every
    # rule of the search and re-read the settings nineteen times over, and the page took four
    # seconds to open.
    loaded = rules.load(data_dir)
    switches = {rule.id: rule_on(data_dir, rule, in_archive=in_archive) for rule in loaded}
    chosen = {rule.id: rule_settings(data_dir, rule, in_archive=in_archive) for rule in loaded}
    # What the instance answers, beside what this archive does, so that a switch set for one
    # archive can say what the rest of them run by. Nothing on this page may show the one as the
    # other: that is the seventh entry, and it is the whole of this card.
    instance_wide = {rule.id: rule_on(data_dir, rule) for rule in loaded}
    its_own = {rule.id: answered_about(data_dir, rule.id, in_archive) for rule in loaded}
    counts = _tally(data_dir, archives, loaded, {rule for rule, on in switches.items() if on})
    tried, asked_for = _trial(data_dir, archives, loaded, trying)
    held_back = {f"{rule_id}:{name}": value for rule_id, held in waiting.items()
                 for name, value in held["thresholds"].items()}  # fmt: skip
    context = {
            "current": "settings",
            "enabled": ask_enabled(data_dir),
            "mode": answer_mode(data_dir),
            "model_ready": backend_installed(),
            "rules": [
                {"id": rule.id, "name": rule.name, "summary": rule.summary, "about": render_markdown(rule.about),
                 "at": rule.at, "cost": rule.cost, "shipped": rule.shipped, "costly": rule.costly,
                 # Whether it has a switch at all. Five of them report a hole in the archive and
                 # do not: see `Kind.stays_on` and `validate.LEFTOVER`.
                 "stays_on": rule.stays_on,
                 # Where turning it off does more than stop a line being reported, the rule
                 # says so itself and the switch says it too.
                 "switching_off": rule.switching_off,
                 "on": waiting[rule.id]["on"] if rule.id in waiting else switches[rule.id],
                 # Whether this archive has an answer of its own about this rule, and what the
                 # rest of the instance runs by where it has. Drawn beside the switch, because a
                 # switch that looks the same whether it was answered here or inherited is a
                 # switch nobody can tell they have set.
                 "its_own": bool(its_own[rule.id]) and in_archive != THE_WHOLE_INSTANCE,
                 "instance_wide": instance_wide[rule.id],
                 "found": counts.get(rule.id, tally.Tally(counted=False)).says,
                 # What this archive's own verdicts say about whether the rule earns its
                 # place. Usually nothing, which is right: it speaks only where a person has
                 # judged enough of its findings for their judgement to mean something.
                 "worth_keeping": counts.get(rule.id, tally.Tally(counted=False)).worth_keeping,
                 # The form is built from what the kind declares, so a name it does not
                 # have cannot be typed and a number cannot be given as a word.
                 "tried": tried if tried and trying and trying[0] == rule.id else None,
                 "knobs": [{"name": name.replace("_", " "),
                            # What was typed wins over what is stored, so that a number held back
                            # for asking — or tried out — is still in the field when the page
                            # comes back. Nothing here is stored by being drawn.
                            "value": held_back.get(f"{rule.id}:{name}",
                                                   asked_for.get(f"{rule.id}:{name}", chosen[rule.id][name])),
                            "field": f"{rule.id}:{name}", "means": rule.check.means.get(name, ""),
                            "number": isinstance(default, int | float) and not isinstance(default, bool),
                            "default": default}
                           for name, default in rule.settings.items()],  # fmt: skip
                 "tryable": rule.at == kinds.SUSPECTS,
                 "waiting": rule.id in waiting,
                 "turning_on": waiting[rule.id]["on"] if rule.id in waiting else None,
                 # Which half of the press is being asked about, in the words the panel prints.
                 "waiting_about": _what_is_held_back(waiting.get(rule.id))}
                # By the step that runs them, in the order the program runs its steps: what
                # turning one on asks of a person is decided by its step, so rules that ask
                # the same thing stand together.
                for rule in sorted(loaded, key=lambda rule: (kinds.AT.index(rule.at), rule.name))
            ],
            "rule_problems": loaded.problems,
            # Only the kinds a person can honestly fill in: one that places a value on a
            # scale answers in a shape of its own, and there is nothing here to type for it.
            "kinds": [{"name": name, "about": item.about, "at": item.at, "cost": item.cost,
                       # Whether the step acts on what such a rule finds rather than showing it
                       # to anybody. Sixteen of these are offered and two of the fields beside
                       # them mean nothing for one: what settles a finding nobody is shown, and
                       # where it hangs. They were written into the file anyway and the loader
                       # refused it, naming two fields the person had not filled in.
                       "answered_by_the_step": item.at in kinds.ANSWERED_BY_THE_STEP,
                       "settings": ", ".join(item.settings) or "none"}
                      for name, item in sorted(kinds.KINDS.items()) if item.does == kinds.MARKS],  # fmt: skip
            "read_materials": trusts_read_materials(data_dir),
            "passes": [
                {"key": key, "label": item["label"], "about": item["about"],
                 "chosen": model_for(data_dir, key)}
                for key, item in PASSES.items()
            ],
            "known_models": KNOWN_MODELS,
            "engines": [
                {"name": item.name, "label": item.label, "about": item.about,
                 "ready": not engines.what_it_needs(item.name, data_dir),
                 "chosen": item.name == engines.chosen_engine(data_dir),
                 "needs_what": engines.what_it_needs(item.name, data_dir)}
                for item in engines.ENGINES
            ],  # fmt: skip
            "known_names": [name for name, _about in KNOWN_MODELS],
            "read_materials_known": _tables_read(data_dir, archives),
            "mcp_lock": mcp_lock_on(data_dir),
            "mcp_lock_scope": mcp_lock_scope(data_dir),
            "mcp_lock_minutes": mcp_lock_minutes(data_dir),
            # How many locks are keeping somebody waiting after wrong codes. Each link counts its
            # own — one person guessing badly must not hold the others out — so a wait is invisible
            # from here unless the page says there is one, and the way out is a command.
            #
            # **Asked of what is in those files, not of how many there are.** A run of wrong codes
            # answered correctly leaves the file behind holding `[]`, and a run from last week has
            # aged out of the window — so counting files said "1 link is in a wait after wrong
            # codes" on this instance, with the command to clear it, over a file of two bytes
            # holding nothing. Measured on the owner's own machine.
            "waits": len(whoever_is_waiting(data_dir)),
            "public_host": the_name_the_tunnel_answers_on(data_dir),
            "mcp_secret": bool(read_lock_secret()),
            "confirmed": has_consent(data_dir, engines.engine_name(data_dir)),
            "saved": saved,
            "stored": stored,
            "trying": bool(trying),
            # Which archive the Rules tab is asking about, said on the tab itself. §7: a page that
            # shows switches outside any archive, while the count beside each one is of the
            # archive being looked at, is two different things drawn as one.
            "rules_about": asking,
            "tab": tab,
            "waiting": waiting,
            "trouble": trouble,
            # Asked on the way in, not only on the way out. The switches below come from the
            # file, and over a file that cannot be read every one of them is drawn at its
            # default — the answer mode, the materials, the length of the code's window —
            # which a person reads as the truth about their own instance. Worse for the lock:
            # it fails closed on an unreadable file, so it drew as on over an archive whose
            # owner had never turned it on, indistinguishable from their own choice. The only
            # way to learn any of this was to press Save and be refused.
            "settings_unreadable": settings_unreadable(data_dir),
            # Who this instance is for, out of the same one reading the rest of the page was
            # drawn from. Shown, and nothing else: see `who_this_instance_is_for`.
            "keeping": who_this_instance_is_for(archives),
            # The folder this instance keeps its files in, so that the commands this page gives
            # can be copied whole. Every one of them that writes a setting needs to be told
            # which instance, and the page used to print them without it.
            "data_dir": str(data_dir),
    }
    # Trying a threshold draws this page again from the submission it came in, not from
    # storage. Without this, pressing "Try it" on the Rules tab silently put back whatever a
    # person had just changed on the other three — a switch, an answer mode, a model — and
    # said nothing about it. Nothing is stored either way: trying is not saving.
    if kept:
        was_drawn = set(kept["shown"])
        if "ask_page" in was_drawn:
            context["enabled"] = kept["ask_page"] == "on"
        if "read_materials" in was_drawn:
            context["read_materials"] = kept["read_materials"] == "on"
        if "mcp_lock" in was_drawn:
            context["mcp_lock"] = kept["mcp_lock"] == "on"
        if kept["mode"] in ANSWER_MODES:
            context["mode"] = kept["mode"]
        context["mcp_lock_scope"] = kept["mcp_lock_scope"]
        context["mcp_lock_minutes"] = kept["mcp_lock_minutes"]
        context["public_host"] = kept["public_host"]
        for item in context["engines"]:
            if any(kept["engine"] == known.name for known in engines.ENGINES):
                item["chosen"] = item["name"] == kept["engine"]
        for item in context["passes"]:
            item["chosen"] = kept["models"].get(item["key"]) or item["chosen"]
        for rule in context["rules"]:
            if rule["id"] in was_drawn:
                rule["on"] = rule["id"] in kept["rules_on"]
    return context


def who_this_instance_is_for(archives: TheArchives) -> dict:
    """Which archives are kept by whom, for the one place in this program that shows it.

    **It shows and it does not decide**, and the line matters enough to be the first sentence
    here. Three things it is not allowed to become, each of them a question that is already
    answered somewhere else and would then be answered twice: which archives exist, which is
    `sources.json`'s; which archive is open, which is `sources.json`'s too; and who may open one,
    which nothing in this program answers yet. There is no press on this block and no form around
    it. What a person reads here they can act on through the doors that already exist — a name is
    typed on the archive status page, where it always was.

    No signature is handed to the page. A keeper has no name, so what names them here is the work
    they do: the archives they keep, by the owner each archive carries, as somebody typed it. That
    is also what makes a wrong grouping visible by reading the screen, which is the third of the
    three things the fourth entry asks of a claim a program makes on its own.

    Everything comes from the one reading the page was drawn from, and nothing is read again:
    `TheArchives` carries the keepers for exactly this, because a page that read the archives and
    then the keepers would be two readings inside one answer.
    """
    held = archives.keepers
    kept_by_nobody = archives.kept_by_nobody
    return {
        # The file is there and will not read. Two different things from "there are no keepers",
        # and the page says which: a switch drawn at its default over an unreadable file is the
        # failure this page has already had once, two notices further up.
        "unreadable": held is None,
        # Whether this instance has a keeper at all, which is what decides whether any of this is
        # drawn. An instance from before keepers existed has none until the next name is typed on
        # an archive, and about such an instance the honest thing to draw is nothing: the link has
        # not been written, so there is nothing to show, and a block announcing that every archive
        # is kept by nobody would be noise on a page a person goes to when something is wrong.
        "written_down": bool(held),
        "keepers": [
            {"archives": [one.whose for one in archives.kept_by(keeper)]}
            for keeper in held or ()
            if archives.kept_by(keeper)
        ],
        # Said rather than left out: an archive nobody keeps is the ordinary state of a folder
        # whose owner has not been typed yet, and a shorter list here than on the archives page,
        # with nothing saying why, is the seventh entry's defect.
        "nobody": [one.whose for one in kept_by_nobody],
        # A signature on the list that keeps no archive on it. It is what is left of an archive
        # taken off the list, and of a file written by the step before this one, which issued
        # signatures and wrote no link at all.
        "keep_nothing": sum(1 for keeper in held or () if not archives.kept_by(keeper)),
    }


@dataclass(frozen=True)
class Pressed:
    """What one press of Save came to: what was stored, what was refused, and what to draw.

    `stored` and `refused` are the two halves of one sentence, and both are here because a press
    that stored eleven switches and turned down one number has two true things to say. The page
    used to say the first and swallow the second.

    `draw_again` is the settings page again, in `settings_view`'s own words, for the three presses
    that do not end in a redirect: a settings file that cannot be read, a threshold being tried
    out, and a costly rule held back for asking. Where it is None the press is over and the route
    sends the person back to the page.
    """

    stored: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()
    #: Each rule held back for asking, by id: the switch as it was asked for, whether the switch
    #: moves at all, and the thresholds that were typed. See `_what_is_held_back`.
    waiting: dict[str, dict] = field(default_factory=dict)
    trouble: str = ""
    draw_again: dict | None = None

    @property
    def said(self) -> str:
        """What was stored, in a person's words. "Saved." on its own, over a page that can store
        an engine, three models, an answer mode, nineteen switches, their thresholds and the lock
        in one press, says that something happened and not what."""
        return ", ".join(self.stored)


def settings_pressed(data_dir: Path, archives: TheArchives, *, ask_page: str = "",
                     mode: str = "as_printed", engine: str = "",
                     rule_on_ids: Sequence[str] = (), shown: Sequence[str] = (),
                     confirmed_rules: Sequence[str] = (), read_materials: str = "",
                     models: dict[str, str] | None = None, mcp_lock: str = "",
                     mcp_lock_scope_choice: str = "conversation",
                     mcp_lock_minutes_choice: int = 240,
                     public_host: str = "",
                     knob_name: Sequence[str] = (), knob_value: Sequence[str] = (),
                     try_rule: str = "", tab: str = "", about: str = "",
                     the_instance_answers: Sequence[str] = (),
                     build_indexes: Callable[[], str | None]) -> Pressed:  # fmt: skip
    """One press of Save: what it changed, written once, and what it has to say for itself.

    Which archive comes in as a value with no default of its own, as every door into an archive
    does. `build_indexes` comes in the same way and for a plainer reason: building every archive's
    index again is what the indicator page does too, so it is one thing in one place in the routes
    and is handed here rather than reached for.
    """
    models = models or {}
    # Which archive the switches on this press were drawn about, read the same way the page read
    # it. The press carries the word rather than working it out again from which archive is open:
    # a person can switch archive in another tab between the draw and the press, and a press that
    # answered about whichever archive is open now would write their answer into somebody else's.
    asking = rules_are_about(archives, about)
    in_archive = asking["in_archive"]
    # Which settings a rule has is the kind's business and changes with it, so the knobs
    # cannot be declared one by one here. They travel as two lists in the order the page
    # wrote them: what each one is, and what was typed into it.
    form = dict(zip(knob_name, knob_value, strict=False))
    # Nothing on this page can be stored while the file it is all stored in cannot be read:
    # every write builds the whole file from what is there, so one saved setting would take
    # the place of all the rest. Said on the page rather than raised at it.
    if settings_unreadable(data_dir):
        return Pressed(draw_again={"tab": tab, "about": about, "trouble": (
            "The settings file of this instance is there and cannot be read, so nothing was "
            "changed. Repair data/settings.json, or move it aside to start from the defaults. "
            "Until then the lock over the network stays on, if a code was ever set up here."
        )})  # fmt: skip
    # Trying is not saving. Nothing at all is stored on this path: a person turning a
    # threshold over in their hands has not decided anything yet.
    if try_rule:
        return Pressed(draw_again={"tab": "rules", "about": about, "trying": (try_rule, form), "kept": {
            "shown": shown, "ask_page": ask_page, "engine": engine, "mode": mode,
            "models": models,
            "read_materials": read_materials, "mcp_lock": mcp_lock,
            "mcp_lock_scope": mcp_lock_scope_choice, "mcp_lock_minutes": mcp_lock_minutes_choice,
            "public_host": public_host,
            "rules_on": set(rule_on_ids),
        }})  # fmt: skip
    # What was in fact stored, in a person's words. "Saved." on its own, over a page that can
    # store an engine, three models, an answer mode, nineteen switches, their thresholds and
    # the lock in one press, says that something happened and not what.
    stored: list[str] = []
    # And what was refused, which is the other half of the same sentence: a press that stored
    # eleven switches and turned down one number has two true things to say, and the page used
    # to say the first and swallow the second.
    refused: list[str] = []
    waiting, changed = {}, set()
    thresholds, switched = 0, 0
    trouble = None
    build_again = False
    # One press of Save is one change of settings.json: one write, and one copy of the
    # version before the press. Every line below used to write the whole file for itself —
    # measured at 44 writes and 44 copies for a press over 26 rules and 25 thresholds — so
    # settings.json.previous, which this program's own refusal offers in so many words as
    # "the version before the last change", was left holding the middle of the press a
    # person had just made. settings.editing holds the lock for the whole of this and
    # gathers the writes into one; the writers below are unchanged and still take it
    # themselves when a command calls them one at a time.
    with settings_editing(data_dir):
        if "ask_page" in shown and ask_enabled(data_dir) != (ask_page == "on"):
            set_ask_enabled(data_dir, ask_page == "on")
            stored.append("answering questions " + ("on" if ask_page == "on" else "off"))
        # An engine that is not built, or not known, is not stored — and now it is not stored
        # in silence either. This stood under "a form can always be made to say something the
        # page did not", which is the reason to answer such a form rather than to drop it: the
        # refusals engines.set_engine raises are sentences written for a person, "no such
        # engine: X" and "<engine> cannot answer yet: <what is missing>", and under a suppress
        # the page replied "Saved. Nothing on the page was different from what was already
        # stored" over a press it had just refused. The page does say "Not ready" beside the
        # radio it draws disabled, but that is the state of a thing, not an answer to a press.
        if engine and engine != engines.chosen_engine(data_dir):
            try:
                set_engine(data_dir, engine)
            except ValueError as refusal:
                refused.append(f"The engine was not stored: {refusal}. It still stands at "
                               f"{engines.engine_name(data_dir)}.")  # fmt: skip
            else:
                stored.append(f"the engine — {engine}")
        # Checkboxes only say what is ticked, so what is not in the list is what was turned
        # off. A rule whose step reads documents again is not stored on the strength of a
        # click: it is held back, said out loud with what it will cost, and stored on the
        # second answer. A checkbox that is not ticked is not sent at all, so a form arriving
        # without one is indistinguishable from a form that turned it off. The page says what
        # it drew, and only those are changed — otherwise a half-sent form silently turns off
        # everything at once, and for the switch that reads materials that also means
        # rebuilding the index.
        for rule in rules.load(data_dir):
            if rule.id not in shown:
                continue
            # "Let the instance answer" on one rule: this archive's own answer about it goes,
            # and what every other archive runs by stands again. Done before the switch and the
            # thresholds below are read, because the box beside it is drawn at whatever this
            # archive answered and pressing this one says that answer should not exist — reading
            # the box afterwards would write it straight back.
            if rule.id in the_instance_answers and in_archive != THE_WHOLE_INSTANCE:
                if answered_about(data_dir, rule.id, in_archive):
                    let_the_instance_answer(data_dir, rule.id, in_archive)
                    changed.add(rule.at)
                    stored.append(f"“{rule.name}” answered by this instance again")
                continue
            # The thresholds are saved for every rule, switched on or not: turning one on next
            # month should find what somebody set for it, not what it shipped with. Saved only
            # when they differ, so that an untouched page rewrites nothing. Where the step reads
            # documents again, they are held back for the same question the switch is held back
            # for — see below, where both halves of one press are asked about together.
            given = {name: form[f"{rule.id}:{name}"] for name in rule.settings
                     if form.get(f"{rule.id}:{name}") not in (None, "")}  # fmt: skip
            now = {name: str(value) for name, value in
                   rule_settings(data_dir, rule, in_archive=in_archive).items() if name in given}  # fmt: skip
            # A number this rule cannot read is refused by name, out loud, and the one already
            # stored for it is written straight back. Two things were wrong here. The write
            # replaces every threshold of a rule at once and settings.py refuses the whole
            # rule on the first value it cannot read, so one mistyped number lost every other
            # threshold of that rule as well; and the refusal — a sentence written for a
            # person — went into a suppress(ValueError), under which the page said "Saved.
            # Nothing on the page was different from what was already stored". Measured on a
            # rule of three thresholds with one of the three mistyped: both good ones lost,
            # and that sentence, which is false about the page and about the storing both.
            cannot = what_a_rule_cannot_use(rule, given)
            for name, wants in cannot.items():
                refused.append(f"“{name.replace('_', ' ')}” of “{rule.name}” wants {wants}, so "
                               f"that one was not stored and still stands at {now[name]}.")  # fmt: skip
            given = {**given, **{name: now[name] for name in cannot}}
            moving_thresholds = bool(given and given != now)
            wanted = rule.id in rule_on_ids
            # A rule with no switch is never switched by a press, and asking the form about it
            # would read the absent box as "turn it off": the page draws no box for it, and a box
            # that is not drawn is a box that is not sent.
            switching = not rule.stays_on and wanted != rule_on(data_dir, rule, in_archive=in_archive)
            # **One question for both halves of one press**, and the reason is money. A switch
            # whose step reads documents again is held back and asked about; the threshold of the
            # same rule costs exactly as much and was stored on the click, three lines above the
            # check that was supposed to stand between a person and that cost. `least_number_share`
            # from 0.9 to 0.5, or `least_characters` from 20 to 200, and the next run sends most of
            # an archive to the strongest model there is. The confirmation was built one round ago
            # to make that reachable; this is the half that walked round it.
            if (moving_thresholds or switching) and rule.costly and rule.id not in confirmed_rules:
                waiting[rule.id] = {"on": wanted, "switching": switching,
                                    # What was typed, kept so that saying yes is one press and
                                    # not a page of numbers to type again.
                                    "thresholds": dict(given) if moving_thresholds else {}}  # fmt: skip
                continue
            if moving_thresholds:
                try:
                    set_rule_settings(data_dir, rule, given, in_archive=in_archive)
                except ValueError as refusal:
                    # Nothing the question above leaves behind, and still never in silence:
                    # a refusal this page cannot explain is a refusal it says in full.
                    refused.append(f"“{rule.name}” did not store its thresholds: {refusal}.")
                else:
                    changed.add(rule.at)
                    thresholds += 1
            if not switching:
                continue
            set_rule_on(data_dir, rule.id, wanted, in_archive=in_archive)
            changed.add(rule.at)
            switched += 1
        # What was stored says which archive it was about, because the same press with the other
        # address stores something else entirely. "2 rules switched" over a page that can answer
        # for one archive or for every one of them says that something happened and not what.
        whose = (" for every archive" if in_archive == THE_WHOLE_INSTANCE
                 else f" for {asking['whose']}’s archive" if asking["whose"]
                 else " for the archive shown")  # fmt: skip
        if thresholds:
            stored.append(f"thresholds of {thresholds} rule"
                          + ("s" if thresholds != 1 else "") + whose)  # fmt: skip
        if switched:
            stored.append(f"{switched} rule" + ("s" if switched != 1 else "") + " switched" + whose)
        if "models" in shown:
            was_models = {key: model_for(data_dir, key) for key in PASSES}
            set_chosen_models(data_dir, {
                "first": models.get("first", ""), "strong": models.get("strong", ""),
                "second_reader": models.get("second_reader", ""),
            })  # fmt: skip
            if {key: model_for(data_dir, key) for key in PASSES} != was_models:
                stored.append("the models")
        # This one changes what is in the index, not only how a page draws it, so the index is
        # built again — and only when the answer actually changed.
        if "read_materials" in shown and trusts_read_materials(data_dir) != (read_materials == "on"):
            set_trusts_read_materials(data_dir, read_materials == "on")
            stored.append("reading the material from the table heading "
                          + ("on" if read_materials == "on" else "off")
                          + ", and the index built again")
            build_again = True
        if "mcp_lock" in shown and mcp_lock_on(data_dir) != (mcp_lock == "on"):
            set_mcp_lock(data_dir, mcp_lock == "on" and bool(read_lock_secret()))
            stored.append("the lock over the network " + ("on" if mcp_lock_on(data_dir) else "off"))
        # The two choices of the lock, and the same defect the thresholds above had. Both
        # refusals are sentences written for a person — "a lock opens a conversation or the
        # server", "a window runs from a minute to a week" — and both went into a
        # suppress(ValueError), under which this page went on to say "Saved. Nothing on the
        # page was different from what was already stored": false about the page and false
        # about the storing, with the cause of the refusal in hand and thrown away. Measured
        # with a window of 0 minutes: the page said it had saved, and the window still stood
        # at 240. Neither is reachable from the page as it is drawn — one is a select of two
        # values, the other an input carrying min and max — but what a browser will not send
        # is not what this server will not be sent, and the seventh entry does not make that
        # exception.
        if mcp_lock_scope_choice != mcp_lock_scope(data_dir):
            try:
                set_mcp_lock_scope(data_dir, mcp_lock_scope_choice)
            except ValueError as refusal:
                refused.append(f"What a code opens was not stored: {refusal}. It still stands "
                               f"at “{mcp_lock_scope(data_dir)}”.")  # fmt: skip
            else:
                stored.append("what a code opens")
        if mcp_lock_minutes_choice != mcp_lock_minutes(data_dir):
            try:
                set_mcp_lock_minutes(data_dir, mcp_lock_minutes_choice)
            except ValueError as refusal:
                refused.append(f"How long a code lasts was not stored: {refusal}. It still "
                               f"stands at {mcp_lock_minutes(data_dir)} minutes.")  # fmt: skip
            else:
                stored.append("how long a code lasts")
        if "public_host" in shown and public_host.strip().rstrip(".") != the_name_the_tunnel_answers_on(data_dir):
            try:
                set_the_name_the_tunnel_answers_on(data_dir, public_host)
            except ValueError as refusal:
                # Named back in the person's own words rather than as a pattern: what gets pasted
                # into this box is a whole URL out of an address bar, and "a host name: no
                # https://" tells somebody what to delete.
                refused.append(f"The name the tunnel answers on was not stored: {refusal}. It "
                               f"still stands at “{the_name_the_tunnel_answers_on(data_dir) or 'nothing'}”.")  # fmt: skip
            else:
                stored.append("the name the tunnel answers on" if public_host.strip()
                              else "that this instance has no public name")  # fmt: skip
        if mode in ANSWER_MODES and mode != answer_mode(data_dir):
            set_answer_mode(data_dir, mode)
            stored.append("what may be said about a value — " + ANSWER_MODE_NAMES[mode])
    # Stored first, then built out of it. The checks and the index read settings.json off the
    # disk, and the index reads it from threads of its own, so neither can run while the
    # choices of this press are still gathered in one thread's hands and not yet written.
    #
    # A rule turned off has to stop counting now, not at the next run of the checks. The
    # findings of an archive are a file on disk; leaving it as it was would show a person
    # findings from a rule they have just switched off, with no way to tell why they persist.
    if kinds.VALIDATE in changed:
        trouble = check_every_archive(data_dir, archives) or trouble
        # And then built in. The findings of a check live in the index as well as in the file
        # of findings, and the tools answer over the network from the index: a rule switched
        # off cleared the page and went on being handed to a model as something to look at,
        # with nothing on either side to say why.
        build_again = True
        stored.append("every archive checked again and built in")
    # Once for the whole press, however many of the things above asked for it. Two of them in
    # one press built every archive's index twice, and the second build's failure quietly
    # replaced the first one's.
    if build_again:
        trouble = build_indexes() or trouble
    # Said where this page already says a refusal, and never instead of what was stored.
    if refused:
        trouble = " ".join([*refused, *([trouble] if trouble else [])])
    answer = Pressed(stored=tuple(stored), refused=tuple(refused), waiting=waiting,
                     trouble=trouble or "")  # fmt: skip
    if waiting:
        # Everything else is already stored; only the held-back ones come back as a question,
        # shown the way they were asked for so that answering yes is one step and not two.
        return replace(answer, draw_again={"saved": True, "trouble": answer.trouble, "tab": "rules",
                                           "about": about, "waiting": waiting,
                                           "stored": answer.said})  # fmt: skip
    return answer


def check_every_archive(data_dir: Path, archives: TheArchives) -> str:
    """Every archive checked again with the rules as they now stand. No model, seconds."""
    for source in archives.all:
        try:
            validate_source(source_output_dir(data_dir, source.id), Path(source.path))
        except Exception as exc:  # the type only: a message can quote a document
            return f"The archive could not be checked again: {type(exc).__name__}. Run {CLI} validate."
    return ""


def _trial(data_dir: Path, archives: TheArchives, loaded, trying: tuple | None):
    """What one rule would find with the thresholds just typed, and those thresholds back.

    The numbers a person typed are handed back to the page whether the trial worked or not:
    a form that forgot what was in it the moment you asked a question of it is worse than no
    question at all.
    """
    if not trying:
        return None, {}
    rule_id, typed = trying
    rule = loaded.get(rule_id)
    if rule is None:
        return None, typed
    wanted = {name: typed[f"{rule_id}:{name}"] for name in rule.settings if f"{rule_id}:{name}" in typed}
    showing = archives.showing
    try:
        asked = {name: type(rule.settings[name])(value) for name, value in wanted.items()}
        return tally.trial(data_dir, showing.id if showing else "", rule, asked), typed
    except (TypeError, ValueError):
        return {"trouble": "Those are not numbers this rule can use."}, typed
    except Exception:  # a half-built archive is not a reason for the page to fail
        return {"trouble": "This archive could not be read just now."}, typed


def _tally(data_dir: Path, archives: TheArchives, loaded, on: set[str]) -> dict:
    """What every rule has found on the archive being shown. A fifth of a second, so it is
    worked out when the page is drawn rather than kept and left to go stale."""
    showing = archives.showing
    try:
        return tally.counts(data_dir, showing.id if showing else "", loaded, on)
    except Exception:  # a half-built archive is not a reason for the settings page to fail
        return {}


def _tables_read(data_dir: Path, archives: TheArchives) -> int:
    """How many tables a model has already been asked about, in the archive that is open.

    Not every archive here: what it is shown beside is what this archive's own reading has
    settled, and a total of several people's would be a number about nobody.
    """
    from epicrisis.material_reading import answered

    return sum(len(answered(source_output_dir(data_dir, source.id))) for source in archives.open)
