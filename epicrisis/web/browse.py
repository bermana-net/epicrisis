"""Folder listing for the "add folder" dialog. Lists folders only; file names are never sent."""

import os
from pathlib import Path

MAX_FOLDERS = 1000


class BrowseError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def list_folder(raw_path: str, added_paths: set[str], roots: list[Path] | None = None) -> dict:
    """One folder's subfolders, for choosing an archive. Never above the roots it is given."""
    target = Path(raw_path).expanduser()
    if not target.is_absolute():
        raise BrowseError("Use an absolute path, starting with /.", 400)
    target = target.resolve()
    if not target.is_dir():
        raise BrowseError("No such folder on this server.", 404)
    if roots and not any(target.is_relative_to(root) for root in roots):
        raise BrowseError("Folders are chosen from " + " or ".join(str(root) for root in roots) + ".", 403)

    folders, file_count = [], 0
    try:
        with os.scandir(target) as entries:
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir():
                        folders.append(entry)
                    elif entry.is_file():
                        file_count += 1
                except OSError:
                    continue
    except PermissionError as exc:
        raise BrowseError("The server cannot read this folder.", 403) from exc

    folders.sort(key=lambda entry: entry.name.casefold())
    return {
        "path": str(target),
        "parent": str(target.parent) if target.parent != target else None,
        "crumbs": [{"name": part, "path": str(Path(*target.parts[: index + 1]))} for index, part in enumerate(target.parts)],
        "folders": [
            {"name": entry.name, "path": entry.path, "added": entry.path in added_paths}
            for entry in folders[:MAX_FOLDERS]
        ],
        "truncated": len(folders) > MAX_FOLDERS,
        "folder_count": len(folders),
        "file_count": file_count,
    }
