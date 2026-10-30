# depictio all-in-one image (draft)

One image holding the whole single-user stack that `depictio local up` runs:
MongoDB, Redis and SeaweedFS (the same conda-forge builds), the FastAPI API serving
the built viewer, and the Celery worker. Its only state is one mounted folder, a
**depictio local home**: the `depictio/` folder the Nextflow module writes
(`mongo/`, `s3/`, `keys/`, `cli/`, `secrets.json`, `.depictio-local-home`, ...).

Use case: reopen a pipeline's `results/depictio/` and browse its dashboards with a
single `docker run` or `apptainer run`. No compose file, no install.

| File | Role |
| --- | --- |
| `Dockerfile` | 3 stages: viewer bundles (node), conda-forge services (py-rattler), runtime |
| `entrypoint.py` | PID 1's child: starts the stack on `/data`, supervises it, stops it in order |
| `install_services.py` | build step: installs `CONDA_SPECS` from `local_stack.py` into `/opt/depictio-services`, prunes it |

## Build

The build context is the root of a depictio checkout:

```bash
cd depictio                                    # the repository root
docker build -f docker-images/allinone/Dockerfile -t depictio-allinone:1.19.3 .

# both platforms (arm64 needs ARMv8.2-A for mongod: Graviton, Apple silicon; not a Pi 4)
docker buildx build --platform linux/amd64,linux/arm64 \
  -f docker-images/allinone/Dockerfile -t ghcr.io/depictio/depictio-allinone:1.19.3 --push .

# Apptainer / Singularity image, from the local Docker daemon or a registry
apptainer build depictio-allinone.sif docker-daemon://depictio-allinone:1.19.3
apptainer build depictio-allinone.sif docker://ghcr.io/depictio/depictio-allinone:1.19.3
```

Tag the image with the depictio version the pipeline used: the image must run the
MongoDB series that wrote the data (see *MongoDB versions*).

## Run on a pipeline result

```bash
# Docker. 127.0.0.1: single-user mode has no login, whoever reaches the port is admin.
docker run --rm --name depictio -p 127.0.0.1:8058:8058 \
  -v "$PWD/results/depictio:/data" depictio-allinone:1.19.3
# -> open http://localhost:8058/dashboards

# Apptainer (HPC). --containall gives the run a private /tmp and PID namespace.
apptainer run --containall --bind "$PWD/results/depictio:/data" depictio-allinone.sif
# -> on the node: http://127.0.0.1:8058/dashboards
#    from a laptop: ssh -L 8058:127.0.0.1:8058 <node>, then http://localhost:8058/dashboards
```

Mount the `depictio/` folder itself, not `results/`: the entrypoint says so if you
mount its parent.

What the user sees (`docker logs`, or the terminal):

```
[depictio-allinone] Running as uid 1000:1000, the owner of /data
[depictio-allinone] Existing depictio home at /data
[depictio-allinone] MongoDB 8.0.23 (data written by 8.0.23)
[depictio-allinone] Starting MongoDB, Redis, SeaweedFS, the API and the worker (logs in /data/logs)
[depictio-allinone] Ready: http://localhost:8058/dashboards  (API on 0.0.0.0:8058)
[depictio-allinone] Stop with Ctrl-C or `docker stop -t 60 <container>`
```

Startup takes ~10-60 s (the API's own startup dominates). The service logs go to
`/data/logs/{mongo,redis,s3,api,worker}.log`, as with `depictio local up`; on a
failed start their last lines are printed.

**Stop**: Ctrl-C, or `docker stop -t 60 depictio`. The worker and API stop first,
then SeaweedFS and Redis, MongoDB last; each gets SIGTERM, then SIGKILL after 10 /
15 / 30 s. Measured: ~6 s, mongod `exitCode 0` with an empty `mongod.lock` (a clean
WiredTiger checkpoint). Docker's default `-t 10` can cut a slow MongoDB shutdown;
WiredTiger's journal then recovers on the next start, but use `-t 60`.

**Add more data** to the running stack, from inside it (the CLI is in the image and
`--server local` reads `/data/cli/admin_config.yaml`):

```bash
docker exec -it -u "$(id -u):$(id -g)" depictio \
  depictio ingest /results/... --server local   # mount the results at /results too
```

Any command other than `serve`/`health` is exec'ed, e.g.
`docker run --rm depictio-allinone depictio --help`.

### Settings (environment variables)

| Variable | Default | Effect |
| --- | --- | --- |
| `DEPICTIO_PORT` | `8058` (Docker), previous/free port (Apptainer) | API + viewer port inside the container |
| `DEPICTIO_PUBLISHED_PORT` | = `DEPICTIO_PORT` | only the port printed in the "Ready" URL (`-p 9000:8058`) |
| `DEPICTIO_BIND_HOST` | `0.0.0.0` (Docker), `127.0.0.1` (Apptainer) | API bind address. MongoDB, Redis, S3 always stay on loopback |
| `DEPICTIO_EXAMPLES` | `none` | iris/penguins examples, seeded on a *new* home only |
| `DEPICTIO_DATA_ROOTS` | | comma-separated extra folders the web UI may read run folders from (mount them) |
| `DEPICTIO_ALLOW_ROOT` | | `1` keeps running as root instead of dropping to the owner of `/data` |
| `DEPICTIO_TELEMETRY_ENABLED` | | `false` to opt out, as for `local up` |

Apptainer passes them with `--env DEPICTIO_PORT=9058`.

## Design

**Choice: the image runs `depictio.cli.cli.local_stack` itself, in the foreground,
through a ~300-line Python entrypoint under `tini`.** It neither shells out to
`depictio local up` (option a) nor reimplements the five processes for a
supervisor (option b).

Why not (a), `depictio local up` as is:
- it daemonizes: `up` returns once the API answers, so PID 1 would be a wrapper
  polling `state.json` and calling `local down`, and nothing notices a dead service;
- it binds the API to 127.0.0.1 (hard-coded), so `-p 8058:8058` reaches nothing;
- it installs the services into `<home>/env`, i.e. ~900 MB downloaded into the
  user's results at first start (a home from the pipeline may carry an `env/` for
  another platform, or none). There is no option to point it at baked binaries.

Why not (b), supervisord/s6 running the services like the compose images:
- the five processes share an environment *derived from the home*: the S3 and
  admin passwords in `secrets.json`, the keys and CLI-config folders, the ports in
  `ports.json`. A supervisor config cannot compute it; a script would, and that
  script is `local_stack.server_env()`. Rewriting it means two definitions of a
  local home that drift apart, and a home written by one not opening in the other;
- the API's first-run/reopen logic (admin token, rebuilt CLI config) and the
  startup ordering with readiness probes are already in `local_stack`.

So the entrypoint imports `local_stack` and reuses, unchanged: `claim_home`,
`ensure_dirs`, `load_secrets`, `load_ports`/`pick_ports`, `server_env`,
`start_services` (spawn order, readiness probes, SeaweedFS port flags, cleanup of a
failed start), `wait_for_api` (incl. rebuilding a missing CLI config),
`check_alive`, `lock_for_startup`, `State`. It adds what `local up` cannot do yet:

| Added in the entrypoint | Mechanism |
| --- | --- |
| foreground supervision | polls the five `Popen`s; a dead one stops all and exits 1 (`--restart` can retry) |
| ordered shutdown on SIGTERM/SIGINT/SIGHUP | worker+API, then S3+Redis, then MongoDB; further signals ignored meanwhile |
| baked services | `Paths.env` -> `/opt/depictio-services` (patched property) |
| API bind host | wraps `local_stack.spawn` to replace `--host 127.0.0.1`; asserts the command shape, so a depictio change fails loudly |
| run as the data's owner | as root, `setgid/setuid` to the owner of `/data` (like the mongo/postgres images) |
| writable `HOME` for any uid | `/tmp/depictio-home-<uid>` when `HOME` is unset, `/`, or not writable |
| home lock for the whole run | `local up` holds `.up.lock` during startup only; here a second container, or a host `local up`/`wipe`, fails fast |
| per-user SeaweedFS socket names | see *Shared /tmp* below |

Trade-offs: the two monkeypatches (`Paths.env`, `spawn`) tie the entrypoint to
`local_stack` internals, and `start_services`/`_signals_interrupt` are not a public
API. The image and the module come from the same commit, and the `spawn` patch
fails loudly; the proper fix is the depictio changes below, which reduce the
entrypoint to a root drop plus `exec depictio local up --foreground ...`.

### Details

- **Arbitrary UID.** `docker run` without `-u` starts as root and drops to the owner
  of `/data`, so files stay the user's (validated: every file of the home stayed
  owned by the data's uid). `-u $(id -u):$(id -g)` and Apptainer run as that uid
  directly; no passwd entry is needed. The image itself is never written: bytecode
  is compiled at build time, the API's static folders exist, and caches/HOME go to
  `/tmp`. A home the uid cannot read/write is refused with a hint (pipeline outputs
  are `0700`: open them as the user who ran the pipeline).
- **First run vs. reopen.** Empty `/data`: it becomes a home (marker, folders,
  `secrets.json` with new passwords); the API creates the admin, the signing keys
  and `cli/admin_config.yaml`; no examples unless `DEPICTIO_EXAMPLES`. Existing
  home: the stored passwords, keys and ports are reused, so the stored S3 objects
  and tokens stay valid; a missing CLI config is rewritten through the API; an
  unparsable one is refused before anything starts. A folder that is neither empty
  nor a home is refused (`claim_home`). Like `local up`, a run rewrites
  `api_base_url` in the CLI config to its own port.
- **MongoDB versions.** The services stage installs `CONDA_SPECS` read from
  `local_stack.py` (`mongodb 8.0.*`, today 8.0.23), so the image runs the series of
  `local up` of the same version. MongoDB opens data of its own series (and the
  previous one after a feature-compatibility step), never a newer one. At start the
  entrypoint compares its mongod with `/data/env/conda-meta/mongodb-*.json` when
  the home has one and warns on a series mismatch. Pin exactly with
  `--build-arg SERVICES_SPECS="mongodb 8.0.23;redis-server 8.*;seaweedfs 4.*"`.
- **Linux 6.19+ (SERVER-121912).** The conda-forge 8.0.23 `mongod` contains the
  same check as the official image (`validateRseqKernelCompat`, the "Linux kernel
  versions 6.19 and newer" message). It only fires when tcmalloc uses per-CPU
  caches, i.e. when glibc does *not* own rseq. Unlike the official image (which sets
  `glibc.pthread.rseq=0`), this image's glibc 2.36 owns rseq by default; the image
  still sets `GLIBC_TUNABLES=glibc.pthread.rseq=1` so an inherited value cannot flip
  it. Not tested on a 6.19 kernel (the sandbox runs 6.18).
- **Shared /tmp (Apptainer).** `weed mini` puts unix sockets in `/tmp` and ignores
  `TMPDIR`. Reproduced: a `/tmp/seaweedfs-s3-9000.sock` owned by another user makes
  SeaweedFS exit at startup (`Failed to remove ... operation not permitted`). The
  entrypoint names the two sockets weed lets you name
  (`-s3.localSocket`/`-filer.localSocket=/tmp/seaweedfs-u<uid>-...`); a foreign
  stale master/volume gRPC socket was tolerated. weed saves these flags in
  `s3/mini.options`; the per-user `/tmp` names stay valid for a later host
  `local up`. `--containall` avoids the question altogether.
- **Ports under Apptainer** (host network): MongoDB/Redis/S3/weed's internal ports
  move to free ones when taken (`pick_ports`, `seaweedfs_port_flags`); the API keeps
  `DEPICTIO_PORT` if set, else the home's previous port or a free one, printed.
  MongoDB and Redis have no auth on loopback, as with `local up`: other users of a
  shared node can reach them.
- **Health check.** `HEALTHCHECK` runs `depictio-allinone health`: the API's
  `/health` must answer `healthy`, on the port in `/data/state.json`. Start period
  180 s. (OCI/Apptainer ignore it.)
- **Platforms.** linux/amd64 and linux/arm64: conda-forge builds all three services
  for both (`check_platform_supported`). The viewer stage runs on the build
  platform; the services stage on the target one (under QEMU for a cross build).
  mongod needs AVX (x86_64) / ARMv8.2-A (arm64).
- **Size (estimate, not measured).** Base ~150 MB, Python env (`--extra server`)
  ~1.6-1.8 GB (two polars runtimes ~410 MB, kaleido 220, llvmlite 170, pyarrow 160,
  playwright driver 135, deltalake 120), depictio source ~100 MB, viewer bundles
  ~30 MB, services 545 MB (measured, after pruning mongos, the Redis modules and
  headers from ~900 MB): **~2.5-2.7 GB unpacked, ~1 GB compressed**. No Chromium
  (thumbnails off): the worker image's ~450 MB browser is left out.

## Changes to depictio that would simplify this

1. `depictio local up --foreground`: stay attached, supervise, stop in order on
   SIGTERM/SIGINT/SIGHUP, exit non-zero when a service dies, hold the home lock for
   the whole run. (`supervise()`/`stop()` in `entrypoint.py` are the sketch.)
2. `--host` (or `DEPICTIO_LOCAL_BIND_HOST`) for the API; `--home` as a flag
   alongside `DEPICTIO_LOCAL_HOME`. Warn when binding beyond loopback in
   single-user mode.
3. `DEPICTIO_LOCAL_SERVICES=<prefix>`: use pre-installed binaries, never download
   into `<home>/env` (`ensure_binaries` + `Paths.env`). Also useful on air-gapped
   HPC nodes, where `local up` cannot reach conda-forge.
4. Per-user socket names for `weed mini` in `_start_services`: the stale-socket
   failure above hits `local up` on any shared node too.
5. Pass `GLIBC_TUNABLES=glibc.pthread.rseq=1` to mongod in `_start_services`
   (harmless on glibc >= 2.35, defensive against an inherited `rseq=0`).
6. Publish `start_services`/`stop_all`-style helpers as a small public API, or ship
   this entrypoint in the package (`depictio local serve`), so the image does not
   reach into private names (`_signals_interrupt`, `_stop_child`).

With 1-3 the entrypoint becomes: drop root to the owner of `/data`, then
`exec depictio local up --foreground --host 0.0.0.0 --examples none --no-open`.

Side finding, unverified: `Dockerfile.viewer` (and the catalog-preview stage of
`Dockerfile.api`) copy only `packages/` and `depictio/viewer/`, but the viewer's
icon-subset step also scans `depictio/models/components/advanced_viz/schemas.py`
and `depictio/projects/` (`VIEWER_SOURCES` in `local_stack.py`,
`scripts/generate-icon-subset.mjs`). Released bundles may therefore miss icons named
only in shipped dashboards. This Dockerfile copies both.

## What was validated, and what was not

No Docker or Podman command was run. The entrypoint was run natively with the
repository's venv, in a private mount namespace laid out as the image lays itself
out (a helper script, not committed): home bind-mounted at a fixed path, services prefix and
the whole depictio checkout **read-only**, network and PIDs shared with the host.

Validated:
- **Reopen**: a copy of an existing local home (made by `depictio local up` +
  `depictio ingest`: 4 dashboards incl. nf-core/rnaseq). `/health` healthy,
  `/dashboards` and `/dashboard/<id>` 200 with the built SPA and its assets,
  `/dashboards/list` with the admin token from the home's CLI config returns the 4
  dashboards, `/deltatables/shape/<dc>` reads a Delta table from SeaweedFS (125
  rows): the stored passwords and keys work.
- **First run** on an empty folder (secrets, keys, CLI config created), then a
  reopen of that home.
- **Identity**: started as root, dropped to the owner (uid 4242, no passwd entry,
  `HOME=/root` unwritable); started directly as uid 4242. All files stayed owned
  by 4242.
- **Shutdown**: SIGTERM steady state (~6 s, mongod exit 0, empty `mongod.lock`,
  `state.json` removed, no process left); SIGINT the same; SIGTERM during startup
  stops what was started; a SIGKILLed worker stops the stack with exit 1.
  Once, SeaweedFS did not finish within 8 s of SIGTERM and was killed (MongoDB,
  stopped last, was unaffected); the timeout is now 15 s.
- **Apptainer mode** (`APPTAINER_CONTAINER` set): API on 127.0.0.1 only, refused on
  the external address; a free/previous port picked.
- **Error paths**: parent folder mounted, foreign non-empty folder, busy port.
- **Build step** `install_services.py`: real solve + install from conda-forge
  (packages cached), prune to 545 MB, and the stack run on that prefix.
- Static checks: hadolint 2.12 clean (DL3008/DL3002 ignored with reasons),
  shellcheck 0.10 clean, ruff check + format clean.

Not validated:
- any `docker build`: the viewer stage, `uv sync` in the image, the COPY paths,
  the final size; `tini`; `HEALTHCHECK`; real `-p` port publishing; `docker stop`;
- Apptainer itself (`--containall`, read-only SIF, env passing, Ctrl-C under `srun`);
- arm64; a Linux >= 6.19 kernel; homes on NFS/Lustre (`flock`, mongod on network FS);
- a home produced by the actual Nextflow module (an equivalent `local up` home was used);
- a MongoDB series mismatch (only the matching case and the warning's code path).
