"""Admin "Log & Task" monitoring subsystem.

Durable MongoDB ledger for Celery task lifecycle, CLI ingestion runs, and recent
application logs, plus the worker-side Celery signal handlers and logging handler
that populate it. Surfaced to admins via ``monitoring_endpoints`` and the
``AdminMonitoringPanel`` React view.
"""
