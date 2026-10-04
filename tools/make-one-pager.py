"""Print the one-pagers to docs/: one for insurers, one for clinics and hospitals.

    uv run --with playwright --with pypdf --with pypdfium2 python tools/make-one-pager.py
    ... python tools/make-one-pager.py clinics     # one of them only

CHROME=<path to a chromium> if this machine already has one; Playwright's own is used otherwise.

The pages printed from are tools/one-pager*.html, which are not published: the PDF is what a person
downloads, and there is no second copy of the text to drift away from it.
"""

import hashlib
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
DOCS = HERE.parent / "docs"

# The manifest of published pictures has one writer and three callers; this script is not run as
# part of an installed package, so that writer is found by the path it sits at.
sys.path.insert(0, str(HERE))
from the_manifest import MANIFEST, CannotRead, declare  # noqa: E402

# The two files this writes are published, and the guard before a push knows both by their hash:
# the PDF among the files that are not a picture of anybody's page, the preview among the pictures.
# Printed again and not written down, they are two files nothing declares and a push that is
# refused; written down and nothing said about the versions they displace, they are two blobs in
# the history that nothing declares either. So this writes down both, and the person printing a
# sheet again has nothing to remember.
TAKEN = MANIFEST

# What each PDF was printed from, by its hash. The PDF is what a person downloads and the sheet is
# the only copy of its text, so there is no second copy to read the two against each other — and
# the one number they both carry, the size of the test suite, drifted 275 tests apart before
# anybody noticed. The five published places that carry that number are held to the suite by a
# test; the PDFs were not, because nothing in the suite can open a PDF. So the sheet is hashed
# here instead, and a sheet edited without printing again is a red test rather than a stale
# download.
PRINTED_FROM = DOCS / "printed-from.json"

# One row per sheet: the page it is printed from, the PDF a person downloads, and the picture of it
# that stands in the panel on the site. A sheet is added by adding a row, and nothing else.
SHEETS = {
    "insurance": (HERE / "one-pager.html", DOCS / "epicrisis-for-underwriting.pdf", DOCS / "images" / "one-pager.png"),
    "clinics": (HERE / "one-pager-clinics.html", DOCS / "epicrisis-for-clinics.pdf", DOCS / "images" / "one-pager-clinics.png"),
}


def main(argv: list[str]) -> int:
    wanted = argv or list(SHEETS)
    for name in wanted:
        if name not in SHEETS:
            print(f"No such sheet: {name}. There is " + " and ".join(SHEETS), file=sys.stderr)
            return 2

    from playwright.sync_api import sync_playwright

    # A Chromium that is already on the machine, if one was named; Playwright's own otherwise.
    chrome = os.environ.get("CHROME")
    with sync_playwright() as play:
        browser = play.chromium.launch(**({"executable_path": chrome} if chrome else {}))
        for name in wanted:
            page_file, pdf, _preview = SHEETS[name]
            page = browser.new_page()
            page.goto(page_file.as_uri(), wait_until="networkidle")
            page.wait_for_timeout(400)
            page.pdf(path=str(pdf), format="A4", print_background=True,
                     margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})  # fmt: skip
            page.close()
        browser.close()

    import pypdf
    import pypdfium2

    too_long = []
    for name in wanted:
        _page_file, pdf, preview = SHEETS[name]
        pages = len(pypdf.PdfReader(pdf).pages)
        pypdfium2.PdfDocument(pdf)[0].render(scale=2.2).to_pil().save(preview)
        print(f"{pdf.name}: {pages} page(s), {pdf.stat().st_size // 1024} KB; preview in {preview.name}")
        if pages != 1:  # a one-pager that runs to two pages is not a one-pager
            too_long.append(pdf.name)
    try:
        for line in write_down({name: SHEETS[name] for name in wanted}):
            print(line)
        for line in write_down_the_sheet({name: SHEETS[name] for name in wanted}):
            print(line)
    except CannotRead as why:
        print(why, file=sys.stderr)
        return 2
    if too_long:
        print("Too long: " + ", ".join(too_long), file=sys.stderr)
    return 1 if too_long else 0


def write_down(sheets: dict[str, tuple], manifest: pathlib.Path = TAKEN,
               root: pathlib.Path = DOCS.parent) -> list[str]:  # fmt: skip
    """Declare the sheets just printed, and leave the rest of the manifest alone.

    The PDF is declared by the path the repository spells it with, the preview by its bare name,
    each in the list it belongs to — which is how the guard already reads them. Only the sheets of
    this run are handed over: a sheet printed on its own used to be reason enough to rewrite the
    whole file, and the pictures of the demo pages, which no run of this script ever prints, are
    none of its business.
    """
    return declare(
        manifest,
        pictures={preview.name: preview for _page, _pdf, preview in sheets.values()},
        not_of_a_page={str(pdf.relative_to(root)): pdf for _page, pdf, _preview in sheets.values()},
    )


def write_down_the_sheet(sheets: dict[str, tuple], printed_from: pathlib.Path = PRINTED_FROM,
                         root: pathlib.Path = DOCS.parent) -> list[str]:  # fmt: skip
    """The hash of the sheet each PDF was printed from, left beside the PDFs.

    Only the sheets of this run, like the manifest beside it: printing one sheet is no reason to
    say anything about the other.
    """
    kept = json.loads(printed_from.read_text(encoding="utf-8")) if printed_from.exists() else {}
    said = []
    for page_file, pdf, _preview in sheets.values():
        key = str(pdf.relative_to(root))
        now = hashlib.sha256(page_file.read_bytes()).hexdigest()
        if kept.get(key) != now:
            said.append(f"{pdf.name} is now declared as printed from {page_file.name} as it stands")
        kept[key] = now
    printed_from.write_text(json.dumps(kept, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return said


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
