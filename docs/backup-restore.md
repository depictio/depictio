# Backup and restore

Depictio stores state in two independent places, and they are backed up by two
independent mechanisms. Reading this page as an operator, the one thing to take
away is:

> **Admin > Backups covers the database, not your data.**
> Delta tables in S3/MinIO are a separate backup, with a separate procedure, and
> they are never restored by the admin UI.

## What lives where

| Store | Holds | Covered by Admin > Backups |
| --- | --- | --- |
| MongoDB | users, groups, projects, workflows, dashboards, data collection definitions, file records, delta table *locations*, runs, instance settings, branding assets | Yes |
| S3 / MinIO | the Delta Lake tables themselves, uploaded images, MultiQC inputs | **No** |

A MongoDB backup records that a data collection's table lives at
`s3://depictio-bucket/<data_collection_id>/`. It does not contain a single row of
that table. Restoring the database therefore restores the *pointers*; whether
they resolve depends entirely on the object store being in a matching state.

## Database backups (Admin > Backups)

### What is included

Eleven collections: `users`, `projects`, `dashboards`, `data_collections`,
`workflows`, `files`, `deltatables`, `runs`, `groups`, `instance_settings`,
`branding_assets`.

Deliberately excluded:

- **`tokens`** — restoring them would create a circular dependency, and leaving
  them out is why an admin session survives a restore performed from the UI.
- **Temporary users** and the dashboards they own.
- **Derived or self-expiring collections** — `jbrowse`, `multiqc`,
  `multiqc_prerender` are regenerated from source data; `task_events`,
  `app_logs` and `telemetry` expire by design.
- **`ingestion_runs`** — real audit/lineage data with no TTL. This is a known
  gap, not a decision that it should never be backed up.

A `check_backup_collections_coverage` test fails CI when a new collection is
added to settings without being classified, so this list cannot silently drift.

### Backup files

Each backup is a single JSON document written to `DEPICTIO_BACKUP_BACKUP_DIR`
(`backups/` by default), named `depictio_backup_<YYYYMMDD_HHMMSS>.json`, with a
`.sha256` sidecar written alongside it. Restore verifies the digest: a missing
sidecar (legacy backups) can be waived with `allow_unverified`, but a *mismatch*
is never bypassable.

Because the id is the creation timestamp, retention reads a backup's age from
its filename rather than its mtime, which does not survive a volume restore or
an rsync.

### Scheduling and retention

Scheduled backups are **off by default**: a snapshot is the size of the whole
database, and a deployment that has not sized its backup volume should not start
filling it on upgrade.

The schedule is read from MongoDB on every tick, so changes made in the UI apply
to every API worker within a few minutes without a restart. Every worker runs
the loop; the due time is claimed with a single conditional MongoDB update, so
exactly one worker takes each backup.

Retention offers two modes in the UI:

- **Keep for a fixed time** — delete anything older than N days. `0` keeps
  everything forever.
- **Smart retention** — grandfather-father-son thinning: keep every backup for N
  days, then one per ISO week for 4 weeks, then one per calendar month for 12
  months. Bounded output from unbounded input.

Pruning runs after every backup, scheduled or manual. Nothing else prunes the
directory, and **there is no delete action**: retention is currently the only
way a backup is ever removed.

### Configuration

Environment variables supply the *defaults*; anything saved from the Backups tab
overrides them from then on, so an admin's click is never silently reverted on
the next restart.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DEPICTIO_BACKUP_AUTO_BACKUP_ENABLED` | `false` | Run scheduled backups |
| `DEPICTIO_BACKUP_AUTO_BACKUP_INTERVAL_HOURS` | `24` | Hours between scheduled backups |
| `DEPICTIO_BACKUP_BACKUP_FILE_RETENTION_DAYS` | `30` | Keep every backup for this long; `0` keeps forever |
| `DEPICTIO_BACKUP_BACKUP_RETENTION_WEEKLY_WEEKS` | `0` | Weekly tier length; `0` disables it |
| `DEPICTIO_BACKUP_BACKUP_RETENTION_MONTHLY_MONTHS` | `0` | Monthly tier length; `0` disables it |

With both tiers at `0`, retention is a plain age cutoff.

### Restoring

Restore is destructive: each selected collection is emptied and refilled. Before
anything is touched, the backup is validated against the current Pydantic models
and the restore is refused if any document in a selected collection fails, unless
`skip_validation` is set. A failed insert rolls that collection back to its
previous contents.

The list marks the backup a deployment's data was last restored from, so it is
possible to tell which snapshot the live data came from.

Backward compatibility is guarded two ways: frozen backup fixtures from v1.0.0
onward are validated against current models on every run, and a weekly CI job
boots the previous release, takes a real backup, and restores it into current
code. Versions before v1.0.0 are out of scope.

## Data backups (S3 / Delta Lake)

**None of the above touches your data.** There are three ways to cover it, in
descending order of what we would recommend.

### 1. Object store replication (recommended for production)

Let the object store do it. S3 bucket versioning plus Cross-Region Replication,
or MinIO's `mc mirror` / site replication, gives point-in-time recovery of the
Delta tables without Depictio being in the path at all. Delta Lake is
append-structured, so object versioning composes well with it.

This is the only option that scales to a real dataset, and the only one that
protects you if the Depictio deployment itself is lost.

### 2. The CLI, with `--include-s3-data`

```bash
depictio-cli backup create --include-s3-data --s3-backup-prefix backup
```

This takes the database backup *and* copies the Delta tables, driven by
`DEPICTIO_BACKUP_S3_BACKUP_STRATEGY`:

| Strategy | Effect |
| --- | --- |
| `s3_to_s3` (default) | Copy tables into a second bucket (`DEPICTIO_BACKUP_BACKUP_S3_BUCKET`), configured by `DEPICTIO_BACKUP_BACKUP_S3_ENDPOINT_URL` / `_ACCESS_KEY` / `_SECRET_KEY` / `_REGION`, enabled with `DEPICTIO_BACKUP_BACKUP_S3_ENABLED=true` |
| `local` | Copy tables to `DEPICTIO_BACKUP_S3_LOCAL_BACKUP_DIR` on the server, optionally gzipped via `DEPICTIO_BACKUP_COMPRESS_LOCAL_BACKUPS` |
| `both` | Both of the above |

The same flag exists on the API's `POST /backup/create`. It is **not** exposed
in the admin UI, on purpose: it needs a second bucket and credentials that are
deployment configuration, and it runs synchronously inside the request.

### 3. Snapshot the volume

For single-node MinIO deployments, a filesystem or block-device snapshot of the
MinIO data volume, taken alongside a database backup, is a coherent pair.

### Restoring data: manual

There is **no S3 restore path in Depictio.** `S3BackupStrategyManager` copies
tables out; nothing copies them back. Recovering data means restoring the bucket
yourself, with `mc mirror`, `aws s3 sync`, object-version rollback, or a volume
snapshot, and then restoring the matching database backup.

## Ordering, and one hazard worth knowing

To recover a deployment consistently:

1. Restore the object store to the state it had at the time of the database
   backup you intend to use.
2. Restore the database backup from Admin > Backups.
3. Confirm dashboards render before letting users back in.

**Restoring the database alone can cause data loss on S3.**
`periodic_cleanup_orphaned_s3_files` runs on a timer and deletes bucket prefixes
that no live data collection references. After a restore rewinds the database,
every Delta table ingested *after* that snapshot is an orphan by that
definition, and the next cleanup pass deletes it permanently. The task's safety
check only aborts when *all* prefixes look orphaned, so a partial rewind passes
straight through it.

Until that interaction is guarded, treat a database restore on a deployment with
live data as an operation that requires the object store to be rewound to match,
or the cleanup task to be disabled first.

## Related

- `depictio/api/v1/endpoints/backup_endpoints/routes.py` — endpoints, retention, restore gate
- `depictio/api/v1/tasks/backup_tasks.py` — the scheduler loop
- `depictio/api/v1/backup_strategy_manager.py` — S3 copy strategies
- `depictio/cli/cli/commands/backup.py` — `depictio-cli backup create|list|validate|restore`, plus the hidden maintainer command `depictio-cli dev check-coverage`
- `depictio/dev_scripts/k8s_mongo_backup.sh` — mongodump straight from a Kubernetes pod
