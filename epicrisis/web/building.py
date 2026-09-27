"""Building one archive's index in again, shortly after a person changes something in it.

A correction is written into this archive's own file the moment it is saved, and the card of the
document shows it at once, because a card is drawn from those files. The chart, the search, the
timeline and the tools over the network all answer from the index, which is *built* from them. So
a number a person put right in order to show a doctor the chart was right on its card and wrong on
the chart, for as long as nobody happened to run `epicrisis index` by hand. Nothing said so, and
there was no button on any page that would do it.

The build reads only files already on this machine: no model, nothing sent anywhere, seconds. It
is still far too long to hold a form's answer on — somebody working down a table of thirty rows
saves them one after another — so it happens behind the page, once the saving stops, and every
page says so while it has not happened yet.
"""

import threading
import time
from pathlib import Path

from epicrisis.runs import Busy
from epicrisis.sources import SourceRegistry
from epicrisis.invocation import CLI

# How long the saving has to have stopped before the index is built again. A person putting a table
# right saves one line, then the next; a build for each is the same work over and over, and only
# the last of them would be the one a person sees.
QUIET_SECONDS = 1.5
# A build already under way holds the index's own lock — the settings page, a command in a
# terminal, or this same button pressed twice. It is over in seconds, so this waits for it instead
# of giving up: giving up would leave the change out of the index with nothing on its way to put
# it in, which is the very thing this file exists to stop.
WAIT_FOR_THE_LOCK_SECONDS = 2.0
TIMES_TO_WAIT = 30


class Building:
    """At most one build per archive at a time, and at most one waiting behind it."""

    def __init__(self, data_dir: Path, registry: SourceRegistry, background: bool = True):
        self.data_dir = data_dir
        self.registry = registry
        self.background = background
        self._lock = threading.Lock()
        self._asked: dict[str, float] = {}
        self._running: set[str] = set()
        self._trouble: dict[str, str] = {}

    def after_a_change(self, source_id: str) -> None:
        """Something the index is built from has just been written for this archive."""
        with self._lock:
            self._asked[source_id] = time.monotonic()
            if source_id in self._running:
                # The one already at work will see the newer moment and go round again, so a
                # correction saved during a build is not the one left out.
                return
            self._running.add(source_id)
        if self.background:
            threading.Thread(
                target=self._work, args=(source_id,), name=f"index-{source_id}", daemon=True
            ).start()
        else:
            self._work(source_id)

    def state(self, source_id: str) -> dict:
        """Whether this archive's index is being built now, and what stopped the last attempt."""
        with self._lock:
            return {"building": source_id in self._running, "trouble": self._trouble.get(source_id, "")}

    def now(self, source_id: str) -> str:
        """Build it again with a person waiting on the answer. A sentence if it could not be.

        Nothing is said when one is already running: the page a person comes back to says that
        itself, and it is the same build they asked for.
        """
        with self._lock:
            if source_id in self._running:
                return ""
            self._running.add(source_id)
            self._asked.pop(source_id, None)
        try:
            trouble, _busy = self._once(source_id)
        finally:
            with self._lock:
                self._running.discard(source_id)
        return trouble

    def _work(self, source_id: str) -> None:
        try:
            while True:
                while self.background:
                    with self._lock:
                        quiet = time.monotonic() - self._asked.get(source_id, 0.0)
                    if quiet >= QUIET_SECONDS:
                        break
                    time.sleep(QUIET_SECONDS - quiet)
                began = time.monotonic()
                for _ in range(TIMES_TO_WAIT):
                    _trouble, busy = self._once(source_id)
                    if not busy or not self.background:
                        break
                    time.sleep(WAIT_FOR_THE_LOCK_SECONDS)
                with self._lock:
                    # A change saved while that build was running is not in the file it wrote.
                    if self._asked.get(source_id, 0.0) < began:
                        return
        finally:
            with self._lock:
                self._running.discard(source_id)

    def _once(self, source_id: str) -> tuple[str, bool]:
        """One attempt: the sentence for a failure, and whether it was only the lock."""
        from epicrisis.index.build import build_index

        source = next((one for one in self.registry.list() if one.id == source_id), None)
        if source is None:
            return "", False
        try:
            build_index(self.data_dir, [source])
        except Busy:
            return "", True
        except Exception as problem:  # noqa: BLE001 - whatever went wrong, the pages must say so
            # The kind of failure and nothing else. This sentence is shown on every page of this
            # archive, and an exception's own words can quote a path or a value from it.
            said = (f"What was changed could not be built in: {type(problem).__name__}. Nothing is "
                    f"lost — every correction is in this archive's own file. Run '{CLI} index' "
                    "in a terminal to see why.")
            with self._lock:
                self._trouble[source_id] = said
            return said, False
        with self._lock:
            self._trouble.pop(source_id, None)
        return "", False
