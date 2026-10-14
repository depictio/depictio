"""Depictio Project Builder: define a project's data collections from a folder.

For a folder no shipped template recognises. The user browses a data root (a
folder on the server's disk under ``depictio local``, or an ``s3://`` prefix),
picks files, and groups data collections (scan rule, type, properties) under
workflows. The result is an ad-hoc template relative to ``{DATA_ROOT}``: the
server creates the project from it through ``POST /projects/from_run``, and
``depictio ingest <dir|s3://…> --template <bundle>`` runs the same file.

Two front doors share this package:

- the main API (``projects_endpoints/builder.py``), authenticated, with the
  run-folder dialog's confinement (``LocalDataPolicy``, loopback, admin);
- ``depictio project-builder <dir>`` (``standalone.py``), a thin no-Mongo
  server for one folder that writes the template bundle into it.

Everything is asked of a :class:`~depictio.cli.cli.utils.data_root.DataRoot`,
so a local folder and an ``s3://`` prefix answer alike, and the files a data
collection is shown to match are the ones the scan itself picks
(``template_preview.scan_dc_hits``). Only ``routes.py`` and ``standalone.py``
import FastAPI: the rest runs on a CLI-only install.
"""
