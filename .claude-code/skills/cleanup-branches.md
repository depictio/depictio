# Cleanup Branches

Clean up stale, merged, and deleted branches to maintain a tidy Git repository.

## Usage

When the repository has accumulated many old branches, use this skill to safely clean them up.

## Branch Cleanup Types

### 1. Merged Branches

Branches that have been merged into main/master.

```bash
# List merged branches
git branch --merged main

# Delete merged branches (except main/master)
git branch --merged main | grep -v "^\*\|main\|master" | xargs -r git branch -d
```

### 2. Gone Branches

Local branches tracking deleted remote branches (marked as [gone]).

```bash
# List gone branches
git branch -vv | grep ': gone]'

# Delete gone branches
git branch -vv | grep ': gone]' | awk '{print $1}' | xargs -r git branch -D
```

### 3. Stale Remote Branches

Remote tracking branches that no longer exist.

```bash
# List stale remote branches
git remote prune origin --dry-run

# Remove stale remote branches
git remote prune origin
```

### 4. Old Local Branches

Branches that haven't been updated in a long time.

```bash
# List branches by last commit date
git for-each-ref --sort=-committerdate refs/heads/ --format='%(committerdate:short) %(refname:short)'

# Interactive cleanup (review and delete old ones)
```

## Complete Cleanup Workflow

### Safe Cleanup Process

1. **Update repository**:
   ```bash
   git fetch --all --prune
   ```

2. **List current branches**:
   ```bash
   git branch -a
   ```

3. **Identify branches to clean**:
   ```bash
   # Merged branches
   git branch --merged main

   # Gone branches
   git branch -vv | grep ': gone]'

   # Stale remote tracking
   git remote prune origin --dry-run
   ```

4. **Clean up gone branches**:
   ```bash
   git branch -vv | grep ': gone]' | awk '{print $1}' | xargs -r git branch -D
   ```

5. **Clean up merged branches**:
   ```bash
   git branch --merged main | grep -v "^\*\|main\|master" | xargs -r git branch -d
   ```

6. **Clean up remote tracking**:
   ```bash
   git remote prune origin
   ```

7. **Verify cleanup**:
   ```bash
   git branch -a
   ```

## Process for Using This Skill

1. **Assess current state**:
   - Check current branch
   - List all branches
   - Identify cleanup candidates

2. **Safety checks**:
   - Ensure no uncommitted changes
   - Ensure current branch is main or safe branch
   - Backup any branches with important work

3. **Execute cleanup**:
   - Start with remote prune (safest)
   - Then gone branches (already deleted remotely)
   - Then merged branches (already integrated)
   - Carefully consider old unmerged branches

4. **Verify results**:
   - List remaining branches
   - Confirm important branches kept
   - Check nothing unexpected was deleted

## Safety Guidelines

### Before Cleaning

1. **Check current branch**:
   ```bash
   git branch --show-current
   ```
   - Should be on `main` or a safe branch

2. **Check for uncommitted changes**:
   ```bash
   git status
   ```
   - Should be clean

3. **Update from remote**:
   ```bash
   git fetch --all --prune
   ```

### What NOT to Delete

- **Current branch** (marked with *)
- **main/master** branches
- **Development branches** with uncommitted work
- **Release branches** (release/*)
- **Hotfix branches** (hotfix/*)
- **Protected branches** (check repo settings)

### Dry-Run Mode

Always check what will be deleted first:

```bash
# Dry run for merged branches
git branch --merged main | grep -v "^\*\|main\|master"

# Dry run for gone branches
git branch -vv | grep ': gone]'

# Dry run for remote prune
git remote prune origin --dry-run
```

## Common Cleanup Scenarios

### Post-PR Cleanup

After PR is merged:

```bash
# Switch to main
git checkout main

# Pull latest
git pull

# Delete feature branch
git branch -d feature/branch-name

# Cleanup any gone branches
git branch -vv | grep ': gone]' | awk '{print $1}' | xargs -r git branch -D
```

### Weekly Maintenance

Regular cleanup:

```bash
# Update repository
git fetch --all --prune

# Clean gone branches
git branch -vv | grep ': gone]' | awk '{print $1}' | xargs -r git branch -D

# Clean merged branches
git branch --merged main | grep -v "^\*\|main\|master" | xargs -r git branch -d

# Clean remote tracking
git remote prune origin
```

### Pre-Release Cleanup

Before release:

```bash
# Update from remote
git fetch --all --prune

# List all branches
git branch -a

# Clean up merged feature branches
git branch --merged main | grep -v "^\*\|main\|master\|release\|hotfix" | xargs -r git branch -d

# Remove stale remote tracking
git remote prune origin
```

## Advanced Cleanup

### Delete Old Branches (Interactive)

For branches older than 3 months:

```bash
# List branches older than 3 months
git for-each-ref --sort=-committerdate refs/heads/ \
  --format='%(committerdate:short) %(refname:short)' | \
  awk -v date="$(date -d '3 months ago' +%Y-%m-%d)" '$1 < date {print $2}'

# Review and delete manually
git branch -D old-branch-name
```

### Worktree Cleanup

If using git worktrees:

```bash
# List worktrees
git worktree list

# Remove stale worktrees
git worktree prune

# Remove specific worktree
git worktree remove /path/to/worktree
```

### Force Delete Unmerged Branches

Use carefully! Only for branches you're certain about:

```bash
# Force delete specific branch
git branch -D branch-name

# Force delete multiple branches
git branch -D branch1 branch2 branch3
```

## Error Handling

**"Cannot delete current branch"**:
- Switch to a different branch first
- Usually switch to `main`: `git checkout main`

**"Branch not fully merged"**:
- Verify branch should be deleted
- Use `-D` instead of `-d` if certain
- Or merge the branch first

**"No such branch"**:
- Branch already deleted
- Check branch name spelling
- List branches to verify: `git branch -a`

**"Branch has uncommitted changes"** (for worktree):
- Commit or stash changes
- Or use `git worktree remove --force`

## Automation Ideas

### Pre-commit Hook

Add to `.git/hooks/pre-commit`:

```bash
#!/bin/bash
# Auto-cleanup gone branches before commit
git branch -vv | grep ': gone]' | awk '{print $1}' | xargs -r git branch -D
```

### Scheduled Cleanup

Add to cron or task scheduler:

```bash
# Weekly cleanup (every Monday)
0 9 * * 1 cd /path/to/repo && git fetch --all --prune && git branch -vv | grep ': gone]' | awk '{print $1}' | xargs -r git branch -D
```

## Integration with Other Skills

- Run before `/bump-version` to clean state
- Run after `/create-pr` and merge
- Part of `/release-workflow` preparation
- Regular maintenance task

## Quick Reference

```bash
# Full cleanup (safe)
git fetch --all --prune
git branch -vv | grep ': gone]' | awk '{print $1}' | xargs -r git branch -D
git branch --merged main | grep -v "^\*\|main\|master" | xargs -r git branch -d
git remote prune origin

# List branches by age
git for-each-ref --sort=-committerdate refs/heads/ --format='%(committerdate:short) %(refname:short)'

# Count branches
git branch -a | wc -l

# List remote branches
git branch -r

# Delete remote branch
git push origin --delete branch-name
```

## Best Practices

1. **Regular cleanup**: Weekly or after each PR merge
2. **Stay on main**: Switch to main before cleanup
3. **Use dry-run**: Always check what will be deleted
4. **Keep release branches**: Don't delete version branches
5. **Document exceptions**: Note which branches to always keep
6. **Automate when safe**: Automate gone branch cleanup
7. **Backup before force delete**: Be cautious with `-D` flag
