# Commit + Push

Commit current changes (per `/commit` rules) and push the current branch to origin.

## Usage

`/commit-push`

$ARGUMENTS

## Rules

Inherit ALL rules from `/commit`:
- No Claude attribution / trailers / mentions
- Conventional Commits, concise subject, optional short body
- Stage by explicit paths, no `--no-verify`, no `--amend`

## Steps

1. Do everything `/commit` does to produce a clean commit.
2. Determine upstream:
   - `git rev-parse --abbrev-ref --symbolic-full-name @{u}` — if it errors, the branch has no upstream.
3. Push:
   - With upstream: `git push`
   - Without upstream: `git push -u origin <current-branch>`
4. **Never** `git push --force` or `--force-with-lease` unless the user explicitly asks. **Never** push to `main` if the current branch is `main` without confirming first (it is rarely what's intended outside `/bump-version`).
5. Report: branch name, commit SHA + subject, and the remote URL of the branch.
