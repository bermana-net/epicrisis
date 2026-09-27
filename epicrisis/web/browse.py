"""Folder listing for the "add folder" dialog. Lists folders only; file names are never sent."""

import os
from pathlib import Path
from epicrisis.sources import ARCHIVE_ROOT_VARIABLE, belongs_to_the_server
from epicrisis.invocation import run

MAX_FOLDERS = 1000


class BrowseError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def list_folder(raw_path: str, added_paths: set[str], roots: list[Path] | None = None,
                data_dir: Path | None = None) -> dict:  # fmt: skip
    """One folder's subfolders, for choosing an archive. Never above the roots it is given.

    No roots is no folder, and not every folder: the check used to stand behind `if roots and …`,
    so an empty list turned it off altogether and this listed the subfolders and the file counts of
    any folder on the server that was asked for. An empty list is not a strange state. roots() drops
    the folders that belong to the server, and for an instance run as root with its data under
    /var/lib, /opt or /srv — the arrangement an organisation installs, and the one the site now
    invites — the home folder and both folders above the data folder are all three of them the
    server's own, so nothing is left. What went out of the door then was the directory tree of the
    machine, and folder names in this program are surnames and sometimes diagnoses.

    data_dir is the instance this picker belongs to, and it is in the refusals below rather than
    left to a default: that line is typed in a shell standing anywhere, where --data-dir means a
    folder called "data" beside the person, which is some other instance or none at all.
    """
    target = Path(raw_path).expanduser()
    if not target.is_absolute():
        raise BrowseError("Use an absolute path, starting with /.", 400)
    target = target.resolve()
    if not target.is_dir():
        raise BrowseError("No such folder on this server.", 404)
    if not any(target.is_relative_to(root) for root in roots or []):
        # And the ways out, named — the one that works now first. Scans of thirty years of paper
        # live on a disk of their own more often than not. A refusal that listed two folders and
        # stopped left copying tens of gigabytes into the home folder as the only idea, which is the
        # one thing this program promises not to do to somebody's archive; naming only the
        # environment variable was barely better, since it means stopping the server.
        #
        # The folder in that line is the one a person means to add, and this dialog is opened at a
        # folder the server chose: run as root it opens at /root, which is a folder of the server's
        # own and refused however it is offered. So the line said `sources add "/root"` — advice to
        # add, as somebody's medical archive, the home folder of the account the server runs as,
        # which they had not chosen and which nothing would accept. A folder that could never be an
        # archive is never named as one to type; the shape of the line is, so it can still be copied.
        typeable = "<the folder of documents>" if belongs_to_the_server(target) else str(target)
        by_typing_it = run(f'sources add "{typeable}" --owner "<whose records these are>"', data_dir)
        if not roots:
            raise BrowseError(
                "This picker has no folder it can show on this server: the places it would offer — "
                "the home of the account this server runs as, and the folders around the data folder "
                "of this instance — all belong to the server itself, and an archive is never added "
                f"from one. Type the folder out instead: {by_typing_it}. Nothing is copied that way: "
                f"an archive is only read. To have this picker offer a folder, set "
                f"{ARCHIVE_ROOT_VARIABLE} to it before starting this server; several folders are "
                f'separated by "{os.pathsep}".',
                403,
            )  # fmt: skip
        raise BrowseError(
            "Folders are chosen from " + " or ".join(str(root) for root in roots)
            + f', and this one is not inside any of them, so nothing under it is shown. A folder '
              f'anywhere else — a disk with the scans of thirty years on it — is added '
              f'by typing it: {by_typing_it}. '
              f"Nothing is copied any of these ways: an archive is only read. To have this picker "
              f"offer that disk as well, set {ARCHIVE_ROOT_VARIABLE} to it before starting this "
              f'server; several folders are separated by "{os.pathsep}".',
            403,
        )  # fmt: skip

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
