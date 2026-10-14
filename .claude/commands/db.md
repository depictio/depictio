# Database Helper

Inspect MongoDB for the dev stack. Default URL `localhost:27018/depictioDB` unless `.env` / `.env.instance` says otherwise (a worktree has its own `MONGO_PORT` in `.env.instance`).

## Rules

- Read-only by default: `find`, `countDocuments`, `getIndexes`, `getCollectionNames`. Show the query before running it.
- Never drop, delete or update without explicit confirmation. Prefer the CLI or API for changes (`/reseed` for reference projects).
- Collection names come from `settings.mongodb.collections` and are bound in `depictio/api/v1/db.py`; read that file rather than trusting a list here. `dashboards` holds one document per tab; history is in `dashboard_versions`.

## Commands

```bash
mongosh "mongodb://localhost:27018/depictioDB" --quiet --eval 'db.getCollectionNames()'
mongosh "mongodb://localhost:27018/depictioDB" --quiet --eval 'db.projects.countDocuments()'
mongosh "mongodb://localhost:27018/depictioDB" --quiet --eval 'db.users.find({}, {password: 0}).limit(5).toArray()'
```

Usage: `/db collections`, `/db count <collection>`, `/db query <collection> <filter>`, `/db indexes <collection>`.
Never print password hashes or tokens (project them out).

$ARGUMENTS
