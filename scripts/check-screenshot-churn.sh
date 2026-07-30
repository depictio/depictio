#!/usr/bin/env bash
# Block accidental commits of the shipped default dashboard thumbnails.
#
# depictio/api/static/screenshots/ holds the default thumbnails that a fresh
# deployment seeds into the screenshots PVC (see the copy-screenshot-files init
# container in helm-charts/depictio/templates/deployments.yaml). Running a local
# stack regenerates them in place, so they surface as modified files during
# unrelated work and get swept into feature commits.
#
# That is not hypothetical: 55db1a16 ("feat(realtime): full-width timeline
# footer, table column control, and dashboard layout polish") shipped 64
# thumbnails captured against un-ingested data collections — red "required data
# collection(s) were not ingested" banners and "Failed to render ... DC has no
# materialised Delta table" instead of plots — as the defaults for every new
# deployment, and it stayed that way for over a week.
#
# Regenerating is legitimate, it just has to be deliberate. Opt in with:
#
#   DEPICTIO_ALLOW_SCREENSHOT_UPDATE=1 git commit ...
#
# and only after confirming the dashboards actually render with data.
set -euo pipefail

if [ "${DEPICTIO_ALLOW_SCREENSHOT_UPDATE:-0}" != "0" ]; then
    exit 0
fi

SCREENSHOT_DIR="depictio/api/static/screenshots"

staged=$(git diff --cached --name-only --diff-filter=ACM -- "$SCREENSHOT_DIR")

if [ -z "$staged" ]; then
    exit 0
fi

count=$(printf '%s\n' "$staged" | wc -l | tr -d '[:space:]')

echo "Blocked: ${count} default dashboard thumbnail(s) staged."
echo
printf '%s\n' "$staged" | sed 's/^/  /'
echo
echo "These ship as the default thumbnails for every fresh deployment, and a local"
echo "stack rewrites them in place, so they are usually unintended churn."
echo
echo "If the update IS intended, verify the dashboards render with data, then:"
echo "  DEPICTIO_ALLOW_SCREENSHOT_UPDATE=1 git commit ..."
echo
echo "Otherwise drop the churn:"
echo "  git restore --source origin/main --staged --worktree -- ${SCREENSHOT_DIR}"
exit 1
