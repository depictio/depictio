"""Server-side half of Depictio's anonymous installation telemetry.

Everything here needs MongoDB or the API settings, so it stays out of
:mod:`depictio.telemetry` — that package is shipped in the lean ``depictio-cli``
wheel, which has no server dependencies.

Module map:

* :mod:`.identity` — the persistent anonymous installation ID.
* :mod:`.guard` — makes "at most one send per install per day" true across
  gunicorn workers and Kubernetes replicas.
* :mod:`.payload` — builds the heartbeat from settings and aggregate counts.
* :mod:`.tasks` — the periodic loop and its lifespan entry point.
"""
