"""How a person on this machine types a command of this program.

Every page and every message that tells somebody what to run wrote `epicrisis index`, and on a
checkout — which is how this is installed, and how the instructions in the README install it —
there is no such command on the path. `epicrisis` is a console script inside the project's own
virtual environment, reachable as `uv run epicrisis`, and a person who copied the words off a page
was answered by their shell with "command not found" and had to work out for themselves what the
program meant. Advice that cannot be typed is not advice.

`uv run epicrisis` was only half of it. That form finds the project by walking up from wherever the
person is standing, so it works in the checkout and nowhere else: from a home directory, from the
folder the scans are on, from anywhere a person reads a page and opens a terminal, it is
`error: Failed to spawn: epicrisis`. Worst of all in the folder picker's refusal, where the typed
command is named as the one way to add a disk of scans that the picker will not offer — advice
given at the moment somebody has nowhere else to go. So the project is named in the command:
`uv run --project <the checkout> epicrisis …` is the same command, typeable from any folder.
`--project` does not change the working directory, so a relative path given to it still means what
the person standing there means by it.

So the spelling is decided once, here, from where the script actually is:

- Inside the virtual environment of a checkout — a `pyproject.toml` beside it — it is reachable only
  with the environment active, and `uv run --project <checkout> epicrisis` is true whether or not it
  is, and true from any folder.
- Anywhere else on the path — installed with `uv tool install`, with pipx, by a package — the plain
  name is the whole command, and prefixing it with `uv run` would be wrong.

Note that `uv run` puts the environment's bin on the path of the process it starts, so a server
started that way finds the script on its own path. That is why the question asked here is where the
script is, not whether it can be found.

The other half of a command that can be typed is which instance it acts on: `--data-dir` defaults to
a folder called `data` beside wherever the person is standing, so advice printed by one instance,
run from a different folder, acts on another — or makes one. Every command printed for a person to
copy is given the data directory of the instance printing it; `run()` takes it, and the dashboard
hands its own to every page as `data_dir`.
"""

import shlex
import shutil
import sys
from functools import cache
from pathlib import Path

NAME = "epicrisis"


@cache
def _project() -> Path | None:
    """The checkout this program runs from, if it runs from one: the folder holding pyproject.toml.

    sys.prefix is the virtual environment, and a checkout keeps it inside itself as .venv, so the
    folder above it is the project — the one `uv run --project` wants named.
    """
    project = Path(sys.prefix).resolve().parent
    return project if (project / "pyproject.toml").exists() else None


def _somewhere_else_on_the_path() -> bool:
    """Whether the command is on the path from outside this environment: installed, not checked out."""
    found = shutil.which(NAME)
    return bool(found) and Path(sys.prefix).resolve() not in Path(found).resolve().parents


@cache
def how_to_run(uv: str = "uv") -> str:
    """The words a person types to reach this program, from whatever folder they are standing in."""
    project = _project()
    if project is None or _somewhere_else_on_the_path():
        return NAME
    return f"{uv} run --project {shlex.quote(str(project))} {NAME}"


def run(rest: str = "", data_dir: Path | str | None = None) -> str:
    """One command, ready to be typed: run("index", data_dir) -> "… epicrisis index --data-dir …".

    The instance is named whenever the caller knows it. Without it the command means "the folder
    called data beside wherever you are standing", which is the instance of whoever typed it and
    not the one whose page or message gave the advice.
    """
    command = f"{how_to_run()} {rest}".strip()
    if data_dir is None:
        return command
    return f"{command} --data-dir {shlex.quote(str(Path(data_dir).expanduser().resolve()))}"


def as_root(rest: str = "", data_dir: Path | str | None = None) -> str:
    """The same command for root, written so that sudo's own path does not swallow it.

    sudo does not carry the caller's path, so neither the console script of a virtual environment
    nor `uv` itself is necessarily there; the way round it is to resolve the program where the
    caller stands and hand sudo an absolute one.
    """
    if how_to_run() == NAME:
        command = f"sudo $(which {NAME}) {rest}".strip()
    else:
        command = f"sudo {how_to_run('$(which uv)')} {rest}".strip()
    if data_dir is None:
        return command
    return f"{command} --data-dir {shlex.quote(str(Path(data_dir).expanduser().resolve()))}"


# The spelling itself, for the messages that carry it in their text. It cannot change while this
# process runs — where the program is installed is not something a run decides.
CLI = how_to_run()
