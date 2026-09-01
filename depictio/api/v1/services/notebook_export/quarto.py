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
    code_fold: bool = True
    embed_resources: bool = True
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
                "code-fold": self.code_fold,
                "embed-resources": self.embed_resources,
            }
        }
        doc["jupyter"] = "python3"
        doc["execute"] = {"warning": False}
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
