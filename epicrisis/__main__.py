"""`python -m epicrisis`, the same entry point as the installed command.

It called app() directly, which is the one thing this must not do: every answer that run() gives
to trouble a person can act on — a file of state that will not parse, a lock left by a run that
died, a disk with no room left — was missing here, and the same command that said one sentence
when installed said thirty-five lines of traceback when run this way.
"""

from epicrisis.cli import run

run()
