"""Word 97-2003 documents (.doc), read by converting a copy to .docx with LibreOffice.

The copy lives in a temporary directory outside the archive; the archive file is only read.
LibreOffice runs headless with a throwaway profile, so runs do not share state.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

CONVERT_TIMEOUT_SECONDS = 120


class ConversionUnavailable(Exception):
    """LibreOffice is not installed on this server."""


def soffice() -> str:
    path = shutil.which("soffice") or shutil.which("libreoffice")
    if path is None:
        raise ConversionUnavailable("LibreOffice is not installed")
    return path


def doc_to_docx(data: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="epicrisis-doc-") as workdir:
        work = Path(workdir)
        source = work / "document.doc"
        source.write_bytes(data)
        completed = subprocess.run(
            [
                soffice(), f"-env:UserInstallation=file://{work / 'profile'}", "--headless", "--norestore",
                "--convert-to", "docx", "--outdir", str(work / "out"), str(source),
            ],
            capture_output=True, timeout=CONVERT_TIMEOUT_SECONDS, check=False,
        )  # fmt: skip
        result = work / "out" / "document.docx"
        if completed.returncode != 0 or not result.exists():
            raise ValueError(f"LibreOffice could not convert the document (exit {completed.returncode})")
        return result.read_bytes()
