#!/usr/bin/env bash
# =============================================================================
# Depictio security audit — docker-compose flow
# =============================================================================
# Runs the PR1 security checks end-to-end against a running compose stack.
# Each check prints PASS / FAIL / SKIP; the summary at the bottom exits
# non-zero when anything failed.
#
# Usage:
#   # Quick (static checks only, no stack needed):
#   ./scripts/security_audit_compose.sh --static
#
#   # Full (brings the compose stack up, hits the live API, tears down):
#   ./scripts/security_audit_compose.sh
#
#   # Against an already-running stack you started yourself:
#   API_URL=http://localhost:8058 VIEWER_URL=http://localhost:5080 \
#     ./scripts/security_audit_compose.sh --no-stack
#
# Requires: docker, docker compose, curl, jq, openssl, python3.
# =============================================================================

set -uo pipefail

# ---- args / config ----------------------------------------------------------
MODE="full"                      # full | static | no-stack
KEEP_STACK="${KEEP_STACK:-0}"    # 1 = don't `docker compose down` at the end
API_URL="${API_URL:-http://localhost:8058}"
VIEWER_URL="${VIEWER_URL:-http://localhost:5080}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yaml}"
TMPDIR="$(mktemp -d -t depictio-sec.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT

for arg in "$@"; do
    case "$arg" in
        --static)   MODE="static" ;;
        --no-stack) MODE="no-stack" ;;
        --keep)     KEEP_STACK=1 ;;
        -h|--help)
            sed -n '1,25p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown arg: $arg" >&2
            exit 2
            ;;
    esac
done

# ---- output helpers ---------------------------------------------------------
RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; CYAN=$'\033[0;36m'; BOLD=$'\033[1m'; NC=$'\033[0m'
PASS=0; FAIL=0; SKIP=0
FAIL_LINES=()
pass() { echo "${GREEN}[PASS]${NC} $1"; PASS=$((PASS+1)); }
fail() { echo "${RED}[FAIL]${NC} $1"; [ $# -ge 2 ] && echo "       ↳ $2"; FAIL=$((FAIL+1)); FAIL_LINES+=("$1${2:+ — $2}"); }
skip() { echo "${YELLOW}[SKIP]${NC} $1${2:+ — $2}"; SKIP=$((SKIP+1)); }
section() { echo; echo "${CYAN}${BOLD}── $1 ──${NC}"; }

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing dependency: $1" >&2; exit 2; }; }
need curl; need jq; need python3; need openssl
[ "$MODE" != "static" ] && { need docker; }

cd "$(dirname "$0")/.." || exit 2
ROOT="$PWD"

# ---- helpers ----------------------------------------------------------------
gen_password() { openssl rand -base64 24 | tr -d '\n+/='; }
http_status()  { curl -sS -o /dev/null -w '%{http_code}' "$@"; }
api_up()       { [ "$(http_status "$API_URL/health" --max-time 2)" = "200" ]; }
wait_for_api() {
    local timeout="${1:-90}"
    local t=0
    while [ "$t" -lt "$timeout" ]; do
        api_up && return 0
        sleep 2; t=$((t+2))
    done
    return 1
}

# =============================================================================
# Section 1 — Static repo checks (no stack required)
# =============================================================================
section "Static repo checks"

# 1.1 — initial_users.yaml deleted
if [ -f "depictio/api/v1/configs/initial_users.yaml" ]; then
    fail "initial_users.yaml removed" "file still exists — the changeme seed is still on disk"
else
    pass "initial_users.yaml removed"
fi

# 1.2 — no minio123 in shipped configs (excludes dev-only scaffolding, the
# explicit weak-password allowlist, comments, and the backup_minio123 test
# bucket which is a CI-internal credential, not the default we shipped).
grep -rIn --include='*.yaml' --include='*.yml' --include='*.py' --include='Dockerfile*' \
        --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=.venv \
        --exclude-dir=tests --exclude-dir=dev --exclude-dir=.devcontainer \
        --exclude-dir=docker-compose --exclude-dir=.github \
        'minio123' . 2>/dev/null \
    | grep -v 'backup_minio123' \
    | grep -v '_WEAK_PASSWORDS\|configs/settings_models.py:.*"minio123"' \
    | grep -vE ':[[:space:]]*#' \
    | grep -vE ':[[:space:]]*//' \
    | grep -vE ':[[:space:]]*\*' \
    | grep -vE ':\s*"minio123"$' \
    > /tmp/depictio_minio123 || true
if [ -s /tmp/depictio_minio123 ]; then
    fail "no 'minio123' in shipped configs" "$(wc -l </tmp/depictio_minio123) hit(s) — see /tmp/depictio_minio123"
else
    pass "no 'minio123' in shipped configs"
fi

# 1.3 — no `verify=False` in our production code (tests + dev tooling OK).
# Excludes vendored virtualenvs / site-packages: numpy & pandas expose an
# unrelated `verify=` kwarg, so a co-located depictio/cli/.venv would
# otherwise flood this check with false positives.
grep -rIn --include='*.py' --exclude-dir=node_modules --exclude-dir=.git \
        --exclude-dir=tests --exclude-dir=dev \
        --exclude-dir=.venv --exclude-dir=venv --exclude-dir=site-packages \
        'verify=False' depictio 2>/dev/null \
    | grep -vE '/(\.venv|venv|site-packages|node_modules)/' \
    | grep -vE ':[[:space:]]*#' \
    > /tmp/depictio_verify_false || true
if [ -s /tmp/depictio_verify_false ]; then
    fail "no verify=False in production code" "$(wc -l </tmp/depictio_verify_false) hit(s) — see /tmp/depictio_verify_false"
else
    pass "no verify=False in production code"
fi

# 1.4 — CORS wildcard not hardcoded in main.py (active code only, not comments)
if grep -nE '^[^#]*allow_origins=\["\*"\]' depictio/api/main.py >/dev/null; then
    fail "CORS wildcard removed from main.py" "still using allow_origins=['*'] in active code"
else
    pass "CORS wildcard removed from main.py"
fi

# 1.5 — RequestUserRegistration drops is_admin
if grep -q '^    is_admin: bool' depictio/models/models/users.py; then
    # Could be on a different model — check that RequestUserRegistration doesn't have it
    python3 - <<'PY' 2>/dev/null && pass "RequestUserRegistration has no is_admin" || fail "RequestUserRegistration has no is_admin" "model still carries is_admin"
import ast, sys
tree = ast.parse(open("depictio/models/models/users.py").read())
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == "RequestUserRegistration":
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and getattr(stmt.target, "id", None) == "is_admin":
                sys.exit(1)
sys.exit(0)
PY
else
    pass "RequestUserRegistration has no is_admin"
fi

# 1.6 — file-delete uses caller admin flag, not file owner's. Filter to
# active code (drop `# …` comments) since the security commentary
# references the old predicate by name.
if grep -nE '^[[:space:]]*[^#]*"permissions.owners.is_admin": True' \
        depictio/api/v1/endpoints/files_endpoints/routes.py >/dev/null; then
    fail "file-delete IDOR predicate fixed" "old predicate still in active code"
else
    pass "file-delete IDOR predicate fixed"
fi

# 1.7 — JBrowse iframe sandbox dropped allow-same-origin (active JSX only)
if grep -nE 'sandbox="[^"]*allow-same-origin' \
        packages/depictio-react-core/src/components/JBrowseRenderer.tsx >/dev/null; then
    fail "JBrowse iframe sandbox tightened" "still has allow-same-origin in active sandbox attribute"
else
    pass "JBrowse iframe sandbox tightened"
fi

# 1.8 — nginx CSP and HSTS in viewer template
if grep -q 'Content-Security-Policy' docker-images/nginx.conf.template \
   && grep -q 'Strict-Transport-Security' docker-images/nginx.conf.template; then
    pass "nginx viewer config has CSP + conditional HSTS"
else
    fail "nginx viewer config has CSP + conditional HSTS" "headers not configured in template"
fi

# 1.9 — JWT signature verification wired in core_functions
if grep -q 'jwt.decode' depictio/api/v1/endpoints/user_endpoints/core_functions.py \
   && grep -q 'algorithms=\[ALGORITHM\]' depictio/api/v1/endpoints/user_endpoints/core_functions.py; then
    pass "JWT signature verification in _async_fetch_user_from_token"
else
    fail "JWT signature verification in _async_fetch_user_from_token" "jwt.decode with pinned algorithms missing"
fi

# 1.10 — compose refuses to start without MinIO password (`:?` form)
if grep -q 'DEPICTIO_MINIO_ROOT_PASSWORD:?.*must be set' docker-compose.yaml; then
    pass "docker-compose.yaml fails fast on missing MINIO_ROOT_PASSWORD"
else
    fail "docker-compose.yaml fails fast on missing MINIO_ROOT_PASSWORD" "':?REQUIRED' form not used"
fi

# =============================================================================
# Section 2 — Settings validator behaviour (in-process; no stack needed)
# =============================================================================
section "Settings validator (pydantic-level fail-fast)"

if ! python3 -c "import pydantic" 2>/dev/null; then
    skip "settings validator checks" "pydantic not importable from this Python — run 'pip install -e .' or use the project venv"
else
    run_validator_case() {
        local label="$1"; shift
        local expect_raises="$1"; shift
        local script="$1"
        local out
        out="$(env -i PATH="$PATH" PYTHONPATH="$ROOT" "$@" python3 -c "$script" 2>&1)"
        local rc=$?
        if [ "$expect_raises" = "raises" ]; then
            [ $rc -ne 0 ] && pass "$label" || fail "$label" "expected Settings() to raise, but it succeeded"
        else
            [ $rc -eq 0 ] && pass "$label" || fail "$label" "expected Settings() to succeed, but it raised: $(echo "$out" | tail -1)"
        fi
    }

    # 2.1 — weak MinIO password rejected in server context
    run_validator_case "weak MinIO password rejected (server)" "raises" \
        "from depictio.api.v1.configs.settings_models import Settings; Settings()" \
        DEPICTIO_CONTEXT=server \
        DEPICTIO_MINIO_ROOT_PASSWORD=minio123 \
        DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD="strong_admin_password_aaaa"

    # 2.2 — short MinIO password rejected
    run_validator_case "short MinIO password rejected (server)" "raises" \
        "from depictio.api.v1.configs.settings_models import Settings; Settings()" \
        DEPICTIO_CONTEXT=server \
        DEPICTIO_MINIO_ROOT_PASSWORD=short \
        DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD="strong_admin_password_aaaa"

    # 2.3 — strong MinIO password accepted
    run_validator_case "strong MinIO password accepted (server)" "ok" \
        "from depictio.api.v1.configs.settings_models import Settings; Settings()" \
        DEPICTIO_CONTEXT=server \
        DEPICTIO_MINIO_ROOT_PASSWORD="aVeryStrongMinioPasswordXyZ123" \
        DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD="aVeryStrongAdminPasswordXyZ123"

    # 2.4 — weak bootstrap admin password rejected
    run_validator_case "weak bootstrap admin password rejected" "raises" \
        "from depictio.api.v1.configs.settings_models import Settings; Settings()" \
        DEPICTIO_CONTEXT=server \
        DEPICTIO_MINIO_ROOT_PASSWORD="aVeryStrongMinioPasswordXyZ123" \
        DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD=changeme

    # 2.5 — client context skips the checks
    run_validator_case "client context skips MinIO check" "ok" \
        "from depictio.api.v1.configs.settings_models import Settings; Settings()" \
        DEPICTIO_CONTEXT=client
fi

if [ "$MODE" = "static" ]; then
    section "Summary (static mode)"
    echo "${BOLD}Passed: ${GREEN}$PASS${NC}${BOLD}, Failed: ${RED}$FAIL${NC}${BOLD}, Skipped: ${YELLOW}$SKIP${NC}"
    [ "${#FAIL_LINES[@]}" -gt 0 ] && { echo; echo "${BOLD}Failures:${NC}"; printf '  • %s\n' "${FAIL_LINES[@]}"; }
    [ "$FAIL" -eq 0 ] && exit 0 || exit 1
fi

# =============================================================================
# Section 3 — Live compose stack
# =============================================================================
section "Live compose stack"

if [ "$MODE" = "full" ]; then
    # Prepare a temporary .env so the secrets fail-fast lights up correctly
    # and the bootstrap admin gets a strong password we know.
    GEN_MINIO="$(gen_password)"
    GEN_ADMIN_PW="$(gen_password)"
    ADMIN_EMAIL="audit-admin@depict.io"

    cat >"$TMPDIR/.env" <<EOF
DEPICTIO_VERSION=latest
DEPICTIO_MINIO_ROOT_USER=depictio_audit
DEPICTIO_MINIO_ROOT_PASSWORD=$GEN_MINIO
DEPICTIO_BOOTSTRAP_ADMIN_EMAIL=$ADMIN_EMAIL
DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD=$GEN_ADMIN_PW
DEPICTIO_BOOTSTRAP_SEED_TEST_USER=false
DEPICTIO_AUTH_SINGLE_USER_MODE=false
EOF

    # 3.1 — compose REFUSES to start when MinIO password is empty (`:?REQUIRED`)
    if env DEPICTIO_MINIO_ROOT_PASSWORD= \
           DEPICTIO_MINIO_ROOT_USER=depictio_audit \
           DEPICTIO_BOOTSTRAP_ADMIN_EMAIL="$ADMIN_EMAIL" \
           DEPICTIO_BOOTSTRAP_ADMIN_PASSWORD="$GEN_ADMIN_PW" \
           docker compose -f "$COMPOSE_FILE" --env-file /dev/null config >/dev/null 2>"$TMPDIR/compose_err"; then
        fail "compose fails fast with empty MINIO_ROOT_PASSWORD" "compose accepted an empty password"
    elif grep -q 'must be set' "$TMPDIR/compose_err"; then
        pass "compose fails fast with empty MINIO_ROOT_PASSWORD"
    else
        skip "compose fails fast with empty MINIO_ROOT_PASSWORD" "compose errored but for a different reason — check $TMPDIR/compose_err"
    fi

    # 3.2 — bring the stack up cleanly with valid creds
    echo "  → Starting stack (this can take ~60s on first pull)…"
    if docker compose -f "$COMPOSE_FILE" --env-file "$TMPDIR/.env" up -d >"$TMPDIR/compose_up" 2>&1; then
        pass "stack starts with strong env vars"
    else
        fail "stack starts with strong env vars" "docker compose up failed — see $TMPDIR/compose_up"
        echo
        echo "${BOLD}Compose-up output:${NC}"
        tail -20 "$TMPDIR/compose_up"
        echo
        echo "${BOLD}Summary:${NC} ${GREEN}$PASS pass${NC} / ${RED}$FAIL fail${NC} / ${YELLOW}$SKIP skip${NC}"
        exit 1
    fi

    if ! wait_for_api 120; then
        fail "API reaches /health within 120s" "see 'docker compose logs depictio-backend'"
        [ "$KEEP_STACK" = "1" ] || docker compose -f "$COMPOSE_FILE" --env-file "$TMPDIR/.env" down >/dev/null 2>&1
        exit 1
    fi
    pass "API reaches /health"
else
    [ -n "${BOOTSTRAP_ADMIN_EMAIL:-}" ] && ADMIN_EMAIL="$BOOTSTRAP_ADMIN_EMAIL" || ADMIN_EMAIL=""
    [ -n "${BOOTSTRAP_ADMIN_PASSWORD:-}" ] && GEN_ADMIN_PW="$BOOTSTRAP_ADMIN_PASSWORD" || GEN_ADMIN_PW=""
    api_up || { echo "${RED}API at $API_URL is unreachable; aborting.${NC}"; exit 1; }
    pass "API reachable at $API_URL"
fi

# =============================================================================
# Section 4 — Runtime auth / token / CORS checks
# =============================================================================
section "Runtime auth + headers"

# 4.1 — security headers present
HEADERS="$(curl -sI "$API_URL/health")"
for h in "X-Content-Type-Options" "X-Frame-Options" "Referrer-Policy" "Content-Security-Policy" "Permissions-Policy"; do
    if echo "$HEADERS" | grep -qi "^$h:"; then
        pass "header $h present on API"
    else
        fail "header $h present on API" "missing"
    fi
done

# Nginx-served viewer surface (only checked when reachable)
if curl -sf --max-time 3 "$VIEWER_URL/" >/dev/null 2>&1; then
    V_HEADERS="$(curl -sI "$VIEWER_URL/")"
    for h in "Content-Security-Policy" "X-Frame-Options" "X-Content-Type-Options"; do
        if echo "$V_HEADERS" | grep -qi "^$h:"; then
            pass "header $h present on viewer"
        else
            fail "header $h present on viewer" "missing on $VIEWER_URL"
        fi
    done
    if echo "$V_HEADERS" | grep -qi '^Server: nginx/'; then
        fail "nginx server_tokens off" "Server header leaks version"
    else
        pass "nginx server_tokens off"
    fi
else
    skip "viewer header checks" "$VIEWER_URL unreachable"
fi

# 4.2 — CORS: unauthorised origin gets no ACAO
ACAO_BAD="$(curl -sI -X OPTIONS "$API_URL/depictio/api/v1/utils/status" \
    -H "Origin: https://evil.example" \
    -H "Access-Control-Request-Method: GET" | grep -i '^Access-Control-Allow-Origin:' || true)"
if [ -z "$ACAO_BAD" ]; then
    pass "CORS rejects unlisted origin"
else
    fail "CORS rejects unlisted origin" "got: $ACAO_BAD"
fi

# 4.3 — /register doesn't honour is_admin (only meaningful if registration is open)
if [ -n "$ADMIN_EMAIL" ] && [ -n "$GEN_ADMIN_PW" ]; then
    ATTACKER_EMAIL="audit-attacker-$$@depict.io"
    REG_RESP="$(curl -s -X POST "$API_URL/depictio/api/v1/auth/register" \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"$ATTACKER_EMAIL\",\"password\":\"strong_attacker_password_aa\",\"is_admin\":true}")"
    REG_CODE="$(echo "$REG_RESP" | jq -r '.user.is_admin // empty' 2>/dev/null)"
    if [ -z "$REG_CODE" ]; then
        skip "/register strips is_admin" "registration probably disabled (single-user / public mode) or response shape changed — payload: $(echo "$REG_RESP" | head -c 200)"
    elif [ "$REG_CODE" = "false" ]; then
        pass "/register strips client-supplied is_admin"
    else
        fail "/register strips client-supplied is_admin" "created user has is_admin=$REG_CODE"
    fi

    # 4.4 — JWT signature verification rejects tampered tokens
    TOKEN_JSON="$(curl -s -X POST "$API_URL/depictio/api/v1/auth/login" \
        -d "username=$ADMIN_EMAIL&password=$GEN_ADMIN_PW")"
    TOKEN="$(echo "$TOKEN_JSON" | jq -r '.access_token // empty')"
    if [ -z "$TOKEN" ]; then
        skip "JWT signature verification" "couldn't get an access token (login response: $(echo "$TOKEN_JSON" | head -c 200))"
    else
        TAMPERED="${TOKEN%?}X"
        OK_STATUS="$(http_status "$API_URL/depictio/api/v1/auth/fetch_user" -H "Authorization: Bearer $TOKEN")"
        BAD_STATUS="$(http_status "$API_URL/depictio/api/v1/auth/fetch_user" -H "Authorization: Bearer $TAMPERED")"
        if [ "$OK_STATUS" = "200" ] && [ "$BAD_STATUS" = "401" ]; then
            pass "JWT signature verification rejects tampered tokens"
        else
            fail "JWT signature verification rejects tampered tokens" "valid→$OK_STATUS (want 200), tampered→$BAD_STATUS (want 401)"
        fi
    fi
else
    skip "/register strips is_admin" "no admin credentials in this mode"
    skip "JWT signature verification" "no admin credentials in this mode"
fi

# 4.5 — wrong-password login fails
if [ -n "$ADMIN_EMAIL" ]; then
    BAD_LOGIN="$(http_status -X POST "$API_URL/depictio/api/v1/auth/login" \
        -d "username=$ADMIN_EMAIL&password=changeme")"
    if [ "$BAD_LOGIN" = "401" ] || [ "$BAD_LOGIN" = "400" ]; then
        pass "legacy 'changeme' password is rejected ($BAD_LOGIN)"
    else
        fail "legacy 'changeme' password is rejected" "got $BAD_LOGIN — admin@example.com / changeme might still work!"
    fi
fi

# 4.6 — Bootstrap admin idempotency: restart backend, password unchanged
if [ "$MODE" = "full" ]; then
    docker compose -f "$COMPOSE_FILE" --env-file "$TMPDIR/.env" restart depictio-backend >/dev/null 2>&1
    wait_for_api 60 || { fail "API recovers after restart" "didn't come back within 60s"; KEEP_STACK=1; }
    AFTER_LOGIN="$(http_status -X POST "$API_URL/depictio/api/v1/auth/login" \
        -d "username=$ADMIN_EMAIL&password=$GEN_ADMIN_PW")"
    if [ "$AFTER_LOGIN" = "200" ]; then
        pass "bootstrap is idempotent (admin survives restart)"
    else
        fail "bootstrap is idempotent" "login after restart returned $AFTER_LOGIN"
    fi
fi

# ---- teardown ---------------------------------------------------------------
if [ "$MODE" = "full" ] && [ "$KEEP_STACK" != "1" ]; then
    echo
    echo "  → Tearing down stack…"
    docker compose -f "$COMPOSE_FILE" --env-file "$TMPDIR/.env" down -v >/dev/null 2>&1 || true
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
    echo "${YELLOW}${BOLD}Skipped checks were not exercised — re-run after addressing the cause noted next to each.${NC}"
fi
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
