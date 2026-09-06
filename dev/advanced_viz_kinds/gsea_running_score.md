# `gsea_running_score`

The canonical GSEA enrichment plot: three panels stacked on one shared rank
axis.

| Panel  | What it draws                                                  | Roles                |
| ------ | -------------------------------------------------------------- | -------------------- |
| top    | the running enrichment score walked along the ranked gene list  | `rank`, `running_es` |
| middle | a hit rug, one tick per member gene at its rank                 | `member`             |
| bottom | the ranked metric the gene list was ordered by                  | `metric`             |

`config.top_n_sets` gene sets are drawn at once, overlaid on one axis or
faceted one panel each. The leading edge is shaded when `config.show_leading_edge`.

## Model

- Config: `GseaRunningScoreConfig` in
  `depictio/models/components/advanced_viz/configs.py`
- Canonical roles: `CANONICAL_SCHEMAS["gsea_running_score"]` in
  `depictio/models/components/advanced_viz/schemas.py`, namely
  `gene_set` (string), `rank` (numeric), `running_es` (float)
- Sampling policy: `"none"` in
  `depictio/models/components/advanced_viz/sampling.py`. The curve is read as
  an ordered whole, so the server sends the frame whole; past the no-sample
  ceiling it samples anyway and the renderer raises the `estimated` badge
  rather than presenting a punctured curve as the real one.
- No selection: `gsea_running_score` declares none, and the renderer emits none.

## Renderer

`packages/depictio-react-core/src/components/advanced_viz/GseaRunningScoreRenderer.tsx`

Built to the shape of `EnrichmentRenderer` (one `fetchAdvancedVizData` call,
the `plotlyTheme` helpers, `AdvancedVizFrame` for the loading / error / empty /
Show-data / Settings chrome) with the stacked-panel layout borrowed from
`CoverageTrackRenderer` — y-axis `domain` allocation with one shared x axis
anchored to the bottom-most panel.

What it draws:

- **Panels.** Built as a list of relative heights and then shared out over the
  paper, so a component with no `member_col` and no `metric_col` gets a
  full-height curve rather than a curve plus two empty bands. In facet mode
  each gene set gets its own running-ES panel, labelled with an annotation at
  the panel's top-left rather than a y-axis title, since set names
  (`HALLMARK_TNFA_SIGNALING_VIA_NFKB`) do not fit a left margin.
- **Curves.** Rows are grouped by `gene_set_col` and sorted by `rank_col`.
  Colours come from `stableColorMap` keyed on **every** set in the frame, not
  the visible slice, so a set keeps its colour as the user changes top-N or
  filters the dashboard. No second round-trip is needed for the universe: the
  kind is served whole, so the frame already holds every set.
- **Set ranking.** Sets are ordered by `|peak running ES|` descending and the
  first `top_n_sets` are drawn. The extremum is also marked with a dot, so the
  enrichment score can be read off the curve instead of eyeballed.
- **Leading edge.** Drawn as the filled area under the running score between
  the start of the list and the extremum. Two deliberate choices:
  - it is *sign-aware*. GSEA's leading-edge subset is the stretch of the list
    on the enriched side of the extremum: ranks up to the peak for a positively
    enriched set, ranks from the trough to the tail for a negatively enriched
    one. Shading `[0, extremum]` unconditionally would put the highlight on the
    wrong half of a down-regulated set.
  - it is a filled curve segment, not the textbook full-height vertical band.
    Five overlaid bands read as mud; the filled segment says the same thing
    per curve and survives the overlay layout as well as the facet one.
- **Hit rug.** One row per gene set, `line-ns-open` markers at the member
  ranks, coloured with the set's curve colour. Only the ranks whose
  `member_col` cell is truthy — accepted as `true` / `1` / `TRUE` / `yes`,
  because a boolean column survives a TSV round-trip as any of those and
  silently drawing an empty rug would be worse than being lenient.
- **Ranked metric.** The metric is a property of the rank, not of the set, so
  it repeats once per set in the frame; the renderer deduplicates on rank
  before drawing it as a single filled area in the theme's text colour.

## Tier-2 controls

| Control            | Persisted as         | Default   |
| ------------------ | -------------------- | --------- |
| Top-N gene sets    | `top_n_sets`         | `5`       |
| Shade leading edge | `show_leading_edge`  | `true`    |
| Layout             | local state only     | `overlay` |
| Hit rug            | local state only     | `true`    |
| Ranked metric      | local state only     | `true`    |

The first two go through `usePersistedVizControl` with `metadata` and the key
on one line, which is what `test_persisted_controls_survive_their_model`
parses. The last three are plain `useState`: `GseaRunningScoreConfig` has no
field to persist them into, and the config model is `extra="forbid"`, so
inventing a key here would not merely go unvalidated — it would make the
component unloadable on its next export or re-import. See
[Missing model fields](#missing-model-fields).

## Data source

### What the megatest actually holds

Nothing usable, and the reason matters.

`depictio/projects/nf-core/differentialabundance/2.0.0/megatest.yaml` pins
`results_sha 30ed7741fc392127156c2fb10cfa3d69d216b54b`. Listing that prefix
(`python3 scripts/nfcore_megatest.py ls --pipeline differentialabundance
--results-hash 30ed…`, a listing, no download) returns **39 objects and no
GSEA output at all** — no `tables/gsea/`, no `gsea_report_for_*`, no `.gmt`,
no `edb/`.

The `gsea` that appears all over that prefix is a *parameter-set label*, not an
output: the run was launched with two param sets at once, so every published
file sits under `…/deseq2_rnaseq_gsea,deseq2_rnaseq_gprofiler2/`. The published
run's own `pipeline_info/params.json` settles it:

```
functional_method = none
```

GSEA did not run. The `gsea_*` params in that file are defaults carried by the
schema, not evidence of a GSEA execution. So there is no local fixture, no
remote fixture at this results hash, and **the recipe below cannot be validated
against the 2.0.0 megatest**. It needs either a fresh
`nf-core/differentialabundance` run with `--functional_method gsea`, or GSEA
outputs from another pipeline.

### What a real GSEA run publishes

From `nf-core/modules` `gsea/gsea` (GSEA 4.3.2 desktop, `gsea-cli`) and
`nf-core/differentialabundance` 2.0.0 `docs/output.md`. The module sets
`ext.prefix = "${meta.id}.${gene_sets.baseName}."`, and the pipeline publishes
tables under `tables/gsea/<contrast>/` and images under
`plots/gsea/<contrast>/png/`.

| File (module emit)                          | Grain                      | Carries |
| ------------------------------------------- | -------------------------- | ------- |
| `*gsea_report_for_<condition>.tsv` (`report_tsvs_ref` / `report_tsvs_target`) | one row per **gene set**   | `NAME`, `SIZE`, `ES`, `NES`, `NOM p-val`, `FDR q-val`, `FWER p-val`, `RANK AT MAX`, `LEADING EDGE` |
| `*ranked_gene_list*.tsv` (`ranked_gene_list`) | one row per **gene**, in rank order | `NAME`, `DESCRIPTION`, `SCORE` |
| `gene_sets_*.tsv` (`gene_set_tsv`, optional, needs `-make_sets true`) | one row per **member gene of one set** | `NAME`, `PROBE`, `GENE SYMBOL`, `GENE_TITLE`, `RANK IN GENE LIST`, `RANK METRIC SCORE`, `RUNNING ES`, `CORE ENRICHMENT` |
| `*gene_set_sizes.tsv` (`gene_set_sizes`)     | one row per gene set       | `NAME`, `ORIGINAL SIZE`, `AFTER RESTRICTING TO DATASET`, `AFTER GENE SET SIZE FILTER`, `STATUS` |

Header strings above are GSEA 4.x's; they are read from the module's emit
patterns and the tool's documented output, **not** from a file in hand. Verify
them against a real run before pinning the recipe's alias table.

Two things follow directly:

1. **`gsea_report_for_*.tsv` cannot back this kind.** It is one row per gene
   set with no rank axis and no running score. That file backs the existing
   `enrichment` kind (`term` ← `NAME`, `nes` ← `NES`, `padj` ← `FDR q-val`,
   `gene_count` ← `SIZE`) and should get its own catalog output beside this
   one.
2. **`RUNNING ES` exists on disk only at the member ranks.** The per-set detail
   file has one row per *member* gene, so it samples the running score at the
   hits and says nothing about the ranks in between.

### Which output columns can be read, and which must be recomputed

| Output column | Dtype     | Source                                                    |
| ------------- | --------- | --------------------------------------------------------- |
| `gene_set`    | `Utf8`    | read — the set name, from the per-set file name (or the `NAME` column of the report) |
| `rank`        | `Int64`   | read — `RANK IN GENE LIST` (**0-based in GSEA**; the recipe should publish it 1-based or say which it is), or the row position in `ranked_gene_list*.tsv` |
| `running_es`  | `Float64` | read at member ranks only (`RUNNING ES`); **recomputed** for every other rank |
| `member`      | `Boolean` | **recomputed** — `true` for the ranks present in the set's detail file (or in the `.gmt` entry), `false` elsewhere. It is never a column on disk: the per-set file *is* the member list, so every one of its rows is a member and a naive read would produce an all-`true` column |
| `metric`      | `Float64` | read — `RANK METRIC SCORE` at the member ranks, `SCORE` in `ranked_gene_list*.tsv` for every rank |

Optional pass-through columns worth carrying: `contrast` (`Utf8`, from the file
name, so one DC can serve every contrast and the dashboard filters on it),
`gene_id` (`Utf8`, `PROBE` / `GENE SYMBOL`, for hover), `nes` and `fdr`
(`Float64`, joined from the report so the top-N ordering can be by NES rather
than by peak height), `leading_edge` (`Boolean`, `CORE ENRICHMENT` == `Yes`).

**The recomputation.** With the ranked list (every gene, its metric, its rank)
and the set membership, the weighted Kolmogorov–Smirnov walk GSEA uses is
reproduced exactly:

```
N   = number of genes in the ranked list
Nh  = number of set members present in it
N_R = sum over members g of |metric_g| ** p      # p = 1 for scoring_scheme "weighted"
walk over ranks i = 1..N:
    running += |metric_i| ** p / N_R    if gene i is a member
    running -= 1 / (N - Nh)             otherwise
ES = the value of `running` furthest from zero
```

`p` follows `params.gsea_scoring_scheme` (`weighted` → 1, `classic` → 0,
`weighted_p2` → 2). The recomputed curve should be checked against the
`RUNNING ES` values the per-set file already carries — they must agree at every
member rank, which makes this a self-validating recipe.

Membership can come from either the per-set detail files (each file's gene list
is exactly the members present in the ranked list — the right answer, already
size-filtered) or from the input `.gmt` (`params.gene_sets_files`, which is a
pipeline *input*, not a published output; GSEA also drops a copy in `edb/`,
which this module does not emit).

**Row count, and why it needs a cap.** A full walk is one row per (gene set,
rank). Hallmark alone against a 31 000-gene list is ~1.5 M rows per contrast,
and this kind is `sampling: "none"`. Two mitigations the recipe should apply:

- keep only the sets a dashboard would ever draw — top ~20 by `|NES|` among
  those clearing `FDR q-val < 0.25` (GSEA's own convention);
- store the curve's **vertices** rather than every rank. Between two
  consecutive hits the running score falls linearly, so the pair (rank before
  the hit, hit rank) for each hit, plus rank 1 and rank N, reproduces the curve
  losslessly at ~`2·Nh + 2` rows instead of `N` — a 200-gene set drops from
  31 000 rows to ~400.

  Caveat, stated because it is a real trade-off: the vertex form thins the
  `metric` column too, so the bottom panel becomes sparse. If the dashboard
  wants a smooth ranked-metric panel, add a uniform grid of ~2 000 extra
  non-hit ranks per set — cheap, and it costs the losslessness of nothing since
  those ranks lie on the segments already.

## Catalog binding

There is **no `gsea` folder under `depictio/catalog/` today** (checked: 34 tool
folders, `deseq2` and `salmon` among them, no `gsea`). The output belongs in a
new one, shaped like `depictio/catalog/deseq2/`:

```
depictio/catalog/gsea/
  module.yaml          # id: gsea, nf_core_url: …/modules/nf-core/gsea/gsea
  running_score.yaml   # this output + its renders_as
  running_score.py     # the recipe
  running_score.tsv    # fixture for the catalog preview
  report.yaml/.py/.tsv # companion: gsea_report_for_*.tsv -> kind: enrichment
```

`module.yaml` is not optional paperwork: a catalog folder holding recipes but
no `module.yaml` breaks `load_catalog_entries` for the whole repo, not just for
this tool.

Sketch of `running_score.yaml`, following `depictio/catalog/deseq2/results.yaml`:

```yaml
id: gsea_running_score
name: GSEA running enrichment score
mode: differential
description: >-
  The weighted KS walk along the ranked gene list, one row per (gene set, rank),
  with the hit flag and the ranking metric beside it.
find:
  path_glob: "**/gene_sets_*.tsv"
  path_glob_alt: ["**/*ranked_gene_list*.tsv"]
recipe: gsea/running_score.py
fixture: running_score.tsv
renders_as:
  - id: running_score
    component: advanced_viz
    kind: gsea_running_score
    roles: {gene_set: gene_set, rank: rank, running_es: running_es}
```

Note what is **not** in that `roles` map: `member` and `metric` cannot be bound
from the catalog today — see below.

## Shared edits this kind needs (owned elsewhere)

1. **`AdvancedVizDispatch.tsx`** — the import and the `RENDERERS` entry. Until
   every model kind has a dispatch entry,
   `test_every_dispatched_kind_has_a_model_and_a_source` fails, since it
   asserts the two sets are equal.
2. ~~**`api.ts`** — `'gsea_running_score'` added to the `AdvancedVizKind`
   union.~~ Already landed; the renderer sends the kind as a plain typed
   constant. If that entry ever goes away the type-check fails loudly, which is
   the behaviour to keep — omitting the kind on the wire would silently make
   the server fall back to a uniform sample.
3. **`schemas.py`, `_OPTIONAL_ROLES`** — no entry for this kind, so
   `role_dtype_specs("gsea_running_score")` returns only the three required
   roles and `_allowed_roles` rejects `member` / `metric`. Consequences: the
   builder's binding panel never offers them, and a catalog `renders_as` that
   binds them is rejected. Needed: `{"member": …, "metric": _NUMERIC}` — and
   there is no boolean dtype constant in that module yet (`_INT`, `_FLOAT`,
   `_NUMERIC`, `_STRING` only), so `member` needs a new
   `_BOOLEAN = frozenset({"Boolean"})` beside them.
4. **`schemas.py`, `KIND_METADATA`** — no entry, so the kind is absent from
   `GET /advanced_viz/kinds` and from the Tool Studio snapshot, i.e. invisible
   in the builder's kind picker. Needs a label, a one-line description and an
   icon; `category: "tool"` fits, since GSEA computes a statistic before
   plotting it.
5. **`schemas.py`, `_ROLE_DESCRIPTIONS`** — a flat role→text map shared across
   kinds, so two of its entries read wrong here: `rank` is described as
   "Taxonomic rank / level (e.g. Phylum, Genus)" (stacked_taxonomy's meaning)
   and `metric` as "Diversity or summary metric value" (rarefaction's).
   `gene_set`, `running_es` and `member` have no description at all. Fixing the
   two collisions properly means keying descriptions by (kind, role); adding
   the three missing ones is free.

### Missing model fields

`GseaRunningScoreConfig` has no field for three controls the renderer offers,
which is why they are local state:

| Wanted field   | Type   | Default    | For                                      |
| -------------- | ------ | ---------- | ---------------------------------------- |
| `facet_sets`   | `bool` | `False`    | one panel per gene set vs all overlaid   |
| `show_hits`    | `bool` | `True`     | the hit-rug panel                        |
| `show_metric`  | `bool` | `True`     | the ranked-metric panel                  |

Nothing is broken without them; the settings are simply forgotten on remount,
and a dashboard cannot author a faceted GSEA plot — only a viewer can switch to
one by hand.
