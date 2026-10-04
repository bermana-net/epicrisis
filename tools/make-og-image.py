"""Print the picture a shared link shows to docs/og.png.

    uv run --with playwright python tools/make-og-image.py

CHROME=<path to a chromium> if this machine already has one; Playwright's own is used otherwise.

1200×630 is what the services that unfurl a link ask for, and what they crop towards: the words of
the page sit in the middle third so that a square crop keeps them. The page it is printed from is
tools/og-image.html, which is not published — the picture is, and there is no second copy of the
words to drift away from it.
"""

import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
PAGE = HERE / "og-image.html"
PICTURE = HERE.parent / "docs" / "og.png"
SIZE = {"width": 1200, "height": 630}

# The manifest of published pictures has one writer and three callers; this script is not run as
# part of an installed package, so that writer is found by the path it sits at.
sys.path.insert(0, str(HERE))
from the_manifest import MANIFEST, CannotRead, declare  # noqa: E402


def main() -> int:
    from playwright.sync_api import sync_playwright

    chrome = os.environ.get("CHROME")
    with sync_playwright() as play:
        browser = play.chromium.launch(**({"executable_path": chrome} if chrome else {}))
        page = browser.new_page(viewport=SIZE, device_scale_factor=1)
        page.goto(PAGE.as_uri(), wait_until="networkidle")
        page.wait_for_timeout(300)
        page.screenshot(path=str(PICTURE))
        browser.close()

    # Declared where every other published picture is, and for the same reason: the guard refuses
    # anything it cannot account for, and a picture nobody declared is how a page of somebody's
    # archive would get out. This one is of nobody — it is drawn — and it says so by being here.
    # One picture is handed over and nothing else: this script used to write the whole file, which
    # is how three writers came to reformat and cross out one another's lines.
    try:
        for line in write_down():
            print(line)
    except CannotRead as why:
        print(why, file=sys.stderr)
        return 2

    print(f"{PICTURE.name}: {SIZE['width']}×{SIZE['height']}, {PICTURE.stat().st_size // 1024} KB; hash written into the manifest")
    return 0


def write_down(picture: pathlib.Path = PICTURE, manifest: pathlib.Path = MANIFEST) -> list[str]:
    """Declare the picture a shared link shows, under the path the repository spells it with."""
    return declare(manifest, not_of_a_page={f"docs/{picture.name}": picture})


if __name__ == "__main__":
    raise SystemExit(main())
