# Commit + Push + PR

Commit current changes, push the branch, and open a GitHub PR — or update an existing one.

## Usage

`/commit-push-pr` — open new PR if none exists, otherwise update title/body of existing PR for the current branch.

$ARGUMENTS

## Rules

Inherit ALL rules from `/commit` + `/commit-push`:
- No Claude attribution / trailers / mentions in commits
- Conventional Commits, concise subject, optional short body
- Stage by explicit paths, no `--no-verify`, no `--amend`, no force push

**PR-specific rules**:
- **No Claude attribution in PR title or body.** Do NOT include `🤖 Generated with Claude Code`, do NOT mention Claude / "AI" / "session" / "agent".
- **Title**: short (≤ 70 chars), Conventional-Commits-style if it maps to one (`feat: …`, `fix: …`, …). The user's voice — written as if they wrote it.
- **Body**: concise. Prefer a 1–3 bullet `## Summary`. Add `## Test plan` only when there is something non-obvious to verify; otherwise skip it. No long preamble, no AI-generated boilerplate, no emoji clutter.

## Steps

1. Do everything `/commit-push` does (commit + push, set upstream if needed).
2. Detect existing PR for the current branch:
   ```bash
   gh pr view --json number,url,title,body 2>/dev/null
   ```
3. Build a draft title + body from the diff vs. the base branch:
   ```bash
   git log <base>...HEAD --oneline
   git diff <base>...HEAD --stat
   ```
   Read **all** commits on the branch, not just the latest one.
4. Open or update:
   - **No existing PR** → create:
     ```bash
     gh pr create --title "<title>" --body "$(cat <<'EOF'
     ## Summary
     - <bullet>
     - <bullet>
     EOF
     )"
     ```
   - **Existing PR** → update:
     ```bash
     gh pr edit <number> --title "<title>" --body "$(cat <<'EOF'
     ## Summary
     - <bullet>
     - <bullet>
     EOF
     )"
     ```
   Use `--body-file` or HEREDOC; never inline a long body on the command line.
5. Report the PR URL.

## Body templates

**Default (most PRs)**:

```markdown
## Summary
- <what changed, in user's voice>
- <why, if non-obvious>
```

**With test plan (only when reviewer needs to verify something specific)**:

```markdown
## Summary
- <what changed>

## Test plan
- [ ] <concrete verification step>
```

## Anti-examples (do NOT produce)

- Titles like `Implement comprehensive refactoring of the X subsystem to support Y` — too long, narrative
- Body sections like `## Background`, `## Motivation`, `## Implementation Details` with multiple paragraphs — keep it tight
- Anything containing `🤖 Generated with [Claude Code]`, `Co-Authored-By: Claude`, or first-person AI references
