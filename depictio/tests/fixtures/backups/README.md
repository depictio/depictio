# Backup fixtures — backward-compatibility guard

These are **frozen, real backup files** used by
`depictio/tests/cli/utils/test_backward_compat_backup.py` to ensure that a
backup produced by an older Depictio release still validates against the
**current** Pydantic models. If a model change breaks deserialization of an old
backup, the test fails and names the offending collection/document — preventing
a destructive restore (`delete_many` + `insert_many`) from silently dropping
data on an upgraded deployment.

## Supported-version policy: v1.0.0 onwards only

`1.0.0` is the baseline (Dash → React migration complete). Backups produced by
**pre-1.0.0** versions are explicitly **out of scope** and must not be added
here. Fixtures are named `depictio_backup_v<MAJOR>.<MINOR>.<PATCH>.json` with
`<version> >= 1.0.0`.

## Adding a fixture for a new release

When cutting a release, generate a real backup against a freshly seeded
deployment and commit it here:

```bash
# Against a running, freshly seeded deployment (iris/penguins/ampliseq):
depictio-cli backup create --CLI-config-path admin_config.yaml
# then copy the produced depictio_backup_<id>.json and rename it:
#   depictio/tests/fixtures/backups/depictio_backup_v<version>.json
```

Keep fixtures small — trimming bulky collections (e.g. `files`, `runs`) to a
representative handful is fine; the goal is schema coverage, not data volume.
The `dashboards` collection is the highest-value one to keep populated because
it contains the most complex, fastest-evolving models (advanced viz, etc.).

The committed baseline fixture (`depictio_backup_v1.0.1.json`) was built from the
committed reference dashboard seeds
(`depictio/projects/init/{iris,penguins}/.db_seeds/dashboard.json`, converted
from BSON `$oid` form to the plain-string id form a real backup stores) plus a
minimal admin user and the default groups. Every document validates via
`validate_backup_file` against the v1.0.1 models.
