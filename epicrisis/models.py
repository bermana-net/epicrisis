"""Which model does which pass, as the person whose archive this is chooses.

Three jobs, and every model-backed step is one of them:

- the first pass reads a page cheaply and is wrong often enough that its work is checked;
- the strong pass reads again wherever a check failed, and does the thinking jobs — grouping
  printed names, searching a document for its date, answering a question;
- the second reader reads a document a third time, independently, so that two readings can be
  compared. It exists to disagree, so it is worth making it a different model from the others.

The list below is what this program knows how to name. A subscription cannot be asked what it
holds — the `claude` command has no way to list it — so a model that is not in the list can
still be typed in, and the step will simply fail loudly if the subscription has no such model.
"""

from pathlib import Path

# The jobs, in the order a run does them, with what each is for and what it costs to get wrong.
PASSES = {
    "first": {
        "label": "First reading",
        "default": "claude-haiku-4-5-20251001",
        "about": "Reads every page once: what kind of document it is, a first transcription, and "
                 "what a table was measured in. Quick and cheap, and everything it does is "
                 "checked afterwards, which is why a small model belongs here.",
    },
    "strong": {
        "label": "Expert reading",
        "default": "claude-opus-5",
        "about": "Reads again wherever a check failed, and does the work that needs judgement: "
                 "grouping the printed names of one test, finding a date inside a document, "
                 "answering a question about the archive.",
    },
    "second_reader": {
        "label": "Second opinion",
        "default": "claude-fable-5-1",
        "about": "Reads something a third time, on its own, and is compared with what is already "
                 "stored. It is not a better model than the expert one and should not be trusted "
                 "over it: it is a different one, which makes different mistakes, and that is the "
                 "whole point. Where the two agree, nothing needs a person; where they disagree, "
                 "the page is worth opening. Choose a model here that is not the expert one.",
    },
}

# Model names this program knows, newest first. Anything else can still be typed in.
KNOWN_MODELS = (
    ("claude-opus-5", "Opus 5 — the most capable, and the slowest and costliest"),
    ("claude-sonnet-5", "Sonnet 5 — between the two in both"),
    ("claude-fable-5-1", "Fable 5.1 — a different reading, useful as a second opinion"),
    ("claude-haiku-4-5-20251001", "Haiku 4.5 — the quickest and cheapest"),
)


def model_for(data_dir: Path, pass_name: str) -> str:
    """The model chosen for this pass, or the one this program ships with."""
    from epicrisis.settings import chosen_models

    default = PASSES[pass_name]["default"]
    return (chosen_models(data_dir).get(pass_name) or default).strip() or default
