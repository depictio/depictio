#!/usr/bin/env bash
# =============================================================================
# Depictio security audit — Helm chart flow
# =============================================================================
# Renders the chart with `helm template` and runs static security checks
# against the resulting manifests. Optionally renders against a specific
# values file (e.g. values-embl-demo.yaml) so EMBL-demo-shaped deployments
# get audited too.
#
# Usage:
#   ./scripts/security_audit_helm.sh                          # default values.yaml
#   ./scripts/security_audit_helm.sh -f values-embl-demo.yaml # add an env values file
#   ./scripts/security_audit_helm.sh -f values-embl-demo.yaml -f values-embl-demo-base.yaml
#
# All -f paths are resolved relative to helm-charts/depictio/.
#
# Requires: helm, yq (mikefarah variant), grep, awk.
# =============================================================================

set -uo pipefail

CHART_DIR="$(cd "$(dirname "$0")/../helm-charts/depictio" && pwd)"
VALUES_FLAGS=()
RELEASE="audit"
NAMESPACE="audit-ns"

while [ $# -gt 0 ]; do
    case "$1" in
        -f|--values)
            [ -z "${2:-}" ] && { echo "Missing path after $1" >&2; exit 2; }
            VALUES_FLAGS+=("-f" "$CHART_DIR/$2")
            shift 2
            ;;
        --release) RELEASE="$2"; shift 2 ;;
        --namespace) NAMESPACE="$2"; shift 2 ;;
        -h|--help) sed -n '1,20p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; CYAN=$'\033[0;36m'; BOLD=$'\033[1m'; NC=$'\033[0m'
PASS=0; FAIL=0; SKIP=0
FAIL_LINES=()
pass() { echo "${GREEN}[PASS]${NC} $1"; PASS=$((PASS+1)); }
fail() { echo "${RED}[FAIL]${NC} $1"; [ $# -ge 2 ] && echo "       ↳ $2"; FAIL=$((FAIL+1)); FAIL_LINES+=("$1${2:+ — $2}"); }
skip() { echo "${YELLOW}[SKIP]${NC} $1${2:+ — $2}"; SKIP=$((SKIP+1)); }
section() { echo; echo "${CYAN}${BOLD}── $1 ──${NC}"; }

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing dependency: $1" >&2; exit 2; }; }
need helm
HAS_YQ=0
command -v yq >/dev/null 2>&1 && HAS_YQ=1

MANIFESTS="$(mktemp -t depictio-helm.XXXXXX.yaml)"
trap 'rm -f "$MANIFESTS"' EXIT

echo "${BOLD}Chart:${NC}      $CHART_DIR"
echo "${BOLD}Release:${NC}    $RELEASE"
echo "${BOLD}Namespace:${NC}  $NAMESPACE"
if [ ${#VALUES_FLAGS[@]} -gt 0 ]; then
    echo "${BOLD}Overrides:${NC}  ${VALUES_FLAGS[*]}"
else
    echo "${BOLD}Overrides:${NC}  (defaults from values.yaml only)"
fi

# Render
if ! helm template "$RELEASE" "$CHART_DIR" \
        --namespace "$NAMESPACE" \
        "${VALUES_FLAGS[@]}" \
        > "$MANIFESTS" 2>/tmp/helm-render.err; then
    echo "${RED}helm template failed:${NC}"
    cat /tmp/helm-render.err
    exit 1
fi
echo "${BOLD}Rendered manifests:${NC} $MANIFESTS  ($(wc -l <"$MANIFESTS") lines)"

# =============================================================================
# Section 1 — Secret hygiene (passwords must live in Secrets, never ConfigMaps)
# =============================================================================
section "Secret hygiene"

# helper: print a block surrounding a match, used for context-aware grep
find_blocks_kind() {
    # $1 = literal string to search for; prints "kind: <Kind>" of each enclosing doc
    awk -v needle="$1" '
        BEGIN { RS=""; FS="\n" }
        { for (i=1; i<=NF; i++) if (index($i, needle)) {
            kind="(unknown)"
            for (j=1; j<=NF; j++) if (match($j, /^kind: /)) { kind=substr($j, 7); break }
            print kind; next
        }}' "$MANIFESTS"
}

# 1.1 — MinIO root password never lands in a ConfigMap
HITS_CM_MINIO_PW=$(find_blocks_kind 'MINIO_ROOT_PASSWORD' | grep -c '^ConfigMap$' || true)
if [ "$HITS_CM_MINIO_PW" -eq 0 ]; then
    pass "MINIO_ROOT_PASSWORD not in any ConfigMap"
else
    fail "MINIO_ROOT_PASSWORD not in any ConfigMap" "$HITS_CM_MINIO_PW ConfigMap(s) still contain it"
fi

# 1.2 — Bootstrap admin password never lands in a ConfigMap
HITS_CM_BOOT_PW=$(find_blocks_kind 'DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD' | grep -c '^ConfigMap$' || true)
if [ "$HITS_CM_BOOT_PW" -eq 0 ]; then
    pass "DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD not in any ConfigMap"
else
    fail "DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD not in any ConfigMap" "$HITS_CM_BOOT_PW hit(s)"
fi

# 1.3 — MinIO root creds DO appear in a Secret
HITS_SECRET=$(find_blocks_kind 'MINIO_ROOT_PASSWORD' | grep -c '^Secret$' || true)
if [ "$HITS_SECRET" -ge 1 ]; then
    pass "MINIO_ROOT_PASSWORD lives in a Secret"
else
    fail "MINIO_ROOT_PASSWORD lives in a Secret" "no Secret carries the MinIO root password — wiring missing"
fi

# 1.4 — Bootstrap admin creds DO appear in a Secret
HITS_SECRET_BOOT=$(find_blocks_kind 'DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD' | grep -c '^Secret$' || true)
if [ "$HITS_SECRET_BOOT" -ge 1 ]; then
    pass "DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD lives in a Secret"
else
    fail "DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD lives in a Secret" "Secret template missing the bootstrap admin field"
fi

# 1.5 — backend Deployment references the bootstrap secret
if grep -q 'DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD' "$MANIFESTS" \
   && grep -A4 'DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD' "$MANIFESTS" | grep -q 'secretKeyRef'; then
    pass "backend Deployment reads DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD via secretKeyRef"
else
    fail "backend Deployment reads DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD via secretKeyRef" "wire-up missing"
fi

# 1.6 — known weak defaults must not appear ANYWHERE in the rendered output
if grep -q '"minio123"' "$MANIFESTS" 2>/dev/null || grep -q ': minio123$' "$MANIFESTS" 2>/dev/null; then
    fail "no literal 'minio123' anywhere in render" "default leaked"
else
    pass "no literal 'minio123' in render"
fi
if grep -qiE '(password|secret).*changeme' "$MANIFESTS"; then
    fail "no 'changeme' password in render" "default leaked"
else
    pass "no 'changeme' password in render"
fi

# =============================================================================
# Section 2 — Image hygiene (no :latest on data-plane services)
# =============================================================================
section "Image pinning"

check_image_pin() {
    local svc="$1"; local re="$2"
    local images
    images=$(grep -oE "image: \"?${re}[^\" ]*" "$MANIFESTS" | head -3)
    if [ -z "$images" ]; then
        skip "$svc image is pinned" "not present in render"
        return
    fi
    if echo "$images" | grep -qE ':(latest|main|next)(\"|$)'; then
        fail "$svc image is pinned" "uses mutable tag: $(echo "$images" | head -1)"
    else
        pass "$svc image is pinned ($(echo "$images" | head -1 | awk '{print $NF}'))"
    fi
}

check_image_pin "mongo"  "mongo"
check_image_pin "minio"  "minio/minio"
check_image_pin "redis"  "redis"

# Backend / viewer / worker — usually pinned by the chart's Chart.yaml version,
# but flag :latest if it sneaks in via overrides:
for svc in depictio-api depictio-viewer depictio-worker; do
    check_image_pin "$svc" "ghcr.io/depictio/$svc"
done

# =============================================================================
# Section 3 — Pod security (runAsNonRoot, capability drop)
# =============================================================================
section "Pod security context"

if [ "$HAS_YQ" -eq 1 ]; then
    # Per-Deployment / StatefulSet check that runAsNonRoot is true and ALL caps dropped.
    for kind in Deployment StatefulSet; do
        yq -r 'select(.kind == "'"$kind"'") | .metadata.name + "|" + (.spec.template.spec.containers[0].securityContext.runAsNonRoot // "missing" | tostring) + "|" + (.spec.template.spec.containers[0].securityContext.capabilities.drop // [] | join(","))' \
            "$MANIFESTS" 2>/dev/null | while IFS='|' read -r name nonroot caps; do
            [ -z "$name" ] && continue
            # Mongo + MinIO are the historical offenders
            case "$name" in
                *mongo*|*minio*|*backend*|*viewer*|*celery*)
                    if [ "$nonroot" = "true" ]; then
                        echo "${GREEN}[PASS]${NC} $name runs as non-root"; PASS=$((PASS+1))
                    else
                        echo "${RED}[FAIL]${NC} $name runs as non-root — runAsNonRoot=$nonroot"; FAIL=$((FAIL+1))
                        FAIL_LINES+=("$name runs as non-root — runAsNonRoot=$nonroot")
                    fi
                    if echo ",$caps," | grep -q ',ALL,'; then
                        echo "${GREEN}[PASS]${NC} $name drops ALL capabilities"; PASS=$((PASS+1))
                    else
                        echo "${RED}[FAIL]${NC} $name drops ALL capabilities — got: ${caps:-none}"; FAIL=$((FAIL+1))
                        FAIL_LINES+=("$name drops ALL capabilities — got: ${caps:-none}")
                    fi
                    ;;
            esac
        done
    done
else
    skip "per-pod runAsNonRoot / capabilities" "install 'yq' (mikefarah) to enable structured checks"
fi

# =============================================================================
# Section 4 — Ingress / TLS
# =============================================================================
section "Ingress"

INGRESS_COUNT=$(grep -c '^kind: Ingress$' "$MANIFESTS" || true)
if [ "$INGRESS_COUNT" -eq 0 ]; then
    skip "Ingress TLS configured" "no Ingress objects in this render"
else
    # Each Ingress should have a tls: block with at least one host
    TLSLESS=0
    if [ "$HAS_YQ" -eq 1 ]; then
        TLSLESS=$(yq -r 'select(.kind == "Ingress") | .metadata.name + "|" + ((.spec.tls // []) | length | tostring)' "$MANIFESTS" \
                  | awk -F'|' '$2 == "0" {print $1}' | wc -l)
        if [ "$TLSLESS" -eq 0 ]; then
            pass "every Ingress has at least one tls entry"
        else
            fail "every Ingress has at least one tls entry" "$TLSLESS ingress(es) ship without TLS — risk of plain-HTTP traffic"
        fi
    else
        skip "ingress TLS check" "install 'yq' for structured ingress audit"
    fi
fi

# =============================================================================
# Section 5 — Wipe-job lockdown (EMBL demo chain)
# =============================================================================
section "Wipe job"

WIPE_JOB_PRESENT=$(grep -c 'name: .*wipe-job' "$MANIFESTS" || true)
if [ "$WIPE_JOB_PRESENT" -eq 0 ]; then
    skip "wipe-job audit" "wipe job not active in this values combination"
else
    # If autoWipeOnUpgrade is enabled, ensure the chart still expects bootstrap
    # creds from the Secret (so the next boot doesn't reseed defaults).
    if grep -q 'DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD' "$MANIFESTS"; then
        pass "wipe-job + bootstrap admin secret wired together"
    else
        fail "wipe-job + bootstrap admin secret wired together" "autoWipeOnUpgrade is on but the bootstrap secret isn't templated"
    fi
fi

# =============================================================================
# Final report
# =============================================================================
section "Summary"
echo "${BOLD}Passed: ${GREEN}$PASS${NC}${BOLD}, Failed: ${RED}$FAIL${NC}${BOLD}, Skipped: ${YELLOW}$SKIP${NC}"
if [ "${#FAIL_LINES[@]}" -gt 0 ]; then
    echo
    echo "${BOLD}What still needs to be done:${NC}"
    printf '  • %s\n' "${FAIL_LINES[@]}"
fi
if [ "$SKIP" -gt 0 ]; then
    echo
    echo "${YELLOW}${BOLD}Skipped checks were not exercised. Causes:${NC}"
    echo "  • install yq (mikefarah) for structured manifest analysis"
    echo "  • some checks depend on a specific values file — re-run with -f"
fi
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
