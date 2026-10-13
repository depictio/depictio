#!/usr/bin/env bash
# k8s_mongo_backup.sh — point-in-time mongodump of a depictio K8s deployment.
#
# Generic across both mongo topologies the depictio helm chart supports:
#   - Percona PSMDB operator (mongo.useOperator: true)  -> pods "<release>-mongo-rs0-N"
#   - self-managed StatefulSet (mongo.useOperator: false) -> pods "<release>-mongo-N"
# and across auth/no-auth (self-managed mode runs without credentials; operator
# mode always has a "<release>-mongo-password" Secret). Not EMBL-specific —
# works against any namespace/release, local minikube included.
#
# It never needs an application-level admin token: it talks to mongod
# directly, so it complements (does not replace) `depictio-cli backup create`,
# which is still the right tool when you also want the S3/Delta data and a
# format the CLI's own `backup restore` can read back.
#
# Usage:
#   k8s_mongo_backup.sh --namespace NS --release RELEASE [options]
#
# Options:
#   --namespace, -n   NS        Kubernetes namespace (required)
#   --release, -r     RELEASE   Helm release name (required)
#   --db              DB        Database to dump (default: depictioDB; pass "" for
#                                all databases — needs a user with admin-level access,
#                                which operator-mode's scoped depictio user lacks)
#   --out-dir         DIR       Where to write the archive (default: ./backups)
#   --context         CTX       kubectl context to use (default: current context)
#   -h, --help                  Show this help
#
# Example:
#   ./k8s_mongo_backup.sh -n datasci-depictio-internal-dev -r devinternal
#   ./k8s_mongo_backup.sh -n datasci-depictio-demo-prod -r demo --db depictioDB

set -euo pipefail

NAMESPACE=""
RELEASE=""
# Operator-mode users are scoped to this one database (can't dump admin/
# local/config), so default to it rather than "all databases". Self-managed
# mode runs unauthenticated and could dump everything, but depictioDB is
# the only database depictio itself ever writes to either way.
DB="depictioDB"
OUT_DIR="./backups"
CONTEXT=""

usage() { sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --namespace|-n) NAMESPACE="$2"; shift 2 ;;
    --release|-r) RELEASE="$2"; shift 2 ;;
    --db) DB="$2"; shift 2 ;;
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    --context) CONTEXT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

if [ -z "$NAMESPACE" ] || [ -z "$RELEASE" ]; then
  echo "error: --namespace and --release are required" >&2
  usage
  exit 1
fi

KCTX=()
[ -n "$CONTEXT" ] && KCTX=(--context "$CONTEXT")
# ${KCTX[@]+"${KCTX[@]}"} (not "${KCTX[@]}") — macOS ships bash 3.2, which
# treats expanding an empty array under `set -u` as an unbound-variable error.
kubectl() { command kubectl ${KCTX[@]+"${KCTX[@]}"} -n "$NAMESPACE" "$@"; }

echo "==> Resolving mongo pod for release '$RELEASE' in '$NAMESPACE'..."
POD=""
for CANDIDATE in "${RELEASE}-mongo-rs0-0" "${RELEASE}-mongo-0"; do
  if kubectl get pod "$CANDIDATE" >/dev/null 2>&1; then
    POD="$CANDIDATE"
    break
  fi
done
if [ -z "$POD" ]; then
  POD="$(kubectl get pods -l "app=mongo,release=${RELEASE}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
fi
if [ -z "$POD" ]; then
  echo "error: no mongo pod found (tried ${RELEASE}-mongo-rs0-0, ${RELEASE}-mongo-0, label app=mongo,release=${RELEASE})" >&2
  exit 1
fi
echo "    pod: $POD"

CONTAINER="$(kubectl get pod "$POD" -o jsonpath='{.spec.containers[0].name}')"
echo "    container: $CONTAINER"

if ! kubectl exec "$POD" -c "$CONTAINER" -- sh -c 'command -v mongodump' >/dev/null 2>&1; then
  echo "error: mongodump not found in $POD/$CONTAINER — this image doesn't bundle the mongo database tools." >&2
  exit 1
fi

SECRET="${RELEASE}-mongo-password"
URI="mongodb://localhost:27017/?readPreference=secondaryPreferred"
if kubectl get secret "$SECRET" >/dev/null 2>&1; then
  echo "    auth: found $SECRET, connecting authenticated"
  # Username isn't in the Secret (chart only stores the password there) —
  # "depictio" is the chart's mongo.auth.username default across every
  # values-*.yaml in this repo. Override with MONGO_USER if yours differs.
  USERNAME="${MONGO_USER:-depictio}"
  PASSWORD="$(kubectl get secret "$SECRET" -o jsonpath='{.data.password}' | base64 -d)"
  # Passed via env into the exec'd shell, never as a CLI arg (would leak into
  # `kubectl get pods -o wide` process listings / shell history on the pod).
  URI="mongodb://${USERNAME}:\${MONGO_PASSWORD}@localhost:27017/?authSource=admin&readPreference=secondaryPreferred"
else
  echo "    auth: no $SECRET Secret — connecting without credentials (self-managed default)"
  PASSWORD=""
fi

DB_FLAG=""
[ -n "$DB" ] && DB_FLAG="--db=$DB"

mkdir -p "$OUT_DIR"
TIMESTAMP="$(kubectl exec "$POD" -c "$CONTAINER" -- date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="${OUT_DIR}/${RELEASE}_${TIMESTAMP}.archive.gz"

echo "==> Dumping $([ -n "$DB" ] && echo "database '$DB'" || echo "all databases") to $OUT_FILE ..."
kubectl exec "$POD" -c "$CONTAINER" --stdin=false -- sh -c \
  "export MONGO_PASSWORD='${PASSWORD}'; mongodump --uri=\"${URI}\" ${DB_FLAG} --archive --gzip" \
  > "$OUT_FILE"

SIZE="$(du -h "$OUT_FILE" | cut -f1)"
echo "==> Done: $OUT_FILE ($SIZE)"
echo
echo "Restore with (against any target, doesn't have to be the same release):"
echo "  kubectl -n <ns> exec -i <mongo-pod> -c <container> -- mongorestore --uri=\"mongodb://<user>:<pass>@localhost:27017/?authSource=admin\" --archive --gzip < $OUT_FILE"
