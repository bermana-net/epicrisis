"""Several model calls at once for classify and extract.

Each item runs in a worker thread; a model call is a subprocess, so threads are enough. An item
returning False (the usage limit) stops the run: items not started are skipped, running ones
finish and are recorded. Writes and counters go through STATE_LOCK.
"""

import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor

DEFAULT_WORKERS = 3
STATE_LOCK = threading.RLock()


def run_parallel(items: Iterable, work: Callable[[object], bool], workers: int = DEFAULT_WORKERS) -> None:
    stop = threading.Event()

    def run(item) -> None:
        if not stop.is_set() and not work(item):
            stop.set()

    executor = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="epicrisis-call")
    try:
        futures = [executor.submit(run, item) for item in items]
        for future in futures:
            future.result()
    except BaseException:
        stop.set()
        raise
    finally:
        # Running calls finish and are recorded before the run's lock file goes away.
        executor.shutdown(wait=True, cancel_futures=True)
