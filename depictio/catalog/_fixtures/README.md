# Catalog fixtures

Small, committed, **module-keyed** sample files — one per output, named by its
`id` (e.g. `qiime2_alpha_diversity.tsv`, `ivar_variants_long.tsv`). Each is a
trimmed sample of that output's **bindable shape** (the columns a render binds
to).

They are **pipeline-agnostic** (they live with the catalog, not under a specific
`projects/<pipeline>/<version>/`), so they serve two purposes:

1. **Validation (CI, Level-3):** `depictio catalog validate` grounds every
   render's bound columns against the fixture's real columns.
2. **Preview (future):** load the fixture → render the actual component
   (advanced viz / figure / card) on real data.

Reference one from an output with `fixture: <filename>`. To (re)generate, trim
the corresponding canonical recipe output (e.g.
`head -n 31 projects/nf-core/<pipeline>/<version>/<name>.tsv`).
