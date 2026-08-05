# RFC — Remote data sources & manifest-driven projects

**Status:** Draft / design only (no code).
**Audience:** maintainers.
**Related:** `depictio/models/models/data_collections.py`,
`depictio/api/v1/endpoints/datacollections_endpoints/utils.py` (`_create_dc_from_upload`,
the zero-CLI ingestion precedent), `depictio/cli/cli/utils/templates.py`,
`depictio/models/models/links.py`, `.github/ROADMAP_ISSUES_DRAFT.md` (epic 1.5.0),
`docs/design/rfc-serverless-deployment.md` on `feat/serverless-deployment` (see §8).

> This RFC is design-only. It captures a direction to validate before any code is
> written. It is the design counterpart of roadmap epic **1.5.0 — "Template-based
> upload (auto-fill dashboard from a run)"** (issues 734 and 383).

## 1. Context

Connecting data to Depictio today requires installing the CLI on the machine that
holds the files, authoring a `project.yaml`, and running scan + process there. That
is the right shape for the HPC/workstation case the CLI was built for, but it is
the wrong shape for two increasingly common situations:

1. **The data is already reachable by URL.** A workflow published its outputs to a
   bucket or a web server; there is no "machine with the files" to install a CLI
   on. The user has `s3://…` or `https://…` strings, and wants a dashboard.
2. **The data is indexed by an external system.** A pipeline run produced files,
   each tied to sample/entity IDs; an external database, LIMS, or data portal
   knows the URL of every file *by type*. Each type corresponds to what Depictio
   calls a data collection. The user wants those files mapped to DCs
   automatically and a dashboard opened at the end — zero authoring.

Three facts make this an extension rather than a redesign:

1. **The read layer already speaks URL.** Polars reads `s3://` and `https://`
   directly (`scan_parquet`/`scan_csv` + `storage_options`); Delta output paths
   are already S3 (`s3://{bucket}/{dc_id}`, `cli/utils/deltatables.py`). The gap
   is purely at the config/model layer: `Scan` only knows local-filesystem
   `recursive`/`single` modes, and `File.file_location` demands an existing local
   path in CLI context.
2. **Zero-CLI ingestion already ships.** `_create_dc_from_upload`
   (`datacollections_endpoints/utils.py:557`) builds a `DataCollection`
   in-process and drives the same CLI helpers (`process_data_collection_helper`)
   from the API server. Server-side URL ingestion is a sibling of that function,
   not a new pipeline.
3. **Dashboard auto-fill already half-exists.** Dashboard YAML references DCs
   **by tag** (`workflow_tag` + `data_collection_tag`), resolved to IDs at import
   (`POST /dashboards/import/yaml`). Templates already instantiate dashboards
   against any project whose DC tags match
   (`import_dashboards_from_template`, `cli/utils/templates.py`). What is missing
   is only the front half: getting from "URLs of files by type" to "a project
   whose DCs carry those tags, materialized".

## 2. Problem

### 2.1 Framing: an acquisition mode, not a new DC type

A remote file is still `native` lineage — "ingested from external files/sources"
is literally the `DataCollectionSource.NATIVE` docstring. What changes is how
files are *found* (scan) and *read* (Polars over a URL), not what they become (a
Delta table served by the exact same read stack). So the design extends `Scan`
with new modes rather than adding a `REMOTE` member to `DataCollectionSource`;
the latter would fork every `source == native` check (including the
scan-required validator) for no semantic gain.

The durable artifact of this RFC is a **contract** — the Data Manifest (§3) — and
everything else is a producer or consumer of it:

- a workflow (or a script over a LIMS/portal API) **produces** a manifest;
- server-side ingestion **consumes** it into a project with materialized DCs;
- templates **consume** it to select, configure, and prune DCs and to import
  dashboards;
- the serverless runtime (separate RFC) can **consume** the same manifest to
  build backend-less bundles, because `type` doubles as the symbolic DC
  reference its producer B is missing.

### 2.2 What "automatic" must mean

The target UX, end to end:

> paste a manifest URL (or a single file URL) + pick a template →
> project created, files mapped to DCs by type, Delta materialized,
> dashboards imported → redirected to a filled dashboard.

No CLI install, no YAML authoring, no manual DC-to-file wiring. The CLI keeps a
mirror command for scripted use, but the server path is primary.

## 3. The Data Manifest contract

### 3.1 Schema

New module `depictio/models/models/manifest.py` (shared CLI/API, fully typed —
it lives inside the `ty` gate):

```python
class ManifestEntry(BaseModel):
    id: str                    # canonical entity/sample ID
    type: str                  # DC tag this file belongs to  ← the mapping trick
    url: str                   # absolute s3:// or https:// URL
    run: str | None = None     # optional run grouping
    extra: dict[str, str] = {} # escape hatch (closed schema otherwise)

class DataManifest(BaseModel):
    version: str = "1"
    entries: list[ManifestEntry]
    source: str | None = None  # where it was fetched from (provenance)
```

Parsers: `DataManifest.from_csv()` (columns `id,type,url[,run,...]`, extras
folded into `extra`) and `from_json()` (either `{"entries": [...]}` or a bare
list). CSV/JSON are the file-format front door; a live connector (LIMS/API/DB)
is out of scope but its integration point is defined: it produces the same
`DataManifest` in memory.

Example (CSV):

```csv
id,type,url,run
S1,counts,https://data.example.org/run42/S1.counts.parquet,run42
S1,stats,https://data.example.org/run42/S1.stats.tsv,run42
S2,counts,https://data.example.org/run42/S2.counts.parquet,run42
S2,stats,https://data.example.org/run42/S2.stats.tsv,run42
```

### 3.2 Design rules (stability guarantees for downstream consumers)

- URLs are **absolute**; no base-path resolution in the contract.
- `type` values are **DC tags**. This single convention is what makes mapping,
  dashboard binding (tag → ID at import), and serverless symbolic refs all fall
  out for free.
- `version` gates schema evolution; the schema is closed (`extra` is the only
  open field).
- One entry = one file. Aggregation across entries of the same `type` is the
  ingestion layer's job, exactly like multiple scanned files today.

### 3.3 ID flow

`client_aggregate_data` already injects a `depictio_run_id` column per file. For
manifest ingestion:

- `run` → `depictio_run_id` (default constant `"remote"` when absent), keeping
  every existing per-run feature working;
- `id` → a new injected column **`depictio_manifest_id`**, added per-file during
  aggregation. Every table DC built from one manifest thus shares a key column
  with identical canonical values, so `DCLink` with the default `direct`
  resolver works with **zero configuration**. For non-table link targets
  (MultiQC sample names, image filenames) the existing `pattern` /
  `sample_mapping` resolvers apply — the manifest `id` is precisely the
  canonical ID those resolvers were designed around.

## 4. Model-layer changes

### 4.1 New `Scan` modes

`Scan.mode` gains `url` and `manifest` alongside `recursive`/`single`
(`data_collections.py:118` validator + the `scan_parameters` dispatch at
`:125`). The scan-required rule for native DCs (`:299`) is untouched — a
`url`/`manifest` scan *is* a scan.

```python
class ScanURL(BaseModel):
    url: str            # single remote file; s3:// or https:// (http:// behind an env flag)

class ScanManifest(BaseModel):
    manifest_url: str   # where to fetch the manifest (or inline entries)
    manifest_type: str  # which manifest `type` this DC consumes
    id_field: str = "id"
    url_field: str = "url"
    type_field: str = "type"
    run_field: str | None = "run"
```

Validators are **syntactic only** (scheme allowlist); no network calls in
validators, following the context-gated `ScanSingle` precedent.

DC YAML example:

```yaml
data_collections:
  - data_collection_tag: counts
    config:
      type: table
      metatype: aggregate
      scan:
        mode: manifest
        scan_parameters:
          manifest_url: "{MANIFEST_URL}"
          manifest_type: counts
      dc_specific_properties:
        format: parquet
  - data_collection_tag: reference_annotation
    config:
      type: table
      metatype: metadata
      scan:
        mode: url
        scan_parameters:
          url: "https://data.example.org/annotation.tsv"
      dc_specific_properties:
        format: tsv
```

### 4.2 `File` model relaxations

Remote files become ordinary `File` records with `file_location = <url>`. Three
validators in `models/models/files.py` currently block that:

- `validate_location`: skip the local-existence check when the location matches
  `^(s3|https?)://`;
- `filesize`: populate from a `Content-Length` HEAD when available, else a
  documented "unknown" sentinel for remote files;
- `file_hash`: for remote files, sha256 over URL + ETag (or URL alone) —
  documented as an *identity* hash, not a content-integrity hash.

Everything downstream (files endpoints, catalog matching on `file_location`
basenames, run bookkeeping) keeps working on plain strings.

### 4.3 Templates

- `MANIFEST_URL` is an ordinary `TemplateVariable`; substitution needs no change.
- `resolve_template` (`cli/utils/templates.py:671`) currently hard-requires a
  local `data_root` and runs filesystem introspection (pipeline `params.json`,
  metadata column autodetect, samplesheet probing, missing-file DC pruning).
  Refactor by **gating, not rewriting**: `data_root: str | None`, and every
  `Path(...)`-touching step becomes a no-op when it is `None`. Pruning for
  manifest DCs switches to "manifest has ≥ 1 row of this `manifest_type`"
  (same `optional: bool` semantics on the DC).
- `DCOverride` gains `scan_url` / `manifest_type` override fields so template
  conditionals can repoint remote DCs, following its existing shape.
- **Rejected for now:** remote `DATA_ROOT` (regex-recursive scan over an object
  store via S3 LIST). The manifest covers the use case explicitly and cheaply;
  a listing-based remote scan is a separate, much larger feature.

A *manifest-driven template* is therefore just an ordinary `template.yaml`
whose DCs use `scan.mode: manifest` and whose metadata declares `MANIFEST_URL`
required and no `DATA_ROOT`:

```yaml
template:
  template_id: generic/manifest-tables/1
  description: Generic table dashboards over a {id, type, url} manifest
  variables:
    - name: MANIFEST_URL
      required: true
  dashboards:
    - dashboards/base.yaml
```

One reference template (`depictio/projects/generic/manifest-tables/`) ships with
the feature and doubles as the end-to-end test fixture.

## 5. Server-side ingestion

### 5.1 The path

New `_create_dc_from_url(...)` next to `_create_dc_from_upload`
(`datacollections_endpoints/utils.py:557`), same permission/token/DC
construction flow, exposed as `POST /datacollections/create_from_url`.
Differences from the upload sibling: no tempfile, no `_MAX_UPLOAD_BYTES` cap,
`scan_config = Scan(mode="url", ...)`.

The scan stage gains a `url`/`manifest` branch that **synthesizes `File`
records** (one per URL / manifest row) instead of walking a filesystem. The
process stage reads them with Polars directly over the URL
(`storage_options` from the existing `turn_S3_config_into_polars_storage_options`
for s3) and writes Delta to `s3://{bucket}/{dc_id}` exactly as today.

**Materialize-to-Delta stays the default.** Render-time pass-through of remote
URLs is explicitly deferred: it would fork caching, joins, and auth inside
`load_deltatable_lite`, and the genuine no-copy consumer is the serverless
remote bundle (§8). Fetch-to-temp (bounded, streamed, size-capped) remains the
fallback for formats Polars cannot stream over HTTP (xlsx) and for the
column-validation helper.

Single-URL ingestion keeps the synchronous `asyncio.to_thread` pattern (parity
with upload, and the sync-httpx deadlock note there still applies). Manifest
ingestion (N files across N DCs) is implemented as a sequential per-DC loop in
the same threaded pattern — `POST /projects/ingest_manifest` returns a per-DC
`ManifestIngestReport`, with each failed DC's scan config reverted so a failed
run never leaves a manifest config with no data behind it. The report shape is
already per-DC, so switching the loop body to Celery fan-out (per-DC progress,
long-manifest scalability) is an internal phase-4 change, surfaced via the
ingestion-report machinery that `TemplateOrigin.expected_data_collections`
already provides.

### 5.2 Trap №1 — SSRF

User-supplied URLs fetched server-side are a textbook SSRF surface. All remote
reads (endpoint, Celery tasks, manifest fetch) go through one gateway module,
`depictio/api/v1/remote_fetch.py`:

- scheme allowlist (`https`, `s3`; `http` behind an explicit env flag);
- DNS-resolve, then reject private/link-local/loopback ranges (including
  `169.254.169.254`); re-check after each redirect, cap redirects (~3);
- optional admin allow/deny lists (`DEPICTIO_REMOTE_URL_ALLOWLIST`) for
  hardened deployments;
- download size cap + timeout + content-type sanity;
- sanitized error responses (never echo internal fetch errors back).

Residual risk: DNS rebinding between check and fetch — mitigated by resolving
once and connecting to the resolved IP, or accepted and documented in
allowlist-only mode.

### 5.3 Trap №2 — credentials for private buckets

Phase-gated. First slice: public `https` plus the instance's own configured S3
credentials (whatever `DEPICTIO_MINIO_*` points at). Private third-party
buckets need **per-project storage configuration** (roadmap issue 383): a
`ProjectStorageConfig` (endpoint URL, bucket, keys — encrypted at rest like
existing token storage) threaded into `storage_options` for that project's
remote reads. The model is defined by this RFC; implementation is its own
phase.

## 6. Manifest → project + dashboard flow

One orchestration endpoint, `POST /projects/from_manifest`:

```json
{
  "manifest_url": "https://data.example.org/run42/manifest.csv",
  "template_id": "generic/manifest-tables/1",
  "project_name": "run42",
  "variables": {}
}
```

1. Fetch + parse the manifest through the SSRF gateway → `DataManifest`.
2. Resolve the template **server-side**: the refactored
   `resolve_template(template_id, data_root=None, extra_vars={"MANIFEST_URL": …})`.
   `TemplateOrigin` records the manifest URL and variables — reproducibility
   for free.
3. Coverage check: manifest `type` values vs the template's DC tags; prune
   `optional` DCs with no rows, recording removal reasons in
   `expected_data_collections` (the report UI already exists).
4. Create the project (the same path CLI `run.py` uses), then scan + process
   each DC (§5), Celery-fanned.
5. Import dashboards: factor the core of `import_dashboards_from_template`
   (read YAML, `{VAR}` substitution, body construction) into a shared function
   so the server calls the import handler directly instead of HTTP-to-self.
   Tag → ID resolution at import does the binding.
6. Return `{project_id, dashboard_ids, ingestion_report}`; the UI redirects to
   a filled dashboard.

CLI mirror: `depictio run --template X --manifest URL|PATH` (the
`--template`/`--data-root` scaffolding in `cli/commands/run.py` already has the
mutual-exclusion structure to extend) — same shared functions, no new logic.

**Template-free fallback (later):** match manifest types/filenames against the
catalog's `find` rules (`match_run_dir` / `compose_run_dir`, which the catalog
TODO already earmarks for ingestion wiring) and auto-layout the proposed
components. This needs the layout packer that doesn't exist yet (the only
grid-packing code is `benchmark/configgen.py`'s `auto_generate_layout`);
template-first covers the primary ask without it.

## 7. Trap №3 — `run` vs `id` semantics

Is one manifest row a "run" or a "sample"? This RFC says: **`id` is a column,
`run` is a run**. `depictio_run_id` keeps meaning "a batch of files ingested
together" (per-run UI, rescan bookkeeping), while `depictio_manifest_id` is the
cross-DC join key. Conflating them (e.g. mapping `id` → `depictio_run_id`)
would make every sample a run and break run-scoped features. Worth revisiting
if a real deployment has one-file-per-sample-per-run granularity needs.

## 8. Serverless tie-in

The serverless RFC's main open question for producer B ("the spec carries
ObjectIds meaningless without a backend — does it need its own format with
symbolic DC refs?") is answered by this contract: **`type` = DC tag *is* the
symbolic reference table.** A tag-referenced dashboard YAML plus a manifest
(tag → URLs) is a complete backend-free build input.

- Producer B gains `--manifest`:
  `depictio dashboard build-static --spec dash.yaml --manifest manifest.json --out dir/`
  — resolve each spec DC tag to manifest rows, materialize/convert to Parquet
  locally, emit the bundle.
- Remote-mode bundles (serverless phase 9, unimplemented): a `BundleManifest`
  in `remote` mode whose `DataRef`s are the manifest URLs directly — **only
  when those URLs are Parquet** (hyparquet constraint); CSV-backed manifests
  must go through the local producer-B build. This constraint belongs in both
  RFCs.

That work lives on/after `feat/serverless-deployment`; the only obligation on
`main` is manifest schema stability (§3.2).

## 9. Phasing

Each phase independently shippable.

| Phase | Scope | Key files |
|---|---|---|
| **0** | This RFC + `DataManifest` schema frozen against hand-written CSV/JSON fixtures (parser + model tests only) | `docs/design/rfc-remote-data-manifests.md`; `depictio/models/models/manifest.py` (new) |
| **1 — minimal slice** | Table DC from a single `https://`/`s3://` parquet/csv URL, server-side: `ScanURL`, SSRF gateway, `_create_dc_from_url` + `POST /datacollections/create_from_url`, `File` relaxations, url branch in scan/aggregate | `models/models/data_collections.py`; `models/models/files.py`; `api/v1/remote_fetch.py` (new); `datacollections_endpoints/{utils,routes}.py`; `cli/utils/{scan,deltatables}.py` |
| **2** | `ScanManifest` + manifest ingestion into an existing project: type→tag mapping, `depictio_manifest_id` injection, `POST /projects/ingest_manifest` + per-DC report (sequential; Celery fan-out moved to phase 4) | same model files; `cli/utils/deltatables.py`; `projects_endpoints/manifest_ingest.py` (new) |
| **3** | Manifest-driven templates end-to-end: `resolve_template` data-root-optional refactor, shared dashboard-import function, `POST /projects/from_manifest`, CLI `--manifest`, reference template + E2E test | `cli/utils/templates.py`; `models/models/templates.py`; `projects_endpoints/routes.py`; `cli/commands/run.py`; `depictio/projects/generic/manifest-tables/` (new) |
| **4** | Hardening & access: per-project storage config (issue 383), manifest re-ingest/refresh, Celery fan-out for long manifests, builder UI (paste a URL / a manifest) | `ProjectStorageConfig` (new); `projects_endpoints`; `celery_endpoints/`; viewer/builder |
| **5** | Catalog auto-compose fallback (manifest → catalog match → auto-layout, no template) | `models/components/advanced_viz/catalog.py`; `catalog_endpoints`; layout packer |
| **6** | Serverless remote bundles from the same manifest (resolves the serverless RFC's producer-B question) | branch: `depictio/serverless/producer_b.py`; `packages/depictio-static-core` |

Phase 1 is demoable on its own: "paste a URL, get a table DC" — one model
change, one endpoint, one security module, no templates or manifests involved.

## 10. Verification

- **Phase 0:** pytest over the manifest parser (CSV/JSON fixtures, closed-schema
  rejection, version gating); `uv run ty check depictio/models/` stays at zero
  errors.
- **Phase 1:** full-stack HTTP test in the style of the existing API tests —
  serve a fixture parquet/csv over a local HTTP server, `create_from_url`,
  assert the Delta table and `/deltatables/get` round-trip; per-format spike
  matrix (parquet/csv/tsv over https, s3) recorded in the test names; SSRF
  gateway unit tests (private ranges, redirects, schemes).
- **Phase 3:** Playwright E2E — `POST /projects/from_manifest` with the
  reference template, assert redirect target renders components bound to the
  manifest DCs; existing template E2E suites must stay green (the
  `resolve_template` refactor is gate-don't-rewrite).

## 11. Open questions

1. **Polars-over-HTTPS coverage per format.** `scan_parquet` over https is
   solid; csv may route through a full download; xlsx always fetch-to-temp.
   Phase-1 spikes decide streaming vs fetch-to-temp per format.
2. **Manifest refresh semantics.** Re-fetch on demand: overwrite vs append vs
   diff. Proposal: overwrite-with-report first (same shape as the serverless
   RFC's staleness question).
3. **Non-table DC types from manifests** (multiqc parquet URLs, image URLs,
   geojson). Each has an existing S3-pointer precedent
   (`DCMultiQC.s3_location`, `DCImageConfig.s3_base_folder`,
   `DCGeoJSONConfig.s3_location`); extend per-type in phases 2/4, table-only
   first.
4. **File-model relaxations ripple.** Consumers of `file_hash`/`filesize`
   assumptions in files endpoints need a phase-1 audit.
5. **Live connectors** (query a LIMS/portal/DB instead of fetching a file):
   out of scope; the in-memory `DataManifest` is the defined extension point.
6. **Remote `DATA_ROOT`** (listing-based recursive scan over object stores):
   rejected for now (§4.3); reopen if manifest adoption shows a real gap.
