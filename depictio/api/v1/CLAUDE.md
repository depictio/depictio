# Data flow, storage and auth

Loaded when working under `depictio/api/v1/`.

## Data Flow
CLI ingests data → Delta/S3/MongoDB → API serves → React viewer renders

## Data Collection Storage Families
Six types (`table`, `jbrowse2`, `multiqc`, `image`, `geojson`, `phylogeny`) with three storage shapes:
- **Delta** — `table`, `image` (manifest only), joined/transformed: Delta table at `s3://{bucket}/{dc_id}`
- **Content-addressed objects** — `multiqc`: `s3://{bucket}/{dc_id}/{sha256}/multiqc.parquet`, immutable per ingest
- **Opaque blobs** — `geojson` (fixed S3 key), `phylogeny` (bare filesystem path, never uploaded)

`metatype` is a free-form unvalidated string — never key behaviour on it.

## Auth & Storage
- JWT tokens, role-based access (users, groups, projects); single-user mode via
  `DEPICTIO_AUTH_SINGLE_USER_MODE`
- S3-compatible storage (bundled SeaweedFS `weed mini` locally, compose service `s3` with a
  `minio` network alias; any S3 endpoint in prod), Delta Lake format. Config prefix
  `DEPICTIO_S3_*` (`settings.s3`); legacy `DEPICTIO_MINIO_*` / `settings.minio` still accepted.
  Helm values key `s3:` (legacy `minio:` merged in); k8s object names keep `-minio`
- API endpoints at `/depictio/api/v1/`
