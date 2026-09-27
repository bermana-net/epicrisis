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
# The two files this writes are published, and the guard before a push knows both by their hash:
# the PDF among the files that are not a picture of anybody's page, the preview among the pictures.
# Printed again and not written down, they are two files nothing declares and a push that is
# refused; written down and nothing said about the versions they displace, they are two blobs in
# the history that nothing declares either. So this writes down both, and the person printing a
# sheet again has nothing to remember.
TAKEN = DOCS / "images" / "taken-from-the-demo.json"

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

    too_long, printed = [], {}
    for name in wanted:
        _page_file, pdf, preview = SHEETS[name]
        pages = len(pypdf.PdfReader(pdf).pages)
        pypdfium2.PdfDocument(pdf)[0].render(scale=2.2).to_pil().save(preview)
        print(f"{pdf.name}: {pages} page(s), {pdf.stat().st_size // 1024} KB; preview in {preview.name}")
        printed[str(pdf.relative_to(DOCS.parent))] = hashlib.sha256(pdf.read_bytes()).hexdigest()
        printed[preview.name] = hashlib.sha256(preview.read_bytes()).hexdigest()
        if pages != 1:  # a one-pager that runs to two pages is not a one-pager
            too_long.append(pdf.name)
    write_down(printed)
    if too_long:
        print("Too long: " + ", ".join(too_long), file=sys.stderr)
    return 1 if too_long else 0


def write_down(printed: dict[str, str]) -> None:
    """Put what was just printed into the manifest the guard reads, and keep what it displaces.

    The PDF is declared by the path the repository spells it with, the preview by its bare name,
    each in the list it belongs to — which is how the guard already reads them. A hash that changes
    is not lost: it goes under "earlier", because the version it replaces stays in the history and
    is published to everybody who clones this, and a version nothing declares is refused.
    """
    if not TAKEN.exists():
        print(f"No {TAKEN}: the hashes of what was printed are written nowhere.", file=sys.stderr)
        return
    manifest = json.loads(TAKEN.read_text(encoding="utf-8"))
    earlier = manifest.setdefault("earlier", {})
    for name, hashed in printed.items():
        where = "not_of_a_page" if name.endswith(".pdf") else "pictures"
        was = manifest.setdefault(where, {}).get(name)
        if was and was != hashed and was not in earlier.get(name, []):
            earlier.setdefault(name, []).append(was)
        manifest[where][name] = hashed
    TAKEN.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(printed)} hashes written into {TAKEN.relative_to(DOCS.parent)}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
