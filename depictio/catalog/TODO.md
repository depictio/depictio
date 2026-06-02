# Catalog — TODO / open work

Concise backlog for the bio-catalog. Current state: catalog core + guided-mode
preview (`catalog match`/`compose` + `software_versions.yml` scoping) are done
and on `claude/optimistic-mayer-iQrTO`. Direction v3 = module-granular,
pipeline-agnostic (see `docs/design/bioinformatics-catalog.md`).

## Free mode (UI — frontend PR)
- **Do not gate the UI.** The user must always be able to map an advanced viz
  directly onto a file's columns (role → column) **by hand, with no condition**
  — even when nothing is recognised/suggested.
- Applies in **two places**: the **project data manager** and the
  **advanced viz section**.
- Suggestions may *pre-fill* the binding, but must never *block* manual mapping.
- Check/relax gating in `ProjectDetailApp.tsx` (`hasVizMatch`) and
  `AdvancedVizBuilder.tsx` (producer-driven pre-selection).

## Guided mode
- Wire `compose_run_dir()` into the real ingestion/scan path so it actually
  builds/proposes a dashboard (today it's a CLI preview only).
- `refresh-index`: the vendored `_index/{nf_core_modules,edam_terms}.txt` are
  **seeds**; run `depictio catalog refresh-index` (needs network) to make them
  authoritative so existence checks catch typos.

## Module-granular debt (v3 — dedicated PR)
- **Re-key `recipe`/`find` by module**, not by pipeline. Today recipes live
  under `projects/<pipeline>/recipes/` (e.g. `mosdepth/genome_coverage.yaml`
  points at `nf-core/viralrecon/coverage_track_canonical.py`), which breaks
  reuse by a custom workflow. Goal: a module owns its recipe/find; a
  pipeline/workflow is just a list of modules.
- Add typed **input schema** to recipes (`SOURCES`/`INPUT_SCHEMAS`) for input
  validation + fixture generation + nf-core drift detection (do this when
  wiring the scan).

## Retire `suggest_producers` (frontend PR)
- Column-fingerprint recognition is unreliable; currently only de-scoped in
  docs. Actual removal touches the API (`/viz-suggestions`,
  `/suggest-from-columns`) + the React "suggested producer" chips. Keep
  `suggest_viz_kinds` (role/dtype based).

## Validation / CI hardening
- **Level-3 validation**: per-entry sample fixtures so CI proves
  find → recipe → render end-to-end on real data (green CI = trustworthy entry).
- `match_run_dir` perf: single `os.walk` pass (currently one `rglob` per output)
  — only matters once the catalog/run grows.

## Authoring / AI helpers (nice-to-have)
- `catalog scaffold <nf-core-module>`: fetch the module `meta.yml` and emit a
  draft entry (identity + find + EDAM auto-filled; recipe/renders_as left TODO).
- `catalog suggest <recipe>`: from a recipe's output columns, propose viz + role
  bindings (reuses `suggest_viz_kinds`/`CANONICAL_SCHEMAS`) to help authors.
