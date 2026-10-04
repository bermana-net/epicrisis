# The project page

`index.html` is the page shown at the repository's website: the story, a carousel of every screen,
and the security notes. It is one file with no dependencies, and it reads its pictures from
`images/`, which are taken from the built-in demo and from nothing else.

To look at it locally:

```sh
python3 -m http.server 8061 --bind 127.0.0.1 --directory docs
```

## Taking the pictures again

After the interface changes, build a demo, serve it, and let the shot script walk it. The script
finds the documents to photograph through the program's own index, so nothing in it has to be
edited when the demo changes, and it reports anything it could not take rather than quietly
photographing a page that is not there.

```sh
uv run epicrisis demo --into /tmp/demo
uv run epicrisis serve --data-dir /tmp/demo/data --port 8060 &
uv run --with playwright python docs/take-the-pictures.py \
    --data-dir /tmp/demo/data --base http://127.0.0.1:8060 --out docs/images
```

Playwright brings its own browser: `uv run --with playwright playwright install chromium` once,
or point `--chrome` at one that is already on the machine.

`images/taken-from-the-demo.json` declares every picture and PDF this project publishes, by hash,
and `tools/nothing-of-yours.py` refuses to publish anything that is not in it. Three scripts print
such files — this one, `tools/make-one-pager.py` and `tools/make-og-image.py` — and all three write
that manifest through `tools/the_manifest.py`, which only ever adds: a run declares what it printed
and leaves every other entry alone, and a hash it displaces or a picture that leaves the tree is
kept under `earlier`, because the bytes stay in the history and cannot be unpublished.
