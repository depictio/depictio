# Serverless engine spike — DuckDB-WASM vs. hyparquet

Phase 0.5 of the serverless plan (RFC: `rfc-serverless-deployment.md`). This gate
runs **before any phase-1 kernel code is committed**: it measures both candidate
browser engines against the single-file byte budget and the interaction-latency
target, and records the decision the kernels are built on.

**Decision rule (fixed in advance):** DuckDB-WASM is rejected for `single-file`
mode if its inlined footprint (gzip of the base64-embedded artifacts) exceeds the
static-runtime CI budget of 3,355,443 bytes (3.2 MB) — the whole-page budget,
before any viewer code or data.

**Environment:** Chromium 143 (`/opt/pw-browsers/chromium`) driven by Playwright
from `file://` with all network blocked; Node 22 for the native-side runs;
`@duckdb/duckdb-wasm` 1.33.1-dev57.0, `hyparquet` 1.27.1, `hyparquet-compressors`
1.1.1; Polars 1.42.1 as the server-side reference. Linux container, shared vCPUs —
absolute times are indicative; the orders of magnitude are what the decision uses.

## 1. Size

| Artifact | raw | base64 | gzip-9 (base64) |
|---|---|---|---|
| `duckdb-eh.wasm` | 34.25 MB | 45.67 MB | 11.40 MB |
| `duckdb-browser-eh.worker.js` | 0.74 MB | 0.98 MB | 0.29 MB |
| loader (`duckdb-browser.mjs`) | 0.03 MB | 0.04 MB | 0.01 MB |
| **DuckDB `eh` bundle, inlined** | **34.28 MB** | — | **11.41 MB** |
| hyparquet + **all** codecs (esbuild IIFE, minified) | 165 KB | — | **89 KB** |

DuckDB-WASM's inlined gzip footprint is **3.6× the entire single-file budget** on
its own. The decision rule fires with no margin for debate. hyparquet with every
codec included costs 2.7 % of the budget.

## 2. Cold init from `file://`

- **DuckDB-WASM: fails.** Worker created from a blob URL, wasm passed as a blob
  URL: `instantiate()` dies with `TypeError: Failed to fetch` — under a `file://`
  opaque origin the worker cannot fetch the main-page blob, and the init promise
  never settles. Workarounds (inlining the wasm bytes into the worker source)
  were not pursued: size alone already disqualifies single-file, and `static-dir`
  / `remote` are HTTP-served where standard DuckDB-WASM hosting is known-good.
- **hyparquet: no init step at all.** Plain JS, works inside the page, no worker
  or wasm handshake required (hysnappy's wasm is instantiated from bytes, not
  fetched).

## 3. Decode + kernel microbench

Synthetic 1M-row frame shaped like the phase-1 kernel inputs (`f64` metric,
`String` categorical + `Int32` `__code__` companion, datetime + `Int64` `__ts__`
companion, `String` id), snappy, 250k-row row groups → 33 MB Parquet.
Reference values computed with Polars using the server's predicate forms.

| Measurement | Node 22 | Chromium (`file://`, fully inlined 44 MB page) |
|---|---|---|
| Page load + parse | — | 3.0 s |
| base64 → bytes (33 MB) | — | 274 ms |
| Parquet decode, 4/7 columns projected | 1,098 ms cold / 526 ms warm | 726 ms |
| Full decode incl. String column | 1,322 ms | — |
| **mask** (numeric > + codebook `is_in` + `__ts__` compare), 1M rows | **13.0 ms** | **10.6 ms** |
| **aggregate** (sum + mean + median) over the mask | **22.2 ms** | **21.7 ms** |
| Real seed: viralrecon `multiqc.parquet` (25.5 MB, GZIP, 23 cols) full decode | 436 ms | — |

Decode is a **one-time load cost**; every subsequent filter interaction is the
mask + aggregate pair — ~30 ms per interaction against the 150 ms target, 5×
headroom on the largest frames we ship.

**Differential check: exact.** Matched-row count (54,450), `sum`, `mean` and the
interpolated `median` are bit-identical between the JS kernels and Polars on the
same data — including the `Int64`/`BigInt` timestamp comparison path.

## 4. Compression findings (constraints for the phase-1 builder)

- Polars `write_parquet` defaults to **ZSTD**; real seeds in the repo are
  MultiQC-written **GZIP**. Bare hyparquet only decodes snappy/uncompressed —
  `parquet unsupported compression codec: ZSTD` — so codec support must be
  explicit.
- `hyparquet-compressors` (89 KB gz for everything) decodes all of them; ZSTD
  decode measured ~450 ms for one 1M-row column vs. snappy's 526 ms for four —
  JS-side ZSTD is markedly slower per byte.
- **Builder rule:** producer A/B re-export with `compression='snappy'`,
  `row_group_size=250_000`; the runtime still bundles `hyparquet-compressors` so
  a hand-supplied Parquet (producer-B `--data`) in any codec keeps working.

## 5. Decision

**hyparquet is the primary engine for all three modes.** The phase-1
`QueryEngine` implementation is `engine/hyparquet/`; kernels operate on the
decoded typed arrays (`Float64Array`/`Int32Array`/`BigInt64Array`), matching the
microbench above. DuckDB-WASM is **rejected for `single-file`** by the size rule
(11.41 MB inlined-gzip > 3.2 MB budget) and by its `file://` init failure; it is
*not* adopted for `static-dir`/`remote` either at this point — nothing in phases
1–9 needs SQL — but the engine-agnostic `QueryEngine` interface keeps it
pluggable there should a future feature (ad-hoc queries, joins over remote
Parquet) warrant its 11 MB served-over-HTTP cost.

Two consequences flow into phase 1: the differential harness keeps float
comparisons at the strict `1e-9` relative tolerance (the exact-match result says
we can), and `__ts__`/large-int columns are handled as `BigInt64Array` in the
mask kernel (mixing `number` comparisons silently truncates above 2^53).
