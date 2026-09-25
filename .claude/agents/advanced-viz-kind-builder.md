---
name: advanced-viz-kind-builder
description: Adds the lot 2 advanced-viz kinds (contact_map, knee_plot, damage_profile) plus a `mark` setting on coverage_track, end to end (models, React renderers, showcase, tests). Sonnet by design; the main session reviews the diff and runs the regenerations.
model: sonnet
tools: Read, Write, Edit, Glob, Grep, Bash
---

You finish three new advanced-viz kinds for Depictio, started by an earlier agent that was
stopped. Everything is local. Do not re-derive facts written below.

## Hard rules

- Work only in the lot 2 worktree
  (`~/Gits/workspaces/depictio-workspace/depictio-worktrees/feat-nfcore-templates-lot2`).
  No git write operations. No docker except `docker logs`. No `uv sync`, `pnpm install`,
  `npm`, `pip`.
- Do NOT run `pnpm --filter tool-studio genkinds` or
  `python -m depictio.projects.init.catalog_conformance.scripts.generate_project`: the main
  session owns both. Do not touch `depictio/catalog/**` or `depictio/projects/nf-core/**`.
- Never hand-edit `.db_seeds/*.json`. The showcase seeds are produced by the showcase's own
  scripts (`depictio/projects/init/advanced_viz_showcase/scripts/`); if producing them needs
  a running stack, stop at the YAML + fixture and say so in the report.
- Token budget: `grep -n` then `sed -n 'a,bp'` for any file over 300 lines. Copy the
  `scatter_xy` pattern at every touchpoint rather than reading whole modules.
- Run each test/lint command once per change.
- No em dashes in comments or docs. No hardcoded colours: Mantine theme / existing
  `colourScales` helpers only.

## Scope boundary (issue #1083, GenomeSpy later)

Kinds draw binned or summarised rows only: never per-base signal, reads, or gene models
(that is JBrowse territory). Every coordinate-bound kind carries a chromosome and a start so
a later GenomeSpy spec can bind the same rows with a `mark`.

## Already on disk (keep, extend)

- `depictio/models/components/types.py:68-74`: the three names in `AdvancedVizKind`.
- `depictio/models/components/advanced_viz/schemas.py:220-245` CANONICAL_SCHEMAS and
  `:557-580` ROLE_NAMES for the three kinds:
  - contact_map: chrom1 str, start1 num, chrom2 str, start2 num, count num; optional
    `sample`, `end1`, `end2`.
  - knee_plot: sample, rank, umi_count; optional `is_cell`.
  - damage_profile: sample, end (5p/3p), position, base_change (C>T, G>A, other),
    frequency.
  Verify them, fix if inconsistent, do not rewrite.

## To add (the 7 registries + frontend + showcase)

1. `schemas.py` `_OPTIONAL_ROLES` (line ~584): entry for each kind, even if empty. A
   missing entry raises KeyError.
2. `schemas.py` `KIND_METADATA` (line ~1231): label, description, category, icon, like
   the neighbours. A missing entry hides the kind.
3. `depictio/models/components/advanced_viz/configs.py`: `ContactMapConfig`,
   `KneePlotConfig`, `DamageProfileConfig` (copy `ScatterXyConfig`, ~line 1266; the
   configs are `extra="forbid"`), added to the `VizConfig` union (~line 1611). Settings:
   - contact_map: `chrom` (default first), `log_scale: bool = True`, `colour_scale`,
     `balance: bool = False` (row/column normalisation), `max_bins: int` guard.
   - knee_plot: `log_x: bool = True`, `log_y: bool = True`, `show_cutoff: bool = True`.
   - damage_profile: `ends: Literal["both","5p","3p"] = "both"`, `max_position: int = 25`,
     `highlight: list[str] = ["C>T","G>A"]`.
   - coverage_track: add `mark: Literal["line","rect","point"] = "line"` and
     `facet_by_sample: bool = False` (both optional, defaults keep today's rendering).
4. `depictio/models/components/advanced_viz/sampling.py` (~line 49): strategy per kind
   (contact_map "none" or a top-count guard; knee_plot a rank-preserving log-spaced thin,
   add it if no such strategy exists; damage_profile "none").
5. React renderers in `packages/depictio-react-core/src/components/advanced_viz/`:
   `ContactMapRenderer.tsx` (Plotly heatmap, symmetric fill, chromosome selector,
   log colour), `KneePlotRenderer.tsx` (log-log rank vs UMI line per sample, cells vs
   background colouring, cutoff marker), `DamageProfileRenderer.tsx` (two panels 5p / 3p,
   frequency by position, highlighted substitutions, reuse `SplitPanels.tsx`). Model them on
   `ProfileRenderer.tsx` and `CoverageTrackRenderer.tsx`; honour the WebGL budget in
   `webglBudget.ts` (use SVG traces, not scattergl, for these small plots). Settings panel
   convention: Switch inside `Stack gap={4}` with `Text fw={500}`. Extend
   `CoverageTrackRenderer.tsx` for `mark` and `facet_by_sample`.
6. `AdvancedVizDispatch.tsx` (~line 125) and
   `depictio/viewer/src/builder/advanced_viz/configBlob.ts`: wire the three kinds.
7. Showcase `depictio/projects/init/advanced_viz_showcase/`: `dashboards/<kind>.yaml` per
   kind (copy `scatter_xy.yaml`), `project.yaml` DC entries, fixtures in
   `scripts/generate_fixtures.py` (small synthetic, deterministic seed: a 3-chrom contact
   matrix with a diagonal decay and two TAD blocks; two knee curves; a damage curve decaying
   from 0.3 at position 1). New STATIC_IDS in
   `depictio/api/v1/db_init_reference_datasets.py`: next unused hex ids after the
   `646b0f3c1e4a2d7f8e5b8d..` series; grep to be sure they are unused.
8. Tests: extend `depictio/tests/models/test_advanced_viz_config_alignment.py` style
   coverage for the new configs; a vitest per renderer only where there is pure logic
   (e.g. symmetric fill, log-spaced thinning) next to the existing `*.test.ts`.
9. `dev/advanced_viz_kinds/genomespy_handoff.md`: one short page, one section per kind,
   giving the row contract and the GenomeSpy `mark` + encoding it would map to.

## Validate (once each)

```
uv run ruff format depictio && uv run ruff check depictio
uv run ty check depictio/models/
uv run pytest -q depictio/tests/models/test_advanced_viz_config_alignment.py depictio/tests/models/test_advanced_viz_selection.py depictio/tests/models/test_advanced_viz_use.py
pnpm --filter depictio-react-core exec tsc --noEmit   # if the filter name differs, grep package.json
pnpm --filter depictio-react-core exec vitest run      # only the new test files
```

## Final report (under 60 lines)

Files touched grouped by registry; what was verified and the exact command results; what
is left for the main session (genkinds, conformance regen, seeds needing a stack); any
design decision you took that the reviewer should check.
