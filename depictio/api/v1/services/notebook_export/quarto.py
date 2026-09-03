"""Quarto-ready notebooks: the derived ``.ipynb`` plus a front-matter cell.

Quarto renders ``.ipynb`` natively and reads its document options from a
leading *raw* cell holding YAML front matter. Adding that cell is metadata
work on the file marimo produced — the cell code path stays marimo's, so
there is still exactly one generator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

FRONT_MATTER_TAG = "depictio-quarto-front-matter"


@dataclass
class QuartoFrontMatter:
    title: str
    subtitle: str | None = None
    author: str | None = None
    date: str | None = None
    toc: bool = True
    echo: bool = False
    code_tools: bool = True
    embed_resources: bool = True
    # The tab icon, as a data URI. Quarto's own ``favicon`` option is a website
    # option and takes a path it expects to copy next to the output; a
    # single-file report has no "next to", so the icon is injected into the
    # head already inlined, like every other asset in these exports.
    favicon_data_uri: str | None = None
    # Quarto's article grid, widened. Its default body is sized for prose at
    # ~800px, and this is not prose: it carries dashboard tables of a dozen
    # columns, card rows three across and full-width figures, all of which the
    # default column makes the reader scroll sideways through. Not
    # ``page-layout: full`` — on a wide screen that stretches the narrative
    # text to an unreadable line length; a wider fixed column keeps both
    # legible. The margin grows with it so the contents stop wrapping every
    # section title onto two lines.
    body_width: str = "1100px"
    margin_width: str = "300px"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_yaml(self) -> str:
        doc: dict[str, Any] = {"title": self.title}
        if self.subtitle:
            doc["subtitle"] = self.subtitle
        if self.author:
            doc["author"] = self.author
        if self.date:
            doc["date"] = self.date
        doc["format"] = {
            "html": {
                "toc": self.toc,
                # The whole dashboard hangs off one title heading, so Quarto's
                # default (expand the active branch only) shows a contents list
                # with a single line in it until the reader scrolls. The point
                # of the contents here is to see every tab and section at once.
                "toc-expand": True,
                # Down to a section, not the headings inside a text tile: the
                # contents should mirror the dashboard's own navigation.
                "toc-depth": 4,
                # One global "View Source" affordance instead of a fold arrow
                # on every cell: the reader sees a clean report — narrative,
                # figures, cards, tables — with the code a click away rather
                # than a box between every result.
                "code-tools": self.code_tools,
                "embed-resources": self.embed_resources,
                "grid": {
                    "body-width": self.body_width,
                    "margin-width": self.margin_width,
                },
            }
        }
        if self.favicon_data_uri:
            doc["format"]["html"]["include-in-header"] = {
                "text": f'<link rel="icon" href="{self.favicon_data_uri}">'
            }
        doc["jupyter"] = "python3"
        doc["execute"] = {"warning": False, "echo": self.echo}
        doc.update(self.extra)
        return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True).strip()


def to_quarto_ipynb(ipynb_bytes: bytes, front_matter: QuartoFrontMatter) -> bytes:
    """Prepend the front-matter raw cell to an ``.ipynb``."""
    import nbformat

    nb = nbformat.reads(ipynb_bytes.decode("utf-8"), as_version=4)
    raw = nbformat.v4.new_raw_cell(f"---\n{front_matter.to_yaml()}\n---")
    raw.metadata["tags"] = [FRONT_MATTER_TAG]
    raw.metadata["format"] = "text/markdown"
    nb.cells.insert(0, raw)
    nbformat.validate(nb)
    return nbformat.writes(nb).encode("utf-8")
