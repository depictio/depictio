"""Depictio performance benchmark harness.

A self-contained, config-driven harness that generates synthetic datasets +
matching project/dashboard configs across a matrix of dimensions, runs the
matrix against a live Depictio stack (ingest -> trigger renders), and reports
the collected timings.

The four dimensions the user cares about:

- number of components in a tab
- number of data collections used in parallel & connected (joins / links)
- size per data collection (10MB ... 10GB)
- visualization type (figure, table, advanced_viz)
- Celery offload on vs off

Nothing large is committed: datasets live under ``benchmark/output/`` (gitignored)
and are generated live before a run. See ``benchmark/README.md``.
"""

__all__ = ["matrix", "datagen", "configgen", "runner", "metrics", "report"]
