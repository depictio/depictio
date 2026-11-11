# penguins_publish

The penguins demo, set up to try **Publish to...** (project migration, #1303) between
two instances. It has its own ids and names, so it can sit next to the seeded penguins
project, and it carries what a push has to move: two Delta tables and their join, a
two-tab dashboard, comment threads with an annotation, and a dashboard logo.

Not auto-seeded: no `.db_seeds/`, nothing here is loaded at boot.

## Build it on the publishing instance

`project.yaml` holds the container path of the data (`/app/depictio/projects/init/...`).
Running from a host, point `locations` at this folder's `data/` first (the same rewrite
as `penguins_versioned/rebuild_demo.py:write_host_project_yaml`), then:

```bash
python -m depictio.cli ingest --project-config-path <project.yaml> --server <cli config>
python -m depictio.cli dashboard import dashboards/species_analysis.yaml --server <cli config>
python -m depictio.cli dashboard import dashboards/island_season.yaml --server <cli config>   # child tab: parent first
DEPICTIO_TOKEN=<access token> python seed_comments.py --api-url <backend URL>
```

Re-ingesting duplicates dashboards, so wipe first or use `dashboard import --overwrite`.
`seed_comments.py` can be rerun: threads carry a `dedupe_key`, the logo is overwritten.

## What to check after a push

On the receiving instance (the checklist is also the "Publish check" section of the
dashboard itself):

1. The project is locked (read-only) and both tabs are there.
2. The cards and figures render, so the tables were copied rather than linked.
3. Five comment threads: one on a card, two on the scatter plot (one with a published
   annotation), one resolved on the box plot, one on the tab itself, plus the reply.
4. The dashboard logo is shown.
5. Edit a component on the source and publish again with the same invitation: the
   project is updated, not duplicated.

Known gaps of the feature, so not failures here: comment authors keep their source user
ids, dashboard version history is not carried, and the lock is an API-level guarantee.
