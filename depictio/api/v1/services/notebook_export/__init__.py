"""Dashboard → notebook export.

Turns a dashboard family plus an :class:`~depictio.models.models.analysis_state.AnalysisState`
into a marimo notebook (``.py``, canonical), from which a Jupyter ``.ipynb`` and a
Quarto-ready ``.ipynb`` are derived. Nothing here executes user code: the server
emits source, the reader runs it.

Design: ``docs/design/rfc-notebook-export.md``.
"""
