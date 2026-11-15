"""Dashboard → notebook export.

Turns a dashboard family plus an :class:`~depictio.models.models.analysis_state.AnalysisState`
into one Quarto document (``.qmd``). Nothing here executes user code: the server
emits source, the reader runs it — or, behind a flag, a worker renders it into an
HTML report (``render.py``).

Design: ``docs/design/rfc-notebook-export.md``.
"""
