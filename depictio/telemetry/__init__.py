"""Anonymous, opt-out telemetry shared by the Depictio API and the Depictio CLI.

Depictio ships as a Docker Compose stack, a Helm chart, a PyPI package and a
static web app. None of those distribution channels report anything back: GHCR
publishes no pull counts for either the images or the OCI chart, so without this
package the project has no way to know how many installations exist or which
features are used.

What this package is *not*: the ``depictio.api.v1.services.analytics_service``
subsystem, which records per-user sessions into each deployment's own MongoDB and
never transmits anything. That one answers "who used my instance". This one
answers "how many Depictio instances exist", and only ever sends anonymous,
aggregate, bucketed data to the project maintainers.

Layout — this package holds only what both the API *and* the CLI need, because
the CLI wheel ships an explicit package list (``depictio/cli/pyproject.toml``)
that does not include ``depictio.api.v1.*`` beyond ``configs``. Server-only
pieces (the MongoDB-backed instance identity, aggregate counts, the lifespan
hook) live in ``depictio.api.v1.telemetry`` instead.

Two invariants hold everywhere in here:

1. **Telemetry can never break, block or slow the thing it measures.** Every
   send path swallows every exception and runs under a hard timeout, mirroring
   the guarantee ``AnalyticsMiddleware`` already makes for inbound analytics.
2. **Nothing identifying is ever collected.** See ``schema.py`` for the exact
   payloads and ``docs/telemetry.md`` for the operator-facing description.

This ``__init__`` intentionally re-exports nothing. ``settings_models.py`` reads
the default endpoint from ``depictio.telemetry.constants``, and it is imported
earlier than anything else in every context — so re-exporting from here would drag
``httpx`` and pydantic into the config import chain for no benefit. Import from
the submodules directly, as the rest of the codebase does.
"""
