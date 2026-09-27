"""Read every shape in tests/printed-shapes.json with one tree's readers, and print what it made of them.

For the rule this project works by: a fix assumes it breaks something and has to prove it did not.
Run this against the tree before a change and against the tree after, diff the two, and every
shape that moved is named — including the ones this archive does not hold, which is exactly where
the readers kept breaking while every other measurement reported nothing.

    git worktree add /tmp/before <commit>
    python tools/reader-shapes.py /tmp/before > /tmp/before.txt
    python tools/reader-shapes.py .          > /tmp/after.txt
    diff /tmp/before.txt /tmp/after.txt

The tree is given as an argument rather than imported from here, because the point is to run two
of them. Nothing is written and nothing but this repository's own files is read.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def readings(tree: Path) -> list[str]:
    sys.path.insert(0, str(tree))
    for module in [name for name in sys.modules if name.startswith("epicrisis")]:
        del sys.modules[module]
    from epicrisis.dates import read_printed_date
    from epicrisis.reference import parse
    from epicrisis.units import unit_from_reference, unit_key

    shapes = json.loads((HERE / "tests" / "printed-shapes.json").read_text(encoding="utf-8"))
    how = {
        "ranges": parse,
        "units_named_inside_a_range": unit_from_reference,
        "unit_keys": unit_key,
        "dates": lambda text: getattr(read_printed_date(text).value, "isoformat", lambda: None)(),
    }
    lines = []
    for section, read in how.items():
        for shape in shapes[section]:
            try:
                got = read(shape["text"])
            except Exception as trouble:  # a reader that raises is itself the answer
                got = f"raised {type(trouble).__name__}"
            wanted = tuple(shape["expect"]) if section == "ranges" and shape["expect"] is not None else shape["expect"]
            agrees = "  " if got == wanted else "!!"
            lines.append(f"{agrees} {section:26s} {shape['text']!r:58s} -> {got}")
    sys.path.remove(str(tree))
    return lines


def main() -> int:
    tree = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    if not (tree / "epicrisis" / "reference.py").exists():
        print(f"{tree} is not a tree of this program: it holds no epicrisis/reference.py", file=sys.stderr)
        return 2
    lines = readings(tree)
    print("\n".join(lines))
    wrong = sum(1 for line in lines if line.startswith("!!"))
    print(f"\n{len(lines)} shapes, {wrong} read otherwise than the form meant, from {tree}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
