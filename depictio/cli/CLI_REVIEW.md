# `depictio/cli` — Code Review & Improvement Report

Evaluation of the `depictio/cli` package (~12K lines, 33 files) across four
axes: **rich output / presentation**, **performance**, **code style /
structure**, and **logging consistency**.

This document records the findings, the fixes applied in this pass, and a
prioritized backlog of larger follow-ups (some of which involve server-side or
architectural changes).

---

## 1. Summary of findings

| # | Area | Finding | Severity | Status |
|---|------|---------|----------|--------|
| A1 | Logging | `scan_utils.py` imported the **API** logger, not the CLI logger | High | ✅ Fixed |
| A2 | Logging | Same message often emitted twice (logger + rich) | Low | Documented |
| A3 | Logging | Verbose formatter always on; no concise mode | Low | Documented |
| B1 | Presentation | `from rich import print` shadowed the builtin throughout `rich_utils` | Medium | ✅ Fixed |
| B2 | Presentation | Console fragmentation: module global vs. fresh `Console()` instances vs. `rich.print`'s own | Medium | ✅ Fixed |
| B3 | Presentation | `catalog`/`recipe` used bare `typer.echo`; no shared table helper | Medium | ✅ Partially fixed |
| B4 | Presentation | Three different idioms for error output | Low | Documented |
| B5 | Presentation | Progress/spinners only on scan; long API/process/join/S3 ops are silent | Low | Documented |
| C1 | Performance | `regex_match` matched twice + rebuilt an uncompiled pattern every call (O(N×M) hot loop) | High | ✅ Fixed |
| C2 | Performance | Identical `temp_run` reallocated inside the per-file scan loop | Medium | ✅ Fixed |
| C3 | Performance | No HTTP client reuse — fresh TCP/TLS handshake per API call (~30 endpoints) | High | ✅ Fixed |
| C4 | Performance | Serial per-run/per-file `DELETE`s in scan cleanup | High | Backlog |
| C5 | Performance | Serial S3 uploads / sequential lazy file reads | Medium | Backlog |
| D1 | Style | Five >800-line modules; candidates for decomposition | Medium | Backlog |
| D2 | Style | `validate_call` on hot inner helpers adds per-call overhead | Low | Backlog |
| D3 | Style | Duplicate "check by id then by name" project lookup | Low | Documented |
| D4 | Style | Dead/commented code | Low | ✅ Partially fixed |

---

## 2. Fixes applied in this pass

All changes are behaviour-preserving (validated by the full CLI test suite —
269 passed — and command smoke tests).

### Logging
- **`scan_utils.py`**: `from depictio.api.v1.configs.logging_init import logger`
  → `from depictio.cli.cli_logging import logger`. Scan-util debug output now
  obeys the CLI `--verbose` / `--verbose-level` controls like every other CLI
  module.

### Performance
- **`scan_utils.regex_match`**: now matches **once** against a compiled,
  `@lru_cache`-d pattern (`_compiled_normalized_regex`) instead of running
  `re.match` twice and re-running `str.replace` on every call. The
  `(bool, re.Match | None)` return contract is unchanged. This is the per-file,
  per-data-collection hot path in scanning.
- **`scan.py`**: the invariant `temp_run = WorkflowRun(...)` is now built once
  per `(run, data_collection)` before the per-file loop rather than reallocated
  for every matched file.
- **`common.get_http_client()`**: a process-wide, lazily-created, pooled
  `httpx.Client` (closed via `atexit`). `api_calls.py` and `links.py` now route
  every request through it (`get_http_client().get/post/...`) instead of the
  bare `httpx.get/post/...` module functions, so the connection to the API host
  is kept alive across the many sequential calls a single scan/process/sync
  invocation makes. Per-request `timeout`/`headers` overrides are preserved.

### Presentation
- **`rich_utils.py`**: removed `from rich import print` (no more builtin
  shadowing). A single shared `console` is now used everywhere; the redundant
  `Console()` instances and duplicate local `from rich import ...` blocks inside
  the table-rendering helpers were removed (helpers fall back to the shared
  console via `_DEFAULT_CONSOLE`). `rich_print_json` routes through
  `console.print_json`.
- **New `rich_utils.render_records_table(records, columns, title, column_styles)`**
  — a reusable helper to render a list of uniform dict records as a styled
  table, replacing hand-rolled `Table` construction.
- **`catalog.py`**: `catalog list` now renders via `render_records_table`
  instead of bare `typer.echo`, as the consistency exemplar for migrating the
  remaining plain-text commands.

### Cleanup
- Removed dead commented lines in `common.py` and `scan_utils.py`.

---

## 3. Recommended follow-ups (backlog)

Ordered by value/effort. Several were explicitly scoped out of this pass.

1. **Batch delete during scan cleanup (C4)** — `scan.py` issues one HTTP
   `DELETE` per missing run and per orphaned file in a nested loop. Add a
   server-side batch-delete endpoint (`/runs/delete_batch`,
   `/files/delete_batch`) mirroring the existing `upsert_batch` endpoints, and
   collect IDs to delete in one call. *Requires an API change.*
2. **Parallelize client-side I/O (C5)** — wrap the serial S3 uploads
   (`images.py`) and the sequential lazy file reads (`deltatables.read_files_lazy`)
   in a `ThreadPoolExecutor`. boto3 and Polars releases are both thread-safe for
   this pattern.
3. **Adopt `render_records_table` everywhere** — migrate the remaining
   `typer.echo` output in `catalog.py` (`info`, `columns`) and `recipe.py` to
   rich, and replace the hand-rolled `Table` blocks in `data.py` link/join
   listings with the shared helper.
4. **Unify the error idiom (B4)** — standardize on
   `rich_print_checked_statement(..., "error")` / `handle_error`; remove ad-hoc
   `console.print("[red]...")`.
5. **Add spinners to long operations (B5)** — wrap API sync, process, and join
   flows in the same `rich.progress` pattern already used by `scan.py`.
6. **Logging polish (A2/A3)** — stop double-emitting the same message via both
   the logger and a rich statement; add a concise (message-only) formatter for
   the default level and reserve the file/func/line formatter for `--verbose`.
7. **Decompose the >800-line modules (D1)** — split `scan.py`, `deltatables.py`,
   `joins.py`, `api_calls.py` along their natural seams (e.g. `api_calls.py` →
   one module per resource group). High-churn; do as a dedicated PR.
8. **Trim `validate_call` on hot inner helpers (D2)** — keep it on command
   boundaries; drop it from tight inner-loop helpers (e.g. in `common.py`).
9. **Collapse duplicate project lookup (D3)** — the id-then-name fallback in
   `api_sync_project_config_to_server` can be a single endpoint call.

### Larger / aggressive options (evaluate before committing)
- **Async refactor** — the CLI is fully synchronous. An `anyio`/`httpx.AsyncClient`
  rewrite of the scan/process pipelines would overlap network and disk I/O, but
  it is a deep change touching every `api_*` function and Typer command. Only
  worth it if profiling shows network round-trips dominate runtime; the shared
  client (C3) captures most of the easy win first.
- **`force_terminal=True` reconsideration** — the shared console forces ANSI
  even when output is piped/redirected. Consider gating on `sys.stdout.isatty()`
  (or a `--color/--no-color` flag) so logs/redirects stay clean. Left as-is here
  because changing it is a user-visible behaviour change.
