# Commit

Create a single git commit for the current staged/unstaged changes.

## Usage

`/commit` — stage relevant changes and commit with a concise Conventional-Commit message.

$ARGUMENTS

## Rules (strict)

- **No Claude attribution.** Do NOT add `Co-Authored-By: Claude...`, do NOT add the `🤖 Generated with Claude Code` trailer, do NOT mention Claude / "AI" / "session" anywhere in the message body.
- **Author = the user.** Don't override author/committer; let git use the configured identity (Thomas Weber).
- **Conventional Commits format**: `<type>(<optional scope>): <subject>` where type ∈ `feat | fix | chore | refactor | docs | test | perf | build | ci | style`. Subject in lower case, no trailing period, ≤ 72 chars.
- **Body**: optional, only if needed. One short line, or a few bullets. No verbose narrative, no "what/why/how" sections, no test plan.
- **No `--no-verify`**, no `--amend` of existing commits, no skipping pre-commit hooks. If a hook fails, fix the root cause and create a NEW commit.

## Steps

1. Run in parallel: `git status`, `git diff` (staged + unstaged), `git log -10 --oneline` (style reference).
2. Pick the right type from the change kind: new feature → `feat`, bug fix → `fix`, refactor only → `refactor`, deps/tooling/version bumps → `chore`, docs only → `docs`, tests only → `test`.
3. Stage relevant files **explicitly by path** — never `git add -A` / `git add .`. Skip secret-looking files (`.env*`, `*credentials*`, `*token*`) and warn if the user asked to include them.
4. Commit with a HEREDOC so formatting is preserved:

   ```bash
   git commit -m "$(cat <<'EOF'
   <type>(<scope>): <concise subject>

   <optional one-liner or 1–3 short bullets>
   EOF
   )"
   ```

5. Run `git status` afterwards and report the commit SHA + subject.

## Examples of acceptable subjects

- `feat(dash): add multiqc edit modal`
- `fix(api): handle missing token in single-user mode`
- `chore: bump version to 0.9.1`
- `refactor(cli): extract migrate helpers`

## Anti-examples (do NOT produce)

- `feat: implemented a new feature that adds support for X with Y configuration ...` (too long, narrative)
- Anything containing `Claude`, `Anthropic`, `🤖`, `Co-Authored-By: Claude`, or "in this session"
