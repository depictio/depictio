# nf-core template versioning — monitoring, latest-resolution, bump

How depictio tracks nf-core pipeline releases for its bundled template projects
(`depictio/projects/nf-core/<pipeline>/<version>/`), what resolves the "current"
version automatically, and the one manual step left: shipping a new version.

## TL;DR — do I trigger anything manually?

| Step | Trigger | What it does |
| --- | --- | --- |
| Release detection + drift report | **Automatic** — `nfcore-release-monitor.yaml`, Mondays 06:00 UTC (or `workflow_dispatch`) | Detects newer nf-core releases, validates our recipes against that release's AWS megatest, opens one draft PR per pipeline with the drift report |
| Version bump | **Manual** — `python scripts/bump_template_version.py` | Creates the new version directory from the current latest; you then refresh demo data / seeds per its checklist |
| Seeding, CLI, CI, docs picking up the new version | **Automatic** — latest-resolution (below) | Nothing to edit: highest version directory wins everywhere |

The bump is manual on purpose: bundled demo data must come from a real run of
the new release, and dashboard seeds may need regeneration — neither can be
guessed by CI. Everything around it is automated.

## Layout

```
depictio/projects/nf-core/<pipeline>/
├── recipes/                  # shared across versions (version-specific overrides possible)
├── 2.14.0/                   # legacy version (kept for backward-compat tests)
└── 2.16.0/                   # ← current latest: highest numeric dir wins
    ├── template.yaml         # template_id, variables, DCs, conditionals
    ├── dashboards/*.yaml     # dashboard definitions
    ├── .db_seeds/*.json      # generated seeds — what fresh deployments actually load
    └── …                     # bundled demo data (TSVs, multiqc/, input/…)
```

## Latest-resolution (what makes the bump zero-config)

A "latest" is the highest numeric version directory containing a `template.yaml`
(numeric sort: `2.9.0 < 2.16.0`). It is resolved independently by:

- **Seeding** — `ReferenceDatasetRegistry.DATASET_PATHS` stores version-less
  paths (`nf-core/ampliseq`); `resolve_dataset_rel_path()` appends the latest
  version at seed time (project + dashboard seeds in `db_init.py`).
- **CLI** — `depictio-cli run --template nf-core/ampliseq/latest` (or the
  version-less `nf-core/ampliseq`) resolves via `locate_template()`. Explicit
  versions still work and are stored as-is in the project's template origin.
- **CI** (`depictio-ci.yaml`) — offline template validation loops over
  `projects/nf-core/ampliseq/*/template.yaml`; the full-pipeline job runs
  `--template nf-core/ampliseq/latest`; the viralrecon bundled-data check picks
  its version dir with `sort -V`.
- **Docs** — `depictio/dev_scripts/gen_template_docs.py` emits a
  `<pipeline>-latest.md` alias partial next to the per-version partials;
  narrative depictio-docs pages should include the alias
  (`--8<-- ".../_generated/ampliseq-latest.md"`) so they never track versions.
- **.gitignore** — the nf-core data allow-list rules wildcard the version
  segment (`!depictio/projects/nf-core/ampliseq/*/*.tsv`…), so a new version
  dir's data files are committable without touching ignore rules.

Guard rails:

- `test_reference_seed_dashboards.py::test_versioned_dataset_paths_resolve_to_latest_template`
  fails if the resolved latest version ships without `.db_seeds/dashboard_*.json`
  (an incomplete drop would otherwise silently seed zero dashboards).
- `optional: true` DCs (route-gated, e.g. ampliseq multiregion/SIDLE) are
  reported by the monitor as "optional route not exercised by megatest" — never
  as drift, since the official megatest only runs the default profile.

## Release monitoring (automatic)

`.github/workflows/nfcore-release-monitor.yaml` runs `scripts/nfcore_monitor.py`:

1. `check` — compares our highest shipped version per pipeline against the
   latest nf-core GitHub release.
2. `report` — for each pipeline with an update, validates the current template
   against the new release's AWS megatest results (anonymous S3) in three
   layers: source-path existence, actual recipe execution
   (`transform()` + `EXPECTED_SCHEMA`), and `depictio dev catalog validate`.
3. Opens a draft PR per pipeline titled
   `nf-core/<pipeline> <version> — megatest: ✅ valid | ⚠️ N issue(s)` whose body
   is the drift report, including the ready-to-run bump command under
   "Next steps".

Manual dry-run for any pipeline: Actions → "nf-core release monitor" →
`workflow_dispatch` with `force_report_pipeline`.

## Shipping a new template version (manual)

```bash
python scripts/bump_template_version.py --pipeline ampliseq --new-version 2.18.0
# --dry-run to preview; --from-version to copy from a non-latest source
```

The script copies the current latest version directory, rewrites the version
string in all text files (template_id, headers, helper scripts — binaries are
copied verbatim), and refuses existing targets or versions that would not sort
above the source. Then follow its printed checklist:

1. **Refresh demo data** from a real run of the new release (the copied
   TSV/multiqc files still hold the old release's outputs) —
   `download_test_data.sh` / `generate_validation_runs.sh` in the version dir.
2. **Drift-check**: `python scripts/nfcore_monitor.py report --pipeline <p>` and
   fix any moved/renamed recipe source paths.
3. **Reseed if dashboards changed**: `generate_seeds.sh` +
   `remap_seeds_to_static_ids.py` — fresh deployments load `.db_seeds/*.json`,
   not YAML.
4. **Regenerate docs partials**: `python -m depictio.dev_scripts.gen_template_docs`
   (also refreshes `<pipeline>-latest.md`).
5. **Guard tests**:
   `uv run pytest depictio/tests/api/v1/test_reference_seed_dashboards.py depictio/tests/unit/test_nfcore_monitor.py -q`.

Merging that is the whole rollout: the next fresh deployment seeds from the new
version, `--template …/latest` picks it up, CI validates it, and the docs alias
points at it. Old version directories stay in place for reproducibility
(`--template nf-core/ampliseq/2.14.0` keeps working).
