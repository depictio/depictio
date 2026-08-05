"""Serverless (backend-less) bundle producers.

Phase 1 of ``docs/design/rfc-serverless-deployment.md``: producer B builds a
static dashboard bundle from a YAML/JSON spec plus local Parquet files, with no
running Depictio instance. The contract layer (``BundleManifest``) lives in
``depictio.models.models.serverless``; the consuming runtime is
``depictio/viewer/src/static-runtime/`` + ``packages/depictio-static-core``.
"""
