"""Print the one-pager for organisations to docs/epicrisis-for-underwriting.pdf.

    uv run --with playwright --with pypdf --with pypdfium2 python tools/make-one-pager.py

CHROME=<path to a chromium> if this machine already has one; Playwright's own is used otherwise.

The page it prints from is tools/one-pager.html, which is not published: the PDF is what a person
downloads, and there is no second copy of the text to drift away from it.
"""

import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
PAGE = HERE / "one-pager.html"
PDF = HERE.parent / "docs" / "epicrisis-for-underwriting.pdf"
PREVIEW = HERE.parent / "docs" / "images" / "one-pager.png"


def main() -> int:
    from playwright.sync_api import sync_playwright

    # A Chromium that is already on the machine, if one was named; Playwright's own otherwise.
    chrome = os.environ.get("CHROME")
    with sync_playwright() as play:
        browser = play.chromium.launch(**({"executable_path": chrome} if chrome else {}))
        page = browser.new_page()
        page.goto(PAGE.as_uri(), wait_until="networkidle")
        page.wait_for_timeout(400)
        page.pdf(path=str(PDF), format="A4", print_background=True,
                 margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})  # fmt: skip
        browser.close()

    import pypdf
    import pypdfium2

    pages = len(pypdf.PdfReader(PDF).pages)
    pypdfium2.PdfDocument(PDF)[0].render(scale=2.2).to_pil().save(PREVIEW)
    print(f"{PDF.name}: {pages} page(s), {PDF.stat().st_size // 1024} KB; preview in {PREVIEW.name}")
    return 0 if pages == 1 else 1  # a one-pager that runs to two pages is not a one-pager


if __name__ == "__main__":
    raise SystemExit(main())
