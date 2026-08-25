# Catalog CLI smoke

A small project that reaches the catalog picker the way a real user's does:
`depictio-cli run` over staged pipeline output, with the recipes executed by the
CLI rather than shipped pre-computed.

## Why it exists next to `catalog_conformance`

`depictio/projects/init/catalog_conformance/` covers every catalog output, but it
is seeded by `db_init` and each of its recipe collections is the recipe's *result*
copied in as a seed file (`transform.materialized = true`). Nothing in it runs the
CLI, the recipe engine, or a `dc_ref` chain, so a recipe whose input has moved,
or whose output no longer carries the columns its catalog render binds, stays
invisible there.

This project makes the opposite trade: six collections, but every path a
collection can take to the matcher is real.

| Collection | Lane | Recipe source |
| --- | --- | --- |
| `taxonomy_rel_abundance` | recipe | single file (`qiime2/rel_abundance_tables/rel-table-2.tsv`) |
| `bray_curtis_canonical` | recipe | `dc_ref` on the collection above |
| `taxonomy_composition` | recipe | single file (`qiime2/barplot/level-2.csv`) |
| `variants_long` | recipe | glob (`variants/*/variants_long_table.csv`) |
| `pangolin_lineages` | recipe | glob over the per-sample Pangolin CSVs |
| `mosdepth_amplicon_coverage` | raw | none; matched on the scanned file's path |

Four tools (QIIME 2, iVar, Pangolin, mosdepth), six catalog outputs, thirteen
renders offered by the picker.

## Data

`run_1/` holds what the pipelines would have written, derived from the catalog's
own fixtures by `scripts/generate_fixtures.py`. Regenerate with:

```bash
uv run python -m depictio.projects.test.catalog_cli_smoke.scripts.generate_fixtures
```

The two tool families use different sample universes (`SRR*` for 16S, `SAMPLE_*`
for the viral amplicon data) because their catalog fixtures do. Nothing joins
across them.

## Running it

Paths in `project.yaml` are repo-relative, so run from the repository root.

Pick the CLI config **before** anything else. `~/.depictio/CLI.yaml` points at the
main checkout's port; every worktree runs its own API on the port in its
`.env.instance`, and pointing the default config at a worktree fails on step 1
with a bare `Connection refused`. Derive the per-worktree config with the
`/import-template` skill's snippet, or check which one matches:

```bash
grep api_base_url ~/.depictio/CLI*.yaml
grep FASTAPI_PORT .env.instance
```

```bash
source depictio/cli/.venv/bin/activate
CLI_CONFIG=~/.depictio/CLI.yaml   # or ~/.depictio/CLI.<INSTANCE_ID>.yaml in a worktree

depictio-cli run \
  --CLI-config-path "$CLI_CONFIG" \
  --project-config-path depictio/projects/test/catalog_cli_smoke/project.yaml \
  --overwrite --update-config

depictio-cli dashboard import \
  depictio/projects/test/catalog_cli_smoke/dashboards/overview.yaml \
  --config "$CLI_CONFIG" --overwrite
```

Re-running is the normal case here (you edit a recipe or a collection and want
to see it again), so all three flags are on by default:

- `--overwrite` reprocesses a workflow that already exists instead of skipping
  it. Without it the second run leaves the old delta tables in place, and a
  recipe change appears to have done nothing.
- `--update-config` pushes the resolved `project.yaml` back to the server. A DC
  added or retagged here only reaches the catalog picker through this flag: the
  compose endpoint matches against the *stored* project document, not the file.
- `--overwrite` on `dashboard import` updates the existing board rather than
  failing on the duplicate title.

Then open the project, add a component, and the picker's Catalog tab should list
the four tools above.

## Checking it without a server

```bash
# what the catalog recognises on disk
depictio-cli dev catalog match depictio/projects/test/catalog_cli_smoke/run_1

# run one recipe over the staged files and validate its output schema
depictio-cli dev recipe run ivar/variants_long.py \
  --data-dir depictio/projects/test/catalog_cli_smoke/run_1

# every recipe, the compose match, and the dashboard's bindings
uv run pytest depictio/tests/catalog/test_cli_smoke_project.py -q
```

The test suite is the part that runs in CI. It executes every recipe against the
staged files, matches the collections the way the compose endpoint does, and
checks the dashboard only draws renders the catalog actually offers on columns the
computed frames actually have.
