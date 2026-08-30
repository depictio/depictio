# nf-core megatests showcase

Ten dashboards binding depictio's advanced visualisations to **real** nf-core
pipeline outputs, as opposed to the synthetic fixtures of
`../advanced_viz_showcase`. Sources: `differentialabundance`, `rnaseq`,
`viralrecon`, `ampliseq` and `taxprofiler`, pulled from the public
`s3://nf-core-awsmegatests/` bucket.

## This project is not seeded on a fresh deployment

Deliberately. Its fixtures live under `data/`, which is gitignored and not
mirrored anywhere the API can reach at boot. Registering it in
`db_init.dashboards_config` would create a project whose data collections
resolve to nothing, so every tile would 404 on every new deployment. It is
uploaded by hand instead, into an instance that already has the fixtures.

`advanced_viz_showcase` is the one that ships: its fixtures are committed.

## Layout

| path | role |
| --- | --- |
| `project.yaml` | project / workflow / data-collection ids and column descriptions — the single source of truth for every ObjectId here |
| `dashboards/*.yaml` | one lite YAML per tab; the authoring surface |
| `.db_seeds/dashboard_*.json` | generated, committed, uploaded by `scripts/upload.sh` |
| `scripts/preprocess_fixtures.py` | turns raw pipeline outputs into the TSVs the DCs scan |
| `scripts/generate_seeds.py` | thin wrapper over `depictio.dev_scripts.generate_dashboard_seeds` |
| `scripts/upload.sh` | CLI scan inside the API container, then `mongoimport` of the seeds |

## Workflow

```bash
# 1. fetch + reshape the fixtures (needs AWS CLI; writes data/, gitignored)
python depictio/projects/init/nfcore_megatests_showcase/scripts/preprocess_fixtures.py

# 2. regenerate the seeds after editing any dashboards/*.yaml
venv/bin/python -m depictio.dev_scripts.generate_dashboard_seeds nfcore_megatests_showcase

# 3. register the project and upsert the dashboards into a running instance
bash depictio/projects/init/nfcore_megatests_showcase/scripts/upload.sh
```

Never edit `.db_seeds/*.json` by hand: step 2 overwrites them, and the YAML is
what gets reviewed.

## Tab family

`volcano` is the main tab; the other nine carry `parent_dashboard_tag: volcano`
and are resolved into one tab strip through `parent_dashboard_id`. Before this
was fixed the nine pointed at the *project* id, which no dashboard document
carries, so every tab rendered as a family of one.
