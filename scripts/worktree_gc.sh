#!/usr/bin/env bash
# Reclaim the disk a git worktree keeps after its branch is done: virtualenvs,
# node_modules and the per-instance data/ directory (several GB each once the showcases
# are seeded). The worktree itself is kept unless --remove is given.
#
#   scripts/worktree_gc.sh                 dry run: list what could be reclaimed and why
#   scripts/worktree_gc.sh --apply         delete the heavy directories of those worktrees
#   scripts/worktree_gc.sh --apply --remove   also `git worktree remove` the merged ones
#
# A worktree is a candidate when its branch is merged into origin/main, or its upstream is
# gone (squash-merged and deleted), or its last commit is older than --days (default 14).
# It is never touched when it is the main checkout, the one you run this from, dirty, ahead
# of its upstream, or has a process running from inside it.
#
# Options: --days N   idle threshold      --no-fetch   skip `git fetch --prune`
set -euo pipefail

DAYS=14
APPLY=0
REMOVE=0
FETCH=1
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --remove) REMOVE=1 ;;
    --no-fetch) FETCH=0 ;;
    --days) DAYS="${2:?--days needs a number}"; shift ;;
    -h | --help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

# Heavy directories, relative to a worktree root. Nothing else is ever deleted.
HEAVY=(.venv venv depictio/cli/.venv node_modules depictio/viewer/node_modules data)

here="$(git rev-parse --show-toplevel)"
main="$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')"
if [ "$FETCH" = 1 ]; then git fetch --prune origin >/dev/null 2>&1 || true; fi

human() { awk -v k="$1" 'BEGIN{ s=k*1024; split("B KB MB GB TB",u); i=1; while (s>=1024 && i<5) { s/=1024; i++ } printf "%.1f%s", s, u[i] }'; }

heavy_kb() { # total size in KB of the heavy dirs present in $1
  local wt="$1" total=0 d kb
  for d in "${HEAVY[@]}"; do
    [ -d "$wt/$d" ] || continue
    kb="$(du -sk "$wt/$d" 2>/dev/null | cut -f1)"
    total=$((total + ${kb:-0}))
  done
  echo "$total"
}

reason_for() { # prints why $1 (path) / $2 (branch) is reclaimable, or nothing
  local wt="$1" br="$2" track last age
  if git -C "$wt" merge-base --is-ancestor HEAD origin/main 2>/dev/null; then
    echo "merged into origin/main"; return
  fi
  track="$(git for-each-ref --format='%(upstream:track)' "refs/heads/$br" 2>/dev/null || true)"
  if [ "$track" = "[gone]" ]; then echo "upstream deleted"; return; fi
  last="$(git -C "$wt" log -1 --format=%ct 2>/dev/null || echo 0)"
  age=$(( ($(date +%s) - last) / 86400 ))
  if [ "$age" -ge "$DAYS" ]; then echo "idle ${age} days"; fi
}

blocker_for() { # prints why $1 must not be touched, or nothing
  local wt="$1" br="$2" ahead
  [ "$wt" = "$main" ] && { echo "main checkout"; return; }
  [ "$wt" = "$here" ] && { echo "current worktree"; return; }
  # Tracked changes only: the heavy directories themselves show up as untracked in a
  # repo that does not ignore them, and `git worktree remove` refuses on its own when
  # anything untracked is left.
  if [ -n "$(git -C "$wt" status --porcelain --untracked-files=no 2>/dev/null)" ]; then echo "uncommitted changes"; return; fi
  if git rev-parse --verify -q "$br@{upstream}" >/dev/null 2>&1; then
    ahead="$(git rev-list --count "$br@{upstream}..$br" 2>/dev/null || echo 0)"
    [ "$ahead" -gt 0 ] && { echo "$ahead unpushed commit(s)"; return; }
  fi
  # A running server or watcher started from inside the worktree.
  if pgrep -f -- "$wt/" >/dev/null 2>&1; then echo "a process runs from it"; return; fi
}

total_kb=0
printf '%-44s %9s  %s\n' WORKTREE RECLAIM WHY
wt="" br=""
while IFS= read -r line; do
  case "$line" in
    "worktree "*) wt="${line#worktree }"; br="" ;;
    "branch "*) br="${line#branch refs/heads/}" ;;
    "")
      if [ -n "$wt" ] && [ -n "$br" ]; then
        name="$(basename "$wt")"
        blocker="$(blocker_for "$wt" "$br")"
        if [ -n "$blocker" ]; then
          printf '%-44s %9s  skipped: %s\n' "$name" - "$blocker"
        else
          why="$(reason_for "$wt" "$br")"
          if [ -n "$why" ]; then
            kb="$(heavy_kb "$wt")"
            total_kb=$((total_kb + kb))
            printf '%-44s %9s  %s\n' "$name" "$(human "$kb")" "$why"
            if [ "$APPLY" = 1 ]; then
              for d in "${HEAVY[@]}"; do
                [ -d "$wt/$d" ] && rm -rf -- "${wt:?}/$d"
              done
              # Only a finished branch is removed, never one that is merely idle.
              if [ "$REMOVE" = 1 ]; then
                case "$why" in
                  merged* | "upstream deleted") git worktree remove "$wt" && echo "  removed worktree $name" ;;
                esac
              fi
            fi
          fi
        fi
      fi
      wt="" br=""
      ;;
  esac
done < <(git worktree list --porcelain; echo)

if [ "$APPLY" = 1 ]; then
  echo "reclaimed ~$(human "$total_kb")"
else
  echo "reclaimable ~$(human "$total_kb")  (dry run: add --apply to delete)"
fi
