"""Background inventory runs, at most one per source.

Status lives on disk next to the results, so the dashboard survives a server restart.
"""

import json
import threading
import time
from pathlib import Path

from epicrisis import layout
from epicrisis import records
from epicrisis.inventory.run import write_inventory
from epicrisis.sources import OUTPUT_DIR_NAME, Source, source_output_dir
from epicrisis.runs import put_in_place, temporary_name

PROGRESS_INTERVAL_SECONDS = 0.5



class InventoryJobs:
    def __init__(self, data_dir: Path, background: bool = True):
        self.data_dir = data_dir
        self.background = background
        self._lock = threading.Lock()
        self._running: set[str] = set()
        self._mark_interrupted()

    def records_path(self, source_id: str) -> Path:
        return source_output_dir(self.data_dir, source_id) / layout.INVENTORY

    def status(self, source_id: str) -> dict | None:
        try:
            return json.loads(self._status_path(source_id).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def start(self, source: Source) -> bool:
        """Start an inventory unless one is already running for this source."""
        with self._lock:
            if source.id in self._running:
                return False
            self._running.add(source.id)
        started_at = records.now()
        self._write_status(source.id, {"state": "running", "scanned": 0, "total": None, "started_at": started_at})
        if self.background:
            threading.Thread(
                target=self._run, args=(source, started_at), name=f"inventory-{source.id}", daemon=True
            ).start()
        else:
            self._run(source, started_at)
        return True

    def _run(self, source: Source, started_at: str) -> None:
        last_write = 0.0

        def progress(scanned: int, total: int) -> None:
            nonlocal last_write
            now = time.monotonic()
            if scanned == total or now - last_write >= PROGRESS_INTERVAL_SECONDS:
                last_write = now
                self._write_status(
                    source.id,
                    {"state": "running", "scanned": scanned, "total": total, "started_at": started_at},
                )

        try:
            summary = write_inventory(Path(source.path), self.records_path(source.id), progress=progress)
        except Exception as exc:  # reported on the dashboard instead of killing the server
            self._write_status(
                source.id,
                {"state": "failed", "error": f"{type(exc).__name__}: {exc}", "started_at": started_at, "finished_at": records.now()},
            )
        else:
            self._write_status(
                source.id,
                {"state": "done", "scanned": summary.files + summary.skipped, "started_at": started_at, "finished_at": records.now()},
            )
        finally:
            with self._lock:
                self._running.discard(source.id)

    def _mark_interrupted(self) -> None:
        # A fresh process has no threads, so any "running" status is left over from a crash or restart.
        for status_path in (self.data_dir / OUTPUT_DIR_NAME).glob("*/inventory.status.json"):
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # A status file torn by the crash it is evidence of. It says nothing; the
                # dashboard starting is worth more than the line it would have said.
                continue
            if status.get("state") == "running":
                self._write_status(status_path.parent.name, {**status, "state": "interrupted"})

    def _status_path(self, source_id: str) -> Path:
        return source_output_dir(self.data_dir, source_id) / layout.INVENTORY_STATUS

    def _write_status(self, source_id: str, status: dict) -> None:
        path = self._status_path(source_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = temporary_name(path)
        temporary.write_text(json.dumps(status), encoding="utf-8")
        put_in_place(temporary, path)
