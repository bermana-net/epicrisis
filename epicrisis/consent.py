"""One-time confirmation that pages may be sent to a model provider, kept in data/consent.json.

A new CONSENT_VERSION asks again, so changing what the notice says requires a fresh confirmation.
"""

import json
from epicrisis.runs import put_in_place, temporary_name
from datetime import UTC, datetime
from pathlib import Path

CONSENT_VERSION = 2


def _path(data_dir: Path) -> Path:
    return data_dir / "consent.json"


def has_consent(data_dir: Path, backend: str) -> bool:
    try:
        entries = json.loads(_path(data_dir).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    entry = entries.get(backend)
    return bool(entry) and entry.get("version") == CONSENT_VERSION


def record_consent(data_dir: Path, backend: str) -> None:
    path = _path(data_dir)
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    entries[backend] = {"version": CONSENT_VERSION, "accepted_at": datetime.now(UTC).isoformat(timespec="seconds")}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = temporary_name(path)
    temporary.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    put_in_place(temporary, path)
