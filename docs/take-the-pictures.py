"""Take the picture set of a demo instance, cut where no line of text is cut.

    uv run epicrisis demo --into /tmp/demo
    uv run epicrisis serve --data-dir /tmp/demo/data --port 8060 &
    uv run --with playwright python docs/take-the-pictures.py --data-dir /tmp/demo/data --out docs/images

Nothing here reads the demo until it is asked to: the documents to photograph are found through
the program's own index rather than by their hashes, which change with every seed and every
change to how a page is drawn, and every shot is checked for having rendered what it asked for.
A picture of a 404 that reports success is worse than no picture.
"""

import argparse
import pathlib
import sys
from contextlib import closing

REVIEW_STATE = ("open",)


def find_documents(data_dir: pathlib.Path) -> dict:
    """One card of each language to photograph, and the sources they belong to."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from epicrisis.query import open_index
    from epicrisis.sources import SourceRegistry

    registry = SourceRegistry(data_dir)
    sources = {source.whose: source for source in registry.list()}
    cards: dict[str, tuple[str, str, int]] = {}
    for source in registry.list():
        with closing(open_index(data_dir, source.id)) as connection:
            for language in ("en", "es", "ru", "el"):
                if language in cards:
                    continue
                row = connection.execute(
                    """SELECT source_id, file_sha256, first_page FROM documents
                       WHERE language = ? AND doc_type = 'lab_panel' AND primary_copy = 1
                       ORDER BY (SELECT count(*) FROM observations o WHERE o.document_id = documents.id) DESC
                       LIMIT 1""",
                    (language,),
                ).fetchone()
                if row:
                    cards[language] = (source.whose, row["source_id"], row["file_sha256"], row["first_page"])
            words = connection.execute(
                """SELECT source_id, file_sha256, first_page FROM documents
                   WHERE doc_type = 'consultation' AND language = 'en' ORDER BY date DESC LIMIT 1"""
            ).fetchone()
            if words and "words" not in cards:
                cards["words"] = (source.whose, words["source_id"], words["file_sha256"], words["first_page"])
    return {"sources": sources, "cards": cards}


def shots(found: dict) -> list[tuple]:
    """(name, whose archive, path, how tall at most, what to do first)."""
    whose = list(found["sources"])
    first = whose[0]
    father = whose[1] if len(whose) > 1 else first
    grandmother = whose[2] if len(whose) > 2 else first
    cards = found["cards"]

    def card(language: str) -> tuple[str, str] | None:
        """(whose archive it is in, the address of the card). A card answers for its own archive
        only, so the shot has to be taken while that archive is the one open."""
        found_card = cards.get(language)
        if not found_card:
            return None
        whose_card, source_id, sha256, page = found_card
        return (whose_card, f"/documents/{source_id}/{sha256}/{page}")

    scan = cards.get("en") or next(iter(cards.values()), None)
    return [
        ("01-timeline", first, "/", 1000, None),
        ("02-lanes", first, "/?view=lanes", 1000, None),
        ("03-by-test", first, "/?view=indicators", 1100, None),
        ("04-hba1c", father, "/tests/hba1c", 1000, None),
        ("05-creatinine", first, "/tests/creatinine", 1620, None),
        ("06-ferritin", first, "/tests/ferritin", 1000, None),
        ("07-vitamin-d", first, "/tests/vitamin-d", 1000, None),
        ("08-urine-protein", first, "/tests/protein", 1000, None),
        ("09-documents", first, "/documents", 980, None),
        ("10-card-en", *(card("en") or (first, None)), 1450, None),
        ("11-card-es", *(card("es") or (first, None)), 1450, None),
        ("12-card-ru", *(card("ru") or (father, None)), 1450, None),
        ("13-card-el", *(card("el") or (grandmother, None)), 1450, None),
        ("14-scan", scan[0] if scan else first,
         f"/sources/{scan[1]}/files/{scan[2]}/pages/{scan[3]}" if scan else None, 1000, None),
        ("15-search", first, "/search?q=cholesterol", 980, None),
        ("16-search-ru", father, "/search?q=глюкоза", 980, None),
        ("17-indicators", first, "/indicators", 1050, None),
        ("18-review", father, "/review", 1300, "open"),
        ("19-status", father, "/status", 1200, None),
        ("20-settings", first, "/settings", 1200, None),
        ("21-ask", first, "/ask", 900, None),
        ("22-card-words", *(card("words") or (father, None)), 1250, None),
    ]


# Where a cut may fall: a gap between blocks, never through a line of text.
CLEAN_CUT = """(wanted) => {
  const boxes = [...document.body.querySelectorAll('*')].map(n => {
    const r = n.getBoundingClientRect();
    return {top: r.top + scrollY, bottom: r.bottom + scrollY, h: r.height, w: r.width,
            leaf: n.children.length === 0 && (n.textContent || '').trim().length > 0};
  }).filter(b => b.h > 0 && b.w > 0);
  const page = Math.ceil(Math.max(...boxes.map(b => b.bottom), 0)) + 24;
  const top = Math.min(wanted, page);
  const splits = c => boxes.some(b => b.leaf && b.top + 1 < c && b.bottom - 1 > c);
  if (!splits(top)) return top;
  const marks = new Set([top]);
  for (const b of boxes) {
    if (b.leaf) { marks.add(Math.floor(b.top) - 8); marks.add(Math.ceil(b.bottom) + 8); }
  }
  const tried = [...marks].filter(c => c <= top && c >= 400).sort((a, b) => b - a);
  for (const c of tried) if (!splits(c)) return c;
  return top;
}"""


def take(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=pathlib.Path, default=pathlib.Path("/tmp/demo/data"))
    parser.add_argument("--base", default="http://127.0.0.1:8060", help="Where that data dir is being served")
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("docs/images"))
    parser.add_argument("--chrome", default=None, help="A Chromium for Playwright; its own by default")
    args = parser.parse_args(argv)

    from playwright.sync_api import sync_playwright

    found = find_documents(args.data_dir)
    if not found["sources"]:
        print(f"No archive in {args.data_dir}. Build one: epicrisis demo --into {args.data_dir.parent}", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    missed = []

    with sync_playwright() as play:
        browser = play.chromium.launch(**({"executable_path": args.chrome} if args.chrome else {}))
        context = browser.new_context(viewport={"width": 1340, "height": 950}, device_scale_factor=2)
        page = context.new_page()
        showing = None
        for name, whose, path, height, doing in shots(found):
            if path is None:
                missed.append(f"{name}: this archive has no such document")
                continue
            if whose != showing:
                page.request.post(args.base + "/owner", form={"source": found["sources"][whose].id, "back": "/"})
                showing = whose
            page.set_viewport_size({"width": 1340, "height": height})
            answer = page.goto(args.base + path, wait_until="networkidle")
            if answer is None or answer.status >= 400:
                missed.append(f"{name}: {path} answered {answer.status if answer else 'nothing'}")
                continue
            if doing in REVIEW_STATE:
                page.eval_on_selector_all("details", "nodes => nodes.forEach(n => n.open = true)")
            page.wait_for_timeout(350)
            cut = height if "/pages/" in path else page.evaluate(CLEAN_CUT, height)
            page.screenshot(path=str(args.out / f"{name}.png"), clip={"x": 0, "y": 0, "width": 1340, "height": cut})
            print(f"{name}: {cut}px · {page.title()}")
        browser.close()

    for line in missed:
        print(f"not taken — {line}", file=sys.stderr)
    return 1 if missed else 0


if __name__ == "__main__":
    raise SystemExit(take())
