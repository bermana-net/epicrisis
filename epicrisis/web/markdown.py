"""Model answers rendered as markdown: tables read as tables, and no raw HTML gets through.

The renderer never passes HTML written in the text: it escapes it, so an answer cannot bring
markup of its own into the page.
"""

from markdown_it import MarkdownIt
from markupsafe import Markup

_RENDERER = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False}).enable("table").enable("strikethrough")


def render_markdown(text: str | None) -> Markup:
    return Markup(_RENDERER.render(text or ""))
