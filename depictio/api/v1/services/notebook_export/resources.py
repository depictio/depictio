"""The report's own stylesheets, scripts and typst, kept as files in ``assets/``.

Read once per process (``asset``) and wrapped in the tag the page needs
(``style``, ``script``). Shipped as package data (``pyproject.toml``): the
wheel carries them beside this module.
"""

from __future__ import annotations

from functools import cache
from importlib.resources import files


@cache
def asset(name: str) -> str:
    """``assets/<name>``, exactly as written."""
    return files(__package__).joinpath("assets", name).read_text(encoding="utf-8")


def style(name: str) -> str:
    return f"<style>{asset(name)}</style>"


def script(name: str) -> str:
    return f"<script>{asset(name)}</script>"
